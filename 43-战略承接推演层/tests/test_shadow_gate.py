# -*- coding: utf-8 -*-
"""R0-3 shadow 解除门禁测试（PLAN-NN闭环链施工 WP-R0）。

预注册解除条件（两条件同时满足，fail-open 保持 shadow=True）：
1) 连续 7 天五维非默认（桥开启 + crypto_usdt 天/地/将/法任一 ≠50）
2) P3 迁移一致性 ≥95% 且报告 ≤30 天
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import strategic_extension.signal_publisher as sp  # noqa: E402

NOW = datetime(2026, 11, 9, 1, 0, tzinfo=timezone.utc)


@pytest.fixture()
def gate(tmp_path, monkeypatch):
    monkeypatch.setattr(sp, "_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr(sp, "_GATE_STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setattr(sp, "_GATE_AUDIT_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setattr(sp, "_P3_REPORT_PATH", str(tmp_path / "p3.json"))
    return sp


def test_bridge_off_never_qualifies(gate):
    shadow, audit = gate._shadow_gate_decision(NOW, {"tian": 60}, False)
    assert shadow is True
    assert audit["qualifying_today"] is False
    assert audit["consecutive_days"] == 0


def test_bridge_on_default_scores_not_qualifying(gate):
    shadow, audit = gate._shadow_gate_decision(NOW, {}, True)
    assert shadow is True
    assert audit["qualifying_today"] is False
    assert audit["consecutive_days"] == 0


def test_same_day_publish_not_double_counted(gate):
    gate._shadow_gate_decision(NOW, {"tian": 60}, True)
    _, audit = gate._shadow_gate_decision(NOW, {"tian": 60}, True)
    assert audit["consecutive_days"] == 1


def test_gap_day_resets_consecutive(gate):
    gate._shadow_gate_decision(NOW, {"tian": 60}, True)
    _, audit = gate._shadow_gate_decision(NOW + timedelta(days=3), {"tian": 60}, True)
    assert audit["consecutive_days"] == 1


def test_seven_days_without_p3_report_stays_shadow(gate):
    for d in range(7):
        gate._shadow_gate_decision(NOW + timedelta(days=d), {"tian": 60}, True)
    shadow, audit = gate._shadow_gate_decision(NOW + timedelta(days=7), {"tian": 60}, True)
    assert audit["consecutive_days"] == 8
    assert shadow is True  # 无 P3 报告不解除


def test_low_p3_rate_stays_shadow(gate):
    for d in range(8):
        gate._shadow_gate_decision(NOW + timedelta(days=d), {"tian": 60}, True)
    with open(gate._P3_REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump({"consistency_rate": 0.85, "generated_at": NOW.isoformat()}, f)
    shadow, audit = gate._shadow_gate_decision(NOW + timedelta(days=8), {"tian": 60}, True)
    assert shadow is True
    assert audit["p3_ok"] is False


def test_release_when_both_conditions_met(gate):
    for d in range(7):
        gate._shadow_gate_decision(NOW + timedelta(days=d), {"tian": 60}, True)
    with open(gate._P3_REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump({"consistency_rate": 0.97, "generated_at": NOW.isoformat()}, f)
    shadow, audit = gate._shadow_gate_decision(NOW + timedelta(days=7), {"tian": 60}, True)
    assert shadow is False
    assert audit["released"] is True
    # 解除事件已写审计
    with open(gate._GATE_AUDIT_PATH, encoding="utf-8") as f:
        lines = [json.loads(x) for x in f if x.strip()]
    assert any(x.get("released") for x in lines)


def test_stale_p3_report_stays_shadow(gate):
    for d in range(8):
        gate._shadow_gate_decision(NOW + timedelta(days=d), {"tian": 60}, True)
    old = (NOW - timedelta(days=31)).isoformat()
    with open(gate._P3_REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump({"consistency_rate": 0.97, "generated_at": old}, f)
    shadow, audit = gate._shadow_gate_decision(NOW + timedelta(days=8), {"tian": 60}, True)
    assert shadow is True
    assert audit["p3_ok"] is False
