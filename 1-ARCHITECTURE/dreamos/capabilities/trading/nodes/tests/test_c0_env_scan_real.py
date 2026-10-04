"""
RED 测试 — C0 环境扫描节点真实业务逻辑

C0 是 Classic Pipeline 的起点。基于 BTC 价格趋势和波动率判断市场状态，
产出 env_state/regime/macro_flags 供下游 C1 品种筛选消费。

迁移自 ml_trade_service.py 的 _quant_pairs_macro_eval (L129905+) 的简化版：
- 原实现依赖多个内部函数（_entry_macro_btceth_tf_std_at/_macro_trend_at 等），
  返回 risk_budget_tier(risk_on/risk_off/risk_off_pre/neutral)。
- C0 节点采用 spec 定义的更抽象层级：regime (bull/bear/range) + macro_flags。
- 简化策略：基于 BTC 趋势方向 + 波动率分类。

断言：
1. 有市场数据时返回 regime (bull/bear/range) + macro_flags + env_state
2. BTC 上涨 + 低波动 → regime="bull", macro_flags["risk_on"]=True
3. BTC 下跌 + 低波动 → regime="bear", macro_flags["risk_off"]=True
4. 高波动 → regime="range", macro_flags["volatility_regime"]="high"
5. state.config 可覆盖阈值
6. 无 market 时降级返回 SUCCESS + None outputs（FAIL-OPEN）
"""

from __future__ import annotations

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult, NodeStatus


def test_c0_importable():
    from dreamos.capabilities.trading.nodes.c0_env_scan import C0EnvScanNode
    assert C0EnvScanNode is not None


def test_c0_metadata():
    from dreamos.capabilities.trading.nodes.c0_env_scan import C0EnvScanNode
    node = C0EnvScanNode()
    assert node.node_id == "C0"
    assert node.chain == "C"
    assert node.name == "环境扫描"


def test_c0_tags_has_classic_v2():
    from dreamos.capabilities.trading.nodes.c0_env_scan import C0EnvScanNode
    node = C0EnvScanNode()
    assert "classic" in node.tags
    assert "classic_v2" in node.tags


def test_c0_bull_regime_when_btc_up_low_vol():
    """BTC 上涨 + 低波动 → regime=bull, risk_on=True"""
    from dreamos.capabilities.trading.nodes.c0_env_scan import C0EnvScanNode
    market = {
        "btc_trend": 0.05,        # BTC 5% 上涨
        "btc_volatility": 0.02,   # 低波动
        "eth_trend": 0.04,
        "eth_volatility": 0.025,
    }
    state = State(market=market)
    result = C0EnvScanNode().execute_core(state)

    assert result.status == NodeStatus.SUCCESS
    assert result.outputs["regime"] == "bull"
    assert result.outputs["macro_flags"]["risk_on"] is True
    assert result.outputs["macro_flags"]["risk_off"] is False
    assert isinstance(result.outputs["env_state"], str)
    assert len(result.outputs["env_state"]) > 0


def test_c0_bear_regime_when_btc_down_low_vol():
    """BTC 下跌 + 低波动 → regime=bear, risk_off=True"""
    from dreamos.capabilities.trading.nodes.c0_env_scan import C0EnvScanNode
    market = {
        "btc_trend": -0.06,
        "btc_volatility": 0.02,
        "eth_trend": -0.05,
        "eth_volatility": 0.025,
    }
    state = State(market=market)
    result = C0EnvScanNode().execute_core(state)

    assert result.outputs["regime"] == "bear"
    assert result.outputs["macro_flags"]["risk_on"] is False
    assert result.outputs["macro_flags"]["risk_off"] is True


def test_c0_range_regime_when_high_volatility():
    """高波动 → regime=range, volatility_regime=high"""
    from dreamos.capabilities.trading.nodes.c0_env_scan import C0EnvScanNode
    market = {
        "btc_trend": 0.01,
        "btc_volatility": 0.15,   # 高波动
        "eth_trend": 0.0,
        "eth_volatility": 0.18,
    }
    state = State(market=market)
    result = C0EnvScanNode().execute_core(state)

    assert result.outputs["regime"] == "range"
    assert result.outputs["macro_flags"]["volatility_regime"] == "high"


def test_c0_config_overrides_volatility_threshold():
    """state.config 可覆盖波动率阈值"""
    from dreamos.capabilities.trading.nodes.c0_env_scan import C0EnvScanNode
    market = {
        "btc_trend": 0.05,
        "btc_volatility": 0.06,   # 默认阈值下是低波动
        "eth_trend": 0.04,
        "eth_volatility": 0.07,
    }
    # 默认阈值 0.10，0.06 < 0.10 → bull
    state_default = State(market=market)
    result_default = C0EnvScanNode().execute_core(state_default)
    assert result_default.outputs["regime"] == "bull"

    # 覆盖阈值为 0.05，0.06 > 0.05 → range
    state_override = State(
        market=market,
        config={"env_scan_volatility_threshold": 0.05},
    )
    result_override = C0EnvScanNode().execute_core(state_override)
    assert result_override.outputs["regime"] == "range"


def test_c0_no_market_returns_degraded():
    """无 market 数据时应降级返回（FAIL-OPEN）"""
    from dreamos.capabilities.trading.nodes.c0_env_scan import C0EnvScanNode
    state = State()
    result = C0EnvScanNode().execute_core(state)

    assert isinstance(result, NodeResult)
    assert result.node_id == "C0"
    assert result.status in (NodeStatus.SUCCESS, NodeStatus.FAILED, NodeStatus.DEGRADED)
    # outputs 应包含 regime 字段（可为 None）
    assert "regime" in result.outputs
    assert "macro_flags" in result.outputs


def test_c0_macro_flags_contains_all_keys():
    """macro_flags 应包含 risk_on/risk_off/volatility_regime 三个 key"""
    from dreamos.capabilities.trading.nodes.c0_env_scan import C0EnvScanNode
    market = {
        "btc_trend": 0.03,
        "btc_volatility": 0.04,
        "eth_trend": 0.02,
        "eth_volatility": 0.05,
    }
    state = State(market=market)
    result = C0EnvScanNode().execute_core(state)

    macro_flags = result.outputs["macro_flags"]
    assert isinstance(macro_flags, dict)
    assert "risk_on" in macro_flags
    assert "risk_off" in macro_flags
    assert "volatility_regime" in macro_flags
