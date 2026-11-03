#!/usr/bin/env python3
"""test_run_ablation.py — 消融 runner 的契约与 FAIL-OPEN 验收

覆盖：
  - 样本不足 → f1_pass=f2_pass=false，不抛错
  - 输出格式兼容门禁（f1_pass/f2_pass 布尔，字段齐全）
  - F1 计算正确：签名特征含真实信号时 full 优于 baseline
  - F2 置换检验：真实 full MAE 显著低于随机置换时 p_value<alpha
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_PROTO_DIR = Path(__file__).resolve().parent
if str(_PROTO_DIR) not in sys.path:
    sys.path.insert(0, str(_PROTO_DIR))

import run_ablation as ra_mod  # noqa: E402


def _synthetic_rows(n_bins: int = 60, n_domains: int = 4) -> list:
    """构造 n_bins 个 60min bin、n_domains 个域的合成轨迹（每 bin 每域 1 条）。"""
    rows = []
    bin_sec = 3600.0
    for b in range(n_bins):
        ts = 1_700_000_000.0 + b * bin_sec
        for d in range(n_domains):
            # poe 随时间正弦变化，domain 间有相位差
            poe = 0.5 + 0.5 * np.sin(2 * np.pi * b / 12.0 + d * 0.5)
            lat = 5.0 + 3.0 * np.cos(2 * np.pi * b / 12.0 + d)
            rows.append(
                {
                    "ts": ts,
                    "domain": f"dom{d}",
                    "poe": float(poe),
                    "latency": float(lat),
                }
            )
    return rows


def test_insufficient_samples_fails_open():
    rows = _synthetic_rows(n_bins=10)
    res = ra_mod.run_ablation(rows, n_perm=10)
    assert res["f1_pass"] is False
    assert res["f2_pass"] is False
    assert res["n_samples"] < 20
    assert "reason" in res


def test_output_schema_matches_gate_contract():
    rows = _synthetic_rows(n_bins=40)
    res = ra_mod.run_ablation(rows, n_perm=5)
    assert isinstance(res["f1_pass"], bool)
    assert isinstance(res["f2_pass"], bool)
    for key in (
        "mae_baseline",
        "mae_full",
        "improvement_pct",
        "p_value",
        "n_samples",
        "domains",
        "generated_at",
    ):
        assert key in res


def test_f1_improvement_computation(monkeypatch):
    """让签名特征直接携带目标信号，验证 full 显著优于 baseline → f1_pass=True。"""

    def fake_make_windows(bin_centers, domains, poe_grid, lat_grid):
        rng = np.random.default_rng(42)
        n = 200
        # baseline 特征：弱信号（噪声为主）
        X_base = rng.normal(0, 1, (n, 5))
        # 签名特征：第一维 = 目标 + 小噪声（强信号）
        y = rng.normal(0, 1, n)
        X_sig = np.column_stack([y + rng.normal(0, 0.05, n), rng.normal(0, 1, (n, 4))])
        return X_base, X_sig, y, n

    monkeypatch.setattr(ra_mod, "_make_windows", fake_make_windows)
    rows = _synthetic_rows(n_bins=40)
    res = ra_mod.run_ablation(rows, n_perm=50, seed=42)
    assert res["f1_pass"] is True
    assert res["improvement_pct"] > 10.0


def test_f2_permutation_p_value(monkeypatch):
    """签名特征含强信号时，置换后的 MAE 应普遍更高 → p_value 小。"""

    def fake_make_windows(bin_centers, domains, poe_grid, lat_grid):
        rng = np.random.default_rng(7)
        n = 200
        X_base = rng.normal(0, 1, (n, 5))
        y = rng.normal(0, 1, n)
        X_sig = np.column_stack([y + rng.normal(0, 0.02, n), rng.normal(0, 1, (n, 4))])
        return X_base, X_sig, y, n

    monkeypatch.setattr(ra_mod, "_make_windows", fake_make_windows)
    rows = _synthetic_rows(n_bins=40)
    res = ra_mod.run_ablation(rows, n_perm=100, seed=7)
    assert res["f2_pass"] is True
    assert res["p_value"] < 0.05


def test_no_rows_returns_fail_open():
    res = ra_mod.run_ablation([])
    assert res["f1_pass"] is False
    assert res["f2_pass"] is False
    assert res["reason"] == "no_rows"


if __name__ == "__main__":
    sys.exit(0)
