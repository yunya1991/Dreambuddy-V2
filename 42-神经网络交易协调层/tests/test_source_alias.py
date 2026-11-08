#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P1-05：Canonical source 双写 + source 枚举一致性契约测试。

验收口径（49-SPEC §13.5 P1-05）：
- Canonical source：`bdsm`→`11-bdsm` 双写（SOURCE_ALIAS_MODE=1 时同发两条）
- 双写两条 signal_id 不同（同币种同日幂等替换各自独立）
- 旧别名兼容：SOURCE_ALIAS_MODE 未设置时仅发旧 source=bdsm（回滚路径）
- source 枚举一致：registry 名称必须属于 canonical 枚举；禁止 `11-strategy`
"""

import os
import sys
from datetime import datetime, timezone

import pytest

_42_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _42_ROOT not in sys.path:
    sys.path.insert(0, _42_ROOT)

_ADAPTERS_DIR = os.path.join(_42_ROOT, "adapters")
if _ADAPTERS_DIR not in sys.path:
    sys.path.insert(0, _ADAPTERS_DIR)

import bdsm_state_adapter  # noqa: E402
import registry_validator  # noqa: E402
from signal_bus import SignalBus  # noqa: E402


def _snapshot():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return {
        "snapshot_date": today,
        "coins": {
            "BTC": {
                "available": True,
                "direction_constraint": "LONG_ONLY",
                "confidence": 0.7,
                "cap_multiplier": 0.8,
                "score": 75.0,
            }
        },
    }


# ── 1. 回滚路径：未设置开关时仅发旧别名 source=bdsm ──
def test_alias_mode_disabled_default(monkeypatch):
    monkeypatch.delenv("SOURCE_ALIAS_MODE", raising=False)
    signals = bdsm_state_adapter.build_publish_signals(_snapshot())
    assert signals, "应至少发布一条信号"
    assert all(s["source"] == "bdsm" for s in signals)
    assert all(s["signal_id"].startswith("sig_bdsm_") for s in signals)


# ── 2. 双写：SOURCE_ALIAS_MODE=1 时 canonical + 别名各一条 ──
def test_dual_write_when_enabled(monkeypatch):
    monkeypatch.setenv("SOURCE_ALIAS_MODE", "1")
    signals = bdsm_state_adapter.build_publish_signals(_snapshot())
    sources = [s["source"] for s in signals]
    assert "11-bdsm" in sources, "缺少 canonical source=11-bdsm"
    assert "bdsm" in sources, "缺少旧别名 source=bdsm（双写兼容）"
    assert len(signals) == 2, "单币种应恰好双写两条"


# ── 3. 双写 signal_id 区分：canonical 与别名各自幂等 ──
def test_dual_write_signal_ids_distinct(monkeypatch):
    monkeypatch.setenv("SOURCE_ALIAS_MODE", "1")
    signals = bdsm_state_adapter.build_publish_signals(_snapshot())
    ids = [s["signal_id"] for s in signals]
    assert len(set(ids)) == len(ids), "双写 signal_id 必须互不相同"
    canonical = [s for s in signals if s["source"] == "11-bdsm"][0]
    assert canonical["signal_id"].startswith("sig_11_bdsm_")


# ── 4. 双写入总线共存：两条都被接受且按各自 ID 幂等 ──
def test_dual_write_bus_coexist(monkeypatch, tmp_path):
    monkeypatch.setenv("SOURCE_ALIAS_MODE", "1")
    monkeypatch.setenv("SIGNAL_BUS_PERSIST", "1")
    signals = bdsm_state_adapter.build_publish_signals(_snapshot())
    bus = SignalBus(state_path=str(tmp_path / "bus_state.json"))
    for sig in signals:
        result = bus.publish(sig)
        assert result["status"] == "accepted", result
    state = bus.flush()
    assert state["signal_count"] == 2
    assert sorted(state["sources"]) == ["11-bdsm", "bdsm"]
    # 重跑幂等：同 ID 替换不新增
    bus2 = SignalBus(state_path=str(tmp_path / "bus_state.json"))
    for sig in bdsm_state_adapter.build_publish_signals(_snapshot()):
        bus2.publish(sig)
    assert bus2.flush()["signal_count"] == 2


# ── 5. source 枚举一致：registry 名称必须属于 canonical 枚举 ──
def test_registry_name_must_be_canonical(tmp_path):
    registry = tmp_path / "registry.yaml"
    registry.write_text(
        "subsystems:\n"
        "  - name: not-a-canonical-source\n"
        "    publisher: adapters/x.py\n"
        "    publish: [x]\n"
        "    subscribe: []\n"
        "    horizon: days\n"
        "    enabled: true\n",
        encoding="utf-8",
    )
    errors = registry_validator.validate_registry(str(registry))
    assert any("canonical" in e or "枚举" in e for e in errors), errors


# ── 6. 禁止 11-strategy（DEC-28：strategy 不是独立 canonical source）──
def test_registry_rejects_11_strategy(tmp_path):
    registry = tmp_path / "registry.yaml"
    registry.write_text(
        "subsystems:\n"
        "  - name: 11-strategy\n"
        "    publisher: adapters/x.py\n"
        "    publish: [x]\n"
        "    subscribe: []\n"
        "    horizon: days\n"
        "    enabled: true\n",
        encoding="utf-8",
    )
    errors = registry_validator.validate_registry(str(registry))
    assert any("11-strategy" in e for e in errors), errors


# ── 7. 旧别名 bdsm 不再允许作为 registry 名（canonical=11-bdsm）──
def test_registry_rejects_legacy_alias_name(tmp_path):
    registry = tmp_path / "registry.yaml"
    registry.write_text(
        "subsystems:\n"
        "  - name: bdsm\n"
        "    publisher: adapters/x.py\n"
        "    publish: [x]\n"
        "    subscribe: []\n"
        "    horizon: days\n"
        "    enabled: true\n",
        encoding="utf-8",
    )
    errors = registry_validator.validate_registry(str(registry))
    assert any("canonical" in e or "枚举" in e for e in errors), errors


# ── 8. 当前 registry.yaml 全部名称为 canonical（含 11-bdsm 更名后）──
def test_current_registry_all_canonical():
    errors = registry_validator.validate_registry()
    assert errors == [], errors


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
