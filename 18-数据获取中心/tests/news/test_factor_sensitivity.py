"""因子敏感度三条硬补丁的契约测试 — SPEC §2.9.7 / §2.9.8。"""

from __future__ import annotations

from data_center.processing import factor_sensitivity as fs

# ── 补丁① 双窗口同号 ─────────────────────────────────────


def test_same_sign_positive_eligible():
    r = fs.classify_sensitivity(0.01, 0.02)
    assert r == {"verdict": "positive", "eligible": True, "direction": 1}


def test_same_sign_negative_eligible():
    r = fs.classify_sensitivity(-0.01, -0.02)
    assert r["verdict"] == "positive"
    assert r["direction"] == -1
    assert r["eligible"]


def test_reversal_not_eligible():
    r = fs.classify_sensitivity(0.01, -0.02)
    assert r["verdict"] == "reversal"
    assert not r["eligible"]


def test_weak_below_threshold():
    r = fs.classify_sensitivity(0.0001, 0.02)
    assert r["verdict"] == "weak"
    assert not r["eligible"]


def test_bad_input_is_weak():
    assert fs.classify_sensitivity(None, "x")["verdict"] == "weak"


# ── 补丁② walk-forward 不泄漏 ─────────────────────────────


def test_walk_forward_no_overlap():
    ds = [f"2026-01-{i:02d}" for i in range(1, 21)]
    folds = fs.walk_forward_split(ds, n_folds=4, embargo=1)
    assert len(folds) == 4
    assert fs.validate_no_leakage(folds)
    for f in folds:
        if f["train"]:  # 首折无历史，允许空 train
            assert max(f["train"]) < min(f["test"])


def test_walk_forward_too_few_dates_returns_empty():
    assert fs.walk_forward_split(["2026-01-01", "2026-01-02"], n_folds=4) == []


def test_validate_no_leakage_detects_overlap():
    bad = [{"train": ("2026-01-01", "2026-01-02"), "test": ("2026-01-02", "2026-01-03")}]
    assert not fs.validate_no_leakage(bad)


# ── 补丁③ 涌现三要素门禁 ─────────────────────────────────


def test_emergence_gate_blocks_undefined():
    r = fs.emergence_ready({})
    assert r["ready"] is False
    assert r["missing"] == ["variation", "fitness", "selection"]


def test_emergence_gate_passes_when_defined():
    ok = {"variation": "变异算子", "fitness": "适应度", "selection": "选择压力"}
    assert fs.emergence_ready(ok) == {"ready": True, "missing": []}
