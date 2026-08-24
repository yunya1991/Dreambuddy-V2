"""T_B1 验收测试：shadow_param_log 表 + CRUD

位置: scripts/memory_l4/tests/test_shadow_logger_storage.py
运行: cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4 && python -m pytest tests/test_shadow_logger_storage.py -v

对应 Plan §T_B1: shadow_param_log 表 + CRUD 方法。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Add bcrm2 to sys.path
THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))

from bcrm2.storage import EvolutionStorageSQLite


@pytest.fixture
def tmp_storage(tmp_path) -> EvolutionStorageSQLite:
    """临时空 SQLite。"""
    db_path = tmp_path / "evo_shadow_test.db"
    storage = EvolutionStorageSQLite(db_path)
    yield storage
    storage.close()


def _make_record(**overrides) -> dict:
    """构造一条完整的 shadow_param_log 记录。"""
    rec = {
        # reactive 参数
        "reactive_L": 0.6,
        "reactive_T": 0.15,
        "reactive_C": 0.72,
        "reactive_regime": "TREND_UP_STRONG",
        "reactive_pos_mult": 1.2,
        "reactive_tp_mult": 1.0,
        "reactive_sl_mult": 0.8,
        "reactive_threshold": 0.65,
        # forecast 参数
        "forecast_L": 0.85,
        "forecast_T": 0.25,
        "forecast_global_ranges": json.dumps(
            {"global_position_mult": [0.8, 1.5], "ls_ratio_cap": [0.3, 0.7]}),
        "forecast_sector_weights": json.dumps(
            {"defi": 0.25, "ai": 0.30, "rwa": 0.15, "meme": 0.10, "l2": 0.20}),
        # actual 交易参数
        "actual_direction": "LONG",
        "actual_confidence": 0.78,
        "actual_position_usdt": 150.0,
        "actual_tp_px": 72500.0,
        "actual_sl_px": 68000.0,
        "actual_threshold": 0.65,
    }
    rec.update(overrides)
    return rec


# ================================================================
# T_B1: shadow_param_log 表 + CRUD
# ================================================================

class TestShadowLogStorage:
    """验证 save_shadow_log / get_shadow_log / get_shadow_log_count / clear_shadow_log 方法。"""

    def test_save_shadow_log_method_exists(self, tmp_storage):
        """T_B1.1: storage 有 save_shadow_log 方法。"""
        assert hasattr(tmp_storage, "save_shadow_log")

    def test_save_and_get_shadow_log(self, tmp_storage):
        """T_B1.2: 保存后能查询到记录。"""
        rec_id = tmp_storage.save_shadow_log("BTCUSDT", _make_record())
        assert rec_id is not None
        assert isinstance(rec_id, int)
        assert rec_id > 0

        loaded = tmp_storage.get_shadow_log("BTCUSDT", days=7)
        assert len(loaded) == 1
        assert loaded[0]["reactive_L"] == 0.6
        assert loaded[0]["forecast_L"] == 0.85
        assert loaded[0]["actual_direction"] == "LONG"

    def test_get_shadow_log_days_filter(self, tmp_storage):
        """T_B1.3: 查询最近 N 天返回正确数量。"""
        # 保存 3 条记录
        for i in range(3):
            tmp_storage.save_shadow_log("BTCUSDT", _make_record(
                reactive_L=0.6 + i * 0.1))

        # 查询最近 7 天
        loaded = tmp_storage.get_shadow_log("BTCUSDT", days=7)
        assert len(loaded) == 3

        # 查询最近 0 天（应该返回空或当天）
        loaded_0 = tmp_storage.get_shadow_log("BTCUSDT", days=0)
        # days=0 表示今天，刚保存的应该能看到
        # 但具体行为取决于实现，至少不报错
        assert isinstance(loaded_0, list)

    def test_get_shadow_log_count(self, tmp_storage):
        """T_B1.4: get_shadow_log_count 返回正确总数。"""
        assert tmp_storage.get_shadow_log_count("BTCUSDT") == 0

        tmp_storage.save_shadow_log("BTCUSDT", _make_record())
        tmp_storage.save_shadow_log("BTCUSDT", _make_record())
        tmp_storage.save_shadow_log("ETHUSDT", _make_record())

        assert tmp_storage.get_shadow_log_count("BTCUSDT") == 2
        assert tmp_storage.get_shadow_log_count("ETHUSDT") == 1

    def test_clear_shadow_log(self, tmp_storage):
        """T_B1.5: clear_shadow_log 清除后查询返回空。"""
        tmp_storage.save_shadow_log("BTCUSDT", _make_record())
        tmp_storage.save_shadow_log("BTCUSDT", _make_record())
        assert tmp_storage.get_shadow_log_count("BTCUSDT") == 2

        tmp_storage.clear_shadow_log("BTCUSDT")
        assert tmp_storage.get_shadow_log_count("BTCUSDT") == 0
        assert tmp_storage.get_shadow_log("BTCUSDT", days=7) == []

    def test_field_completeness(self, tmp_storage):
        """T_B1.6: 字段完整性（reactive/forecast/actual 三组字段都存在）。"""
        rec = _make_record()
        tmp_storage.save_shadow_log("BTCUSDT", rec)

        loaded = tmp_storage.get_shadow_log("BTCUSDT", days=7)
        assert len(loaded) == 1
        row = loaded[0]

        # reactive 字段
        assert row["reactive_L"] == rec["reactive_L"]
        assert row["reactive_T"] == rec["reactive_T"]
        assert row["reactive_C"] == rec["reactive_C"]
        assert row["reactive_regime"] == rec["reactive_regime"]
        assert row["reactive_pos_mult"] == rec["reactive_pos_mult"]
        assert row["reactive_tp_mult"] == rec["reactive_tp_mult"]
        assert row["reactive_sl_mult"] == rec["reactive_sl_mult"]
        assert row["reactive_threshold"] == rec["reactive_threshold"]

        # forecast 字段
        assert row["forecast_L"] == rec["forecast_L"]
        assert row["forecast_T"] == rec["forecast_T"]
        assert row["forecast_global_ranges"] == rec["forecast_global_ranges"]
        assert row["forecast_sector_weights"] == rec["forecast_sector_weights"]

        # actual 字段
        assert row["actual_direction"] == rec["actual_direction"]
        assert row["actual_confidence"] == rec["actual_confidence"]
        assert row["actual_position_usdt"] == rec["actual_position_usdt"]
        assert row["actual_tp_px"] == rec["actual_tp_px"]
        assert row["actual_sl_px"] == rec["actual_sl_px"]
        assert row["actual_threshold"] == rec["actual_threshold"]

        # symbol 和 timestamp
        assert row["symbol"] == "BTCUSDT"
        assert "timestamp" in row
