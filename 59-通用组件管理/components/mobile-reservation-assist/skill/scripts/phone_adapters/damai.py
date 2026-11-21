"""大麦手机端适配器（占位：真机选择器在 P1 细化）。"""

from __future__ import annotations

from .base import BasePhoneAdapter


class DamaiPhone(BasePhoneAdapter):
    NAME = "damai"
    APP = "cn.damai"
    ROUTE_HINT = "演出详情→场次→票档"
    SEARCH_FIELD = "演出"
    IDENT_FIELD = "观演人"
