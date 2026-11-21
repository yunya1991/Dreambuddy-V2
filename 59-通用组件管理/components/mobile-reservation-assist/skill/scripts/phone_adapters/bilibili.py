"""B站会员购手机端适配器（占位：真机选择器在 P1 细化）。"""

from __future__ import annotations

from .base import BasePhoneAdapter


class BilibiliPhone(BasePhoneAdapter):
    NAME = "bilibili"
    APP = "tv.danmaku.bili"
    ROUTE_HINT = "会员购→详情→场次票档"
    SEARCH_FIELD = "商品"
    IDENT_FIELD = "实名观演人"
