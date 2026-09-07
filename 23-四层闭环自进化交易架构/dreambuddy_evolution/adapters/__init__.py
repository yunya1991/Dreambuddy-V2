"""
数据管线适配器层 — 将分散数据源组装为 KlineEventHandler 所需的 kline_data dict
SPEC: 23-四层闭环自进化交易架构/SPEC-数据管线打通与能力落地.md

FAIL-OPEN 铁律：所有适配器永不抛异常，字段缺失 → R 向量该维度走 0.5 兜底
"""
