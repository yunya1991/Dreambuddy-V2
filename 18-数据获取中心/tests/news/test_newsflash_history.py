"""newsflash 历史翻页回填测试 — SPEC-D1 §2.4 路径 2 补量（P2）。

口径（预注册，禁止事后调整）：
  - 翻页参数 = page（实测 cursor/pageNum 均被 API 忽略），limit 固定 20/页
  - 终止条件：页内最旧条目 published_ms < stop_ts，或空页，或超过 max_pages
  - normalize：缺 id / 缺 publishTimestamp → 丢弃（返回 {}）
  - od_event_type 在抓取期用采集器同款 _classify_event_type 预归类
  - fetch 全部异常 FAIL-OPEN → 重试耗尽返回 []（上游视为终止信号）
"""

from data_center.processing.newsflash_history import (
    iter_pages,
    load_state,
    normalize_flash,
    save_state,
)

BASE_MS = 1700000000_000  # 2023-11-14
HOUR_MS = 3600_000


def _item(oid, ts_ms, title="快讯", desc=""):
    return {
        "id": oid,
        "title": title,
        "description": desc,
        "publishTimestamp": ts_ms,
        "isImportant": False,
    }


# ── normalize_flash ─────────────────────────────────────────
def test_normalize_valid_classifies_event_type():
    out = normalize_flash(_item(1, BASE_MS, "美联储宣布降息25bp", "利率决议"))
    assert out["id"] == 1
    assert out["published_ms"] == BASE_MS
    assert out["od_event_type"] == "monetary_policy"
    assert "美联储" in out["title"]


def test_normalize_rejects_missing_id_or_ts():
    assert normalize_flash({"title": "x"}) == {}
    assert normalize_flash(_item(0, BASE_MS)) == {}
    assert normalize_flash(_item(1, 0)) == {}
    assert normalize_flash("not a dict") == {}
    assert normalize_flash(None) == {}


def test_normalize_description_html_preserved():
    """description 保留原文（下游 classify 自行 strip_html）。"""
    out = normalize_flash(_item(2, BASE_MS, "t", "<p>SEC 批准 ETF</p>"))
    assert out["description"] == "<p>SEC 批准 ETF</p>"


# ── iter_pages ──────────────────────────────────────────────
def _fetcher(pages):
    """pages: dict page→items；缺页=空页。"""

    def fn(page):
        return pages.get(page, [])

    return fn


def test_iter_pages_yields_until_stop_ts():
    pages = {
        1: [_item(3, BASE_MS + 2 * HOUR_MS), _item(2, BASE_MS + HOUR_MS)],
        2: [_item(1, BASE_MS - HOUR_MS)],  # 已越过 stop_ts → 含本页后停
    }
    got = list(iter_pages(_fetcher(pages), start_page=1, stop_ts=BASE_MS // 1000))
    # page2 最旧条目 < stop_ts → 该页仍产出（边界包含），之后终止
    assert [g["id"] for g in got] == [3, 2, 1]


def test_iter_pages_stops_on_empty_page():
    pages = {1: [_item(1, BASE_MS)], 2: []}
    got = list(iter_pages(_fetcher(pages), start_page=1, stop_ts=0))
    assert [g["id"] for g in got] == [1]


def test_iter_pages_respects_max_pages():
    pages = {p: [_item(p, BASE_MS + p * HOUR_MS)] for p in range(1, 100)}
    got = list(iter_pages(_fetcher(pages), start_page=1, stop_ts=0, max_pages=3))
    assert len(got) == 3


def test_iter_pages_failopen_on_fetch_exception():
    def bad(page):
        raise RuntimeError("network down")

    assert list(iter_pages(bad, start_page=1, stop_ts=0)) == []


def test_iter_pages_skips_bad_items():
    pages = {1: [_item(1, BASE_MS), {"broken": True}, _item(2, BASE_MS)]}
    got = list(iter_pages(_fetcher(pages), start_page=1, stop_ts=0, max_pages=1))
    assert [g["id"] for g in got] == [1, 2]


def test_iter_pages_start_page_resume():
    pages = {5: [_item(50, BASE_MS)], 6: []}
    got = list(iter_pages(_fetcher(pages), start_page=5, stop_ts=0))
    assert [g["id"] for g in got] == [50]


# ── state checkpoint ────────────────────────────────────────
def test_state_roundtrip(tmp_path):
    p = tmp_path / "state.json"
    save_state(p, 42)
    assert load_state(p) == 42


def test_load_state_missing_returns_default(tmp_path):
    assert load_state(tmp_path / "nope.json") == 0


def test_load_state_corrupt_returns_default(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    assert load_state(p) == 0
