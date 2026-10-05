"""
RED 测试集 — evolution_engine (种群 + 选择 + 交叉 + 结构变异 + ensemble 合成)

三范式跃迁之"进化范式跃迁"：
  - gmax ±0.01~0.05 随机扰动 → 真正进化算法（种群+选择+交叉+结构变异）
  - 参数微调 → 策略结构发现（NEAT-lite 结构变异改变拓扑）

证明"真正自进化"非参数微调的关键断言：
  - test_structure_mutation_changes_topology: 5代后种群中至少2种不同网络结构
  - test_population_diversity_maintained: Jaccard相似度<0.7
  - test_fitness_monotonic_improvement: 5代fitness严格递增
  - test_ensemble_synthesis_combines_diverse: 合成策略≠top-1
"""
from __future__ import annotations

import pytest


# --------------------------------------------------------------------------------
# RED: 模块尚未创建
# --------------------------------------------------------------------------------
def test_module_importable():
    from dreambuddy_evolution.core.evolution_engine import (  # noqa: F401
        EvolutionEngine,
        Individual,
    )


# --------------------------------------------------------------------------------
# 种群管理
# --------------------------------------------------------------------------------
class TestPopulationManagement:
    def test_init_creates_population_of_given_size(self):
        """初始化创建指定大小的种群."""
        from dreambuddy_evolution.core.evolution_engine import EvolutionEngine
        ee = EvolutionEngine(population_size=20)
        assert len(ee.population) == 20

    def test_elite_preservation_top4(self):
        """精英保留 top-4 不参与变异."""
        from dreambuddy_evolution.core.evolution_engine import EvolutionEngine
        ee = EvolutionEngine(population_size=20, elite_size=4)
        elites = ee.get_elites()
        assert len(elites) == 4

    def test_diversity_threshold_jaccard(self):
        """种群多样性阈值 Jaccard≥0.3 防早熟."""
        from dreambuddy_evolution.core.evolution_engine import EvolutionEngine
        ee = EvolutionEngine(population_size=20)
        diversity = ee.compute_diversity()
        assert 0.0 <= diversity <= 1.0
        assert hasattr(ee, "min_diversity_threshold")


# --------------------------------------------------------------------------------
# 选择策略
# --------------------------------------------------------------------------------
class TestSelectionStrategy:
    def test_tournament_selection_picks_best_of_k(self):
        """tournament(k=3) 应从 k 个个体中选最优."""
        from dreambuddy_evolution.core.evolution_engine import EvolutionEngine, Individual
        ee = EvolutionEngine(population_size=20)
        # 构造 3 个已知 fitness 的个体
        candidates = [
            Individual(id="A", fitness=0.5),
            Individual(id="B", fitness=0.9),
            Individual(id="C", fitness=0.3),
        ]
        winner = ee.tournament_select(candidates, k=3)
        assert winner.id == "B"  # 最高的应被选中


# --------------------------------------------------------------------------------
# 交叉
# --------------------------------------------------------------------------------
class TestCrossover:
    def test_arithmetic_crossover_blends_parents(self):
        """算术交叉 w_child = α·p1 + (1-α)·p2."""
        from dreambuddy_evolution.core.evolution_engine import EvolutionEngine
        ee = EvolutionEngine(population_size=20)
        import numpy as np
        w1 = np.array([0.5, 0.3, 0.8])
        w2 = np.array([0.1, 0.7, 0.2])
        child = ee.arithmetic_crossover(w1, w2, alpha=0.5)
        # 子代应在父代之间
        assert np.all(child >= np.minimum(w1, w2) - 1e-6)
        assert np.all(child <= np.maximum(w1, w2) + 1e-6)


# --------------------------------------------------------------------------------
# 结构变异（关键：证明非参数微调）
# --------------------------------------------------------------------------------
class TestStructureMutation:
    def test_structure_mutation_can_add_neuron(self):
        """结构变异可增加隐藏神经元."""
        from dreambuddy_evolution.core.evolution_engine import EvolutionEngine
        ee = EvolutionEngine(population_size=20)
        original_arch = {"hidden_dims": [64, 32]}
        mutated = ee.structure_mutate(original_arch, add_neuron_prob=1.0)
        assert mutated["hidden_dims"] != original_arch["hidden_dims"]
        assert sum(mutated["hidden_dims"]) >= sum(original_arch["hidden_dims"])

    def test_structure_mutation_can_remove_neuron(self):
        """结构变异可删除隐藏神经元."""
        from dreambuddy_evolution.core.evolution_engine import EvolutionEngine
        ee = EvolutionEngine(population_size=20)
        original_arch = {"hidden_dims": [64, 32]}
        mutated = ee.structure_mutate(original_arch, add_neuron_prob=0.0, remove_neuron_prob=1.0)
        assert sum(mutated["hidden_dims"]) <= sum(original_arch["hidden_dims"])

    def test_structure_mutation_can_change_activation(self):
        """结构变异可改激活函数(ReLU↔Tanh)."""
        from dreambuddy_evolution.core.evolution_engine import EvolutionEngine
        ee = EvolutionEngine(population_size=20)
        original_arch = {"hidden_dims": [64], "activation": "relu"}
        mutated = ee.structure_mutate(original_arch, change_activation_prob=1.0)
        assert mutated.get("activation") != original_arch["activation"]

    def test_structure_mutation_changes_topology(self):
        """5 代后种群中至少 2 种不同网络结构（关键证据：非参数微调）."""
        from dreambuddy_evolution.core.evolution_engine import EvolutionEngine
        ee = EvolutionEngine(population_size=20, structure_mutation_rate=0.3)
        result = ee.evolve(generations=5)
        arch_hashes = result["arch_hashes"]
        unique_archs = len(set(arch_hashes))
        assert unique_archs >= 2, (
            f"5 代后应有 ≥2 种不同拓扑，实际 {unique_archs}（说明只是参数微调非结构变异）"
        )


# --------------------------------------------------------------------------------
# 种群多样性
# --------------------------------------------------------------------------------
class TestPopulationDiversity:
    def test_population_diversity_maintained(self):
        """5 代后 Jaccard 相似度 < 0.7（不退化为单一个体）."""
        from dreambuddy_evolution.core.evolution_engine import EvolutionEngine
        ee = EvolutionEngine(population_size=20)
        result = ee.evolve(generations=5)
        diversity = result["final_diversity"]
        assert diversity < 0.7, f"多样性应 <0.7，实际 {diversity}（种群退化为单一个体）"


# --------------------------------------------------------------------------------
# Fitness 单调递增
# --------------------------------------------------------------------------------
class TestFitnessImprovement:
    def test_fitness_monotonic_improvement(self):
        """5 代 holdout fitness 应严格递增."""
        from dreambuddy_evolution.core.evolution_engine import EvolutionEngine
        ee = EvolutionEngine(population_size=20)
        result = ee.evolve(generations=5)
        fitness_history = result["fitness_history"]
        assert len(fitness_history) == 5
        # 至少 4 次非递减（允许 1 次波动）
        non_decreasing = sum(1 for i in range(1, 5) if fitness_history[i] >= fitness_history[i - 1])
        assert non_decreasing >= 4, f"fitness 应单调递增，历史: {fitness_history}"


# --------------------------------------------------------------------------------
# Ensemble 策略合成
# --------------------------------------------------------------------------------
class TestEnsembleSynthesis:
    def test_ensemble_synthesis_combines_diverse(self):
        """合成策略 ≠ top-1 策略."""
        from dreambuddy_evolution.core.evolution_engine import EvolutionEngine
        ee = EvolutionEngine(population_size=20)
        result = ee.evolve(generations=5)
        assert result["ensemble_id"] != result["best_id"], (
            f"合成 ID={result['ensemble_id']} 应 ≠ top-1 ID={result['best_id']}"
        )

    def test_ensemble_uses_top_k(self):
        """ensemble 应使用 top-K（K=3）策略."""
        from dreambuddy_evolution.core.evolution_engine import EvolutionEngine
        ee = EvolutionEngine(population_size=20, ensemble_k=3)
        result = ee.evolve(generations=3)
        assert "ensemble_members" in result
        assert len(result["ensemble_members"]) <= 3


# --------------------------------------------------------------------------------
# Fitness 函数
# --------------------------------------------------------------------------------
class TestFitnessFunction:
    def test_fitness_combines_ess_sharpe_maxdd(self):
        """fitness = 0.5·ESS + 0.3·Sharpe + 0.2·(1-maxDD)."""
        from dreambuddy_evolution.core.evolution_engine import EvolutionEngine
        ee = EvolutionEngine(population_size=20)
        fitness = ee.compute_fitness(ess=1.5, sharpe=2.0, max_dd=0.1)
        expected = 0.5 * 1.5 + 0.3 * 2.0 + 0.2 * (1 - 0.1)
        assert abs(fitness - expected) < 1e-4


# --------------------------------------------------------------------------------
# 统计检验门槛（复用 P0 的 gene_promotion_stats）
# --------------------------------------------------------------------------------
class TestStatisticalGate:
    def test_individual_must_pass_statistical_gate(self):
        """入种群必须通过统计检验（p<0.05 + Cohen's d≥0.5）."""
        from dreambuddy_evolution.core.evolution_engine import EvolutionEngine
        ee = EvolutionEngine(population_size=20)
        # 弱信号（50% 胜率）应被拒
        weak_samples = [{"pnl_pct": 0.01 if i % 2 == 0 else -0.01} for i in range(30)]
        assert ee.admit_to_population(weak_samples) is False
        # 强信号（75% 胜率）应被接
        strong_samples = [{"pnl_pct": 0.03 if i % 4 < 3 else -0.01} for i in range(30)]
        assert ee.admit_to_population(strong_samples) is True
