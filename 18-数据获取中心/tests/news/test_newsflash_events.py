"""newsflash × K线 对齐回填路径测试 — SPEC-D1 §2.4 回填路径 2。

口径（预注册）：
  - 上游 od_event_type → D1 Top5 映射；未命中类型再按描述关键词补识别
    （listing/unlock/etf）
  - 去重键 = (d1_event_type, 日, asset)：同日同类事件只留最早一条
  - source="announcement"，attribution="strong"（快讯是直接事件流；
    仅行情反查路径为 weak）
  - ts_precision="second"（快讯精确到秒）；reaction 用日 K 对齐，
    只算 T+24h/T+7d
"""

from data_center.processing.event_store import EventStore
from data_center.processing.newsflash_events import (
    build_events_from_newsflash,
    classify_newsflash,
)

DAY = 86400
BASE_TS = 1700000000


def _rec(etype, desc, published_ms):
    return {"od_event_type": etype, "description": desc, "published_ms": str(published_ms)}


def _prices(closes):
    return [(BASE_TS + i * DAY, c) for i, c in enumerate(closes)]


def test_classify_direct_mapping():
    """上游类型直映 D1 Top5。"""
    assert classify_newsflash(_rec("monetary_policy", "美联储加息25bp", 0)) == "macro.rate"
    assert classify_newsflash(_rec("security_incident", "某所被盗", 0)) == "hack.security"
    assert classify_newsflash(_rec("crypto_regulation", "SEC 起诉", 0)) == "regulation.crypto"
    assert classify_newsflash(_rec("us_policy", "白宫声明", 0)) == "regulation.crypto"


def test_classify_keyword_override():
    """market_sentiment 桶内按关键词识别 listing/unlock。"""
    assert (
        classify_newsflash(_rec("market_sentiment", "币安将上线 XYZ 现货交易对", 0))
        == "listing.exchange"
    )
    assert (
        classify_newsflash(_rec("token_milestone", "XYZ 将于明日解锁 2% 流通盘代币", 0))
        == "unlock.supply"
    )
    assert classify_newsflash(_rec("crypto_regulation", "比特币 ETF 获批", 0)) == "etf.regulation"


def test_classify_unmapped_returns_empty():
    assert classify_newsflash(_rec("market_sentiment", "今日大盘震荡整理", 0)) == ""
    assert classify_newsflash(_rec("geopolitics", "地缘冲突", 0)) == ""


def test_build_events_end_to_end(tmp_path):
    """端到端：快讯 → 事件 + reaction 入库。"""
    prices = _prices([100, 100, 90, 95, 100, 100, 100, 100, 100, 100])
    recs = [
        _rec("security_incident", "Bithumb 黑客事件", (BASE_TS + DAY) * 1000),
        _rec("monetary_policy", "美联储降息", (BASE_TS + 2 * DAY) * 1000),
        _rec("market_sentiment", "日常行情播报", (BASE_TS + 3 * DAY) * 1000),  # 不入库
    ]
    store = EventStore(tmp_path / "ev.jsonl")
    stats = build_events_from_newsflash(recs, prices, store)
    assert stats["stored"] == 2
    assert stats["skipped_unmapped"] == 1
    evs = store.load()
    hack = [e for e in evs if e["event_type"] == "hack.security"][0]
    assert hack["trigger_ts"] == BASE_TS + DAY
    assert hack["ts_precision"] == "second"
    assert hack["source"] == "announcement"
    assert hack["attribution"] == "strong"
    assert abs(hack["reaction"]["T+24h"] - (-0.10)) < 1e-6


def test_build_events_dedup_same_day(tmp_path):
    """同日同类型只留最早一条。"""
    prices = _prices([100] * 10)
    day0 = BASE_TS - (BASE_TS % DAY)  # 日界对齐，避免跨日
    recs = [
        _rec("monetary_policy", "加息传闻A", (day0 + 3600) * 1000),
        _rec("monetary_policy", "加息传闻B", (day0 + 7200) * 1000),
    ]
    store = EventStore(tmp_path / "ev.jsonl")
    stats = build_events_from_newsflash(recs, prices, store)
    assert stats["stored"] == 1
    assert stats["deduped"] == 1
    assert store.load()[0]["trigger_ts"] == day0 + 3600


def test_fallback_ts_when_no_published_ms(tmp_path):
    """published_ms 缺失 → 回退 _fallback_ts（实测 2096/3048 条如此）。"""
    prices = _prices([100] * 10)
    iso = "2023-11-14T22:13:20Z"  # = BASE_TS
    recs = [{"od_event_type": "security_incident", "description": "被盗", "_fallback_ts": iso}]
    store = EventStore(tmp_path / "ev.jsonl")
    stats = build_events_from_newsflash(recs, prices, store)
    assert stats["stored"] == 1
    assert store.load()[0]["trigger_ts"] == BASE_TS


def test_build_events_failopen(tmp_path):
    """FAIL-OPEN：坏记录跳过不抛。"""
    store = EventStore(tmp_path / "ev.jsonl")
    stats = build_events_from_newsflash([None, {}, "garbage"], [], store)
    assert stats["stored"] == 0
    stats2 = build_events_from_newsflash(None, None, store)
    assert stats2["stored"] == 0
