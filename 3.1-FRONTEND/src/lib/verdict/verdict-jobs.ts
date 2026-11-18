/**
 * 异步裁决 job（P2.5 运行时接线）。
 *
 * 依据：U2/U3 一律异步执行，Ticket 以 `waiting_verdict` 挂起（SPEC §2.4.3）。
 * 本模块只负责 job 生命周期与持久化；执行器由 runner 注入，便于替换与测试。
 */

import { randomUUID } from "crypto";
import { promises as fs } from "fs";
import * as path from "path";
import type { SourceRecord } from "./cross-source-reconcile";
import { recordVerdict } from "./verdict-events";
import type {
  UncertaintyVerdict,
  VerdictEvidence,
  VerdictIssue,
} from "./uncertainty-verdict";

export type VerdictJobLevel = "U2" | "U3";
export type VerdictJobStatus = "queued" | "running" | "succeeded" | "failed";

export interface VerdictJobRequest {
  task_id: string;
  trace_id: string;
  claim: string;
  level: VerdictJobLevel;
  /** U2：沙箱/回测配置 */
  sandbox?: {
    mode: "sandbox" | "backtest";
    capability: string;
    params?: Record<string, unknown>;
  };
  /** U3：采集来源（由 18 中心或调用方提供） */
  sources?: SourceRecord[];
  /** U3：REA 结构事实 */
  rea?: VerdictEvidence[];
  confidence?: number | null;
  poe_score?: number;
  dissent?: string[];
}

export interface VerdictJobRecord {
  job_id: string;
  request: VerdictJobRequest;
  status: VerdictJobStatus;
  attempts: number;
  created_at: number;
  updated_at: number;
  verdict?: UncertaintyVerdict;
  issues?: VerdictIssue[];
  error?: string;
}

export type VerdictJobExecutor = (
  request: VerdictJobRequest,
) => Promise<{ verdict: UncertaintyVerdict; issues: VerdictIssue[] }>;

export interface VerdictJobOptions {
  root?: string;
  now?: () => number;
  /** 完成后写裁决；默认写 L0 权威事件 */
  onVerdict?: (verdict: UncertaintyVerdict) => Promise<void>;
}

export const DEFAULT_JOB_DIR = path.join(process.cwd(), ".data", "verdict-jobs");

function safeId(value: string): string {
  return value.replace(/[^a-zA-Z0-9._-]/g, "_").slice(0, 120) || "unknown";
}

function jobFile(jobId: string, root: string): string {
  return path.join(root, `${safeId(jobId)}.json`);
}

async function writeJob(job: VerdictJobRecord, root: string): Promise<void> {
  await fs.mkdir(root, { recursive: true });
  await fs.writeFile(jobFile(job.job_id, root), JSON.stringify(job, null, 2), "utf-8");
}

export async function getVerdictJob(
  jobId: string,
  root: string = DEFAULT_JOB_DIR,
): Promise<VerdictJobRecord | null> {
  try {
    const raw = await fs.readFile(jobFile(jobId, root), "utf-8");
    return JSON.parse(raw) as VerdictJobRecord;
  } catch {
    return null;
  }
}

export async function listVerdictJobs(
  taskId?: string,
  root: string = DEFAULT_JOB_DIR,
): Promise<VerdictJobRecord[]> {
  let names: string[] = [];
  try {
    names = (await fs.readdir(root)).filter((name) => name.endsWith(".json"));
  } catch {
    return [];
  }
  const jobs: VerdictJobRecord[] = [];
  for (const name of names) {
    try {
      const raw = await fs.readFile(path.join(root, name), "utf-8");
      const job = JSON.parse(raw) as VerdictJobRecord;
      if (!taskId || job.request?.task_id === taskId) jobs.push(job);
    } catch {
      // 单文件损坏不影响其余 job
    }
  }
  return jobs.sort((left, right) => right.created_at - left.created_at);
}

/** 创建 job（queued），返回持久化记录。 */
export async function createVerdictJob(
  request: VerdictJobRequest,
  options: VerdictJobOptions = {},
): Promise<VerdictJobRecord> {
  const root = options.root ?? DEFAULT_JOB_DIR;
  const now = options.now?.() ?? Date.now();
  const job: VerdictJobRecord = {
    job_id: `verdict-job-${now}-${randomUUID().slice(0, 8)}`,
    request,
    status: "queued",
    attempts: 0,
    created_at: now,
    updated_at: now,
  };
  await writeJob(job, root);
  return job;
}

/**
 * 执行 job：queued → running → succeeded / failed，每一步都落盘。
 * 已成功的 job 幂等返回，不重复写裁决。
 */
export async function executeVerdictJob(
  jobId: string,
  executor: VerdictJobExecutor,
  options: VerdictJobOptions = {},
): Promise<VerdictJobRecord | null> {
  const root = options.root ?? DEFAULT_JOB_DIR;
  const now = () => options.now?.() ?? Date.now();
  const job = await getVerdictJob(jobId, root);
  if (!job) return null;
  if (job.status === "succeeded") return job;

  job.status = "running";
  job.attempts += 1;
  job.updated_at = now();
  await writeJob(job, root);

  try {
    const { verdict, issues } = await executor(job.request);
    const write = options.onVerdict ?? recordVerdict;
    await write(verdict);
    job.status = "succeeded";
    job.verdict = verdict;
    job.issues = issues;
    job.updated_at = now();
    await writeJob(job, root);
    return job;
  } catch (error) {
    job.status = "failed";
    job.error = error instanceof Error ? error.message : String(error);
    job.updated_at = now();
    await writeJob(job, root);
    return job;
  }
}
