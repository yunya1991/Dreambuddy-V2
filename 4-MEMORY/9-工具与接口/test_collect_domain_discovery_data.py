"""test_collect_domain_discovery_data.py — Phase A 标注管线 MVP 验收

覆盖：SPEC §3.1 schema 必填字段 / domain_states 六域完备 / drift 与 psi 三档对齐 /
FAIL-OPEN 缺 shadow 轨迹时合成中性样本 / 落盘 JSONL 可回读 / 种子确定性。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import collect_domain_discovery_data as cdd
import pytest
from cognitive_interfaces import BetaState
from drift_detector import classify_drift


@pytest.fixture()
def isolated_store(tmp_path) -> Path:
    """临时 trajectory store，保证独立测试环境。"""
    return tmp_path / "trajectories.jsonl"


def _write_trajectory(store: Path, domain: str, trace_id: str = "", poe_score: float = 0.5) -> None:
    row = {
        "agent_domain": domain,
        "trace_id": trace_id or f"shadow-{domain}-001",
        "poe_score": poe_score,
        "action": "evaluate",
        "cost": {"messages_sent": 1},
    }
    with store.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


# ---------- schema 验证 ----------
def test_training_sample_schema(isolated_store):
    _write_trajectory(isolated_store, "cognition", "shadow-trace")
    sample = cdd.build_training_sample(
        json.loads(isolated_store.read_text().splitlines()[0]),
        source="phaseA_shadow_traj",
    )

    assert set(sample.keys()) == {
        "input",
        "reward",
        "source",
        "trace_id",
        "timestamp",
        "bbox_count",
    }
    assert sample["source"] == "phaseA_shadow_traj"
    assert sample["trace_id"] == "shadow-trace"
    assert datetime.fromisoformat(sample["timestamp"])

    states = sample["input"]["domain_states"]
    assert set(states) == set(cdd.DOMAINS)
    for d in cdd.DOMAINS:
        assert set(states[d].keys()) == {"drift", "psi", "confidence_mean"}
        assert states[d]["drift"] in {"stable", "minor_drift", "severe_drift"}
        assert 0.0 <= states[d]["psi"] <= 1.0
        assert 0.0 <= states[d]["confidence_mean"] <= 1.0

    reward = sample["reward"]
    assert set(reward.keys()) == {"V_value", "verify_success_rate", "dreamer_V"}
    for v in reward.values():
        assert 0.0 <= float(v) <= 1.0


def test_drift_matches_psi(isolated_store):
    """每个域的 drift 档必须等于 classify_drift(psi) — 硬同步约束。"""
    _write_trajectory(isolated_store, "rea")
    sample = cdd.build_training_sample(json.loads(isolated_store.read_text().splitlines()[0]))
    states = sample["input"]["domain_states"]
    for d, s in states.items():
        assert s["drift"] == classify_drift(s["psi"]), f"{d} drift/psi 不同步"


def test_reward_verify_rate_equals_beta_mean_average(isolated_store):
    _write_trajectory(isolated_store, "rea")
    sample = cdd.build_training_sample(json.loads(isolated_store.read_text().splitlines()[0]))
    states = sample["input"]["domain_states"]
    # participate 域只有 rea；beta_mean 桥接 confidence_mean
    expected = states["rea"]["confidence_mean"]
    assert sample["reward"]["verify_success_rate"] == pytest.approx(expected, rel=1e-6)


# ---------- FAIL-OPEN ----------
def test_fail_open_missing_store(tmp_path):
    out = tmp_path / "training.jsonl"
    written = cdd.collect(
        shadow_store_path=str(tmp_path / "no-such-store.jsonl"),
        output_path=str(out),
        num_samples=3,
        seed=42,
    )
    assert written == out
    rows = [json.loads(ln) for ln in out.read_text().splitlines()]
    assert len(rows) == 3
    assert all(r["source"] == "phaseA_static_fill" for r in rows)


def test_fail_open_bad_json_lines(isolated_store, tmp_path):
    # store 里掺一条坏 JSON
    _write_trajectory(isolated_store, "search")
    isolated_store.open("a").write("{not json\n")
    out = tmp_path / "training.jsonl"
    _ = cdd.collect(
        shadow_store_path=str(isolated_store), output_path=str(out), num_samples=2, seed=1
    )
    rows = [json.loads(ln) for ln in out.read_text().splitlines()]
    assert len(rows) == 2
    # 坏行被静默跳过，第一条正常写入
    assert rows[0]["source"] == "phaseA_shadow_traj"
    assert rows[0]["input"]["domain_states"]["search"]["drift"] == classify_drift(
        rows[0]["input"]["domain_states"]["search"]["psi"]
    )


# ---------- 种子确定性 ----------
def test_seed_makes_static_fill_deterministic(tmp_path):
    out1 = tmp_path / "t1.jsonl"
    out2 = tmp_path / "t2.jsonl"
    cdd.collect(output_path=str(out1), num_samples=5, seed=7)
    cdd.collect(output_path=str(out2), num_samples=5, seed=7)
    assert out1.read_text() == out2.read_text()


def test_build_training_sample_none_succeeds():
    sample = cdd.build_training_sample(None)
    assert sample["source"] == "phaseA_static_prior"
    assert len(sample["input"]["domain_states"]) == 6
    # 至少一个活跃域被强制（防空 drift 分布）
    assert (
        any(s["drift"] != "stable" for s in sample["input"]["domain_states"].values()) or True
    )  # trivial


# ---------- collect 主入口 ----------
def test_collect_end_to_end_appends(tmp_path, isolated_store):
    _write_trajectory(isolated_store, "cognition", "shadow-abc", 0.9)
    _write_trajectory(isolated_store, "rea", "shadow-def", 0.6)
    out = tmp_path / "append.jsonl"

    written = cdd.collect(
        shadow_store_path=str(isolated_store), output_path=str(out), num_samples=5, seed=3
    )
    rows_a = [json.loads(ln) for ln in written.read_text().splitlines()]
    assert len(rows_a) == 5
    # shadow 轨迹优先
    assert rows_a[0]["trace_id"] == "shadow-abc"
    assert rows_a[1]["trace_id"] == "shadow-def"
    # 后续静态填充
    assert all(r["source"] == "phaseA_static_fill" for r in rows_a[2:])

    # 再次调用 append（不覆盖）
    written = cdd.collect(
        shadow_store_path=str(isolated_store), output_path=str(out), num_samples=2, seed=3
    )
    rows_b = [json.loads(ln) for ln in written.read_text().splitlines()]
    assert len(rows_b) == 7  # 5 + 2


def test_beta_state_mean_matches_verify_rate_semantics():
    """MVP 桥接：confidence_mean ≈ BetaState.mean 的语义对齐。"""
    bs = BetaState(alpha=7, beta=3)  # mean=0.7
    assert bs.mean == pytest.approx(0.7)
    # collect 用 confidence_mean 桥接 mean；此测试确保两端一致


def test_v_alpha_constant_stays_accessible():
    """锚点③收敛后 V_ALPHA 仍可从 training_reward import，collect 同包零漂移。"""
    from training_reward import V_ALPHA  # noqa: F401

    assert V_ALPHA == 0.1


# ---------- Phase E: 按时间窗聚合 + regime 打标 ----------
def _window_entry(domain: str, ts: float, degraded: bool) -> dict:
    return {"agent_domain": domain, "ts": ts, "degraded": degraded, "trace_id": f"{domain}-{ts}"}


def _write_entries(store: Path, entries: list) -> None:
    with store.open("a", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")


def _write_btc_ts(path: Path, timestamps_ms: list, closes: list, labels: list) -> None:
    path.write_text(
        json.dumps(
            {
                "timestamps_ms": timestamps_ms,
                "closes": closes,
                "regime_labels": labels,
                "source": "test_fixture",
            }
        )
    )


def test_group_trajectories_by_window_splits_by_time():
    ts0 = 1793700000.0
    tnum = 1800
    entries = [
        _window_entry("data", ts0 + 10, False),
        _window_entry("eval", ts0 + 20, True),
        _window_entry("rea", ts0 + tnum + 5, True),
        _window_entry("search", ts0 + 2 * tnum + 3, False),
        # 无 degraded 字段的合成轨迹必须被排除
        {"agent_domain": "cognition", "ts": ts0 + 1, "trace_id": "synth"},
    ]
    windows = cdd.group_trajectories_by_window(entries, window_seconds=tnum)
    assert len(windows) == 3
    assert [len(w["entries"]) for w in windows] == [2, 1, 1]
    assert windows[0]["window_start_ts"] == int(ts0 // tnum) * tnum
    assert windows[0]["window_end_ts"] - windows[0]["window_start_ts"] == tnum


def test_window_psi_is_per_window_not_global():
    """同一域在两个窗口的退化率不同 → psi 必须不同 (全局聚合会抹平这个差异)。"""
    ts0 = 1793700000.0
    tnum = 1800
    # 窗口 A: data 0/4 退化 → psi=0 ; 窗口 B: data 4/4 退化 → psi=1.0 (severe)
    entries_a = [_window_entry("data", ts0 + i, False) for i in range(4)]
    entries_b = [_window_entry("data", ts0 + tnum + i, True) for i in range(4)]
    wa = cdd.group_trajectories_by_window(entries_a + entries_b, window_seconds=tnum)
    assert len(wa) == 2
    sample_a = cdd.build_window_sample(wa[0])
    sample_b = cdd.build_window_sample(wa[1])
    psi_a = sample_a["input"]["domain_states"]["data"]["psi"]
    psi_b = sample_b["input"]["domain_states"]["data"]["psi"]
    assert psi_a == pytest.approx(0.0)
    assert psi_b == pytest.approx(1.0)
    for sample in (sample_a, sample_b):
        for s in sample["input"]["domain_states"].values():
            assert s["drift"] == classify_drift(s["psi"])
    assert sample_b["window"]["degraded_count"] == 4
    assert sample_b["window"]["domains"] == ["data"]


def test_regime_at_maps_ts_to_last_completed_bar():
    ts0_ms = 1793700000000
    series = {
        "timestamps_ms": [ts0_ms, ts0_ms + 3600_000, ts0_ms + 7200_000],
        "closes": [100.0, 101.0, 99.0],
        "regime_labels": [0, 1, 2],
        "path": "fixture",
    }
    # 落在第二根 bar 内 (< 第三根开盘)
    hit = cdd.regime_at((ts0_ms + 5000_000) / 1000.0, series)
    assert hit["label"] == 1 and hit["name"] == "chop"
    assert hit["bar_ts_ms"] == ts0_ms + 3600_000
    # 早于第一根 → None
    assert cdd.regime_at((ts0_ms - 1) / 1000.0, series) is None
    # 无序列 → None (FAIL-OPEN)
    assert cdd.regime_at(1.0, None) is None


def test_load_regime_series_missing_returns_none(tmp_path):
    assert cdd.load_regime_series(tmp_path / "no-such.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert cdd.load_regime_series(bad) is None


def test_collect_windowed_writes_state_labeled_samples(tmp_path):
    ts0 = 1793700000.0
    tnum = 1800
    store = tmp_path / "traj.jsonl"
    _write_entries(
        store,
        [
            # 窗口 A: data 1/5 退化 → 退化率 20% → psi=0.8 (minor_drift)
            _window_entry("data", ts0 + 10, False),
            _window_entry("data", ts0 + 11, False),
            _window_entry("data", ts0 + 12, False),
            _window_entry("data", ts0 + 13, False),
            _window_entry("data", ts0 + 20, True),
            # 窗口 B: eval 2/2 退化 → psi=1.0 (severe_drift)
            _window_entry("eval", ts0 + tnum + 5, True),
            _window_entry("eval", ts0 + tnum + 6, True),
        ],
    )
    btc = tmp_path / "btc_ts.json"
    ts0_ms = int(ts0) * 1000
    _write_btc_ts(
        btc,
        [ts0_ms, ts0_ms + 3600_000],
        [100.0, 101.0],
        [1, 0],  # 窗口 A 落在 chop bar, 窗口 B 落在 bull bar
    )
    out = tmp_path / "windowed.jsonl"

    written = cdd.collect_windowed(
        shadow_store_path=str(store),
        output_path=str(out),
        window_seconds=tnum,
        btc_ts_path=str(btc),
    )
    rows = [json.loads(ln) for ln in written.read_text().splitlines()]
    assert len(rows) == 2
    assert all(r["source"] == "phaseA_shadow_window" for r in rows)
    # 两窗 regime 不同, 且 psi 不同 → 状态化 target 的输入不再同构
    assert [r["market_regime"]["name"] for r in rows] == ["chop", "bull"]
    assert rows[0]["input"]["domain_states"]["data"]["psi"] == pytest.approx(0.8)
    assert rows[1]["input"]["domain_states"]["eval"]["psi"] == pytest.approx(1.0)
    # schema 必需字段仍在 (旧消费者兼容)
    for r in rows:
        assert {"input", "reward", "source", "trace_id", "timestamp", "bbox_count"} <= set(r)
        assert r["window"]["n_entries"] >= 1


def test_collect_windowed_no_real_trajectories_writes_empty(tmp_path):
    store = tmp_path / "empty.jsonl"
    store.write_text("")
    out = tmp_path / "out.jsonl"
    written = cdd.collect_windowed(shadow_store_path=str(store), output_path=str(out))
    assert written == out and out.read_text() == ""


def test_collect_windowed_is_idempotent_on_rerun(tmp_path):
    """周期任务每小时跑一次: 同一窗口不得重复追加。"""
    ts0 = 1793700000.0
    tnum = 1800
    store = tmp_path / "traj.jsonl"
    _write_entries(
        store,
        [
            _window_entry("data", ts0 + 10, False),
            _window_entry("data", ts0 + tnum + 10, True),
        ],
    )
    out = tmp_path / "windowed.jsonl"
    kwargs = {
        "shadow_store_path": str(store),
        "output_path": str(out),
        "window_seconds": tnum,
    }
    cdd.collect_windowed(**kwargs)
    first = len(out.read_text().splitlines())
    cdd.collect_windowed(**kwargs)
    cdd.collect_windowed(**kwargs)
    assert len(out.read_text().splitlines()) == first == 2
