/**
 * verdict 的 append-only 存储。
 * 权威副本在 L0；本文件是前端侧最小实现（按 task 分文件），行为与 task-board 事件流一致。
 */

import { appendFile, mkdir, readFile } from "fs/promises";
import path from "path";
import {
  validateVerdict,
  type UncertaintyVerdict,
} from "./uncertainty-verdict";

export const DEFAULT_VERDICT_DIR = path.join(
  process.cwd(),
  ".data",
  "verdicts",
);

function safeTaskId(taskId: string): string {
  return taskId.replace(/[^a-zA-Z0-9._-]/g, "_");
}

function fileFor(taskId: string, root: string): string {
  return path.join(root, `${safeTaskId(taskId)}.jsonl`);
}

export async function appendVerdict(
  verdict: UncertaintyVerdict,
  root: string = DEFAULT_VERDICT_DIR,
): Promise<void> {
  const issues = validateVerdict(verdict).filter(
    (issue) => issue.level === "error",
  );
  if (issues.length > 0) {
    throw new Error(
      `verdict 校验失败：${issues.map((issue) => issue.message).join("; ")}`,
    );
  }
  await mkdir(root, { recursive: true });
  await appendFile(fileFor(verdict.task_id, root), `${JSON.stringify(verdict)}\n`, {
    encoding: "utf8",
  });
}

export async function listVerdicts(
  taskId: string,
  root: string = DEFAULT_VERDICT_DIR,
): Promise<UncertaintyVerdict[]> {
  try {
    const raw = await readFile(fileFor(taskId, root), "utf8");
    return raw
      .split("\n")
      .filter(Boolean)
      .map((line) => JSON.parse(line) as UncertaintyVerdict);
  } catch {
    return [];
  }
}

export async function latestVerdict(
  taskId: string,
  root: string = DEFAULT_VERDICT_DIR,
): Promise<UncertaintyVerdict | null> {
  const all = await listVerdicts(taskId, root);
  return all.length > 0 ? all[all.length - 1] : null;
}
