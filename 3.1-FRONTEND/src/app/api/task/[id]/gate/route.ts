import { NextRequest, NextResponse } from "next/server";
import type {
  GateKind,
  GateStatus,
  TaskBoardEvent,
  TaskGate,
} from "@/types/task-board";
import {
  appendTaskEvents,
  pendingGates,
  readTaskBoard,
} from "@/lib/task-board/server-store";
import {
  GATE_RISK,
  resolveGatePolicy,
  type GatePolicy,
} from "@/lib/task-board/gate-policy";
import { canApprove, resolveGateRoles, type GateRole } from "@/lib/task-board/roles";
import {
  computeRewind,
  defaultGateSeats,
  resolveApprovalPlan,
  type GateSeat,
  type ProducerIdentity,
} from "@/lib/task-board/gate-governance";
import { latestVerdictL0 } from "@/lib/verdict/verdict-events";
import { checkVerdictForGate } from "@/lib/verdict/verdict-gate";
import {
  appendGateFlowEvent,
  buildGateFlowRejectionRecord,
} from "@/lib/task-board/gateflow-event-export";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const GATE_KINDS: GateKind[] = [
  "intent",
  "spec",
  "dispatch",
  "acceptance",
  "summary",
];

interface Actor {
  actorId: string;
  kind: "human" | "agent";
  seat?: GateSeat;
  roles: string[];
  bootstrap: boolean;
}

function resolveActor(request: NextRequest): Actor {
  const agentId = (request.headers.get("x-agent-id") || "").trim();
  if (agentId) {
    const seatId = agentId.startsWith("agent:") ? agentId : `agent:${agentId}`;
    const seat = defaultGateSeats().find((item) => item.seat_id === seatId);
    return {
      actorId: seatId,
      kind: "agent",
      seat,
      roles: seat?.roles ?? [],
      bootstrap: false,
    };
  }

  const email =
    request.headers.get("x-user-email") ||
    request.headers.get("x-user-id") ||
    "workspace-user";
  const resolved = resolveGateRoles(email);
  return {
    actorId: resolved.email || email,
    kind: "human",
    roles: resolved.roles,
    bootstrap: resolved.bootstrap,
  };
}

function producerOf(request: NextRequest): ProducerIdentity {
  const agentId = (request.headers.get("x-producer-agent-id") || "").trim();
  const family = (request.headers.get("x-producer-model-family") || "").trim();
  const runId = (request.headers.get("x-producer-run-id") || "").trim();
  const runAgents = (request.headers.get("x-producer-run-agents") || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  return {
    agent_id: agentId || undefined,
    model_family: family || undefined,
    run_id: runId || undefined,
    run_agent_ids: runAgents.length > 0 ? runAgents : undefined,
  };
}

/** 人走角色表；Agent 走席位表；空审批人一律阻塞，不自动通过 */
function authorize(
  policy: GatePolicy,
  actor: Actor,
  producer: ProducerIdentity,
): { ok: true } | { ok: false; status: number; body: Record<string, unknown> } {
  if (actor.kind === "agent") {
    if (!actor.seat) {
      return {
        ok: false,
        status: 403,
        body: { error: "agent_seat_unknown", agent_id: actor.actorId },
      };
    }
    const plan = resolveApprovalPlan(policy, defaultGateSeats(), producer);
    if (plan.blocked) {
      return {
        ok: false,
        status: 409,
        body: {
          error: "approval_blocked",
          reason: plan.reason,
          escalated_to: plan.escalated_to,
        },
      };
    }
    if (!plan.seats.some((seat) => seat.seat_id === actor.actorId)) {
      return {
        ok: false,
        status: 403,
        body: {
          error: "seat_not_eligible",
          required_roles: policy.approver.roles,
          reason: "sod_or_family_conflict",
        },
      };
    }
    return { ok: true };
  }

  if (!actor.bootstrap && !canApprove(actor.roles as GateRole[], policy.approver.roles)) {
    return {
      ok: false,
      status: 403,
      body: {
        error: "role_not_allowed",
        required_roles: policy.approver.roles,
        roles: actor.roles,
      },
    };
  }
  return { ok: true };
}

function gateEvent(
  taskId: string,
  traceId: string,
  now: number,
  gate: TaskGate,
): TaskBoardEvent {
  return {
    task_id: taskId,
    trace_id: traceId || taskId,
    seq: 0,
    ts: now,
    type: "gate.updated",
    payload: gate,
  };
}

/**
 * POST /api/task/[id]/gate — 确认/驳回门禁（人和 Agent 都走这里）。
 *
 * - 人类身份：x-user-email / x-user-id；
 * - Agent 身份：x-agent-id（需在 GATE_AGENT_SEATS 或默认席位中）；
 * - 生产者身份：x-producer-agent-id / x-producer-model-family（用于 SoD）；
 * - 批量确认：gate_ids + status=approved，仅限低/中风险门（做减法）；
 * - 驳回生效：按策略回退，目标门到链尾全部失效。
 */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const body = await request.json().catch(() => null);
  const status = body?.status as GateStatus | undefined;
  const comment =
    typeof body?.comment === "string" ? body.comment.trim() : undefined;
  const rewindTo =
    typeof body?.rewind_to === "string" &&
    GATE_KINDS.includes(body.rewind_to as GateKind)
      ? (body.rewind_to as GateKind)
      : undefined;

  const batch: string[] = Array.isArray(body?.gate_ids)
    ? body.gate_ids.filter((item: unknown): item is string => typeof item === "string")
    : [];
  const single = typeof body?.gate_id === "string" ? body.gate_id.trim() : "";
  const gateIds = batch.length > 0 ? batch : single ? [single] : [];

  if (gateIds.length === 0 || (status !== "approved" && status !== "rejected")) {
    return NextResponse.json(
      { success: false, error: "gate_id_and_status_required" },
      { status: 400 },
    );
  }
  if (status === "rejected" && (gateIds.length > 1 || !comment)) {
    return NextResponse.json(
      {
        success: false,
        error:
          gateIds.length > 1 ? "batch_reject_forbidden" : "reject_comment_required",
      },
      { status: 400 },
    );
  }

  const snapshot = await readTaskBoard(id);
  if (snapshot.terminated) {
    return NextResponse.json(
      { success: false, error: "task_terminated", reason: snapshot.terminated.reason },
      { status: 409 },
    );
  }

  const targets = gateIds
    .map((gateId) => snapshot.gates.find((item) => item.gate_id === gateId))
    .filter((gate): gate is NonNullable<typeof gate> => Boolean(gate));
  if (targets.length !== gateIds.length) {
    return NextResponse.json(
      { success: false, error: "gate_not_found" },
      { status: 404 },
    );
  }

  const submittedEvidence =
    typeof body?.evidence_ref === "string" ? body.evidence_ref.trim() : "";
  for (const gate of targets) {
    if (submittedEvidence && submittedEvidence !== gate.evidence_ref) {
      return NextResponse.json(
        {
          success: false,
          error: "stale_evidence",
          gate_id: gate.gate_id,
          expected: gate.evidence_ref,
          pending_gates: pendingGates(snapshot),
        },
        { status: 409 },
      );
    }
    if (
      gateIds.length > 1 &&
      (GATE_RISK[gate.kind] === "high" || GATE_RISK[gate.kind] === "critical")
    ) {
      return NextResponse.json(
        {
          success: false,
          error: "batch_high_risk_forbidden",
          gate_id: gate.gate_id,
        },
        { status: 400 },
      );
    }
  }

  const actor = resolveActor(request);
  const producer = producerOf(request);
  const policies = new Map<GateKind, GatePolicy>();
  for (const gate of targets) {
    const policy = resolveGatePolicy(gate.kind, GATE_RISK[gate.kind]);
    policies.set(gate.kind, policy);
    const auth = authorize(policy, actor, producer);
    if (!auth.ok) {
      return NextResponse.json(
        {
          success: false,
          ...auth.body,
          gate_id: gate.gate_id,
        },
        { status: auth.status },
      );
    }
  }

  // 同一当前证据版本上重复提交同一结论：幂等返回
  if (targets.every((gate) => gate.status === status)) {
    return NextResponse.json({
      success: true,
      snapshot,
      pending_gates: pendingGates(snapshot),
      idempotent: true,
    });
  }

  // 验收门消费 verdict（T1.5）：只在批准 acceptance 且 Ticket 声明级别时强制
  const requiredLevel = snapshot.objective?.required_verdict_level;
  if (
    status === "approved" &&
    requiredLevel &&
    targets.some((gate) => gate.kind === "acceptance")
  ) {
    const latest = await latestVerdictL0(id);
    const check = checkVerdictForGate({ required: requiredLevel, verdict: latest });
    if (!check.ok) {
      return NextResponse.json(
        {
          success: false,
          error: check.error,
          message: check.message,
          required_level: check.required_level,
          gate_id: "acceptance",
          verdict: check.verdict
            ? {
                verdict_id: check.verdict.verdict_id,
                level: check.verdict.level,
                verdict: check.verdict.verdict,
                confidence: check.verdict.confidence,
                created_at: check.verdict.created_at,
              }
            : null,
          pending_gates: pendingGates(snapshot),
        },
        { status: 409 },
      );
    }
  }

  const now = Date.now();
  const events: TaskBoardEvent[] = [];
  for (const gate of targets) {
    const policy = policies.get(gate.kind)!;
    const rewindTarget =
      status === "rejected"
        ? rewindTo ?? (policy.rejection.rewind_to as GateKind | "none")
        : undefined;
    events.push(
      gateEvent(id, snapshot.trace_id, now, {
        ...gate,
        status,
        evidence_ref: gate.evidence_ref,
        decided_by: actor.actorId,
        decided_at: now,
        comment,
        rewind_to:
          status === "rejected" && rewindTarget !== "none"
            ? (rewindTarget as GateKind)
            : undefined,
      }),
    );
  }

  let rewound: GateKind[] = [];
  if (status === "rejected" && targets.length === 1) {
    const gate = targets[0];
    const policy = policies.get(gate.kind)!;
    const rewindTarget = rewindTo ?? (policy.rejection.rewind_to as GateKind | "none");
    rewound = computeRewind(gate.kind, rewindTo, policy.rejection.rewind_to);

    for (const kind of rewound) {
      const target = snapshot.gates.find((item) => item.kind === kind);
      if (!target) continue;
      events.push(
        gateEvent(id, snapshot.trace_id, now, {
          ...target,
          status: "waiting",
          decided_by: "",
          decided_at: 0,
          comment: `rewind:${gate.kind}`,
          rewind_to: undefined,
          requested_at: now,
          remind_count: 0,
          reminded_at: undefined,
          escalated_at: undefined,
        }),
      );
    }

    if (rewindTarget === "none") rewound = [];
  }

  const next = await appendTaskEvents(id, events);

  // D3D Phase 2：驳回后导出 GateFlow 事件，供 Python 立案消费者幂等消费。
  // FAIL-OPEN：导出失败不阻断门禁结果，但必须在响应中可见。
  let gateflowExported: boolean | undefined;
  if (status === "rejected" && targets.length === 1) {
    const gate = targets[0];
    const policy = policies.get(gate.kind)!;
    const rejectedRewind = rewindTo ?? policy.rejection.rewind_to;
    gateflowExported = await appendGateFlowEvent(
      buildGateFlowRejectionRecord({
        taskId: id,
        traceId: snapshot.trace_id,
        runId: snapshot.flow?.run_id,
        flowId: snapshot.flow?.flow_id,
        gateId: gate.gate_id,
        gateKind: gate.kind,
        comment,
        rewindTo: rejectedRewind,
        evidenceRef: gate.evidence_ref,
        highRisk:
          GATE_RISK[gate.kind] === "high" ||
          GATE_RISK[gate.kind] === "critical",
        at: now,
      }),
    );
  }

  return NextResponse.json({
    success: true,
    snapshot: next,
    pending_gates: pendingGates(next),
    actor: { id: actor.actorId, kind: actor.kind },
    batch: gateIds.length > 1,
    rewound,
    gateflow_exported: gateflowExported,
  });
}
