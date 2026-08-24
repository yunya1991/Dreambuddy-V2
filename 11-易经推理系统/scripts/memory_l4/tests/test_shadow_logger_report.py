"""T_B4 验收测试：get_comparison_report() 评估报告

位置: scripts/memory_l4/tests/test_shadow_logger_report.py
运行: cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4 && python -m pytest tests/test_shadow_logger_report.py -v

对应 Plan §T_B4: get_comparison_report() 评估报告。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Add bcrm2 to sys.path
THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))

from bcrm2.storage import EvolutionStorageSQLite
from bcrm2.shadow_logger import ShadowLogger


@pytest.fixture
def tmp_storage(tmp_path) -> EvolutionStorageSQLite:
    """临时空 SQLite。"""
    db_path = tmp_path / "evo_shadow_report_test.db"
    storage = EvolutionStorageSQLite(db_path)
    yield storage
    storage.close()


def _make_logger(storage):
    """构造 ShadowLogger（报告只读 storage，predictor/mapper 用 mock）。"""
    return ShadowLogger(storage, MagicMock(), MagicMock())


def _save_record(storage, symbol, **fields):
    """直接通过 storage.save_shadow_log 插入一条已知值的记录。"""
    record = {
        "reactive_L": 0.5,
        "reactive_T": 0.1,
        "reactive_C": 0.7,
        "reactive_regime": "TREND_UP_STRONG",
        "reactive_pos_mult": 1.0,
        "reactive_tp_mult": 1.0,
        "reactive_sl_mult": 1.0,
        "reactive_threshold": 1.0,
        "forecast_L": 0.6,
        "forecast_T": 0.15,
        "forecast_global_ranges": json.dumps({
            "global_position_mult": [0.8, 1.2],
            "long_threshold_mult": [0.9, 1.1],
            "short_threshold_mult": [0.8, 1.0],
        }),
        "forecast_sector_weights": json.dumps({"defi": 0.3}),
        "actual_direction": "LONG",
        "actual_confidence": 0.75,
        "actual_position_usdt": 100.0,
        "actual_tp_px": 72000.0,
        "actual_sl_px": 68000.0,
        "actual_threshold": 0.65,
    }
    record.update(fields)
    storage.save_shadow_log(symbol, record)


# ================================================================
# T_B4: get_comparison_report() 评估报告
# ================================================================

class TestShadowLoggerReport:
    """验证 get_comparison_report() 评估报告。"""

    def test_empty_records_returns_zero(self, tmp_storage):
        """T_B4.1: 无记录时返回 total_records=0。"""
        logger = _make_logger(tmp_storage)
        report = logger.get_comparison_report("BTC", days=7)

        assert report["symbol"] == "BTC"
        assert report["days"] == 7
        assert report["total_records"] == 0
        assert report["would_change_decision"]["direction_changes"] == 0
        assert report["would_change_decision"]["threshold_changes"] == 0
        assert report["would_change_decision"]["position_changes"] == 0
        assert report["direction_consistency"] == 0.0
        assert report["regime_distribution"] == {}

    def test_param_diff_stats_structure(self, tmp_storage):
        """T_B4.2: 有记录时返回正确的 param_diff_stats 结构。"""
        logger = _make_logger(tmp_storage)
        _save_record(tmp_storage, "BTC", reactive_L=0.5, forecast_L=0.6)

        report = logger.get_comparison_report("BTC", days=7)

        assert report["total_records"] == 1
        assert "L" in report["param_diff_stats"]
        assert "T" in report["param_diff_stats"]
        for key in ("mean_diff", "std_diff", "max_diff"):
            assert key in report["param_diff_stats"]["L"]
            assert key in report["param_diff_stats"]["T"]

    def test_L_diff_stats_correct(self, tmp_storage):
        """T_B4.3: L 差异 mean/std/max 计算正确。"""
        logger = _make_logger(tmp_storage)
        # 3 条记录: diffs = [0.1, 0.3, -0.1]
        _save_record(tmp_storage, "BTC", reactive_L=0.5, forecast_L=0.6)  # diff=+0.1
        _save_record(tmp_storage, "BTC", reactive_L=0.4, forecast_L=0.7)  # diff=+0.3
        _save_record(tmp_storage, "BTC", reactive_L=0.6, forecast_L=0.5)  # diff=-0.1

        report = logger.get_comparison_report("BTC", days=7)
        L_stats = report["param_diff_stats"]["L"]

        # mean = (0.1 + 0.3 - 0.1) / 3 = 0.1
        assert L_stats["mean_diff"] == pytest.approx(0.1, abs=1e-4)
        # max_abs = max(|0.1|, |0.3|, |0.1|) = 0.3
        assert L_stats["max_diff"] == pytest.approx(0.3, abs=1e-4)
        # std (population) = sqrt(((0)^2 + (0.2)^2 + (-0.2)^2) / 3) = sqrt(0.08/3) ≈ 0.1633
        assert L_stats["std_diff"] == pytest.approx(0.1633, abs=0.01)

    def test_would_change_decision_all_types(self, tmp_storage):
        """T_B4.4: would_change_decision 统计正确（方向/阈值/仓位变化）。"""
        logger = _make_logger(tmp_storage)

        # 记录1: 方向变化（reactive_L 正, forecast_L 负）
        _save_record(tmp_storage, "BTC",
                     reactive_L=0.5, forecast_L=-0.3,
                     reactive_threshold=1.0, reactive_pos_mult=1.0,
                     forecast_global_ranges=json.dumps({
                         "global_position_mult": [0.8, 1.2],
                         "long_threshold_mult": [0.9, 1.1],
                         "short_threshold_mult": [0.8, 1.0],
                     }))

        # 记录2: 阈值变化（forecast long_threshold 中位 0.6, reactive 1.0 → diff=0.4 > 0.1）
        _save_record(tmp_storage, "BTC",
                     reactive_L=0.5, forecast_L=0.6,
                     reactive_threshold=1.0, reactive_pos_mult=1.0,
                     forecast_global_ranges=json.dumps({
                         "global_position_mult": [0.8, 1.2],
                         "long_threshold_mult": [0.5, 0.7],
                         "short_threshold_mult": [0.8, 1.0],
                     }))

        # 记录3: 仓位变化（forecast position 中位 1.75, reactive 1.0 → diff=0.75 > 0.1）
        _save_record(tmp_storage, "BTC",
                     reactive_L=0.5, forecast_L=0.6,
                     reactive_threshold=1.0, reactive_pos_mult=1.0,
                     forecast_global_ranges=json.dumps({
                         "global_position_mult": [1.5, 2.0],
                         "long_threshold_mult": [0.9, 1.1],
                         "short_threshold_mult": [0.8, 1.0],
                     }))

        # 记录4: 无变化
        _save_record(tmp_storage, "BTC",
                     reactive_L=0.5, forecast_L=0.6,
                     reactive_threshold=1.0, reactive_pos_mult=1.0,
                     forecast_global_ranges=json.dumps({
                         "global_position_mult": [0.8, 1.2],
                         "long_threshold_mult": [0.9, 1.1],
                         "short_threshold_mult": [0.8, 1.0],
                     }))

        report = logger.get_comparison_report("BTC", days=7)
        wcd = report["would_change_decision"]

        assert wcd["direction_changes"] == 1
        assert wcd["threshold_changes"] == 1
        assert wcd["position_changes"] == 1

    def test_direction_consistency(self, tmp_storage):
        """T_B4.5: direction_consistency 计算正确。"""
        logger = _make_logger(tmp_storage)
        # 3 条同方向, 1 条不同方向 → 3/4 = 0.75
        _save_record(tmp_storage, "BTC", reactive_L=0.5, forecast_L=0.6)   # same
        _save_record(tmp_storage, "BTC", reactive_L=0.4, forecast_L=0.7)   # same
        _save_record(tmp_storage, "BTC", reactive_L=0.6, forecast_L=0.5)   # same
        _save_record(tmp_storage, "BTC", reactive_L=0.5, forecast_L=-0.3)   # diff

        report = logger.get_comparison_report("BTC", days=7)
        assert report["direction_consistency"] == pytest.approx(0.75, abs=1e-4)

    def test_regime_distribution(self, tmp_storage):
        """T_B4.6: regime_distribution 统计正确。"""
        logger = _make_logger(tmp_storage)
        _save_record(tmp_storage, "BTC", reactive_regime="TREND_UP_STRONG")
        _save_record(tmp_storage, "BTC", reactive_regime="TREND_UP_STRONG")
        _save_record(tmp_storage, "BTC", reactive_regime="RANGE_BOUND")
        _save_record(tmp_storage, "BTC", reactive_regime="TREND_DOWN_WEAK")

        report = logger.get_comparison_report("BTC", days=7)
        dist = report["regime_distribution"]

        assert dist["TREND_UP_STRONG"] == 2
        assert dist["RANGE_BOUND"] == 1
        assert dist["TREND_DOWN_WEAK"] == 1
