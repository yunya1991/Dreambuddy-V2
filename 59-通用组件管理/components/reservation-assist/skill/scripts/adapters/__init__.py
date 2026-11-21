"""适配器注册表：新增平台 = 新增一个文件并在此登记。"""

from __future__ import annotations

from .base import (
    Adapter,
    AdapterError,
    AuthExpired,
    BaseHttpAdapter,
    GateDenied,
    Hit,
    PlatformChanged,
    RateLimited,
    Response,
    Snapshot,
    SubmitResult,
    SubmitUnknown,
    Transport,
    TransportError,
)
from .bilibili import Bilibili
from .damai import Damai
from .gov import Gov
from .maoyan import Maoyan
from .medical import Medical
from .railway import Railway

ADAPTERS = {cls.NAME: cls for cls in (Railway, Damai, Bilibili, Maoyan, Medical, Gov)}


def get_adapter(name: str) -> Adapter:
    if name not in ADAPTERS:
        raise KeyError("未登记的适配器：{}".format(name))
    return ADAPTERS[name]()


__all__ = [
    "ADAPTERS",
    "Adapter",
    "AdapterError",
    "AuthExpired",
    "BaseHttpAdapter",
    "GateDenied",
    "Hit",
    "PlatformChanged",
    "RateLimited",
    "Response",
    "Snapshot",
    "SubmitResult",
    "SubmitUnknown",
    "Transport",
    "TransportError",
    "get_adapter",
]
