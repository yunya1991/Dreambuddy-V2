/**
 * P0-D3D Phase 3：approval_outbox → GateFlow 推进。
 *
 * Python `ApprovalBridge` 已验签并写入 `approval.granted`（append-only JSONL）。
 * 本模块作为唯一消费者，把授权结果转成 `gate.updated`（approved），推进任务门禁。
 *
 * 硬约束：
 * - 只消费 `approval.granted`；其他事件忽略；
 * - 必须有 `task_id` + `gate_id`（来自 Python 侧 context），否则跳过并留痕；
 * - 幂等：同 request_id/grant_id 只应用一次；门已 approved 直接视为已应用；
 * - 失败不推进游标，下一轮重试；坏行跳过，不阻塞整轮；
 * - 不绕过验收 verdict：GateFlow 的验收硬门仍由 gate API/verdict 侧负责。
 */

import { createHash } from "crypto";
import { promises as fs } from "fs";
import * as path from "path";
import type { TaskBoardEvent } from "@/types/task-board";
import { latestVerdictL0 } from "@/lib/verdict/verdict-events";
import { checkVerdictForGate } from "@/lib/verdict/verdict-gate";
import { appendTaskEvents, readTaskBoard } from "./server-store";

const DEFAULT_OUTBOX =
  process.env.GATEFLOW_APPROVAL_OUTBOX?.trim() ||
  path.join(process.cwd(), ".data", "gateflow", "approval_outbox.jsonl");
const DEFAULT_STATE =
  process.env.APPROVAL_OUTBOX_STATE?.trim() ||
  path.join(process.cwd(), ".data", "gateflow", "approval_outbox_state.json");

const MAX_APPLIED_KEYS = 5000;

export interface ApprovalOutboxEvent {
  type?: string;
  request_id?: string;
  grant_id?: string;
  grant_hash?: string;
  subject?: string;
  task_id?: string;
  gate_id?: string;
  gate_kind?: string;
  gate_run_id?: string;
  node_id?: string;
  scope?: unknown;
  grant?: Record<string, unknown>;
  context?: Record<string, unknown>;
}

export interface ApprovalOutboxDetail {
  request_id: string;
  grant_id: string;
  task_id: string;
  gate_id: string;
  status: "applied" | "duplicate" | "skipped" | "failed";
  reason?: string;
}

export interface ApprovalOutboxResult {
  ok: boolean;
  scanned: number;
  applied: number;
  duplicates: number;
  skipped: number;
  failed: number;
  details: ApprovalOutboxDetail[];
}

export interface ApprovalOutboxOptions {
  outboxPath?: string;
  statePath?: string;
  now?: number;
}

interface OutboxState {
  cursor: number;
  applied: string[];
  updated_at: number;
}

function str(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function appliedKey(event: ApprovalOutboxEvent): string {
  const requestId = str(event.request_id);
  const grantId = str(event.grant_id);
  if (requestId && grantId) return `${requestId}|${grantId}`;
  if (grantId) return `grant:${grantId}`;
  if (requestId) return `request:${requestId}`;
  return "";
}

function targetOf(event: ApprovalOutboxEvent): { taskId: string; gateId: string } {
  const context = event.context ?? {};
  return {
    taskId: str(event.task_id) || str(context.task_id),
    gateId: str(event.gate_id) || str(context.gate_id),
  };
}

function kindOf(event: ApprovalOutboxEvent): string {
  const context = event.context ?? {};
  return str(event.gate_kind) || str(context.gate_kind);
}

async function readState(statePath: string): Promise<OutboxState> {
  try {
    const raw = await fs.readFile(statePath, "utf-8");
    const parsed = JSON.parse(raw) as Partial<OutboxState>;
    return {
      cursor: Number.isFinite(parsed.cursor) ? Number(parsed.cursor) : 0,
      applied: Array.isArray(parsed.applied)
        ? parsed.applied.filter((item): item is string => typeof item === "string")
        : [],
      updated_at: Number(parsed.updated_at) || 0,
    };
  } catch {
    return { cursor: 0, applied: [], updated_at: 0 };
  }
}

async function writeState(statePath: string, state: OutboxState): Promise<void> {
  const dir = path.dirname(statePath) || ".";
  await fs.mkdir(dir, { recursive: true });
  const tmp = path.join(dir, `.${path.basename(statePath)}.${process.pid}.tmp`);
  await fs.writeFile(tmp, JSON.stringify(state), "utf-8");
  await fs.rename(tmp, statePath);
}

async function readLines(outboxPath: string): Promise<string[]> {
  try {
    const raw = await fs.readFile(outboxPath, "utf-8");
    const lines = raw.split("\n");
    // 末尾换行不产生真实事件行
    if (lines.length > 0 && lines[lines.length - 1] === "") lines.pop();
    return lines;
  } catch {
    return [];
  }
}

/**
 * 消费 outbox 中未处理的事件，推进 GateFlow。
 * 可在 API/cron 中重复调用；游标与已应用键持久化，天然幂等。
 */
export async function processApprovalOutbox(
  options: ApprovalOutboxOptions = {},
): Promise<ApprovalOutboxResult> {
  const outboxPath = options.outboxPath ?? DEFAULT_OUTBOX;
  const statePath = options.statePath ?? DEFAULT_STATE;
  const now = options.now ?? Date.now();

  const result: ApprovalOutboxResult = {
    ok: true,
    scanned: 0,
    applied: 0,
    duplicates: 0,
    skipped: 0,
    failed: 0,
    details: [],
  };

  const state = await readState(statePath);
  const applied = new Set(state.applied);
  const lines = await readLines(outboxPath);
  let start = state.cursor;
  if (lines.length < start) start = 0; // 文件截断自愈

  let processed = 0;
  for (let index = start; index < lines.length; index += 1) {
    const text = lines[index].trim();
    if (!text) {
      processed += 1;
      continue;
    }

    let event: ApprovalOutboxEvent;
    try {
      event = JSON.parse(text) as ApprovalOutboxEvent;
    } catch {
      result.skipped += 1;
      result.details.push({
        request_id: "",
        grant_id: "",
        task_id: "",
        gate_id: "",
        status: "skipped",
        reason: "bad_json",
      });
      processed += 1;
      continue;
    }
    if (!event || event.type !== "approval.granted") {
      processed += 1;
      continue;
    }

    result.scanned += 1;
    const key = appliedKey(event);
    const { taskId, gateId } = targetOf(event);
    const detail: ApprovalOutboxDetail = {
      request_id: str(event.request_id),
      grant_id: str(event.grant_id),
      task_id: taskId,
      gate_id: gateId,
      status: "skipped",
    };

    if (!key || !str(event.grant_hash)) {
      detail.reason = "missing_grant_identity";
      result.skipped += 1;
      result.details.push(detail);
      processed += 1;
      continue;
    }
    if (applied.has(key)) {
      detail.status = "duplicate";
      result.duplicates += 1;
      result.details.push(detail);
      processed += 1;
      continue;
    }
    if (!taskId || !gateId) {
      detail.reason = "missing_task_or_gate";
      result.skipped += 1;
      result.details.push(detail);
      processed += 1;
      continue;
    }

    try {
      const snapshot = await readTaskBoard(taskId);
      if (snapshot.terminated) {
        detail.reason = "task_terminated";
        result.skipped += 1;
        result.details.push(detail);
        applied.add(key);
        processed += 1;
        continue;
      }
      const gate = snapshot.gates.find((item) => item.gate_id === gateId);
      if (!gate) {
        detail.reason = "gate_not_found";
        result.skipped += 1;
        result.details.push(detail);
        applied.add(key);
        processed += 1;
        continue;
      }
      const expectedKind = kindOf(event);
      if (expectedKind && expectedKind !== gate.kind) {
        detail.reason = `gate_kind_mismatch:${expectedKind}!=${gate.kind}`;
        result.skipped += 1;
        result.details.push(detail);
        applied.add(key);
        processed += 1;
        continue;
      }
      if (gate.status === "approved") {
        detail.status = "duplicate";
        detail.reason = "gate_already_approved";
        result.duplicates += 1;
        result.details.push(detail);
        applied.add(key);
        processed += 1;
        continue;
      }

      // 验收门硬约束不因授权通道而放松：仍消费 L0 verdict。
      const requiredLevel = snapshot.objective?.required_verdict_level;
      if (gate.kind === "acceptance" && requiredLevel) {
        const latest = await latestVerdictL0(taskId);
        const check = checkVerdictForGate({ required: requiredLevel, verdict: latest });
        if (!check.ok) {
          detail.reason = `verdict_blocked:${check.error}`;
          result.skipped += 1;
          result.details.push(detail);
          // 不推进游标：等 L0 verdict 到达后重试，避免授权被永久跳过。
          break;
        }
      }

      const subject = str(event.subject) || "unknown";
      const decidedBy = subject.startsWith("feishu:") ? subject : `feishu:${subject}`;
      const grantRef = str(event.grant_id) || str(event.request_id);
      const eventToAppend: TaskBoardEvent = {
        task_id: taskId,
        trace_id: snapshot.trace_id || taskId,
        seq: 0,
        ts: now,
        type: "gate.updated",
        payload: {
          ...gate,
          status: "approved",
          evidence_ref: gate.evidence_ref,
          decided_by: decidedBy,
          decided_at: now,
          comment: `approval.granted:${grantRef}`,
          rewind_to: undefined,
        },
      };
      await appendTaskEvents(taskId, [eventToAppend]);

      detail.status = "applied";
      result.applied += 1;
      result.details.push(detail);
      applied.add(key);
      processed += 1;
    } catch (error) {
      // 不推进游标：下一轮重试该事件。
      detail.status = "failed";
      detail.reason = `apply_failed:${(error as Error)?.message ?? "unknown"}`;
      result.failed += 1;
      result.ok = false;
      result.details.push(detail);
      break;
    }
  }

  const nextApplied = [...applied];
  await writeState(statePath, {
    cursor: start + processed,
    applied:
      nextApplied.length > MAX_APPLIED_KEYS
        ? nextApplied.slice(-MAX_APPLIED_KEYS)
        : nextApplied,
    updated_at: now,
  }).catch(() => undefined);

  return result;
}

export interface ApprovalOutboxStatus {
  outbox_path: string;
  state_path: string;
  outbox_exists: boolean;
  cursor: number;
  applied: number;
  updated_at: number;
}

export async function readApprovalOutboxStatus(
  options: ApprovalOutboxOptions = {},
): Promise<ApprovalOutboxStatus> {
  const outboxPath = options.outboxPath ?? DEFAULT_OUTBOX;
  const statePath = options.statePath ?? DEFAULT_STATE;
  const state = await readState(statePath);
  let exists = false;
  try {
    await fs.access(outboxPath);
    exists = true;
  } catch {
    exists = false;
  }
  return {
    outbox_path: outboxPath,
    state_path: statePath,
    outbox_exists: exists,
    cursor: state.cursor,
    applied: state.applied.length,
    updated_at: state.updated_at,
  };
}

/** 审计指纹：便于在日志中核对事件来源（不参与幂等判定） */
export function outboxEventFingerprint(event: ApprovalOutboxEvent): string {
  return createHash("sha1")
    .update(`${str(event.request_id)}|${str(event.grant_id)}|${str(event.grant_hash)}`)
    .digest("hex");
}
