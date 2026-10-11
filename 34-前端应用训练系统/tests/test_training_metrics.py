"""P4 评估与反馈闭环单元测试。

测试:
  1. TrainingMetrics: 辅导质量分+纠正次数+提升幅度
  2. PatternMiner: 跨案例模式挖掘
  3. FeedbackLoop: 阈值自动调整
"""
import os
import sys
import unittest

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_CORE_DIR = os.path.join(os.path.dirname(_THIS_DIR), "core")
_34_DIR = os.path.dirname(_THIS_DIR)

for _p in [_THIS_DIR, _CORE_DIR, _34_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


class TrainingMetricsTest(unittest.TestCase):

    def test_quality_score_calculation(self):
        """辅导质量分: 训练结果与33-REA解析的一致度 (0-100)。"""
        from training_metrics import TrainingMetrics

        metrics = TrainingMetrics()

        # 33-REA 解析结果
        rea_patterns = ["conditional_branch", "iteration", "recursion"]
        rea_call_chain = ["func_a", "func_b", "func_c"]

        # 前端训练输出
        trained_patterns = ["conditional_branch", "iteration"]  # 缺 recursion
        trained_call_chain = ["func_a", "func_b"]  # 缺 func_c

        score = metrics.calculate_quality_score(
            rea_patterns=rea_patterns,
            trained_patterns=trained_patterns,
            rea_call_chain=rea_call_chain,
            trained_call_chain=trained_call_chain,
        )

        # patterns 一致度 = 2/3, call_chain 一致度 = 2/3
        # 综合分 = (66.67 + 66.67) / 2 = 66.67
        self.assertGreater(score, 60)
        self.assertLess(score, 70)

    def test_perfect_score(self):
        """完全一致时质量分=100。"""
        from training_metrics import TrainingMetrics

        metrics = TrainingMetrics()
        patterns = ["recursion", "greedy"]
        chain = ["f1", "f2"]

        score = metrics.calculate_quality_score(
            rea_patterns=patterns,
            trained_patterns=patterns,
            rea_call_chain=chain,
            trained_call_chain=chain,
        )
        self.assertEqual(score, 100.0)

    def test_zero_score(self):
        """完全不一致时质量分=0。"""
        from training_metrics import TrainingMetrics

        metrics = TrainingMetrics()
        score = metrics.calculate_quality_score(
            rea_patterns=["a"],
            trained_patterns=["b"],
            rea_call_chain=["x"],
            trained_call_chain=["y"],
        )
        self.assertEqual(score, 0.0)

    def test_correction_count(self):
        """纠正次数统计。"""
        from training_metrics import TrainingMetrics

        metrics = TrainingMetrics()
        metrics.record_correction("pattern_mismatch", "DSH层训练缺少递归模式")
        metrics.record_correction("path_divergence", "执行路径偏离调用链")

        self.assertEqual(metrics.get_correction_count(), 2)
        corrections = metrics.get_corrections()
        self.assertEqual(len(corrections), 2)
        self.assertEqual(corrections[0]["type"], "pattern_mismatch")

    def test_improvement_delta(self):
        """训练成果提升: 前后质量对比。"""
        from training_metrics import TrainingMetrics

        metrics = TrainingMetrics()
        metrics.set_before_score(40.0)
        metrics.set_after_score(75.0)

        delta = metrics.get_improvement_delta()
        self.assertEqual(delta, 35.0)
        self.assertTrue(metrics.is_improved())


class PatternMinerTest(unittest.TestCase):

    def test_mine_common_patterns(self):
        """跨案例模式挖掘: 从多案例中找共同模式。"""
        from training_metrics import PatternMiner

        miner = PatternMiner()
        cases = [
            {"patterns": ["recursion", "greedy"], "source": "cognitive"},
            {"patterns": ["recursion", "iteration"], "source": "cognitive"},
            {"patterns": ["recursion", "divide_conquer"], "source": "skill"},
        ]

        common = miner.mine_common_patterns(cases)
        # recursion 出现在 3/3 案例 → 频率最高
        self.assertIn("recursion", common)
        self.assertEqual(common["recursion"], 3)

    def test_mine_top_patterns(self):
        """获取 Top-N 频繁模式。"""
        from training_metrics import PatternMiner

        miner = PatternMiner()
        cases = [
            {"patterns": ["a", "b", "c"]},
            {"patterns": ["a", "b"]},
            {"patterns": ["a", "c"]},
        ]

        top = miner.mine_top_patterns(cases, top_n=2)
        self.assertEqual(len(top), 2)
        self.assertEqual(top[0][0], "a")  # 3次
        self.assertEqual(top[1][0], "b")  # 2次


class FeedbackLoopTest(unittest.TestCase):

    def test_threshold_adjustment(self):
        """训练质量反馈到CaseIngestGate阈值调整。"""
        from training_metrics import FeedbackLoop

        loop = FeedbackLoop(
            initial_novelty_threshold=0.6,
            initial_significance_threshold=0.05,
        )

        # 高质量训练 → 可适当放宽阈值（更多案例入库）
        loop.record_training_quality(85.0)
        loop.record_training_quality(90.0)

        adjusted = loop.get_adjusted_thresholds()
        # 连续高质量 → novelty阈值可放宽（降低，更多案例入库）
        self.assertLessEqual(adjusted["novelty_threshold"], 0.6)

    def test_threshold_tighten_on_low_quality(self):
        """低质量训练 → 收紧阈值（更严格筛选）。"""
        from training_metrics import FeedbackLoop

        loop = FeedbackLoop(
            initial_novelty_threshold=0.6,
            initial_significance_threshold=0.05,
        )

        loop.record_training_quality(30.0)
        loop.record_training_quality(25.0)

        adjusted = loop.get_adjusted_thresholds()
        # 连续低质量 → 阈值收紧（提高，更严格筛选）
        self.assertGreaterEqual(adjusted["novelty_threshold"], 0.6)

    def test_quality_history(self):
        """训练质量历史记录。"""
        from training_metrics import FeedbackLoop

        loop = FeedbackLoop()
        loop.record_training_quality(50.0)
        loop.record_training_quality(70.0)
        loop.record_training_quality(80.0)

        history = loop.get_quality_history()
        self.assertEqual(len(history), 3)
        self.assertEqual(history[0], 50.0)
        self.assertEqual(history[-1], 80.0)


class FeedbackLoopP2TuningTest(unittest.TestCase):
    """SPEC v0.5 §5.3 P2.4: FeedbackLoop 扩展 — 调优 microBatch + capacity + λ。

    高质量训练连续出现 → 放宽（更大微批 + 更大容量 + 更高λ）
    低质量训练连续出现 → 收紧（更小微批 + 更小容量 + 更低λ）
    """

    def test_tuning_high_quality_relax(self):
        """高质量训练 → 放宽 microBatch + capacity + λ。"""
        from training_metrics import FeedbackLoop

        loop = FeedbackLoop()
        loop.record_training_quality(85.0)
        loop.record_training_quality(90.0)

        tuning = loop.get_tuning_recommendations(
            layer="S",
            current_micro_batch=5,
            current_capacity=200,
            current_lambda=0.95,
        )

        # 高质量 → 放宽：微批增大、容量增大、λ增大（保留更多历史）
        self.assertGreaterEqual(tuning["micro_batch"], 5)
        self.assertGreaterEqual(tuning["capacity"], 200)
        self.assertGreaterEqual(tuning["lambda"], 0.95)

    def test_tuning_low_quality_tighten(self):
        """低质量训练 → 收紧 microBatch + capacity + λ。"""
        from training_metrics import FeedbackLoop

        loop = FeedbackLoop()
        loop.record_training_quality(25.0)
        loop.record_training_quality(30.0)

        tuning = loop.get_tuning_recommendations(
            layer="S",
            current_micro_batch=5,
            current_capacity=200,
            current_lambda=0.95,
        )

        # 低质量 → 收紧：微批减小、容量减小、λ减小（快速遗忘旧模式）
        self.assertLessEqual(tuning["micro_batch"], 5)
        self.assertLessEqual(tuning["capacity"], 200)
        self.assertLessEqual(tuning["lambda"], 0.95)

    def test_tuning_medium_quality_keep(self):
        """中等质量训练 → 保持当前值不变。"""
        from training_metrics import FeedbackLoop

        loop = FeedbackLoop()
        loop.record_training_quality(55.0)
        loop.record_training_quality(60.0)

        tuning = loop.get_tuning_recommendations(
            layer="DSH",
            current_micro_batch=10,
            current_capacity=300,
            current_lambda=0.95,
        )

        self.assertEqual(tuning["micro_batch"], 10)
        self.assertEqual(tuning["capacity"], 300)
        self.assertEqual(tuning["lambda"], 0.95)

    def test_tuning_insufficient_history_keep_current(self):
        """质量历史不足2次时 → 保持当前值不变。"""
        from training_metrics import FeedbackLoop

        loop = FeedbackLoop()
        loop.record_training_quality(90.0)  # 只有1条

        tuning = loop.get_tuning_recommendations(
            layer="G",
            current_micro_batch=15,
            current_capacity=500,
            current_lambda=0.99,
        )

        self.assertEqual(tuning["micro_batch"], 15)
        self.assertEqual(tuning["capacity"], 500)
        self.assertEqual(tuning["lambda"], 0.99)

    def test_tuning_respects_bounds(self):
        """调优值不超出上下限边界。"""
        from training_metrics import FeedbackLoop

        loop = FeedbackLoop()
        # 连续极高质量 → 放宽但不超上限
        for _ in range(10):
            loop.record_training_quality(95.0)

        tuning = loop.get_tuning_recommendations(
            layer="S",
            current_micro_batch=5,
            current_capacity=200,
            current_lambda=0.95,
        )

        # 上限约束
        self.assertLessEqual(tuning["micro_batch"], 20)
        self.assertLessEqual(tuning["capacity"], 1000)
        self.assertLessEqual(tuning["lambda"], 0.99)

        # 连续极低质量 → 收紧但不超下限
        loop2 = FeedbackLoop()
        for _ in range(10):
            loop2.record_training_quality(10.0)

        tuning2 = loop2.get_tuning_recommendations(
            layer="S",
            current_micro_batch=5,
            current_capacity=200,
            current_lambda=0.95,
        )

        # 下限约束
        self.assertGreaterEqual(tuning2["micro_batch"], 2)
        self.assertGreaterEqual(tuning2["capacity"], 50)
        self.assertGreaterEqual(tuning2["lambda"], 0.80)


if __name__ == "__main__":
    unittest.main()
