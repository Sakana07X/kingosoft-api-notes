"""课表：学期、单周、天桶归一、今日课程、班级反查。

结构要点（细节见 docs/02-timetable.md）：
  - 一次只拿一周；响应顶层挂 `week1`..`week7` = 周一到周日（不是第 1~7 周）
  - 周次用顶层「第 1 周周一」的日期算，不靠猜
  - 排课计划串（`3-15周` 之类）只能展示，不能用来过滤
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from .client import Client

DAY_KEYS = {i: f"week{i}" for i in range(1, 8)}  # 1=周一 … 7=周日


def _first(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _parse_date(text: Any) -> date | None:
    s = _first(text)[:10]
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


@dataclass
class Course:
    """一门课的一次排课。`skbjdm` 与 `jc_str` 是签到接口的必需入参。"""

    kcmc: str = ""
    kcdm: str = ""
    skbjdm: str = ""
    skbjmc: str = ""
    jc_str: str = ""          # 节次区间串，如 "3-4"；必须原样传给签到接口
    jcdm: str = ""
    teacher: str = ""
    room: str = ""
    zc: str = ""
    day: int = 0              # 1=周一 … 7=周日
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_raw(cls, obj: dict[str, Any], day: int) -> Course:
        return cls(
            kcmc=_first(obj.get("kcmc")),
            kcdm=_first(obj.get("kcdm")),
            skbjdm=_first(obj.get("skbjdm")),
            skbjmc=_first(obj.get("skbjmc")),
            jc_str=_first(obj.get("jcxx") or obj.get("jc")),
            jcdm=_first(obj.get("jcdm")),
            teacher=_first(obj.get("jsxm") or obj.get("teacher")),
            room=_first(obj.get("jsmc") or obj.get("room") or obj.get("cdmc")),
            zc=_first(obj.get("zc")),
            day=day,
            raw=obj,
        )


@dataclass
class WeekTable:
    week: int
    qssj: str = ""                     # 第 1 周周一
    maxzc: int = 0
    days: dict[int, list[Course]] = field(default_factory=dict)

    def today(self, on: date | None = None) -> list[Course]:
        """只取今天那一桶，不做任何过滤。"""
        d = on or date.today()
        return self.days.get(d.isoweekday(), [])

    def all_courses(self) -> list[Course]:
        return [c for day in sorted(self.days) for c in self.days[day]]


def terms(client: Client) -> list[dict[str, Any]]:
    """学期列表。`current` 来自服务端的「是否当前学期」标记——**部分学校恒为空**，
    所以选默认学期时要做回落（取第一项），不能只依赖它。"""
    resp = client.call(
        {
            "userId": client.userid,
            "usertype": client.usertype,
            "action": "getKb",
            "step": "xnxq",
        }
    )
    rows = resp.get("xnxq") or (resp.get("data") or {}).get("xnxq") or []
    out: list[dict[str, Any]] = []
    for it in rows if isinstance(rows, list) else []:
        if not isinstance(it, dict):
            continue
        out.append(
            {
                "id": _first(it.get("dm") or it.get("id")),
                "name": _first(it.get("mc") or it.get("name")),
                "current": _first(it.get("dqxq")) == "1",
            }
        )
    return out


def _fetch_raw(client: Client, xnxq: str, week: int) -> dict[str, Any]:
    """按周取原始课表。

    两条互斥分支：教务直连学校传「去前缀学号」，其余学校传「完整 userid + 渠道参数」。
    实测直连分支可能返回空体（非 JSON）——那是走错分支的判据，不是没数据。
    这里固定走第二种，跨校最稳。
    """
    return client.call(
        {
            "usertype": client.usertype,
            "action": "getKb",
            "step": "kbdetail_bz",
            "bjdm": "",
            "jsdm": "",
            "xnxq": xnxq,
            "week": str(week),
            "userId": client.userid,
            "channel": "jrkb",
        }
    )


def normalize(raw: dict[str, Any], week: int) -> WeekTable:
    """把天桶展开成 `days[1..7]`。"""
    table = WeekTable(week=week, qssj=_first(raw.get("qssj")), maxzc=int(raw.get("maxzc") or 0))
    for day, key in DAY_KEYS.items():
        bucket = raw.get(key) or []
        table.days[day] = [
            Course.from_raw(obj, day) for obj in bucket if isinstance(obj, dict)
        ]
    return table


def week_table(client: Client, xnxq: str, week: int = 0, *, on: date | None = None) -> WeekTable:
    """取某一周课表。`week=0` 时先探测当前周（用第 1 周的起始日算）。"""
    if week > 0:
        raise_on_error = _fetch_raw(client, xnxq, week)
        table = normalize(raise_on_error, week)
        first = _fetch_raw(client, xnxq, 1)
        table.qssj = table.qssj or _first(first.get("qssj"))
        table.maxzc = table.maxzc or int(first.get("maxzc") or 0)
        return table

    first = _fetch_raw(client, xnxq, 1)
    start = _parse_date(first.get("qssj"))
    if not start:
        neighbours = normalize(first, 1)
        return neighbours
    week = max(1, ((on or date.today()) - start).days // 7 + 1)
    if week == 1:
        return normalize(first, 1)
    return normalize(_fetch_raw(client, xnxq, week), week)


def my_class(client: Client, skbjdm: str, xnxq: str) -> dict[str, Any] | None:
    """班级信息：在同班名单里按自己的学号匹配。

    能读就不要推——从课程名里切班级字符串是错的做法。
    """
    xn, xq = ("", "")
    if len(xnxq) >= 5:
        xn, xq = xnxq[:4], xnxq[4:]
    resp = client.call(
        {
            **client.identity_params(),
            "action": "getKb",
            "step": "skbjmc",
            "skbj": skbjdm,
            "xnxq": xnxq,
            "xn": xn,
            "xq": xq,
        }
    )
    rows = resp.get("resultSet") or resp.get("data") or []
    me = (client.userid or "").split("_", 1)[-1]
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and _first(row.get("yhxh")) == me:
            return row
    return None
