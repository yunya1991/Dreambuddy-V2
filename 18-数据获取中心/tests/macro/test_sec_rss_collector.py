"""SecRssCollector 测试 — SEC 执法行动 / 加密政策事件采集。

SPEC-Phase2 §6.3:
  - 数据源: SEC RSS 三个 feed（administrative proceedings / litigation releases / press releases）
  - direction 关键词匹配: BEARISH(charge/sue/fraud/...)→short, BULLISH(approve/exempt/...)→long
  - crypto_related: 标题含 crypto/bitcoin/token/digital asset 等
  - 三层去重: dc:creator 精确 + 标题 Jaccard>0.7(24h) + 实体名交集(24h)
  - FAIL-OPEN: feed 解析失败返回空列表

RED 阶段：SecRssCollector 类尚未实现，测试应因 ImportError 失败。
"""
import pytest
from datetime import datetime, timezone, timedelta

from data_center.core.contract import DataRecord

SEC_MOD = "data_center.collectors.macro.sec_rss_collector"


@pytest.fixture
def collector(tmp_path):
    from data_center.collectors.macro.sec_rss_collector import SecRssCollector
    # 用临时状态文件避免跨测试污染
    return SecRssCollector(config={"state_file": str(tmp_path / "sec_state.json")})


# ---------- 基础属性 ----------

def test_source_category(collector):
    assert collector.source == "sec"
    # "enforcement" 不在 DataRecord CATEGORIES，用 "news"（SEC 新闻稿）
    assert collector.category == "news"


# ---------- RSS 解析 ----------

def _make_entry(title, creator="SEC", pub_date=None, link="https://sec.gov/x"):
    if pub_date is None:
        pub_date = datetime.now(timezone.utc)
    return {
        "title": title,
        "link": link,
        "dc_creator": creator,
        "published": pub_date.strftime("%a, %d %b %Y %H:%M:%S %z"),
        "summary": f"SEC {title}",
    }


def test_fetch_parses_rss_entries(collector, mocker):
    """解析 3 个 RSS feed 的 entries，构造 DataRecord。"""
    mock_fetch = mocker.patch(f"{SEC_MOD}.SecRssCollector._fetch_feeds")
    mock_fetch.return_value = [
        _make_entry("SEC Charges Crypto Exchange With Fraud", creator="LR-26520"),
        _make_entry("SEC Approves New Bitcoin ETF Rules", creator="34-105415"),
    ]

    recs = collector.fetch({})

    assert len(recs) == 2
    for r in recs:
        assert isinstance(r, DataRecord)
        assert r.source == "sec"
        assert r.category == "news"
        assert r.sub_category == "sec_deadline"
        assert r.metrics["event_type"] == "sec_deadline"
        assert r.metrics["is_scheduled"] is False


# ---------- direction 关键词匹配 ----------

def test_direction_bearish_keywords(collector, mocker):
    """BEARISH 关键词（charge/fraud/sue）→ direction=short。"""
    mock_fetch = mocker.patch(f"{SEC_MOD}.SecRssCollector._fetch_feeds")
    mock_fetch.return_value = [
        _make_entry("SEC Charges Token Issuer With Securities Fraud"),
    ]
    recs = collector.fetch({})
    assert recs[0].metrics["direction"] == "short"
    assert recs[0].metrics["crypto_related"] is True


def test_direction_bullish_keywords(collector, mocker):
    """BULLISH 关键词（approve/exempt/relief）→ direction=long。"""
    mock_fetch = mocker.patch(f"{SEC_MOD}.SecRssCollector._fetch_feeds")
    mock_fetch.return_value = [
        _make_entry("SEC Grants Exemptive Relief to Bitcoin Fund"),
    ]
    recs = collector.fetch({})
    assert recs[0].metrics["direction"] == "long"


def test_direction_neutral_when_no_keywords(collector, mocker):
    """无 BEARISH/BULLISH 关键词 → direction=neutral。"""
    mock_fetch = mocker.patch(f"{SEC_MOD}.SecRssCollector._fetch_feeds")
    mock_fetch.return_value = [
        _make_entry("SEC Announces Annual Report on Market Activity"),
    ]
    recs = collector.fetch({})
    assert recs[0].metrics["direction"] == "neutral"


def test_crypto_related_detection(collector, mocker):
    """标题含 crypto/bitcoin/token 等 → crypto_related=True。"""
    mock_fetch = mocker.patch(f"{SEC_MOD}.SecRssCollector._fetch_feeds")
    mock_fetch.return_value = [
        _make_entry("SEC Charges XYZ Corporation With Fraud"),  # 非加密
    ]
    recs = collector.fetch({})
    assert recs[0].metrics["crypto_related"] is False


# ---------- 三层去重 ----------

def test_dedup_layer1_creator_exact_match(collector):
    """第 1 层：dc:creator 完全相同 → 重复。"""
    now = datetime.now(timezone.utc)
    new_item = {"title": "SEC Charges A", "dc_creator": "LR-12345", "pub_date": now}
    recent = [{"title": "Different Title", "dc_creator": "LR-12345", "pub_date": now}]
    assert collector.is_duplicate(new_item, recent) is True


def test_dedup_layer2_jaccard_above_threshold(collector):
    """第 2 层：标题 Jaccard > 0.7 且 24h 内 → 重复。"""
    now = datetime.now(timezone.utc)
    title = "SEC Charges Crypto Exchange Coinbase With Securities Fraud"
    new_item = {"title": title, "dc_creator": "LR-111", "pub_date": now}
    # 仅改一个词，Jaccard 仍 > 0.7
    recent = [{"title": title + " Today", "dc_creator": "LR-999", "pub_date": now}]
    assert collector.is_duplicate(new_item, recent) is True


def test_dedup_layer2_jaccard_below_threshold(collector):
    """第 2 层：标题 Jaccard <= 0.7 → 不重复（需实体层进一步判断）。"""
    now = datetime.now(timezone.utc)
    new_item = {"title": "SEC Charges Crypto Exchange", "dc_creator": "LR-111", "pub_date": now}
    recent = [{"title": "FED Holds Interest Rate Steady", "dc_creator": "LR-999", "pub_date": now}]
    # creator 不同、Jaccard 低、实体不重叠 → 不重复
    assert collector.is_duplicate(new_item, recent) is False


def test_dedup_layer3_entity_intersection(collector):
    """第 3 层：实体名（大写词）交集 > 0 且 24h 内 → 重复。"""
    now = datetime.now(timezone.utc)
    new_item = {
        "title": "SEC Charges Binance With Unregistered Offering",
        "dc_creator": "LR-111",
        "pub_date": now,
    }
    recent = [
        {
            "title": "Binance Settles SEC Enforcement Action",
            "dc_creator": "LR-999",
            "pub_date": now - timedelta(hours=2),
        }
    ]
    # creator 不同、Jaccard 可能不高，但共享实体 "Binance" → 重复
    assert collector.is_duplicate(new_item, recent) is True


def test_dedup_outside_time_window_not_duplicate(collector):
    """超过 24h 窗口 → 不重复（即使标题相似）。"""
    now = datetime.now(timezone.utc)
    title = "SEC Charges Crypto Exchange With Fraud"
    new_item = {"title": title, "dc_creator": "LR-111", "pub_date": now}
    recent = [
        {"title": title, "dc_creator": "LR-999", "pub_date": now - timedelta(hours=25)}
    ]
    assert collector.is_duplicate(new_item, recent) is False


def test_dedup_filters_duplicates_in_fetch(collector, mocker):
    """fetch 内部对三 feed 合并结果应用去重，同一行动仅产出一条。"""
    now = datetime.now(timezone.utc)
    mock_fetch = mocker.patch(f"{SEC_MOD}.SecRssCollector._fetch_feeds")
    # 两个 feed 对同一行动各发一条（creator 不同，标题相似）
    mock_fetch.return_value = [
        {"title": "SEC Charges Coinbase With Fraud", "dc_creator": "LR-26520",
         "published": now.strftime("%a, %d %b %Y %H:%M:%S %z"), "link": "l1", "summary": "s"},
        {"title": "SEC Charges Coinbase With Securities Fraud", "dc_creator": "34-105415",
         "published": (now + timedelta(hours=1)).strftime("%a, %d %b %Y %H:%M:%S %z"),
         "link": "l2", "summary": "s"},
    ]
    recs = collector.fetch({})
    # 实体 "Coinbase" 交集 → 去重后仅 1 条
    assert len(recs) == 1


# ---------- FAIL-OPEN ----------

def test_fail_open_feed_parse_error(collector, mocker):
    """feed 解析异常 → 返回空列表，不抛异常。"""
    mock_fetch = mocker.patch(f"{SEC_MOD}.SecRssCollector._fetch_feeds")
    mock_fetch.side_effect = RuntimeError("network error")
    recs = collector.fetch({})
    assert recs == []


def test_fail_open_empty_feeds(collector, mocker):
    """所有 feed 无 entries → 返回空列表。"""
    mock_fetch = mocker.patch(f"{SEC_MOD}.SecRssCollector._fetch_feeds")
    mock_fetch.return_value = []
    recs = collector.fetch({})
    assert recs == []


# ---------- 跨重启去重（sec_rss_processed 状态文件）----------

def test_cross_restart_dedup_via_state_file(collector, mocker):
    """首次 fetch 接受条目后持久化；第二次 fetch 同 creator 条目被去重。"""
    now = datetime.now(timezone.utc)
    entry = {
        "title": "SEC Charges Coinbase With Fraud",
        "dc_creator": "LR-26520",
        "published": now.strftime("%a, %d %b %Y %H:%M:%S %z"),
        "link": "https://sec.gov/lr-26520",
        "summary": "s",
    }
    mock_fetch = mocker.patch(f"{SEC_MOD}.SecRssCollector._fetch_feeds")

    # 第一次：1 条记录
    mock_fetch.return_value = [dict(entry)]
    recs1 = collector.fetch({})
    assert len(recs1) == 1

    # 第二次：同 creator 条目被状态文件去重 → 0 条
    mock_fetch.return_value = [dict(entry)]
    recs2 = collector.fetch({})
    assert len(recs2) == 0


def test_cross_restart_dedup_different_creator_passes(collector, mocker):
    """跨重启：不同 creator 的新条目不被去重。"""
    now = datetime.now(timezone.utc)
    entry1 = {
        "title": "SEC Charges Coinbase With Fraud",
        "dc_creator": "LR-26520",
        "published": now.strftime("%a, %d %b %Y %H:%M:%S %z"),
        "link": "l1", "summary": "s",
    }
    entry2 = {
        "title": "SEC Approves New ETF Framework",
        "dc_creator": "34-105416",
        "published": (now + timedelta(hours=1)).strftime("%a, %d %b %Y %H:%M:%S %z"),
        "link": "l2", "summary": "s",
    }
    mock_fetch = mocker.patch(f"{SEC_MOD}.SecRssCollector._fetch_feeds")

    mock_fetch.return_value = [entry1]
    assert len(collector.fetch({})) == 1

    mock_fetch.return_value = [entry2]
    # creator 不同、实体不重叠 → 通过
    assert len(collector.fetch({})) == 1
