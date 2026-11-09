"""P1 测试：跨类资产注册表 + p3_cross_asset_matrix 纯函数（不联网）。"""

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
from p3_cross_asset_matrix import (  # noqa: E402
    align_pair,
    build_asset_entry,
    ma200_info,
    momentum_3m,
    to_ccxt_swap_symbol,
)

# ── 配置完整性 ────────────────────────────────────────────────────


def test_ten_asset_classes_registered():
    assert len(ac.ASSET_CLASSES) == 10


def test_six_g1_anchors_confirmed():
    assert set(ac.G1_ANCHORS) == {"BTC", "XAU", "CL", "US500", "JP225", "TLT"}


def test_g1_anchors_have_live_swap_inst_ids():
    for sym, cfg in ac.G1_ANCHORS.items():
        assert cfg["inst_id"].endswith("-USDT-SWAP")
        assert ac.class_of(sym) == cfg["class"]


def test_confirmed_decisions():
    assert ac.GOLD_DUAL_TRACK["tradable"] == "XAU-USDT-SWAP"
    assert ac.GOLD_DUAL_TRACK["macro_reference"] == "XAUT/USDT"
    assert ac.EQUITY_ALIGNMENT == "continuous_24h"
    assert ac.TLT_IN_G1 is True
    assert ac.ASSET_CLASSES["rates_credit"]["g1_anchor"] is True


def test_class_of_normalizes_suffix():
    assert ac.class_of("XAU-USDT-SWAP") == "precious_metal"
    assert ac.class_of("XAU/USDT:USDT") == "precious_metal"
    assert ac.class_of("UNKNOWN") is None


def test_inst_id_none_for_macro_only_fx():
    assert ac.inst_id("DXY") is None
    assert ac.inst_id("XAU") == "XAU-USDT-SWAP"


def test_to_ccxt_swap_symbol():
    assert to_ccxt_swap_symbol("XAU-USDT-SWAP") == "XAU/USDT:USDT"


# ── 动量 / MA200 ──────────────────────────────────────────────────


def test_momentum_3m_linear_ramp():
    closes = [100 + i for i in range(63)]
    assert momentum_3m(closes) == 62.0


def test_momentum_3m_short_sample_none():
    assert momentum_3m([100.0] * 10) is None


def test_ma200_short_sample_none():
    assert ma200_info([100.0] * 199) == (None, None)


def test_ma200_constant_series_not_above():
    ma, above = ma200_info([100.0] * 250)
    assert ma == 100.0
    assert above is False


# ── 对齐 ──────────────────────────────────────────────────────────


def test_align_pair_by_common_timestamps():
    ts = list(range(100))
    a, b, n, degraded = align_pair(ts, [1.0] * 100, ts, [2.0] * 100)
    assert n == 100
    assert degraded == []
    assert a[-1] == 1.0 and b[-1] == 2.0


def test_align_pair_tail_fallback_when_disjoint():
    a, b, n, degraded = align_pair(
        list(range(100)), [1.0] * 100, list(range(1000, 1100)), [2.0] * 100
    )
    assert n == 100
    assert "timestamp_misaligned_tail_aligned" in degraded


# ── 条目构造 / fail-open ──────────────────────────────────────────


def _synth_pair(n=200, seed=7):
    rng = np.random.default_rng(seed)
    btc = 100 + np.cumsum(rng.standard_normal(n) * 0.02)
    xau = 100 + 0.5 * (btc - 100) + rng.standard_normal(n) * 0.0001
    return list(range(n)), btc.tolist(), xau.tolist()


def test_build_entry_fetch_failed_is_fail_open():
    cfg = ac.G1_ANCHORS["XAU"]
    entry = build_asset_entry("XAU", cfg, (None, None), (None, None))
    assert entry["degraded"] == ["fetch_failed"]
    assert entry["corr0"] == 1.0
    assert entry["momentum_3m_pct"] is None


def test_build_entry_btc_identity():
    cfg = ac.G1_ANCHORS["BTC"]
    ts, btc, _ = _synth_pair()
    entry = build_asset_entry("BTC", cfg, (ts, btc), (ts, btc))
    assert entry["corr0"] == 1.0
    assert entry["lag_profile"] == [1.0]
    assert entry["beta"] == 1.0
    assert entry["n_samples"] == 200


def test_build_entry_cross_correlation_and_granger():
    ts, btc, xau = _synth_pair()
    cfg = ac.G1_ANCHORS["XAU"]
    entry = build_asset_entry("XAU", cfg, (ts, xau), (ts, btc))
    assert entry["corr0"] > 0.9
    assert entry["class"] == "precious_metal"
    assert entry["granger_p"] is not None
    assert 0.0 <= entry["granger_p"] <= 1.0
    assert entry["ma200"] is not None


def test_build_entry_btc_missing_degrades():
    ts, _, xau = _synth_pair()
    cfg = ac.G1_ANCHORS["XAU"]
    entry = build_asset_entry("XAU", cfg, (ts, xau), (None, None))
    assert "btc_anchor_missing" in entry["degraded"]
    assert entry["corr0"] == 1.0


def test_build_entry_short_sample_resonance_fallback():
    ts = list(range(20))
    closes = [100.0 + i for i in range(20)]
    cfg = ac.G1_ANCHORS["CL"]
    entry = build_asset_entry("CL", cfg, (ts, closes), (ts, closes))
    assert "resonance_fallback" in entry["degraded"]
