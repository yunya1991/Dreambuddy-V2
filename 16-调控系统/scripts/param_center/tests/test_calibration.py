"""任务③ TDD 测试：影子模式参数校准

测试目标:
  1. CalibrationAnalyzer 偏差统计正确
  2. 样本不足时不触发校准
  3. 偏差超阈值时触发校准
  4. 校准参数满足硬约束 (SL≥4%, TP≥12%, RR≥2)
  5. calibrate_with_verifier 端到端跑通

运行:
  python -m pytest 16-调控系统/scripts/param_center/tests/test_calibration.py -v
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# 路径设置
_THIS = Path(__file__).resolve()
_PARAM_CENTER = _THIS.parent.parent
_SCRIPTS_16 = _PARAM_CENTER.parent
_PROJECT_ROOT = _SCRIPTS_16.parent.parent
_YIJING_SCRIPTS = _PROJECT_ROOT / "11-易经推理系统" / "scripts"
for p in [_YIJING_SCRIPTS, _SCRIPTS_16, _PARAM_CENTER]:
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)

from param_center.calibration import (  # noqa: E402
    CalibrationAnalyzer,
    CalibrationProposal,
    DeviationStats,
    MIN_SAMPLE_COUNT,
    DEVIATION_AVG_THRESHOLD,
    DEVIATION_STD_THRESHOLD,
)
from param_center.aggregator import (  # noqa: E402
    SL_FLOOR, TP_FLOOR, RR_FLOOR,
)


# ============================================================================
# Mock fixtures
# ============================================================================
def _make_record(symbol: str, rec_sl=0.04, act_sl=0.05, rec_tp=0.12, act_tp=0.15, dev=0.20):
    """构造一条影子记录"""
    return {
        "symbol": symbol.upper(),
        "timestamp": datetime.utcnow().isoformat(),
        "param_center_recommended": json.dumps({"sl_floor": rec_sl, "tp_floor": rec_tp, "atr_mult": 4.5}),
        "actual_used": json.dumps({"sl_floor": act_sl, "tp_floor": act_tp, "atr_mult": 4.5}),
        "deviation_pct": dev,
        "aggregator_weights": json.dumps({"hmm": 0.5, "bagua": 0.5}),
        "confidence": 0.7,
        "event_type": "polling",
    }


@pytest.fixture
def mock_shadow_logger():
    """构造一个 mock 的 ParamCenterShadowLogger"""
    shadow = MagicMock()
    shadow.query_deviation_report.return_value = []
    return shadow


@pytest.fixture
def populated_shadow_logger():
    """构造一个填满 30+ 条偏差记录的 mock logger"""
    shadow = MagicMock()
    # 30 条偏差记录，偏差均值 0.20（超过 0.15 阈值）
    records = [_make_record("BTC", dev=0.20 + 0.01 * i) for i in range(35)]
    shadow.query_deviation_report.return_value = records
    return shadow


# ============================================================================
# 测试用例
# ============================================================================
class TestCalibrationAnalyzer:
    """CalibrationAnalyzer 单元测试"""

    def test_analyze_empty_returns_zero_stats(self, mock_shadow_logger):
        """无影子数据时返回 sample_count=0 的统计"""
        analyzer = CalibrationAnalyzer(shadow_logger=mock_shadow_logger)
        stats = analyzer.analyze_deviation("BTC", days=30)
        assert stats.sample_count == 0
        assert stats.avg_deviation == 0.0

    def test_analyze_returns_valid_stats(self, populated_shadow_logger):
        """35 条记录时返回有效统计"""
        analyzer = CalibrationAnalyzer(shadow_logger=populated_shadow_logger)
        stats = analyzer.analyze_deviation("BTC", days=30)
        assert stats.sample_count == 35
        assert stats.avg_deviation > 0.0
        assert stats.max_deviation >= stats.min_deviation
        # avg_recommended 应有 sl_floor/tp_floor
        assert "sl_floor" in stats.avg_recommended
        assert "tp_floor" in stats.avg_actual

    def test_propose_no_calibration_when_sample_insufficient(self, mock_shadow_logger):
        """样本 < 30 时不触发校准"""
        # 10 条记录
        mock_shadow_logger.query_deviation_report.return_value = [
            _make_record("BTC", dev=0.30) for _ in range(10)
        ]
        analyzer = CalibrationAnalyzer(shadow_logger=mock_shadow_logger)
        proposal = analyzer.propose_calibration("BTC", days=30)
        assert not proposal.should_calibrate
        assert "样本不足" in proposal.reason
        assert proposal.stats.sample_count == 10

    def test_propose_no_calibration_when_deviation_stable(self, mock_shadow_logger):
        """样本充足但偏差稳定（< 15%）时不触发校准"""
        # 30 条偏差 0.05（远低于 0.15 阈值）
        mock_shadow_logger.query_deviation_report.return_value = [
            _make_record("BTC", dev=0.05) for _ in range(30)
        ]
        analyzer = CalibrationAnalyzer(shadow_logger=mock_shadow_logger)
        proposal = analyzer.propose_calibration("BTC", days=30)
        assert not proposal.should_calibrate
        assert "稳定" in proposal.reason

    def test_propose_calibration_when_deviation_high(self, populated_shadow_logger):
        """平均偏差 ≥ 15% 时触发校准"""
        analyzer = CalibrationAnalyzer(shadow_logger=populated_shadow_logger)
        proposal = analyzer.propose_calibration("BTC", days=30)
        assert proposal.should_calibrate
        assert "偏差触发" in proposal.reason
        assert proposal.calibrated_params["sl_floor"] >= SL_FLOOR
        assert proposal.calibrated_params["tp_floor"] >= TP_FLOOR
        # RR ≥ 2:1
        rr = proposal.calibrated_params["tp_floor"] / proposal.calibrated_params["sl_floor"]
        assert rr >= RR_FLOOR

    def test_propose_calibration_enforces_hard_constraints(self, mock_shadow_logger):
        """校准参数硬约束兜底：SL∈[4%, 15%], TP∈[12%, 30%]"""
        # 构造极端实际值：SL=0.30, TP=0.05（违反硬约束）
        records = []
        for i in range(35):
            records.append({
                "symbol": "BTC",
                "timestamp": datetime.utcnow().isoformat(),
                "param_center_recommended": json.dumps({"sl_floor": 0.04, "tp_floor": 0.12, "atr_mult": 4.5}),
                "actual_used": json.dumps({"sl_floor": 0.30, "tp_floor": 0.05, "atr_mult": 10.0}),
                "deviation_pct": 0.50,
                "aggregator_weights": "{}",
                "confidence": 0.5,
                "event_type": "polling",
            })
        mock_shadow_logger.query_deviation_report.return_value = records
        analyzer = CalibrationAnalyzer(shadow_logger=mock_shadow_logger)
        proposal = analyzer.propose_calibration("BTC", days=30)
        assert proposal.should_calibrate
        # 硬约束兜底
        assert 0.04 <= proposal.calibrated_params["sl_floor"] <= 0.15
        assert 0.12 <= proposal.calibrated_params["tp_floor"] <= 0.30
        assert 2.0 <= proposal.calibrated_params["atr_mult"] <= 8.0
        # RR ≥ 2:1
        rr = proposal.calibrated_params["tp_floor"] / proposal.calibrated_params["sl_floor"]
        assert rr >= RR_FLOOR


class TestCalibrateWithVerifier:
    """calibrate_with_verifier 端到端测试"""

    def test_no_calibration_short_circuits_verifier(self, mock_shadow_logger):
        """样本不足时跳过 verifier"""
        analyzer = CalibrationAnalyzer(shadow_logger=mock_shadow_logger)
        proposal, ver_result = analyzer.calibrate_with_verifier("BTC", days=30)
        assert not proposal.should_calibrate
        assert not ver_result.passed
        assert "无需校准" in ver_result.rollback_reason

    def test_calibration_with_mock_verifier_passes(self, populated_shadow_logger):
        """校准建议 + mock verifier 通过"""
        # 用 mock verifier 跳过真实回测
        mock_verifier = MagicMock()
        from param_center.verifier import VerificationResult
        mock_verifier.verify_and_upgrade.return_value = VerificationResult(
            passed=True,
            new_calmar=1.5,
            old_calmar=1.2,
            new_drawdown=0.30,
            version_bumped=True,
            ablation_p_value=0.5,
        )
        analyzer = CalibrationAnalyzer(shadow_logger=populated_shadow_logger)
        proposal, ver_result = analyzer.calibrate_with_verifier(
            "BTC", verifier=mock_verifier, days=30,
        )
        assert proposal.should_calibrate
        assert ver_result.passed
        assert ver_result.version_bumped
        # 确认 verifier 被调用
        assert mock_verifier.verify_and_upgrade.called
