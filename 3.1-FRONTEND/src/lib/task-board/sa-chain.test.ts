/**
 * S→A 最小闭环实跑：真实写事件流再回放，验证
 * okr.updated → gate.updated 的看板投影（不是只测纯函数）。
 */

import os from "os";
import path from "path";
import { promises as fs } from "fs";

const TMP_DIR = path.join(
  os.tmpdir(),
  `dream-sa-chain-${process.pid}-${Date.now()}`,
);
process.env.TASK_BOARD_DIR = TMP_DIR;

/* eslint-disable @typescript-eslint/no-var-requires */
const store = require("@/lib/task-board/server-store") as typeof import("@/lib/task-board/server-store");
const { decomposeTask } = require("@/lib/task-board/decompose") as typeof import("@/lib/task-board/decompose");
const {
  buildDispatchGate,
  dispatchGateEvidenceRef,
  resolveDispatchGate,
} = require("@/lib/task-board/okr-gate") as typeof import("@/lib/task-board/okr-gate");
const { buildAgentDispatchEvents, planAgentRuns } =
  require("@/lib/task-board/dispatcher") as typeof import("@/lib/task-board/dispatcher");
/* eslint-enable @typescript-eslint/no-var-requires */

afterAll(async () => {
  await fs.rm(TMP_DIR, { recursive: true, force: true });
});

describe("S→A 事件链", () => {
  it("deep 任务：okr.updated 后 dispatch 门待确认，门事件落盘后可回放为 approved", async () => {
    const taskId = `sa-ok-${Date.now()}`;
    const result = await decomposeTask(
      {
        taskId,
        text: "对比三只标的基本面并回测择时策略",
        intent: "strategy_verify",
        level: "deep",
        score: 6,
      },
      {},
      {},
    );
    expect(result.krs.length).toBeGreaterThanOrEqual(2);

    const afterOkr = await store.appendTaskEvents(taskId, [
      {
        task_id: taskId,
        trace_id: taskId,
        seq: 0,
        ts: Date.now(),
        type: "okr.updated",
        payload: { objective: result.objective, krs: result.krs },
      },
    ]);
    expect(afterOkr.stage).toBe("dispatch");
    expect(afterOkr.objective?.title).toContain("对比三只标的");
    expect(afterOkr.gates.find((gate) => gate.kind === "dispatch")?.status).toBe(
      "waiting",
    );

    const decision = resolveDispatchGate({
      objective: result.objective,
      krs: result.krs,
      level: "deep",
      score: 6,
    });
    expect(decision.status).toBe("approved");

    const okrSeq = afterOkr.cursors["okr.updated:okr"] ?? 0;
    await store.appendTaskEvents(taskId, [
      {
        task_id: taskId,
        trace_id: taskId,
        seq: 0,
        ts: Date.now(),
        type: "gate.updated",
        payload: buildDispatchGate(decision, dispatchGateEvidenceRef(okrSeq)),
      },
    ]);

    const replay = await store.readTaskBoard(taskId);
    const gate = replay.gates.find((item) => item.kind === "dispatch");
    expect(gate?.status).toBe("approved");
    expect(gate?.decided_by).toBe("system:auto");
    expect(replay.status).toBe("pending");

    // 裁决通过后按 KR 派发子 Agent（1 KR = 1 AgentRun，且不得 running）
    const runs = planAgentRuns(result.krs, { decision });
    await store.appendTaskEvents(
      taskId,
      buildAgentDispatchEvents(taskId, taskId, runs),
    );
    const dispatched = await store.readTaskBoard(taskId);
    expect(dispatched.agents).toHaveLength(result.krs.length);
    expect(dispatched.agents.every((agent) => agent.state === "pending")).toBe(true);
    expect(new Set(dispatched.agents.map((agent) => agent.role)).size).toBe(
      result.krs.length,
    );
  });

  it("高不确定性：缺证据锚点时门保持 waiting，看板状态为 waiting", async () => {
    const taskId = `sa-wait-${Date.now()}`;
    const result = await decomposeTask(
      {
        taskId,
        text: "核对当前持仓风险",
        intent: "risk_alert",
        level: "standard",
        score: 2,
      },
      {},
      {},
    );
    // 人为制造证据锚点缺失，模拟拆解产物不合规
    const krs = result.krs.map((kr) => ({ ...kr, evidence_id: undefined }));

    const afterOkr = await store.appendTaskEvents(taskId, [
      {
        task_id: taskId,
        trace_id: taskId,
        seq: 0,
        ts: Date.now(),
        type: "okr.updated",
        payload: { objective: result.objective, krs },
      },
    ]);
    const decision = resolveDispatchGate({
      objective: result.objective,
      krs,
      level: "standard",
      score: 2,
    });
    expect(decision.status).toBe("waiting");

    const okrSeq = afterOkr.cursors["okr.updated:okr"] ?? 0;
    await store.appendTaskEvents(taskId, [
      {
        task_id: taskId,
        trace_id: taskId,
        seq: 0,
        ts: Date.now(),
        type: "gate.updated",
        payload: buildDispatchGate(decision, dispatchGateEvidenceRef(okrSeq)),
      },
    ]);

    const replay = await store.readTaskBoard(taskId);
    const gate = replay.gates.find((item) => item.kind === "dispatch");
    expect(gate?.status).toBe("waiting");
    expect(gate?.comment).toContain("证据锚点");
    expect(replay.status).toBe("waiting");

    // 门未通过：子 Agent 只能是 waiting，绝不 running
    const runs = planAgentRuns(krs, { decision });
    await store.appendTaskEvents(
      taskId,
      buildAgentDispatchEvents(taskId, taskId, runs),
    );
    const dispatched = await store.readTaskBoard(taskId);
    expect(dispatched.agents.every((agent) => agent.state === "waiting")).toBe(true);
    expect(
      dispatched.agents.some((agent) => agent.state === "running"),
    ).toBe(false);
  });
});
