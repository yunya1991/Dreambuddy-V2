"""政务/签证/场馆手机端适配器（占位：真机选择器在 P1 细化）。"""

from __future__ import annotations

from .base import BasePhoneAdapter


class GovPhone(BasePhoneAdapter):
    NAME = "gov"
    APP = ""  # 各政务/场馆 App/小程序不同，P1 按实例配置
    ROUTE_HINT = "预约→业务→时段"
    SEARCH_FIELD = "业务/场馆"
    IDENT_FIELD = "预约人"
