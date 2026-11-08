# R1b: 约束包络钳位测试（43 层信号 -> 四档约束 -> PACA 钳位）。
from __future__ import annotations

import json
import sys
from pathlib import Path

_16_DIR = Path(__file__).resolve().parents[2]  # 16-调控系统/
_CORE_ROOT = _16_DIR / "core"
if str(_CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(_CORE_ROOT))

from capital_allocator.component import CapitalAllocatorComponent  # noqa: E402
from capital_allocator.constraint_envelope import ConstraintEnvelopeReader  # noqa: E402


def _write_signal(path, tier, leverage_cap, asset_count_cap, long_count_cap, short_count_cap, net_bias):
    data = {
        "payload": {
            "per_asset_class": {
                "crypto_usdt": {
                    "tier": tier,
                    "leverage_cap": leverage_cap,
                    "asset_count_cap": asset_count_cap,
                    "long_count_cap": long_count_cap,
                    "short_count_cap": short_count_cap,
                    "net_bias": net_bias,
                }
            }
        }
    }
    path.write_text(json.dumps(data), encoding="utf-8")


def _write_trades(path):
    # BTC: 10 胜 5 负
    with open(path, "w", encoding="utf-8") as f:
        for i in range(10):
            f.write(json.dumps({"coin": "BTC-USDT-SWAP", "pnl": 5.0, "pnl_pct": 3.0, "close_ts": float(i)}))
            f.write(chr(10))
        for i in range(5):
            f.write(json.dumps({"coin": "BTC-USDT-SWAP", "pnl": -3.0, "pnl_pct": -2.0, "close_ts": float(100 + i)}))
            f.write(chr(10))


def _make_config(tmp_path, trades_file, signal_file):
    cfg = {
        "mode": "shadow",
        "trades_file": str(trades_file),
        "constraint_signal_path": str(signal_file),
        "cache_ttl_sec": 0,
    }
    p = tmp_path / "capital_allocator.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")
    return p


def test_reader_attack_envelope(tmp_path):
    sig = tmp_path / "signal.json"
    _write_signal(sig, "attack", 5, 8, 6, 4, 0.2)
    r = ConstraintEnvelopeReader(signal_path=sig, cache_ttl=600)
    env = r.get_envelope()
    assert env is not None
    assert env["tier"] == "attack"
    assert env["leverage_cap"] == 5
    assert env["asset_count_cap"] == 8
    assert env["net_bias"] == 0.2
    # attack 档：pct_cap = max_pct * 5 / 5 = max_pct（不额外限）
    assert r.leverage_pct_cap(0.25) == 0.25


def test_reader_missing_file_degrades(tmp_path):
    r = ConstraintEnvelopeReader(signal_path=tmp_path / "missing.json", cache_ttl=600)
    assert r.get_envelope() is None
    assert r.leverage_pct_cap(0.25) is None


def test_reader_missing_field_degrades(tmp_path):
    sig = tmp_path / "signal.json"
    sig.write_text(
        json.dumps({"payload": {"per_asset_class": {"crypto_usdt": {"tier": "attack"}}}}),
        encoding="utf-8",
    )
    r = ConstraintEnvelopeReader(signal_path=sig, cache_ttl=600)
    assert r.get_envelope() is None
    assert r.leverage_pct_cap(0.25) is None


def test_reader_tier_pct_caps(tmp_path):
    # defend: 3 -> 0.15；light_defense: 2 -> 0.10；full_freeze: 1 -> 0.05（max_pct=0.25）
    for tier, cap, expected in (("defend", 3, 0.15), ("light_defense", 2, 0.10), ("full_freeze", 1, 0.05)):
        sig = tmp_path / (tier + ".json")
        _write_signal(sig, tier, cap, 5, 4, 3, 0.0)
        r = ConstraintEnvelopeReader(signal_path=sig, cache_ttl=600)
        assert abs(r.leverage_pct_cap(0.25) - expected) < 1e-9


def test_component_full_freeze_clamps_final_pct(tmp_path):
    trades = tmp_path / "trades.jsonl"
    _write_trades(trades)
    sig = tmp_path / "signal.json"
    _write_signal(sig, "full_freeze", 1, 0, 0, 0, 0.0)
    cfg = _make_config(tmp_path, trades, sig)
    comp = CapitalAllocatorComponent(config_path=cfg)
    env = comp.get_constraint_envelope()
    assert env is not None
    assert env["tier"] == "full_freeze"
    snap = comp.evaluate()
    # by_coin 键归一化为 BTC（去掉 -USDT-SWAP 后缀）
    result = snap.by_coin.get("BTC")
    assert result is not None
    # full_freeze 档：final_pct 钳位至 max_pct * 1 / 5 = 0.05
    assert result.final_position_pct <= 0.05 + 1e-9
    advice = comp.get_allocation_advice("BTC", "bcrm", 10000.0)
    assert advice["constraint_envelope"] is not None
    assert advice["constraint_envelope"]["tier"] == "full_freeze"


def test_component_missing_signal_no_clamp(tmp_path):
    trades = tmp_path / "trades.jsonl"
    _write_trades(trades)
    cfg = _make_config(tmp_path, trades, tmp_path / "missing.json")
    comp = CapitalAllocatorComponent(config_path=cfg)
    assert comp.get_constraint_envelope() is None
    advice = comp.get_allocation_advice("BTC", "bcrm", 10000.0)
    assert advice["constraint_envelope"] is None
