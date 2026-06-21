import unittest
from pathlib import Path


class TestP1StructureGovernance(unittest.TestCase):
    def test_backend_src_contains_service_files(self) -> None:
        root = Path(__file__).resolve().parent.parent
        backend_src = root / "backend" / "src"
        self.assertTrue((backend_src / "ml_trade_service.py").exists())
        self.assertTrue((backend_src / "carry_service.py").exists())
        self.assertTrue((backend_src / "lite_code_index.py").exists())

    def test_tests_directory_contains_migrated_tests(self) -> None:
        root = Path(__file__).resolve().parent.parent
        tests_dir = root / "tests"
        self.assertTrue((tests_dir / "test_news_dedup.py").exists())
        self.assertTrue((tests_dir / "test_web3_market_digest_automation.py").exists())
        self.assertTrue((tests_dir / "test_web3_market_digest_automation_fast.py").exists())
        self.assertTrue((tests_dir / "test_p0_no_cross_repo_dependency.py").exists())
        self.assertTrue((tests_dir / "test_p1_structure_governance.py").exists())

    def test_pre_release_gate_script_exists_and_contains_required_checks(self) -> None:
        root = Path(__file__).resolve().parent.parent
        gate = root / "ops" / "nanoclaw" / "core_task1" / "scripts" / "pre_release_gate.sh"
        self.assertTrue(gate.exists())
        content = gate.read_text(encoding="utf-8")
        self.assertIn('pytest tests -q -m "not slow"', content)
        self.assertIn("python -m py_compile backend/src/_embedded_ml_trade_service_source.py backend/src/ml_trade_service.py", content)
        self.assertIn("npm run lint", content)

    def test_ci_workflows_define_not_slow_default_and_slow_nightly(self) -> None:
        root = Path(__file__).resolve().parent.parent
        fast = root / ".github" / "workflows" / "ci-not-slow.yml"
        slow = root / ".github" / "workflows" / "ci-slow-nightly.yml"
        self.assertTrue(fast.exists())
        self.assertTrue(slow.exists())
        fast_content = fast.read_text(encoding="utf-8")
        slow_content = slow.read_text(encoding="utf-8")
        self.assertIn('pytest tests -q -m "not slow"', fast_content)
        self.assertIn("cron:", slow_content)
        self.assertIn("RUN_SLOW_TESTS: \"1\"", slow_content)
        self.assertIn("pytest tests -q -m slow --maxfail=1", slow_content)


if __name__ == "__main__":
    unittest.main()
