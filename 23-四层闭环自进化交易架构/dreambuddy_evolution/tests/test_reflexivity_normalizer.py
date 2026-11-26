"""R_reflexivity 历史分位归一化（F4.1）测试。"""

import json

import pytest

from dreambuddy_evolution.core.level0_path_cost import compute_d_star
from dreambuddy_evolution.core.reflexivity_normalizer import ReflexivityNormalizer


def test_fallback_linear_before_min_samples(tmp_path):
    n = ReflexivityNormalizer(path=str(tmp_path / "h.json"), min_samples=50)
    assert n.percentile(0.35) == pytest.approx(0.0)
    assert n.percentile(0.85) == pytest.approx(1.0)
    assert n.percentile(0.60) == pytest.approx(0.5)


def test_ecdf_after_samples(tmp_path):
    n = ReflexivityNormalizer(path=str(tmp_path / "h.json"), min_samples=10)
    for v in [i / 100 for i in range(100)]:
        n.observe(v)
    assert n.size == 100
    assert n.percentile(0.50) == pytest.approx(0.51, abs=0.02)
    assert n.percentile(0.99) == pytest.approx(1.0, abs=0.02)


def test_persistence_and_cap(tmp_path):
    path = str(tmp_path / "h.json")
    n = ReflexivityNormalizer(path=path, min_samples=5, cap=60)
    for v in [i / 60 for i in range(60)]:
        n.observe(v)
    n.flush()
    assert n.size == 60

    n2 = ReflexivityNormalizer(path=path, min_samples=5, cap=60)
    assert n2.size == 60
    assert n2.percentile(0.5) == pytest.approx(0.5, abs=0.05)

    # 超过 cap 丢最旧
    n2.observe(5.0)
    assert n2.size == 60


def test_cost_norm_disabled_by_default(monkeypatch):
    monkeypatch.delenv("EVOLUTION_DSTAR_REFL_NORM", raising=False)
    rv = {"R_up": 0.45, "R_down": 0.55, "R_smooth": 0.10, "R_flow": 0.5, "R_reflexivity": 0.65}
    r = compute_d_star(rv, wait_mode="calibrated", wait_margin=0.0)
    assert r["R_reflexivity_pct"] is None
    assert r["wait_scale"] == pytest.approx(1.0)
    assert r["costs_calibrated"]["wait"] == pytest.approx(0.9 * 0.65)


def test_cost_norm_enabled_uses_percentile_and_scale(monkeypatch, tmp_path):
    hist = tmp_path / "h.json"
    hist.write_text(json.dumps([i / 100 for i in range(100)]), encoding="utf-8")
    monkeypatch.setenv("EVOLUTION_DSTAR_REFL_NORM", "1")
    monkeypatch.setenv("EVOLUTION_DSTAR_WAIT_SCALE", "2.0")
    monkeypatch.setenv("EVOLUTION_REFL_HISTORY_PATH", str(hist))

    rv = {"R_up": 0.45, "R_down": 0.55, "R_smooth": 0.10, "R_flow": 0.5, "R_reflexivity": 0.50}
    r = compute_d_star(rv, wait_mode="calibrated", wait_margin=0.0)
    assert r["R_reflexivity_pct"] == pytest.approx(0.51, abs=0.02)
    # wait = (1-0.10) * 0.51 * 2.0 ≈ 0.918
    assert r["costs_calibrated"]["wait"] == pytest.approx(0.918, abs=0.02)
    # wait 高于方向代价 → 允许交易
    assert r["d_star"] == "long"


def test_norm_wait_clipped_at_099(monkeypatch, tmp_path):
    hist = tmp_path / "h.json"
    hist.write_text(json.dumps([0.9] * 100), encoding="utf-8")
    monkeypatch.setenv("EVOLUTION_DSTAR_REFL_NORM", "1")
    monkeypatch.setenv("EVOLUTION_DSTAR_WAIT_SCALE", "5.0")
    monkeypatch.setenv("EVOLUTION_REFL_HISTORY_PATH", str(hist))

    rv = {"R_up": 0.45, "R_down": 0.55, "R_smooth": 0.10, "R_flow": 0.5, "R_reflexivity": 0.9}
    r = compute_d_star(rv, wait_mode="calibrated", wait_margin=0.0)
    assert r["costs_calibrated"]["wait"] <= 0.99
