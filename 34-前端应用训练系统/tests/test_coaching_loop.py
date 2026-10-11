"""CoachingSession 单元测试。

测试:
  1. 监控清单生成（字符串列表 + dict 列表）
  2. 监控结果记录
  3. 纠正记录
  4. 质量分计算（全通过/部分通过/无记录）
  5. 报告输出
"""
import os
import sys
import unittest

# sys.path 注入
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_CORE_DIR = os.path.join(os.path.dirname(_THIS_DIR), "core")
_34_DIR = os.path.dirname(_THIS_DIR)

for _p in [_THIS_DIR, _CORE_DIR, _34_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from coaching_loop import CoachingSession


class CoachingSessionTest(unittest.TestCase):

    def _make_context(self, **kwargs):
        """创建测试辅导上下文。"""
        defaults = {
            "case_intent": "实现登录功能",
            "case_outcome": "success",
            "acceptance_level": "full",
            "algorithm_patterns": ["recursion", "divide_conquer"],
            "call_chain": ["func_a", "func_b", "func_c"],
            "known_gaps": ["gap1"],
            "monitoring_checks": [
                "各层训练是否符合33-REA解析的算法模式",
                "DSH执行路径是否与调用链一致",
                "C层反思是否覆盖known_gaps",
                "G层图结构是否与依赖图匹配",
            ],
        }
        defaults.update(kwargs)
        return defaults

    def test_monitoring_checklist_from_strings(self):
        """monitoring_checks 为字符串列表 → 正确生成清单。"""
        ctx = self._make_context()
        session = CoachingSession(ctx)
        checklist = session.get_monitoring_checklist()

        self.assertEqual(len(checklist), 4)
        self.assertEqual(checklist[0]["check_id"], "check_1")
        self.assertEqual(checklist[0]["check_name"], "各层训练是否符合33-REA解析的算法模式")
        self.assertEqual(checklist[0]["status"], "pending")

    def test_monitoring_checklist_from_dicts(self):
        """monitoring_checks 为 dict 列表 → 正确生成清单。"""
        ctx = self._make_context(
            monitoring_checks=[
                {"check_id": "c1", "check_name": "检查1", "description": "描述1"},
                {"check_name": "检查2"},
            ]
        )
        session = CoachingSession(ctx)
        checklist = session.get_monitoring_checklist()

        self.assertEqual(len(checklist), 2)
        self.assertEqual(checklist[0]["check_id"], "c1")
        self.assertEqual(checklist[0]["description"], "描述1")
        self.assertEqual(checklist[1]["check_id"], "check_2")

    def test_record_monitoring_result(self):
        """记录监控结果 → monitoring_log 正确更新。"""
        session = CoachingSession(self._make_context())
        session.record_monitoring_result("check1", True, "通过")
        session.record_monitoring_result("check2", False, "路径不一致")

        report = session.to_report()
        self.assertEqual(len(report["monitoring_log"]), 2)
        self.assertTrue(report["monitoring_log"][0]["passed"])
        self.assertFalse(report["monitoring_log"][1]["passed"])

    def test_record_correction(self):
        """记录纠正 → corrections 列表更新。"""
        session = CoachingSession(self._make_context())
        session.record_correction("DSH", "路径遗漏", "补充 func_c")

        report = session.to_report()
        self.assertEqual(len(report["corrections"]), 1)
        self.assertEqual(report["corrections"][0]["layer"], "DSH")
        self.assertEqual(report["corrections"][0]["issue"], "路径遗漏")

    def test_quality_score_all_pass(self):
        """全部监控通过 → 质量分 100。"""
        session = CoachingSession(self._make_context())
        session.record_monitoring_result("c1", True)
        session.record_monitoring_result("c2", True)
        self.assertEqual(session.calculate_quality_score(), 100)

    def test_quality_score_partial(self):
        """部分监控通过 → 质量分按比例计算。"""
        session = CoachingSession(self._make_context())
        session.record_monitoring_result("c1", True)
        session.record_monitoring_result("c2", False)
        session.record_monitoring_result("c3", True)
        session.record_monitoring_result("c4", False)
        self.assertEqual(session.calculate_quality_score(), 50)

    def test_quality_score_no_records(self):
        """无监控记录 → 质量分 0。"""
        session = CoachingSession(self._make_context())
        self.assertEqual(session.calculate_quality_score(), 0)

    def test_to_report_structure(self):
        """to_report 输出结构正确。"""
        session = CoachingSession(self._make_context())
        session.record_monitoring_result("c1", True)
        session.record_correction("DSH", "issue", "fix")

        report = session.to_report()

        self.assertIn("quality_score", report)
        self.assertIn("correction_count", report)
        self.assertIn("monitoring_log", report)
        self.assertIn("corrections", report)
        self.assertIn("improvement", report)
        self.assertIn("coaching_context_summary", report)

        summary = report["coaching_context_summary"]
        self.assertEqual(summary["case_intent"], "实现登录功能")
        self.assertEqual(summary["algorithm_patterns_count"], 2)
        self.assertEqual(summary["call_chain_length"], 3)
        self.assertEqual(summary["known_gaps_count"], 1)

    def test_empty_context(self):
        """空辅导上下文 → 不崩溃，清单为空。"""
        session = CoachingSession({})
        self.assertEqual(session.get_monitoring_checklist(), [])
        self.assertEqual(session.calculate_quality_score(), 0)


if __name__ == "__main__":
    unittest.main()
