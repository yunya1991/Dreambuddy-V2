import {
  buildTaskBoard,
  emptyTaskBoard,
  type GateKind,
  type TaskBoardEvent,
  type TaskGate,
} from "@/types/task-board";
import { buildGatePolicy } from "./gate-policy";
import {
  canSeatApprove,
  computeRewind,
  defaultGateSeats,
  evaluateGateSla,
  resolveApprovalPlan,
  tallySeatVotes,
  type GateSeat,
} from "./gate-governance";

const teamLead = buildGatePolicy("dispatch", "medium");
const acceptance = buildGatePolicy("acceptance", "high");
const acceptancePolicy = {
  ...acceptance,
  approver: {
    ...acceptance.approver,
    roles: ["risk_reviewer", "team_lead"],
    quorum: "all" as const,
    min_distinct: 2,
  },
};

function waitingGate(kind: GateKind, requestedAt?: number): TaskGate {
  return {
    gate_id: kind,
    kind,
    title: kind,
    status: "waiting",
    required: true,
    evidence_ref: `${kind}:1`,
    requested_at: requestedAt,
  };
}

describe("gate-governance / Agent 席位", () => {
  it("Agent 可持有席位投票，但不能批准自己 / 同 run 的产出", () => {
    const judge = defaultGateSeats().find(
      (seat) => seat.seat_id === "agent:judge",
    )!;
    expect(canSeatApprove(judge, teamLead)).toBe(true);
    expect(canSeatApprove(judge, teamLead, { agent_id: "judge" })).toBe(false);
    expect(
      canSeatApprove(judge, teamLead, { run_agent_ids: ["judge"] }),
    ).toBe(false);
  });

  it("生产模型与 Agent 席位同家族时禁止会签", () => {
    const qwen = defaultGateSeats().find(
      (seat) => seat.seat_id === "agent:gate-qwen",
    )!;
    expect(
      canSeatApprove(qwen, acceptancePolicy, { model_family: "qwen" }),
    ).toBe(false);
    expect(
      canSeatApprove(qwen, acceptancePolicy, { model_family: "deepseek" }),
    ).toBe(true);
  });

  it("空审批人升级并阻塞，绝不自动通过", () => {
    const plan = resolveApprovalPlan(teamLead, []);
    expect(plan.blocked).toBe(true);
    expect(plan.reason).toBe("empty_approver");
    expect(plan.escalated_to).toEqual(["team_lead"]);
    expect(
      tallySeatVotes(
        [{ seat_id: "anyone", verdict: "approved" }],
        plan,
        "any",
      ).approved,
    ).toBe(false);
  });

  it("高风险验收没有人类责任人时阻塞", () => {
    const agentsOnly: GateSeat[] = [
      {
        seat_id: "agent:qwen",
        kind: "agent",
        roles: ["risk_reviewer"],
        model_family: "qwen",
      },
      {
        seat_id: "agent:jev",
        kind: "agent",
        roles: ["risk_reviewer"],
        model_family: "typesafe",
      },
    ];
    expect(resolveApprovalPlan(acceptancePolicy, agentsOnly).reason).toBe(
      "human_chair_required",
    );

    const withHuman: GateSeat[] = [
      ...agentsOnly,
      {
        seat_id: "risk@example.com",
        kind: "human",
        roles: ["risk_reviewer"],
      },
    ];
    expect(resolveApprovalPlan(acceptancePolicy, withHuman).blocked).toBe(
      false,
    );
  });

  it("同模型家族多实例只计 1 票", () => {
    const plan = resolveApprovalPlan(teamLead, [
      { seat_id: "agent:a", kind: "agent", roles: ["team_lead"], model_family: "qwen" },
      { seat_id: "agent:b", kind: "agent", roles: ["team_lead"], model_family: "qwen" },
    ]);
    const tally = tallySeatVotes(
      [
        { seat_id: "agent:a", verdict: "approved", model_family: "qwen" },
        { seat_id: "agent:b", verdict: "approved", model_family: "qwen" },
      ],
      plan,
      "all",
    );
    expect(tally.approved_seats).toBe(1);
    expect(tally.approved).toBe(false);
  });
});

describe("gate-governance / 超时与退回", () => {
  const now = 10_000_000;

  it("超时只提醒/升级，不自动通过", () => {
    const policy = buildGatePolicy("acceptance", "high");
    const gate = waitingGate(
      "acceptance",
      now - (policy.sla.minutes + 1) * 60_000,
    );
    const actions = evaluateGateSla([gate], () => policy, now);
    expect(actions.map((item) => item.type)).toEqual(["gate.reminded"]);

    const late = waitingGate(
      "acceptance",
      now - (policy.escalation.after_minutes + 1) * 60_000,
    );
    const escalated = evaluateGateSla([late], () => policy, now);
    expect(escalated.map((item) => item.type)).toEqual([
      "gate.reminded",
      "gate.escalated",
    ]);
    expect(gate.status).toBe("waiting");
  });

  it("已提醒后不重复催办", () => {
    const policy = buildGatePolicy("summary", "low");
    const gate = {
      ...waitingGate("summary", now - 999 * 60_000),
      remind_count: policy.sla.remind_max_times,
      reminded_at: now - 1,
    };
    const actions = evaluateGateSla([gate], () => policy, now);
    expect(actions.some((item) => item.type === "gate.reminded")).toBe(false);
  });

  it("退回使目标门与下游全部失效", () => {
    expect(computeRewind("acceptance", undefined, "dispatch")).toEqual([
      "dispatch",
      "summary",
    ]);
    expect(computeRewind("spec", "intent", "spec")).toEqual([
      "intent",
      "dispatch",
      "acceptance",
      "summary",
    ]);
    expect(computeRewind("intent", "none", "none")).toEqual([]);
  });
});

describe("gate-governance / 事件回放", () => {
  const taskId = "task-1";

  function event(
    seq: number,
    ts: number,
    payload: TaskBoardEvent["payload"],
    type: TaskBoardEvent["type"] = "gate.updated",
  ): TaskBoardEvent {
    return { task_id: taskId, trace_id: "trace-1", seq, ts, type, payload } as TaskBoardEvent;
  }

  it("退回后上游门回到 waiting，下游确认失效", () => {
    const snapshot = buildTaskBoard(taskId, "trace-1", [
      event(
        0,
        1,
        { spec_id: "s1", version: 1, status: "confirmed", fields: [] },
        "spec.updated",
      ),
      event(1, 2, { ...waitingGate("spec"), status: "approved", decided_by: "qa@x" }),
      event(2, 3, {
        ...waitingGate("spec"),
        status: "rejected",
        decided_by: "qa@x",
        comment: "证据不足",
        rewind_to: "spec",
      }),
      event(3, 4, { ...waitingGate("spec"), status: "waiting", requested_at: 4 }),
    ]);

    const spec = snapshot.gates.find((gate) => gate.kind === "spec")!;
    expect(spec.status).toBe("waiting");
    expect(spec.decided_by).toBeUndefined();
  });

  it("终止后任务状态为 terminated，且不再有待办门禁", () => {
    const base = emptyTaskBoard(taskId, "trace-1");
    const snapshot = buildTaskBoard(taskId, "trace-1", [
      {
        task_id: taskId,
        trace_id: "trace-1",
        seq: 0,
        ts: 1,
        type: "task.terminated",
        payload: { reason: "范围取消", by: "admin@x", at: 1 },
      },
    ]);
    expect(snapshot.status).toBe("terminated");
    expect(snapshot.terminated?.reason).toBe("范围取消");
    expect(base.terminated).toBeUndefined();
  });
});
