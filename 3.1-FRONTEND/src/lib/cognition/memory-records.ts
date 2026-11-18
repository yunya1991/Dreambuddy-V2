/**
 * 残差记忆记录生产端（P2.5 运行时接线）。
 *
 * 链路：残差候选 → 准入（四禁入/四残差/三测试）→ 追加 jsonl → 治理周期消费。
 * 只写通过准入的记录；拒绝原因原样返回，不静默丢弃。
 *
 * 存储为 append-only jsonl，同一 id 以最后一行为准（便于锚点复核后回写）。
 */

import { createHash } from "crypto";
import { promises as fs } from "fs";
import * as path from "path";
import {
  admitResidual,
  type AdmissionResult,
  type ResidualCandidate,
} from "./residual-admission";
import type {
  MemoryRecord,
  ResidualSubclass,
} from "./residual-forgetting";

export interface MemoryRecordInput extends ResidualCandidate {
  /** 记忆分型；治理口径依赖它 */
  subclass: ResidualSubclass;
  /** 事实源锚点（file:... / doc:...）；缺省回退 candidate.anchor */
  source_anchor?: string;
  summary?: string;
}

export interface MemoryWriteResult {
  ok: boolean;
  record?: MemoryRecord;
  admission: AdmissionResult;
  duplicated?: boolean;
}

export const DEFAULT_MEMORY_FILE = path.join(
  process.cwd(),
  ".data",
  "memory",
  "records.jsonl",
);

export const DEFAULT_PENDING_FILE = path.join(
  process.cwd(),
  ".data",
  "memory",
  "pending.jsonl",
);

/** 运行时读取环境变量，便于测试与不同部署覆盖。 */
export function memoryFile(): string {
  return process.env.MEMORY_RECORDS_FILE?.trim() || DEFAULT_MEMORY_FILE;
}

export function pendingFile(): string {
  return process.env.MEMORY_PENDING_FILE?.trim() || DEFAULT_PENDING_FILE;
}

function fingerprint(input: MemoryRecordInput): string {
  return createHash("sha1")
    .update(`${input.subclass}|${input.content}|${input.trace_id ?? ""}`)
    .digest("hex")
    .slice(0, 12);
}

async function appendRaw(record: MemoryRecord, file: string): Promise<void> {
  await fs.mkdir(path.dirname(file), { recursive: true });
  await fs.appendFile(file, `${JSON.stringify(record)}\n`, "utf-8");
}

/** 读取全部记录（同 id 最后一行生效）。 */
export async function listMemoryRecords(
  file: string = memoryFile(),
): Promise<MemoryRecord[]> {
  try {
    const raw = await fs.readFile(file, "utf-8");
    const byId = new Map<string, MemoryRecord>();
    for (const line of raw.split("\n")) {
      const text = line.trim();
      if (!text) continue;
      try {
        const parsed = JSON.parse(text) as MemoryRecord;
        if (parsed?.id) byId.set(parsed.id, parsed);
      } catch {
        // 单行损坏跳过
      }
    }
    return [...byId.values()];
  } catch {
    return [];
  }
}

/**
 * 写入一条候选：先过残差准入，通过才落盘。
 * 同一内容指纹重复提交返回已有记录，不重复写。
 */
export async function appendMemoryRecord(
  input: MemoryRecordInput,
  options: { file?: string; now?: number } = {},
): Promise<MemoryWriteResult> {
  const admission = admitResidual(input);
  if (!admission.admit) {
    return { ok: false, admission };
  }

  const file = options.file ?? memoryFile();
  const now = options.now ?? Date.now();
  const id = `mem-${fingerprint(input)}`;
  const existing = (await listMemoryRecords(file)).find((item) => item.id === id);
  if (existing) {
    return { ok: true, record: existing, admission, duplicated: true };
  }

  const record: MemoryRecord = {
    id,
    trace_id: input.trace_id,
    subclass: input.subclass,
    source_anchor: input.source_anchor ?? input.anchor,
    verify_state: "verified",
    created_at: now,
    last_verified_at: now,
    last_used_at: now,
    access_count: 0,
    form: admission.form === "reject" ? undefined : admission.form,
    summary: input.summary,
  };
  await appendRaw(record, file);
  return { ok: true, record, admission };
}

export interface AnchorRefreshResult {
  records: MemoryRecord[];
  changed: MemoryRecord[];
}

const SUBCLASSES: ResidualSubclass[] = [
  "code_fact",
  "runtime",
  "policy",
  "relationship",
  "tech_decision",
  "artifact",
];

export interface IngestResult {
  scanned: number;
  admitted: number;
  duplicated: number;
  rejected: number;
  invalid: number;
}

function asText(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

/**
 * 消费 settle 暂存候选：逐条过准入后落正式记录。
 * 处理完后只保留异常行（下次重试），被拒绝的候选不保留（判定是确定性的）。
 */
export async function ingestPendingCandidates(
  options: { pending?: string; file?: string; now?: number } = {},
): Promise<IngestResult> {
  const pending = options.pending ?? pendingFile();
  const counts: IngestResult = {
    scanned: 0,
    admitted: 0,
    duplicated: 0,
    rejected: 0,
    invalid: 0,
  };

  let lines: string[] = [];
  try {
    const raw = await fs.readFile(pending, "utf-8");
    lines = raw.split("\n").filter((line) => line.trim());
  } catch {
    return counts;
  }

  const retry: string[] = [];
  for (const line of lines) {
    counts.scanned += 1;
    let item: Record<string, unknown>;
    try {
      item = JSON.parse(line) as Record<string, unknown>;
    } catch {
      counts.invalid += 1;
      continue;
    }
    const content = asText(item.content);
    const subclass = item.subclass as ResidualSubclass;
    if (!content || !SUBCLASSES.includes(subclass)) {
      counts.invalid += 1;
      continue;
    }
    const input: MemoryRecordInput = {
      content,
      subclass,
      anchor: asText(item.anchor),
      source_anchor: asText(item.source_anchor),
      summary: asText(item.summary),
      trace_id: asText(item.trace_id),
      // 准入信号必须透传，否则暂存层会绕过四禁入
      sensitive: item.sensitive === true,
      trajectory: item.trajectory === true,
      duplicate: item.duplicate === true,
      derivable: item.derivable === true,
      residual_kind: ["R1", "R2", "R3", "R4"].includes(String(item.residual_kind))
        ? (item.residual_kind as "R1" | "R2" | "R3" | "R4")
        : undefined,
      relations: Array.isArray(item.relations)
        ? item.relations.filter((value): value is string => typeof value === "string")
        : undefined,
      tests:
        item.tests && typeof item.tests === "object"
          ? (item.tests as MemoryRecordInput["tests"])
          : undefined,
    };
    try {
      const result = await appendMemoryRecord(input, {
        file: options.file,
        now: options.now,
      });
      if (!result.ok) counts.rejected += 1;
      else if (result.duplicated) counts.duplicated += 1;
      else counts.admitted += 1;
    } catch {
      retry.push(line);
    }
  }

  try {
    await fs.writeFile(
      pending,
      retry.length > 0 ? `${retry.join("\n")}\n` : "",
      "utf-8",
    );
  } catch {
    // 暂存清理失败不影响已落盘记录；下轮会因指纹重复自动去重
  }
  return counts;
}

const ANCHOR_RE = /^(file|doc):(.+)$/;

async function defaultExists(target: string): Promise<boolean> {
  try {
    await fs.access(target);
    return true;
  } catch {
    return false;
  }
}

/**
 * 事件驱动锚点复核：只检查 `file:` / `doc:` 锚点，未知格式不动。
 * 变化记录追加回写（append-only），返回合并后的最新视图。
 */
export async function refreshAnchors(
  records: MemoryRecord[],
  options: {
    root?: string;
    file?: string;
    now?: number;
    exists?: (target: string) => Promise<boolean>;
  } = {},
): Promise<AnchorRefreshResult> {
  const root = options.root ?? process.cwd();
  const file = options.file ?? memoryFile();
  const now = options.now ?? Date.now();
  const exists = options.exists ?? defaultExists;
  const changed: MemoryRecord[] = [];

  for (const record of records) {
    const anchor = record.source_anchor?.trim();
    if (!anchor) continue;
    const match = ANCHOR_RE.exec(anchor);
    if (!match) continue;
    const target = match[2].split("#", 1)[0];
    const absolute = path.isAbsolute(target) ? target : path.join(root, target);
    const anchorExists = await exists(absolute);
    if (record.anchor_exists === anchorExists) continue;
    changed.push({
      ...record,
      anchor_exists: anchorExists,
      last_verified_at: anchorExists ? now : record.last_verified_at,
    });
  }

  for (const record of changed) {
    await appendRaw(record, file);
  }

  const merged = new Map(records.map((record) => [record.id, record]));
  for (const record of changed) merged.set(record.id, record);
  return { records: [...merged.values()], changed };
}
