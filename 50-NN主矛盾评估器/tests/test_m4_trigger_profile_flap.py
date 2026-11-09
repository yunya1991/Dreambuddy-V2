"""M4 测试：trigger/weight_profile/regime_overlay/trigger_flap（SPEC-M3）。

覆盖：
  M4-5: trigger → weight_profile 三档（default/macro_led/micro_led）
  M4-6: micro_led regime_overlay 调整 intent 权重
  M4-7: trigger_flap 防振荡（4h 内 ≤2 次切换，超出锁定）
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.decision import make_decision
from core.mappings import WEIGHT_PROFILES, profile_for_trigger
from core.trigger_flap import FLAP_MAX_SWITCHES, FLAP_WINDOW_HOURS, check_trigger_flap

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)

_FLAP_PATH = Path(__file__).resolve().parents[1] / "runtime" / "trigger_flap.jsonl"


def _purge_symbol(symbol: str) -> None:
    """从 trigger_flap.jsonl 中移除指定标的的记录（测试隔离）。"""
    if not _FLAP_PATH.exists():
        return
    try:
        with open(_FLAP_PATH, encoding="utf-8") as f:
            lines = f.read().splitlines()
        kept = [ln for ln in lines if ln and json.loads(ln).get("symbol") != symbol]
        with open(_FLAP_PATH, "w", encoding="utf-8") as f:
            f.write("\n".join(kept) + ("\n" if kept else ""))
    except Exception:  # noqa: BLE001
        pass


def _evidence(source="11-bcrm", direction="long", confidence=0.8, **overrides):
    base = {
        "evidence_id": f"e-{source}",
        "source": source,
        "symbol": "BTC-USDT-SWAP",
        "granularity": "per_symbol",
        "direction": direction,
        "confidence": confidence,
        "horizon": "hours",
        "intent": None,
        "ts": NOW.isoformat(),
        "expires_at": (NOW + timedelta(hours=2)).isoformat(),
        "provenance": "42-bus",
        "payload": {},
    }
    base.update(overrides)
    return base


# ══════════════════════════════════════════════════════════════════
# M4-5: weight_profile 三档
# ══════════════════════════════════════════════════════════════════


class TestWeightProfile:
    def test_profiles_registered(self):
        assert set(WEIGHT_PROFILES) == {"default", "macro_led", "micro_led"}
        assert WEIGHT_PROFILES["default"] == {"macro_weight": 0.30, "micro_weight": 0.70}
        assert WEIGHT_PROFILES["macro_led"] == {"macro_weight": 0.50, "micro_weight": 0.50}
        assert WEIGHT_PROFILES["micro_led"] == {"macro_weight": 0.40, "micro_weight": 0.60}

    def test_profile_for_trigger_unknown_returns_default(self):
        assert profile_for_trigger(None) == WEIGHT_PROFILES["default"]
        assert profile_for_trigger("garbage") == WEIGHT_PROFILES["default"]

    def test_decision_payload_carries_default_profile(self):
        d = make_decision([_evidence()], symbol="BTC-PROFILE-DEFAULT", now=NOW)
        assert d["trigger"] == "default"
        assert d["weight_profile"] == WEIGHT_PROFILES["default"]

    def test_decision_payload_carries_macro_led_profile(self):
        d = make_decision(
            [_evidence(trigger="macro_led")],
            symbol="BTC-PROFILE-MACRO",
            now=NOW,
        )
        assert d["trigger"] == "macro_led"
        assert d["weight_profile"] == WEIGHT_PROFILES["macro_led"]

    def test_decision_payload_carries_micro_led_profile(self):
        d = make_decision(
            [_evidence(payload={"trigger": "micro_led"})],
            symbol="BTC-PROFILE-MICRO",
            now=NOW,
        )
        assert d["trigger"] == "micro_led"
        assert d["weight_profile"] == WEIGHT_PROFILES["micro_led"]


# ══════════════════════════════════════════════════════════════════
# M4-6: regime_overlay
# ══════════════════════════════════════════════════════════════════


class TestRegimeOverlay:
    def test_regime_overlay_trend_boosts_trend_intent(self):
        # 一个 trend path + 一个 reversal path，confidence 相同
        evs = [
            _evidence(source="11-bcrm", direction="long", confidence=0.5, intent="trend"),
            _evidence(source="11-bdsm", direction="short", confidence=0.5, intent="reversal"),
        ]
        evs[0]["regime_overlay"] = "trend"
        d = make_decision(evs, symbol="BTC-REGIME-TREND", now=NOW)
        assert d["regime_overlay"] == "trend"
        # trend 路径置信度应被 ×1.1，reversal ×0.9
        paths = d["payload"]["paths"]
        trend_p = next(p for p in paths if p["intent"] == "trend")
        rev_p = next(p for p in paths if p["intent"] == "reversal")
        assert trend_p["confidence"] == round(0.5 * 1.1, 8)
        assert rev_p["confidence"] == round(0.5 * 0.9, 8)

    def test_regime_overlay_range_boosts_reversal_intent(self):
        evs = [
            _evidence(source="11-bcrm", direction="long", confidence=0.5, intent="trend"),
            _evidence(source="11-bdsm", direction="short", confidence=0.5, intent="reversal"),
        ]
        evs[0]["payload"] = {"regime_overlay": "range"}
        d = make_decision(evs, symbol="BTC-REGIME-RANGE", now=NOW)
        assert d["regime_overlay"] == "range"
        paths = d["payload"]["paths"]
        rev_p = next(p for p in paths if p["intent"] == "reversal")
        assert rev_p["confidence"] == round(0.5 * 1.1, 8)

    def test_regime_overlay_unknown_no_adjustment(self):
        evs = [
            _evidence(source="11-bcrm", direction="long", confidence=0.5, intent="trend"),
        ]
        d = make_decision(evs, symbol="BTC-REGIME-UNK", now=NOW)
        assert d["regime_overlay"] == "unknown"
        assert d["payload"]["paths"][0]["confidence"] == 0.5


# ══════════════════════════════════════════════════════════════════
# M4-7: trigger_flap 防振荡
# ══════════════════════════════════════════════════════════════════


class TestTriggerFlap:
    def test_within_limit_not_locked(self):
        sym = "BTC-FLAP-1"
        _purge_symbol(sym)
        # 首次切换
        d1 = check_trigger_flap(sym, "macro_led", now=NOW)
        assert d1.locked is False
        assert d1.trigger == "macro_led"

    def test_exceeds_limit_locks_to_previous(self):
        sym = "BTC-FLAP-LOCK"
        _purge_symbol(sym)
        # 构造 4h 窗口内多次切换记录
        base = NOW - timedelta(hours=1)
        sequence = ["default", "macro_led", "micro_led", "macro_led"]
        for i, t in enumerate(sequence):
            check_trigger_flap(sym, t, now=base + timedelta(minutes=i * 10))
        # 第 5 次（超出 FLAP_MAX_SWITCHES=2 次切换）应锁定
        result = check_trigger_flap(sym, "micro_led", now=base + timedelta(minutes=50))
        assert result.locked is True
        # 锁定为上一值（macro_led）
        assert result.trigger == "macro_led"
        assert result.switches_in_window > FLAP_MAX_SWITCHES

    def test_flap_decision_reflected_in_decision_payload(self):
        sym = "BTC-FLAP-PAYLOAD"
        _purge_symbol(sym)
        # 快速切换触发锁定
        base = NOW - timedelta(minutes=30)
        for t in ["default", "macro_led", "micro_led", "macro_led"]:
            check_trigger_flap(sym, t, now=base)
        d = make_decision(
            [_evidence(trigger="micro_led")],
            symbol=sym,
            now=NOW,
        )
        # proposed=micro_led 但被锁定为上一值 macro_led
        assert d["payload"]["proposed_trigger"] == "micro_led"
        assert d["payload"]["trigger_flap"]["locked"] is True
        assert d["trigger"] == "macro_led"

    def test_flap_window_constants(self):
        assert FLAP_WINDOW_HOURS == 4.0
        assert FLAP_MAX_SWITCHES == 2
