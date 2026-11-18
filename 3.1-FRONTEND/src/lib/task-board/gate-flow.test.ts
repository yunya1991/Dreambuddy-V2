import { buildGatePolicy } from "./gate-policy";
import {
  addSigner,
  decideGateRun,
  fireGateTimer,
  startGateRun,
  validateGateFlow,
  type GateFacts,
  type GateFlow,
  type GateFlowNode,
} from "./gate-flow";
import type { GateSeat } from "./gate-governance";

const lead: GateSeat = {
  seat_id: "lead@example.com",
  kind: "human",
  roles: ["team_lead", "risk_reviewer"],
};
const qwen: GateSeat = {
  seat_id: "agent:qwen",
  kind: "agent",
  roles: ["risk_reviewer"],
  model_family: "qwen",
};

function dispatchPolicy() {
  const policy = buildGatePolicy("dispatch", "medium");
  return {
    ...policy,
    rejection: { ...policy.rejection, rewind_to: "none" as const },
  };
}

function baseFlow(): GateFlow {
  return {
    flow_id: "flow-1",
    version: 1,
    status: "active",
    applies_to: { task_types: ["*"], risk_levels: ["medium", "high"] },
    entry: "cond",
    nodes: [
      {
        id: "cond",
        type: "condition",
        when: { field: "risk_level", op: "eq", value: "high" },
        then: "g_high",
        else: "g_low",
      },
      { id: "g_high", type: "gate", gate: dispatchPolicy(), next: "g_acc" },
      { id: "g_low", type: "gate", gate: dispatchPolicy(), next: "g_acc" },
      {
        id: "g_acc",
        type: "gate",
        gate: buildGatePolicy("acceptance", "high"),
        next: null,
      },
    ],
    guardrails: {
      must_end_with: "acceptance",
      forbid_skip_high_risk: true,
      max_nodes: 12,
      max_gates: 5,
    },
  };
}

const mediumFacts: GateFacts = {
  risk_level: "medium",
  task_type: "research",
  change_class: "normal",
  evidence_count: 2,
};

function codes(flow: GateFlow): string[] {
  return validateGateFlow(flow)
    .filter((issue) => issue.level === "error")
    .map((issue) => issue.code);
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function mutate(fn: (flow: GateFlow) => void): GateFlow {
  const flow = clone(baseFlow());
  fn(flow);
  return flow;
}

describe("GateFlow / 12 条编译期校验", () => {
  it("合法流程无 error", () => {
    expect(codes(baseFlow())).toEqual([]);
  });

  it("1 所有路径必须终于验收门", () => {
    expect(
      codes(
        mutate((flow) => {
          const acc = flow.nodes.find((node) => node.id === "g_acc");
          if (acc?.type === "gate") acc.gate = { ...acc.gate, kind: "summary" };
        }),
      ),
    ).toContain("flow_must_end_with_acceptance");
  });

  it("2 高风险验收必须保留人工", () => {
    expect(
      codes(
        mutate((flow) => {
          const acc = flow.nodes.find((node) => node.id === "g_acc");
          if (acc?.type === "gate") {
            acc.gate = { ...acc.gate, auto_approve: true, human_required: false };
          }
        }),
      ),
    ).toContain("high_risk_requires_human_gate");
  });

  it("3 禁止环", () => {
    expect(
      codes(
        mutate((flow) => {
          const acc = flow.nodes.find((node) => node.id === "g_acc");
          if (acc?.type === "gate") acc.next = "cond";
        }),
      ),
    ).toContain("cycle_detected");
  });

  it("4 条件只能引用事实字段", () => {
    expect(
      codes(
        mutate((flow) => {
          const cond = flow.nodes.find((node) => node.id === "cond");
          if (cond?.type === "condition") {
            cond.when = { ...cond.when, field: "llm_opinion" as never };
          }
        }),
      ),
    ).toContain("condition_uses_non_fact_field");
  });

  it("5 高风险验收禁止转交", () => {
    expect(
      codes(
        mutate((flow) => {
          const acc = flow.nodes.find((node) => node.id === "g_acc");
          if (acc?.type === "gate") {
            acc.gate = {
              ...acc.gate,
              approver: { ...acc.gate.approver, allow_delegate: true },
            };
          }
        }),
      ),
    ).toContain("delegate_forbidden_on_high_acceptance");
  });

  it("6 加签必须会签", () => {
    expect(
      codes(
        mutate((flow) => {
          const node = flow.nodes.find((item) => item.id === "g_low");
          if (node?.type === "gate") {
            node.gate = {
              ...node.gate,
              approver: {
                ...node.gate.approver,
                allow_add_signer: true,
                quorum: "any",
              },
            };
          }
        }),
      ),
    ).toContain("add_signer_requires_quorum_all");
  });

  it("7 退回目标必须是祖先门", () => {
    expect(
      codes(
        mutate((flow) => {
          const acc = flow.nodes.find((node) => node.id === "g_acc");
          if (acc?.type === "gate") {
            acc.gate = {
              ...acc.gate,
              rejection: { ...acc.gate.rejection, rewind_to: "summary" },
            };
          }
        }),
      ),
    ).toContain("rewind_target_not_ancestor");
  });

  it("8 终止仅管理员", () => {
    expect(
      codes(
        mutate((flow) => {
          flow.nodes.push({
            id: "t",
            type: "terminate",
            reason: "取消",
            admin_only: false,
          } as unknown as GateFlowNode);
        }),
      ),
    ).toContain("terminate_requires_admin_only");
  });

  it("9 审批人或升级链不得为空", () => {
    expect(
      codes(
        mutate((flow) => {
          const node = flow.nodes.find((item) => item.id === "g_low");
          if (node?.type === "gate") {
            node.gate = {
              ...node.gate,
              approver: { ...node.gate.approver, roles: [] },
            };
          }
        }),
      ),
    ).toContain("approver_or_escalation_empty");
  });

  it("10 超时不得自动通过", () => {
    expect(
      codes(
        mutate((flow) => {
          flow.nodes.unshift({
            id: "timer",
            type: "timer",
            hours: 1,
            on_timeout: "auto_approve",
            next: "cond",
          } as unknown as GateFlowNode);
          flow.entry = "timer";
        }),
      ),
    ).toContain("timer_cannot_auto_approve");
  });

  it("11 抄送对象不得为空", () => {
    expect(
      codes(
        mutate((flow) => {
          flow.nodes.unshift({
            id: "cc",
            type: "cc",
            to: [],
            next: "cond",
          });
          flow.entry = "cc";
        }),
      ),
    ).toContain("cc_must_not_vote");
  });

  it("12 审批席位不得重复", () => {
    expect(
      codes(
        mutate((flow) => {
          const node = flow.nodes.find((item) => item.id === "g_low");
          if (node?.type === "gate") {
            node.gate = {
              ...node.gate,
              approver: {
                ...node.gate.approver,
                roles: ["team_lead", "team_lead"],
              },
            };
          }
        }),
      ),
    ).toContain("duplicate_approver_seat");
  });
});

describe("GateFlow / 运行时", () => {
  it("条件分支按事实选择，门不足票停在 waiting_human", () => {
    const run = startGateRun(baseFlow(), {
      taskId: "t1",
      traceId: "tr1",
      facts: mediumFacts,
      seats: [lead, qwen],
      now: 1,
    });
    expect(run.status).toBe("waiting_human");
    expect(run.node_id).toBe("g_low");
  });

  it("人和 Agent 会签通过后走到验收门并完成", () => {
    const flow = baseFlow();
    const opts = { seats: [lead, qwen], now: 2 };
    let run = startGateRun(flow, {
      taskId: "t1",
      traceId: "tr1",
      facts: mediumFacts,
      ...opts,
    });

    run = decideGateRun(
      flow,
      run,
      "g_low",
      [{ seat_id: lead.seat_id, verdict: "approved" }],
      opts,
    );
    expect(run.node_id).toBe("g_acc");

    run = decideGateRun(
      flow,
      run,
      "g_acc",
      [{ seat_id: lead.seat_id, verdict: "approved" }],
      opts,
    );
    expect(run.status).toBe("waiting_human");

    run = decideGateRun(
      flow,
      run,
      "g_acc",
      [{ seat_id: qwen.seat_id, verdict: "approved", model_family: "qwen" }],
      opts,
    );
    expect(run.status).toBe("completed");
  });

  it("驳回后退回祖先门并清空既有批准", () => {
    const flow = baseFlow();
    const opts = { seats: [lead, qwen], now: 3 };
    let run = startGateRun(flow, {
      taskId: "t1",
      traceId: "tr1",
      facts: mediumFacts,
      ...opts,
    });
    run = decideGateRun(
      flow,
      run,
      "g_low",
      [{ seat_id: lead.seat_id, verdict: "approved" }],
      opts,
    );
    run = decideGateRun(
      flow,
      run,
      "g_acc",
      [{ seat_id: lead.seat_id, verdict: "rejected" }],
      opts,
    );
    expect(run.node_id).toBe("g_low");
    expect(run.status).toBe("waiting_human");
    expect(run.approvals.g_acc).toBeUndefined();
  });

  it("抄送只记录，不计票不阻塞", () => {
    const flow = clone(baseFlow());
    flow.nodes.unshift({
      id: "cc",
      type: "cc",
      to: ["owner@example.com"],
      next: "cond",
    });
    flow.entry = "cc";
    const run = startGateRun(flow, {
      taskId: "t1",
      traceId: "tr1",
      facts: mediumFacts,
      seats: [lead, qwen],
      now: 4,
    });
    expect(run.cc).toContain("owner@example.com");
    expect(run.node_id).toBe("g_low");
  });

  it("定时器到点只推进，不自动批准", () => {
    const flow = clone(baseFlow());
    flow.nodes.unshift({
      id: "timer",
      type: "timer",
      hours: 1,
      on_timeout: "remind",
      next: "cond",
    });
    flow.entry = "timer";
    const run = startGateRun(flow, {
      taskId: "t1",
      traceId: "tr1",
      facts: mediumFacts,
      seats: [lead, qwen],
      now: 5,
    });
    expect(run.status).toBe("waiting_timer");

    const fired = fireGateTimer(flow, run, {
      seats: [lead, qwen],
      now: 6,
    });
    expect(fired.status).toBe("waiting_human");
    expect(fired.node_id).toBe("g_low");
    expect(fired.events.some((event) => event.type === "timer.fired")).toBe(true);
  });

  it("并签 all 需要所有分支完成", () => {
    const flow: GateFlow = {
      ...baseFlow(),
      entry: "p",
      nodes: [
        {
          id: "p",
          type: "parallel",
          branches: ["b1", "b2"],
          join: "all",
          next: "g_acc",
        },
        { id: "b1", type: "gate", gate: dispatchPolicy(), next: "p" },
        { id: "b2", type: "gate", gate: dispatchPolicy(), next: "p" },
        {
          id: "g_acc",
          type: "gate",
          gate: buildGatePolicy("acceptance", "high"),
          next: null,
        },
      ],
    };
    const opts = { seats: [lead, qwen], now: 7 };
    let run = startGateRun(flow, {
      taskId: "t1",
      traceId: "tr1",
      facts: mediumFacts,
      ...opts,
    });
    expect(run.node_id).toBe("b1");

    run = decideGateRun(
      flow,
      run,
      "b1",
      [{ seat_id: lead.seat_id, verdict: "approved" }],
      opts,
    );
    expect(run.node_id).toBe("b2");

    run = decideGateRun(
      flow,
      run,
      "b2",
      [{ seat_id: lead.seat_id, verdict: "approved" }],
      opts,
    );
    expect(run.node_id).toBe("g_acc");
  });

  it("或签 any 首个分支完成即进入下一节点", () => {
    const flow: GateFlow = {
      ...baseFlow(),
      entry: "p",
      nodes: [
        {
          id: "p",
          type: "parallel",
          branches: ["b1", "b2"],
          join: "any",
          next: "g_acc",
        },
        { id: "b1", type: "gate", gate: dispatchPolicy(), next: "p" },
        { id: "b2", type: "gate", gate: dispatchPolicy(), next: "p" },
        {
          id: "g_acc",
          type: "gate",
          gate: buildGatePolicy("acceptance", "high"),
          next: null,
        },
      ],
    };
    const opts = { seats: [lead, qwen], now: 8 };
    let run = startGateRun(flow, {
      taskId: "t1",
      traceId: "tr1",
      facts: mediumFacts,
      ...opts,
    });
    run = decideGateRun(
      flow,
      run,
      "b1",
      [{ seat_id: lead.seat_id, verdict: "approved" }],
      opts,
    );
    expect(run.node_id).toBe("g_acc");
  });

  it("加签使既有批准失效，必须重新计票", () => {
    const flow = baseFlow();
    const opts = { seats: [lead, qwen], now: 9 };
    let run = startGateRun(flow, {
      taskId: "t1",
      traceId: "tr1",
      facts: mediumFacts,
      ...opts,
    });
    run = decideGateRun(
      flow,
      run,
      "g_low",
      [{ seat_id: lead.seat_id, verdict: "approved" }],
      opts,
    );
    run = decideGateRun(
      flow,
      run,
      "g_acc",
      [{ seat_id: lead.seat_id, verdict: "approved" }],
      opts,
    );
    expect(run.approvals.g_acc).toHaveLength(1);

    const signed = addSigner(flow, run, "g_acc", 10);
    expect(signed.approvals.g_acc).toEqual([]);
    expect(
      signed.events.some((event) => event.type === "node.signer_added"),
    ).toBe(true);
  });

  it("终止节点直接结束，不触发验收", () => {
    const flow: GateFlow = {
      flow_id: "f",
      version: 1,
      status: "active",
      applies_to: { task_types: ["*"], risk_levels: ["low"] },
      entry: "t",
      nodes: [{ id: "t", type: "terminate", reason: "取消", admin_only: true }],
      guardrails: {
        must_end_with: "acceptance",
        forbid_skip_high_risk: true,
        max_nodes: 12,
        max_gates: 5,
      },
    };
    const run = startGateRun(flow, {
      taskId: "t1",
      traceId: "tr1",
      facts: { ...mediumFacts, risk_level: "low" },
      seats: [lead],
      now: 11,
    });
    expect(run.status).toBe("terminated");
    expect(run.terminated?.reason).toBe("取消");
  });
});
