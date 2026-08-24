"""
TDD：P2-2 di.py Shadow Read 机制
=================================
当 READ_SOURCE=shadow 时，DualWrapper 读方法额外执行新库读 + 比对 + 写审计。

入口：di.py 的 _DualWrapper 在 READ_PREFIXES 命中时：
  1. 调 legacy 取结果 result_legacy
  2. 若 READ_SOURCE=shadow → 调 new 取 result_new
  3. 比对 → MATCH/DIFF → 写 ma_migration_audit(category='shadow_read')
  4. 返回 result_legacy（不影响主流程）

测试场景：
  1. READ_SOURCE 未设 → 无 shadow read（正常 dual_write 行为不变）
  2. READ_SOURCE=shadow → 读后 ma_migration_audit 出现 category='shadow_read' 行
  3. 两端结果一致 → result=MATCH
  4. 两端结果不一致 → result=DIFF（但仍返回 legacy 结果，不抛异常）
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from dreambuddy_dal.connection import get_sqlite_connection
from dreambuddy_dal.implementations.sqlite_unified.schema_init import init_db_schema


@pytest.fixture
def clean_env():
    """清理单例 + 环境变量，保证每个测试隔离。"""
    from dreambuddy_dal import di
    di._INSTANCES.clear()
    di._sqlite_schema_inited_paths.clear()
    old_vals = {
        k: os.environ.pop(k, None)
        for k in ("DB_BACKEND", "READ_SOURCE", "DATA_DIR", "DAL_DB_PATH")
    }
    yield
    di._INSTANCES.clear()
    di._sqlite_schema_inited_paths.clear()
    for k, v in old_vals.items():
        if v is not None:
            os.environ[k] = v


@pytest.fixture
def db_paths():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        data_dir = root / "data"
        data_dir.mkdir()
        db = root / "dreambuddy_core.db"
        with get_sqlite_connection(str(db)) as conn:
            init_db_schema(conn)
        os.environ["DATA_DIR"] = str(data_dir)
        os.environ["DAL_DB_PATH"] = str(db)
        yield str(db)


# ===========================================================================
# 1. READ_SOURCE 未设 → 无 shadow read 审计行
# ===========================================================================
def test_no_shadow_read_when_env_unset(clean_env, db_paths):
    from dreambuddy_dal import di
    os.environ["DB_BACKEND"] = "dual_write"
    repo = di.get_trade_repo()
    # 做一次读操作
    repo.get_trade("nonexistent_id")
    # ma_migration_audit 不应有 shadow_read 行
    with get_sqlite_connection(db_paths) as conn:
        rows = conn.execute(
            "SELECT COUNT(*) FROM ma_migration_audit WHERE category='shadow_read'"
        ).fetchone()
    assert rows[0] == 0


# ===========================================================================
# 2. READ_SOURCE=shadow → 读后出现 shadow_read 审计行
# ===========================================================================
def test_shadow_read_writes_audit_when_enabled(clean_env, db_paths):
    from dreambuddy_dal import di
    os.environ["DB_BACKEND"] = "dual_write"
    os.environ["READ_SOURCE"] = "shadow"
    repo = di.get_trade_repo()
    # 做一次读操作
    repo.get_trade("nonexistent_id_2")
    # ma_migration_audit 应至少 1 条 shadow_read
    with get_sqlite_connection(db_paths) as conn:
        rows = conn.execute(
            "SELECT COUNT(*) FROM ma_migration_audit WHERE category='shadow_read'"
        ).fetchone()
    assert rows[0] >= 1


# ===========================================================================
# 3. 两端结果一致（都返回 None / 空列表）→ result=MATCH
# ===========================================================================
def test_shadow_read_match_when_both_none(clean_env, db_paths):
    from dreambuddy_dal import di
    os.environ["DB_BACKEND"] = "dual_write"
    os.environ["READ_SOURCE"] = "shadow"
    repo = di.get_trade_repo()
    repo.get_trade("both_none_id")
    with get_sqlite_connection(db_paths) as conn:
        rows = conn.execute(
            "SELECT result FROM ma_migration_audit WHERE category='shadow_read' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert rows is not None
    assert rows[0] == "MATCH"


# ===========================================================================
# 4. READ_SOURCE=next_gen → 读走新库（不走 legacy）
# ===========================================================================
def test_read_source_next_gen_uses_new_repo(clean_env, db_paths):
    from dreambuddy_dal import di
    from dreambuddy_dal.unified_models import TradeRecord, TradeDirection
    from decimal import Decimal
    from datetime import datetime, timezone
    os.environ["DB_BACKEND"] = "dual_write"
    os.environ["READ_SOURCE"] = "next_gen"
    # 先写入一条 trade（双写）
    repo = di.get_trade_repo()
    t = TradeRecord(
        trade_id="next_gen_test_1",
        sub_system="YIJING",
        strategy_name="test_strategy",
        symbol="BTC",
        direction=TradeDirection.LONG,
        entry_price=Decimal("50000"),
        quantity=Decimal("0.01"),
        entry_ts=datetime(2026, 8, 24, tzinfo=timezone.utc),
        stop_loss=Decimal("48000"),
        take_profit=Decimal("55000"),
        risk_level_cn="低风险",
    )
    repo.add_trade(t)
    # 读走新库：应该能拿到
    result = repo.get_trade("next_gen_test_1")
    assert result is not None
    assert result.trade_id == "next_gen_test_1"
