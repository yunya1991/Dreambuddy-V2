# -*- coding: utf-8 -*-
"""P0-1 资产池 v2（五类 + OKX 代币化美股 + 定源规则 + per-anchor min_rows）。

覆盖评审阻断项：
  - B-LT5：per-anchor `history.min_rows` 覆盖全局 quality（`coverage_audit` 先读 per-anchor）
  - B-LT4：五类视图分组 + 首屏池与 leader_registry 同口径
  - B-LT12：`role` 扩 `co_leader`（三大指数并列）
  - §2.3：per-symbol 唯一定源、历史不足显式降级、proxy/tokenized 必标
"""

import datetime
import os
import sqlite3
import sys

import pytest
import yaml

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
_SCRIPTS = os.path.join(_MODULE_ROOT, "scripts")
for _p in (_MODULE_ROOT, _SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from coverage_audit import audit  # noqa: E402
from l1agg import leader_registry as R  # noqa: E402
from l1agg.asset_pool import AssetPoolError, load  # noqa: E402

_DAY = 86400
NOW = int(datetime.datetime(2026, 11, 15, 12, 0, tzinfo=datetime.UTC).timestamp())
CORE_IDS = {"BTC", "ETH", "SOL", "IXIC", "SPX", "XAU", "WTI", "US10Y"}
TOKENIZED = {"AMD", "GEV", "SPCX", "SKHYNIX"}
VIEWS = ("加密", "避险", "大宗", "美股", "情绪")


@pytest.fixture(scope="module")
def pool():
    return load()


# ============================================================ 结构：核心 / 扩展分层
def test_core_anchors_untouched(pool):
    """v1 的 8 个核心锚定不得被 v2 改动（test_asset_pool.py 的断言继续成立）。"""
    assert {a.id for a in pool.anchors} == CORE_IDS
    assert len(pool.anchors) == 8
    assert pool.version == 2


def test_extended_covers_five_views(pool):
    assert pool.extended, "extended_anchors 为空"
    for view in VIEWS:
        assert pool.by_view(view), f"视图 {view} 无成员"
    assert pool.views() == list(VIEWS)


def test_tokenized_us_stocks_in_pool(pool):
    for sym in TOKENIZED:
        anchor = pool.resolve(sym)
        assert anchor is not None, sym
        assert anchor.tokenized is True
        assert anchor.proxy is True, "代币化标的必须 proxy=true"
        assert anchor.venue == "okx"
        assert anchor.inst_id.endswith("-USDT-SWAP")
        assert anchor.min_rows == 250, "代币化美股一律 per-anchor 250"
        assert anchor.history_lt_3y is True


# ============================================================ 定源规则（§2.3）
def test_per_symbol_single_venue(pool):
    """每个标的显式声明 venue，禁止运行时跨源择优。"""
    for anchor in pool.all_anchors():
        assert anchor.venue in ("okx", "fred", "nasdaq"), anchor.id
        assert anchor.instrument_id, anchor.id


def test_long_history_preferred_over_okx(pool):
    """Nasdaq/FRED 有 ≥750 天的标的不得用 OKX 短历史（752 天不得被砍成 250）。"""
    for sym in ("DJIA", "NVDA", "AAPL", "MSFT", "SPY", "QQQ"):
        assert pool.resolve(sym).venue == "nasdaq", sym
    for sym in ("US500", "US100", "CL", "BZ", "NG", "VIX"):
        assert pool.resolve(sym).venue == "fred", sym


def test_tokenized_only_for_okx(pool):
    for anchor in pool.all_anchors():
        if anchor.tokenized:
            assert anchor.venue == "okx", anchor.id


# ============================================================ per-anchor min_rows（B-LT5）
def test_min_rows_per_anchor(pool):
    assert pool.min_rows_for(pool.resolve("BTC")) == 1090  # okx 3 年日历日
    assert pool.min_rows_for(pool.resolve("CL")) == 740  # fred 3 年交易日
    assert pool.min_rows_for(pool.resolve("DJIA")) == 740  # nasdaq 3 年交易日
    assert pool.min_rows_for(pool.resolve("AMD")) == 250  # 代币化短历史
    assert pool.min_rows_for(pool.resolve("GEV")) == 250


def test_global_quality_unchanged(pool):
    """全局 quality 段不得被 per-anchor 覆盖逻辑篡改（test_asset_pool.py L107）。"""
    assert pool.quality["min_rows_3y"] == 1090
    assert pool.quality["min_rows_3y_trading"] == 740


def test_min_rows_falls_back_to_global(tmp_path):
    """未声明 history.min_rows 时按 venue 回落全局。"""
    data = {
        "version": 2,
        "quality": {"min_rows_3y": 1090, "min_rows_3y_trading": 740},
        "anchors": [
            {
                "id": "BTC",
                "asset_class": "crypto",
                "role": "leader",
                "aliases": ["BTC"],
                "instrument": {"venue": "okx", "inst_id": "BTC-USDT"},
                "storage": {"sub_category": "BTC", "metric": "close_usd"},
                "history": {"years": 3},
            }
        ],
        "extended_anchors": [
            {
                "id": "VIX",
                "asset_class": "macro",
                "role": "member",
                "aliases": ["VIX"],
                "instrument": {"venue": "fred", "series_id": "VIXCLS"},
                "storage": {"sub_category": "VIXCLS", "metric": "value"},
                "history": {"years": 3},
            }
        ],
    }
    path = tmp_path / "pool.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    p = load(str(path))
    assert p.min_rows_for(p.resolve("BTC")) == 1090
    assert p.min_rows_for(p.resolve("VIX")) == 740


# ============================================================ 首屏池与跨层一致性
def test_default_pool_fourteen_and_five_views(pool):
    members = pool.pool("default")
    assert len(members) == 14
    assert [a.id for a in members][0] == "BTC"
    covered = {a.view_class for a in members}
    assert covered == set(VIEWS)
    assert sum(1 for a in members if a.view_class == "美股") == 4


def test_pools_match_leader_registry(pool):
    """资产池 pools 与 leader_registry 首屏/扩展池必须同口径（前端零硬编码）。"""
    default_ids = {a.id for a in pool.pool("default")}
    extended_ids = {a.id for a in pool.pool("extended")}
    assert default_ids == set(R.DEFAULT_POOL) - {"US500", "US100", "CL"} | {"SPX", "IXIC", "WTI"}
    assert extended_ids == set(R.EXTENDED_POOL) - {"TLT", "DXY"}
    assert len(R.default_pool()) == 14
    assert len({*default_ids, *extended_ids}) == len(default_ids) + len(extended_ids)


def test_extended_pool_lazy_load_contains_tokenized(pool):
    ids = {a.id for a in pool.pool("extended")}
    assert TOKENIZED <= ids


# ============================================================ 五类视图（B-LT4/B-LT12）
def test_view_members(pool):
    assert {a.id for a in pool.by_view("加密")} == {"BTC", "ETH", "SOL"}
    assert {a.id for a in pool.by_view("避险")} == {"XAU", "XAG"}
    assert {a.id for a in pool.by_view("大宗")} == {"WTI", "BZ", "NG", "XCU"}
    assert "DJIA" in {a.id for a in pool.by_view("美股")}
    assert {a.id for a in pool.by_view("情绪")} == {"US10Y", "VIX", "T10Y2Y"}


def test_co_leader_role_allowed(pool):
    assert pool.resolve("DJIA").role == "co_leader"
    # 核心锚定 leader 语义不变（leader_of 仍回首个 leader）
    assert pool.leader_of("equity_us").id == "SPX"


def test_registry_view_grouping():
    grouped = R.pool_by_view()
    assert list(grouped) == list(VIEWS)
    assert grouped["加密"] == ["BTC", "ETH"]
    assert grouped["美股"] == ["US500", "US100", "DJIA", "NVDA"]
    assert grouped["情绪"] == ["VIX", "US10Y"]
    assert R.view_of("AMD") == "美股"
    assert R.view_of("NOT_A_SYMBOL") is None


def test_registry_tokenized_bindings():
    for sym in TOKENIZED:
        binding = R.resolve(sym)
        assert binding is not None, sym
        assert binding.tokenized is True
        assert binding.proxy is True
        assert binding.asset_class == "us_stock"


# ============================================================ 别名跨层对齐
@pytest.mark.parametrize(
    "key,expected",
    [
        ("CL", "WTI"),
        ("US500", "SPX"),
        ("US100", "IXIC"),
        ("AMD", "AMD"),
        ("海力士", "SKHYNIX"),
        ("000660.KS", "SKHYNIX"),
    ],
)
def test_resolve_cross_layer_aliases(pool, key, expected):
    assert pool.resolve(key).id == expected


# ============================================================ 校验负例
def _write(tmp_path, data):
    path = tmp_path / "pool.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return str(path)


def _base():
    return {
        "version": 2,
        "view_order": ["美股"],
        "anchors": [
            {
                "id": "BTC",
                "asset_class": "crypto",
                "role": "leader",
                "aliases": ["BTC"],
                "instrument": {"venue": "okx", "inst_id": "BTC-USDT"},
                "storage": {"sub_category": "BTC", "metric": "close_usd"},
                "history": {"years": 3},
            }
        ],
        "extended_anchors": [
            {
                "id": "AMD",
                "asset_class": "us_stock",
                "view_class": "美股",
                "role": "member",
                "aliases": ["AMD"],
                "proxy": True,
                "tokenized": True,
                "instrument": {"venue": "okx", "inst_id": "AMD-USDT-SWAP"},
                "storage": {"sub_category": "AMD", "metric": "close_usd"},
                "history": {"years": 1, "history_lt_3y": True, "min_rows": 250},
            }
        ],
    }


def test_tokenized_without_proxy_rejected(tmp_path):
    data = _base()
    data["extended_anchors"][0]["proxy"] = False
    with pytest.raises(AssetPoolError, match="proxy=true"):
        load(_write(tmp_path, data))


def test_short_history_without_min_rows_rejected(tmp_path):
    data = _base()
    data["extended_anchors"][0]["history"].pop("min_rows")
    with pytest.raises(AssetPoolError, match="min_rows"):
        load(_write(tmp_path, data))


def test_unknown_pool_member_rejected(tmp_path):
    data = _base()
    data["pools"] = {"default": ["DOGE"]}
    with pytest.raises(AssetPoolError, match="DOGE"):
        load(_write(tmp_path, data))


def test_duplicate_id_across_layers_rejected(tmp_path):
    data = _base()
    data["extended_anchors"][0]["id"] = "BTC"
    data["extended_anchors"][0]["aliases"] = ["AMD"]
    with pytest.raises(AssetPoolError, match="重复 id"):
        load(_write(tmp_path, data))


def test_short_core_anchor_still_rejected(tmp_path):
    data = _base()
    data["anchors"][0]["history"]["years"] = 1
    with pytest.raises(AssetPoolError, match="years=1"):
        load(_write(tmp_path, data))


# ============================================================ coverage_audit 先读 per-anchor
def _make_db(path, rows):
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE mm_metrics (
            source TEXT NOT NULL, sub_category TEXT NOT NULL, metric_name TEXT NOT NULL,
            metric_value REAL, timestamp INTEGER NOT NULL,
            PRIMARY KEY (source, sub_category, metric_name, timestamp)
        ) WITHOUT ROWID
        """)
    conn.executemany("INSERT INTO mm_metrics VALUES (?, ?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()


def _daily(source, sub, metric, days, value=100.0):
    end = NOW // _DAY
    return [(source, sub, metric, value + i, (end - (days - 1 - i)) * _DAY) for i in range(days)]


def test_coverage_audit_uses_per_anchor_min_rows(tmp_path):
    db = str(tmp_path / "cov.db")
    rows = []
    rows += _daily("okx", "AMD", "close_usd", 250)  # 恰达 250 → PASS
    rows += _daily("okx", "GEV", "close_usd", 179)  # < 250 → FAIL（history_lt_250）
    _make_db(db, rows)
    result = audit(db, days=1095, now=NOW)
    by_id = {a["id"]: a for a in result["anchors"]}
    assert by_id["AMD"]["min_rows"] == 250
    assert by_id["AMD"]["status"] == "PASS", by_id["AMD"]["reasons"]
    assert by_id["GEV"]["status"] == "FAIL"
    assert any("行数 179 < 250" in r for r in by_id["GEV"]["reasons"])
    # 未回填的 nasdaq 长历史标的仍是 MISSING，不得因 per-anchor 被误判 PASS
    assert by_id["NVDA"]["status"] == "MISSING"
    assert by_id["NVDA"]["min_rows"] == 740


def test_coverage_audit_trading_calendar_includes_nasdaq(tmp_path):
    db = str(tmp_path / "cov.db")
    rows = []
    # 连续 740 个交易日（跳过周末）→ 按工作日口径应 PASS（不足日历日 1090）
    day = datetime.datetime.fromtimestamp(NOW, datetime.UTC).date()
    collected = 0
    while collected < 740:
        if day.weekday() < 5:
            ts = int(
                datetime.datetime(day.year, day.month, day.day, tzinfo=datetime.UTC).timestamp()
            )
            rows.append(("nasdaq", "DJIA", "close_usd", 300.0 + collected * 0.01, ts))
            collected += 1
        day -= datetime.timedelta(days=1)
    _make_db(db, rows)
    result = audit(db, days=1095, now=NOW)
    djia = next(a for a in result["anchors"] if a["id"] == "DJIA")
    assert djia["trading_calendar"] is True
    assert djia["status"] == "PASS", djia["reasons"]


# ============================================================ registry coverage 降级状态
def test_registry_coverage_partial_state(tmp_path):
    db = str(tmp_path / "core.db")
    _make_db(db, _daily("okx", "GEV", "close_usd", 179))
    rows = {r["symbol"]: r for r in R.coverage(db, min_days=250)}
    assert rows["GEV"]["status"] == "partial"
    assert rows["GEV"]["degraded_reason"] == "history_lt_250"
    assert rows["GEV"]["tokenized"] is True
    assert rows["AMD"]["status"] == "missing"
