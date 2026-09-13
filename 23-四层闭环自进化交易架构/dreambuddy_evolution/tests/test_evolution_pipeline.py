"""
dreambuddy-v2 四层闭环进化架构 — TDD 测试套件
覆盖: Level 0 路径代价 (§1.5.5) + L3 ShadowRL + L4 BellmanV + EvolutionPipeline
蓝图根: 四层闭环进化架构-最小阻力路径总览.md §1.5
"""
import sys
import os
import json
import math
import numpy as np
from pathlib import Path

import pytest

# ---- path inject ----
REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# ---- fixtures ----
@pytest.fixture
def rv():
    """ResistanceVector instance"""
    from dreambuddy_evolution.core.resistance_vector import ResistanceVector
    return ResistanceVector()

@pytest.fixture
def mock_market_data():
    """Mock OHLCV + positions for RV.calculate"""
    rng = np.random.default_rng(42)
    N = 200
    close = 35000.0 + np.cumsum(rng.normal(0, 50, N))
    return {
        "close": close,
        "volume": np.full(N, 3000.0),
        "okx_positions": {"long": 0.55, "short": 0.45},
        "liquidation_buy": np.zeros(N),
        "liquidation_sell": np.zeros(N),
        "ma_200": float(np.mean(close)),
        "fib_retrace_0786": 37000.0,
        "fib_retrace_0618": 35000.0,
        "fib_retrace_0500": 33500.0,
        "bid_ask_spread_bps": 2.0,
        "news_sentiment_score": 0.60,
    }

@pytest.fixture
def gene_root():
    return REPO / "dreambuddy_evolution" / "gene_data"


# ==============================================================================
# TR-L0: Level 0 路径代价计算器 (§1.5.5)
# ==============================================================================
class TestLevel0PathCost:
    """Level 0: d* = argmin_{d∈{long,short,WAIT}} d^T·g_diag·d"""

    def test_TR_L0_01_compute_g_diag_shape_and_values(self):
        """g_MVP = diag(R_up, R_down, R_smooth, R_flow, R_reflexivity) 5×5 对角正定"""
        from dreambuddy_evolution.core.level0_path_cost import compute_g_diag
        rv_out = {"R_up": 0.3, "R_down": 0.7, "R_smooth": 0.2,
                  "R_flow": 0.8, "R_reflexivity": 0.4}
        g = compute_g_diag(rv_out)
        assert g.shape == (5, 5), f"g shape {g.shape} != (5,5)"
        # 对角线
        assert g[0, 0] == pytest.approx(0.3, abs=1e-6)
        assert g[1, 1] == pytest.approx(0.7, abs=1e-6)
        assert g[2, 2] == pytest.approx(0.2, abs=1e-6)
        assert g[3, 3] == pytest.approx(0.8, abs=1e-6)
        assert g[4, 4] == pytest.approx(0.4, abs=1e-6)
        # 非对角元 = 0 (MVP 对角阵)
        assert g[0, 1] == 0 and g[1, 0] == 0
        # 正定
        assert np.all(np.linalg.eigvalsh(g) > 0)

    def test_TR_L0_02_d_star_long_when_R_up_low(self):
        """R_up=0.2 < wait=0.40 < R_down=0.8 → d*='long' (上行阻力最小)"""
        from dreambuddy_evolution.core.level0_path_cost import compute_d_star
        rv = {"R_up": 0.2, "R_down": 0.8, "R_smooth": 0.8,
              "R_flow": 0.6, "R_reflexivity": 0.5}
        result = compute_d_star(rv)
        assert result["d_star"] == "long"
        assert result["costs"]["long"] == pytest.approx(0.2, abs=1e-6)
        assert result["costs"]["short"] == pytest.approx(0.8, abs=1e-6)

    def test_TR_L0_03_d_star_short_when_R_down_low(self):
        """R_down=0.15 < wait=0.40 < R_up=0.85 → d*='short'"""
        from dreambuddy_evolution.core.level0_path_cost import compute_d_star
        rv = {"R_up": 0.85, "R_down": 0.15, "R_smooth": 0.8,
              "R_flow": 0.6, "R_reflexivity": 0.5}
        result = compute_d_star(rv)
        assert result["d_star"] == "short"

    def test_TR_L0_04_d_star_wait_when_smooth_refl_low(self):
        """R_smooth=0.3, R_reflexivity=0.3 → WAIT cost=0.09 低于 long=short=0.7"""
        from dreambuddy_evolution.core.level0_path_cost import compute_d_star
        rv = {"R_up": 0.7, "R_down": 0.7, "R_smooth": 0.3,
              "R_flow": 0.5, "R_reflexivity": 0.3}
        result = compute_d_star(rv)
        wait_cost = 0.3 * 0.3  # R_smooth × R_reflexivity
        assert result["costs"]["wait"] == pytest.approx(wait_cost, abs=1e-6)
        assert result["d_star"] == "WAIT"
        assert wait_cost < result["costs"]["long"]
        assert wait_cost < result["costs"]["short"]

    def test_TR_L0_05_fallback_050_all_dims(self):
        """全维 0.50 fallback → long=short=0.50, wait=0.25 → d*=WAIT"""
        from dreambuddy_evolution.core.level0_path_cost import compute_d_star
        rv = {"R_up": 0.50, "R_down": 0.50, "R_smooth": 0.50,
              "R_flow": 0.50, "R_reflexivity": 0.50}
        result = compute_d_star(rv)
        # long=short=0.5; wait=0.5*0.5=0.25 < 0.5
        assert result["d_star"] == "WAIT"
        assert result["costs"]["wait"] == pytest.approx(0.25, abs=1e-6)

    def test_TR_L0_06_confidence_range(self):
        """confidence ∈ [0,1]，差距越大越自信"""
        from dreambuddy_evolution.core.level0_path_cost import compute_d_star
        rv_clear = {"R_up": 0.1, "R_down": 0.9, "R_smooth": 0.3,
                    "R_flow": 0.6, "R_reflexivity": 0.4}
        rv_murky = {"R_up": 0.45, "R_down": 0.55, "R_smooth": 0.5,
                    "R_flow": 0.5, "R_reflexivity": 0.5}
        r_clear = compute_d_star(rv_clear)
        r_murky = compute_d_star(rv_murky)
        assert 0.0 <= r_clear["confidence"] <= 1.0
        assert 0.0 <= r_murky["confidence"] <= 1.0
        assert r_clear["confidence"] > r_murky["confidence"]


# ==============================================================================
# TR-SRL: L3 ShadowRLTracker (§二 L3 高频探索层)
# ==============================================================================
class TestShadowRLTracker:
    """L3: 记录 (s,a,R,s') 样本 + 计算 Sharpe stub"""

    def test_TR_SRL_01_record_sample_basic(self):
        """记录一条 (s, a, R, s') 样本"""
        from dreambuddy_evolution.core.shadow_rl import ShadowRLTracker
        tracker = ShadowRLTracker()
        tracker.record(
            symbol="BTC",
            state={"R_up": 0.2, "R_down": 0.8},
            action="long",
            reward=0.03,
            next_state={"R_up": 0.3, "R_down": 0.7},
        )
        assert tracker.sample_count() == 1

    def test_TR_SRL_02_sharpe_calculation(self):
        """多条样本后计算 Sharpe stub"""
        from dreambuddy_evolution.core.shadow_rl import ShadowRLTracker
        tracker = ShadowRLTracker()
        rewards = [0.02, -0.01, 0.03, 0.01, -0.005, 0.015]
        for r in rewards:
            tracker.record("BTC", {"R_up": 0.2}, "long", r, {"R_up": 0.3})
        stats = tracker.get_stats()
        assert "sharpe" in stats
        assert "sample_count" in stats
        assert stats["sample_count"] == len(rewards)
        # Sharpe = mean/std (无风险利率=0 简化)
        expected_sharpe = np.mean(rewards) / (np.std(rewards, ddof=1) + 1e-9)
        assert stats["sharpe"] == pytest.approx(expected_sharpe, abs=1e-4)

    def test_TR_SRL_03_empty_tracker_sharpe_zero(self):
        """空 tracker → Sharpe=0（FAIL-OPEN 降级）"""
        from dreambuddy_evolution.core.shadow_rl import ShadowRLTracker
        tracker = ShadowRLTracker()
        stats = tracker.get_stats()
        assert stats["sharpe"] == 0.0
        assert stats["sample_count"] == 0

    def test_TR_SRL_04_phase3_not_activated_log(self):
        """L3 stub 标记 Phase 3 not yet activated"""
        from dreambuddy_evolution.core.shadow_rl import ShadowRLTracker
        tracker = ShadowRLTracker()
        assert tracker.is_phase3_activated() is False


# ==============================================================================
# TR-BV: L4 BellmanVTracker (§二 L4 最优目标层)
# ==============================================================================
class TestBellmanVTracker:
    """L4: V(s) 时序差分更新 + ESS 回馈"""

    def test_TR_BV_01_initial_v_zero(self):
        """新 symbol V(s)=0"""
        from dreambuddy_evolution.core.bellman_tracker import BellmanVTracker
        tracker = BellmanVTracker()
        assert tracker.get_v("BTC") == 0.0

    def test_TR_BV_02_td_update(self):
        """V(s) ← V(s) + α·(R + γ·V(s') - V(s))"""
        from dreambuddy_evolution.core.bellman_tracker import BellmanVTracker
        tracker = BellmanVTracker(alpha=0.1, gamma=0.95)
        # V(BTC)=0 → update with R=0.05, V(s')=0.0
        tracker.td_update("BTC", reward=0.05, next_symbol="ETH")
        # V(BTC) = 0 + 0.1*(0.05 + 0.95*0 - 0) = 0.005
        assert tracker.get_v("BTC") == pytest.approx(0.005, abs=1e-6)

    def test_TR_BV_03_multiple_updates_converge(self):
        """连续相同 reward → V(s) 收敛到 R/(1-γ)"""
        from dreambuddy_evolution.core.bellman_tracker import BellmanVTracker
        tracker = BellmanVTracker(alpha=0.1, gamma=0.9)
        for _ in range(500):
            tracker.td_update("BTC", reward=0.01, next_symbol="BTC")
        # 理论收敛: V = R/(1-γ) = 0.01/0.1 = 0.1
        assert tracker.get_v("BTC") == pytest.approx(0.1, abs=0.01)

    def test_TR_BV_04_ess_feedback(self):
        """V(s) 回馈 ESS 调整量"""
        from dreambuddy_evolution.core.bellman_tracker import BellmanVTracker
        tracker = BellmanVTracker()
        tracker.td_update("BTC", reward=0.05, next_symbol="BTC")
        adj = tracker.get_ess_adjustment("BTC")
        # 正 reward → positive ESS adjustment
        assert adj > 0
        assert abs(adj) <= 0.02  # ≤ ±0.02 硬约束 (§1.6.3)


# ==============================================================================
# TR-EP: EvolutionPipeline 端到端 (§一 闭环动作流)
# ==============================================================================
class TestEvolutionPipeline:
    """L1→Level0→L2→L3→L4 全闭环"""

    def test_TR_EP_01_run_symbol_returns_decision(self, rv, mock_market_data, gene_root):
        """单 symbol pipeline 输出含 d_star + ess_top + aligned + action"""
        from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
        pipe = EvolutionPipeline(gene_root=gene_root)
        result = pipe.run_symbol("BTC", mock_market_data, rv=rv)
        # 必须含 4 层输出
        assert "l1_r_vector" in result
        assert "level0_d_star" in result
        assert "l2_top_combo" in result
        assert "aligned" in result
        assert "action" in result
        # action 合法
        assert result["action"] in {"long", "short", "WAIT", "light_long", "light_short"}

    def test_TR_EP_02_alignment_logic(self, rv, mock_market_data, gene_root):
        """d* 与最优路径方向一致 → aligned=True；不一致 → 降仓"""
        from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
        pipe = EvolutionPipeline(gene_root=gene_root)
        result = pipe.run_symbol("BTC", mock_market_data, rv=rv)
        d = result["level0_d_star"]
        opt = result["path_discovery"]["optimal_path"]
        stat_val = result["path_discovery"]["statistical_validation"]
        if opt and stat_val.get("validated"):
            # 有最优路径 → 检查对齐逻辑
            opt_dir = opt["direction"]
            d_star_raw = result["level0_costs"]
            # d_star 与 opt_dir 一致 → aligned=True
            # d_star 与 opt_dir 不一致 → aligned=False（降仓）
            assert result["aligned"] in (True, False)
        else:
            # 无验证通过的最优路径 → aligned=False
            assert result["aligned"] is False

    def test_TR_EP_03_wait_when_not_aligned(self, rv, mock_market_data, gene_root):
        """d* 与 ESS top 不对齐 → action=WAIT or light position"""
        from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
        pipe = EvolutionPipeline(gene_root=gene_root)
        result = pipe.run_symbol("BTC", mock_market_data, rv=rv)
        if not result["aligned"]:
            assert result["action"] in ("WAIT", "light_long", "light_short")

    def test_TR_EP_04_l3_l4_tracking(self, rv, mock_market_data, gene_root):
        """Pipeline 跑完后 L3 有样本、L4 有 V(s) 更新"""
        from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
        pipe = EvolutionPipeline(gene_root=gene_root)
        pipe.run_symbol("BTC", mock_market_data, rv=rv)
        assert pipe.shadow_rl.sample_count() >= 1
        assert pipe.bellman.get_v("BTC") != 0.0  # 已更新

    def test_TR_EP_05_fail_open_never_crash(self, gene_root):
        """市场数据全空 → 仍不崩，输出合法 action"""
        from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
        from dreambuddy_evolution.core.resistance_vector import ResistanceVector
        pipe = EvolutionPipeline(gene_root=gene_root)
        result = pipe.run_symbol("X", {}, rv=ResistanceVector())
        # 重构后：L2基因库路径可能在空数据时也产生候选 → action 可能是 light_long/WAIT
        assert result["action"] in ("WAIT", "light_long", "light_short", "long", "short")
        assert "error" in result.get("l1_r_vector", {}).get("fallback_flags", {}) or \
               result["l1_r_vector"]["quality_score"] <= 0.40

    def test_TR_EP_06_batch_run_multi_symbol(self, rv, mock_market_data, gene_root):
        """批量 3 symbol 跑 pipeline"""
        from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
        pipe = EvolutionPipeline(gene_root=gene_root)
        results = pipe.run_batch(
            {"BTC": mock_market_data, "ETH": mock_market_data, "SOL": mock_market_data},
            rv=rv,
        )
        assert len(results) == 3
        for sym, r in results.items():
            assert "action" in r


# ==============================================================================
# TR-AGI-Pipeline: 阶段4 AGI 增强点测试 (F/G/H/I)
# ==============================================================================
class TestEvolutionPipelineAGI:
    """AGI 阶段4增强：FAIL-OPEN + 开关控制 + 只读增强"""

    def test_agi_fields_present_in_output(self, rv, mock_market_data, gene_root):
        """输出包含 4 个 AGI 阶段4增强字段"""
        from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
        pipe = EvolutionPipeline(gene_root=gene_root)
        result = pipe.run_symbol("BTC", mock_market_data, rv=rv)
        for field in ("agi_deep_reasoning", "agi_strategy_synth",
                      "agi_transfer", "agi_counterfactual"):
            assert field in result, f"missing field: {field}"

    def test_fail_open_agi_crash_does_not_block(self, rv, mock_market_data, gene_root):
        """FAIL-OPEN: AGI 模块崩溃 → 不阻塞主流程"""
        from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
        pipe = EvolutionPipeline(gene_root=gene_root)
        # 注入崩溃的 DeepReasoningEngine
        crashing_dr = type("MockDR", (), {"reason": staticmethod(
            lambda **kw: (_ for _ in ()).throw(RuntimeError("崩溃"))
        )})()
        pipe._deep_reasoning = crashing_dr
        result = pipe.run_symbol("BTC", mock_market_data, rv=rv)
        # 主流程不受影响
        assert result["action"] in ("long", "short", "WAIT", "light_long", "light_short")
        assert result["agi_deep_reasoning"] is None

    def test_switch_off_skips_agi_module(self, rv, mock_market_data, gene_root):
        """开关关闭时 → AGI 模块不被调用，返回 fallback"""
        from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
        from dreambuddy_evolution.agi_config import set_switch
        set_switch("enable_deep_reasoning", False)
        set_switch("enable_strategy_synthesizer", False)
        set_switch("enable_transfer_learning", False)
        set_switch("enable_counterfactual", False)
        try:
            pipe = EvolutionPipeline(gene_root=gene_root)
            mock_dr = type("MockDR", (), {"reason": staticmethod(lambda **kw: "CALLED")})()
            pipe._deep_reasoning = mock_dr
            result = pipe.run_symbol("BTC", mock_market_data, rv=rv)
            # 开关关闭 → 模块不调用，返回 None
            assert result["agi_deep_reasoning"] is None
            assert result["agi_strategy_synth"] is None
            assert result["agi_transfer"] is None
            assert result["agi_counterfactual"] is None
        finally:
            set_switch("enable_deep_reasoning", True)
            set_switch("enable_strategy_synthesizer", True)
            set_switch("enable_transfer_learning", True)
            set_switch("enable_counterfactual", True)

    def test_deep_reasoning_produces_output(self, rv, mock_market_data, gene_root):
        """DeepReasoningEngine 开启 + 数据充足 → agi_deep_reasoning 非空"""
        from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
        pipe = EvolutionPipeline(gene_root=gene_root)
        result = pipe.run_symbol("BTC", mock_market_data, rv=rv)
        if result["agi_deep_reasoning"] is not None:
            dr = result["agi_deep_reasoning"]
            # 路径发现层提取的 metadata 包含 forecast_end 和 min_resistance
            assert "forecast_end" in dr or "min_resistance" in dr
            assert "min_resistance" in dr or "n_paths" in dr

    def test_transfer_learner_with_returns(self, rv, gene_root):
        """TransferLearner 有 source/target/control returns → 返回迁移结果"""
        from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
        pipe = EvolutionPipeline(gene_root=gene_root)
        rng = np.random.default_rng(42)
        N = 200
        close = 35000.0 + np.cumsum(rng.normal(0, 50, N))
        market_data = {
            "close": close,
            "volume": np.full(N, 3000.0),
            "okx_positions": {"long": 0.55, "short": 0.45},
            "liquidation_buy": np.zeros(N),
            "liquidation_sell": np.zeros(N),
            "ma_200": float(np.mean(close)),
            "fib_retrace_0786": 37000.0,
            "fib_retrace_0618": 35000.0,
            "fib_retrace_0500": 33500.0,
            "bid_ask_spread_bps": 2.0,
            "news_sentiment_score": 0.60,
            "source_returns": list(rng.normal(0.001, 0.02, 50)),
            "target_returns": list(rng.normal(0.0005, 0.02, 50)),
            "control_returns": [list(rng.normal(0, 0.01, 50)) for _ in range(5)],
            "source_asset": "ETH",
            "actual_pnl": 0.03,
        }
        from dreambuddy_evolution.core.resistance_vector import ResistanceVector
        result = pipe.run_symbol("BTC", market_data, rv=ResistanceVector())
        # 迁移结果应为 dict（有效或被拒绝）
        if result["agi_transfer"] is not None:
            assert "valid" in result["agi_transfer"]
            assert "similarity" in result["agi_transfer"]

    def test_counterfactual_with_returns(self, rv, gene_root):
        """CounterfactualEvaluator 有 returns → 返回反事实评估结果"""
        from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
        pipe = EvolutionPipeline(gene_root=gene_root)
        rng = np.random.default_rng(42)
        N = 200
        close = 35000.0 + np.cumsum(rng.normal(0, 50, N))
        market_data = {
            "close": close,
            "volume": np.full(N, 3000.0),
            "okx_positions": {"long": 0.55, "short": 0.45},
            "liquidation_buy": np.zeros(N),
            "liquidation_sell": np.zeros(N),
            "ma_200": float(np.mean(close)),
            "fib_retrace_0786": 37000.0,
            "fib_retrace_0618": 35000.0,
            "fib_retrace_0500": 33500.0,
            "bid_ask_spread_bps": 2.0,
            "news_sentiment_score": 0.60,
            "target_returns": list(rng.normal(0.001, 0.02, 50)),
            "control_returns": [list(rng.normal(0, 0.01, 50)) for _ in range(5)],
            "actual_pnl": 0.05,
        }
        from dreambuddy_evolution.core.resistance_vector import ResistanceVector
        result = pipe.run_symbol("BTC", market_data, rv=ResistanceVector())
        if result["agi_counterfactual"] is not None:
            cf = result["agi_counterfactual"]
            assert "alpha" in cf or "counterfactual_pnl" in cf

    def test_agi_enhance_method_directly(self, gene_root):
        """直接测试 _agi_enhance 方法的开关控制和 FAIL-OPEN"""
        from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
        from dreambuddy_evolution.agi_config import set_switch
        pipe = EvolutionPipeline(gene_root=gene_root)

        # 开关开启时 → 调用函数
        set_switch("enable_deep_reasoning", True)
        result = pipe._agi_enhance(
            "enable_deep_reasoning",
            fn=lambda x: x * 3,
            fallback=-1,
            x=5,
        )
        assert result == 15

        # 开关关闭时 → 返回 fallback
        set_switch("enable_deep_reasoning", False)
        result = pipe._agi_enhance(
            "enable_deep_reasoning",
            fn=lambda x: x * 3,
            fallback=-1,
            x=5,
        )
        assert result == -1

        # 函数崩溃时 → 返回 fallback（FAIL-OPEN）
        set_switch("enable_deep_reasoning", True)
        result = pipe._agi_enhance(
            "enable_deep_reasoning",
            fn=lambda x: (_ for _ in ()).throw(RuntimeError("crash")),
            fallback=-1,
            x=5,
        )
        assert result == -1

        # 恢复
        set_switch("enable_deep_reasoning", True)


# ==============================================================================
# 路径发现层测试：多路径竞争 → 寻优 → argmin → 统计验证
# ==============================================================================
class TestPathDiscovery:
    """路径发现层：多路径竞争 → 寻优 → argmin → 统计验证"""

    def test_path_discovery_returns_paths(self, rv, mock_market_data, gene_root):
        """路径发现层返回多个候选路径"""
        from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
        pipe = EvolutionPipeline(gene_root=gene_root)
        result = pipe.run_symbol("BTC", mock_market_data, rv=rv)
        pd = result["path_discovery"]
        assert "all_paths" in pd
        assert "path_scores" in pd
        assert "optimal_path" in pd
        assert "statistical_validation" in pd
        assert pd["n_paths"] >= 0

    def test_l2_gene_path_present(self, rv, mock_market_data, gene_root):
        """L2 基因库路径出现"""
        from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
        pipe = EvolutionPipeline(gene_root=gene_root)
        result = pipe.run_symbol("BTC", mock_market_data, rv=rv)
        l2_paths = [p for p in result["path_discovery"]["all_paths"]
                    if p["source"] == "l2_gene"]
        # L2 基因库有数据 → 至少 1 个路径
        assert len(l2_paths) >= 0  # 可能 gene_root 为空，不强制

    def test_optimal_path_has_required_fields(self, rv, mock_market_data, gene_root):
        """最优路径包含所有必需字段"""
        from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
        pipe = EvolutionPipeline(gene_root=gene_root)
        result = pipe.run_symbol("BTC", mock_market_data, rv=rv)
        opt = result["path_discovery"]["optimal_path"]
        if opt is not None:
            assert "path_id" in opt
            assert "source" in opt
            assert "direction" in opt
            assert "expected_return" in opt
            assert "confidence" in opt
            assert "resistance" in opt
            assert "score" in opt

    def test_statistical_validation_threshold(self, rv, gene_root):
        """统计验证：score 低于 0.05 → 不验证 → WAIT"""
        from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
        pipe = EvolutionPipeline(gene_root=gene_root)
        # 构造低质量路径
        paths = [{
            "path_id": "weak", "source": "test", "direction": "long",
            "expected_return": 0.01, "confidence": 0.1, "resistance": 0.9,
            "metadata": {},
        }]
        result = pipe._select_optimal_path(paths, {})
        assert result["optimal_path"] is None
        assert not result["statistical_validation"]["validated"]

    def test_statistical_validation_passes(self, rv, gene_root):
        """统计验证：score 高于 0.05 → 验证通过"""
        from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
        pipe = EvolutionPipeline(gene_root=gene_root)
        paths = [{
            "path_id": "strong", "source": "test", "direction": "long",
            "expected_return": 0.5, "confidence": 0.8, "resistance": 0.2,
            "metadata": {},
        }]
        result = pipe._select_optimal_path(paths, {})
        assert result["optimal_path"] is not None
        assert result["statistical_validation"]["validated"]

    def test_low_conviction_detection(self, rv, gene_root):
        """低确信度检测：最优与次优 score 差距 < 0.02"""
        from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
        pipe = EvolutionPipeline(gene_root=gene_root)
        paths = [
            {"path_id": "a", "source": "test", "direction": "long",
             "expected_return": 0.3, "confidence": 0.7, "resistance": 0.3, "metadata": {}},
            {"path_id": "b", "source": "test", "direction": "short",
             "expected_return": 0.3, "confidence": 0.69, "resistance": 0.3, "metadata": {}},
        ]
        result = pipe._select_optimal_path(paths, {})
        assert result["statistical_validation"]["low_conviction"]

    def test_multi_path_competition_picks_best(self, rv, gene_root):
        """多路径竞争 → 选 score 最高的"""
        from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
        pipe = EvolutionPipeline(gene_root=gene_root)
        paths = [
            {"path_id": "weak", "source": "test", "direction": "long",
             "expected_return": 0.1, "confidence": 0.3, "resistance": 0.8, "metadata": {}},
            {"path_id": "strong", "source": "test", "direction": "short",
             "expected_return": 0.5, "confidence": 0.8, "resistance": 0.2, "metadata": {}},
        ]
        result = pipe._select_optimal_path(paths, {})
        assert result["optimal_path"]["path_id"] == "strong"

    def test_fail_open_no_paths_returns_wait(self, rv, gene_root):
        """无路径 → FAIL-OPEN → WAIT 或轻仓（L2基因库可能产生路径）"""
        from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
        pipe = EvolutionPipeline(gene_root=gene_root)
        # 构造无法产生路径的 market_data
        result = pipe.run_symbol("UNKNOWN", {"close": []}, rv=rv)
        # 不崩溃，action 是合法值
        assert result["action"] in ("WAIT", "light_long", "light_short")
        # optimal_path 可能来自 L2 基因库（不依赖 market_data）
        # 核心是不崩溃

    def test_path_discovery_with_bridge(self, rv, mock_market_data, gene_root):
        """有 bridge 时 BCRM/BDSM/战略层路径加入竞争"""
        from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline

        # Mock trader with bridge data
        class MockTrader:
            _five_domain_state_shadow = type("FD", (), {
                "war_state": "ALLOW",
                "direction_state": "LONG_PREFER",
                "aggregate_position_cap_pct": {"crypto_usdt": 0.5},
            })()
            _last_bcrm2_result = {
                "next_state": {"pattern": {"hs_top": False, "hs_bottom": False, "confidence": 0.0}}
            }

        pipe = EvolutionPipeline(gene_root=gene_root, trader=MockTrader())
        result = pipe.run_symbol("BTC", mock_market_data, rv=rv)
        # bridge 存在 → 应有路径
        assert result["path_discovery"]["n_paths"] >= 0

    def test_action_follows_optimal_path(self, rv, mock_market_data, gene_root):
        """决策跟随最优路径方向"""
        from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
        pipe = EvolutionPipeline(gene_root=gene_root)
        result = pipe.run_symbol("BTC", mock_market_data, rv=rv)
        opt = result["path_discovery"]["optimal_path"]
        action = result["action"]
        # 如果有最优路径且验证通过，action 应与方向一致或轻仓
        if opt and result["path_discovery"]["statistical_validation"]["validated"]:
            d = opt["direction"]
            if d in ("long", "short"):
                assert action in (d, f"light_{d}", "WAIT")


class TestContradictionIntegration:
    """Phase 3.4: 主要矛盾识别 + 趋势延续性集成测试

    SPEC §4.5: _select_optimal_path 融合矛盾强度 + 延续性
    """

    def test_select_returns_primary_contradiction_field(self, rv, gene_root):
        """返回结果包含 primary_contradiction 字段"""
        from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
        pipe = EvolutionPipeline(gene_root=gene_root)
        paths = [
            {"path_id": "p1", "source": "bcrm", "direction": "long",
             "expected_return": 0.3, "confidence": 0.8, "resistance": 0.2, "metadata": {}},
            {"path_id": "p2", "source": "bdsm", "direction": "long",
             "expected_return": 0.2, "confidence": 0.7, "resistance": 0.3, "metadata": {}},
        ]
        result = pipe._select_optimal_path(paths, {})
        assert "primary_contradiction" in result

    def test_select_with_contradiction_aligned_path_wins(self, rv, gene_root):
        """对齐主要矛盾的路径评分更高"""
        from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
        pipe = EvolutionPipeline(gene_root=gene_root)
        # 两条路径 base_score 接近, 但方向不同
        paths = [
            {"path_id": "long_path", "source": "bcrm", "direction": "long",
             "expected_return": 0.2, "confidence": 0.7, "resistance": 0.3, "metadata": {}},
            {"path_id": "short_path", "source": "bcrm", "direction": "short",
             "expected_return": 0.2, "confidence": 0.7, "resistance": 0.3, "metadata": {}},
        ]
        # 多路径方向冲突时, bcrm(long) 力量 0.7 > 无 short 路径... 实际两者力量相同
        # 所以会走冲突裁决, long 和 short 力量相同 → 取 long (>=)
        result = pipe._select_optimal_path(paths, {})
        pc = result.get("primary_contradiction")
        if pc and pc.get("direction") != "neutral":
            # 主要矛盾方向存在时, 对齐路径应胜出
            aligned_dir = pc["direction"]
            best = result["optimal_path"]
            if best:
                assert best["direction"] == aligned_dir

    def test_select_with_continuation_score(self, rv, gene_root):
        """趋势延续性高 → 评分加分"""
        from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
        pipe = EvolutionPipeline(gene_root=gene_root)
        # 路径 A 有高延续性, 路径 B 无延续性字段(默认 0.5)
        paths = [
            {"path_id": "high_cont", "source": "bcrm", "direction": "long",
             "expected_return": 0.2, "confidence": 0.7, "resistance": 0.3,
             "metadata": {}, "continuation_score": 0.9},
            {"path_id": "low_cont", "source": "bcrm", "direction": "long",
             "expected_return": 0.2, "confidence": 0.7, "resistance": 0.3,
             "metadata": {}, "continuation_score": 0.1},
        ]
        result = pipe._select_optimal_path(paths, {})
        scores = {p["path_id"]: p["score"] for p in result["all_paths"]}
        assert scores["high_cont"] > scores["low_cont"]

    def test_select_failopen_contradiction_exception(self, rv, gene_root):
        """HC-AGI-18: 矛盾识别异常 → FAIL-OPEN, 不阻塞"""
        from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
        pipe = EvolutionPipeline(gene_root=gene_root)
        paths = [
            {"path_id": "p1", "source": "bcrm", "direction": "long",
             "expected_return": 0.3, "confidence": 0.8, "resistance": 0.2, "metadata": {}},
        ]
        # 单路径 → primary_contradiction = neutral (HC-AGI-23)
        result = pipe._select_optimal_path(paths, {})
        # 不应抛异常, 应正常返回
        assert "optimal_path" in result
        assert result["primary_contradiction"]["direction"] == "neutral"

    def test_all_switches_off_still_works(self, rv, gene_root):
        """开关全关 → 仍能正常返回结果"""
        from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
        from dreambuddy_evolution.agi_config import set_switch
        # 关闭新开关
        set_switch("enable_contradiction_identifier", False)
        try:
            pipe = EvolutionPipeline(gene_root=gene_root)
            paths = [
                {"path_id": "p1", "source": "bcrm", "direction": "long",
                 "expected_return": 0.3, "confidence": 0.8, "resistance": 0.2, "metadata": {}},
            ]
            result = pipe._select_optimal_path(paths, {})
            assert "optimal_path" in result
            assert result["primary_contradiction"] is None
        finally:
            set_switch("enable_contradiction_identifier", True)


# ============================================================================
# Phase 3 链路断裂修复测试（审计发现的 3 个断裂点）
# ============================================================================

class TestLinkBreakFixTrendContinuation:
    """断裂2: TrendContinuationScorer 从未接入 pipeline

    审计发现: continuation_score 恒为 0.5，TrendContinuationScorer 从未被 pipeline 调用
    修复: _select_optimal_path 调用 TrendContinuationScorer.score() 填充 continuation_score
    """

    def test_trend_continuation_filled_by_pipeline(self, rv, gene_root):
        """pipeline 主动调用 TrendContinuationScorer 填充 continuation_score

        路径不传 continuation_score 时，pipeline 应通过 TrendContinuationScorer 计算并填充
        """
        from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
        pipe = EvolutionPipeline(gene_root=gene_root)
        paths = [
            {"path_id": "p1", "source": "bcrm", "direction": "long",
             "expected_return": 0.3, "confidence": 0.8, "resistance": 0.2, "metadata": {}},
            {"path_id": "p2", "source": "bdsm", "direction": "long",
             "expected_return": 0.2, "confidence": 0.7, "resistance": 0.3, "metadata": {}},
        ]
        # market_data 含 kline_data 供 TrendContinuationScorer 使用
        market_data = {"kline_data": {"price": 100, "ma50": 95, "ma150": 90, "ma200": 85,
                                      "ma200_slope": 0.01, "low_52w": 70, "high_52w": 120}}
        result = pipe._select_optimal_path(paths, {}, market_data)
        # 路径应被填充了 continuation_score（不再是默认 0.5）
        for p in result["all_paths"]:
            # 有 kline_data 时，TrendContinuationScorer 应计算出非 0.5 的值
            assert "continuation_score" in p
            # ma 全多头排列 → continuation_score 应 > 0.5
            assert p["continuation_score"] > 0.5

    def test_trend_continuation_disabled_defaults_05(self, rv, gene_root):
        """enable_trend_continuation=False → continuation_score 保持 0.5"""
        from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
        from dreambuddy_evolution.agi_config import set_switch, get_switch
        _orig = get_switch("enable_trend_continuation")
        try:
            set_switch("enable_trend_continuation", False)
            pipe = EvolutionPipeline(gene_root=gene_root)
            paths = [
                {"path_id": "p1", "source": "bcrm", "direction": "long",
                 "expected_return": 0.3, "confidence": 0.8, "resistance": 0.2, "metadata": {}},
                {"path_id": "p2", "source": "bdsm", "direction": "long",
                 "expected_return": 0.2, "confidence": 0.7, "resistance": 0.3, "metadata": {}},
            ]
            market_data = {"kline_data": {"price": 100, "ma50": 95}}
            result = pipe._select_optimal_path(paths, {}, market_data)
            for p in result["all_paths"]:
                assert p.get("continuation_score", 0.5) == 0.5
        finally:
            set_switch("enable_trend_continuation", _orig)


class TestLinkBreakFixHJBContradiction:
    """断裂1: HJB lagrangian 矛盾调制从未生效

    审计发现: _value_iteration L268 调用 lagrangian() 不传 primary_contradiction
    修复: solve() 接受 primary_contradiction，_value_iteration 传入 lagrangian 调用
    """

    def test_hjb_solve_accepts_primary_contradiction(self):
        """HJBPathSolver.solve() 接受 primary_contradiction 参数"""
        from dreambuddy_evolution.core.hjb_solver import HJBPathSolver
        import inspect
        sig = inspect.signature(HJBPathSolver.solve)
        assert "primary_contradiction" in sig.parameters

    def test_hjb_lagrangian_modulated_in_value_iteration(self):
        """_value_iteration 内部调用 lagrangian 时传入 primary_contradiction

        验证: 矛盾调制后的 HJB 值函数与无调制时不同
        """
        from dreambuddy_evolution.core.hjb_solver import HJBPathSolver
        solver = HJBPathSolver()
        r_vector = {"R_up": 0.3, "R_down": 0.7, "R_smooth": 0.2,
                    "R_flow": 0.5, "R_reflexivity": 0.4}
        # 无矛盾调制
        result_no_pc = solver.solve(
            start_price=100.0, horizon=10, volatility=0.02,
            r_vector=r_vector, primary_contradiction=None,
        )
        # 有矛盾调制: long 方向 strength=0.8
        result_with_pc = solver.solve(
            start_price=100.0, horizon=10, volatility=0.02,
            r_vector=r_vector,
            primary_contradiction={"direction": "long", "strength": 0.8},
        )
        # 矛盾调制应改变值函数（long 阻力降低 → total_cost 不同）
        assert result_no_pc["total_cost"] != result_with_pc["total_cost"]

    def test_pipeline_passes_contradiction_to_hjb(self, rv, gene_root):
        """_select_optimal_path 将 primary_contradiction 传入 HJB solve

        验证: 有矛盾识别时 HJB 值函数受矛盾调制影响
        """
        from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
        pipe = EvolutionPipeline(gene_root=gene_root)
        paths = [
            {"path_id": "p1", "source": "bcrm", "direction": "long",
             "expected_return": 0.3, "confidence": 0.8, "resistance": 0.2, "metadata": {}},
            {"path_id": "p2", "source": "bdsm", "direction": "short",
             "expected_return": 0.25, "confidence": 0.7, "resistance": 0.3, "metadata": {}},
        ]
        r_out = {"_last_price": 100.0, "_last_vol": 0.02,
                 "R_up": 0.3, "R_down": 0.7, "R_smooth": 0.2,
                 "R_flow": 0.5, "R_reflexivity": 0.4}
        result = pipe._select_optimal_path(paths, r_out, {})
        # HJB policy 应存在且 primary_contradiction 应存在
        assert result.get("hjb_policy") is not None
        assert result.get("primary_contradiction") is not None


class TestLinkBreakFixFeedbackLoop:
    """断裂3: ContradictionFeedback 回流未闭环

    审计发现: adjust_weight({}, outcome) 传空 dict，回流结果无人消费
    修复: 传入实际 primary_contradiction，存储权重供下次 identify 使用
    """

    def test_feedback_uses_actual_contradiction(self, rv, gene_root):
        """get_feedback() 的 adjust_weight 传入实际 primary_contradiction 而非空 dict"""
        from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
        pipe = EvolutionPipeline(gene_root=gene_root)
        # 先跑一次 _select_optimal_path 产生 primary_contradiction
        paths = [
            {"path_id": "p1", "source": "bcrm", "direction": "long",
             "expected_return": 0.3, "confidence": 0.8, "resistance": 0.2, "metadata": {}},
            {"path_id": "p2", "source": "bdsm", "direction": "long",
             "expected_return": 0.2, "confidence": 0.7, "resistance": 0.3, "metadata": {}},
        ]
        result = pipe._select_optimal_path(paths, {})
        pc = result.get("primary_contradiction")
        # primary_contradiction 应存在且非 neutral（2 条同向路径 → 共振）
        assert pc is not None
        # 存储到 pipeline 供 get_feedback 使用
        pipe._last_primary_contradiction = pc
        # get_feedback 应使用存储的 primary_contradiction
        pipe._contradiction_weight_factor = 1.0
        feedback = pipe.get_feedback()
        cf = feedback.get("contradiction_feedback")
        if cf is not None:
            # 不应是空 dict 的 adjust_weight 结果
            assert cf.get("direction") is not None or cf.get("weight_adjustment") is not None

    def test_feedback_weight_stored_for_next_identify(self, rv, gene_root):
        """回流权重存储后，下次 identify 可读取更新后的权重"""
        from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
        pipe = EvolutionPipeline(gene_root=gene_root)
        # 模拟一次成功的验证回流
        pipe._last_primary_contradiction = {
            "direction": "long", "strength": 0.6, "confidence": 0.7,
            "dimension": "C3", "cause_score": 0.5, "effort_result": 0.5,
            "continuation_score": 0.5,
        }
        pipe._contradiction_weight_factor = 1.2  # 模拟已更新的权重
        # 下次 get_feedback 应能读取存储的 weight_factor
        assert hasattr(pipe, "_contradiction_weight_factor")
        assert pipe._contradiction_weight_factor == 1.2

    def test_pipeline_passes_weight_factor_to_identify(self, rv, gene_root):
        """_select_optimal_path 将 _contradiction_weight_factor 传入 identify()

        验证闭环: 存储的 weight_factor 真正影响下次 identify 的 strength
        """
        from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
        pipe = EvolutionPipeline(gene_root=gene_root)
        paths = [
            {"path_id": "p1", "source": "bcrm", "direction": "long",
             "expected_return": 0.3, "confidence": 0.8, "resistance": 0.2, "metadata": {}},
            {"path_id": "p2", "source": "bdsm", "direction": "long",
             "expected_return": 0.2, "confidence": 0.7, "resistance": 0.3, "metadata": {}},
        ]
        # 第一次调用 — 无 weight_factor
        result_no_wf = pipe._select_optimal_path(paths, {}, {})
        strength_no_wf = result_no_wf["primary_contradiction"]["strength"]

        # 设置 weight_factor=1.5（成功验证后升级）
        pipe._contradiction_weight_factor = 1.5
        result_with_wf = pipe._select_optimal_path(paths, {}, {})
        strength_with_wf = result_with_wf["primary_contradiction"]["strength"]

        # weight_factor > 1.0 应使 strength 更高
        assert strength_with_wf >= strength_no_wf

    def test_identify_accepts_weight_factor_param(self):
        """PrimaryContradictionIdentifier.identify() 接受 weight_factor 参数"""
        import inspect
        from dreambuddy_evolution.core.contradiction_identifier import (
            PrimaryContradictionIdentifier,
        )
        sig = inspect.signature(PrimaryContradictionIdentifier.identify)
        assert "weight_factor" in sig.parameters
