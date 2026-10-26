"""签到：状态、提交、距离、落库核验。

三个容易踩坏的地方（详见 docs/03-checkin.md）：
  1. 查询用的节次参数必须是**区间串**（"3-4"），传首节数字一律答「未发起」
  2. 同一个教学班一天有多节课，回查考勤必须连节次一起匹配，否则会串
  3. `flag=1` 只代表服务端受理，不代表落库；落库可能滞后到一分钟以上
"""
from __future__ import annotations

import math
import random
import re
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .client import Client
from .kb import Course

# 考勤状态码（服务端同时下发中文名，取不到时用这张表兜底）
QDZT = {
    "00": "正常",
    "01": "缺勤",
    "02": "迟到",
    "03": "事假",
    "04": "早退",
    "05": "病假",
    "06": "公假",
}

# 查询状态码
STATE = {
    "1": "签到中",
    "-1": "未发起",
    "0": "未发起",
    "": "未发起",
    "-4": "已结束",
    "-2": "已结束",
}

_EARTH_R = 6371000.0

_SUCCESS_WORDS = ("签到成功", "签到完成", "上报成功")
_ALREADY_WORDS = ("无需重复", "重复签到", "已签到", "已经签到")

_JC_SPLIT = re.compile(r"[-~,，\s]+")


def jc_nums(jc: str) -> set[int]:
    out: set[int] = set()
    for part in _JC_SPLIT.split(str(jc or "")):
        if part.isdigit():
            out.add(int(part))
    return out


def jc_hit(left: str, right: str) -> bool:
    """两个节次串（数字或区间）是否相交。"""
    a, b = jc_nums(left), jc_nums(right)
    return bool(a & b)


def distance_m(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    """球面距离，单位米。与客户端算法同量级（差在浮点末位，不影响判定）。"""
    r1, r2 = math.radians(lat1), math.radians(lat2)
    dlng = math.radians(lng2 - lng1)
    dlat = r2 - r1
    x = math.cos(r2) * math.cos(dlng) - math.cos(r1)
    y = math.sin(dlng) * math.cos(r2)
    z = math.sin(dlat)
    # 两点单位向量的弦长 → 半弦角 → 弧长
    return abs(math.asin(min(1.0, math.hypot(x, y, z) / 2.0))) * 2.0 * _EARTH_R


def nearby(point: str, dmin: float = 3.0, dmax: float = 10.0, rng: random.Random | None = None) -> str:
    """在基准点附近造一个合法点位，返回 "lng,lat"。

    思路是让上报坐标自洽（在同一片校园里、距离落在合理档位），
    不是让坐标不存在——服务端如果重算距离，只要点真在半径内结果就一致。
    """
    rng = rng or random
    lng_s, lat_s = str(point).split(",", 1)
    lng, lat = float(lng_s), float(lat_s)
    dist = rng.uniform(dmin, dmax)
    angle = rng.uniform(0.0, 2.0 * math.pi)
    dlat = dist * math.cos(angle) / 111320.0
    dlng = dist * math.sin(angle) / (111320.0 * max(0.2, math.cos(math.radians(lat))))
    return f"{lng + dlng:.6f},{lat + dlat:.6f}"


@dataclass
class State:
    code: str = ""
    qdfs: str = ""          # ""/"0" 未发起 · "1" 定位 · "2" 手势 · "3" 二维码
    jsjwd: str = ""         # 教师基准点 "lng,lat"，可能为空
    qdssm: str = ""         # 手势图案串
    dm: str = ""            # 二维码码值
    qdztdm: str = ""
    kssj: str = ""
    jssj: str = ""
    msg: str = ""
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def label(self) -> str:
        return STATE.get(self.code, self.msg or self.code or "未知")

    @property
    def active(self) -> bool:
        return self.code == "1"

    @property
    def closed(self) -> bool:
        return self.code in ("-4", "-2")

    @property
    def signed(self) -> bool:
        return self.qdztdm == "00"

    @property
    def kind(self) -> str:
        return {"1": "location", "2": "gesture", "3": "qrcode"}.get(self.qdfs, "none")


def _ok(resp: dict[str, Any]) -> bool:
    result = resp.get("result")
    flag = result.get("flag") if isinstance(result, dict) else None
    if str(flag or resp.get("flag") or "") == "1":
        return True
    msg = str(resp.get("msg") or resp.get("message") or "")
    return any(w in msg for w in _SUCCESS_WORDS) and not any(w in msg for w in _ALREADY_WORDS)


@dataclass
class Checkin:
    """绑定一个客户端与一个学期，之后按课程操作。"""

    client: Client
    xnxq: str = ""

    # ------------------------------------------------------------------ 查询

    def state(self, course: Course) -> State:
        resp = self.client.call(
            {
                **self.client.identity_params(),
                "action": "oriSkqd",
                "step": "stu_jwd",
                "xnxq": self.xnxq,
                "skbjdm": course.skbjdm,
                "kcdm": course.kcdm,
                "qdjc": course.jc_str,   # 必须是区间串
            }
        )
        body = resp.get("result") if isinstance(resp.get("result"), dict) else resp
        return State(
            code=str(body.get("state", "")),
            qdfs=str(body.get("qdfs", "")),
            jsjwd=str(body.get("jsjwd", "")),
            qdssm=str(body.get("qdssm", "")),
            dm=str(body.get("dm", "")),
            qdztdm=str(body.get("qdztdm", "")),
            kssj=str(body.get("kssj", "")),
            jssj=str(body.get("jssj", "")),
            msg=str(body.get("msg", "")),
            raw=body,
        )

    def records(self, skbjdm: str) -> list[dict[str, Any]]:
        """该教学班的考勤记录（不是签到状态）。"""
        resp = self.client.call(
            {
                **self.client.identity_params(),
                "action": "oriSkqd",
                "step": "stu_home",
                "xnxq": self.xnxq,
                "skbjdm": skbjdm,
            }
        )
        body = resp.get("result") if isinstance(resp.get("result"), dict) else resp
        rows = body.get("skqd") or body.get("data") or []
        return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []

    # ------------------------------------------------------------------ 提交

    def _submit(self, course: Course, extra: dict[str, Any]) -> dict[str, Any]:
        params = {
            **self.client.identity_params(),
            "action": "oriSkqd",
            "step": "stu_yjqd",
            "xnxq": self.xnxq,
            "skbjdm": course.skbjdm,
            "kcdm": course.kcdm,
            "qdrq": date.today().isoformat(),
            "qdjc": course.jc_str,
            "qdjwd": "",
            "qdjl": "",
            "errorflag": "",
        }
        params.update(extra)
        return self.client.call(params)

    def submit_location(
        self,
        course: Course,
        state: State,
        *,
        student_point: str = "",
        meters: float = 0.0,
    ) -> dict[str, Any]:
        """定位签到。教师没给基准点时按客户端行为提交空坐标。"""
        if state.jsjwd and not student_point:
            student_point = nearby(state.jsjwd)
        if state.jsjwd and student_point and not meters:
            tlng, tlat = (float(v) for v in state.jsjwd.split(",", 1))
            slng, slat = (float(v) for v in student_point.split(",", 1))
            meters = distance_m(tlng, tlat, slng, slat)
        return self._submit(
            course,
            {
                "qdfs": state.qdfs or "1",
                "qdssm": state.qdssm,           # 手势：图案原文回传
                "qdjwd": student_point,
                "qdjl": "" if meters <= 0 else str(int(meters)),
            },
        )

    def submit_qrcode(self, course: Course, code: str) -> dict[str, Any]:
        """二维码签到。`code` 是扫到的原文（或码值本身）。"""
        return self._submit(course, {"qdfs": "3", "qdewm": code})

    # ------------------------------------------------------------------ 核验

    def verify(
        self,
        course: Course,
        *,
        tries: int = 4,
        gap: float = 3.0,
        on: date | None = None,
    ) -> dict[str, Any]:
        """回查考勤，确认是否真的落库。`flag=1` 与成功提示都不算证据。"""
        day = (on or date.today()).isoformat()
        detail = ""
        for i in range(max(1, tries)):
            try:
                for row in self.records(course.skbjdm):
                    if str(row.get("rq", "")) != day:
                        continue
                    if not jc_hit(str(row.get("jc", "")), course.jc_str):
                        continue
                    code = str(row.get("qdztdm", ""))
                    return {
                        "verified": code == "00",
                        "code": code,
                        "label": str(row.get("qdztmc") or QDZT.get(code, code)),
                        "tries": i + 1,
                        "detail": "考勤已落库" if code == "00" else f"考勤记录为「{QDZT.get(code, code)}」",
                    }
                detail = "该节次仍无考勤记录（落库可能有延迟）"
            except Exception as exc:  # 回查失败不影响主流程结论
                detail = f"回查异常：{exc}"
            if i + 1 < tries:
                time.sleep(min(gap * (1 + i * 0.7), 20.0))
        return {"verified": False, "code": "", "label": "", "tries": tries, "detail": detail}
