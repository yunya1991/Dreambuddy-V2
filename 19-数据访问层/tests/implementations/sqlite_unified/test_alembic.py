"""
TDD：P2-4 Alembic 首版接入验证
================================
验证 Alembic 迁移链结构正确性 + revision 文件可导入 + upgrade 可执行。
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from dreambuddy_dal.connection import get_sqlite_connection


def test_alembic_revision_file_exists():
    """revision 文件存在且 revision_id 正确。"""
    base = Path(__file__).resolve().parents[3]  # 19-数据访问层/
    rev_path = base / "dreambuddy_dal" / "migrations" / "versions" / "0001_v1_initial_schema.py"
    assert rev_path.exists(), f"revision file not found: {rev_path}"


def test_alembic_config_exists():
    """alembic.ini 存在且 script_location 正确。"""
    base = Path(__file__).resolve().parents[3]
    ini_path = base / "dreambuddy_dal" / "migrations" / "alembic.ini"
    assert ini_path.exists()


def test_alembic_upgrade_creates_schema():
    """alembic upgrade head → 21 表全部创建 + 种子数据存在。"""
    from alembic.config import Config
    from alembic import command

    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test_alembic.db"
        os_env = {"DAL_DB_PATH": str(db_path), "DATA_DIR": str(td)}

        import os
        old_vals = {k: os.environ.get(k) for k in os_env}
        os.environ.update(os_env)
        try:
            base = Path(__file__).resolve().parents[3]
            ini = base / "dreambuddy_dal" / "migrations" / "alembic.ini"
            cfg = Config(str(ini))
            cfg.set_main_option(
                "script_location",
                str(base / "dreambuddy_dal" / "migrations"),
            )
            command.upgrade(cfg, "head")
        finally:
            for k, v in old_vals.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

        # 验证表存在
        with get_sqlite_connection(str(db_path)) as conn:
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()]
            for expected in [
                "ma_schema_version", "ma_migration_audit", "ma_integrity_log",
                "tr_trades", "tr_daily_stats", "tr_daily_stats_overrides",
                "po_positions", "po_price_refresh_log",
                "rs_state", "rs_cases",
                "cv_config_versions",
                "kg_entities", "kg_entity_aliases", "kg_triples",
            ]:
                assert expected in tables, f"表 {expected} 未创建，实际: {tables}"

            # 验证种子数据（单行表 CHECK id=1）
            (cnt,) = conn.execute(
                "SELECT COUNT(*) FROM ma_schema_version"
            ).fetchone()
            assert cnt == 1, f"种子数据期望 1 行（单行表），实际: {cnt}"

            (semver,) = conn.execute(
                "SELECT schema_semver FROM ma_schema_version WHERE id=1"
            ).fetchone()
            assert semver == "1.0.0"

            (rs_cnt,) = conn.execute(
                "SELECT COUNT(*) FROM rs_state WHERE id=1"
            ).fetchone()
            assert rs_cnt == 1
