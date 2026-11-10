"""WP-R1 N6 测试：16 constraint_envelope SSoT 版本戳校验。

ConstraintEnvelopeReader 读取 43 信号文件的约束包络，并与总线（42 bus_state.json）
中的 43-strategic 信号做版本戳（ts）一致性校验：
- 一致 → 返回文件包络，degraded=False
- 不一致 → 取保守值（caps 取 min，net_bias 取 abs 更小），degraded=True
- 总线不可用 → 回退文件包络，degraded=False
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_16_ROOT = Path(__file__).resolve().parent.parent
_CE_PATH = _16_ROOT / "core" / "capital_allocator" / "constraint_envelope.py"


def _load_ce():
    spec = importlib.util.spec_from_file_location("n6_constraint_envelope", _CE_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["n6_constraint_envelope"] = mod
    spec.loader.exec_module(mod)
    return mod


def _file_signal(
    ts, leverage_cap=4, asset_count_cap=5, long_count_cap=3, short_count_cap=2, net_bias=0.3
):
    return {
        "ts": ts,
        "source": "43-strategic",
        "payload": {
            "per_asset_class": {
                "crypto_usdt": {
                    "tier": "balanced",
                    "leverage_cap": leverage_cap,
                    "asset_count_cap": asset_count_cap,
                    "long_count_cap": long_count_cap,
                    "short_count_cap": short_count_cap,
                    "net_bias": net_bias,
                }
            }
        },
    }


def _bus_signal(
    ts, leverage_cap=4, asset_count_cap=5, long_count_cap=3, short_count_cap=2, net_bias=0.3
):
    sig = _file_signal(ts, leverage_cap, asset_count_cap, long_count_cap, short_count_cap, net_bias)
    return {"signals": [sig]}


# ── 一致：无 degraded ──────────────────────────────────────────


def test_consistent_version_returns_envelope_no_degraded(tmp_path):
    ce = _load_ce()
    ts = "2026-11-09T14:00:00+00:00"
    file_path = tmp_path / "sig.json"
    file_path.write_text(json.dumps(_file_signal(ts)), encoding="utf-8")
    bus_path = tmp_path / "bus.json"
    bus_path.write_text(json.dumps(_bus_signal(ts)), encoding="utf-8")

    reader = ce.ConstraintEnvelopeReader(signal_path=file_path, bus_path=bus_path)
    env = reader.get_envelope()
    assert env is not None
    assert env.get("degraded") is not True
    assert env["leverage_cap"] == 4
    assert env["asset_count_cap"] == 5


# ── 不一致：保守值 + degraded ─────────────────────────────────


def test_inconsistent_version_takes_conservative_caps(tmp_path):
    ce = _load_ce()
    file_ts = "2026-11-09T14:00:00+00:00"
    bus_ts = "2026-11-09T15:00:00+00:00"
    # 文件 caps 较松，总线 caps 较紧 → 取总线（min）
    file_path = tmp_path / "sig.json"
    file_path.write_text(
        json.dumps(_file_signal(file_ts, leverage_cap=5, asset_count_cap=8, net_bias=0.5)),
        encoding="utf-8",
    )
    bus_path = tmp_path / "bus.json"
    bus_path.write_text(
        json.dumps(_bus_signal(bus_ts, leverage_cap=2, asset_count_cap=3, net_bias=0.1)),
        encoding="utf-8",
    )

    reader = ce.ConstraintEnvelopeReader(signal_path=file_path, bus_path=bus_path)
    env = reader.get_envelope()
    assert env is not None
    assert env["degraded"] is True
    # caps 取 min
    assert env["leverage_cap"] == 2
    assert env["asset_count_cap"] == 3
    # net_bias 取 abs 更小（0.1 < 0.5）
    assert env["net_bias"] == 0.1


def test_inconsistent_version_bus_tighter_takes_bus(tmp_path):
    """总线更紧时取总线值（min）。"""
    ce = _load_ce()
    file_path = tmp_path / "sig.json"
    file_path.write_text(
        json.dumps(_file_signal("2026-11-09T14:00:00+00:00", leverage_cap=4)), encoding="utf-8"
    )
    bus_path = tmp_path / "bus.json"
    bus_path.write_text(
        json.dumps(_bus_signal("2026-11-09T15:00:00+00:00", leverage_cap=1)), encoding="utf-8"
    )

    reader = ce.ConstraintEnvelopeReader(signal_path=file_path, bus_path=bus_path)
    env = reader.get_envelope()
    assert env["leverage_cap"] == 1
    assert env["degraded"] is True


# ── 总线不可用：回退文件 ───────────────────────────────────────


def test_bus_unavailable_falls_back_to_file(tmp_path):
    ce = _load_ce()
    file_path = tmp_path / "sig.json"
    file_path.write_text(json.dumps(_file_signal("2026-11-09T14:00:00+00:00")), encoding="utf-8")

    reader = ce.ConstraintEnvelopeReader(signal_path=file_path, bus_path=tmp_path / "no_bus.json")
    env = reader.get_envelope()
    assert env is not None
    assert env.get("degraded") is not True
    assert env["leverage_cap"] == 4


# ── 文件缺失：降级 None ────────────────────────────────────────


def test_file_missing_returns_none(tmp_path):
    ce = _load_ce()
    reader = ce.ConstraintEnvelopeReader(signal_path=tmp_path / "no_sig.json")
    assert reader.get_envelope() is None
