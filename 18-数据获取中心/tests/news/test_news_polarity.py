"""快讯极性测试 — SPEC-D1-MULTIDIM-STATE §2.8（P3-b）。

覆盖：三源优先级（attention > lexicon > event_prior）、日度序列、时效窗口、
lead/lag 判定、FAIL-OPEN。
"""

import json
from datetime import datetime, timedelta, timezone

from data_center.processing import news_polarity
from data_center.processing.news_polarity import (
    all_window_scores,
    calibrated_flash_score,
    daily_news_series,
    flash_polarity,
    lead_lag,
    learn_word_weights,
    load_calibrated_flashes,
    load_flashes,
    score_window,
)


def _ts(iso: str) -> int:
    return int(datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).timestamp())


def _write(path, recs):
    with open(path, "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path


# ── 三源极性 ───────────────────────────────────────────────


def test_lexicon_bullish():
    """利好词命中多于利空 → +1 / lexicon。"""
    sign, src = flash_polarity({"title": "比特币突破新高", "description": "ETF 获批上线"})
    assert (sign, src) == (1, "lexicon")


def test_lexicon_bearish():
    """利空词命中多于利好 → -1 / lexicon。"""
    sign, src = flash_polarity({"title": "交易所被盗", "description": "用户资金净流出"})
    assert (sign, src) == (-1, "lexicon")


def test_attention_overrides_lexicon():
    """od_attention_type 优先级最高，即使标题是利好。"""
    sign, src = flash_polarity({"title": "ETF 获批", "od_attention_type": "market_risk_off"})
    assert (sign, src) == (-1, "attention")


def test_event_prior_only_when_lexicon_neutral():
    """无方向词时回落到 event_type 先验：security_incident → -1。"""
    sign, src = flash_polarity(
        {"title": "某项目发布例行公告", "od_event_type": "security_incident"}
    )
    assert (sign, src) == (-1, "event_prior")


def test_ambiguous_event_type_stays_zero():
    """歧义事件类型（monetary_policy）不得猜方向。"""
    sign, src = flash_polarity({"title": "美联储召开议息会议", "od_event_type": "monetary_policy"})
    assert (sign, src) == (0, "none")


def test_neutral_no_polarity():
    sign, src = flash_polarity({"title": "Odaily星球日报讯", "description": "今日天气晴"})
    assert (sign, src) == (0, "none")


def test_non_dict_fail_open():
    assert flash_polarity(None) == (0, "none")
    assert flash_polarity("x") == (0, "none")


# ── 日度序列 ───────────────────────────────────────────────


def test_daily_series_sorted_and_bounded(tmp_path):
    p = _write(
        tmp_path / "nf.jsonl",
        [
            {"title": "突破新高", "published_ms": _ts("2026-10-01T12:00:00") * 1000},
            {"title": "暴跌清算", "published_ms": _ts("2026-10-03T12:00:00") * 1000},
            {"title": "突破新高", "published_ms": _ts("2026-10-02T12:00:00") * 1000},
        ],
    )
    series = daily_news_series(path=p)
    assert [d for d, _ in series] == ["2026-10-01", "2026-10-02", "2026-10-03"]
    assert all(-1.0 <= v <= 1.0 for _, v in series)
    assert series[1][1] > 0 and series[2][1] < 0


def test_daily_series_missing_file_fail_open():
    assert daily_news_series(path="/nonexistent/nf.jsonl") == ()


def test_news_density_counts_day_and_important(tmp_path):
    """当日快讯条数 / 重要条数；跨日边界不计入。"""
    p = _write(
        tmp_path / "nf_density.jsonl",
        [
            {"title": "a", "published_ms": _ts("2026-10-01T00:00:00") * 1000, "is_important": True},
            {"title": "b", "published_ms": _ts("2026-10-01T23:59:59") * 1000},
            {"title": "c", "published_ms": _ts("2026-10-02T00:00:00") * 1000},
        ],
    )
    d = news_polarity.news_density(_ts("2026-10-01T12:00:00"), path=p)
    assert d == {"date": "2026-10-01", "n_total": 2, "n_important": 1}


# ── 时效窗口 ───────────────────────────────────────────────


def test_pre_post_windows_split(tmp_path):
    """T 前 1h 利好、T 后 1h 利空 → pre 为正、post 为负。"""
    t = _ts("2026-10-05T12:00:00")
    p = _write(
        tmp_path / "nf2.jsonl",
        [
            {"title": "突破新高", "published_ms": (t - 3600) * 1000},
            {"title": "暴跌清算", "published_ms": (t + 3600) * 1000},
        ],
    )
    scores = all_window_scores(t, path=p)
    assert scores["pre_24h"]["score"] > 0
    assert scores["post_24h"]["score"] < 0
    assert scores["pre_24h"]["n_total"] == 1
    assert scores["post_24h"]["n_total"] == 1


def test_window_coverage(tmp_path):
    """coverage = 有极性 / 总数。"""
    t = _ts("2026-10-05T12:00:00")
    p = _write(
        tmp_path / "nf3.jsonl",
        [
            {"title": "突破新高", "published_ms": (t - 3600) * 1000},
            {"title": "例行公告", "published_ms": (t - 7200) * 1000},
        ],
    )
    s = score_window(t, "pre_24h", path=p)
    assert s["n_total"] == 2 and s["n_polar"] == 1
    assert s["coverage"] == 0.5


def test_unknown_window_returns_zero(tmp_path):
    p = _write(tmp_path / "nf4.jsonl", [])
    s = score_window(_ts("2026-10-05T12:00:00"), "bogus", path=p)
    assert s["score"] == 0.0 and s["n_total"] == 0


# ── lead / lag ─────────────────────────────────────────────


def test_lead_lag_lead():
    assert lead_lag({"score": -0.2}, {"score": 0.5}, "bullish") == "lead"


def test_lead_lag_lag():
    assert lead_lag({"score": 0.5}, {"score": 0.0}, "bullish") == "lag"


def test_lead_lag_coincident():
    assert lead_lag({"score": 0.5}, {"score": 0.2}, "bullish") == "coincident"


def test_lead_lag_undetermined():
    assert lead_lag({"score": 0.0}, {"score": 0.0}, "bullish") == "undetermined"
    assert lead_lag({"score": 0.5}, {"score": 0.5}, "neutral") == "undetermined"


# ── 加载 ───────────────────────────────────────────────────


def test_load_flashes_skips_bad_lines(tmp_path):
    p = tmp_path / "nf5.jsonl"
    p.write_text(
        '{"title":"突破新高","published_ms":1793270085000}\n'
        "not-json\n"
        '{"title":"x"}\n'
        '{"title":"暴跌清算","published_ms":1793270085000,"is_important":"true"}\n',
        encoding="utf-8",
    )
    fs = load_flashes(p)
    assert len(fs) == 2
    assert any(f.important for f in fs)  # 字符串 "true" 也识别为重要
    assert {f.sign for f in fs} == {-1, 1}


# ── P3-b2 词-收益关联校准 ──────────────────────────────────


def _calib_fixture(tmp_path, monkeypatch, n_per_word=60):
    """构造：'涨超' 日 → 次日 +2%，'暴跌' 日 → 次日 -2%（词-日一一对应）。"""
    p = tmp_path / "nf_calib.jsonl"
    d0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rets = {}
    recs = []
    for i in range(n_per_word * 2):
        word, ret = ("涨超", 0.02) if i % 2 == 0 else ("暴跌", -0.02)
        day = d0 + timedelta(days=i)
        recs.append({"title": f"市场{word}", "published_ms": int(day.timestamp()) * 1000})
        rets[day.strftime("%Y-%m-%d")] = ret
    _write(p, recs)
    monkeypatch.setattr(news_polarity, "_btc_next_day_returns", lambda *_a, **_k: rets)
    return p


def test_learn_word_weights_sign_matches_return(tmp_path, monkeypatch):
    p = _calib_fixture(tmp_path, monkeypatch)
    info = learn_word_weights(path=p, min_n=30)
    assert info["usable"] is True
    assert info["n_train"] == 120
    assert info["weights"]["涨超"] > 0
    assert info["weights"]["暴跌"] < 0


def test_learn_word_weights_unusable_without_returns(tmp_path, monkeypatch):
    p = _write(tmp_path / "nf.jsonl", [{"title": "涨超", "published_ms": 1793270085000}])
    monkeypatch.setattr(news_polarity, "_btc_next_day_returns", lambda *_a, **_k: {})
    assert learn_word_weights(path=p)["usable"] is False


def test_learn_word_weights_min_n_filter(tmp_path, monkeypatch):
    p = _calib_fixture(tmp_path, monkeypatch, n_per_word=2)
    info = learn_word_weights(path=p, min_n=30)
    assert info["usable"] is False
    assert info["weights"] == {}


def test_calibrated_flash_score_sums_hits():
    w = {"涨超": 0.1, "暴跌": -0.1}
    assert round(calibrated_flash_score("今日涨超 5%", w), 6) == 0.1
    assert round(calibrated_flash_score("市场暴跌", w), 6) == -0.1
    assert calibrated_flash_score("无关键词", w) == 0.0
    assert calibrated_flash_score(None, w) == 0.0


def test_load_calibrated_flashes_uses_value(tmp_path, monkeypatch):
    p = _calib_fixture(tmp_path, monkeypatch)
    fs = load_calibrated_flashes(path=p)
    assert fs and all(f.source == "calibrated" for f in fs)
    assert all(f.value != 0 for f in fs)


def test_load_calibrated_flashes_fallback_when_unusable(tmp_path, monkeypatch):
    p = _write(tmp_path / "nf.jsonl", [{"title": "涨超", "published_ms": 1793270085000}])
    monkeypatch.setattr(news_polarity, "_btc_next_day_returns", lambda *_a, **_k: {})
    fs = load_calibrated_flashes(path=p)
    assert fs and fs[0].source == "lexicon"  # 回落朴素口径
