"""猫眼手机端适配器（占位：真机选择器在 P1 细化）。"""

from __future__ import annotations

from .base import BasePhoneAdapter


class MaoyanPhone(BasePhoneAdapter):
    NAME = "maoyan"
    APP = "com.sankuai.movie"
    ROUTE_HINT = "影片/演出→选座→票档"
    SEARCH_FIELD = "影片/演出"
    IDENT_FIELD = ""
