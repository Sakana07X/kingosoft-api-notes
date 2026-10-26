"""请求信封。

这套接口从某个版本起不再发明文参数，而是把业务参数序列化后塞进一个固定外壳里，
外壳字段名固定，具体编码随版本变化。所以这里把「外壳」抽象成一个协议：

    envelope.wrap(params, token) -> dict      # 直接作为 POST body

`PlainEnvelope` 是明文外壳（老版本可用，也是抓包时最容易读的形态）。
新版本客户端走 native 编码，需要自己实现 `wrap()`——思路见 docs/01-login.md。

为什么不在库里内置 native 编码实现：
  1. 它依赖客户端自带的 .so，纯 Python 复刻需要额外移植一大坨字符算术与签名；
  2. 每个版本都可能变，硬编码进来只会让库更快过期；
  3. 明确定义边界，比给一个"看起来能用但只在某个版本对"的实现更有用。
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Protocol, runtime_checkable

BASE_URL_PLACEHOLDER = "https://{host}/manager/"

# 设备指纹。客户端只上报机型与系统版本，设备唯一标识方法实测返回空串，
# 所以这里默认留空——伪造一个看不出真假的值没有意义。
DEVICE_MODEL = "PCT-AL10"
ANDROID_VERSION = "13"
USER_AGENT = "okhttp/3.10.0"


@runtime_checkable
class Envelope(Protocol):
    """外壳协议：把业务参数变成最终要发的 body。"""

    def wrap(self, params: dict[str, Any], token: str) -> dict[str, Any]: ...


class PlainEnvelope:
    """明文外壳：body 就是业务参数本身。

    适合老版本接口，或先用它把参数调通、再换成真正的编码层。
    """

    def wrap(self, params: dict[str, Any], token: str) -> dict[str, Any]:
        body = {k: "" if v is None else str(v) for k, v in params.items()}
        if token:
            body.setdefault("token", token)
        return body


class BoardEnvelope:
    """示例：带固定外壳 + 时间戳/随机串的外壳骨架。

    只演示结构，不实现真正的序列化编码 —— 把 `_encode` 换成你那一版的算法即可。
    """

    def __init__(self, appver: str) -> None:
        self.appver = appver

    def _encode(self, plain: str) -> tuple[str, str]:
        """返回 (param, param2)。子类或调用方按实际版本实现。"""
        raise NotImplementedError("外壳编码需按客户端版本实现")

    def wrap(self, params: dict[str, Any], token: str) -> dict[str, Any]:
        plain = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
        param, param2 = self._encode(plain)
        return {
            "param": param,
            "param2": param2,
            "timestamp": str(int(time.time())),
            "echo": uuid.uuid4().hex[:16],
            "token": token or "00000",
            "appinfo": f"android{self.appver}",
            "appsjxh": DEVICE_MODEL,
        }
