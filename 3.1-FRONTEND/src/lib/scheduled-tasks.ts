/**
 * 定时任务存储（工作台会话下方的「定时任务」）。
 *
 * 配置落在 .data/scheduled-tasks.json；到期执行由 run 接口触发，
 * 复用现有任务中台（/api/task），不另建执行器。
 */

import { promises as fs } from "fs";
import * as path from "path";

const DATA_DIR =
  process.env.TASK_BOARD_DIR?.trim()
    ? path.dirname(process.env.TASK_BOARD_DIR.trim())
    : path.join(process.cwd(), ".data");
const FILE = path.join(DATA_DIR, "scheduled-tasks.json");

export interface ScheduledTask {
  id: string;
  title: string;
  prompt: string;
  /** 执行间隔（分钟），最小 5 */
  interval_minutes: number;
  enabled: boolean;
  created_at: number;
  last_run_at?: number;
}

export async function readScheduledTasks(): Promise<ScheduledTask[]> {
  try {
    const raw = await fs.readFile(FILE, "utf-8");
    const parsed = JSON.parse(raw) as ScheduledTask[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export async function writeScheduledTasks(
  items: ScheduledTask[],
): Promise<void> {
  await fs.mkdir(DATA_DIR, { recursive: true });
  await fs.writeFile(FILE, JSON.stringify(items, null, 2), "utf-8");
}

export function isDue(task: ScheduledTask, now = Date.now()): boolean {
  if (!task.enabled) return false;
  const last = task.last_run_at ?? task.created_at;
  return now - last >= task.interval_minutes * 60_000;
}
