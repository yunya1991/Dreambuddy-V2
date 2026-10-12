"""MasterSeminarCollector 单元测试 — v0.5 P3 DSH 层训练数据采集器.

测试覆盖:
  TR-4.1  MasterSeminarCollector 类存在且实现 TrainingDataProvider 接口
  TR-4.2  get_source_name() 返回 "master_seminar"
  TR-4.3  get_quality_threshold() 返回 "A"
  TR-4.4  fetch_cases() 从 SEM_*.md 报告采集 TrainingCase
  TR-4.5  TrainingCase.intent 含 "seminar"
  TR-4.6  TrainingCase.actions (node_sequence) 长度 ≥5
  TR-4.7  layer_tags 含 "DSH"
  TR-4.8  metadata.outcome == "success"
  TR-4.9  metadata 含 seminar_id 字段
  TR-4.10 识别阵营结构 (多方/中立/空方)
  TR-4.11 FAIL-OPEN: 目录不存在返回空列表
  TR-4.12 FAIL-OPEN: 单个文件异常不影响其他
  TR-4.13 node_sequence 含研讨专用节点 (camp/debate/round/bias/conclusion)
  TR-4.14 每个报告生成多条 case (按Round或阵营拆分)
"""
import os
import sys
import tempfile
import textwrap
import unittest

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_ADAPTERS_DIR = os.path.join(os.path.dirname(_THIS_DIR), "adapters")
_34_DIR = os.path.dirname(_THIS_DIR)

for _p in [_THIS_DIR, _ADAPTERS_DIR, _34_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


class MasterSeminarCollectorTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """创建临时 master-seminar/reports/ 目录和样本报告."""
        cls._tmpdir = tempfile.mkdtemp(prefix="master_seminar_test_")
        cls._reports_dir = os.path.join(cls._tmpdir, "master-seminar", "reports")
        os.makedirs(cls._reports_dir, exist_ok=True)

        # 样本1: 完整研讨报告
        sem1 = os.path.join(cls._reports_dir, "SEM_20260429_104041.md")
        with open(sem1, "w") as f:
            f.write(textwrap.dedent('''
                # 大师研讨报告

                **研讨ID**: SEM_20260429_104041
                **触发类型**: 手动触发
                **当前Regime**: TREND_BULL

                ## 市场状态
                | 指标 | 值 |
                |:---|:---:|
                | price | 76287 |
                | trend | BULL |
                | regime | TREND_BULL |

                ## 阵营分配
                ### 多方阵营
                | 大师 | 风格 | 权重 | 核心观点 |
                |:---|:---|:---:|:---|
                | Druckenmiller | 趋势追踪 | 1.00 | 趋势是朋友 |
                | ONeil | CANSLIM | 1.00 | 突破时买入 |

                ### 中立阵营
                | 大师 | 风格 | 权重 | 核心观点 |
                |:---|:---|:---:|:---|
                | Tharp | 仓位管理 | 1.00 | 概率游戏 |
                | Livermore | 关键点 | 1.00 | 最小阻力方向 |

                ### 空方阵营
                | 大师 | 风格 | 权重 | 核心观点 |
                |:---|:---|:---:|:---|
                | PTJ | 危机Alpha | 1.00 | 风险管理第一 |
                | Dalio | 风险平价 | 1.00 | 理解债务周期 |

                ## 辩论详情
                ### Round 1: 分阵营内部讨论
                **Druckenmiller**: 趋势是你最好的朋友。在明确的趋势中，应该果断加仓。
                **ONeil**: CANSLIM法则: 成长股在突破时是最好的买入时机。
                阵营总结: 看多观点

                ### Round 2: 分阵营内部讨论
                **Tharp**: 交易是一个概率游戏。系统化的风险管理是关键。
                **Livermore**: 价格总是沿着最小阻力方向运行。
                阵营总结: 中立观点

                ### Round 3: 分阵营内部讨论
                **PTJ**: 我只在最有利的位置下重注。风险管理比赚钱更重要。
                **Dalio**: 理解债务周期和经济机器的运作。
                阵营总结: 看空观点

                ### Round 4: 交叉辩论
                **Druckenmiller**: 请问空方: 空方如何解释当前的资金流入?
                **PTJ**: 请问多方: 多方忽视的最大风险是什么?
                关键争议:
                - 趋势是你最好的朋友
                - 风险管理比赚钱更重要

                ### Round 5: 最终陈述
                **Druckenmiller**:
                - 坚守: 趋势确认后应该持有甚至加仓
                - 让步: 承认短期波动风险
                - 建议: 趋势明确时重仓

                **PTJ**:
                - 坚守: 风险管理第一
                - 让步: 承认多方有资金支撑
                - 建议: 控制仓位，设置止损

                ## 研讨结论
                ### 多空倾向
                倾向: 中性 (+0.00)
                置信度: 39%
                大师一致性: 40%

                ### 可执行建议
                1. 中立: 建议观望，等待趋势明确

                ### 多方信号
                - 趋势明确时重仓

                ### 空方信号
                - 控制仓位，设置止损

                ### 风险警告
                - 多空分歧较大，注意仓位控制
            ''').strip())

        # 样本2: 简短研讨报告
        sem2 = os.path.join(cls._reports_dir, "SEM_20260429_104453.md")
        with open(sem2, "w") as f:
            f.write(textwrap.dedent('''
                # 大师研讨报告
                **研讨ID**: SEM_20260429_104453
                **当前Regime**: RANGE

                ## 阵营分配
                ### 多方阵营
                | 大师 | 风格 | 权重 |
                |:---|:---|:---:|
                | Soros | 反身性 | 1.00 |

                ### 空方阵营
                | 大师 | 风格 | 权重 |
                |:---|:---|:---:|
                | PTJ | 危机Alpha | 1.00 |

                ## 辩论详情
                ### Round 1: 分阵营内部讨论
                **Soros**: 反身性理论表明市场可以自我强化。
                **PTJ**: 风险管理永远是第一位的。

                ## 研讨结论
                ### 多空倾向
                倾向: 中性 (+0.00)
                置信度: 45%
            ''').strip())

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    # ===== TR-4.1: 类存在且实现接口 =====
    def test_4_1_class_exists_and_implements_interface(self):
        from master_seminar_collector import MasterSeminarCollector
        from interfaces.training_data_provider import TrainingDataProvider
        collector = MasterSeminarCollector()
        self.assertIsInstance(collector, TrainingDataProvider)

    # ===== TR-4.2: get_source_name =====
    def test_4_2_source_name(self):
        from master_seminar_collector import MasterSeminarCollector
        self.assertEqual(MasterSeminarCollector().get_source_name(), "master_seminar")

    # ===== TR-4.3: get_quality_threshold =====
    def test_4_3_quality_threshold(self):
        from master_seminar_collector import MasterSeminarCollector
        self.assertEqual(MasterSeminarCollector().get_quality_threshold(), "A")

    # ===== TR-4.4: fetch_cases 采集 TrainingCase =====
    def test_4_4_fetch_cases_returns_training_cases(self):
        from master_seminar_collector import MasterSeminarCollector
        collector = MasterSeminarCollector()
        collector.reports_root = self._reports_dir
        cases = collector.fetch_cases(limit=100)
        self.assertGreater(len(cases), 0)
        from interfaces.training_data_provider import TrainingCase
        for c in cases:
            self.assertIsInstance(c, TrainingCase)

    # ===== TR-4.5: intent 含 seminar =====
    def test_4_5_intent_contains_seminar(self):
        from master_seminar_collector import MasterSeminarCollector
        c = MasterSeminarCollector()
        c.reports_root = self._reports_dir
        cases = c.fetch_cases(limit=100)
        for case in cases:
            self.assertIn("seminar", case.intent.lower())

    # ===== TR-4.6: node_sequence ≥5 =====
    def test_4_6_node_sequence_min_length(self):
        from master_seminar_collector import MasterSeminarCollector
        c = MasterSeminarCollector()
        c.reports_root = self._reports_dir
        cases = c.fetch_cases(limit=100)
        for case in cases:
            self.assertGreaterEqual(len(case.actions), 5,
                                    f"intent='{case.intent}' len={len(case.actions)}")

    # ===== TR-4.7: layer_tags 含 DSH =====
    def test_4_7_layer_tags_contains_dsh(self):
        from master_seminar_collector import MasterSeminarCollector
        c = MasterSeminarCollector()
        c.reports_root = self._reports_dir
        cases = c.fetch_cases(limit=100)
        for case in cases:
            self.assertIn("DSH", case.layer_tags)

    # ===== TR-4.8: outcome == success =====
    def test_4_8_outcome_is_success(self):
        from master_seminar_collector import MasterSeminarCollector
        c = MasterSeminarCollector()
        c.reports_root = self._reports_dir
        cases = c.fetch_cases(limit=100)
        for case in cases:
            self.assertEqual(case.metadata.get("outcome"), "success")

    # ===== TR-4.9: metadata 含 seminar_id =====
    def test_4_9_metadata_contains_seminar_id(self):
        from master_seminar_collector import MasterSeminarCollector
        c = MasterSeminarCollector()
        c.reports_root = self._reports_dir
        cases = c.fetch_cases(limit=100)
        for case in cases:
            self.assertIn("seminar_id", case.metadata)
            self.assertTrue(case.metadata["seminar_id"])

    # ===== TR-4.10: 识别阵营结构 =====
    def test_4_10_recognizes_camp_structure(self):
        from master_seminar_collector import MasterSeminarCollector
        c = MasterSeminarCollector()
        c.reports_root = self._reports_dir
        cases = c.fetch_cases(limit=100)
        all_nodes = []
        for case in cases:
            all_nodes.extend(case.actions)
        node_str = " ".join(all_nodes).lower()
        camp_kw = ["bull", "neutral", "bear", "多方", "中立", "空方"]
        found = sum(1 for kw in camp_kw if kw in node_str)
        self.assertGreaterEqual(found, 2, f"应识别≥2种阵营, found {found}")

    # ===== TR-4.11: FAIL-OPEN 目录不存在 =====
    def test_4_11_fail_open_dir_not_exist(self):
        from master_seminar_collector import MasterSeminarCollector
        c = MasterSeminarCollector()
        c.reports_root = "/nonexistent/seminars"
        self.assertEqual(c.fetch_cases(limit=100), [])

    # ===== TR-4.12: FAIL-OPEN 单个文件异常 =====
    def test_4_12_fail_open_single_file_error(self):
        from master_seminar_collector import MasterSeminarCollector
        bad = os.path.join(self._reports_dir, "SEM_bad.md")
        with open(bad, "w") as f:
            f.write("\x00\x01\x02binary\xff\xfe")
        c = MasterSeminarCollector()
        c.reports_root = self._reports_dir
        cases = c.fetch_cases(limit=100)
        self.assertGreater(len(cases), 0)

    # ===== TR-4.13: node_sequence 含研讨专用节点 =====
    def test_4_13_node_sequence_contains_seminar_nodes(self):
        from master_seminar_collector import MasterSeminarCollector
        c = MasterSeminarCollector()
        c.reports_root = self._reports_dir
        cases = c.fetch_cases(limit=100)
        seminar_kw = ["camp", "debate", "round", "bias", "conclusion",
                      "阵营", "辩论", "倾向", "结论", "master"]
        has = False
        for case in cases:
            ns = " ".join(case.actions).lower()
            if any(kw in ns for kw in seminar_kw):
                has = True
                break
        self.assertTrue(has, "应含研讨专用节点关键词")

    # ===== TR-4.14: 每个报告生成多条 case =====
    def test_4_14_multiple_cases_per_report(self):
        from master_seminar_collector import MasterSeminarCollector
        c = MasterSeminarCollector()
        c.reports_root = self._reports_dir
        cases = c.fetch_cases(limit=100)
        # 样本1有5个Round → 应拆出≥2条 case
        self.assertGreaterEqual(len(cases), 2,
                                f"应≥2条case, got {len(cases)}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
