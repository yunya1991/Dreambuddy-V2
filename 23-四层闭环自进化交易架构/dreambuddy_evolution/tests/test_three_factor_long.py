"""Phase 4.3 TDD: 三因子共振做多检测器测试

验证头肩底 + BTC regime=STRONG + ETF流入 三因子共振时允许升级到 L2 加强做多。
安全侧 FAIL-OPEN: 任一因子缺失/异常 → False（不升级）

三因子条件:
  - pattern_factor >= +0.5 (头肩底看涨)
  - btc_regime == "STRONG" (BTC 与美股脱钩，独立强势)
  - etf_flow_norm > +0.1 (ETF 净流入)
"""
import sys
from pathlib import Path

import pytest

# ---- path inject ----
REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


class TestThreeFactorLongDetector:
    """三因子共振做多检测器测试"""

    def test_three_factor_resonance_all_true(self):
        """三因子全满足 → True（允许升级到 L2 加强做多）"""
        from dreambuddy_evolution.engines.three_factor_long import (
            ThreeFactorLongDetector,
        )
        detector = ThreeFactorLongDetector()
        result = detector.detect(
            pattern_factor=0.8,
            btc_regime="STRONG",
            etf_flow_norm=0.3,
        )
        assert result is True

    def test_pattern_insufficient(self):
        """pattern_factor=0.3（低于 0.5 阈值）→ False"""
        from dreambuddy_evolution.engines.three_factor_long import (
            ThreeFactorLongDetector,
        )
        detector = ThreeFactorLongDetector()
        result = detector.detect(
            pattern_factor=0.3,
            btc_regime="STRONG",
            etf_flow_norm=0.3,
        )
        assert result is False

    def test_regime_not_strong(self):
        """btc_regime=WEAK → False"""
        from dreambuddy_evolution.engines.three_factor_long import (
            ThreeFactorLongDetector,
        )
        detector = ThreeFactorLongDetector()
        result = detector.detect(
            pattern_factor=0.8,
            btc_regime="WEAK",
            etf_flow_norm=0.3,
        )
        assert result is False

    def test_etf_outflow(self):
        """etf_flow_norm=-0.2（流出）→ False"""
        from dreambuddy_evolution.engines.three_factor_long import (
            ThreeFactorLongDetector,
        )
        detector = ThreeFactorLongDetector()
        result = detector.detect(
            pattern_factor=0.8,
            btc_regime="STRONG",
            etf_flow_norm=-0.2,
        )
        assert result is False

    def test_crash_fail_open_false(self):
        """传 None/异常 → False（FAIL-OPEN，不升级）"""
        from dreambuddy_evolution.engines.three_factor_long import (
            ThreeFactorLongDetector,
        )
        detector = ThreeFactorLongDetector()
        # pattern_factor=None
        assert detector.detect(pattern_factor=None, btc_regime="STRONG", etf_flow_norm=0.3) is False
        # btc_regime=None
        assert detector.detect(pattern_factor=0.8, btc_regime=None, etf_flow_norm=0.3) is False
        # etf_flow_norm=None
        assert detector.detect(pattern_factor=0.8, btc_regime="STRONG", etf_flow_norm=None) is False
        # 全部 None
        assert detector.detect(pattern_factor=None, btc_regime=None, etf_flow_norm=None) is False

    def test_switch_disabled(self):
        """enable_three_factor_long=False → 不计算，返回 False"""
        from dreambuddy_evolution.engines.three_factor_long import (
            ThreeFactorLongDetector,
        )
        from dreambuddy_evolution.agi_config import set_switch, get_switch
        # 保存原值
        _orig = get_switch("enable_three_factor_long")
        try:
            set_switch("enable_three_factor_long", False)
            detector = ThreeFactorLongDetector()
            result = detector.detect(
                pattern_factor=0.8,
                btc_regime="STRONG",
                etf_flow_norm=0.3,
            )
            assert result is False
        finally:
            set_switch("enable_three_factor_long", _orig)

    def test_boundary_pattern_threshold(self):
        """pattern_factor=0.5（刚好等于阈值）→ True"""
        from dreambuddy_evolution.engines.three_factor_long import (
            ThreeFactorLongDetector,
        )
        detector = ThreeFactorLongDetector()
        result = detector.detect(
            pattern_factor=0.5,
            btc_regime="STRONG",
            etf_flow_norm=0.3,
        )
        assert result is True

    def test_boundary_etf_threshold(self):
        """etf_flow_norm=0.1（刚好等于阈值，不满足 >）→ False"""
        from dreambuddy_evolution.engines.three_factor_long import (
            ThreeFactorLongDetector,
        )
        detector = ThreeFactorLongDetector()
        result = detector.detect(
            pattern_factor=0.8,
            btc_regime="STRONG",
            etf_flow_norm=0.1,
        )
        assert result is False
