# -*- coding: utf-8 -*-
"""H3: ExecutionTrace v2 影子字段 + 命令信封 join（P0 / shadow）

对齐 56/SPEC-56-H v0.3 §4.3 / §5.1:
  - v1.0 span 顶层不变，新 ID 只写 `attrs["hcp.*"]`
  - 命令信封必须携带同一 trace_id / session_id（由 hcp.trace.shadow 开关控制）
  - 缺失 session_id 时不得伪造
  - join 口径：强关联（case/trace/tool_call 任一相同）计入分子；
    仅 session_id 相同且时间差 ≤60s 为弱关联，不计入分子
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "1-ARCHITECTURE"))

from core.hcp_trace import (  # noqa: E402
    HCP_FLAG,
    attach_hcp,
    build_span,
    classify_join,
    hcp_attrs,
)
from core.shell_handles import ShellHandleManager  # noqa: E402
from core.worker_tool_call import call_worker_tool  # noqa: E402

SPAN_SCHEMA = REPO_ROOT / "56-L2架构能力聚合层" / "contracts" / "span.schema.json"

TRACE_ID = "tr-20261117-001"
RUN_ID = "run-20261117-001"
SESSION_ID = "sess-20261117-001"


class FakeShell:
    def call(self, tool, args=None):
        return {"ok": True, "data": {"tool": tool}}

    def close(self):
        pass


def _manager():
    return ShellHandleManager(
        launcher=lambda spec: FakeShell(), flags={"enable_shell_handles": True}
    )


def _attrs_session(span):
    return (span.get("attrs") or {}).get("hcp.session_id")


# ── span 影子字段 ───────────────────────────────────


def test_span_with_hcp_attrs_matches_v1_contract():
    span = build_span(
        trace_id=TRACE_ID,
        run_id=RUN_ID,
        name="capability.route",
        segment="capability",
        started_at="2026-11-17T10:00:00+00:00",
        ended_at="2026-11-17T10:00:01+00:00",
        context_hash="sha256:" + "a" * 64,
        model_id="qwen-max",
        tokens_in=120,
        tokens_out=80,
        cost_cu=0.02,
        stop_reason="done",
        session_id=SESSION_ID,
        tool_call_id="tc-001",
        interaction_case_id="case-001",
    )

    schema = json.loads(SPAN_SCHEMA.read_text(encoding="utf-8"))
    from jsonschema import Draft202012Validator

    errors = list(Draft202012Validator(schema).iter_errors(span))
    assert not errors, [e.message for e in errors]

    assert _attrs_session(span) == SESSION_ID
    assert span["attrs"]["hcp.tool_call_id"] == "tc-001"
    assert span["attrs"]["hcp.interaction_case_id"] == "case-001"
    # v1.0 顶层字段不得新增
    for key in ("session_id", "tool_call_id", "interaction_case_id"):
        assert key not in span


def test_missing_session_id_is_not_fabricated():
    attrs = hcp_attrs(session_id=None, tool_call_id="tc-001")
    assert "hcp.session_id" not in attrs
    assert attrs["hcp.tool_call_id"] == "tc-001"

    span = build_span(
        trace_id=TRACE_ID,
        run_id=RUN_ID,
        name="capability.route",
        segment="capability",
        started_at="2026-11-17T10:00:00+00:00",
        ended_at="2026-11-17T10:00:01+00:00",
        context_hash="sha256:" + "b" * 64,
    )
    assert span["trace_id"] == TRACE_ID
    assert "hcp.session_id" not in (span.get("attrs") or {})


def test_attach_hcp_keeps_existing_attrs():
    span = {"attrs": {"step": 1}}
    out = attach_hcp(span, session_id=SESSION_ID)
    assert out["attrs"] == {"step": 1, "hcp.session_id": SESSION_ID}
    assert span["attrs"] == {"step": 1}  # 不原地修改


def test_model_none_with_tokens_rejected():
    with pytest.raises(ValueError):
        build_span(
            trace_id=TRACE_ID,
            run_id=RUN_ID,
            name="capability.route",
            segment="capability",
            started_at="2026-11-17T10:00:00+00:00",
            ended_at="2026-11-17T10:00:01+00:00",
            context_hash="sha256:" + "c" * 64,
            model_id="none",
            tokens_in=1,
        )


# ── 命令信封 ────────────────────────────────────────


def test_command_envelope_carries_trace_and_session():
    flags = {"enable_worker_tool_call": True, HCP_FLAG: True}
    result = call_worker_tool(
        "research",
        "recall",
        checker=lambda role, tool: True,
        manager=_manager(),
        flags=flags,
        trace_id=TRACE_ID,
        session_id=SESSION_ID,
        tool_call_id="tc-001",
    )

    assert result["ok"] is True
    assert result["meta"]["trace_id"] == TRACE_ID
    assert result["meta"]["session_id"] == SESSION_ID
    assert result["meta"]["tool_call_id"] == "tc-001"


def test_command_envelope_shadow_off_keeps_old_behavior():
    flags = {"enable_worker_tool_call": True}
    result = call_worker_tool(
        "research",
        "recall",
        checker=lambda role, tool: True,
        manager=_manager(),
        flags=flags,
        trace_id=TRACE_ID,
        session_id=SESSION_ID,
    )

    assert result["meta"]["trace_id"] == TRACE_ID
    assert "session_id" not in result["meta"]


def test_command_envelope_without_session_does_not_fabricate():
    flags = {"enable_worker_tool_call": True, HCP_FLAG: True}
    result = call_worker_tool(
        "research",
        "recall",
        checker=lambda role, tool: True,
        manager=_manager(),
        flags=flags,
        trace_id=TRACE_ID,
    )

    assert result["meta"]["trace_id"] == TRACE_ID
    assert "session_id" not in result["meta"]


# ── join 口径 ───────────────────────────────────────


def _case(**overrides):
    case = {
        "interaction_case_id": "case-001",
        "session_id": SESSION_ID,
        "ended_at": "2026-11-17T10:00:30+00:00",
        "links": {"trace_id": TRACE_ID},
        "tool_call_id": "tc-001",
    }
    case.update(overrides)
    return case


def _span(**ids):
    return {
        "trace_id": ids.get("trace_id"),
        "attrs": {
            k: v
            for k, v in {
                "hcp.session_id": ids.get("session_id"),
                "hcp.tool_call_id": ids.get("tool_call_id"),
                "hcp.interaction_case_id": ids.get("interaction_case_id"),
            }.items()
            if v
        },
        "ended_at": ids.get("ended_at", "2026-11-17T10:00:10+00:00"),
    }


def test_join_strong_by_trace_id():
    verdict = classify_join(_case(), [_span(trace_id=TRACE_ID)])
    assert verdict["eligible"] is True
    assert verdict["strong"] is True
    assert verdict["weak"] is False
    assert "trace_id" in verdict["basis"]


def test_join_strong_by_interaction_case_id():
    verdict = classify_join(_case(links={}), [_span(interaction_case_id="case-001")])
    assert verdict["strong"] is True
    assert "interaction_case_id" in verdict["basis"]


def test_join_strong_by_tool_call_id():
    verdict = classify_join(_case(links={}), [_span(tool_call_id="tc-001")])
    assert verdict["strong"] is True
    assert "tool_call_id" in verdict["basis"]


def test_join_weak_session_within_60s_not_counted():
    verdict = classify_join(
        _case(links={}, tool_call_id=None),
        [_span(session_id=SESSION_ID, ended_at="2026-11-17T10:01:20+00:00")],
    )
    assert verdict["strong"] is False
    assert verdict["weak"] is True
    assert "session_id_window" in verdict["basis"]


def test_join_weak_outside_window_rejected():
    verdict = classify_join(
        _case(links={}, tool_call_id=None),
        [_span(session_id=SESSION_ID, ended_at="2026-11-17T10:05:00+00:00")],
    )
    assert verdict["strong"] is False
    assert verdict["weak"] is False


def test_join_case_without_session_not_eligible():
    verdict = classify_join(_case(session_id="", links={}), [_span(trace_id=TRACE_ID)])
    assert verdict["eligible"] is False
