"""RED 测试 — WashoutReversalGenome (洗盘反转基因组编排层).

Spec: docs/superpowers/specs/2026-09-22-washout-reversal-genome-design.md §3.3

阶段1 新增文件 (纯新增):
  - 1-ARCHITECTURE/dreamos/evolution/washout_reversal_genome.py
      — WashoutReversalGenome 主类 + WashoutReversalSignal

设计原则 (硬约束):
  - HC-G1: 信号走 evolution probe 仓路径
  - HC-G2: WashoutDetector conf≥0.80 才进入结束信号判定
  - HC-G6: 信号需 ≥ PROBE_THRESHOLD=0.55
  - HC-G7: 平仓后必须 record_case
  - confidence = washout_verdict.confidence*0.6 + ending_signal.confidence*0.4

TDD 测试清单:
  T1  / test_signal_dataclass_fields                     — WashoutReversalSignal 字段
  T2  / test_detect_signal_washout_high_confidence       — WASHOUT+conf≥0.80 → EndingDetector 调用
  T3  / test_detect_signal_weakness_skips_ending         — WEAKNESS → signal=NONE
  T4  / test_detect_signal_unknown_skips_ending           — UNKNOWN → signal=NONE
  T5  / test_detect_signal_low_confidence_skips          — conf<0.80 → signal=NONE
  T6  / test_confidence_calculation                       — confidence = wv*0.6 + es*0.4
  T7  / test_confidence_range                             — confidence ∈ [0, 1]
  T8  / test_record_case                                  — 平仓后案例入库
  T9  / test_evolve_sandbox_validate                     — 复用 _sandbox_validate
  T10 / test_evolve_no_sandbox                             — 无 sandbox → accepted=False
  T11 / test_enable_false_returns_none                    — enable=False → signal=NONE
  T12 / test_fail_open_exception                           — 异常 → signal=NONE
  T13 / test_no_llm_dependency                             — grep 确认无 LLM
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# ============================================================
# sys.path 设置
# ============================================================
_THIS_DIR = Path(__file__).resolve().parent
_BCRM2_SCRIPTS_ROOT = _THIS_DIR.parent.parent
_PROJECT_ROOT = _BCRM2_SCRIPTS_ROOT.parent.parent
_ARCH_ROOT = _PROJECT_ROOT / "1-ARCHITECTURE"

for _p in (_BCRM2_SCRIPTS_ROOT, _ARCH_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


# ============================================================
# 导入（RED 阶段：模块不存在时 ImportError）
# ============================================================
from dreamos.evolution.washout_reversal_genome import (  # noqa: E402
    WashoutReversalGenome,
    WashoutReversalSignal,
)
from dreamos.evolution.washout_ending_detector import (  # noqa: E402
    EndingSignal,
    WashoutEndingDetector,
)
from dreamos.evolution.washout_reversal_case_library import (  # noqa: E402
    WashoutReversalCaseLibrary,
)
from dreamos.evolution.washout_case_library import WashoutCase  # noqa: E402
from dreamos.evolution.washout_bayesian_updater import BayesianUpdater  # noqa: E402
from scripts.memory_l4.bcrm2.washout_detector import (  # noqa: E402
    WashoutDetector,
    WashoutLabel,
    WashoutVerdict,
)


# ============================================================
# 辅助函数: 构造 Mock WashoutDetector
# ============================================================
def _make_mock_washout_detector(
    label: WashoutLabel = WashoutLabel.WASHOUT,
    confidence: float = 0.85,
) -> MagicMock:
    """构造 Mock WashoutDetector, 返回指定 verdict."""
    detector = MagicMock(spec=WashoutDetector)
    verdict = WashoutVerdict(
        label=label,
        confidence=confidence,
        trigger_activated=True,
        feature_snapshot={"F1": 1.0},
        reason=f"mock_{label.value}_conf={confidence}",
        timestamp="2026-09-22T00:00:00+00:00",
    )
    detector.run.return_value = verdict
    return detector


def _make_ending_detector_stub(activated: bool = True, confidence: float = 0.75):
    """构造 stub WashoutEndingDetector."""
    detector = MagicMock(spec=WashoutEndingDetector)
    detector.check.return_value = EndingSignal(
        activated=activated,
        confidence=confidence,
        reason="stub_ending_signal",
        timestamp="2026-09-22T00:01:00+00:00",
    )
    return detector


def _make_test_df(n: int = 30) -> pd.DataFrame:
    """构造简单测试用 DataFrame."""
    import numpy as np
    rng = np.random.RandomState(42)
    idx = pd.date_range("2026-01-01", periods=n, freq="1H")
    return pd.DataFrame({
        "open": rng.randn(n) + 100,
        "high": rng.randn(n) + 101,
        "low": rng.randn(n) + 99,
        "close": rng.randn(n) + 100,
        "volume": rng.randn(n) * 100 + 1000,
    }, index=idx)


# ============================================================
# T1: WashoutReversalSignal dataclass
# ============================================================
class TestReversalSignalDataclass:
    def test_signal_dataclass_fields(self):
        """T1: WashoutReversalSignal 包含 direction, confidence, reason, timestamp."""
        verdict = WashoutVerdict.unknown()
        ending = EndingSignal.not_activated("test")
        sig = WashoutReversalSignal(
            direction="LONG",
            confidence=0.75,
            washout_verdict=verdict,
            ending_signal=ending,
            reason="test_reason",
            timestamp="2026-09-22T00:00:00+00:00",
        )
        assert sig.direction == "LONG"
        assert 0.0 <= sig.confidence <= 1.0
        assert isinstance(sig.reason, str)
        assert sig.washout_verdict is not None
        assert sig.ending_signal is not None


# ============================================================
# T2-T5: detect_signal 流程测试
# ============================================================
class TestDetectSignalFlow:
    def test_detect_signal_washout_high_confidence(self):
        """T2: WASHOUT+conf≥0.80 → EndingDetector 调用 → LONG signal."""
        mock_det = _make_mock_washout_detector(
            label=WashoutLabel.WASHOUT, confidence=0.85
        )
        ending_det = _make_ending_detector_stub(activated=True, confidence=0.75)
        genome = WashoutReversalGenome(
            washout_detector=mock_det,
            ending_detector=ending_det,
            case_library=WashoutReversalCaseLibrary(),
            bayesian_updater=BayesianUpdater(),
            enable=True,
        )
        df = _make_test_df()
        signal = genome.detect_signal("BTC", df, {"oi_current": 100})
        assert signal.direction == "LONG"
        assert signal.confidence > 0.0
        # EndingDetector 被调用
        ending_det.check.assert_called_once()

    def test_detect_signal_weakness_skips_ending(self):
        """T3: WEAKNESS → EndingDetector 不被调用, signal=NONE."""
        mock_det = _make_mock_washout_detector(
            label=WashoutLabel.WEAKNESS, confidence=0.90
        )
        ending_det = _make_ending_detector_stub()
        genome = WashoutReversalGenome(
            washout_detector=mock_det,
            ending_detector=ending_det,
            case_library=WashoutReversalCaseLibrary(),
            bayesian_updater=BayesianUpdater(),
            enable=True,
        )
        df = _make_test_df()
        signal = genome.detect_signal("BTC", df, {})
        assert signal.direction == "NONE"
        ending_det.check.assert_not_called()

    def test_detect_signal_unknown_skips_ending(self):
        """T4: UNKNOWN → signal=NONE."""
        mock_det = _make_mock_washout_detector(
            label=WashoutLabel.UNKNOWN, confidence=0.50
        )
        ending_det = _make_ending_detector_stub()
        genome = WashoutReversalGenome(
            washout_detector=mock_det,
            ending_detector=ending_det,
            case_library=WashoutReversalCaseLibrary(),
            bayesian_updater=BayesianUpdater(),
            enable=True,
        )
        df = _make_test_df()
        signal = genome.detect_signal("BTC", df, {})
        assert signal.direction == "NONE"

    def test_detect_signal_low_confidence_skips(self):
        """T5: WASHOUT but conf<0.80 → signal=NONE."""
        mock_det = _make_mock_washout_detector(
            label=WashoutLabel.WASHOUT, confidence=0.70  # < 0.80
        )
        ending_det = _make_ending_detector_stub()
        genome = WashoutReversalGenome(
            washout_detector=mock_det,
            ending_detector=ending_det,
            case_library=WashoutReversalCaseLibrary(),
            bayesian_updater=BayesianUpdater(),
            enable=True,
        )
        df = _make_test_df()
        signal = genome.detect_signal("BTC", df, {})
        assert signal.direction == "NONE"


# ============================================================
# T6-T7: confidence 计算
# ============================================================
class TestConfidenceCalculation:
    def test_confidence_calculation(self):
        """T6: confidence = wv.confidence*0.6 + es.confidence*0.4."""
        mock_det = _make_mock_washout_detector(confidence=0.90)
        ending_det = _make_ending_detector_stub(confidence=0.80)
        genome = WashoutReversalGenome(
            washout_detector=mock_det,
            ending_detector=ending_det,
            case_library=WashoutReversalCaseLibrary(),
            bayesian_updater=BayesianUpdater(),
            enable=True,
        )
        df = _make_test_df()
        signal = genome.detect_signal("BTC", df, {})
        expected = 0.90 * 0.6 + 0.80 * 0.4  # 0.54 + 0.32 = 0.86
        assert signal.confidence == pytest.approx(expected, abs=1e-6)

    def test_confidence_range(self):
        """T7: confidence 始终 ∈ [0, 1]."""
        mock_det = _make_mock_washout_detector(confidence=0.85)
        ending_det = _make_ending_detector_stub(confidence=0.75)
        genome = WashoutReversalGenome(
            washout_detector=mock_det,
            ending_detector=ending_det,
            case_library=WashoutReversalCaseLibrary(),
            bayesian_updater=BayesianUpdater(),
            enable=True,
        )
        df = _make_test_df()
        signal = genome.detect_signal("BTC", df, {})
        assert 0.0 <= signal.confidence <= 1.0


# ============================================================
# T8: record_case
# ============================================================
class TestRecordCase:
    def test_record_case(self):
        """T8: 平仓后案例入库."""
        lib = WashoutReversalCaseLibrary()
        mock_det = _make_mock_washout_detector()
        ending_det = _make_ending_detector_stub()
        genome = WashoutReversalGenome(
            washout_detector=mock_det,
            ending_detector=ending_det,
            case_library=lib,
            bayesian_updater=BayesianUpdater(),
            enable=True,
        )
        case = WashoutCase(
            case_id="test-rec-001",
            coin="BTC",
            entry_time="2026-09-22T00:00:00+00:00",
            exit_time="2026-09-22T12:00:00+00:00",
            features_snapshot={"F1": 1.0},
            actual_label="reversal_long_success",
            pnl_pct=0.05,
            reward=WashoutCase.compute_reward(0.05),
            timestamp="2026-09-22T12:00:00+00:00",
        )
        genome.record_case(case)
        assert len(lib) == 1
        assert lib.get("test-rec-001") is not None


# ============================================================
# T9-T10: evolve
# ============================================================
class TestEvolve:
    def test_evolve_sandbox_validate(self):
        """T9: 复用 _sandbox_validate 通过."""
        sandbox_fn = MagicMock(return_value=True)
        lib = WashoutReversalCaseLibrary()
        mock_det = _make_mock_washout_detector()
        ending_det = _make_ending_detector_stub()
        genome = WashoutReversalGenome(
            washout_detector=mock_det,
            ending_detector=ending_det,
            case_library=lib,
            bayesian_updater=BayesianUpdater(),
            enable=True,
            sandbox_validate_fn=sandbox_fn,
        )
        result = genome.evolve({"scenario_id": "test", "new_pattern": "knn"})
        assert result["accepted"] is True

    def test_evolve_no_sandbox(self):
        """T10: 无 sandbox_validate_fn → accepted=False."""
        lib = WashoutReversalCaseLibrary()
        mock_det = _make_mock_washout_detector()
        ending_det = _make_ending_detector_stub()
        genome = WashoutReversalGenome(
            washout_detector=mock_det,
            ending_detector=ending_det,
            case_library=lib,
            bayesian_updater=BayesianUpdater(),
            enable=True,
            sandbox_validate_fn=None,
        )
        result = genome.evolve()
        assert result["accepted"] is False


# ============================================================
# T11-T12: 开关 + FAIL-OPEN
# ============================================================
class TestSwitchAndFailOpen:
    def test_enable_false_returns_none(self):
        """T11: enable=False → signal direction=NONE."""
        mock_det = _make_mock_washout_detector(confidence=0.90)
        ending_det = _make_ending_detector_stub()
        genome = WashoutReversalGenome(
            washout_detector=mock_det,
            ending_detector=ending_det,
            case_library=WashoutReversalCaseLibrary(),
            bayesian_updater=BayesianUpdater(),
            enable=False,  # 关闭
        )
        df = _make_test_df()
        signal = genome.detect_signal("BTC", df, {})
        assert signal.direction == "NONE"

    def test_fail_open_exception(self):
        """T12: 异常 → signal direction=NONE (不抛错)."""
        mock_det = MagicMock(spec=WashoutDetector)
        mock_det.run.side_effect = RuntimeError("boom")
        ending_det = _make_ending_detector_stub()
        genome = WashoutReversalGenome(
            washout_detector=mock_det,
            ending_detector=ending_det,
            case_library=WashoutReversalCaseLibrary(),
            bayesian_updater=BayesianUpdater(),
            enable=True,
        )
        df = _make_test_df()
        signal = genome.detect_signal("BTC", df, {})
        assert signal.direction == "NONE"


# ============================================================
# T13: 无 LLM 依赖
# ============================================================
class TestNoLLMDependency:
    def test_no_llm_dependency(self):
        """T13: 源码中无 LLM/openai/anthropic 调用."""
        source_path = (
            _ARCH_ROOT / "dreamos" / "evolution"
            / "washout_reversal_genome.py"
        )
        if source_path.exists():
            source = source_path.read_text()
            for kw in ("import openai", "from openai", "import anthropic", "from anthropic",
                        "chat.completions.create", "messages.create"):
                assert kw not in source.lower(), f"发现 LLM 依赖: {kw}"
