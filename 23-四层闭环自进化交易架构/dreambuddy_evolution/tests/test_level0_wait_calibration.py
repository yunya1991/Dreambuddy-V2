"""Level0 wait 口径校准（F4）测试。

背景：wait = R_smooth × R_reflexivity 是两维 [0,1] 乘积，量纲系统性低于单维
R_up / R_down；实测 R_smooth p90=0.164 时 wait≈0.07，d_star 恒为 WAIT。
本测试锁定：
  - legacy 口径默认不变（回归保护）
  - calibrated 口径（1-R_smooth + 中性区 margin）行为正确
  - 环境变量开关生效
"""

import os

import pytest

from dreambuddy_evolution.core.level0_path_cost import compute_d_star

BASE = {"R_up": 0.45, "R_down": 0.55, "R_smooth": 0.10, "R_flow": 0.5, "R_reflexivity": 0.65}
DEEP_LONG = {"R_up": 0.31, "R_down": 0.62, "R_smooth": 0.10, "R_flow": 0.5, "R_reflexivity": 0.65}


def test_legacy_unchanged_backward_compat():
    """legacy: wait = 0.10*0.65 = 0.065 恒最小 → WAIT"""
    r = compute_d_star(BASE)
    assert r["d_star"] == "WAIT"
    assert r["costs"]["wait"] == pytest.approx(0.065)


def test_legacy_shadow_exposes_calibrated():
    """legacy 模式下仍给出 calibrated 影子值，供 N4 事件对比"""
    r = compute_d_star(DEEP_LONG)
    assert r["d_star"] == "WAIT"
    assert r["wait_mode"] == "legacy"
    assert "d_star_calibrated" in r
    assert "costs_calibrated" in r
    # calibrated wait = (1-0.10)*0.65 = 0.585
    assert r["costs_calibrated"]["wait"] == pytest.approx(0.585)


def test_calibrated_no_dead_zone_equivalent_flip():
    """margin=0: 等价 1-R_smooth 口径，bc < wait 即选方向"""
    r = compute_d_star(DEEP_LONG, wait_mode="calibrated", wait_margin=0.0)
    assert r["d_star"] == "long"


def test_calibrated_dead_zone_blocks_weak_edge():
    """margin=0.30: bc=0.45 > 0.585*0.70=0.4095 → 仍 WAIT"""
    r = compute_d_star(BASE, wait_mode="calibrated", wait_margin=0.30)
    assert r["d_star"] == "WAIT"


def test_calibrated_dead_zone_passes_strong_edge():
    """margin=0.30: bc=0.31 ≤ 0.4095 → long"""
    r = compute_d_star(DEEP_LONG, wait_mode="calibrated", wait_margin=0.30)
    assert r["d_star"] == "long"


def test_calibrated_short_side():
    """反向对称：R_down 更小 → short"""
    rv = {"R_up": 0.62, "R_down": 0.31, "R_smooth": 0.10, "R_flow": 0.5, "R_reflexivity": 0.65}
    r = compute_d_star(rv, wait_mode="calibrated", wait_margin=0.30)
    assert r["d_star"] == "short"


def test_env_switch(monkeypatch):
    """EVOLUTION_DSTAR_WAIT_MODE=calibrated 时 d_star 采用校准口径"""
    monkeypatch.setenv("EVOLUTION_DSTAR_WAIT_MODE", "calibrated")
    monkeypatch.setenv("EVOLUTION_DSTAR_WAIT_MARGIN", "0.30")
    r = compute_d_star(DEEP_LONG)
    assert r["wait_mode"] == "calibrated"
    assert r["d_star"] == "long"


def test_env_invalid_falls_back_legacy(monkeypatch):
    monkeypatch.setenv("EVOLUTION_DSTAR_WAIT_MODE", "whatever")
    monkeypatch.setenv("EVOLUTION_DSTAR_WAIT_MARGIN", "not-a-float")
    r = compute_d_star(DEEP_LONG)
    assert r["wait_mode"] == "legacy"
    assert r["d_star"] == "WAIT"
    assert os.environ["EVOLUTION_DSTAR_WAIT_MODE"] == "whatever"
