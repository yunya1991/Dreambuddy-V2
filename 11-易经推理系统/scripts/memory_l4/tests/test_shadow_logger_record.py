"""T_B3 验收测试：record_polling() 记录逻辑

位置: scripts/memory_l4/tests/test_shadow_logger_record.py
运行: cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4 && python -m pytest tests/test_shadow_logger_record.py -v

对应 Plan §T_B3: record_polling() 记录逻辑。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add bcrm2 to sys.path
THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))

from bcrm2.storage import EvolutionStorageSQLite
from bcrm2.shadow_logger import ShadowLogger, SHADOW_LOGGER_ENABLED


@pytest.fixture
def tmp_storage(tmp_path) -> EvolutionStorageSQLite:
    """临时空 SQLite。"""
    db_path = tmp_path / "evo_shadow_rec_test.db"
    storage = EvolutionStorageSQLite(db_path)
    yield storage
    storage.close()


def _make_inference(**overrides) -> dict:
    """构造一条 BCRM 2.0 推理结果 dict。"""
    inf = {
        "snapshot": {
            "level_smooth": 0.6,
            "trend_smooth": 0.15,
            "consensus": 0.72,
        },
        "_regime_pred": "TREND_UP_STRONG",
        "_regime_multipliers": {
            "position_mult": 1.2,
            "tp_mult": 1.0,
            "sl_mult": 0.8,
            "threshold_mult": 0.65,
        },
        "direction": "LONG",
        "confidence": 0.78,
        "position_usdt": 150.0,
        "take_profit_px": 72500.0,
        "stop_loss_px": 68000.0,
    }
    inf.update(overrides)
    return inf


def _make_actual_params() -> dict:
    """构造实际交易参数。"""
    return {
        "direction": "LONG",
        "confidence": 0.78,
        "position_usdt": 150.0,
        "tp_px": 72500.0,
        "sl_px": 68000.0,
        "threshold": 0.65,
    }


def _make_mock_predictor(forecast_values=None, ok=True):
    """构造 mock MorphCyclePredictor。

    ★ FIX: 同时 mock predict 和 predict_with_fallback，因为
    _compute_forecast_params() 优先调用 predict_with_fallback（若存在）。
    MagicMock 会自动创建该属性导致测试拿到 MagicMock 而非预期 dict。
    """
    mock = MagicMock()
    if forecast_values is None:
        forecast_values = [0.70, 0.75, 0.80, 0.83, 0.85]
    _ret = {
        "ok": ok,
        "series": {
            "forecast": forecast_values,
        },
    }
    mock.predict.return_value = _ret
    mock.predict_with_fallback.return_value = _ret
    return mock


def _make_mock_mapper():
    """构造 mock ParameterMapper。"""
    mock = MagicMock()
    mock.map_global_parameters.return_value = {
        "global_position_mult": (0.8, 1.5),
        "ls_ratio_cap": (0.3, 0.7),
        "long_bias": (0.5, 0.8),
        "short_bias": (0.2, 0.5),
        "long_threshold_mult": (0.9, 1.2),
        "short_threshold_mult": (0.8, 1.1),
    }
    mock.map_sector_weights.return_value = {
        "defi": 0.25, "ai": 0.30, "rwa": 0.15, "meme": 0.10, "l2": 0.20,
    }
    return mock


# ================================================================
# T_B3: record_polling() 记录逻辑
# ================================================================

class TestShadowLoggerRecord:
    """验证 record_polling() 核心记录逻辑。"""

    def test_disabled_returns_none(self, tmp_storage):
        """T_B3.1: 开关关闭时返回 None。"""
        mock_predictor = _make_mock_predictor()
        mock_mapper = _make_mock_mapper()
        logger = ShadowLogger(tmp_storage, mock_predictor, mock_mapper)

        # 显式 patch 为 False（测试开关关闭路径）
        with patch("bcrm2.shadow_logger.SHADOW_LOGGER_ENABLED", False):
            result = logger.record_polling("BTC", _make_inference(), _make_actual_params())
        assert result is None

    def test_enabled_returns_record_id(self, tmp_storage):
        """T_B3.2: 开关开启时返回记录 id（int）。"""
        mock_predictor = _make_mock_predictor()
        mock_mapper = _make_mock_mapper()
        logger = ShadowLogger(tmp_storage, mock_predictor, mock_mapper)

        with patch("bcrm2.shadow_logger.SHADOW_LOGGER_ENABLED", True):
            result = logger.record_polling("BTC", _make_inference(), _make_actual_params())

        assert result is not None
        assert isinstance(result, int)
        assert result > 0

    def test_reactive_L_from_snapshot(self, tmp_storage):
        """T_B3.3: 记录的 reactive_L 来自 inference.snapshot.level_smooth。"""
        mock_predictor = _make_mock_predictor()
        mock_mapper = _make_mock_mapper()
        logger = ShadowLogger(tmp_storage, mock_predictor, mock_mapper)

        inference = _make_inference()
        inference["snapshot"]["level_smooth"] = 0.85

        with patch("bcrm2.shadow_logger.SHADOW_LOGGER_ENABLED", True):
            logger.record_polling("BTC", inference, _make_actual_params())

        loaded = tmp_storage.get_shadow_log("BTC", days=7)
        assert len(loaded) == 1
        assert loaded[0]["reactive_L"] == 0.85

    def test_forecast_L_from_predictor(self, tmp_storage):
        """T_B3.4: 记录的 forecast_L 来自 predictor.predict().forecast[-1]。"""
        forecast_values = [0.70, 0.75, 0.80, 0.83, 0.92]
        mock_predictor = _make_mock_predictor(forecast_values=forecast_values)
        mock_mapper = _make_mock_mapper()
        logger = ShadowLogger(tmp_storage, mock_predictor, mock_mapper)

        with patch("bcrm2.shadow_logger.SHADOW_LOGGER_ENABLED", True):
            logger.record_polling("BTC", _make_inference(), _make_actual_params())

        loaded = tmp_storage.get_shadow_log("BTC", days=7)
        assert len(loaded) == 1
        # forecast[-1] = 0.92
        assert loaded[0]["forecast_L"] == pytest.approx(0.92)

    def test_forecast_cache_hit(self, tmp_storage):
        """T_B3.5: forecast 缓存命中（同 symbol 1h 内不重算）。"""
        mock_predictor = _make_mock_predictor()
        mock_mapper = _make_mock_mapper()
        logger = ShadowLogger(tmp_storage, mock_predictor, mock_mapper)

        with patch("bcrm2.shadow_logger.SHADOW_LOGGER_ENABLED", True):
            # 第一次调用
            logger.record_polling("BTC", _make_inference(), _make_actual_params())
            # 第二次调用（同 symbol，应命中缓存）
            logger.record_polling("BTC", _make_inference(), _make_actual_params())

        # predictor 只被调用 1 次（缓存命中，predict 或 predict_with_fallback 均算）
        _total_calls = mock_predictor.predict.call_count + mock_predictor.predict_with_fallback.call_count
        assert _total_calls == 1

        # 两条记录都存在
        loaded = tmp_storage.get_shadow_log("BTC", days=7)
        assert len(loaded) == 2

    def test_predict_failure_fallback_zero(self, tmp_storage):
        """T_B3.6: 预测失败时用 0.0 兜底。"""
        mock_predictor = MagicMock()
        _fail_ret = {"ok": False, "series": {}}
        mock_predictor.predict.return_value = _fail_ret
        mock_predictor.predict_with_fallback.return_value = _fail_ret
        mock_mapper = _make_mock_mapper()
        logger = ShadowLogger(tmp_storage, mock_predictor, mock_mapper)

        with patch("bcrm2.shadow_logger.SHADOW_LOGGER_ENABLED", True):
            logger.record_polling("BTC", _make_inference(), _make_actual_params())

        loaded = tmp_storage.get_shadow_log("BTC", days=7)
        assert len(loaded) == 1
        assert loaded[0]["forecast_L"] == 0.0

    def test_actual_params_written(self, tmp_storage):
        """T_B3.7: actual_params 字段完整写入。"""
        mock_predictor = _make_mock_predictor()
        mock_mapper = _make_mock_mapper()
        logger = ShadowLogger(tmp_storage, mock_predictor, mock_mapper)

        actual = _make_actual_params()
        actual["direction"] = "SHORT"
        actual["confidence"] = 0.65
        actual["position_usdt"] = 80.0
        actual["tp_px"] = 65000.0
        actual["sl_px"] = 70000.0
        actual["threshold"] = 0.60

        with patch("bcrm2.shadow_logger.SHADOW_LOGGER_ENABLED", True):
            logger.record_polling("BTC", _make_inference(), actual)

        loaded = tmp_storage.get_shadow_log("BTC", days=7)
        assert len(loaded) == 1
        row = loaded[0]
        assert row["actual_direction"] == "SHORT"
        assert row["actual_confidence"] == 0.65
        assert row["actual_position_usdt"] == 80.0
        assert row["actual_tp_px"] == 65000.0
        assert row["actual_sl_px"] == 70000.0
        assert row["actual_threshold"] == 0.60
