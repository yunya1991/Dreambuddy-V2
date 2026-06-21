import importlib.util
import unittest
from pathlib import Path


def _load_module():
    module_path = Path(__file__).resolve().parent.parent / "ops" / "nanoclaw" / "core_task1" / "scripts" / "run_news_digest_on_demand.py"
    spec = importlib.util.spec_from_file_location("core_task1_news_digest", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


class TestNewsDedup(unittest.TestCase):
    def test_cross_source_same_event_is_deduped_by_fact_fingerprint(self) -> None:
        mod = _load_module()
        now_iso = mod.NOW.isoformat()
        items = [
            {
                "title": "某鲸鱼40倍做空650枚BTC，爆仓价71,711美元",
                "summary": "地址目前持有 650 枚 BTC 的 40x 空单，价值 4609 万美元。70,520 美元开仓，71,711 美元即爆仓。",
                "category": "onchain_data",
                "source_url": "https://m.theblockbeats.info/flash/337817",
                "published_at": now_iso,
                "source_confidence": "low",
                "risk_flags": [],
                "mention_count": 1,
            },
            {
                "title": "某地址持有4609万美元BTC的40倍杠杆空单，爆仓价71711美元",
                "summary": "某地址持有 650 枚 BTC 的 40 倍杠杆空单，价值 4609 万美元。该订单开仓价格为 70520 美元，若价格上涨至 71711 美元将触及爆仓。",
                "category": "onchain_data",
                "source_url": "https://www.odaily.news/zh-CN/newsflash/473645",
                "published_at": now_iso,
                "source_confidence": "low",
                "risk_flags": [],
                "mention_count": 1,
            },
        ]
        rows = mod._preprocess_crypto_news(items, hours=24)
        self.assertEqual(len(rows), 1)
        self.assertEqual(int(rows[0].get("mention_count") or 0), 2)
