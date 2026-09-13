"""
test_strategy_synthesizer — StrategySynthesizer 单元测试

覆盖：
  - Decision Transformer 轨迹学习（torch + 统计降级）
  - 遗传编程参数变异 + 组合交叉
  - 回测验证（Sharpe/最大回撤/达标判断）
  - 完整 synthesize 流程
  - FAIL-OPEN（空输入/异常不 crash）
"""
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from dreambuddy_evolution.core.strategy_synthesizer import StrategySynthesizer


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------
@pytest.fixture
def synth():
    return StrategySynthesizer(gene_root=REPO / "dreambuddy_evolution" / "gene_data")


@pytest.fixture
def sample_trades():
    """模拟历史交易轨迹"""
    trades = []
    for i in range(20):
        n_steps = 20
        states = [[float(i * 0.1), float(j * 0.01), np.random.randn()] for j in range(n_steps)]
        actions = [[float(np.random.randn()), float(np.random.randn() > 0)] for _ in range(n_steps)]
        rewards = [float(np.random.randn() * 0.01) for _ in range(n_steps)]
        sharpe = float(np.random.uniform(-0.5, 2.0))
        trades.append({"states": states, "actions": actions, "rewards": rewards, "sharpe": sharpe})
    return trades


@pytest.fixture
def sample_gene_library():
    """模拟基因库"""
    return {
        "conditions": [
            {
                "gene_id": "CD-ADX-GT25-TREND",
                "category": "trend",
                "condition_type": "market_state",
                "expression": "adx_14 > 25",
                "parameters": {
                    "adx_threshold": {"value": 25, "range": {"low": 20, "high": 40}},
                    "adx_window": {"value": 14, "range": {"low": 7, "high": 28}},
                },
                "tags": ["trend"],
            },
            {
                "gene_id": "CD-RSI30-BOLL-TOUCH",
                "category": "momentum",
                "condition_type": "indicator",
                "expression": "rsi < 30 AND boll_lower_touch",
                "parameters": {
                    "rsi_oversold": {"value": 30, "range": {"low": 20, "high": 40}},
                },
                "tags": ["momentum"],
            },
        ],
        "combinations": [
            {"combo_id": "CB-001", "condition_ids": ["CD-ADX-GT25-TREND"], "action_ids": ["AC-001"], "ess": 0.8},
            {"combo_id": "CB-002", "condition_ids": ["CD-RSI30-BOLL-TOUCH"], "action_ids": ["AC-002"], "ess": 0.6},
        ],
    }


@pytest.fixture
def sample_prices():
    """合成价格数据"""
    return StrategySynthesizer._synth_prices(500)


# ------------------------------------------------------------------
# 1. Decision Transformer 轨迹学习
# ------------------------------------------------------------------
class TestDecisionTransformer:
    def test_dt_learn_with_torch(self, synth, sample_trades):
        """torch 可用时用 Decision Transformer"""
        result = synth.dt_learn_trajectories(sample_trades)
        assert result["n_trajectories"] > 0
        assert result["top_sharpe"] > 0
        assert len(result["learned_patterns"]) > 0
        # torch 可用时 method 应为 decision_transformer
        if synth.backend_status()["torch"]:
            assert result["method"] == "decision_transformer"
            assert result["model_loaded"] is True

    def test_dt_empty_input_failopen(self, synth):
        """空输入 FAIL-OPEN"""
        result = synth.dt_learn_trajectories([])
        assert result["n_trajectories"] == 0
        assert result["learned_patterns"] == []

    def test_dt_statistical_fallback(self, sample_trades):
        """禁用 DT 时走统计降级"""
        s = StrategySynthesizer(enable_dt=False)
        result = s.dt_learn_trajectories(sample_trades)
        assert result["method"] == "statistical_fallback"
        assert len(result["learned_patterns"]) > 0

    def test_dt_exception_failopen(self, synth):
        """异常输入不 crash"""
        result = synth.dt_learn_trajectories([{"bad": "data"}])
        assert result["method"] in ("statistical_fallback", "unavailable")


# ------------------------------------------------------------------
# 2. 遗传编程
# ------------------------------------------------------------------
class TestGeneticProgramming:
    def test_gp_generates_candidates(self, synth, sample_gene_library):
        """GP 生成候选基因"""
        candidates = synth.genetic_programming(sample_gene_library, n_candidates=5)
        assert len(candidates) > 0
        for c in candidates:
            assert "gene_id" in c
            assert c["gene_id"].startswith("CD-GP-")
            assert "parameters" in c

    def test_gp_mutation_within_range(self, synth, sample_gene_library):
        """变异后的参数值在 range 内"""
        candidates = synth.genetic_programming(sample_gene_library, n_candidates=10)
        for c in candidates:
            for pname, pdef in c["parameters"].items():
                if isinstance(pdef, dict) and "value" in pdef and "range" in pdef:
                    val = pdef["value"]
                    lo = pdef["range"]["low"]
                    hi = pdef["range"]["high"]
                    assert lo <= val <= hi, f"{pname}={val} not in [{lo},{hi}]"

    def test_gp_preserves_gene_structure(self, synth, sample_gene_library):
        """变异保留基因基本结构（category/condition_type 与 parent 一致）"""
        candidates = synth.genetic_programming(sample_gene_library, n_candidates=10)
        cond_map = {c["gene_id"]: c for c in sample_gene_library["conditions"]}
        for c in candidates:
            parent_id = c.get("parent_gene_id")
            if parent_id and parent_id in cond_map:
                parent = cond_map[parent_id]
                assert c["category"] == parent["category"]
                assert c["condition_type"] == parent["condition_type"]

    def test_gp_disabled_returns_empty(self, sample_gene_library):
        """禁用 GP 返回空"""
        s = StrategySynthesizer(enable_gp=False)
        candidates = s.genetic_programming(sample_gene_library)
        assert candidates == []

    def test_gp_empty_library_failopen(self, synth):
        """空基因库 FAIL-OPEN"""
        candidates = synth.genetic_programming({"conditions": [], "combinations": []})
        assert candidates == []


# ------------------------------------------------------------------
# 3. 回测验证
# ------------------------------------------------------------------
class TestBacktestValidate:
    def test_backtest_returns_metrics(self, synth, sample_gene_library, sample_prices):
        """回测返回完整指标"""
        candidate = sample_gene_library["conditions"][0]
        result = synth.backtest_validate(candidate, sample_prices, top_gene_sharpe=1.0)
        assert "sharpe" in result
        assert "max_drawdown" in result
        assert "n_trades" in result
        assert "passes_threshold" in result
        assert "score" in result
        assert result["gene_id"] == candidate["gene_id"]

    def test_backtest_sharpe_clamped(self, synth, sample_gene_library, sample_prices):
        """Sharpe 被 clamp 到 [-5, 5]"""
        candidate = sample_gene_library["conditions"][0]
        result = synth.backtest_validate(candidate, sample_prices, top_gene_sharpe=1.0)
        assert -5.0 <= result["sharpe"] <= 5.0

    def test_backtest_max_drawdown_in_range(self, synth, sample_gene_library, sample_prices):
        """最大回撤在 [0, 1]"""
        candidate = sample_gene_library["conditions"][0]
        result = synth.backtest_validate(candidate, sample_prices, top_gene_sharpe=1.0)
        assert 0.0 <= result["max_drawdown"] <= 1.0

    def test_backtest_passes_threshold(self, synth, sample_gene_library, sample_prices):
        """top Sharpe 很低时容易通过，很高时难通过"""
        candidate = sample_gene_library["conditions"][0]
        # top_sharpe=0 → 阈值=0，容易通过
        r_easy = synth.backtest_validate(candidate, sample_prices, top_gene_sharpe=0.0)
        # top_sharpe=10 → 阈值=8，难通过
        r_hard = synth.backtest_validate(candidate, sample_prices, top_gene_sharpe=10.0)
        # 至少一个的 passes 应与阈值逻辑一致
        assert r_easy["passes_threshold"] or not r_hard["passes_threshold"]

    def test_backtest_no_price_uses_synth(self, synth, sample_gene_library):
        """无价格数据时用合成数据"""
        candidate = sample_gene_library["conditions"][0]
        result = synth.backtest_validate(candidate, None, top_gene_sharpe=1.0)
        assert result["sharpe"] is not None

    def test_backtest_failopen_on_bad_candidate(self, synth, sample_prices):
        """异常候选基因不 crash"""
        result = synth.backtest_validate({"gene_id": "bad", "parameters": None}, sample_prices)
        assert result["sharpe"] == 0.0
        assert result["passes_threshold"] is False


# ------------------------------------------------------------------
# 4. 完整 synthesize 流程
# ------------------------------------------------------------------
class TestSynthesize:
    def test_synthesize_full_pipeline(self, synth, sample_trades, sample_gene_library, sample_prices):
        """完整流程：学习→变异→验证→筛选"""
        result = synth.synthesize(
            historical_trades=sample_trades,
            gene_library=sample_gene_library,
            price_data=sample_prices,
            n_candidates=5,
            top_gene_sharpe=1.0,
        )
        assert "dt_result" in result
        assert "candidates" in result
        assert "validated" in result
        assert "accepted_genes" in result
        assert "n_accepted" in result
        assert len(result["candidates"]) > 0
        assert len(result["validated"]) == len(result["candidates"])

    def test_synthesize_accepted_pass_threshold(self, synth, sample_trades, sample_gene_library, sample_prices):
        """accepted_genes 中的基因必须 passes_threshold=True"""
        result = synth.synthesize(
            historical_trades=sample_trades,
            gene_library=sample_gene_library,
            price_data=sample_prices,
            n_candidates=5,
            top_gene_sharpe=0.0,  # 低阈值让更多通过
        )
        for acc in result["accepted_genes"]:
            assert acc["validation"]["passes_threshold"] is True

    def test_synthesize_no_trades(self, synth, sample_gene_library, sample_prices):
        """无历史交易也能运行（DT 降级）"""
        result = synth.synthesize(
            historical_trades=None,
            gene_library=sample_gene_library,
            price_data=sample_prices,
            n_candidates=3,
        )
        assert len(result["candidates"]) > 0

    def test_synthesize_stats_updated(self, synth, sample_trades, sample_gene_library, sample_prices):
        """统计计数器更新"""
        result = synth.synthesize(
            historical_trades=sample_trades,
            gene_library=sample_gene_library,
            price_data=sample_prices,
            n_candidates=3,
        )
        assert result["stats"]["gp_candidates_generated"] > 0
        assert result["stats"]["genes_validated"] > 0


# ------------------------------------------------------------------
# 5. 真实基因库集成
# ------------------------------------------------------------------
class TestRealGeneLibrary:
    def test_gp_on_real_library(self, synth):
        """用真实基因库做 GP"""
        from dreambuddy_evolution.core.strategy_gene import load_gene_library

        lib = load_gene_library(synth._gene_root)
        assert lib["conditions"], "真实基因库应有 conditions"
        candidates = synth.genetic_programming(lib, n_candidates=5)
        assert len(candidates) > 0
        for c in candidates:
            assert c["gene_id"].startswith("CD-GP-")

    def test_synthesize_on_real_library(self, synth, sample_trades, sample_prices):
        """真实基因库端到端 synthesize"""
        from dreambuddy_evolution.core.strategy_gene import load_gene_library

        lib = load_gene_library(synth._gene_root)
        # 获取 top 基因 Sharpe（用 ESS 代理）
        top_ess = max((c.get("ess", 0) for c in lib["combinations"]), default=1.0)
        result = synth.synthesize(
            historical_trades=sample_trades,
            gene_library=lib,
            price_data=sample_prices,
            n_candidates=5,
            top_gene_sharpe=float(top_ess),
        )
        assert len(result["candidates"]) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
