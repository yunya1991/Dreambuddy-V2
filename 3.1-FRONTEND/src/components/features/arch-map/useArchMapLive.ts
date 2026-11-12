'use client';

/**
 * 架构工程地图 — 运行时点亮（M1）
 *
 * 数据源：monitor-stream-manager 单例 SSE（`/api/monitor/stream`，零新增后端）
 * 映射优先级（SPEC §3.4）：event.extra.cap_id → phase_map[event.phase] → layer_default[event.layer]
 * 节点态：active(<30s) / failed(<30s) / warm(<5min) / idle
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { subscribeMonitor, subscribeMonitorStatus } from '@/lib/stream/monitor-stream-manager';
import type {
  ArchCapRuntime,
  ArchMapRuntimeExport,
  ArchNodeState,
  CapMapData,
} from '@/lib/arch-map/types';

const ACTIVE_MS = 30_000;
const WARM_MS = 5 * 60_000;
const FLUSH_MS = 200;
const TICK_MS = 1_000;

interface MonitorLiteEvent {
  type?: string;
  layer?: string;
  phase?: string;
  status?: string;
  duration_ms?: number;
  extra?: Record<string, unknown>;
}

export function stateOf(runtime: ArchCapRuntime | undefined, now: number): ArchNodeState {
  if (!runtime) return 'idle';
  const age = now - runtime.lastAt;
  if (age < ACTIVE_MS) {
    return runtime.lastFailedAt && now - runtime.lastFailedAt < ACTIVE_MS ? 'failed' : 'active';
  }
  if (age < WARM_MS) return 'warm';
  return 'idle';
}

interface ArchCapRuntimeInternal extends ArchCapRuntime {
  lastFailedAt?: number;
}

function resolveCaps(event: MonitorLiteEvent, capMap: CapMapData) {
  const out: string[] = [];
  const raw = event.extra?.cap_id;
  const push = (v: unknown) => {
    if (typeof v === 'string' && v) out.push(v);
  };
  if (Array.isArray(raw)) raw.forEach(push);
  else push(raw);
  if (out.length > 0) return out;
  const byPhase = event.phase ? capMap.phase_map[event.phase] : undefined;
  if (byPhase?.length) return byPhase;
  const byLayer = event.layer ? capMap.layer_default[event.layer] : undefined;
  return byLayer ?? [];
}

export function useArchMapLive(capMap: CapMapData) {
  const [caps, setCaps] = useState<Record<string, ArchCapRuntimeInternal>>({});
  const [ghosts, setGhosts] = useState<Record<string, number>>({});
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());

  const pending = useRef<Record<string, Partial<ArchCapRuntimeInternal>>>({});
  const pendingGhosts = useRef<Record<string, number>>({});
  const known = useRef<Set<string>>(new Set(capMap.cap_ids));
  const since = useRef<string>(new Date().toISOString());

  useEffect(() => {
    known.current = new Set(capMap.cap_ids);
  }, [capMap]);

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), TICK_MS);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    let flushTimer: ReturnType<typeof setInterval> | null = null;

    const flush = () => {
      const batched = pending.current;
      const ghostBatch = pendingGhosts.current;
      pending.current = {};
      pendingGhosts.current = {};
      if (Object.keys(batched).length === 0 && Object.keys(ghostBatch).length === 0) return;
      setCaps((prev) => {
        const next = { ...prev };
        for (const [cap, delta] of Object.entries(batched)) {
          const base =
            next[cap] ?? { hits: 0, completed: 0, failed: 0, lastAt: 0 };
          next[cap] = {
            hits: base.hits + (delta.hits ?? 0),
            completed: base.completed + (delta.completed ?? 0),
            failed: base.failed + (delta.failed ?? 0),
            lastAt: Math.max(base.lastAt, delta.lastAt ?? 0),
            lastFailedAt: Math.max(base.lastFailedAt ?? 0, delta.lastFailedAt ?? 0),
            lastDurationMs: delta.lastDurationMs ?? base.lastDurationMs,
          };
        }
        return next;
      });
      if (Object.keys(ghostBatch).length > 0) {
        setGhosts((prev) => {
          const next = { ...prev };
          for (const [cap, n] of Object.entries(ghostBatch)) next[cap] = (next[cap] ?? 0) + n;
          return next;
        });
      }
    };

    const handle = (event: MonitorLiteEvent) => {
      if (!event || event.type === 'connected' || event.type === 'system') return;
      if (!event.layer && !event.phase) return;

      const capIds = resolveCaps(event, capMap);
      if (capIds.length === 0) return;

      const ts = Date.now();
      const failedStatus = event.status === 'failed' || event.status === 'timeout' || event.status === 'denied';
      const completedStatus = event.status === 'completed';
      for (const capId of capIds) {
        if (!known.current.has(capId)) {
          pendingGhosts.current[capId] = (pendingGhosts.current[capId] ?? 0) + 1;
          continue;
        }
        const slot = (pending.current[capId] ??= {});
        slot.hits = (slot.hits ?? 0) + 1;
        slot.lastAt = Math.max(slot.lastAt ?? 0, ts);
        if (failedStatus) {
          slot.failed = (slot.failed ?? 0) + 1;
          slot.lastFailedAt = Math.max(slot.lastFailedAt ?? 0, ts);
        }
        if (completedStatus) slot.completed = (slot.completed ?? 0) + 1;
        if (typeof event.duration_ms === 'number') slot.lastDurationMs = event.duration_ms;
      }
    };

    // 订阅 monitor 单例流：与监控页/交易页共享同一条 EventSource
    const unsubscribe = subscribeMonitor((event) => handle(event as MonitorLiteEvent));
    const unsubscribeStatus = subscribeMonitorStatus((s) => {
      const isOpen = s === 'open';
      setConnected(isOpen);
      setError(s === 'reconnecting' ? 'SSE 连接中断（将自动重连）' : null);
      if (isOpen) since.current = new Date().toISOString();
    });
    flushTimer = setInterval(flush, FLUSH_MS);

    return () => {
      if (flushTimer) clearInterval(flushTimer);
      unsubscribe();
      unsubscribeStatus();
    };
  }, [capMap]);

  const reset = useCallback(() => {
    pending.current = {};
    pendingGhosts.current = {};
    setCaps({});
    setGhosts({});
    since.current = new Date().toISOString();
  }, []);

  const hydrate = useCallback((payload: ArchMapRuntimeExport) => {
    const next: Record<string, ArchCapRuntimeInternal> = {};
    for (const [cap, v] of Object.entries(payload.caps ?? {})) {
      const lastAt = Date.parse(v.last_at);
      next[cap] = {
        hits: v.hits ?? 0,
        completed: v.completed ?? 0,
        failed: v.failed ?? 0,
        lastAt: Number.isNaN(lastAt) ? Date.now() : lastAt,
        lastDurationMs: v.last_duration_ms,
      };
    }
    setCaps(next);
    setGhosts(payload.ghosts ?? {});
    since.current = payload.since ?? new Date().toISOString();
  }, []);

  const buildExport = useCallback((): ArchMapRuntimeExport => {
    const capsOut: ArchMapRuntimeExport['caps'] = {};
    for (const [cap, v] of Object.entries(caps)) {
      capsOut[cap] = {
        hits: v.hits,
        completed: v.completed,
        failed: v.failed,
        last_at: new Date(v.lastAt || Date.now()).toISOString(),
        last_duration_ms: v.lastDurationMs,
      };
    }
    return {
      schema: 'ArchMapRuntime/v1',
      exported_at: new Date().toISOString(),
      since: since.current,
      caps: capsOut,
      ghosts,
    };
  }, [caps, ghosts]);

  const stateMap: Record<string, ArchNodeState> = {};
  for (const [cap, runtime] of Object.entries(caps)) {
    stateMap[cap] = stateOf(runtime, now);
  }

  return {
    caps,
    ghosts,
    stateMap,
    connected,
    error,
    now,
    reset,
    hydrate,
    buildExport,
  };
}
