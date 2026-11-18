/**
 * 裁决事件的统一写入口（P2.5 运行时接线）。
 *
 * 单一事实源：L0 `verdict.updated` 事件。
 * - 写入：先落 append-only verdict 文件，再追加 L0 事件；
 * - 读取：事件优先，旧数据无事件时回退到文件存储（迁移期兼容）。
 */

import {
  appendTaskEvents,
  readVerdictEvents,
} from "@/lib/task-board/server-store";
import { appendVerdict, latestVerdict, listVerdicts } from "./verdict-store";
import type { UncertaintyVerdict } from "./uncertainty-verdict";

/** 写入一条裁决（文件 + L0 事件），供 API / 异步 job 共用。 */
export async function recordVerdict(verdict: UncertaintyVerdict): Promise<void> {
  await appendVerdict(verdict);
  await appendTaskEvents(verdict.task_id, [
    {
      task_id: verdict.task_id,
      trace_id: verdict.trace_id,
      seq: 0,
      ts: verdict.created_at,
      type: "verdict.updated",
      payload: verdict,
    },
  ]);
}

/** 最新裁决：L0 事件优先，回退文件。 */
export async function latestVerdictL0(
  taskId: string,
): Promise<UncertaintyVerdict | null> {
  const events = await readVerdictEvents(taskId);
  if (events.length > 0) return events[events.length - 1];
  return latestVerdict(taskId);
}

/** 裁决历史：L0 事件优先，回退文件。 */
export async function listVerdictsL0(
  taskId: string,
): Promise<UncertaintyVerdict[]> {
  const events = await readVerdictEvents(taskId);
  return events.length > 0 ? events : listVerdicts(taskId);
}
