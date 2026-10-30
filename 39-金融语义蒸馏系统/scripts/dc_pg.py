# -*- coding: utf-8 -*-
"""39-金融语义蒸馏系统 · PostgreSQL 查询辅助模块（C4b 薄壳）

能力已收编至 19-DAL：dreambuddy_dal.implementations.postgres.datacenter_impl
（DataCenterQueries）。本模块保留旧名薄壳，函数签名与返回结构不变，
调用方零改动；连接发现与 FAIL-OPEN 语义由 DAL 实现承担。

FAIL-OPEN: PostgreSQL 不可达时返回空结果，不抛异常（由 DAL 实现保证）。
"""
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DAL = os.path.join(_REPO, "19-数据访问层")
if _DAL not in sys.path:
    sys.path.insert(0, _DAL)

from dreambuddy_dal.implementations.postgres.datacenter_impl import DataCenterQueries

_impl = DataCenterQueries()


def fetch_records(sub_category_like, limit=500, order_desc=True):
    """按 sub_category 模式查询 records，返回 [{id, sub_category, timestamp, metrics}]。"""
    return _impl.fetch_records(sub_category_like, limit=limit, order_desc=order_desc)


def fetch_latest(sub_category):
    """取某 sub_category 最新一条记录，返回 dict 或 None。"""
    return _impl.fetch_latest(sub_category)


def fetch_max_record_id():
    """取 records 表最大 id（原子事件断点续扫用）。FAIL-OPEN: 异常返回 0。"""
    return _impl.fetch_max_record_id()


def fetch_latest_by_source(source, sub_category=None):
    """按 source（可选 sub_category）取最新一条记录（L0 datacenter.record scope 用）。"""
    return _impl.fetch_latest_by_source(source, sub_category=sub_category)


def fetch_source_groups(limit=60):
    """按 source/category/sub_category 分组统计记录数（data_query 意图采集用）。"""
    return _impl.fetch_source_groups(limit=limit)


def fetch_records_since(sub_category_like, since_id, limit=5000):
    """按 id 增量查询（原子事件 --live 模式用），返回升序结果。"""
    return _impl.fetch_records_since(sub_category_like, since_id, limit=limit)
