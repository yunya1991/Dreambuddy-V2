/**
 * 任务看板契约测试（T0）。
 *
 * 覆盖：六类事件归并、幂等回放、旧事件不覆盖、能力并集、验收回写 KR、
 * 以及 O0 span 的降级投影边界。
 */
import {
  applyTaskEvent,
  buildTaskBoard,
  emptyTaskBoard,
  type AgentRun,
  type OkrNode,
  type TaskBoardEvent,
} from "@/types/task-board";
import type { TraceSpan } from "@/types/run-trace";
import { projectFromSpans, projectTaskEvents } from "./project-events";

const META = { taskId: "bt-1", traceId: "tr-1" };
const BASE = { task_id: META.taskId, trace_id: META.traceId };

function agent(
  role: string,
  state: AgentRun["state"],
  capabilityIds: string[] = [],
): AgentRun {
  return {
    role,
    label: role,
    state,
    capability_ids: capabilityIds,
    evidence_count: 0,
  };
}

function kr(nodeId: string, verify: OkrNode["verify"] = "evidence_backed"): OkrNode {
  return {
    node_id: nodeId,
    objective: nodeId,
    criteria: `${nodeId} 判据`,
    verify,
    evidence_count: 0,
    verdict: "pending",
  };
}

const INTENT_EVENT: TaskBoardEvent = {
  ...BASE,
  type: "intent.decided",
  seq: 0,
  ts: 100,
  payload: {
    raw_input: "分析一下 BTC 最近的趋势，现在还能不能加仓？",
    gates: [
      { key: "brainstorm", label: "脑暴", hit: false },
      { key: "reverse_parse", label: "逆向解析", hit: true },
      { key: "external_collect", label: "外部采集", hit: true },
    ],
    decision: "直接生成 SPEC，无需多 Agent 辩论",
  },
};

const SPEC_EVENT: TaskBoardEvent = {
  ...BASE,
  type: "spec.updated",
  seq: 1,
  ts: 110,
  payload: {
    spec_id: "spec-1",
    version: 1,
    status: "confirmed",
    fields: [
      { key: "goal", label: "目标", value: "判断趋势方向与加仓可行性" },
      { key: "scope", label: "范围", value: "价格结构 / 资金流 / 链上 / 宏观" },
      { key: "assumption", label: "假设", value: "窗口 90 天" },
      { key: "deliverable", label: "交付", value: "结论 + 仓位建议" },
      { key: "acceptance", label: "验收", value: "每条结论带 evidence_ref" },
      { key: "dependency", label: "依赖", value: "行情 / 链上 / 宏观" },
    ],
  },
};

const OKR_EVENT: TaskBoardEvent = {
  ...BASE,
  type: "okr.updated",
  seq: 2,
  ts: 120,
  payload: {
    objective: {
      title: "给出可执行的加仓结论",
      owner: "领队",
      mode: "judge",
      confidence_threshold: 0.6,
      progress: 0.4,
    },
    krs: [kr("KR1"), kr("KR2", "gap_closed"), kr("KR3", "c_action")],
  },
};

const AGENT_EVENTS: TaskBoardEvent[] = [
  { ...BASE, type: "agent.updated", seq: 3, ts: 130, payload: agent("technical", "done") },
  { ...BASE, type: "agent.updated", seq: 4, ts: 140, payload: agent("onchain", "running") },
  { ...BASE, type: "agent.updated", seq: 5, ts: 150, payload: agent("risk", "failed") },
];

const ACCEPT_EVENTS: TaskBoardEvent[] = [
  {
    ...BASE,
    type: "acceptance.recorded",
    seq: 6,
    ts: 160,
    payload: {
      role: "technical",
      node_id: "KR1",
      verdict: "pass",
      evidence_refs: ["l1:k1", "l1:k2", "l1:k3"],
      ts: 160,
    },
  },
  {
    ...BASE,
    type: "acceptance.recorded",
    seq: 7,
    ts: 170,
    payload: {
      role: "onchain",
      node_id: "KR2",
      verdict: "pending",
      evidence_refs: ["l1:o1", "l1:o2"],
      ts: 170,
    },
  },
  {
    ...BASE,
    type: "acceptance.recorded",
    seq: 8,
    ts: 180,
    payload: {
      role: "risk",
      node_id: "KR3",
      verdict: "fail",
      reason: "缺 evidence_ref",
      evidence_refs: [],
      ts: 180,
    },
  },
];

const SUMMARY_EVENT: TaskBoardEvent = {
  ...BASE,
  type: "summary.ready",
  seq: 9,
  ts: 190,
  payload: {
    conclusion: "趋势偏多，但只满足两成加仓条件",
    key_points: ["日线未破 20 日线", "MVRV 仍处低位"],
    confidence: 0.62,
    data_quality: [{ item: "macro.gdp_yoy", status: "missing" }],
  },
};

const ALL_EVENTS: TaskBoardEvent[] = [
  INTENT_EVENT,
  SPEC_EVENT,
  OKR_EVENT,
  ...AGENT_EVENTS,
  ...ACCEPT_EVENTS,
  SUMMARY_EVENT,
];

describe("applyTaskEvent", () => {
  it("六类事件归并后覆盖看板全部状态", () => {
    const snap = buildTaskBoard(META.taskId, META.traceId, ALL_EVENTS);

    expect(snap.intent?.raw_input).toContain("BTC");
    expect(snap.intent?.gates.filter((gate) => gate.hit)).toHaveLength(2);
    expect(snap.spec?.fields).toHaveLength(6);
    expect(snap.spec?.status).toBe("confirmed");
    expect(snap.objective?.progress).toBe(0.4);
    expect(snap.krs.map((item) => item.verdict)).toEqual(["pass", "pending", "fail"]);
    expect(snap.krs[0].evidence_count).toBe(3);
    expect(snap.agents.map((item) => item.state).sort()).toEqual([
      "done",
      "failed",
      "running",
    ]);
    expect(snap.acceptance).toHaveLength(3);
    expect(snap.summary?.confidence).toBe(0.62);
    expect(snap.stage).toBe("summary");
    // 汇总已产出但交付门未确认：不能显示为 done
    expect(snap.status).toBe("waiting");
    expect(snap.gates.find((gate) => gate.kind === "summary")?.status).toBe("waiting");
    expect(snap.seq).toBe(9);
  });

  it("同一事件重复应用是幂等的", () => {
    const snap = buildTaskBoard(META.taskId, META.traceId, ALL_EVENTS);
    const again = applyTaskEvent(snap, AGENT_EVENTS[0]);
    expect(again).toBe(snap);
  });

  it("旧 seq 不覆盖新状态", () => {
    const snap = buildTaskBoard(META.taskId, META.traceId, ALL_EVENTS);
    const stale = applyTaskEvent(snap, {
      ...BASE,
      type: "agent.updated",
      seq: 2,
      ts: 1,
      payload: agent("technical", "failed"),
    });
    expect(stale).toBe(snap);
  });

  it("同一角色的多次能力调用合并能力列表", () => {
    let snap = emptyTaskBoard(META.taskId, META.traceId);
    snap = applyTaskEvent(snap, {
      ...BASE,
      type: "agent.updated",
      seq: 0,
      ts: 10,
      payload: agent("technical", "running", ["dsh.technical"]),
    });
    snap = applyTaskEvent(snap, {
      ...BASE,
      type: "agent.updated",
      seq: 1,
      ts: 20,
      payload: agent("technical", "done", ["price.kline"]),
    });
    expect(snap.agents).toHaveLength(1);
    expect(snap.agents[0].state).toBe("done");
    expect(snap.agents[0].capability_ids).toEqual(["dsh.technical", "price.kline"]);
  });

  it("验收结论回写 KR，后续复验可覆盖前值", () => {
    let snap = buildTaskBoard(META.taskId, META.traceId, [OKR_EVENT, ...ACCEPT_EVENTS]);
    expect(snap.krs.find((item) => item.node_id === "KR2")?.verdict).toBe("pending");

    snap = applyTaskEvent(snap, {
      ...BASE,
      type: "acceptance.recorded",
      seq: 10,
      ts: 200,
      payload: {
        role: "onchain",
        node_id: "KR2",
        verdict: "pass",
        evidence_refs: ["l1:o3"],
        ts: 200,
      },
    });
    expect(snap.krs.find((item) => item.node_id === "KR2")?.verdict).toBe("pass");
  });

  it("步骤随事实推进：intent → spec → dispatch → execute → accept → summary", () => {
    let snap = emptyTaskBoard(META.taskId, META.traceId);
    expect(snap.stage).toBe("intent");

    snap = applyTaskEvent(snap, SPEC_EVENT);
    expect(snap.stage).toBe("spec");

    snap = applyTaskEvent(snap, OKR_EVENT);
    expect(snap.stage).toBe("dispatch");

    snap = applyTaskEvent(snap, AGENT_EVENTS[1]);
    expect(snap.stage).toBe("execute");
    expect(snap.status).toBe("waiting");

    snap = applyTaskEvent(snap, ACCEPT_EVENTS[0]);
    expect(snap.stage).toBe("accept");

    snap = applyTaskEvent(snap, SUMMARY_EVENT);
    expect(snap.stage).toBe("summary");
    expect(snap.status).toBe("waiting");
  });

  it("串任务的事件被忽略", () => {
    const snap = emptyTaskBoard(META.taskId, META.traceId);
    const other = applyTaskEvent(snap, { ...INTENT_EVENT, task_id: "bt-2" });
    expect(other).toBe(snap);
  });
});

describe("projectTaskEvents（O0 span 降级投影）", () => {
  const spans: TraceSpan[] = [
    {
      span_id: "sp0",
      trace_id: META.traceId,
      stage: "S1",
      label: "意图识别",
      status: "done",
      started_at: 1,
      seq: 0,
    },
    {
      span_id: "sp1",
      trace_id: META.traceId,
      stage: "C2",
      label: "行情结构",
      role: "technical",
      capability_id: "dsh.technical",
      status: "running",
      started_at: 2,
      seq: 1,
    },
    {
      span_id: "sp1",
      trace_id: META.traceId,
      stage: "C2",
      label: "行情结构",
      role: "technical",
      capability_id: "dsh.technical",
      status: "done",
      started_at: 2,
      seq: 1,
      duration_ms: 900,
      summary: "日线多头排列",
    },
    {
      span_id: "sp2",
      trace_id: META.traceId,
      stage: "A1",
      label: "证据完整性",
      role: "okr_verifier",
      status: "failed",
      started_at: 3,
      seq: 2,
      summary: "缺 evidence_ref",
    },
    {
      span_id: "sp3",
      trace_id: META.traceId,
      stage: "G1",
      label: "汇总输出",
      status: "done",
      started_at: 4,
      seq: 3,
      summary: "趋势偏多，条件不足",
    },
  ];

  it("只投影 C2 / A1 / G1，且 running 被终态覆盖", () => {
    const events = projectTaskEvents(META, spans);
    expect(events.map((event) => event.type)).toEqual([
      "agent.updated",
      "acceptance.recorded",
      "summary.ready",
    ]);

    const snap = projectFromSpans(META, spans);
    expect(snap.agents).toHaveLength(1);
    expect(snap.agents[0].state).toBe("done");
    expect(snap.agents[0].duration_ms).toBe(900);
    expect(snap.krs[0]?.verdict).toBeUndefined();
    expect(snap.stage).toBe("summary");
    // 降级投影出的汇总同样需要人工交付确认
    expect(snap.status).toBe("waiting");
  });

  it("G1 没有摘要时不点亮汇总，也不编造置信度", () => {
    const quiet = spans.filter((span) => span.span_id !== "sp3");
    const snap = projectFromSpans(META, [
      ...quiet,
      {
        span_id: "sp4",
        trace_id: META.traceId,
        stage: "G1",
        label: "汇总输出",
        status: "done",
        started_at: 5,
        seq: 4,
      },
    ]);
    expect(snap.summary).toBeUndefined();
    expect(snap.stage).not.toBe("summary");
  });

  it("无法从 span 推导的字段保持为空，不伪造", () => {
    const snap = projectFromSpans(META, spans);
    expect(snap.intent).toBeUndefined();
    expect(snap.spec).toBeUndefined();
    expect(snap.objective).toBeUndefined();
    expect(snap.krs).toHaveLength(0);
  });
});
