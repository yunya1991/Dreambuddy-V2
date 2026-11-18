# -*- coding: utf-8 -*-
"""Watchdog 独立巡查(T-DSH-P2 P2-4)。

依据: DESIGN-DSH-ARCH-UPGRADE v0.2 P2·验收(Watchdog 独立巡查;退出判据:
Watchdog 能识别偏离目标) + 职责边界(Watchdog 不改任务,只产巡查结论并
升级给人或 Router) + 风险 U3(长尾 Ticket 堆积) + ADR-7(trace_id 观测主轴)。

定位: 纯函数只读巡查。输入 Ticket 快照(来自 L0 单一事实源,ADR-2),
输出巡查报告;不持有状态、不修改 Ticket、不直接执行动作——发现经
escalate 标记交给人或 Router 处置。

发现类型:
  stalled_live:   live 但最近活动超过 stale_ttl(进展停滞)
  long_paused:    paused/waitsForPerson 超过 paused_ttl(长尾堆积 U3)
  missing_trace:  缺 trace_id(观测链断裂,ADR-7)
  goal_drift:     mandate.goal 与 current_focus 词集零交集(偏离目标)
  missing_evidence: 验收阶段 U2/U3 却无证据引用
  metric_drift:   当前指标相对基线漂移超过阈值
  unauthorized_access: 尝试调用了未授权工具/能力

硬约束: FAIL-OPEN(坏输入/坏元素不炸);不得修改 tickets(只读)。
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

_FINDING_KINDS = (
    "stalled_live",
    "long_paused",
    "missing_trace",
    "goal_drift",
    "missing_evidence",
    "metric_drift",
    "unauthorized_access",
)
_WATCHED_STATES = ("live", "paused", "waitsForPerson")
_VERDICT_LEVELS_NEED_EVIDENCE = ("U2", "U3")


def _last_activity_ts(ticket: Dict[str, Any]) -> Optional[float]:
    """最近活动时间 = history 中最大 ts;无 history → None(无法判定,跳过)。"""
    history = ticket.get("history")
    if not isinstance(history, list) or not history:
        return None
    ts_values = [h.get("ts") for h in history if isinstance(h, dict)]
    ts_values = [t for t in ts_values if isinstance(t, (int, float))]
    return max(ts_values) if ts_values else None


def _token_set(text: Any) -> set:
    """词集(中文按 bigram,英文按词)用于零交集偏离判定。"""
    if not isinstance(text, str) or not text.strip():
        return set()
    tokens = set()
    for word in text.lower().split():
        if any("一" <= ch <= "鿿" for ch in word):
            tokens.update(word[i : i + 2] for i in range(len(word) - 1))
        else:
            tokens.add(word)
    return tokens


def _required_level(ticket: Dict[str, Any]) -> Optional[str]:
    level = ticket.get("required_verdict_level")
    if not level and isinstance(ticket.get("objective"), dict):
        level = ticket["objective"].get("required_verdict_level")
    return level if level in ("U0", "U1", "U2", "U3") else None


def _at_acceptance(ticket: Dict[str, Any]) -> bool:
    return ticket.get("at_acceptance") is True or ticket.get("gate") == "acceptance"


def _metric_drift(ticket: Dict[str, Any], threshold: float) -> List[Dict[str, Any]]:
    current = ticket.get("metrics")
    baseline = ticket.get("baseline_metrics")
    if not isinstance(current, dict) or not isinstance(baseline, dict):
        return []
    out = []
    for key, cur in current.items():
        base = baseline.get(key)
        if not isinstance(cur, (int, float)) or not isinstance(base, (int, float)):
            continue
        if base == 0:
            continue
        ratio = abs(float(cur) - float(base)) / abs(float(base))
        if ratio > threshold:
            out.append(
                {
                    "metric": str(key),
                    "baseline": float(base),
                    "current": float(cur),
                    "drift_ratio": round(ratio, 4),
                }
            )
    return out


def _unauthorized(ticket: Dict[str, Any]) -> List[str]:
    mandate = ticket.get("mandate") if isinstance(ticket.get("mandate"), dict) else {}
    allowed_tools = set(mandate.get("allowed_tools") or ticket.get("allowed_tools") or [])
    attempted_tools = ticket.get("attempted_tools") or []
    bad_tools = [str(t) for t in attempted_tools if str(t) not in allowed_tools]

    granted_caps = set(ticket.get("granted_capabilities") or [])
    attempted_caps = ticket.get("attempted_capabilities") or []
    bad_caps = [str(c) for c in attempted_caps if str(c) not in granted_caps]
    return bad_tools + bad_caps


def patrol(
    tickets: Any,
    now: Optional[float] = None,
    stale_ttl_s: float = 1800.0,
    paused_ttl_s: float = 3600.0,
    metric_drift_threshold: float = 0.3,
) -> Dict[str, Any]:
    """巡查 Ticket 快照,产出报告(只读,不改任务)。

    坏输入 → {ok: False, findings: [], degraded: True}(FAIL-OPEN)。
    """
    try:
        if not isinstance(tickets, list):
            return {"ok": False, "findings": [], "stats": {}, "escalate": False, "degraded": True}
        now_ts = float(now) if now is not None else time.time()
        findings: List[Dict[str, Any]] = []
        stats: Dict[str, int] = {
            "total": 0,
            "live": 0,
            "paused": 0,
            "waitsForPerson": 0,
            "ended": 0,
        }

        for ticket in tickets:
            if not isinstance(ticket, dict):
                continue  # 坏元素跳过(FAIL-OPEN)
            stats["total"] += 1
            state = ticket.get("state")
            if state in stats:
                stats[state] += 1
            if state not in _WATCHED_STATES:
                continue  # ended 等终态不参与巡查
            tid = ticket.get("ticket_id")

            if not ticket.get("trace_id"):
                findings.append(
                    {"ticket_id": tid, "kind": "missing_trace", "detail": "缺 trace_id,观测链断裂"}
                )

            last_ts = _last_activity_ts(ticket)
            if state == "live":
                if last_ts is not None and now_ts - last_ts > float(stale_ttl_s):
                    findings.append(
                        {
                            "ticket_id": tid,
                            "kind": "stalled_live",
                            "detail": f"live 停滞 {now_ts - last_ts:.0f}s > stale_ttl {stale_ttl_s:.0f}s",
                        }
                    )
            else:  # paused / waitsForPerson
                if last_ts is not None and now_ts - last_ts > float(paused_ttl_s):
                    findings.append(
                        {
                            "ticket_id": tid,
                            "kind": "long_paused",
                            "detail": f"{state} 超 {paused_ttl_s:.0f}s(长尾堆积 U3)",
                        }
                    )

            mandate = ticket.get("mandate")
            focus = ticket.get("current_focus")
            if isinstance(mandate, dict) and mandate.get("goal") and focus:
                goal_tokens = _token_set(mandate.get("goal"))
                focus_tokens = _token_set(focus)
                if goal_tokens and focus_tokens and not (goal_tokens & focus_tokens):
                    findings.append(
                        {
                            "ticket_id": tid,
                            "kind": "goal_drift",
                            "detail": "current_focus 与 mandate.goal 词集零交集(偏离目标)",
                        }
                    )

            # 证据缺失:只在验收阶段检查,避免执行中期误报
            level = _required_level(ticket)
            if level in _VERDICT_LEVELS_NEED_EVIDENCE and _at_acceptance(ticket):
                refs = ticket.get("evidence_refs")
                if not refs and isinstance(ticket.get("objective"), dict):
                    refs = ticket["objective"].get("evidence_refs")
                if not refs:
                    findings.append(
                        {
                            "ticket_id": tid,
                            "kind": "missing_evidence",
                            "detail": f"验收要求 {level},但未提供证据引用",
                        }
                    )

            for drift in _metric_drift(ticket, float(metric_drift_threshold)):
                findings.append(
                    {
                        "ticket_id": tid,
                        "kind": "metric_drift",
                        "detail": (
                            f"{drift['metric']} 从 {drift['baseline']} 漂移到 "
                            f"{drift['current']}({drift['drift_ratio']:.0%})"
                        ),
                        **drift,
                    }
                )

            bad_access = _unauthorized(ticket)
            if bad_access:
                findings.append(
                    {
                        "ticket_id": tid,
                        "kind": "unauthorized_access",
                        "detail": f"未授权调用: {', '.join(bad_access)}",
                        "resources": bad_access,
                    }
                )

        return {
            "ok": True,
            "findings": findings,
            "stats": stats,
            "escalate": bool(findings),  # 有发现 → 升级给人/Router;本模块不动作
        }
    except Exception:
        return {"ok": False, "findings": [], "stats": {}, "escalate": False, "degraded": True}
