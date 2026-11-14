"""P3 测试：类内龙头共振矩阵纯函数（不联网）。"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_40_ROOT = Path(__file__).resolve().parent.parent
_40_SCRIPTS = _40_ROOT / "scripts"
for _p in (str(_40_ROOT), str(_40_SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import asset_classes as ac  # noqa: E402
from p3_leader_resonance import build_member_entry, member_inst_id  # noqa: E402


def _series(n: int = 200, scale: float = 1.0, seed: int = 7):
    rng = np.random.default_rng(seed)
    closes = 100.0 * np.cumprod(1 + rng.normal(0, 0.02, n))
    return list(range(n)), [float(c * scale) for c in closes]


def test_member_inst_id_uses_leader_config():
    cfg = {"leader": "NVDA", "inst_id": "NVDA-USDT-SWAP"}
    assert member_inst_id("NVDA", cfg) == "NVDA-USDT-SWAP"
    assert member_inst_id("AMZN", cfg) == "AMZN-USDT-SWAP"


def test_build_member_entry_computes_r_vs_leader():
    leader = _series()
    member = _series(scale=2.0)  # 同形态、两倍价格 → corr0≈1（beta 基于收益率≈1）
    entry = build_member_entry(
        "AMZN", "us_stock", {"leader": "NVDA", "inst_id": "NVDA-USDT-SWAP"}, member, leader
    )
    assert entry["class"] == "us_stock"
    assert entry["leader"] == "NVDA"
    assert entry["n_samples"] == 200
    assert entry["corr0"] > 0.99
    assert 0.9 < entry["beta"] < 1.1
    assert entry["degraded"] == []


def test_build_member_entry_fails_open_without_leader():
    member = _series()
    entry = build_member_entry(
        "XAG", "precious_metal", {"leader": "XAU", "inst_id": "XAU-USDT-SWAP"}, member, (None, None)
    )
    assert entry["corr0"] == 1.0
    assert "leader_missing" in entry["degraded"]


def test_every_live_registry_symbol_has_class_leader():
    """22 域 live 注册表的每个标的都能在资产类别表里找到（龙头或成员）。"""
    import json

    registry = json.loads(
        (_40_ROOT.parent / "22-执行引擎中心" / "config" / "live_symbols.json").read_text(
            encoding="utf-8"
        )
    )
    bases = {str(k).upper() for k in registry["symbols"]}
    missing = sorted(b for b in bases if b not in ac.SYMBOL_CLASS)
    assert not missing, f"注册表标的缺少资产类别归属: {missing}"
