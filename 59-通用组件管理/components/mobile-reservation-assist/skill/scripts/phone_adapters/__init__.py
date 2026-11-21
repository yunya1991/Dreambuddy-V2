"""手机端适配器注册表：新增平台 = 新增一个文件并在此登记。"""

from __future__ import annotations

from .base import BasePhoneAdapter, CommandError, PhoneAdapter, assert_no_payment
from .bilibili import BilibiliPhone
from .carpool import CarpoolPhone
from .damai import DamaiPhone
from .douyin import DouyinPhone
from .jianying import JianyingPhone
from .gov import GovPhone
from .maoyan import MaoyanPhone
from .medical import MedicalPhone
from .news import NewsPhone
from .notes import NotesPhone
from .qianwen import QianwenPhone
from .railway import RailwayPhone
from .xiaohongshu import XiaohongshuPhone

ADAPTERS = {
    cls.NAME: cls
    for cls in (RailwayPhone, DamaiPhone, BilibiliPhone, MaoyanPhone, MedicalPhone, GovPhone)
}

# 非预约类通道：千问知识咨询（不计入"预约平台适配器"数量）
CONSULT_ADAPTERS = {QianwenPhone.NAME: QianwenPhone}

# 顺风车抢单通道：扫描订单大厅，授权后才接单（不计入预约平台数量）
CARPOOL_ADAPTERS = {CarpoolPhone.NAME: CarpoolPhone}

# 内容生产通道：资讯采集 / 小红书图文 / 抖音图文 / 剪映视频（不计入预约平台数量）
NOTE_ADAPTERS = {cls.NAME: cls for cls in (NewsPhone, XiaohongshuPhone, DouyinPhone, JianyingPhone, NotesPhone)}


def get_adapter(name: str) -> PhoneAdapter:
    if name in CONSULT_ADAPTERS:
        return CONSULT_ADAPTERS[name]()
    if name in CARPOOL_ADAPTERS:
        return CARPOOL_ADAPTERS[name]()
    if name in NOTE_ADAPTERS:
        return NOTE_ADAPTERS[name]()
    if name not in ADAPTERS:
        raise KeyError("未登记的手机适配器：{}".format(name))
    return ADAPTERS[name]()


__all__ = [
    "ADAPTERS",
    "CARPOOL_ADAPTERS",
    "CONSULT_ADAPTERS",
    "NOTE_ADAPTERS",
    "BasePhoneAdapter",
    "CommandError",
    "PhoneAdapter",
    "assert_no_payment",
    "get_adapter",
]
