"""trigger_passive_training 入口脚本测试。

测试:
  1. _prepare_record_params: INGEST 路径 → record_params 含 hermes反思
  2. _prepare_record_params: 非 INGEST → None
  3. run_trigger: SKIP 路径 → 无 record_params
  4. run_trigger: 编排器创建失败 → FAIL-OPEN 不崩溃
  5. run_trigger: trigger_passive_training 异常 → FAIL-OPEN 不崩溃
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

# sys.path 注入
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_34_DIR = os.path.dirname(_THIS_DIR)
_CORE_DIR = os.path.join(_34_DIR, "core")

for _p in [_THIS_DIR, _34_DIR, _CORE_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from trigger_passive_training import _prepare_record_params, run_trigger


class PrepareRecordParamsTest(unittest.TestCase):

    def _make_case(self, **kwargs):
        defaults = {
            "intent": "实现P0被动训练",
            "outcome": "success",
            "acceptance_level": "full",
            "domain_tag": "前端训练",
        }
        defaults.update(kwargs)
        return defaults

    def test_ingest_contains_hermes_tag(self):
        """INGEST 路径 → record_params.tags 含 hermes反思。"""
        case = self._make_case()
        result = {
            "status": "coaching_started",
            "evaluation": {"decision": "ingest"},
            "coaching_context": {
                "algorithm_patterns": ["recursion"],
                "call_chain": ["func_a"],
                "known_gaps": ["gap1"],
            },
        }
        params = _prepare_record_params(case, result)

        self.assertIsNotNone(params)
        self.assertIn("hermes反思", params["tags"])
        self.assertIn("被动训练", params["tags"])
        self.assertIn("在线辅导", params["tags"])
        self.assertIn("wrapup", params["tags"])
        self.assertEqual(params["quality_level"], "B")
        self.assertIn("实现P0被动训练", params["content"])

    def test_non_ingest_returns_none(self):
        """非 INGEST → record_params 为 None。"""
        case = self._make_case()
        result = {"status": "skipped", "reason": "low value"}
        params = _prepare_record_params(case, result)
        self.assertIsNone(params)

    def test_domain_tag_in_tags(self):
        """domain_tag 正确注入 tags。"""
        case = self._make_case(domain_tag="交易系统")
        result = {
            "status": "coaching_started",
            "evaluation": {"decision": "ingest"},
            "coaching_context": {},
        }
        params = _prepare_record_params(case, result)
        self.assertIn("交易系统", params["tags"])


class RunTriggerTest(unittest.TestCase):

    def _write_case_json(self, case: dict) -> str:
        """写临时案例 JSON 文件，返回路径。"""
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(case, f, ensure_ascii=False)
        return path

    def test_skip_path_no_record_params(self):
        """SKIP 路径 → record_params 为 None。"""
        case = {
            "intent": "test",
            "actions": [],
            "outcome": "failure",
            "learned": [],
            "quality": "D",
        }
        case_path = self._write_case_json(case)

        with patch("orchestrator_factory.create_orchestrator") as mock_factory:
            mock_orch = MagicMock()
            mock_orch.trigger_passive_training.return_value = {
                "status": "skipped",
                "reason": "low value",
                "evaluation": {"decision": "skip"},
            }
            mock_factory.return_value = mock_orch

            result = run_trigger(case_path)

        self.assertEqual(result["status"], "skipped")
        self.assertIsNone(result["record_params"])

    def test_ingest_path_has_record_params(self):
        """INGEST 路径 → record_params 含 hermes反思。"""
        case = {
            "intent": "实现P0",
            "actions": ["编码", "测试"],
            "outcome": "success",
            "learned": ["经验"],
            "acceptance_level": "full",
            "domain_tag": "前端训练",
        }
        case_path = self._write_case_json(case)

        with patch("orchestrator_factory.create_orchestrator") as mock_factory:
            mock_orch = MagicMock()
            mock_orch.trigger_passive_training.return_value = {
                "status": "coaching_started",
                "evaluation": {"decision": "ingest", "novelty": 0.8},
                "coaching_context": {
                    "case_intent": "实现P0",
                    "case_outcome": "success",
                    "acceptance_level": "full",
                    "algorithm_patterns": ["recursion"],
                    "call_chain": ["func_a"],
                    "known_gaps": [],
                    "monitoring_checks": ["检查1"],
                },
            }
            mock_factory.return_value = mock_orch

            result = run_trigger(case_path)

        self.assertEqual(result["status"], "coaching_started")
        self.assertIsNotNone(result["record_params"])
        self.assertIn("hermes反思", result["record_params"]["tags"])
        self.assertEqual(len(result["monitoring_checklist"]), 1)

    def test_orchestrator_creation_fail_open(self):
        """编排器创建失败 → FAIL-OPEN 返回 error 不崩溃。"""
        case_path = self._write_case_json({"intent": "test"})

        with patch("orchestrator_factory.create_orchestrator") as mock_factory:
            mock_factory.side_effect = ImportError("module not found")

            result = run_trigger(case_path)

        self.assertEqual(result["status"], "error")
        self.assertIn("orchestrator creation failed", result["error"])
        self.assertIsNone(result["record_params"])

    def test_trigger_exception_fail_open(self):
        """trigger_passive_training 异常 → FAIL-OPEN 返回 error 不崩溃。"""
        case_path = self._write_case_json({"intent": "test"})

        with patch("orchestrator_factory.create_orchestrator") as mock_factory:
            mock_orch = MagicMock()
            mock_orch.trigger_passive_training.side_effect = RuntimeError("boom")
            mock_factory.return_value = mock_orch

            result = run_trigger(case_path)

        self.assertEqual(result["status"], "error")
        self.assertIn("trigger_passive_training failed", result["error"])
        self.assertIsNone(result["record_params"])


if __name__ == "__main__":
    unittest.main()
