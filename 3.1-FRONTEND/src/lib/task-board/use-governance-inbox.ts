"use client";

/**
 * 治理待办收件箱（工作台左下抽屉的数据源）。
 *
 * 对接治理类模块：门禁待办 / Agent 工作监控 / 记忆管理 / 人工审批 / 报告。
 * 当前窗口的任务由对话内弹窗处理，这里只承接「其它任务与系统告警」。
 *
 * 防打扰规则（与 DESIGN §11.8 审批疲劳治理一致）：
 * - 有待办就展开（高优先级额外标亮），没有待办时保持收起；
 * - 10 分钟内最多自动弹出一次；
 * - 「稍后」静默 30 分钟；
 * - 流式回答期间冻结自动弹出，避免打断推理。
 */

import { useCallback, useEffect, useRef, useState } from "react";

const POLL_MS = 15_000;
const AUTO_OPEN_COOLDOWN_MS = 10 * 60 * 1000;
const SNOOZE_MS = 30 * 60 * 1000;

export type GovernanceSource =
  | "gate"
  | "monitor"
  | "memory"
  | "approval"
  | "report";

export interface GovernanceItem {
  key: string;
  source: GovernanceSource;
  source_label: string;
  title: string;
  detail?: string;
  high: boolean;
  waiting_minutes: number;
  requested_at: number;
  href: string;
  task_id?: string;
  gate_id?: string;
  gate_title?: string;
}

interface FeedItem {
  key: string;
  source: GovernanceSource;
  source_label: string;
  title: string;
  detail?: string;
  priority: "high" | "normal";
  href: string;
  created_at: number;
  task_id?: string;
  gate_id?: string;
  gate_title?: string;
}

export interface GovernanceInbox {
  items: GovernanceItem[];
  total: number;
  highCount: number;
  taskCount: number;
  loading: boolean;
  lastSyncedAt: number;
  /** 新到消息（用于标亮），抽屉打开后调用 markAllRead 清除 */
  newKeys: string[];
  /** 每次触发自动弹出时递增；页面据此展开抽屉 */
  autoOpenSignal: number;
  markAllRead: () => void;
  snooze: () => void;
  refresh: () => void;
}

function normalize(item: FeedItem, now: number): GovernanceItem {
  return {
    key: item.key,
    source: item.source,
    source_label: item.source_label,
    title: item.title,
    detail: item.detail,
    high: item.priority === "high",
    waiting_minutes: Math.max(
      0,
      Math.floor((now - (item.created_at || now)) / 60_000),
    ),
    requested_at: item.created_at,
    href: item.href,
    task_id: item.task_id,
    gate_id: item.gate_id,
    gate_title: item.gate_title,
  };
}

export function useGovernanceInbox({
  paused = false,
  excludeTaskIds = [],
}: { paused?: boolean; excludeTaskIds?: string[] } = {}): GovernanceInbox {
  const [items, setItems] = useState<GovernanceItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [lastSyncedAt, setLastSyncedAt] = useState(0);
  const [newKeys, setNewKeys] = useState<string[]>([]);
  const [autoOpenSignal, setAutoOpenSignal] = useState(0);

  const knownRef = useRef<Set<string>>(new Set());
  const baselineRef = useRef(false);
  const lastAutoRef = useRef(0);
  const snoozeUntilRef = useRef(0);
  const pausedRef = useRef(paused);
  const excludeRef = useRef(excludeTaskIds);
  const mountedRef = useRef(true);

  useEffect(() => {
    pausedRef.current = paused;
  }, [paused]);

  useEffect(() => {
    excludeRef.current = excludeTaskIds;
  }, [excludeTaskIds]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const apply = useCallback((feed: FeedItem[]) => {
    const now = Date.now();
    const exclude = new Set(excludeRef.current.filter(Boolean));
    const next = feed
      .filter((item) => !(item.task_id && exclude.has(item.task_id)))
      .map((item) => normalize(item, now));
    const fresh = next.filter((item) => !knownRef.current.has(item.key));
    for (const item of next) knownRef.current.add(item.key);

    if (!baselineRef.current) {
      baselineRef.current = true;
      setItems(next);
      setLastSyncedAt(now);
      // 首次加载就有待办：直接展开，避免「审批抽屉不存在」的错觉
      if (
        next.length > 0 &&
        !pausedRef.current &&
        now >= snoozeUntilRef.current
      ) {
        lastAutoRef.current = now;
        setAutoOpenSignal((value) => value + 1);
      }
      return;
    }

    if (fresh.length > 0) {
      setNewKeys((prev) => [
        ...new Set([...prev, ...fresh.map((item) => item.key)]),
      ]);
      const canAutoOpen =
        !pausedRef.current &&
        now >= snoozeUntilRef.current &&
        now - lastAutoRef.current >= AUTO_OPEN_COOLDOWN_MS;
      if (canAutoOpen) {
        lastAutoRef.current = now;
        setAutoOpenSignal((value) => value + 1);
      }
    }

    setItems(next);
    setLastSyncedAt(now);
  }, []);

  const refresh = useCallback(async () => {
    try {
      const response = await fetch("/api/governance/feed", {
        cache: "no-store",
      });
      const data = (await response.json().catch(() => null)) as
        | { success?: boolean; items?: FeedItem[] }
        | null;
      if (!response.ok || !data?.success) return;
      if (mountedRef.current) apply(Array.isArray(data.items) ? data.items : []);
    } catch {
      // 网络抖动：保留上一次结果，不打断当前工作
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, [apply]);

  useEffect(() => {
    void refresh();
    const timer = setInterval(() => {
      void refresh();
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  const markAllRead = useCallback(() => setNewKeys([]), []);
  const snooze = useCallback(() => {
    snoozeUntilRef.current = Date.now() + SNOOZE_MS;
  }, []);

  return {
    items,
    total: items.length,
    highCount: items.filter((item) => item.high).length,
    taskCount: new Set(items.map((item) => item.task_id).filter(Boolean)).size,
    loading,
    lastSyncedAt,
    newKeys,
    autoOpenSignal,
    markAllRead,
    snooze,
    refresh,
  };
}
