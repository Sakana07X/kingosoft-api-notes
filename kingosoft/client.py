"""客户端：学校解析、登录、请求发送、会话续期。

只依赖 requests。所有方法失败时抛 `ApiError`（带服务端原文），不吞异常。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import requests

from .envelope import DEVICE_MODEL, ANDROID_VERSION, USER_AGENT, Envelope, PlainEnvelope

# 学校目录与学校网关都在同一套控制器下，只是 host 不同
GATEWAY = "https://api.xiqueer.com/manager/"
CONTROLLER = "wap/wapController.jsp"

APP_VERSION = "2.6.452"  # 版本门是下限校验，传一个不低于门槛的值即可，见 docs/01-login.md §4

NET_RETRIES = 2
NET_BACKOFF = 0.6

# JS escape() 的保留字符集
_SAFE = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.!~*'()"
)


class ApiError(RuntimeError):
    """服务端返回了错误，或响应不是预期的 JSON。"""


class VersionGateError(ApiError):
    """被版本门拦下：客户端版本低于服务端要求的下限。"""


def js_escape(text: str) -> str:
    """等价于 JavaScript 的 escape()。

    这套接口把密码交给它处理，函数名叫「加密」，实际只是百分号编码——
    可逆、无密钥、无随机数。判别方法见 docs/01-login.md §3。
    """
    out: list[str] = []
    for ch in text:
        if ch in _SAFE:
            out.append(ch)
        elif ord(ch) < 256:
            out.append(f"%{ord(ch):02X}")
        else:
            out.append(f"%u{ord(ch):04X}")
    return "".join(out)


def _join(base: str) -> str:
    return base if base.endswith("/") else base + "/"


@dataclass
class School:
    xxdm: str
    name: str
    service_url: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Client:
    """一个账号一个实例。`service_url` 留空时先查学校目录。"""

    xxdm: str
    login_id: str
    password: str
    service_url: str = ""
    envelope: Envelope = field(default_factory=PlainEnvelope)
    device_model: str = DEVICE_MODEL
    android_version: str = ANDROID_VERSION
    appver: str = APP_VERSION
    timeout: int = 20

    # 登录后填充
    userid: str = ""
    usertype: str = ""
    token: str = ""
    xm: str = ""
    xxmc: str = ""

    session: requests.Session = field(default_factory=requests.Session, repr=False)

    def __post_init__(self) -> None:
        self.session.headers.update(
            {"User-Agent": USER_AGENT, "Content-Type": "application/x-www-form-urlencoded"}
        )

    # ---------------------------------------------------------------- 基础设施

    def _request(self, url: str, data: dict[str, Any]) -> dict[str, Any]:
        """带网络层退避的 POST。业务错误不在这里重试。"""
        last: Exception | None = None
        for attempt in range(NET_RETRIES + 1):
            try:
                resp = self.session.post(url, data=data, timeout=self.timeout)
                resp.raise_for_status()
                if not resp.content:
                    # 空 body 是「走错分支」的判据，不是网络问题，见 docs/02-timetable.md §5
                    raise ApiError("响应为空（通常是接口分支或参数形态不对）")
                try:
                    return resp.json()
                except ValueError as exc:
                    raise ApiError(f"响应不是 JSON：{resp.text[:120]}") from exc
            except (requests.Timeout, requests.ConnectionError) as exc:
                last = exc
                if attempt < NET_RETRIES:
                    time.sleep(NET_BACKOFF * (attempt + 1))
                    continue
                raise ApiError(f"网络失败：{exc}") from exc
            except requests.HTTPError as exc:  # 4xx/5xx 不重试
                raise ApiError(f"HTTP {exc.response.status_code}") from exc
        raise ApiError(f"网络失败：{last}")

    @property
    def base(self) -> str:
        return _join(self.service_url or GATEWAY)

    def close(self) -> None:
        self.session.close()

    # ---------------------------------------------------------------- 学校 / 登录

    @staticmethod
    def resolve_school(xxdm: str, appver: str = APP_VERSION, timeout: int = 20) -> School:
        """学校代码 → 该校网关。跨校场景不能跳过这一步。"""
        body = PlainEnvelope().wrap(
            {"action": "getAgentByXxdm", "xxdm": xxdm, "appver": appver}, ""
        )
        resp = requests.post(_join(GATEWAY) + CONTROLLER, data=body, timeout=timeout)
        data = resp.json()
        rows = data.get("data") or data.get("result") or []
        if isinstance(rows, dict):
            rows = rows.get("data") or [rows]
        for row in rows:
            if str(row.get("xxdm")) == str(xxdm):
                return School(
                    xxdm=str(xxdm),
                    name=str(row.get("xxmc") or ""),
                    service_url=str(row.get("serviceUrl") or GATEWAY),
                    extra=row,
                )
        raise ApiError(f"学校目录里没有 {xxdm}")

    def login(self) -> dict[str, Any]:
        """登录。成功返回服务端 data，失败抛 ApiError / VersionGateError。"""
        if not self.service_url:
            self.service_url = self.resolve_school(self.xxdm, self.appver).service_url

        params = {
            "loginId": self.login_id,
            "xxdm": self.xxdm,
            "pwd": js_escape(self.password),
            "pwdsfzm": "1",
            "action": "getLoginInfoNew",
            "zddl": "1",
            "isky": "1",
            "sjbz": "",           # 客户端那个方法实测就是返回空串
            "sswl": "",
            "sjxh": self.device_model,
            "os": "android",
            "xtbb": self.android_version,
            "loginmode": "",
            "appver": self.appver,
        }
        resp = self._request(self.base + CONTROLLER, self.envelope.wrap(params, ""))

        result = resp.get("result") or {}
        if str(result.get("flag") or "") != "1":
            msg = str(resp.get("msg") or result.get("memo") or resp.get("message") or "")
            if "更新" in msg or "升级" in msg or "版本" in msg:
                raise VersionGateError(msg or "被版本门拦下")
            raise ApiError(msg or "登录失败")

        self.userid = str(result.get("userId") or resp.get("userId") or "")
        self.usertype = str(result.get("usertype") or resp.get("usertype") or "STU")
        self.token = str(result.get("token") or resp.get("token") or "")
        self.xm = str(resp.get("xm") or result.get("xm") or "")
        self.xxmc = str(resp.get("xxmc") or "")
        return resp

    # ---------------------------------------------------------------- 调用

    def identity_params(self) -> dict[str, str]:
        """每次请求都要带的身份五键。`xh` 是 userid 去掉学校前缀。"""
        xh = (self.userid or self.login_id).split("_", 1)[-1]
        return {
            "userId": self.userid or self.login_id,
            "usertype": self.usertype or "STU",
            "xh": xh,
            "xxdm": self.xxdm,
            "sjbz": "",
        }

    def call(self, params: dict[str, Any], *, _retry: bool = True) -> dict[str, Any]:
        """发一个业务请求。

        token 过期时服务端回业务错误码而不是 401，所以在这里拦截一次：
        重新登录后重放本次请求（只重放一次，避免把业务错误也重试）。
        """
        if not self.token:
            self.login()
        resp = self._request(self.base + CONTROLLER, self.envelope.wrap(params, self.token))

        if _retry and str(resp.get("errcode") or "") == "-1":
            self.login()
            return self.call(params, _retry=False)
        return resp
