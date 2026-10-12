"""CognitiveSessionCollector 单元测试 — P1 DSH 层认知会话采集器.

测试覆盖:
  TR-2.1  类存在且实现 TrainingDataProvider 接口
  TR-2.2  get_source_name() 返回 "cognitive_session"
  TR-2.3  get_quality_threshold() 返回 "B"
  TR-2.4  fetch_cases() 采集 TrainingCase
  TR-2.5  node_sequence 包含 session_start / session_end 节点
  TR-2.6  node_sequence 包含 recall 节点 (从 recalled_memory_ids)
  TR-2.7  node_sequence 包含 action 节点 (从 action_chain.jsonl)
  TR-2.8  layer_tags 包含 "DSH"
  TR-2.9  FAIL-OPEN: 目录不存在返回空列表
  TR-2.10 FAIL-OPEN: session.json 损坏跳过不崩溃
"""
import json
import os
import sys
import tempfile
import unittest

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_ADAPTERS_DIR = os.path.join(os.path.dirname(_THIS_DIR), "adapters")
_34_DIR = os.path.dirname(_THIS_DIR)

for _p in [_THIS_DIR, _ADAPTERS_DIR, _34_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


class CognitiveSessionCollectorTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """创建临时 .cognitive/sessions/ 目录结构。"""
        cls._tmpdir = tempfile.mkdtemp(prefix="cog_session_test_")
        cls._sessions_dir = os.path.join(cls._tmpdir, "sessions")
        os.makedirs(cls._sessions_dir)

        # 会话1: 完整会话 (有 recall + action_chain)
        sid1 = "CS-TEST-0001"
        s1_dir = os.path.join(cls._sessions_dir, sid1)
        os.makedirs(s1_dir)
        # session.json
        with open(os.path.join(s1_dir, "session.json"), "w") as f:
            json.dump({
                "id": sid1,
                "start_time": 1786238933.44,
                "end_time": 1786240861.67,
                "status": "ended",
                "task_type": "memory-system",
                "action_count": 3,
                "recalled_memory_ids": ["VM-001", "VM-002", "VM-003"],
                "recalled_processes": [
                    {"skill_id": "brainstorming", "match_score": 6.1},
                ],
            }, f)
        # action_chain.jsonl
        with open(os.path.join(s1_dir, "action_chain.jsonl"), "w") as f:
            f.write(json.dumps({"timestamp": 1786238933.49, "session_id": sid1,
                                "action_type": "file_change",
                                "detail": "modified: test.py", "file": "test.py"}) + "\n")
            f.write(json.dumps({"timestamp": 1786239393.82, "session_id": sid1,
                                "action_type": "git_commit",
                                "detail": "feat: test commit", "commit_hash": "abc123"}) + "\n")
            f.write(json.dumps({"timestamp": 1786239407.23, "session_id": sid1,
                                "action_type": "file_change",
                                "detail": "added: new.py", "file": "new.py"}) + "\n")

        # 会话2: 仅 session.json (无 action_chain)
        sid2 = "CS-TEST-0002"
        s2_dir = os.path.join(cls._sessions_dir, sid2)
        os.makedirs(s2_dir)
        with open(os.path.join(s2_dir, "session.json"), "w") as f:
            json.dump({
                "id": sid2,
                "start_time": 1786240081.0,
                "end_time": 1786240090.0,
                "status": "ended",
                "task_type": "bugfix",
                "action_count": 0,
                "recalled_memory_ids": ["VM-004"],
            }, f)

        # 会话3: 损坏的 session.json (应被跳过)
        sid3 = "CS-TEST-0003"
        s3_dir = os.path.join(cls._sessions_dir, sid3)
        os.makedirs(s3_dir)
        with open(os.path.join(s3_dir, "session.json"), "w") as f:
            f.write("{invalid json!!!}")

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    # ===== TR-2.1 =====
    def test_class_exists_and_implements_interface(self):
        from cognitive_session_collector import CognitiveSessionCollector
        from interfaces.training_data_provider import TrainingDataProvider
        c = CognitiveSessionCollector()
        self.assertIsInstance(c, TrainingDataProvider)

    # ===== TR-2.2 =====
    def test_get_source_name(self):
        from cognitive_session_collector import CognitiveSessionCollector
        self.assertEqual(CognitiveSessionCollector().get_source_name(), "cognitive_session")

    # ===== TR-2.3 =====
    def test_get_quality_threshold(self):
        from cognitive_session_collector import CognitiveSessionCollector
        self.assertEqual(CognitiveSessionCollector().get_quality_threshold(), "B")

    # ===== TR-2.4 =====
    def test_fetch_cases_returns_training_cases(self):
        from cognitive_session_collector import CognitiveSessionCollector
        c = CognitiveSessionCollector(sessions_dir=self._sessions_dir)
        cases = c.fetch_cases(limit=100)
        self.assertGreater(len(cases), 0, "应至少采集1条")
        # 损坏的会话应被跳过
        for case in cases:
            self.assertNotIn("CS-TEST-0003", case.intent)

    # ===== TR-2.5 =====
    def test_node_sequence_has_session_markers(self):
        from cognitive_session_collector import CognitiveSessionCollector
        c = CognitiveSessionCollector(sessions_dir=self._sessions_dir)
        cases = c.fetch_cases(limit=100)
        for case in cases:
            actions_str = ",".join(case.actions)
            self.assertIn("session_start", actions_str)
            self.assertIn("session_end", actions_str)

    # ===== TR-2.6 =====
    def test_node_sequence_has_recall_nodes(self):
        from cognitive_session_collector import CognitiveSessionCollector
        c = CognitiveSessionCollector(sessions_dir=self._sessions_dir)
        cases = c.fetch_cases(limit=100)
        # 至少有一条 case 含 recall 节点
        has_recall = any("recall" in a.lower() for case in cases for a in case.actions)
        self.assertTrue(has_recall, "node_sequence 应含 recall 节点")

    # ===== TR-2.7 =====
    def test_node_sequence_has_action_nodes(self):
        from cognitive_session_collector import CognitiveSessionCollector
        c = CognitiveSessionCollector(sessions_dir=self._sessions_dir)
        cases = c.fetch_cases(limit=100)
        # 会话1 有 action_chain → node_sequence 应含 action 节点
        s1_cases = [c for c in cases if "CS-TEST-0001" in c.intent or "0001" in c.intent]
        if s1_cases:
            actions_str = ",".join(s1_cases[0].actions)
            self.assertIn("action", actions_str, "node_sequence 应含 action 节点")

    # ===== TR-2.8 =====
    def test_layer_tags_contains_dsh(self):
        from cognitive_session_collector import CognitiveSessionCollector
        c = CognitiveSessionCollector(sessions_dir=self._sessions_dir)
        cases = c.fetch_cases(limit=100)
        for case in cases:
            self.assertIn("DSH", case.layer_tags)

    # ===== TR-2.9 =====
    def test_fail_open_dir_missing(self):
        from cognitive_session_collector import CognitiveSessionCollector
        c = CognitiveSessionCollector(sessions_dir="/nonexistent/sessions")
        cases = c.fetch_cases(limit=10)
        self.assertEqual(cases, [])

    # ===== TR-2.10 =====
    def test_fail_open_corrupt_session(self):
        """损坏的 session.json 应跳过不崩溃。"""
        from cognitive_session_collector import CognitiveSessionCollector
        c = CognitiveSessionCollector(sessions_dir=self._sessions_dir)
        cases = c.fetch_cases(limit=100)
        # CS-TEST-0003 损坏,不应出现在结果中
        for case in cases:
            self.assertNotIn("0003", case.intent)


if __name__ == "__main__":
    unittest.main()
