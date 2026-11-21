"""医院挂号/疫苗手机端适配器（占位：真机选择器在 P1 细化）。"""

from __future__ import annotations

from .base import BasePhoneAdapter


class MedicalPhone(BasePhoneAdapter):
    NAME = "medical"
    APP = ""  # 各医院 App/小程序不同，P1 按实例配置
    ROUTE_HINT = "预约挂号→科室→号源"
    SEARCH_FIELD = "科室/医生"
    IDENT_FIELD = "就诊人"
