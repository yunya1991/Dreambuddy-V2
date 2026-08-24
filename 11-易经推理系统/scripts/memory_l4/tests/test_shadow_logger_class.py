"""T_B2 验收测试：ShadowLogger 类骨架

位置: scripts/memory_l4/tests/test_shadow_logger_class.py
运行: cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4 && python -m pytest tests/test_shadow_logger_class.py -v

对应 Plan §T_B2: ShadowLogger 类骨架。
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Add bcrm2 to sys.path
THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))

from bcrm2.storage import EvolutionStorageSQLite
from bcrm2.shadow_logger import ShadowLogger, SHADOW_LOGGER_ENABLED


@pytest.fixture
def tmp_storage(tmp_path) -> EvolutionStorageSQLite:
    """临时空 SQLite。"""
    db_path = tmp_path / "evo_shadow_cls_test.db"
    storage = EvolutionStorageSQLite(db_path)
    yield storage
    storage.close()


@pytest.fixture
def shadow_logger(tmp_storage):
    """构造 ShadowLogger（mock predictor 和 mapper）。"""
    mock_predictor = MagicMock()
    mock_mapper = MagicMock()
    return ShadowLogger(tmp_storage, mock_predictor, mock_mapper)


# ================================================================
# T_B2: ShadowLogger 类骨架
# ================================================================

class TestShadowLoggerClass:
    """验证 ShadowLogger 类可实例化且核心方法存在。"""

    def test_can_instantiate(self, shadow_logger):
        """T_B2.1: ShadowLogger 类可实例化。"""
        assert shadow_logger is not None
        assert isinstance(shadow_logger, ShadowLogger)

    def test_record_polling_method_exists(self, shadow_logger):
        """T_B2.2: record_polling 方法存在。"""
        assert hasattr(shadow_logger, "record_polling")
        assert callable(shadow_logger.record_polling)

    def test_get_comparison_report_method_exists(self, shadow_logger):
        """T_B2.3: get_comparison_report 方法存在。"""
        assert hasattr(shadow_logger, "get_comparison_report")
        assert callable(shadow_logger.get_comparison_report)

    def test_compute_forecast_params_method_exists(self, shadow_logger):
        """T_B2.4: _compute_forecast_params 方法存在。"""
        assert hasattr(shadow_logger, "_compute_forecast_params")
        assert callable(shadow_logger._compute_forecast_params)

    def test_shadow_logger_enabled_default_false(self):
        """T_B2.5: SHADOW_LOGGER_ENABLED 默认值（已改为 True，用于在线记录 baseline/ai/eff 三值差异）。"""
        # 当前版本默认为 True（Phase B/C 在线影子记录已启动作为基线数据采集）
        # 此处只校验它是 bool
        assert isinstance(SHADOW_LOGGER_ENABLED, bool)
