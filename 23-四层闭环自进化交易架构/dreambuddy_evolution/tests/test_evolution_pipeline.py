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
        """d* 与 ESS top strategy direction 一致 → aligned=True"""
        from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
        pipe = EvolutionPipeline(gene_root=gene_root)
        result = pipe.run_symbol("BTC", mock_market_data, rv=rv)
        d = result["level0_d_star"]
        top = result["l2_top_combo"]
        if top and d in ("long", "short"):
            # Check alignment logic is correct
            top_dir = top.get("resolved_direction", "")
            if top_dir == d:
                assert result["aligned"] is True
            else:
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
        """市场数据全空 → 仍不崩，输出 WAIT"""
        from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
        from dreambuddy_evolution.core.resistance_vector import ResistanceVector
        pipe = EvolutionPipeline(gene_root=gene_root)
        result = pipe.run_symbol("X", {}, rv=ResistanceVector())
        assert result["action"] in ("WAIT",)
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
