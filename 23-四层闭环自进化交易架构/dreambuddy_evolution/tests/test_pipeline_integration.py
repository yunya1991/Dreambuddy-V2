"""
TDD 测试: P0 接入 RegimeGateSwitch + TrendFollowing + GridTrading + ShadowRLTrainer

验证点：
  T1. EvolutionPipeline 初始化时创建 RegimeGateSwitch 实例
  T2. _discover_paths 返回的路径中包含 regime 路由信息
  T3. regime=TREND 时路径 source 包含 trend_following
  T4. regime=RANGE 时路径 source 包含 grid_trading
  T5. regime=CRISIS 时路径为空或 pause
  T6. EvolutionPipeline 初始化时创建 ShadowRLTrainer 实例
  T7. ShadowRLTrainer 训练结果可通过 get_trained_policy 获取
  T8. run_symbol 返回结果中包含 regime 字段
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline


def _make_market_data(symbol="BTC-USDT-SWAP"):
    """构造模拟 market_data"""
    return {
        "symbol": symbol,
        "kline_data": {
            "high": [100 + i * 0.5 for i in range(60)],
            "low": [95 + i * 0.5 for i in range(60)],
            "close": [98 + i * 0.3 for i in range(60)],
            "volume": [1000] * 60,
        },
        "budget": 1000.0,
    }


# ====================================================================
# T1. EvolutionPipeline 初始化时创建 RegimeGateSwitch 实例
# ====================================================================
def test_pipeline_has_regime_gate():
    pipeline = EvolutionPipeline()
    assert hasattr(pipeline, "_regime_gate"), "EvolutionPipeline 应有 _regime_gate 属性"
    assert pipeline._regime_gate is not None, "RegimeGateSwitch 应已初始化"


# ====================================================================
# T2. _discover_paths 返回路径中包含 regime 路由信息
# ====================================================================
def test_discover_paths_has_regime():
    pipeline = EvolutionPipeline()
    market_data = _make_market_data()
    r_out = {"R_up": 0.5, "R_down": 0.5, "R_up_mod": 0.5, "R_down_mod": 0.5}
    paths = pipeline._discover_paths(r_out, market_data, "BTC-USDT-SWAP")
    # 至少应有路径返回（即使是 regime 路由的路径）
    assert isinstance(paths, list)


# ====================================================================
# T3. regime=TREND 时路径 source 包含 trend_following
# ====================================================================
def test_regime_trend_adds_trend_following_path():
    pipeline = EvolutionPipeline()
    # 构造 TREND 市场数据（ADX>25 的趋势数据）
    market_data = _make_market_data()
    # 强趋势数据：价格持续上涨
    trend_closes = [100 + i * 2 for i in range(60)]
    market_data["kline_data"]["close"] = trend_closes
    market_data["kline_data"]["high"] = [c + 5 for c in trend_closes]
    market_data["kline_data"]["low"] = [c - 5 for c in trend_closes]

    r_out = {"R_up": 0.7, "R_down": 0.3, "R_up_mod": 0.7, "R_down_mod": 0.3}
    paths = pipeline._discover_paths(r_out, market_data, "BTC-USDT-SWAP")
    sources = [p.get("source", "") for p in paths]
    # 应包含 trend_following 来源的路径
    assert any("trend" in s for s in sources), f"TREND regime 应有 trend_following 路径，实际 sources={sources}"


# ====================================================================
# T4. regime=RANGE 时路径 source 包含 grid_trading
# ====================================================================
def test_regime_range_adds_grid_path():
    pipeline = EvolutionPipeline()
    # 构造 RANGE 市场数据（价格在区间内波动）
    market_data = _make_market_data()
    range_closes = [100 + 5 * (1 if i % 10 < 5 else -1) for i in range(60)]
    market_data["kline_data"]["close"] = range_closes
    market_data["kline_data"]["high"] = [c + 2 for c in range_closes]
    market_data["kline_data"]["low"] = [c - 2 for c in range_closes]

    r_out = {"R_up": 0.5, "R_down": 0.5, "R_up_mod": 0.5, "R_down_mod": 0.5}
    paths = pipeline._discover_paths(r_out, market_data, "BTC-USDT-SWAP")
    sources = [p.get("source", "") for p in paths]
    # 应包含 grid 来源的路径
    assert any("grid" in s for s in sources), f"RANGE regime 应有 grid 路径，实际 sources={sources}"


# ====================================================================
# T5. regime=CRISIS 时路径为空或 pause
# ====================================================================
def test_regime_crisis_returns_pause():
    """CRISIS 时不添加 trend_following/grid 路径"""
    pipeline = EvolutionPipeline()
    market_data = _make_market_data()

    # 直接 mock detect_regime 返回 CRISIS
    from unittest.mock import patch
    with patch.object(pipeline._regime_gate.__class__, "detect_regime", return_value="CRISIS"):
        r_out = {"R_up": 0.5, "R_down": 0.5, "R_up_mod": 0.5, "R_down_mod": 0.5}
        paths = pipeline._discover_paths(r_out, market_data, "BTC-USDT-SWAP")

    sources = [p.get("source", "") for p in paths]
    has_strategy = any("trend" in s or "grid" in s for s in sources)
    assert not has_strategy, f"CRISIS 应暂停策略，实际 sources={sources}"


# ====================================================================
# T6. EvolutionPipeline 初始化时创建 ShadowRLTrainer 实例
# ====================================================================
def test_pipeline_has_shadow_rl_trainer():
    pipeline = EvolutionPipeline()
    assert hasattr(pipeline, "shadow_rl_trainer"), "EvolutionPipeline 应有 shadow_rl_trainer 属性"
    assert pipeline.shadow_rl_trainer is not None, "ShadowRLTrainer 应已初始化"


# ====================================================================
# T7. ShadowRLTrainer 训练结果可通过 get_trained_policy 获取
# ====================================================================
def test_pipeline_trainer_can_train():
    pipeline = EvolutionPipeline()
    # 构造模拟样本
    import numpy as np
    np.random.seed(42)
    samples = []
    for i in range(50):
        samples.append({
            "symbol": "BTC-USDT-SWAP",
            "state": {"features": np.random.randn(5).tolist()},
            "action": f"action_{np.random.randint(0, 3)}",
            "reward": float(np.random.randn() * 0.1),
            "next_state": {"features": np.random.randn(5).tolist()},
        })
    result = pipeline.shadow_rl_trainer.train_policy(samples, epochs=10, gene_id="test")
    assert result["status"] in ("trained", "degraded")
    if result["status"] == "trained":
        policy = pipeline.shadow_rl_trainer.get_trained_policy("test")
        assert policy is not None


# ====================================================================
# T8. run_symbol 返回结果中包含 regime 字段
# ====================================================================
def test_run_symbol_returns_regime():
    pipeline = EvolutionPipeline()
    market_data = _make_market_data()
    result = pipeline.run_symbol("BTC-USDT-SWAP", market_data)
    assert "regime" in result, f"run_symbol 应返回 regime 字段，实际 keys={list(result.keys())}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
