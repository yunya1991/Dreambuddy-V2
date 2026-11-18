"use client";

/**
 * 任务看板快照存取 + 订阅入口 + 门禁决策。
 *
 * - 事件归并统一走 `applyTaskEvent`（幂等、按 seq）；
 * - 快照优先从服务端事件流回放，服务端不可达时退回 localStorage；
 * - 没有事件时不编造内容，保持空态由组件自行提示。
 */

import { useCallback, useEffect, useState } from "react";
import {
  applyTaskEvent,
  emptyTaskBoard,
  type GateKind,
  type TaskBoardEvent,
  type TaskBoardSnapshot,
} from "@/types/task-board";

const KEY_PREFIX = "dreambuddy:task-board:";

export function taskBoardStorageKey(taskId: string): string {
  return `${KEY_PREFIX}${taskId}`;
}

export function loadTaskBoard(taskId: string): TaskBoardSnapshot | null {
  if (typeof window === "undefined" || !taskId) return null;
  try {
    const raw = window.localStorage.getItem(taskBoardStorageKey(taskId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as TaskBoardSnapshot;
    if (!parsed || parsed.task_id !== taskId) return null;
    return parsed;
  } catch {
    // 快照损坏或隐私模式禁用存储：降级为实时内存态
    return null;
  }
}

export function saveTaskBoard(snapshot: TaskBoardSnapshot): void {
  if (typeof window === "undefined" || !snapshot.task_id) return;
  try {
    window.localStorage.setItem(
      taskBoardStorageKey(snapshot.task_id),
      JSON.stringify(snapshot),
    );
  } catch {
    // 配额不足：不阻塞主链路
  }
}

/** 供非页面场景（如对话面板）把事件落到同一份快照 */
export function applyEventsToStorage(
  taskId: string,
  traceId: string,
  events: TaskBoardEvent[],
): TaskBoardSnapshot | null {
  if (!taskId || events.length === 0) return null;
  const base = loadTaskBoard(taskId) ?? emptyTaskBoard(taskId, traceId);
  const next = events.reduce(applyTaskEvent, base);
  if (next !== base) saveTaskBoard(next);
  return next;
}

export interface GateDecisionInput {
  gateId: string;
  /** 批量确认：低/中风险门一次落票（做减法） */
  gateIds?: string[];
  status: "approved" | "rejected";
  comment?: string;
  rewindTo?: GateKind;
}

export interface GateDecisionResult {
  ok: boolean;
  error?: string;
  snapshot?: TaskBoardSnapshot;
}

export type GateMode = "autonomy" | "human";

export function useTaskBoard(taskId: string) {
  const [snapshot, setSnapshot] = useState<TaskBoardSnapshot>(() =>
    emptyTaskBoard(taskId, taskId),
  );
  const [hydrated, setHydrated] = useState(false);
  const [mode, setMode] = useState<GateMode>("human");
  const [busyGateId, setBusyGateId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function hydrate() {
      const local = loadTaskBoard(taskId);
      if (local && !cancelled) setSnapshot(local);

      try {
        const response = await fetch(
          `/api/task/${encodeURIComponent(taskId)}`,
          { cache: "no-store" },
        );
        if (response.ok) {
          const data = (await response.json()) as {
            snapshot?: TaskBoardSnapshot;
            mode?: GateMode;
          };
          if (data?.mode === "autonomy" || data?.mode === "human") {
            if (!cancelled) setMode(data.mode);
          }
          const remote = data?.snapshot;
          if (
            !cancelled &&
            remote &&
            remote.task_id === taskId &&
            remote.seq >= 0
          ) {
            setSnapshot(remote);
            saveTaskBoard(remote);
          }
        }
      } catch {
        // 服务端不可达：本地快照即当前事实
      } finally {
        if (!cancelled) setHydrated(true);
      }
    }

    hydrate();
    return () => {
      cancelled = true;
    };
  }, [taskId]);

  const applyEvents = useCallback((events: TaskBoardEvent[]) => {
    if (events.length === 0) return;
    setSnapshot((prev) => {
      const next = events.reduce(applyTaskEvent, prev);
      if (next === prev) return prev;
      saveTaskBoard(next);
      return next;
    });
  }, []);

  const decideGate = useCallback(
    async (decision: GateDecisionInput): Promise<GateDecisionResult> => {
      setBusyGateId(decision.gateId);
      try {
        const response = await fetch(
          `/api/task/${encodeURIComponent(taskId)}/gate`,
          {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify({
              gate_id: decision.gateId,
              gate_ids:
                decision.gateIds && decision.gateIds.length > 1
                  ? decision.gateIds
                  : undefined,
              status: decision.status,
              comment: decision.comment,
              rewind_to: decision.rewindTo,
            }),
          },
        );
        const data = (await response.json().catch(() => null)) as
          | { success?: boolean; error?: string; snapshot?: TaskBoardSnapshot }
          | null;

        if (!response.ok || !data?.success) {
          return {
            ok: false,
            error: data?.error || `http_${response.status}`,
          };
        }

        const next = data.snapshot;
        if (next) {
          setSnapshot(next);
          saveTaskBoard(next);
        }
        return { ok: true, snapshot: next };
      } catch {
        return { ok: false, error: "network_error" };
      } finally {
        setBusyGateId(null);
      }
    },
    [taskId],
  );

  return { snapshot, hydrated, mode, applyEvents, decideGate, busyGateId };
}
