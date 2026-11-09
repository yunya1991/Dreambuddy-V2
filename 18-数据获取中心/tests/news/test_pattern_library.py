"""模式库构建器测试 — SPEC-D1 §2.5 + docs/PATTERN-STATS-PREREG-v0.1（冻结口径）。

合成数据设计（确定性）：
  价格：day0-59=100，day60-139=110，day140-199=95
    → bull 窗 day60-89（+10%/30d），bear 窗 day140-169（-13.6%），其余 chop
  事件：hack.security(bull 强信号/chop 噪声)、listing.exchange(三 regime 分级强)、
    etf.regulation(bull 方向翻转：前半 +0.06 后半 -0.005)
"""

import json

from data_center.processing.pattern_library import (
    build_patterns,
    regime_bucket,
    save_patterns,
    unconditional_mean_return,
)

DAY = 86400
BASE = 1700000000 - (1700000000 % DAY)


def _prices():
    px = []
    for d in range(200):
        c = 100.0 if d < 60 else (110.0 if d < 140 else 95.0)
        px.append((BASE + d * DAY, c))
    return px


def _ev(etype, day, r24):
    return {
        "event_id": f"EV-t-{etype}-{day}-{r24}",
        "event_type": etype,
        "asset_scope": ["BTC"],
        "trigger_ts": BASE + day * DAY + 3600,
        "ts_precision": "second",
        "market_state": {},
        "reaction": {"T+24h": r24},
        "source": "announcement",
        "attribution": "strong",
    }


def _alt_cell(etype, days, mean, eps):
    return [_ev(etype, d, mean + eps * (1 if i % 2 == 0 else -1)) for i, d in enumerate(days)]


def _events():
    evs = []
    evs += _alt_cell("hack.security", range(62, 81, 2), 0.04, 0.005)  # bull 强
    evs += _alt_cell("hack.security", range(92, 111, 2), 0.001, 0.004)  # chop 噪声
    evs += _alt_cell("listing.exchange", range(62, 81, 2), 0.05, 0.002)  # bull 最强
    evs += _alt_cell("listing.exchange", range(92, 111, 2), 0.02, 0.002)  # chop 次强
    evs += _alt_cell("listing.exchange", range(142, 161, 2), 0.005, 0.002)  # bear 弱
    # etf bull：前 10 天 +0.06，后 10 天 -0.005（方向翻转，整体仍显著为正）
    evs += _alt_cell("etf.regulation", range(61, 71), 0.06, 0.002)
    evs += _alt_cell("etf.regulation", range(71, 81), -0.005, 0.002)
    return evs


def _index(result):
    return {(p["event_type"], p["regime"]): p for p in result["patterns"]}


# ── regime_bucket ─────────────────────────────────────────


def test_regime_bucket_basic():
    px = _prices()
    assert regime_bucket(px, BASE + 70 * DAY) == "bull"  # 110/100 = +10%
    assert regime_bucket(px, BASE + 50 * DAY) == "chop"  # 100/100
    assert regime_bucket(px, BASE + 150 * DAY) == "bear"  # 95/110 ≈ -13.6%
    assert regime_bucket(px, BASE + 10 * DAY) == "unknown"  # 历史不足 30 天


def test_regime_bucket_boundary_and_failopen():
    # 边界带：4.9% → chop；5.1% → bull（严格 >；恰 5.0% 有二进制浮点歧义不作断言）
    px = [(BASE + d * DAY, 100.0) for d in range(31)]
    assert regime_bucket(px + [(BASE + 31 * DAY, 104.9)], BASE + 31 * DAY) == "chop"
    assert regime_bucket(px + [(BASE + 31 * DAY, 105.1)], BASE + 31 * DAY) == "bull"
    assert regime_bucket(None, BASE + 50 * DAY) == "unknown"
    assert regime_bucket(_prices(), "garbage") == "unknown"


def test_unconditional_mean_return():
    mu0 = unconditional_mean_return(_prices())
    # 199 个日收益：仅 day60 +10%、day140 -13.6%，其余 0
    assert abs(mu0 - (0.1 + (95.0 / 110.0 - 1.0)) / 199) < 1e-9
    assert unconditional_mean_return(None) == 0.0
    assert unconditional_mean_return([(1, 100.0)]) == 0.0


# ── build_patterns ────────────────────────────────────────


def test_build_patterns_three_layer_gates():
    result = build_patterns(_events(), _prices(), n_boot=1000, seed=42)
    assert result["version"] == "prereg-v0.1"
    assert result["trials_count"] == 6
    assert len(result["patterns"]) == 6
    pats = _index(result)

    # 第一层 Holm：强信号 candidate，噪声出局
    hb = pats[("hack.security", "bull")]
    assert hb["n_events"] == 10
    assert hb["significance"]["holm_p"] < 0.05
    assert hb["direction_stable"] is True
    hc = pats[("hack.security", "chop")]
    assert hc.get("status") is None

    # 第二层 PBO：hack 仅 2 合格 cell → insufficient_data（不得晋级 verified）
    assert result["families"]["hack.security"]["pbo"] is None
    assert result["families"]["hack.security"]["pbo_status"] == "insufficient_data"
    assert hb["status"] == "candidate"  # 强但因 PBO 不可算保守留 candidate

    # listing 三 cell 排序恒定 → PBO=0 → 门开
    assert result["families"]["listing.exchange"]["pbo"] == 0.0
    assert result["families"]["listing.exchange"]["pbo_status"] == "ok"

    # 第三层 SPA + 稳定性：listing bull 三层全过 → verified
    lb = pats[("listing.exchange", "bull")]
    assert lb["significance"]["spa_p"] < 0.05
    assert lb["status"] == "verified"
    assert isinstance(lb["significance"]["dsr"], float)

    # etf bull：整体显著但前后半方向翻转 → 不得 verified
    eb = pats[("etf.regulation", "bull")]
    assert eb["significance"]["holm_p"] < 0.05
    assert eb["direction_stable"] is False
    assert eb["status"] == "candidate"

    # trials_count 写入 evidence（SPEC-EMERGENCE-3D 硬要求）
    assert all(p["trials_count"] == 6 for p in result["patterns"])


def test_build_patterns_failopen():
    assert build_patterns(None, None)["patterns"] == []
    assert build_patterns("garbage", [])["patterns"] == []
    # 缺 reaction / trigger_ts 的事件跳过不崩溃
    evs = [{"event_type": "hack.security", "trigger_ts": BASE + 70 * DAY}, {"event_type": "x"}]
    assert build_patterns(evs, _prices())["patterns"] == []


def test_build_patterns_unknown_regime_excluded():
    evs = _alt_cell("hack.security", range(2, 21, 2), 0.04, 0.005)  # day<30 → unknown
    result = build_patterns(evs, _prices(), n_boot=100, seed=1)
    assert result["patterns"] == []
    assert result["skipped"]["unknown_regime"] == 10


# ── save_patterns ─────────────────────────────────────────


def test_save_patterns_roundtrip(tmp_path):
    result = build_patterns(_events(), _prices(), n_boot=100, seed=1)
    out = tmp_path / "patterns.jsonl"
    assert save_patterns(result, out) is True
    lines = [json.loads(line) for line in out.open() if line.strip()]
    assert lines[0]["type"] == "run_meta"
    assert lines[0]["trials_count"] == 6
    assert len(lines) == 1 + 6
    assert all(line["type"] == "pattern" for line in lines[1:])


def test_save_patterns_failopen(tmp_path):
    assert save_patterns(None, tmp_path / "x.jsonl") is False
    assert not (tmp_path / "x.jsonl").exists()
    assert save_patterns({"patterns": []}, tmp_path / "nonexist_dir/deep/x.jsonl") in (True, False)
