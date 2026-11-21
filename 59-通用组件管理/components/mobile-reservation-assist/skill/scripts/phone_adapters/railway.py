"""铁路 12306 手机端适配器（占位：真机选择器在 P1 细化）。"""

from __future__ import annotations

from .base import BasePhoneAdapter


class RailwayPhone(BasePhoneAdapter):
    NAME = "railway"
    APP = "com.MobileTicket"
    ROUTE_HINT = "车票预订→查询→余票"
    SEARCH_FIELD = "车次/区间"
    IDENT_FIELD = "乘车人"
