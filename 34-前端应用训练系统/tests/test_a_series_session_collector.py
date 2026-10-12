"""ASeriesSessionCollector 单元测试 — v0.5 P0 DSH 层训练数据采集器.

测试覆盖:
  TR-1.1  ASeriesSessionCollector 类存在且实现 TrainingDataProvider 接口
  TR-1.2  get_source_name() 返回 "a_series_session"
  TR-1.3  get_quality_threshold() 返回 "B"
  TR-1.4  fetch_cases() 从 6-TRADING/sessions/ 采集 TrainingCase
  TR-1.5  TrainingCase.intent 含 A 阶段标识 (a0-a9 或 oneirology)
  TR-1.6  TrainingCase.actions (node_sequence) 长度 ≥5 (哲学链)
  TR-1.7  layer_tags 含 "DSH"
  TR-1.8  metadata.outcome == "success" (session 已完成)
  TR-1.9  metadata 含 session_id 字段
  TR-1.10 采集器识别多种 session 类型 (SCREEN1/SCREEN2/SCREEN3/ONEIROLOGY)
  TR-1.11 FAIL-OPEN: sessions 目录不存在返回空列表
  TR-1.12 FAIL-OPEN: 单个 session 解析异常不影响其他 session
  TR-1.13 node_sequence 含矛盾分析节点 (identify_contradict/resolution/emit_bias_flag)
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


class ASeriesSessionCollectorTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """创建临时 6-TRADING/sessions 目录结构 + 样本 session md 文件."""
        cls._tmpdir = tempfile.mkdtemp(prefix="a_series_session_test_")

        # 构造 sessions/ 目录
        cls._sessions_dir = os.path.join(cls._tmpdir, "6-TRADING", "sessions")
        os.makedirs(cls._sessions_dir, exist_ok=True)

        # 样本1: A1 矛盾分析 session (BTC-SCREEN2 风格)
        session1_dir = os.path.join(cls._sessions_dir, "20260603-BTC-SCREEN2", "team-a", "screen2")
        os.makedirs(session1_dir, exist_ok=True)
        a1_file = os.path.join(session1_dir, "a1-contradiction.md")
        with open(a1_file, "w") as f:
            f.write(textwrap.dedent('''
                # A1 日线矛盾分析 | 2026-06-03 | BTC-SCREEN2

                ## 综合矛盾评分: 5.25/10

                ### C1: Screen1 SHORT vs 极度恐惧反向信号 (6/10)
                - Screen1 维持 SHORT (score 48)，但 F&G=28（极度恐惧）
                - 历史常视极度恐惧为买入机会
                - **分辨率**: SHORT 维持但警惕空头拥挤

                ### C2: ETF 大规模流出 vs 停火反弹 (7/10)
                - ETF 10日净流出 -$2.2B
                - 美伊停火引发 BTC 反弹
                - **分辨率**: ETF 流出反映机构减仓

                ## 偏差标志
                - `short_squeeze_risk_elevated`
                - `ceasefire_relief_rally_possible`
            ''').strip())

        # 样本2: A2 第一性原理 session
        session2_dir = os.path.join(cls._sessions_dir, "20260526-BTC-SCREEN1", "team-a", "screen1")
        os.makedirs(session2_dir, exist_ok=True)
        a2_file = os.path.join(session2_dir, "a2-first-principles.md")
        with open(a2_file, "w") as f:
            f.write(textwrap.dedent('''
                # A2 第一性原理分析 | 2026-05-26 | BTC-SCREEN1

                ## 阻力来源分解
                | 阻力类型 | 量化值 |
                | 成本摩擦 | 25 bps |
                | 流动性摩擦 | 高 |

                ## 趋势阶段判断
                - 当前阶段: 加速期
                - 反向阻力: 不足
                - **结论**: 趋势延续
            ''').strip())

        # 样本3: 做梦部 session
        session3_dir = os.path.join(cls._sessions_dir, "20260712-YIJING-ONEIROLOGY")
        os.makedirs(session3_dir, exist_ok=True)
        dream_file = os.path.join(session3_dir, "dream_journal.md")
        with open(dream_file, "w") as f:
            f.write(textwrap.dedent('''
                # 梦境日志 2026-07-12
                ## 梦境一：坤为地的强迫性重复
                > 我梦见自己站在广袤的土地上...
                **解析**: 凝缩机制触发
            ''').strip())

    def test_1_1_class_exists_and_implements_interface(self):
        """TR-1.1: 类存在且实现 TrainingDataProvider 接口."""
        from a_series_session_collector import ASeriesSessionCollector
        from interfaces.training_data_provider import TrainingDataProvider
        collector = ASeriesSessionCollector()
        self.assertIsInstance(collector, TrainingDataProvider)

    def test_1_2_source_name(self):
        """TR-1.2: get_source_name() 返回 'a_series_session'."""
        from a_series_session_collector import ASeriesSessionCollector
        collector = ASeriesSessionCollector()
        self.assertEqual(collector.get_source_name(), "a_series_session")

    def test_1_3_quality_threshold(self):
        """TR-1.3: get_quality_threshold() 返回 'B'."""
        from a_series_session_collector import ASeriesSessionCollector
        collector = ASeriesSessionCollector()
        self.assertEqual(collector.get_quality_threshold(), "B")

    def test_1_4_fetch_cases_returns_training_cases(self):
        """TR-1.4: fetch_cases() 从 6-TRADING/sessions/ 采集 TrainingCase."""
        from a_series_session_collector import ASeriesSessionCollector
        collector = ASeriesSessionCollector()
        collector.sessions_root = self._sessions_dir  # 注入测试路径
        cases = collector.fetch_cases(limit=100)
        self.assertGreater(len(cases), 0, "应至少采集到 1 条 case")
        from interfaces.training_data_provider import TrainingCase
        for c in cases:
            self.assertIsInstance(c, TrainingCase)

    def test_1_5_intent_contains_a_phase(self):
        """TR-1.5: intent 含 A 阶段标识 (a0-a9 或 oneirology)."""
        from a_series_session_collector import ASeriesSessionCollector
        collector = ASeriesSessionCollector()
        collector.sessions_root = self._sessions_dir
        cases = collector.fetch_cases(limit=100)
        self.assertGreater(len(cases), 0)
        phase_keywords = ["a0", "a1", "a2", "a3", "a4", "a5", "a6", "a7", "a8", "a9", "oneirology"]
        for c in cases:
            intent_lower = c.intent.lower()
            self.assertTrue(
                any(kw in intent_lower for kw in phase_keywords),
                f"intent '{c.intent}' 应含 A 阶段标识"
            )

    def test_1_6_node_sequence_min_length(self):
        """TR-1.6: node_sequence 长度 ≥5 (哲学决策链)."""
        from a_series_session_collector import ASeriesSessionCollector
        collector = ASeriesSessionCollector()
        collector.sessions_root = self._sessions_dir
        cases = collector.fetch_cases(limit=100)
        self.assertGreater(len(cases), 0)
        for c in cases:
            self.assertGreaterEqual(
                len(c.actions), 5,
                f"intent='{c.intent}' node_sequence 长度 {len(c.actions)} < 5"
            )

    def test_1_7_layer_tags_contains_dsh(self):
        """TR-1.7: layer_tags 含 'DSH'."""
        from a_series_session_collector import ASeriesSessionCollector
        collector = ASeriesSessionCollector()
        collector.sessions_root = self._sessions_dir
        cases = collector.fetch_cases(limit=100)
        for c in cases:
            self.assertIn("DSH", c.layer_tags)

    def test_1_8_outcome_is_success(self):
        """TR-1.8: metadata.outcome == 'success' (session 已完成)."""
        from a_series_session_collector import ASeriesSessionCollector
        collector = ASeriesSessionCollector()
        collector.sessions_root = self._sessions_dir
        cases = collector.fetch_cases(limit=100)
        for c in cases:
            self.assertEqual(c.metadata.get("outcome"), "success")

    def test_1_9_metadata_contains_session_id(self):
        """TR-1.9: metadata 含 session_id 字段."""
        from a_series_session_collector import ASeriesSessionCollector
        collector = ASeriesSessionCollector()
        collector.sessions_root = self._sessions_dir
        cases = collector.fetch_cases(limit=100)
        for c in cases:
            self.assertIn("session_id", c.metadata)
            self.assertTrue(c.metadata["session_id"])

    def test_1_10_recognizes_multiple_session_types(self):
        """TR-1.10: 识别多种 session 类型 (SCREEN1/SCREEN2/ONEIROLOGY)."""
        from a_series_session_collector import ASeriesSessionCollector
        collector = ASeriesSessionCollector()
        collector.sessions_root = self._sessions_dir
        cases = collector.fetch_cases(limit=100)
        session_ids = {c.metadata.get("session_id", "") for c in cases}
        # 至少识别 2 种不同的 session
        self.assertGreaterEqual(
            len(session_ids), 2,
            f"应识别 ≥2 种 session, 实际: {session_ids}"
        )

    def test_1_11_fail_open_when_dir_not_exist(self):
        """TR-1.11: FAIL-OPEN: sessions 目录不存在返回空列表."""
        from a_series_session_collector import ASeriesSessionCollector
        collector = ASeriesSessionCollector()
        collector.sessions_root = "/nonexistent/sessions/path"
        cases = collector.fetch_cases(limit=100)
        self.assertEqual(cases, [])

    def test_1_12_fail_open_on_single_session_error(self):
        """TR-1.12: FAIL-OPEN: 单个 session 解析异常不影响其他 session."""
        from a_series_session_collector import ASeriesSessionCollector
        # 在测试目录下加一个损坏的 session
        bad_dir = os.path.join(self._sessions_dir, "20260101-BAD-SESSION", "team-a")
        os.makedirs(bad_dir, exist_ok=True)
        bad_file = os.path.join(bad_dir, "a1-contradiction.md")
        with open(bad_file, "w") as f:
            f.write("\x00\x01\x02binary garbage")  # 二进制乱码

        collector = ASeriesSessionCollector()
        collector.sessions_root = self._sessions_dir
        cases = collector.fetch_cases(limit=100)
        # 应跳过损坏文件，仍返回其他正常 session 的 cases
        self.assertGreater(len(cases), 0)

    def test_1_13_node_sequence_contains_decision_nodes(self):
        """TR-1.13: A1 session 的 node_sequence 含决策节点 (identify/resolution/emit_bias)."""
        from a_series_session_collector import ASeriesSessionCollector
        collector = ASeriesSessionCollector()
        collector.sessions_root = self._sessions_dir
        cases = collector.fetch_cases(limit=100)
        # 至少有一条 case 的 node_sequence 含决策节点关键词
        decision_keywords = ["identify", "resolution", "emit_bias", "contradict", "principle"]
        has_decision_node = False
        for c in cases:
            node_str = " ".join(c.actions).lower()
            if any(kw in node_str for kw in decision_keywords):
                has_decision_node = True
                break
        self.assertTrue(has_decision_node, "至少一条 case 应含决策节点关键词")


if __name__ == "__main__":
    unittest.main(verbosity=2)
