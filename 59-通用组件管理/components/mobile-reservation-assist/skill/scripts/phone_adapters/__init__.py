"""手机端适配器注册表：新增平台 = 新增一个文件并在此登记。"""

from __future__ import annotations

from .base import BasePhoneAdapter, CommandError, PhoneAdapter, assert_no_payment
from .bilibili import BilibiliPhone
from .damai import DamaiPhone
from .gov import GovPhone
from .maoyan import MaoyanPhone
from .medical import MedicalPhone
from .railway import RailwayPhone

ADAPTERS = {
    cls.NAME: cls
    for cls in (RailwayPhone, DamaiPhone, BilibiliPhone, MaoyanPhone, MedicalPhone, GovPhone)
}


def get_adapter(name: str) -> PhoneAdapter:
    if name not in ADAPTERS:
        raise KeyError("未登记的手机适配器：{}".format(name))
    return ADAPTERS[name]()


__all__ = [
    "ADAPTERS",
    "BasePhoneAdapter",
    "CommandError",
    "PhoneAdapter",
    "assert_no_payment",
    "get_adapter",
]
