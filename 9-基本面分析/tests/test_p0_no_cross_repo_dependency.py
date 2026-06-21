import unittest
from pathlib import Path


class TestP0NoCrossRepoDependency(unittest.TestCase):
    def test_ml_trade_service_no_external_exec_loader(self) -> None:
        file_path = Path(__file__).resolve().parent.parent / "ml_trade_service.py"
        content = file_path.read_text(encoding="utf-8")
        self.assertNotIn('_CURRENT_FILE.parents[1] / "经典指标机器学习系统" / "ml_trade_service.py"', content)
        self.assertIn('_SOURCE_FILE = _CURRENT_FILE.parent / "backend" / "src" / "ml_trade_service.py"', content)

    def test_news_digest_no_cross_repo_absolute_fallback(self) -> None:
        file_path = (
            Path(__file__).resolve().parent.parent
            / "ops"
            / "nanoclaw"
            / "core_task1"
            / "scripts"
            / "run_news_digest_on_demand.py"
        )
        content = file_path.read_text(encoding="utf-8")
        self.assertNotIn("经典指标机器学习系统/ops/nanoclaw/core_task1/historical_data", content)


if __name__ == "__main__":
    unittest.main()
