# -*- coding: utf-8 -*-
"""T-DSH-P2 P2-1 RED: 45 业务门禁适配器。

依据: DESIGN-DSH-ARCH-UPGRADE v0.2 P2·验收(45 业务门禁接为硬门,先 shadow 转正)
+ DD4(45 先 shadow,误拦率 <5% 转硬门) + ADR-6(验收外置,Worker 不自证)
+ 45-评测系统/api/routes.py 契约(异步两段式: submit 202→poll verdict
PASS/BLOCK/INCONCLUSIVE)。

契约:
  build_gate_45(config) -> gate(context) -> (allowed: bool, verdict: dict)
  - shadow 模式: 评测执行、裁决记录,但一律放行(P0 语义延续)
  - hard 模式: PASS 放行;BLOCK/INCONCLUSIVE/TIMEOUT/ERROR 拦截(fail-closed,
    与 l0_foundation.settle「门禁异常按 fail-closed」一致,避免无凭证沉淀)
  - verdict 结构化: {verdict, eval_id, evidence_uri, trace_id, mode}
  - 开关 enable_gate_45_hard 默认关: 关断时即使 config.mode=hard 也按 shadow 放行
  - FAIL-OPEN: config 非 dict / submit_fn·poll_fn 非 callable → None(退回无门禁)
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.gate_45_adapter import (  # noqa: E402  ModuleNotFoundError → RED
    GATE_45_HARD_SWITCH,
    build_gate_45,
    is_gate_45_hard_enabled,
)


def _cfg(mode="hard", submit=None, poll=None, **kw):
    return {
        "mode": mode,
        "submit_fn": submit or (lambda ctx: "EV-TEST-1"),
        "poll_fn": poll or (lambda eid: {"verdict": "PASS", "evidence_uri": "s3://ev/1"}),
        "timeout_s": 5.0,
        "poll_interval_s": 0.0,
        **kw,
    }


# ---------- 开关 ----------


def test_switch_default_off():
    assert is_gate_45_hard_enabled(None) is False
    assert is_gate_45_hard_enabled({}) is False
    assert is_gate_45_hard_enabled({"flags": 1}) is False  # 非 bool 语义键缺失
    assert is_gate_45_hard_enabled({GATE_45_HARD_SWITCH: True}) is True
    assert GATE_45_HARD_SWITCH == "enable_gate_45_hard"


# ---------- build FAIL-OPEN ----------


def test_build_bad_config_returns_none():
    assert build_gate_45(None) is None
    assert build_gate_45("hard") is None
    assert build_gate_45({"mode": "hard"}) is None  # 缺 submit/poll
    assert build_gate_45(_cfg(mode="weird")) is None  # 未知模式


# ---------- shadow 模式 ----------


def test_shadow_allows_even_on_block_verdict():
    gate = build_gate_45(_cfg(mode="shadow", poll=lambda eid: {"verdict": "BLOCK"}))
    allowed, verdict = gate({"trace_id": "tr-1"})
    assert allowed is True  # shadow: 只记录不拦截
    assert verdict["verdict"] == "BLOCK"
    assert verdict["mode"] == "shadow"
    assert verdict["eval_id"] == "EV-TEST-1"
    assert verdict["trace_id"] == "tr-1"


def test_shadow_allows_on_submit_error():
    def boom(ctx):
        raise RuntimeError("network down")

    gate = build_gate_45(_cfg(mode="shadow", submit=boom))
    allowed, verdict = gate({})
    assert allowed is True  # shadow: 异常放行但记录
    assert verdict["verdict"] == "ERROR"


# ---------- hard 模式 ----------


def test_hard_pass_allows_with_evidence():
    gate = build_gate_45(_cfg(mode="hard"), flags={"enable_gate_45_hard": True})
    allowed, verdict = gate({"trace_id": "tr-2"})
    assert allowed is True
    assert verdict["verdict"] == "PASS"
    assert verdict["evidence_uri"] == "s3://ev/1"
    assert verdict["mode"] == "hard"


def test_hard_block_denies():
    gate = build_gate_45(
        _cfg(mode="hard", poll=lambda eid: {"verdict": "BLOCK"}),
        flags={"enable_gate_45_hard": True},
    )
    allowed, verdict = gate({})
    assert allowed is False
    assert verdict["verdict"] == "BLOCK"


def test_hard_inconclusive_denies():
    gate = build_gate_45(
        _cfg(mode="hard", poll=lambda eid: {"verdict": "INCONCLUSIVE"}),
        flags={"enable_gate_45_hard": True},
    )
    allowed, _ = gate({})
    assert allowed is False


def test_hard_poll_timeout_denies_fail_closed():
    # poll 一直返回 running → 超时 → fail-closed 拦截
    gate = build_gate_45(
        _cfg(
            mode="hard", poll=lambda eid: {"status": "running"}, timeout_s=0.01, poll_interval_s=0.0
        ),
        flags={"enable_gate_45_hard": True},
    )
    allowed, verdict = gate({})
    assert allowed is False
    assert verdict["verdict"] == "TIMEOUT"


def test_hard_submit_error_denies_fail_closed():
    def boom(ctx):
        raise RuntimeError("45 unreachable")

    gate = build_gate_45(_cfg(mode="hard", submit=boom), flags={"enable_gate_45_hard": True})
    allowed, verdict = gate({})
    assert allowed is False  # fail-closed: 无凭证不沉淀
    assert verdict["verdict"] == "ERROR"


# ---------- 开关裁决: 关断时 hard 退化为 shadow ----------


def test_switch_off_degrades_hard_to_shadow():
    gate = build_gate_45(
        _cfg(mode="hard", poll=lambda eid: {"verdict": "BLOCK"}),
        flags={},  # 开关默认关
    )
    allowed, verdict = gate({})
    assert allowed is True  # 开关关断 → 按 shadow 放行
    assert verdict["mode"] == "shadow"
    assert verdict["verdict"] == "BLOCK"  # 裁决仍记录,供误拦率统计


def test_switch_on_enforces_hard():
    gate = build_gate_45(
        _cfg(mode="hard", poll=lambda eid: {"verdict": "BLOCK"}),
        flags={GATE_45_HARD_SWITCH: True},
    )
    allowed, _ = gate({})
    assert allowed is False


# ---------- poll 返回带 decided 状态 ----------


def test_poll_status_done_extracts_verdict_fields():
    gate = build_gate_45(
        _cfg(
            mode="hard",
            poll=lambda eid: {
                "status": "done",
                "verdict": "PASS",
                "evidence_uri": "pg://ev/42",
                "score": 0.91,
            },
        ),
        flags={"enable_gate_45_hard": True},
    )
    allowed, verdict = gate({})
    assert allowed is True
    assert verdict["evidence_uri"] == "pg://ev/42"
    assert verdict["eval_id"] == "EV-TEST-1"
