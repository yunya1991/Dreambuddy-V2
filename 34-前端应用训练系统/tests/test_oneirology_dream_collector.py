"""OneirologyDreamCollector 单元测试 — v0.5 P2 DSH 层训练数据采集器.

测试覆盖:
  TR-3.1  OneirologyDreamCollector 类存在且实现 TrainingDataProvider 接口
  TR-3.2  get_source_name() 返回 "oneirology_dream"
  TR-3.3  get_quality_threshold() 返回 "S" (梦境洞察=最高置信度)
  TR-3.4  fetch_cases() 从梦境日志文件采集 TrainingCase
  TR-3.5  TrainingCase.intent 含 "oneirology" 或 "dream"
  TR-3.6  TrainingCase.actions (node_sequence) 长度 ≥5
  TR-3.7  layer_tags 含 "DSH"
  TR-3.8  metadata.outcome == "success"
  TR-3.9  metadata 含 dream_theme 字段
  TR-3.10 识别弗洛伊德5大机制 (凝缩/移置/象征/二次修正/投射)
  TR-3.11 FAIL-OPEN: 目录不存在返回空列表
  TR-3.12 FAIL-OPEN: 单个文件解析异常不影响其他
  TR-3.13 node_sequence 含梦境专用节点 (freud/trauma/dream_theme)
  TR-3.14 每个梦境日志可生成多条 case (按梦境拆分)
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


class OneirologyDreamCollectorTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """创建临时梦境日志目录和样本文件."""
        cls._tmpdir = tempfile.mkdtemp(prefix="oneirology_dream_test_")
        cls._sessions_dir = os.path.join(cls._tmpdir, "6-TRADING", "sessions")
        os.makedirs(cls._sessions_dir, exist_ok=True)

        # 样本1: 完整梦境日志 (含5大机制 + 创伤信号 + 主题)
        dream1 = os.path.join(cls._sessions_dir, "dream_brainstorm_daily_20260415.md")
        with open(dream1, "w") as f:
            f.write(textwrap.dedent('''
                # 做梦部日报 — 2026-04-15

                ## 梦境1: 追逐逃跑梦
                - dream_theme: 逃避决策压力
                - freud_mechanism_凝缩: 多个交易品种合并为一个追逐者
                - freud_mechanism_移置: 对止损的恐惧转移到追逐者身上
                - freud_mechanism_象征: 隧道象征限价单通道
                - freud_mechanism_二次修正: 醒后解释为"只是压力梦"
                - freud_mechanism_投射: 将自己的犹豫投射到市场
                - detect_trauma_signal: 连续3次止损后的回避行为
                - dream_analysis_completed: 追逐者代表止损执行恐惧

                ## 梦境2: 悬浮飞行梦
                - dream_theme: 控制力幻觉
                - freud_mechanism_凝缩: 杠杆和仓位合二为一
                - freud_mechanism_移置: 对亏损的焦虑转为飞行失控感
                - freud_mechanism_象征: 高度象征价格水平
                - freud_mechanism_二次修正: 解释为"自由的感觉"
                - freud_mechanism_投射: 将贪婪投射为上升气流
                - detect_trauma_signal: 无
                - dream_analysis_completed: 飞行梦反映过度自信

                ## 梦境3: 迷宫寻找出口梦
                - dream_theme: 决策路径混乱
                - freud_mechanism_凝缩: 多个信号源合并为墙壁
                - freud_mechanism_移置: 对选择错误的恐惧转为迷路焦虑
                - freud_mechanism_象征: 出口象征确定性信号
                - freud_mechanism_二次修正: 醒后觉得"很简单"
                - freud_mechanism_投射: 将自己的犹豫投射为迷宫结构
                - detect_trauma_signal: 策略频繁切换的历史
                - dream_analysis_completed: 迷宫代表策略选择困难
            ''').strip())

        # 样本2: 简短梦境日志
        dream2 = os.path.join(cls._sessions_dir, "dream_brainstorm_daily_20260416.md")
        with open(dream2, "w") as f:
            f.write(textwrap.dedent('''
                # 做梦部日报 — 2026-04-16

                ## 梦境1: 水下憋气梦
                - dream_theme: 窒息感=持仓过重
                - freud_mechanism_凝缩: 水压=仓位压力
                - freud_mechanism_移置: 对爆仓的恐惧转为憋气
                - freud_mechanism_象征: 水面=安全止损位
                - freud_mechanism_二次修正: 解释为"游泳练习"
                - freud_mechanism_投射: 将风控缺失投射为水流
                - detect_trauma_signal: 历史爆仓创伤
                - dream_analysis_completed: 反映仓位过重焦虑
            ''').strip())

        # 样本3: 非梦境文件 (不应被采集)
        nondream = os.path.join(cls._sessions_dir, "weekly-direction-20260415.md")
        with open(nondream, "w") as f:
            f.write("# 周度方向报告\n这不是梦境日志。")

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    # ===== TR-3.1: 类存在且实现接口 =====
    def test_3_1_class_exists_and_implements_interface(self):
        """TR-3.1: OneirologyDreamCollector 应存在且实现 TrainingDataProvider."""
        from oneirology_dream_collector import OneirologyDreamCollector
        from interfaces.training_data_provider import TrainingDataProvider
        collector = OneirologyDreamCollector()
        self.assertIsInstance(collector, TrainingDataProvider)

    # ===== TR-3.2: get_source_name =====
    def test_3_2_source_name(self):
        """TR-3.2: get_source_name() 返回 'oneirology_dream'."""
        from oneirology_dream_collector import OneirologyDreamCollector
        collector = OneirologyDreamCollector()
        self.assertEqual(collector.get_source_name(), "oneirology_dream")

    # ===== TR-3.3: get_quality_threshold =====
    def test_3_3_quality_threshold(self):
        """TR-3.3: get_quality_threshold() 返回 'S'."""
        from oneirology_dream_collector import OneirologyDreamCollector
        collector = OneirologyDreamCollector()
        self.assertEqual(collector.get_quality_threshold(), "S")

    # ===== TR-3.4: fetch_cases 采集 TrainingCase =====
    def test_3_4_fetch_cases_returns_training_cases(self):
        """TR-3.4: fetch_cases() 从梦境日志采集 TrainingCase."""
        from oneirology_dream_collector import OneirologyDreamCollector
        collector = OneirologyDreamCollector()
        collector.sessions_root = self._sessions_dir
        cases = collector.fetch_cases(limit=100)
        self.assertGreater(len(cases), 0)
        from interfaces.training_data_provider import TrainingCase
        for c in cases:
            self.assertIsInstance(c, TrainingCase)

    # ===== TR-3.5: intent 含 dream 标识 =====
    def test_3_5_intent_contains_dream(self):
        """TR-3.5: intent 含 'oneirology' 或 'dream'."""
        from oneirology_dream_collector import OneirologyDreamCollector
        collector = OneirologyDreamCollector()
        collector.sessions_root = self._sessions_dir
        cases = collector.fetch_cases(limit=100)
        for c in cases:
            il = c.intent.lower()
            self.assertTrue("dream" in il or "oneirology" in il,
                            f"intent '{c.intent}' 应含 dream/oneirology")

    # ===== TR-3.6: node_sequence 长度 ≥5 =====
    def test_3_6_node_sequence_min_length(self):
        """TR-3.6: node_sequence 长度 ≥5."""
        from oneirology_dream_collector import OneirologyDreamCollector
        collector = OneirologyDreamCollector()
        collector.sessions_root = self._sessions_dir
        cases = collector.fetch_cases(limit=100)
        for c in cases:
            self.assertGreaterEqual(len(c.actions), 5,
                                   f"intent='{c.intent}' len={len(c.actions)} < 5")

    # ===== TR-3.7: layer_tags 含 DSH =====
    def test_3_7_layer_tags_contains_dsh(self):
        """TR-3.7: layer_tags 含 'DSH'."""
        from oneirology_dream_collector import OneirologyDreamCollector
        collector = OneirologyDreamCollector()
        collector.sessions_root = self._sessions_dir
        cases = collector.fetch_cases(limit=100)
        for c in cases:
            self.assertIn("DSH", c.layer_tags)

    # ===== TR-3.8: outcome == success =====
    def test_3_8_outcome_is_success(self):
        """TR-3.8: metadata.outcome == 'success'."""
        from oneirology_dream_collector import OneirologyDreamCollector
        collector = OneirologyDreamCollector()
        collector.sessions_root = self._sessions_dir
        cases = collector.fetch_cases(limit=100)
        for c in cases:
            self.assertEqual(c.metadata.get("outcome"), "success")

    # ===== TR-3.9: metadata 含 dream_theme =====
    def test_3_9_metadata_contains_dream_theme(self):
        """TR-3.9: metadata 含 dream_theme 字段."""
        from oneirology_dream_collector import OneirologyDreamCollector
        collector = OneirologyDreamCollector()
        collector.sessions_root = self._sessions_dir
        cases = collector.fetch_cases(limit=100)
        for c in cases:
            self.assertIn("dream_theme", c.metadata)
            self.assertTrue(c.metadata["dream_theme"])

    # ===== TR-3.10: 识别弗洛伊德5大机制 =====
    def test_3_10_recognizes_freud_mechanisms(self):
        """TR-3.10: 识别弗洛伊德5大机制 (凝缩/移置/象征/二次修正/投射)."""
        from oneirology_dream_collector import OneirologyDreamCollector
        collector = OneirologyDreamCollector()
        collector.sessions_root = self._sessions_dir
        cases = collector.fetch_cases(limit=100)
        all_nodes = []
        for c in cases:
            all_nodes.extend(c.actions)
        node_str = " ".join(all_nodes)
        # 至少识别3种机制
        mechanisms = ["凝缩", "移置", "象征", "二次修正", "投射",
                     "condensation", "displacement", "symbol", "secondary", "projection"]
        found = sum(1 for m in mechanisms if m in node_str)
        self.assertGreaterEqual(found, 3,
                                f"应识别≥3种弗洛伊德机制, found {found}")

    # ===== TR-3.11: FAIL-OPEN 目录不存在 =====
    def test_3_11_fail_open_dir_not_exist(self):
        """TR-3.11: FAIL-OPEN: 目录不存在返回空列表."""
        from oneirology_dream_collector import OneirologyDreamCollector
        collector = OneirologyDreamCollector()
        collector.sessions_root = "/nonexistent/dreams"
        cases = collector.fetch_cases(limit=100)
        self.assertEqual(cases, [])

    # ===== TR-3.12: FAIL-OPEN 单个文件异常 =====
    def test_3_12_fail_open_single_file_error(self):
        """TR-3.12: FAIL-OPEN: 单个文件异常不影响其他."""
        from oneirology_dream_collector import OneirologyDreamCollector
        bad = os.path.join(self._sessions_dir, "dream_brainstorm_daily_bad.md")
        with open(bad, "w") as f:
            f.write("\x00\x01\x02binary\xff\xfe")
        collector = OneirologyDreamCollector()
        collector.sessions_root = self._sessions_dir
        cases = collector.fetch_cases(limit=100)
        self.assertGreater(len(cases), 0)

    # ===== TR-3.13: node_sequence 含梦境专用节点 =====
    def test_3_13_node_sequence_contains_dream_nodes(self):
        """TR-3.13: node_sequence 含梦境专用节点 (freud/trauma/dream_theme)."""
        from oneirology_dream_collector import OneirologyDreamCollector
        collector = OneirologyDreamCollector()
        collector.sessions_root = self._sessions_dir
        cases = collector.fetch_cases(limit=100)
        dream_kw = ["freud", "trauma", "dream_theme", "mechanism",
                    "dream_analysis", "detect_trauma"]
        has_dream_node = False
        for c in cases:
            node_str = " ".join(c.actions).lower()
            if any(kw in node_str for kw in dream_kw):
                has_dream_node = True
                break
        self.assertTrue(has_dream_node, "应含梦境专用节点关键词")

    # ===== TR-3.14: 每个梦境日志生成多条 case =====
    def test_3_14_multiple_cases_per_journal(self):
        """TR-3.14: 每个梦境日志按梦境拆分生成多条 case."""
        from oneirology_dream_collector import OneirologyDreamCollector
        collector = OneirologyDreamCollector()
        collector.sessions_root = self._sessions_dir
        cases = collector.fetch_cases(limit=100)
        # 样本1有3个梦境 → 应拆分出≥3条 case
        self.assertGreaterEqual(len(cases), 3,
                                f"应≥3条case(3梦境拆分), got {len(cases)}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
