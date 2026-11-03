# -*- coding: utf-8 -*-
"""T-DSH-P2 E2E: 45 硬门禁 × Evidence Bundle × Watchdog × 误拦率转正。

依据: DESIGN-DSH-ARCH-UPGRADE v0.2 P2·验收退出判据(未过门禁的产出无法沉淀;
Watchdog 能识别偏离目标) + V6(未过 45 的产出 0 条进入沉淀,抽样核对)
+ V2(全链路 trace_id 一致) + DD4(误拦率 <5% 转硬门) + H2(开关默认关)。

链路(全部 in-process,45 用 fake submit/poll):
  事件 → Ticket(live) → Worker 产出 → 45 硬门禁(开关开)
  → attach_evidence_gate 凭证随 context → settle 沉淀(案例带 evidence_bundle)
  V6 反向: 45 BLOCK → settle 0 条沉淀
  Watchdog: 对 Ticket 快照巡查,识别停滞/偏离,不改任务
  转正: shadow 裁决记录 → 误拦率 <5% → should_promote_to_hard
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.evidence_bundle import attach_evidence_gate, verify_bundle_hash  # noqa: E402
from core.gate_45_adapter import GATE_45_HARD_SWITCH, build_gate_45  # noqa: E402
from core.gate_45_stats import load_verdicts, record_verdict, should_promote_to_hard  # noqa: E402
from core.l0_foundation import L0Foundation  # noqa: E402
from core.ticket_state import create_ticket, transition_ticket  # noqa: E402
from core.watchdog import patrol  # noqa: E402

_TRACE = "tr-e2e-p2-001"


def _fake_45(verdict="PASS"):
    """in-process fake 45: submit 受理 → poll 出裁决(异步两段式语义)。"""
    calls = {"submit": 0, "poll": 0}

    def submit(ctx):
        calls["submit"] += 1
        return "EV-E2E-1"

    def poll(eval_id):
        calls["poll"] += 1
        assert eval_id == "EV-E2E-1"
        return {"status": "done", "verdict": verdict, "evidence_uri": "pg://ev/e2e-1"}

    return submit, poll, calls


def test_e2e_p2_hard_gate_pass_settles_with_evidence(tmp_path):
    submit, poll, calls = _fake_45("PASS")
    gate = build_gate_45(
        {"mode": "hard", "submit_fn": submit, "poll_fn": poll, "poll_interval_s": 0.0},
        flags={GATE_45_HARD_SWITCH: True},
    )
    gate = attach_evidence_gate(gate, ticket_id="TK-P2-1")

    # Ticket 全生命周期留痕
    ticket = create_ticket("TK-P2-1", trace_id=_TRACE)
    ticket["worker_id"] = "w-res-1"
    ticket = transition_ticket(ticket, "ended", now=1002.0)

    # settle: 凭证随 context 流入沉淀
    l0 = L0Foundation(root=str(tmp_path))
    ctx = {"intent": "event_research", "message": "研究请求", "trace_id": _TRACE}
    l0.settle({"success": True, "answer": "研究结论", "data": {"k": 1}}, ctx, gate=gate)

    case_path = tmp_path / "34-前端应用训练系统" / "l1_case_store.jsonl"
    case = json.loads(case_path.read_text(encoding="utf-8").strip().splitlines()[-1])
    # V2: trace_id 全链一致;证据包随沉淀落库
    assert case["trace_id"] == _TRACE
    bundle = case["evidence_bundle"]
    assert bundle["trace_id"] == _TRACE
    assert bundle["ticket_id"] == "TK-P2-1"
    assert bundle["eval_id"] == "EV-E2E-1"
    assert bundle["verdict"] == "PASS"
    assert bundle["evidence_uri"] == "pg://ev/e2e-1"
    assert verify_bundle_hash(bundle) is True  # WORM 完整
    assert calls["submit"] == 1 and calls["poll"] >= 1  # 真实走了两段式


def test_e2e_p2_hard_gate_block_zero_settlement(tmp_path):
    """V6: 未过 45 的产出 0 条进入沉淀。"""
    submit, poll, _ = _fake_45("BLOCK")
    gate = build_gate_45(
        {"mode": "hard", "submit_fn": submit, "poll_fn": poll, "poll_interval_s": 0.0},
        flags={GATE_45_HARD_SWITCH: True},
    )
    gate = attach_evidence_gate(gate, ticket_id="TK-P2-2")

    l0 = L0Foundation(root=str(tmp_path))
    ctx = {"intent": "event_research", "message": "m", "trace_id": _TRACE}
    l0.settle({"success": True, "answer": "a", "data": None}, ctx, gate=gate)

    case_path = tmp_path / "34-前端应用训练系统" / "l1_case_store.jsonl"
    assert not case_path.exists()  # V6: 0 条沉淀
    assert "evidence_bundle" not in ctx  # 拦截无凭证


def test_e2e_p2_switch_off_shadow_still_settles(tmp_path):
    """H2: 开关关断 → hard 配置退化为 shadow,BLOCK 也放行(字节等价 P1 行为)。"""
    submit, poll, _ = _fake_45("BLOCK")
    gate = build_gate_45(
        {"mode": "hard", "submit_fn": submit, "poll_fn": poll, "poll_interval_s": 0.0},
        flags={},  # 开关默认关
    )
    l0 = L0Foundation(root=str(tmp_path))
    l0.settle(
        {"success": True, "answer": "a", "data": None}, {"intent": "i", "message": "m"}, gate=gate
    )
    assert (tmp_path / "34-前端应用训练系统" / "l1_case_store.jsonl").exists()


def test_e2e_p2_watchdog_patrol_on_ticket_snapshot():
    """Watchdog 独立巡查: 识别停滞与偏离,不改任务。"""
    now = 10_000.0
    healthy = create_ticket("TK-H", trace_id=_TRACE)
    healthy["history"] = [{"from": "live", "to": "live", "ts": now - 10}]
    stalled = create_ticket("TK-S", trace_id=_TRACE)
    stalled["history"] = [{"from": "live", "to": "live", "ts": now - 7200}]
    drifting = create_ticket("TK-D", trace_id=_TRACE)
    drifting["history"] = [{"from": "live", "to": "live", "ts": now - 10}]
    drifting["mandate"] = {"goal": "回测洗盘反转因子"}
    drifting["current_focus"] = "修复文档索引链接"

    tickets = [healthy, stalled, drifting]
    report = patrol(tickets, now=now, stale_ttl_s=1800)

    kinds = {f["ticket_id"]: f["kind"] for f in report["findings"]}
    assert kinds == {"TK-S": "stalled_live", "TK-D": "goal_drift"}
    assert report["escalate"] is True
    # Watchdog 不改任务: 状态未被触碰
    assert all(t["state"] == "live" for t in tickets)
    assert "history" not in healthy or len(healthy["history"]) == 1


def test_e2e_p2_shadow_verdicts_feed_promote_decision(tmp_path):
    """DD4 闭环: shadow 裁决落记录 → 误拦率 <5% → 判据通过可转硬门。"""
    log = str(tmp_path / "verdicts.jsonl")
    # 20 笔 shadow: 19 PASS + 1 BLOCK(误拦率 5% → 不转正)
    for i in range(19):
        assert record_verdict(
            {
                "verdict": "PASS",
                "mode": "shadow",
                "eval_id": f"EV-{i}",
                "trace_id": _TRACE,
                "ts": i,
            },
            log,
        )
    record_verdict(
        {"verdict": "BLOCK", "mode": "shadow", "eval_id": "EV-X", "trace_id": _TRACE, "ts": 19}, log
    )
    records = load_verdicts(log)
    assert len(records) == 20
    assert should_promote_to_hard(records, threshold=0.05, min_samples=20) is False
    # 再来 1 笔 PASS → 1/21 ≈ 4.76% < 5% → 可转正
    record_verdict(
        {"verdict": "PASS", "mode": "shadow", "eval_id": "EV-19", "trace_id": _TRACE, "ts": 20}, log
    )
    assert should_promote_to_hard(load_verdicts(log), threshold=0.05, min_samples=20) is True
