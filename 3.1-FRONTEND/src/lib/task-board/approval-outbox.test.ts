import { promises as fs } from "fs";
import * as os from "os";
import * as path from "path";
import type { TaskBoardSnapshot } from "@/types/task-board";

jest.mock("@/lib/task-board/server-store", () => ({
  readTaskBoard: jest.fn(),
  appendTaskEvents: jest.fn(),
}));
jest.mock("@/lib/verdict/verdict-events", () => ({
  latestVerdictL0: jest.fn(),
}));

import { appendTaskEvents, readTaskBoard } from "@/lib/task-board/server-store";
import { latestVerdictL0 } from "@/lib/verdict/verdict-events";
import {
  processApprovalOutbox,
  readApprovalOutboxStatus,
  type ApprovalOutboxEvent,
} from "./approval-outbox";

const readBoard = readTaskBoard as jest.Mock;
const appendEvents = appendTaskEvents as jest.Mock;
const latestVerdict = latestVerdictL0 as jest.Mock;

function snapshot(overrides: Partial<TaskBoardSnapshot> = {}): TaskBoardSnapshot {
  return {
    task_id: "TK-1",
    trace_id: "tr-1",
    status: "running",
    stage: "accept",
    krs: [],
    agents: [],
    acceptance: [],
    gates: [
      {
        gate_id: "G-1",
        kind: "acceptance",
        title: "验收确认",
        status: "waiting",
        required: true,
        evidence_ref: "spec:v1",
      },
    ],
    cursors: {},
    seq: 0,
    updated_at: 0,
    ...overrides,
  };
}

function granted(overrides: Partial<ApprovalOutboxEvent> = {}): ApprovalOutboxEvent {
  return {
    type: "approval.granted",
    request_id: "AR-1",
    grant_id: "AG-1",
    grant_hash: "sha256:abc",
    subject: "feishu:u-approver",
    task_id: "TK-1",
    gate_id: "G-1",
    gate_kind: "acceptance",
    ...overrides,
  };
}

async function setup(events: Array<ApprovalOutboxEvent | string>) {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "approval-outbox-"));
  const outboxPath = path.join(dir, "approval_outbox.jsonl");
  const statePath = path.join(dir, "approval_outbox_state.json");
  const body = events
    .map((event) => (typeof event === "string" ? event : JSON.stringify(event)))
    .join("\n");
  await fs.writeFile(outboxPath, `${body}\n`, "utf-8");
  return { dir, outboxPath, statePath };
}

beforeEach(() => {
  readBoard.mockReset();
  appendEvents.mockReset();
  latestVerdict.mockReset();
  latestVerdict.mockResolvedValue(null);
  readBoard.mockResolvedValue(snapshot());
  appendEvents.mockImplementation(async (_taskId: string) => snapshot());
});

test("applies approval.granted to gate.updated and is idempotent", async () => {
  const { outboxPath, statePath } = await setup([granted()]);

  const first = await processApprovalOutbox({ outboxPath, statePath, now: 1000 });
  expect(first.ok).toBe(true);
  expect(first.applied).toBe(1);
  expect(first.failed).toBe(0);

  expect(appendEvents).toHaveBeenCalledTimes(1);
  const [taskId, events] = appendEvents.mock.calls[0];
  expect(taskId).toBe("TK-1");
  expect(events[0].type).toBe("gate.updated");
  expect(events[0].payload.status).toBe("approved");
  expect(events[0].payload.decided_by).toBe("feishu:u-approver");
  expect(events[0].payload.comment).toBe("approval.granted:AG-1");

  // 同一事件再次追加：游标读到新行，但 applied key 已存在 → 不重复推进
  await fs.appendFile(outboxPath, `${JSON.stringify(granted())}\n`, "utf-8");
  const second = await processApprovalOutbox({ outboxPath, statePath, now: 2000 });
  expect(second.applied).toBe(0);
  expect(second.duplicates).toBe(1);
  expect(appendEvents).toHaveBeenCalledTimes(1);
});

test("skips events without task_id or gate_id and advances cursor", async () => {
  const { outboxPath, statePath } = await setup([
    granted({ task_id: "", gate_id: "" }),
  ]);

  const result = await processApprovalOutbox({ outboxPath, statePath, now: 1000 });
  expect(result.applied).toBe(0);
  expect(result.skipped).toBe(1);
  expect(result.details[0].reason).toBe("missing_task_or_gate");
  expect(appendEvents).not.toHaveBeenCalled();

  const status = await readApprovalOutboxStatus({ outboxPath, statePath });
  expect(status.cursor).toBe(1);
});

test("ignores non approval.granted and bad json without blocking", async () => {
  const { outboxPath, statePath } = await setup([
    { type: "approval.rejected", request_id: "AR-X" },
    "not-json",
    granted(),
  ]);

  const result = await processApprovalOutbox({ outboxPath, statePath, now: 1000 });
  expect(result.scanned).toBe(1);
  expect(result.applied).toBe(1);
  expect(result.skipped).toBe(1);
  expect(appendEvents).toHaveBeenCalledTimes(1);
});

test("duplicates when gate is already approved", async () => {
  const { outboxPath, statePath } = await setup([granted()]);
  readBoard.mockResolvedValue(
    snapshot({
      gates: [
        {
          gate_id: "G-1",
          kind: "acceptance",
          title: "验收确认",
          status: "approved",
          required: true,
          evidence_ref: "spec:v1",
        },
      ],
    }),
  );

  const result = await processApprovalOutbox({ outboxPath, statePath, now: 1000 });
  expect(result.duplicates).toBe(1);
  expect(result.details[0].reason).toBe("gate_already_approved");
  expect(appendEvents).not.toHaveBeenCalled();
});

test("skips gate_not_found and kind mismatch", async () => {
  const notFound = await setup([granted({ gate_id: "G-404" })]);
  const first = await processApprovalOutbox({
    outboxPath: notFound.outboxPath,
    statePath: notFound.statePath,
    now: 1000,
  });
  expect(first.skipped).toBe(1);
  expect(first.details[0].reason).toBe("gate_not_found");

  const mismatch = await setup([granted({ gate_kind: "dispatch" })]);
  const second = await processApprovalOutbox({
    outboxPath: mismatch.outboxPath,
    statePath: mismatch.statePath,
    now: 1000,
  });
  expect(second.skipped).toBe(1);
  expect(second.details[0].reason).toContain("gate_kind_mismatch");
  expect(appendEvents).not.toHaveBeenCalled();
});

test("does not advance cursor when apply fails, so next run retries", async () => {
  const { outboxPath, statePath } = await setup([granted()]);
  appendEvents.mockRejectedValueOnce(new Error("disk full"));

  const first = await processApprovalOutbox({ outboxPath, statePath, now: 1000 });
  expect(first.ok).toBe(false);
  expect(first.failed).toBe(1);
  const status = await readApprovalOutboxStatus({ outboxPath, statePath });
  expect(status.cursor).toBe(0);

  appendEvents.mockImplementation(async (_taskId: string) => snapshot());
  const second = await processApprovalOutbox({ outboxPath, statePath, now: 2000 });
  expect(second.applied).toBe(1);
  expect(appendEvents).toHaveBeenCalledTimes(2);
});

test("terminated tasks are skipped and marked applied", async () => {
  const { outboxPath, statePath } = await setup([granted()]);
  readBoard.mockResolvedValue(
    snapshot({ terminated: { reason: "admin", by: "ops", at: 1 } }),
  );

  const result = await processApprovalOutbox({ outboxPath, statePath, now: 1000 });
  expect(result.skipped).toBe(1);
  expect(result.details[0].reason).toBe("task_terminated");
  expect(appendEvents).not.toHaveBeenCalled();
});

test("acceptance gate still requires L0 verdict even with approval grant", async () => {
  const { outboxPath, statePath } = await setup([granted()]);
  readBoard.mockResolvedValue(
    snapshot({
      objective: {
        title: "验收",
        owner: "owner",
        mode: "judge",
        confidence_threshold: 0.8,
        progress: 1,
        required_verdict_level: "U2",
      },
    }),
  );

  const result = await processApprovalOutbox({ outboxPath, statePath, now: 1000 });
  expect(result.applied).toBe(0);
  expect(result.skipped).toBe(1);
  expect(result.details[0].reason).toBe("verdict_blocked:verdict_required");
  expect(appendEvents).not.toHaveBeenCalled();

  // 游标不前进：verdict 到达后可重试
  const status = await readApprovalOutboxStatus({ outboxPath, statePath });
  expect(status.cursor).toBe(0);
});

test("status reports cursor and applied count", async () => {
  const { outboxPath, statePath } = await setup([granted()]);
  await processApprovalOutbox({ outboxPath, statePath, now: 1000 });

  const status = await readApprovalOutboxStatus({ outboxPath, statePath });
  expect(status.outbox_exists).toBe(true);
  expect(status.cursor).toBe(1);
  expect(status.applied).toBe(1);
  expect(status.updated_at).toBe(1000);
});
