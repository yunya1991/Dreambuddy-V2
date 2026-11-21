"""云端数据摘要与内容适配器测试（不访问网络）。"""

from __future__ import annotations

import unittest

import _support  # noqa: F401 - 注入 skill/scripts 到 sys.path

import cloud_data
import executor
from phone_adapters import get_adapter


FUNDAMENTAL = {
    "modules": {
        "macro": {
            "data": {"vix": {"value": 19.03, "label": "VIX波动率指数"}},
            "metrics": {"core": {"cpi_yoy": 3.82, "fed_funds_rate": 3.88, "vix": 19.03}},
            "meta": {"data_quality": "good"},
        },
        "valuation": {
            "data": {},
            "metrics": {"core": {"mvrv_ratio": 1.27, "valuation_zone": "低估"}},
            "meta": {"data_quality": "good"},
        },
    },
    "timestamp": "2026-11-20T20:33:36Z",
}
RESEARCH = {
    "as_of": "2026-11-20",
    "degraded": False,
    "latest": {"evaluable": 46980, "significant": 17730, "holdout_agree": 2600, "gate_pass": 0, "stable": 0},
    "funnel": [{"step": "已评估单元", "count": 46980}],
    "classes": [{"id": "R1", "name": "趋势延续", "gate_pass": 3775, "mean_abs_rank_ic": 0.0477, "rows": 23490}],
    "coverage": {"rows": [{"label": "BTC", "n": 3376, "gate_pass": 910}]},
    "recommendations": [
        {"target": "DOGE", "relation": "R1", "method": "M01", "horizon": 20, "rank_ic": -0.27, "hit_rate": 0.45,
         "status": "candidate"},
    ],
}
OVERVIEW = {
    "base": "BTC",
    "as_of": "2026-11-20",
    "assets": ["BTC", "ETH"],
    "base_metrics": {"percentile": {"value": 39.85, "sample_n": 1094}},
    "lights": {"answer": "点亮投影覆盖 14 个标的", "quality": {"status": "partial"}},
    "recommended": [{"title": "全市场概览", "reason": "14 个资产"}],
    "degraded": False,
}
MARKET = {"symbol": "BTC", "price": 58730.4, "change24h": -5.6, "source": "okx+dal"}


class DigestTest(unittest.TestCase):
    def test_digest_keeps_selected_metrics_and_labels(self) -> None:
        result = cloud_data.digest(FUNDAMENTAL, RESEARCH, OVERVIEW, MARKET)
        macro = result["fundamentals"]["macro"]
        self.assertEqual(macro["模块"], "宏观")
        self.assertIn("CPI同比%", [row["指标"] for row in macro["指标"]])
        self.assertEqual(result["market"]["价格"], 58730.4)
        self.assertEqual(result["research"]["评估"]["显著"], 17730)
        self.assertEqual(result["technical"]["历史分位"], 39.85)
        self.assertIn("不构成投资建议", result["caveats"])

    def test_digest_tolerates_missing_modules(self) -> None:
        result = cloud_data.digest({}, {}, {}, {})
        self.assertEqual(result["fundamentals"], {})
        self.assertEqual(result["research"]["分类"], [])
        self.assertEqual(result["technical"]["标的数"], 0)


class NoteAdapterTest(unittest.TestCase):
    def test_news_adapter_writes_read_only_steps(self) -> None:
        adapter = get_adapter("news")
        command = adapter.describe({"target": {"source": "sina"}})
        self.assertEqual(command["source"], "sina")
        self.assertEqual(command["app"], "cn.com.sina.finance")
        self.assertEqual([step["action"] for step in command["steps"]][:2], ["open_app", "read_article"])
        self.assertEqual(command["steps"][-1]["action"], "stop")

    def test_xiaohongshu_stops_before_publish_by_default(self) -> None:
        adapter = get_adapter("xiaohongshu")
        command = adapter.describe({"note": {"title": "测试标题", "body": "正文", "topics": ["#数据"]}})
        self.assertFalse(command["publish_authorized"])
        self.assertEqual(command["stop_before"], "publish")
        self.assertEqual(command["topics"], ["数据"])
        self.assertEqual(command["steps"][-1]["action"], "stop")

    def test_publish_flag_is_passed_only_when_authorized(self) -> None:
        adapter = get_adapter("xiaohongshu")
        command = adapter.describe({"note": {"title": "t", "body": "b"}, "publish_authorized": True})
        self.assertTrue(command["publish_authorized"])

    def test_executor_builds_command_for_content_adapters(self) -> None:
        for adapter_name, job in (
            ("news", {"adapter": "news", "target": {"source": "wallstreetcn"}}),
            ("xiaohongshu", {"adapter": "xiaohongshu", "note": {"title": "t", "body": "b"}}),
        ):
            job["_id"] = 1
            command = executor.build_command(job)
            self.assertEqual(command["adapter"], adapter_name)
            self.assertTrue(command["trace_id"])


if __name__ == "__main__":
    unittest.main()
