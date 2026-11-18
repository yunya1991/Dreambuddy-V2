/**
 * A2 派发器单测：1 KR = 1 AgentRun、门禁阻断、能力白名单继承。
 */

import type { OkrNode } from "@/types/task-board";
import type { DispatchGateDecision } from "./okr-gate";
import {
  buildAgentDispatchEvents,
  planAgentRuns,
} from "./dispatcher";

function kr(over: Partial<OkrNode> = {}): OkrNode {
  return {
    node_id: "kr-1",
    objective: "收集证据",
    criteria: "结论引用证据",
    verify: "evidence_backed",
    evidence_id: "kr-evidence:t:kr-1",
    evidence_count: 0,
    verdict: "pending",
    owner_domain: "domain:analysis",
    owner_agent: "agent:evidence-analysis",
    capability_ids: ["analysis.data_insight", "dsh.technical"],
    ...over,
  };
}

function decision(status: "approved" | "waiting"): DispatchGateDecision {
  return {
    status,
    required: status === "waiting",
    reasons: status === "waiting" ? ["capability_gap"] : [],
    detail: status === "waiting" ? ["KR 能力域匹配存在缺口"] : [],
    validation: { ok: status === "approved", issues: [] },
  };
}

describe("planAgentRuns", () => {
  it("1 KR = 1 AgentRun，同域多 KR 角色仍然唯一", () => {
    const runs = planAgentRuns(
      [
        kr({ node_id: "kr-1" }),
        kr({ node_id: "kr-2" }),
        kr({ node_id: "kr-3", owner_domain: "domain:strategy", owner_agent: "agent:strategy-verification" }),
      ],
      { decision: decision("approved") },
    );

    expect(runs).toHaveLength(3);
    expect(new Set(runs.map((run) => run.role)).size).toBe(3);
    expect(runs[0].role).toBe("agent:evidence-analysis#kr-1");
    expect(runs.every((run) => run.state === "pending")).toBe(true);
  });

  it("门未通过时只能是 waiting，能力白名单原样继承", () => {
    const runs = planAgentRuns([kr()], { decision: decision("waiting") });
    expect(runs).toHaveLength(1);
    expect(runs[0].state).toBe("waiting");
    expect(runs[0].state).not.toBe("running");
    expect(runs[0].capability_ids).toEqual([
      "analysis.data_insight",
      "dsh.technical",
    ]);
    expect(runs[0].summary).toContain("dispatch 门未通过");
  });

  it("空 KR 列表不产生 AgentRun", () => {
    expect(planAgentRuns([], { decision: decision("approved") })).toEqual([]);
  });
});

describe("buildAgentDispatchEvents", () => {
  it("每个 AgentRun 生成一条 agent.updated 事件", () => {
    const runs = planAgentRuns([kr()], { decision: decision("approved") });
    const events = buildAgentDispatchEvents("t1", "trace1", runs, 123);
    expect(events).toHaveLength(1);
    expect(events[0].type).toBe("agent.updated");
    expect(events[0].task_id).toBe("t1");
    expect(events[0].ts).toBe(123);
  });
});
