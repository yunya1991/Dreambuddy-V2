#!/usr/bin/env python3
"""test_debate_trainer.py — 算法训练层单元测试 (TDD RED→GREEN)

SPEC v1.2-rc1 §5 Layer 3: Training
- BayesianStrategyWeights: P(S wins|T) ~ Beta(α,β) 更新
- PersonaElo: Elo评分 + 动态K + draw处理 (m2)
- CBRCaseLibrary: 案例入库 + cosine检索 Top-K
- DebateTrainer: train(reflection_report) 协调三参数更新
- §5.7 冷启动退化: 0-5场纯Persona / 5-20弱增强 / 20-50正常 / 50+成熟
- FAIL-OPEN: 无数据或异常时不崩溃
"""
from __future__ import annotations
import json, os, sys, unittest
from unittest.mock import MagicMock

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)


# ── 简单 hash 编码器（测试用，替代 sentence-transformers） ────

def _hash_encode(text: str, dim: int = 384) -> list[float]:
    """简单 hash 编码器，用于测试替代 all-MiniLM-L6-v2。"""
    import hashlib
    vec = [0.0] * dim
    for i, ch in enumerate(text):
        h = int(hashlib.md5(f"{ch}_{i}".encode()).hexdigest(), 16)
        vec[h % dim] += 1.0
    # 归一化
    norm = sum(v * v for v in vec) ** 0.5
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


# ── mock 数据 ─────────────────────────────────────────────────

def _make_adjudication_result():
    """创建 mock AdjudicationResult。"""
    from adjudicator import AdjudicationResult
    return AdjudicationResult(
        topic="BTC是数字黄金",
        bull_turn_scores=[],
        bear_turn_scores=[],
        bull_total=23.0,
        bear_total=19.0,
        dimension_comparison={
            "clarity": {"bull": 4.0, "bear": 3.0},
            "fact_authenticity": {"bull": 4.0, "bear": 3.0},
            "logical_validity": {"bull": 4.0, "bear": 3.0},
        },
        winner="bull",
        rfd="正方领先",
        key_clash_points=["稀缺性vs波动性"],
        rebuttal_strength={"bull": 4, "bear": 3},
        evidence_depth={"bull": 4, "bear": 3},
        timestamp="2026-01-01T00:00:00",
    )


def _make_reflection_report():
    """创建 mock ReflectionReport。"""
    from reflector import ReflectionReport
    return ReflectionReport(
        topic="BTC是数字黄金",
        review={"key_pivot": "第2轮"},
        strategy_analysis={"evidence-heavy": {"used_by": "bull", "effect": 4}},
        persona_analysis={"bull_persona": "乐观分析师"},
        evidence_analysis={"bull_fact_score": 4.0},
        gaps={"evidence_gaps": [], "dropped_args": [], "unused_tactics": []},
        recommendations=["增加数据"],
        strategy_tags=["evidence-heavy", "definition-lock"],
        persona_suggestions={"bull": "加强类比"},
        memory_id="VM-test-001",
        timestamp="2026-01-01T00:00:00",
    )


# ── Tests ─────────────────────────────────────────────────────

class TestImport(unittest.TestCase):
    """RED: debate_trainer 模块可导入。"""

    def test_import_bayesian(self):
        from debate_trainer import BayesianStrategyWeights  # noqa: F401

    def test_import_persona_elo(self):
        from debate_trainer import PersonaElo  # noqa: F401

    def test_import_cbr_case_library(self):
        from debate_trainer import CBRCaseLibrary  # noqa: F401

    def test_import_debate_trainer(self):
        from debate_trainer import DebateTrainer  # noqa: F401


# ── BayesianStrategyWeights ──────────────────────────────────

class TestBayesianStrategyWeights(unittest.TestCase):
    """§5.2 贝叶斯策略权重更新。"""

    def test_initial_beta_uniform(self):
        """初始 Beta(1,1) 均匀分布。"""
        from debate_trainer import BayesianStrategyWeights
        bsw = BayesianStrategyWeights()
        prob = bsw.get_win_prob("evidence-heavy", "crypto")
        # Beta(1,1) → α/(α+β) = 1/2 = 0.5
        self.assertAlmostEqual(prob, 0.5)

    def test_update_on_win(self):
        """策略被使用且获胜 → α += 1。"""
        from debate_trainer import BayesianStrategyWeights
        bsw = BayesianStrategyWeights()
        bsw.update("evidence-heavy", "crypto", won=True)
        prob = bsw.get_win_prob("evidence-heavy", "crypto")
        # α=2, β=1 → 2/3 ≈ 0.667
        self.assertAlmostEqual(prob, 2/3, places=2)

    def test_update_on_loss(self):
        """策略被使用且失败 → β += 1。"""
        from debate_trainer import BayesianStrategyWeights
        bsw = BayesianStrategyWeights()
        bsw.update("evidence-heavy", "crypto", won=False)
        prob = bsw.get_win_prob("evidence-heavy", "crypto")
        # α=1, β=2 → 1/3 ≈ 0.333
        self.assertAlmostEqual(prob, 1/3, places=2)

    def test_multiple_updates(self):
        """多次更新后概率收敛。"""
        from debate_trainer import BayesianStrategyWeights
        bsw = BayesianStrategyWeights()
        # 3胜1负
        bsw.update("evidence-heavy", "crypto", won=True)
        bsw.update("evidence-heavy", "crypto", won=True)
        bsw.update("evidence-heavy", "crypto", won=True)
        bsw.update("evidence-heavy", "crypto", won=False)
        prob = bsw.get_win_prob("evidence-heavy", "crypto")
        # α=4, β=2 → 4/6 ≈ 0.667
        self.assertAlmostEqual(prob, 4/6, places=2)

    def test_different_topic_types(self):
        """不同话题类型的策略权重独立。"""
        from debate_trainer import BayesianStrategyWeights
        bsw = BayesianStrategyWeights()
        bsw.update("evidence-heavy", "crypto", won=True)
        # crypto 有更新，ai 没有
        prob_crypto = bsw.get_win_prob("evidence-heavy", "crypto")
        prob_ai = bsw.get_win_prob("evidence-heavy", "ai")
        self.assertAlmostEqual(prob_crypto, 2/3, places=2)
        self.assertAlmostEqual(prob_ai, 0.5)  # 无更新，仍为初始值

    def test_get_top_strategies(self):
        """获取胜率最高的策略排序。"""
        from debate_trainer import BayesianStrategyWeights
        bsw = BayesianStrategyWeights()
        bsw.update("evidence-heavy", "crypto", won=True)
        bsw.update("evidence-heavy", "crypto", won=True)
        bsw.update("counterplan", "crypto", won=False)
        top = bsw.get_top_strategies("crypto", top_k=2)
        self.assertIsInstance(top, list)
        self.assertLessEqual(len(top), 2)
        # evidence-heavy 胜率应高于 counterplan
        if len(top) >= 2:
            self.assertEqual(top[0][0], "evidence-heavy")


# ── PersonaElo ────────────────────────────────────────────────

class TestPersonaElo(unittest.TestCase):
    """§5.3 Persona Elo 评分 + m2 draw 处理。"""

    def test_initial_elo(self):
        """初始 Elo = 1200。"""
        from debate_trainer import PersonaElo
        elo = PersonaElo()
        self.assertEqual(elo.get_elo("乐观分析师"), 1200)

    def test_update_on_win(self):
        """胜方 Elo 增加。"""
        from debate_trainer import PersonaElo
        elo = PersonaElo()
        old_bull = elo.get_elo("乐观分析师")
        elo.update("乐观分析师", "谨慎风控师", winner="bull")
        new_bull = elo.get_elo("乐观分析师")
        self.assertGreater(new_bull, old_bull)

    def test_update_on_loss(self):
        """败方 Elo 减少。"""
        from debate_trainer import PersonaElo
        elo = PersonaElo()
        old_bear = elo.get_elo("谨慎风控师")
        elo.update("乐观分析师", "谨慎风控师", winner="bull")
        new_bear = elo.get_elo("谨慎风控师")
        self.assertLess(new_bear, old_bear)

    def test_draw_handling(self):
        """平局时双方各得 0.5 (m2)。"""
        from debate_trainer import PersonaElo
        elo = PersonaElo()
        # 初始双方 Elo 相同(1200), expected=0.5
        # draw → score=0.5, delta = K*(0.5-0.5) = 0
        elo.update("乐观分析师", "谨慎风控师", winner="draw")
        # 相同 Elo 平局 → 不变
        self.assertEqual(elo.get_elo("乐观分析师"), 1200)
        self.assertEqual(elo.get_elo("谨慎风控师"), 1200)

    def test_draw_with_different_elo(self):
        """不同 Elo 平局时，高 Elo 方略降，低 Elo 方略升。"""
        from debate_trainer import PersonaElo
        elo = PersonaElo()
        # 先让 bull 赢一场 → Elo 更高
        elo.update("乐观分析师", "谨慎风控师", winner="bull")
        bull_elo_before = elo.get_elo("乐观分析师")
        bear_elo_before = elo.get_elo("谨慎风控师")
        # 平局
        elo.update("乐观分析师", "谨慎风控师", winner="draw")
        bull_elo_after = elo.get_elo("乐观分析师")
        bear_elo_after = elo.get_elo("谨慎风控师")
        # 高 Elo 方平局略降
        self.assertLess(bull_elo_after, bull_elo_before)
        # 低 Elo 方平局略升
        self.assertGreater(bear_elo_after, bear_elo_before)

    def test_dynamic_k(self):
        """动态 K = max(16, 32 - n/10)。"""
        from debate_trainer import PersonaElo
        elo = PersonaElo()
        # 前 50 场 K=32（但实际 32-n/10 > 16 当 n<160）
        k = elo.get_k_factor("乐观分析师")
        # 初始 0 场 → K=32
        self.assertEqual(k, 32)
        # 模拟 160 场
        for _ in range(160):
            elo.update("乐观分析师", "对手", winner="bull")
        k2 = elo.get_k_factor("乐观分析师")
        # 160 场 → 32 - 160/10 = 16
        self.assertEqual(k2, 16)


# ── CBRCaseLibrary ────────────────────────────────────────────

class TestCBRCaseLibrary(unittest.TestCase):
    """§5.4 CBR 案例检索 + m3 embedding。"""

    def test_add_case(self):
        """案例入库。"""
        from debate_trainer import CBRCaseLibrary
        cbr = CBRCaseLibrary(encode_fn=_hash_encode)
        case_id = cbr.add_case(
            topic="BTC是数字黄金",
            topic_type="crypto",
            strategies_used=["evidence-heavy"],
            winner="bull",
            bull_score=23,
            bear_score=19,
            effective_dimensions=["fact_authenticity"],
            effective_strategies=["evidence-heavy"],
            adaptation_hints=["需要历史数据对比"],
        )
        self.assertIsNotNone(case_id)

    def test_retrieve_similar(self):
        """检索相似案例。"""
        from debate_trainer import CBRCaseLibrary
        cbr = CBRCaseLibrary(encode_fn=_hash_encode)
        # 入库 3 个案例
        cbr.add_case("BTC是数字黄金", "crypto",
                     ["evidence-heavy"], "bull", 23, 19,
                     ["fact_authenticity"], ["evidence-heavy"], [])
        cbr.add_case("AI将取代人类工作", "ai",
                     ["evidence-heavy"], "bear", 20, 22,
                     ["logical_validity"], ["kritik"], [])
        cbr.add_case("美股将迎来大牛市", "macro",
                     ["evidence-heavy"], "bull", 25, 18,
                     ["fact_authenticity"], ["evidence-heavy"], [])

        # 检索相似案例
        results = cbr.retrieve("BTC是数字黄金", top_k=2)
        self.assertIsInstance(results, list)
        self.assertLessEqual(len(results), 2)
        # 最相似的应是 BTC 案例
        if results:
            self.assertEqual(results[0]["topic"], "BTC是数字黄金")

    def test_cold_start_skip_retrieval(self):
        """§5.7 冷启动: <5 案例时跳过检索。"""
        from debate_trainer import CBRCaseLibrary
        cbr = CBRCaseLibrary(encode_fn=_hash_encode)
        # 空库
        results = cbr.retrieve("BTC是数字黄金", top_k=3)
        self.assertEqual(results, [])
        # 3 个案例 → 仍 <5
        cbr.add_case("BTC是数字黄金", "crypto", ["evidence-heavy"], "bull", 23, 19, [], [], [])
        cbr.add_case("AI将取代人类", "ai", ["kritik"], "bear", 20, 22, [], [], [])
        cbr.add_case("美股牛市", "macro", ["evidence-heavy"], "bull", 25, 18, [], [], [])
        results = cbr.retrieve("BTC是数字黄金", top_k=3)
        self.assertEqual(results, [])  # <5 案例 → 返回空

    def test_normal_retrieval_after_5_cases(self):
        """§5.7 正常期: >=5 案例后可检索。"""
        from debate_trainer import CBRCaseLibrary
        cbr = CBRCaseLibrary(encode_fn=_hash_encode)
        # 入库 5 个案例
        for i in range(5):
            cbr.add_case(f"BTC案例{i}", "crypto",
                         ["evidence-heavy"], "bull", 23, 19,
                         ["fact_authenticity"], ["evidence-heavy"], [])
        results = cbr.retrieve("BTC案例0", top_k=3)
        self.assertGreater(len(results), 0)
        self.assertLessEqual(len(results), 3)


# ── DebateTrainer ─────────────────────────────────────────────

class TestDebateTrainer(unittest.TestCase):
    """DebateTrainer 协调三参数更新。"""

    def test_train_updates_all(self):
        """train() 更新贝叶斯+Elo+CBR。"""
        from debate_trainer import DebateTrainer
        trainer = DebateTrainer(encode_fn=_hash_encode)
        adj = _make_adjudication_result()
        report = _make_reflection_report()
        bull_persona = "乐观分析师"
        bear_persona = "谨慎风控师"

        result = trainer.train(adj, report, bull_persona, bear_persona)

        self.assertIsInstance(result, dict)
        self.assertIn("bayesian_updated", result)
        self.assertIn("elo_updated", result)
        self.assertIn("cbr_ingested", result)
        self.assertTrue(result["bayesian_updated"])
        self.assertTrue(result["elo_updated"])
        self.assertTrue(result["cbr_ingested"])

    def test_train_bayesian_with_strategy_tags(self):
        """train 后贝叶斯权重按策略标签更新。"""
        from debate_trainer import DebateTrainer
        trainer = DebateTrainer(encode_fn=_hash_encode)
        adj = _make_adjudication_result()  # winner=bull
        report = _make_reflection_report()  # strategy_tags=["evidence-heavy", "definition-lock"]

        trainer.train(adj, report, "乐观分析师", "谨慎风控师")

        # bull 的策略应 α+=1 (赢了)
        prob = trainer.bayesian.get_win_prob("evidence-heavy", "crypto")
        self.assertGreater(prob, 0.5)  # 赢了 → >0.5

    def test_train_elo_updated(self):
        """train 后 Elo 更新。"""
        from debate_trainer import DebateTrainer
        trainer = DebateTrainer(encode_fn=_hash_encode)
        adj = _make_adjudication_result()  # winner=bull
        report = _make_reflection_report()

        old_elo = trainer.elo.get_elo("乐观分析师")
        trainer.train(adj, report, "乐观分析师", "谨慎风控师")
        new_elo = trainer.elo.get_elo("乐观分析师")
        self.assertGreater(new_elo, old_elo)  # 胜方 Elo 增加

    def test_train_cbr_ingested(self):
        """train 后案例入 CBR 库。"""
        from debate_trainer import DebateTrainer
        trainer = DebateTrainer(encode_fn=_hash_encode)
        adj = _make_adjudication_result()
        report = _make_reflection_report()

        trainer.train(adj, report, "乐观分析师", "谨慎风控师")
        # CBR 库应有 1 条案例
        self.assertGreaterEqual(trainer.cbr.case_count(), 1)


# ── 冷启动退化 (§5.7) ─────────────────────────────────────────

class TestColdStartDegradation(unittest.TestCase):
    """§5.7 冷启动退化行为。"""

    def test_cold_start_0_5_debates(self):
        """0-5场: 纯Persona+SKILL无训练增强。"""
        from debate_trainer import DebateTrainer
        trainer = DebateTrainer(encode_fn=_hash_encode)
        # 0 场
        phase = trainer.get_cold_start_phase()
        self.assertEqual(phase, "cold_start")

    def test_cold_start_5_20_debates(self):
        """5-20场: 弱增强标注低置信度。"""
        from debate_trainer import DebateTrainer
        trainer = DebateTrainer(encode_fn=_hash_encode)
        for _ in range(10):
            adj = _make_adjudication_result()
            report = _make_reflection_report()
            trainer.train(adj, report, "乐观分析师", "谨慎风控师")
        phase = trainer.get_cold_start_phase()
        self.assertEqual(phase, "weak_enhancement")

    def test_cold_start_20_50_debates(self):
        """20-50场: 正常增强。"""
        from debate_trainer import DebateTrainer
        trainer = DebateTrainer(encode_fn=_hash_encode)
        for _ in range(30):
            adj = _make_adjudication_result()
            report = _make_reflection_report()
            trainer.train(adj, report, "乐观分析师", "谨慎风控师")
        phase = trainer.get_cold_start_phase()
        self.assertEqual(phase, "normal")

    def test_cold_start_50_plus_debates(self):
        """50+场: 成熟期。"""
        from debate_trainer import DebateTrainer
        trainer = DebateTrainer(encode_fn=_hash_encode)
        for _ in range(60):
            adj = _make_adjudication_result()
            report = _make_reflection_report()
            trainer.train(adj, report, "乐观分析师", "谨慎风控师")
        phase = trainer.get_cold_start_phase()
        self.assertEqual(phase, "mature")


# ── FAIL-OPEN ─────────────────────────────────────────────────

class TestFailOpen(unittest.TestCase):
    """FAIL-OPEN: 异常时不崩溃。"""

    def test_train_with_none_args(self):
        """train 参数为 None 时不崩溃。"""
        from debate_trainer import DebateTrainer
        trainer = DebateTrainer(encode_fn=_hash_encode)
        result = trainer.train(None, None, "bull", "bear")
        self.assertIsInstance(result, dict)
        self.assertFalse(result["bayesian_updated"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
