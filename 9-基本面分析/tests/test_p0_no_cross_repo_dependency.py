import unittest
from pathlib import Path


class TestP0NoCrossRepoDependency(unittest.TestCase):
    def test_ml_trade_service_no_external_exec_loader(self) -> None:
        # 实际服务入口已重构为 backend/src/ml_trade_service.py（顶层已删除）
        file_path = (
            Path(__file__).resolve().parent.parent / "backend" / "src" / "ml_trade_service.py"
        )
        self.assertTrue(file_path.exists(), f"入口文件缺失：{file_path}")
        content = file_path.read_text(encoding="utf-8")
        # 禁止引用跨仓硬编码路径（经典指标机器学习系统）
        self.assertNotIn("经典指标机器学习系统", content)
        # 必须有 fallback/嵌入加载机制（backend/src 版本用 _embedded_ml_trade_service_source.py）
        self.assertIn(
            '_SOURCE_FILE = _CURRENT_FILE.with_name("_embedded_ml_trade_service_source.py")',
            content,
        )

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
