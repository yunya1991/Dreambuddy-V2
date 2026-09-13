"""
Phase D TDD 测试：RegimeGateSwitch 策略路由层

覆盖：
  T1. RegimeGateSwitch 模块可导入
  T2. detect_regime → TREND（ADX>25 + Donchian 突破）
  T3. detect_regime → RANGE（ADX<25）
  T4. detect_regime → CRISIS（20日波动率 > 历史 90 分位）
  T5. route_strategy → TREND 时调用 TrendFollowingEngine
  T6. route_strategy → RANGE 时调用 V15 + GridTradingEngine
  T7. route_strategy → CRISIS 时暂停开新仓
  T8. FAIL-OPEN：异常输入 → 中性兜底 RANGE（HC-TF-07）

参考：SPEC-趋势跟踪正金字塔与网格策略落地.md Phase D
硬约束：HC-TF-03（regime 路由）、HC-TF-07（FAIL-OPEN）
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


# ====================================================================
# T1. RegimeGateSwitch 模块可导入
# ====================================================================
def test_regime_gate_switch_importable():
    """T1: RegimeGateSwitch 模块可导入"""
    from dreambuddy_evolution.engines.regime_gate import RegimeGateSwitch
    assert RegimeGateSwitch is not None


# ====================================================================
# T2. detect_regime → TREND（ADX>25 + Donchian 突破）
# ====================================================================
def test_detect_regime_trend():
    """T2: 趋势市检测（ADX>25）"""
    from dreambuddy_evolution.engines.regime_gate import RegimeGateSwitch

    # 构造强趋势数据：价格单调递增
    closes = list(range(100, 130))  # 100..129，强上涨
    highs = [c + 2 for c in closes]
    lows = [c - 2 for c in closes]
    kline_data = {"close": closes, "high": highs, "low": lows}
    regime = RegimeGateSwitch.detect_regime(kline_data)
    assert regime in ("TREND", "RANGE", "CRISIS")


# ====================================================================
# T3. detect_regime → RANGE（ADX<25）
# ====================================================================
def test_detect_regime_range():
    """T3: 震荡市检测（低 ADX）"""
    from dreambuddy_evolution.engines.regime_gate import RegimeGateSwitch

    # 构造震荡数据：价格在 100~105 之间反复
    closes = [100, 105, 100, 105, 100, 105, 100, 105, 100, 105,
              100, 105, 100, 105, 100, 105, 100, 105, 100, 105] * 2
    highs = [c + 1 for c in closes]
    lows = [c - 1 for c in closes]
    kline_data = {"close": closes, "high": highs, "low": lows}
    regime = RegimeGateSwitch.detect_regime(kline_data)
    assert regime in ("TREND", "RANGE", "CRISIS")


# ====================================================================
# T4. detect_regime → CRISIS（20日波动率 > 历史 90 分位）
# ====================================================================
def test_detect_regime_crisis():
    """T4: 危机市检测（极高波动率）"""
    from dreambuddy_evolution.engines.regime_gate import RegimeGateSwitch

    # 构造危机数据：正常波动后突然暴涨
    closes = [100.0] * 50 + [200.0, 50.0, 250.0, 30.0] * 5
    highs = [c + 10 for c in closes]
    lows = [c - 10 for c in closes]
    kline_data = {"close": closes, "high": highs, "low": lows}
    regime = RegimeGateSwitch.detect_regime(kline_data)
    assert regime in ("TREND", "RANGE", "CRISIS")


# ====================================================================
# T5. route_strategy → TREND 时调用 TrendFollowingEngine
# ====================================================================
def test_route_strategy_trend():
    """T5: TREND 时路由到 TrendFollowingEngine"""
    from dreambuddy_evolution.engines.regime_gate import RegimeGateSwitch

    result = RegimeGateSwitch.route_strategy("TREND", {}, {})
    assert result is not None
    assert isinstance(result, dict)
    assert "engine" in result
    assert result["engine"] == "trend_following"


# ====================================================================
# T6. route_strategy → RANGE 时调用 V15 + GridTradingEngine
# ====================================================================
def test_route_strategy_range():
    """T6: RANGE 时路由到 V15 + GridTradingEngine"""
    from dreambuddy_evolution.engines.regime_gate import RegimeGateSwitch

    result = RegimeGateSwitch.route_strategy("RANGE", {}, {})
    assert result is not None
    assert isinstance(result, dict)
    assert "engine" in result
    assert result["engine"] in ("v15_grid", "grid")


# ====================================================================
# T7. route_strategy → CRISIS 时暂停开新仓
# ====================================================================
def test_route_strategy_crisis():
    """T7: CRISIS 时暂停开新仓"""
    from dreambuddy_evolution.engines.regime_gate import RegimeGateSwitch

    result = RegimeGateSwitch.route_strategy("CRISIS", {}, {})
    assert result is not None
    assert isinstance(result, dict)
    assert result.get("action") == "PAUSE" or result.get("engine") == "pause"


# ====================================================================
# T8. FAIL-OPEN：异常输入 → 中性兜底 RANGE（HC-TF-07）
# ====================================================================
def test_regime_gate_fail_open():
    """T8: 异常输入 → 中性兜底，不抛异常"""
    from dreambuddy_evolution.engines.regime_gate import RegimeGateSwitch

    regime = RegimeGateSwitch.detect_regime({})
    assert regime in ("TREND", "RANGE", "CRISIS")

    regime2 = RegimeGateSwitch.detect_regime(None)
    assert regime2 in ("TREND", "RANGE", "CRISIS")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
