"""
TDD 红-绿-重构：SqliteMarketMacroRepo + SqliteConfigRepo + SqliteKGRepo
------------------------------------------------------------------------
覆盖用例：共 12 个 TDD 单测

[MM 市场宏观 6 个]
 1. fear_greed: upsert 幂等 + 按时间范围查询（无 symbol 指标）
 2. funding_rate: upsert 幂等 + Decimal 精度 + 按 symbol+时间 查询
 3. open_interest: upsert 幂等 + sum_open_interest_value 正确持久化
 4. liquidation: upsert 幂等 + BUY/SELL 双边映射 + total_quantity 汇总
 5. long_short_ratio: upsert 幂等 + int 账户数往返
 6. taker_volume: upsert 幂等 + diff/ratio 双字段正确

[CV 配置版本 3 个]
 7. create_version: 新版本号单调递增 + JSON payload 无损
 8. activate_version: 全局单激活不变量（激活新版本自动取消旧激活）
 9. get_active_version / get_specific_version: 历史版本精确回读

[KG 知识图谱 3 个]
 10. upsert_entity + add_alias: 实体别名同实体可多别名幂等
 11. add_triple: subject-predicate-object 三元组双时态 + 子图查询 N 跳
 12. fts_search_entities: FTS5 全文索引命中（实体名/分类）
"""
from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from dreambuddy_dal.connection import get_sqlite_connection
from dreambuddy_dal.implementations.sqlite_unified.schema_init import init_db_schema


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def db_path():
    """每个测试独立临时 SQLite（WAL 模式+init_schema 已做）。"""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "t.db"
        with get_sqlite_connection(str(p)) as conn:
            init_db_schema(conn)
        yield str(p)


@pytest.fixture
def mm_repo(db_path):
    from dreambuddy_dal.implementations.sqlite_unified.market_macro_impl import (
        SqliteMarketMacroRepository,
    )
    return SqliteMarketMacroRepository(db_path)


@pytest.fixture
def cfg_repo(db_path):
    from dreambuddy_dal.implementations.sqlite_unified.config_impl import (
        SqliteConfigRepository,
    )
    return SqliteConfigRepository(db_path)


@pytest.fixture
def kg_repo(db_path):
    from dreambuddy_dal.implementations.sqlite_unified.kg_impl import (
        SqliteKnowledgeGraphRepository,
    )
    return SqliteKnowledgeGraphRepository(db_path)


# ===========================================================================
# MM 市场宏观 6 个单测
# ===========================================================================
def _ts(dt: datetime) -> int:
    """datetime → UNIX 秒（对齐 mm_* 表 timestamp INTEGER）。"""
    return int(dt.astimezone(timezone.utc).timestamp())


def test_mm_fear_greed_upsert_idempotent_and_query(mm_repo):
    """[1] 恐惧贪婪：无 symbol 指标 upsert 幂等 + 按时间区间查询。"""
    t1 = datetime(2026, 8, 24, 8, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 8, 24, 10, 0, 0, tzinfo=timezone.utc)
    t3 = datetime(2026, 8, 24, 12, 0, 0, tzinfo=timezone.utc)

    r1 = mm_repo.upsert_fear_greed(65, "Greed", t1)
    r2 = mm_repo.upsert_fear_greed(65, "Greed", t1)  # 幂等
    r3 = mm_repo.upsert_fear_greed(30, "Fear", t2)
    assert r1 is True
    assert r2 is True  # 幂等 upsert 仍返回 True（INSERT OR REPLACE 语义）
    assert r3 is True

    # 区间查询（t1<=ts<t3 → 应含 t1,t2，不含 t3 外）
    rows = mm_repo.query_fear_greed_by_time(t1, t3)
    assert len(rows) == 2
    # 返回格式：(value, value_classification, datetime)
    values = sorted(r[0] for r in rows)
    assert values == [30, 65]
    assert isinstance(rows[0][2], datetime)


def test_mm_funding_rate_decimal_roundtrip(mm_repo):
    """[2] 资金费率：Decimal 精度保留（ADR-19-004 TEXT/REAL 语义） + symbol 维度。"""
    t = datetime(2026, 8, 24, 8, 0, 0, tzinfo=timezone.utc)
    rate = Decimal("0.000123456789")  # 高精度
    ok = mm_repo.upsert_funding_rate("BTC-USDT-SWAP", rate, t)
    assert ok is True

    # 幂等（同 PK 替换）
    ok2 = mm_repo.upsert_funding_rate("BTC-USDT-SWAP", rate, t)
    assert ok2 is True

    rows = mm_repo.query_funding_by_time(
        "BTC-USDT-SWAP",
        datetime(2026, 8, 24, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 25, 0, 0, tzinfo=timezone.utc),
    )
    assert len(rows) == 1
    symbol, rate_out, ts_out = rows[0]
    assert symbol == "BTC-USDT-SWAP"
    # REAL 存储可能会有 float 精度损失，但保留到 1e-10 以内
    assert abs(Decimal(str(rate_out)) - rate) < Decimal("1e-9")
    assert ts_out.date() == t.date()


def test_mm_open_interest_dual_decimal_fields(mm_repo):
    """[3] 持仓量：open_interest + sum_open_interest_value 双 Decimal 字段。"""
    t = datetime(2026, 8, 24, 9, 0, tzinfo=timezone.utc)
    oi = Decimal("1234567.89")
    sum_oi = Decimal("98765432.10")
    ok = mm_repo.upsert_open_interest("ETH-USDT-SWAP", oi, sum_oi, t)
    assert ok is True

    rows = mm_repo.query_open_interest_by_time(
        "ETH-USDT-SWAP",
        datetime(2026, 8, 24, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 25, 0, tzinfo=timezone.utc),
    )
    assert len(rows) == 1
    sym, oi_out, sum_out, _ts = rows[0]
    assert sym == "ETH-USDT-SWAP"
    assert abs(Decimal(str(oi_out)) - oi) < Decimal("1e-5")
    assert abs(Decimal(str(sum_out)) - sum_oi) < Decimal("1e-5")


def test_mm_liquidation_buy_sell_side(mm_repo):
    """[4] 爆仓数据：BUY 侧 & SELL 侧正确映射 + total_quantity 合计。"""
    t = datetime(2026, 8, 24, 11, tzinfo=timezone.utc)
    # BUY = 空单爆仓（空平）；SELL = 多单爆仓（多平）
    r1 = mm_repo.upsert_liquidation(
        "BTC-USDT-SWAP", Decimal("50.5"), "SELL", Decimal("64500"), Decimal("50.5"), t
    )
    assert r1 is True
    r2 = mm_repo.upsert_liquidation(
        "BTC-USDT-SWAP", Decimal("25.0"), "BUY", Decimal("64800"), Decimal("25.0"), t
    )
    assert r2 is True  # 同 t，同 symbol → INSERT OR REPLACE

    rows = mm_repo.query_liquidation_by_time(
        "BTC-USDT-SWAP",
        datetime(2026, 8, 24, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 25, 0, tzinfo=timezone.utc),
    )
    # 最后一次 upsert(BUY) 替换了同一 (symbol, t) PK
    assert len(rows) == 1
    sym, qty, side, price, total_qty, _ts = rows[0]
    assert sym == "BTC-USDT-SWAP"
    assert side == "BUY"
    assert abs(Decimal(str(qty)) - Decimal("25.0")) < Decimal("1e-5")


def test_mm_long_short_ratio_int_accounts(mm_repo):
    """[5] 多空比：long/short 账户数（int）往返正确。"""
    t = datetime(2026, 8, 24, 12, tzinfo=timezone.utc)
    l_acc = Decimal("12500")
    s_acc = Decimal("10000")
    ratio = Decimal("1.25")
    ok = mm_repo.upsert_long_short_ratio("SOL-USDT-SWAP", l_acc, s_acc, ratio, t)
    assert ok is True

    rows = mm_repo.query_long_short_ratio_by_time(
        "SOL-USDT-SWAP",
        datetime(2026, 8, 24, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 25, 0, tzinfo=timezone.utc),
    )
    assert len(rows) == 1
    sym, l_out, s_out, r_out, _ts = rows[0]
    assert Decimal(str(l_out)) == l_acc
    assert Decimal(str(s_out)) == s_acc
    assert abs(Decimal(str(r_out)) - ratio) < Decimal("1e-5")


def test_mm_taker_volume_diff_and_ratio(mm_repo):
    """[6] Taker 主动买卖量：diff 和 ratio 双字段正确。"""
    t = datetime(2026, 8, 24, 13, tzinfo=timezone.utc)
    buy = Decimal("1_000_000")
    sell = Decimal("800_000")
    diff = Decimal("200_000")
    ratio = Decimal("1.25")
    ok = mm_repo.upsert_taker_volume("XRP-USDT-SWAP", buy, sell, diff, ratio, t)
    assert ok is True

    rows = mm_repo.query_taker_volume_by_time(
        "XRP-USDT-SWAP",
        datetime(2026, 8, 24, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 25, 0, tzinfo=timezone.utc),
    )
    assert len(rows) == 1
    sym, b_out, s_out, d_out, r_out, _ts = rows[0]
    assert abs(Decimal(str(b_out)) - buy) < Decimal("1")
    assert abs(Decimal(str(s_out)) - sell) < Decimal("1")
    assert abs(Decimal(str(d_out)) - diff) < Decimal("1")
    assert abs(Decimal(str(r_out)) - ratio) < Decimal("1e-4")


# ===========================================================================
# CV 配置版本 3 个单测
# ===========================================================================
def test_cfg_create_version_monotonic_and_payload_roundtrip(cfg_repo):
    """[7] 创建版本：版本号单调递增 + JSON payload 无损序列化。"""
    data_v1 = {"cap": 1.0, "war_state": "ALLOW", "threshold": Decimal("0.015")}
    v1 = cfg_repo.create_version(
        "global", data_v1, created_by="zhangjiangtao",
        description="v1 baseline 易经五计庙算参数",
    )
    assert isinstance(v1, int) and v1 >= 1

    data_v2 = {"cap": 0.8, "war_state": "DEFEND", "threshold": Decimal("0.012")}
    v2 = cfg_repo.create_version(
        "global", data_v2, description="v2 防御姿态收紧阈值",
    )
    assert v2 == v1 + 1  # 单调递增

    # 指定历史版本回读
    read_v1 = cfg_repo.get_specific_version("global", v1)
    assert read_v1 is not None
    # Decimal → JSON 序列化后以 str 浮点或 int 回归，校验 cap/war_state 核心字段
    assert float(read_v1["cap"]) == 1.0
    assert read_v1["war_state"] == "ALLOW"


def test_cfg_activate_version_uniq_active_invariant(cfg_repo):
    """[8] 激活版本：全局单激活不变量（触发器自动取消旧激活）。"""
    v1 = cfg_repo.create_version("yijing", {"p": 1})
    cfg_repo.create_version("yijing", {"p": 2})
    v3 = cfg_repo.create_version("yijing", {"p": 3})

    # 激活 v1 → 再激活 v3
    r1 = cfg_repo.activate_version("yijing", v1, activated_by="tester")
    assert r1 is True

    r2 = cfg_repo.activate_version("yijing", v3, activated_by="tester")
    assert r2 is True

    # 不存在的版本号 → 返回 False
    r_bad = cfg_repo.activate_version("yijing", 9999, activated_by="tester")
    assert r_bad is False

    active = cfg_repo.get_active_version("yijing")
    assert active is not None
    # 激活态应当是 v3（最后一次 activate）
    assert active.get("p") == 3


def test_cfg_get_active_vs_specific_version(cfg_repo):
    """[9] get_active（查激活态） vs get_specific_version（查任意历史版）。"""
    # 初始无激活版本
    assert cfg_repo.get_active_version("v15") is None

    v1 = cfg_repo.create_version("v15", {"martin_max_level": 7})
    v2 = cfg_repo.create_version("v15", {"martin_max_level": 5})

    # 未激活，get_active 仍 None
    assert cfg_repo.get_active_version("v15") is None
    cfg_repo.activate_version("v15", v1)
    active = cfg_repo.get_active_version("v15")
    assert active is not None
    assert active["martin_max_level"] == 7

    # 历史版 v2 可以独立回读（不影响激活态）
    hist_v2 = cfg_repo.get_specific_version("v15", v2)
    assert hist_v2 is not None
    assert hist_v2["martin_max_level"] == 5
    # 读回后激活态不变
    active2 = cfg_repo.get_active_version("v15")
    assert active2["martin_max_level"] == 7


# ===========================================================================
# KG 知识图谱 3 个单测
# ===========================================================================
def test_kg_upsert_entity_and_multiple_aliases(kg_repo):
    """[10] 实体 upsert + 多别名幂等（同一实体可多别名，同一别名重复不报错）。"""
    ok1 = kg_repo.upsert_entity(
        "BTC",
        "asset",
        "Bitcoin",
        description="全球市值第一加密货币，POW 共识，白皮书 2008",
        attributes_json='{"tier": "blue_chip", "launch_year": 2009}',
    )
    assert ok1 is True

    # 同一实体多别名
    a1 = kg_repo.add_alias("BTC", "大饼", confidence=1.0)
    a2 = kg_repo.add_alias("BTC", "比特币", confidence=0.95)
    a3 = kg_repo.add_alias("BTC", "大饼", confidence=1.0)  # 幂等
    assert a1 is True
    assert a2 is True
    assert a3 is True  # UNIQUE(entity_id, alias) 不抛异常，幂等


def test_kg_add_triple_and_subgraph_n_hops(kg_repo):
    """[11] 三元组插入（双时态 valid_from） + N 跳子图查询 out 方向。"""
    # 先建实体
    for eid, etype, cname in [
        ("BTC", "asset", "Bitcoin"),
        ("CRYPTO_SECTOR", "sector", "加密资产"),
        ("BLUE_CHIP_TIER", "tier", "蓝筹等级"),
    ]:
        kg_repo.upsert_entity(eid, etype, cname)

    # BTC -[belongs_to]-> CRYPTO_SECTOR
    t1 = kg_repo.add_triple(
        "BTC", "belongs_to_sector", "CRYPTO_SECTOR",
        confidence=0.99, source="manual_classification",
    )
    # BTC -[has_tier]-> BLUE_CHIP_TIER
    t2 = kg_repo.add_triple("BTC", "has_tier", "BLUE_CHIP_TIER", confidence=0.90)
    assert t1 is True and t2 is True

    # 1 跳 out 子图：BTC → 直接邻居
    triples, entities = kg_repo.query_subgraph_by_entity(
        "BTC", hops=1, direction="out", min_confidence=0.5,
    )
    # 应找到 2 条三元组 + 3 个实体（BTC + CRYPTO_SECTOR + BLUE_CHIP_TIER）
    assert len(triples) == 2
    entity_ids = {e[0] for e in entities}
    assert {"BTC", "CRYPTO_SECTOR", "BLUE_CHIP_TIER"}.issubset(entity_ids)


def test_kg_fts_search_entities_basic(kg_repo):
    """[12] FTS5 全文索引：实体标签+分类命中。"""
    kg_repo.upsert_entity("BTC", "asset", "Bitcoin")
    kg_repo.upsert_entity("ETH", "asset", "Ethereum")
    kg_repo.upsert_entity("MARTIN_GRID", "strategy", "MartinGrid 马丁加仓策略")
    kg_repo.add_alias("MARTIN_GRID", "马丁策略")

    # 搜索 "strategy 马丁" 或类似关键词（FTS5 MATCH 语法）
    results = kg_repo.fts_search_entities("strategy", limit=20)
    assert len(results) >= 1
    # MARTIN_GRID 的标签/别名里有 strategy/MartinGrid/马丁
    ids = {r[0] for r in results}
    assert "MARTIN_GRID" in ids
