import fs from "node:fs";
import path from "node:path";
import { loadConfig, resolveRepoRoot } from "../config.js";

export interface QueueFileInfo {
  name: string;
  absolute_path: string;
  size_bytes: number;
  mtime_ms: number;
  id: string | null;
}

export interface QueueSnapshot {
  generated_at: string;
  artifacts_root: string;
  tasks_total: number;
  results_total: number;
  pending_total: number;
  pending_ids: string[];
  latest_tasks: QueueFileInfo[];
  latest_results: QueueFileInfo[];
}

function resolveArtifactsRoot(): string {
  const override = process.env.ARTIFACTS_ROOT?.trim();
  if (override && override.length > 0) return override;

  const repoRoot = resolveRepoRoot();
  const config = loadConfig(repoRoot);
  return path.join(repoRoot, config.paths.artifacts_root);
}

function toFileInfo(dir: string, name: string, id: string | null): QueueFileInfo {
  const absolute = path.join(dir, name);
  const st = fs.statSync(absolute);
  return {
    name,
    absolute_path: absolute,
    size_bytes: st.size,
    mtime_ms: st.mtimeMs,
    id
  };
}

function listJsonFiles(dir: string, parseId: (name: string) => string | null): QueueFileInfo[] {
  if (!fs.existsSync(dir)) return [];
  const names = fs
    .readdirSync(dir, { withFileTypes: true })
    .filter((d) => d.isFile() && d.name.endsWith(".json"))
    .map((d) => d.name);

  return names.map((name) => toFileInfo(dir, name, parseId(name)));
}

function sortByMtimeDesc(items: QueueFileInfo[]): QueueFileInfo[] {
  return items.slice().sort((a, b) => b.mtime_ms - a.mtime_ms);
}

function parseTaskId(name: string): string | null {
  const m = /^task_(.+)\.json$/.exec(name);
  return m?.[1] ?? null;
}

function parseResultId(name: string): string | null {
  const m = /^result_(.+)\.json$/.exec(name);
  return m?.[1] ?? null;
}

export function getQueueSnapshot(params?: { limit?: number }): QueueSnapshot {
  const artifactsRoot = resolveArtifactsRoot();
  const limit = Math.max(0, params?.limit ?? 50);

  const tasksDir = path.join(artifactsRoot, "tasks");
  const resultsDir = path.join(artifactsRoot, "results");

  const tasks = listJsonFiles(tasksDir, parseTaskId);
  const results = listJsonFiles(resultsDir, parseResultId);

  const taskIds = new Set(tasks.map((t) => t.id).filter((x): x is string => !!x));
  const resultIds = new Set(results.map((r) => r.id).filter((x): x is string => !!x));

  const pendingIds = Array.from(taskIds).filter((id) => !resultIds.has(id)).sort();

  const latestTasks = sortByMtimeDesc(tasks).slice(0, limit);
  const latestResults = sortByMtimeDesc(results).slice(0, limit);

  return {
    generated_at: new Date().toISOString(),
    artifacts_root: artifactsRoot,
    tasks_total: tasks.length,
    results_total: results.length,
    pending_total: pendingIds.length,
    pending_ids: pendingIds,
    latest_tasks: latestTasks,
    latest_results: latestResults
  };
}

