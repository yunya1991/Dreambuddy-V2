/**
 * 任务看板服务端存储（事件 SSoT）。
 *
 * - 事件追加写入 JSONL；同一任务串行化，避免并发把 seq 写乱；
 * - 快照永远由事件回放得到，刷新/换设备后一致；
 * - 相同事件按内容指纹去重，重复上报不会产生重复确认。
 */

import { createHash } from "crypto";
import { promises as fs } from "fs";
import * as path from "path";
import {
  buildTaskBoard,
  taskEventEntityId,
  type TaskBoardEvent,
  type TaskBoardSnapshot,
  type TaskGate,
} from "@/types/task-board";
import { getGateMode, GATE_RISK, resolveGatePolicy } from "./gate-policy";
import type { UncertaintyVerdict } from "@/lib/verdict/uncertainty-verdict";
import { autoApproveGates } from "./gate-auto";
import { evaluateGateSla } from "./gate-governance";

const DATA_DIR =
  process.env.TASK_BOARD_DIR?.trim() ||
  path.join(process.cwd(), ".data", "task-board");

type StoredEvent = TaskBoardEvent & { fp: string };

function safeId(taskId: string): string {
  const clean = taskId.replace(/[^a-zA-Z0-9._-]/g, "_").slice(0, 120);
  return clean || "unknown";
}

function filePath(taskId: string): string {
  return path.join(DATA_DIR, `${safeId(taskId)}.jsonl`);
}

function fingerprint(event: TaskBoardEvent): string {
  return createHash("sha1")
    .update(`${event.type}|${taskEventEntityId(event)}|${JSON.stringify(event.payload)}`)
    .digest("hex");
}

const locks = new Map<string, Promise<unknown>>();

function withLock<T>(taskId: string, fn: () => Promise<T>): Promise<T> {
  const key = safeId(taskId);
  const prev = locks.get(key) ?? Promise.resolve();
  const next = prev.then(fn, fn);
  locks.set(key, next.catch(() => undefined));
  return next;
}

async function readStored(taskId: string): Promise<StoredEvent[]> {
  try {
    const raw = await fs.readFile(filePath(taskId), "utf-8");
    const events: StoredEvent[] = [];
    for (const line of raw.split("\n")) {
      const text = line.trim();
      if (!text) continue;
      try {
        const parsed = JSON.parse(text) as StoredEvent;
        if (parsed?.type && parsed.task_id) events.push(parsed);
      } catch {
        // 单行损坏不影响其余事件
      }
    }
    return events;
  } catch {
    return [];
  }
}

function snapshotFrom(taskId: string, events: StoredEvent[]): TaskBoardSnapshot {
  const seen = new Set<string>();
  const unique = events.filter((event) => {
    if (!event.fp) return true;
    if (seen.has(event.fp)) return false;
    seen.add(event.fp);
    return true;
  });
  return buildTaskBoard(taskId, unique[0]?.trace_id || taskId, unique);
}

/** 读取快照（不存在时返回空看板） */
export async function readTaskBoard(taskId: string): Promise<TaskBoardSnapshot> {
  return snapshotFrom(taskId, await readStored(taskId));
}

/**
 * L0 权威裁决事件（append-only）。
 * `verdict.updated` 是 UncertaintyVerdict 的权威副本，调用方不得另建第二事实源。
 */
export async function readVerdictEvents(
  taskId: string,
): Promise<UncertaintyVerdict[]> {
  const verdicts: UncertaintyVerdict[] = [];
  for (const event of await readStored(taskId)) {
    if (event.type === "verdict.updated") verdicts.push(event.payload);
  }
  return verdicts;
}

/** 追加事件并返回最新快照；seq 由服务端统一分配 */
export async function appendTaskEvents(
  taskId: string,
  incoming: TaskBoardEvent[],
): Promise<TaskBoardSnapshot> {
  return withLock(taskId, async () => {
    const existing = await readStored(taskId);
    const seen = new Set(existing.map((event) => event.fp));
    let seq = existing.reduce((max, event) => Math.max(max, event.seq), -1) + 1;
    const fresh: StoredEvent[] = [];

    for (const event of incoming) {
      if (!event?.type) continue;
      const fp = fingerprint(event);
      if (seen.has(fp)) continue;
      seen.add(fp);
      fresh.push({
        ...event,
        task_id: taskId,
        trace_id: event.trace_id || taskId,
        seq: seq++,
        fp,
      });
    }

    if (fresh.length > 0) {
      await writeEvents(taskId, fresh);
    }

    const baseEvents = [...existing, ...fresh];
    let snapshot = snapshotFrom(taskId, baseEvents);

    // 全权模式：门禁生成后自动确认低/中风险门，high/critical 留给人工
    const auto = autoApproveGates(snapshot, getGateMode());
    if (auto.length > 0) {
      const autoStored: StoredEvent[] = auto.map((event) => ({
        ...event,
        task_id: taskId,
        trace_id: event.trace_id || taskId,
        seq: seq++,
        fp: fingerprint(event),
      }));
      await writeEvents(taskId, autoStored);
      snapshot = snapshotFrom(taskId, [...baseEvents, ...autoStored]);
    }

    return snapshot;
  });
}

async function writeEvents(taskId: string, events: StoredEvent[]): Promise<void> {
  await fs.mkdir(DATA_DIR, { recursive: true });
  await fs.appendFile(
    filePath(taskId),
    `${events.map((event) => JSON.stringify(event)).join("\n")}\n`,
    "utf-8",
  );
}

/** 未确认的必需门禁（按工作流顺序）；已终止任务不再产生待办 */
export function pendingGates(snapshot: TaskBoardSnapshot): TaskGate[] {
  if (snapshot.terminated) return [];
  return snapshot.gates.filter(
    (gate) => gate.required && gate.status !== "approved",
  );
}

export async function pendingGatesForTask(taskId: string): Promise<TaskGate[]> {
  return pendingGates(await readTaskBoard(taskId));
}

export interface PendingGateTask {
  task_id: string;
  title: string;
  updated_at: number;
  pending_gates: TaskGate[];
}

const RISK_RANK: Record<string, number> = {
  acceptance: 3,
  dispatch: 2,
  spec: 2,
  intent: 1,
  summary: 1,
};

function taskRiskRank(gates: TaskGate[]): number {
  return gates.reduce(
    (max, gate) => Math.max(max, RISK_RANK[gate.kind] ?? 1),
    0,
  );
}

/** 待办中心：扫描所有任务，返回仍有未确认门禁的任务（高风险优先） */
export async function listPendingGateTasks(): Promise<PendingGateTask[]> {
  let files: string[] = [];
  try {
    files = (await fs.readdir(DATA_DIR)).filter((name) =>
      name.endsWith(".jsonl"),
    );
  } catch {
    return [];
  }

  const items = await Promise.all(
    files.map(async (file) => {
      const taskId = file.replace(/\.jsonl$/, "");
      const snapshot = await readTaskBoard(taskId);
      const pending = pendingGates(snapshot);
      if (pending.length === 0) return null;
      return {
        task_id: snapshot.task_id,
        title: snapshot.objective?.title || "未命名任务",
        updated_at: snapshot.updated_at,
        pending_gates: pending,
      } satisfies PendingGateTask;
    }),
  );

  return items
    .filter((item): item is PendingGateTask => Boolean(item))
    .sort(
      (a, b) =>
        taskRiskRank(b.pending_gates) - taskRiskRank(a.pending_gates) ||
        b.updated_at - a.updated_at,
    );
}

export interface GateSlaSweepResult {
  task_id: string;
  actions: { type: string; gate_id: string; kind: string }[];
}

/**
 * 超时巡检：只写提醒/升级事件，绝不自动通过。
 * 可在待办中心或定时任务里调用；重复调用由 reminded_at / escalated_at 幂等。
 */
export async function sweepGateSla(
  now: number = Date.now(),
): Promise<GateSlaSweepResult[]> {
  let files: string[] = [];
  try {
    files = (await fs.readdir(DATA_DIR)).filter((name) =>
      name.endsWith(".jsonl"),
    );
  } catch {
    return [];
  }

  const results: GateSlaSweepResult[] = [];

  for (const file of files) {
    const taskId = file.replace(/\.jsonl$/, "");
    const snapshot = await readTaskBoard(taskId);
    if (snapshot.terminated) continue;

    const actions = evaluateGateSla(
      snapshot.gates,
      (kind) => resolveGatePolicy(kind, GATE_RISK[kind]),
      now,
    );
    if (actions.length === 0) continue;

    const events: TaskBoardEvent[] = [];
    for (const action of actions) {
      const gate = snapshot.gates.find((item) => item.gate_id === action.gate_id);
      if (!gate) continue;
      events.push({
        task_id: taskId,
        trace_id: snapshot.trace_id || taskId,
        seq: 0,
        ts: now,
        type: "gate.updated",
        payload:
          action.type === "gate.reminded"
            ? {
                ...gate,
                remind_count: (gate.remind_count ?? 0) + 1,
                reminded_at: now,
              }
            : { ...gate, escalated_at: now },
      });
    }

    if (events.length > 0) {
      await appendTaskEvents(taskId, events);
    }
    results.push({
      task_id: taskId,
      actions: actions.map((action) => ({
        type: action.type,
        gate_id: action.gate_id,
        kind: action.kind,
      })),
    });
  }

  return results;
}
