"""Phase 7 closed-loop integration test suite."""
import pytest
from pathlib import Path
import sys

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

from dreamos.capabilities.trading.orchestrator_v2 import OrchestratorV2
from dreamos.capabilities.trading.coin_selector import CoinSelector
from dreamos.capabilities.trading.yijing_signal_generator import YijingSignalGenerator
from dreamos.capabilities.trading.v15_executor import V15Executor
from dreamos.capabilities.trading.signal_router import SignalRouter
from dreamos.capabilities.trading.cognitive_reviewer import CognitiveReviewer


def test_phase7_full_closed_loop():
    """Phase 7: Full closed-loop end-to-end verification.

    Verifies the complete six-layer pipeline:
        A: CoinSelector -> coin pools
        B: YijingSignalGenerator -> directional signal
        C: V15Executor -> position execution
        D: SignalRouter -> unified routing
        E: CognitiveReviewer -> lesson extraction
        F: OrchestratorV2 -> scheduling + Bayesian trigger
    """
    # Initialize orchestrator (connects all 6 layers)
    orch = OrchestratorV2(use_hermes=False)

    # Prepare market data
    market_data = {
        "symbol": "BTC",
        "supply_demand_score": 0.65,
        "technical_score": 0.60,
        "capital_flow_score": 0.55,
        "sentiment_score": 0.50,
        "trend_strength": 0.70,
        "volatility": 0.30,
        "volume_ratio": 1.2,
        "price_position": 0.45,
        "ma5": 100.0,
        "ma10": 98.0,
        "ma20": 95.0,
        "momentum_direction": "UP",
        "close_price": 100000.0,
        "entry_price": 100000.0,
    }

    # Execute full cycle
    result = orch.run_cycle(market_data)

    # Verify all 6 layers produced output
    assert result["status"] in ("COMPLETED", "PARTIAL")
    assert "selection" in result
    assert "signal" in result
    assert "execution" in result
    assert "review" in result
    assert "cycle_id" in result

    # Layer A: Coin selection
    assert result["selection"]["status"] == "OK"
    assert "pools" in result["selection"]

    # Layer B: Yijing signal
    assert result["signal"]["status"] == "OK"
    assert result["signal"]["direction"] in ("LONG", "SHORT", "HOLD")
    assert result["signal"]["confidence"] > 0

    # Layer C: V15 execution
    assert result["execution"]["status"] in ("OPEN", "REJECTED")

    # Layer E: 认知层 —— P1-3 后新契约: 周期内不再伪造 pnl=0 审查,
    # 改为 awaiting_real_feedback 快照(真实审查由平仓回填 record_real_exit 产生)
    assert result["review"]["status"] == "OK"
    assert result["review"]["mode"] == "awaiting_real_feedback"
    assert "cognitive_context" in result["review"]


def test_phase7_cognitive_injection():
    """Phase 7 / P1-1: 认知注入闭环 —— 真实教训 → 下轮信号置信度调整。

    新契约(P1-3 后): run_cycle 不再伪造审查;认知积累来自真实平仓回填
    (record_real_exit)。本测试验证完整闭环:
        1. record_real_exit(盈利单) → lessons 落盘 + 状态更新
        2. 新建 OrchestratorV2 → 启动加载 lessons (P1-2)
        3. run_cycle → confidence_adjustment 注入信号置信度 (P1-1)
    """
    from dreamos.capabilities.trading.orchestrator_v2 import record_real_exit

    # Step 1: 真实盈利单回填 → 产生 lesson 并落盘
    win_trade = {
        "symbol": "BTC", "direction": "LONG", "entry_price": 100000.0,
        "exit_price": 105000.0, "position_size": 0.01,
        "confidence": 0.75, "addon_count": 0, "hold_hours": 5.0,
        "exit_reason": "TP hit|real", "pnl_usdt": 50.0, "pnl_pct": 0.05,
    }
    review = record_real_exit(win_trade)
    assert review["status"] == "OK"
    assert review["state_update"] == "OK"

    # Step 2: 新实例启动加载 —— 认知记忆跨实例保留 (P1-2)
    orch = OrchestratorV2(use_hermes=False)
    ctx = orch.reviewer.get_cognitive_context()
    assert ctx["total_reviews"] >= 1
    assert ctx["total_pnl"] > 0
    assert ctx["win_rate"] > 0.6
    assert isinstance(ctx["confidence_adjustment"], float)
    assert -0.1 <= ctx["confidence_adjustment"] <= 0.1
    assert ctx["confidence_adjustment"] > 0  # 盈利教训 → 正向调整

    # Step 3: run_cycle → P1-1 注入生效
    market_data = {
        "symbol": "BTC",
        "supply_demand_score": 0.65, "technical_score": 0.60,
        "capital_flow_score": 0.55, "sentiment_score": 0.50,
        "trend_strength": 0.70, "volatility": 0.30,
        "volume_ratio": 1.2, "price_position": 0.45,
        "ma5": 100.0, "ma10": 98.0, "ma20": 95.0,
        "momentum_direction": "UP",
        "close_price": 100000.0, "entry_price": 100000.0,
    }
    result = orch.run_cycle(market_data)

    # 认知快照: review 与信号均携带注入痕迹
    assert result["review"]["cognitive_context"]["total_reviews"] >= 1
    sig = result["signal"]
    if sig.get("status") == "OK" and "confidence_raw" in sig:
        raw = sig["confidence_raw"]
        adj = sig["cognitive_adjustment"]
        assert adj == pytest.approx(ctx["confidence_adjustment"])
        assert sig["confidence"] == pytest.approx(max(0.0, min(1.0, raw + adj)))


def test_phase7_bayesian_optimization_loop():
    """Phase 7: Verify Bayesian optimization trigger after consecutive losses."""
    orch = OrchestratorV2(use_hermes=False)

    # Simulate 3 consecutive losses
    orch.record_trade_result(-10.0)
    orch.record_trade_result(-15.0)
    orch.record_trade_result(-20.0)

    # Check Bayesian trigger
    triggered = orch.check_bayesian_trigger()
    assert triggered is True

    # Verify optimization was recorded
    status = orch.get_status()
    assert status["bayesian_optimizations"] == 1
    assert status["consecutive_losses"] == 0  # Reset after optimization
    assert status["total_pnl"] == -45.0


def test_phase7_multi_cycle_evolution():
    """Phase 7: Multi-cycle evolution with cognitive feedback.

    Simulates multiple trading cycles to verify:
        1. Cognitive lessons accumulate over time
        2. Win/loss tracking works correctly
        3. Bayesian optimization triggers when needed
        4. System state evolves correctly
    """
    orch = OrchestratorV2(use_hermes=False)

    market_data = {
        "symbol": "BTC",
        "supply_demand_score": 0.65,
        "technical_score": 0.60,
        "capital_flow_score": 0.55,
        "sentiment_score": 0.50,
        "trend_strength": 0.70,
        "volatility": 0.30,
        "volume_ratio": 1.2,
        "price_position": 0.45,
        "ma5": 100.0,
        "ma10": 98.0,
        "ma20": 95.0,
        "momentum_direction": "UP",
        "close_price": 100000.0,
        "entry_price": 100000.0,
    }

    # Run 3 cycles
    for i in range(3):
        result = orch.run_cycle(market_data)
        assert result["status"] in ("COMPLETED", "PARTIAL")

    # Record mixed results with actual trade reviews for lesson extraction
    win_trade = {
        "symbol": "BTC", "direction": "LONG", "entry_price": 100000.0,
        "exit_price": 105000.0, "confidence": 0.75, "hexagram": {},
        "addon_count": 0, "hold_hours": 5.0,
        "exit_reason": "ATR trailing TP hit",
        "pnl_usdt": 50.0, "pnl_pct": 0.05,
    }
    loss_trade = {
        "symbol": "BTC", "direction": "LONG", "entry_price": 100000.0,
        "exit_price": 97000.0, "confidence": 0.40, "hexagram": {},
        "addon_count": 3, "hold_hours": 35.0,
        "exit_reason": "Timeout exit",
        "pnl_usdt": -30.0, "pnl_pct": -0.03,
    }
    orch.reviewer.review(win_trade)
    orch.record_trade_result(50.0)   # Win
    orch.reviewer.review(loss_trade)
    orch.record_trade_result(-30.0)  # Loss
    orch.record_trade_result(-20.0)  # Loss

    # Check status
    status = orch.get_status()
    assert status["total_cycles"] == 3
    assert status["total_pnl"] == 0.0  # 50 - 30 - 20
    assert status["consecutive_losses"] == 2
    assert status["win_rate"] > 0  # At least 1 win out of 3

    # Cognitive context should have accumulated lessons
    ctx = orch.reviewer.get_cognitive_context()
    assert ctx["total_reviews"] >= 2  # At least 2 manual reviews
    assert len(ctx["recent_lessons"]) > 0


def test_phase7_all_nodes_registered():
    """Phase 7: Verify all 6 nodes are properly registered in nodes.yaml."""
    import yaml

    nodes_path = Path(__file__).parent.parent / "config" / "nodes.yaml"
    with open(nodes_path, "r") as f:
        config = yaml.safe_load(f)

    node_ids = [n["node_id"] for n in config["nodes"]]

    # Verify all 6 DreamOS trading nodes are registered
    assert "COIN_SELECTOR" in node_ids
    assert "YIJING_SIGNAL" in node_ids
    assert "V15_EXECUTOR" in node_ids
    assert "SIGNAL_ROUTER" in node_ids
    assert "COGNITIVE_REVIEW" in node_ids
    assert "ORCHESTRATOR_V2" in node_ids

    # Verify chain assignments
    node_map = {n["node_id"]: n for n in config["nodes"]}
    assert node_map["COIN_SELECTOR"]["chain"] == "A"
    assert node_map["YIJING_SIGNAL"]["chain"] == "B"
    assert node_map["V15_EXECUTOR"]["chain"] == "C"
    assert node_map["SIGNAL_ROUTER"]["chain"] == "D"
    assert node_map["COGNITIVE_REVIEW"]["chain"] == "E"
    assert node_map["ORCHESTRATOR_V2"]["chain"] == "F"
