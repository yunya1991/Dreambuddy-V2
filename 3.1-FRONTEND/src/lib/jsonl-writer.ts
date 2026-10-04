/**
 * JSONL 事件写入器 — SPEC-20260929-L1-TRACE-PILOT
 *
 * 把统一事件写入 ~/.workbuddy/events/{system}/{YYYY-MM-DD}.jsonl
 * - append-only, 按日期滚动
 * - 失败兜底 console.warn, 不阻断业务
 * - 全局开关: MONITOR_JSONL_DISABLE=1 时跳过写入
 *
 * 服务端专用 (依赖 node:fs)
 */

import fs from 'fs';
import path from 'path';
import os from 'os';

export type JsonlSystem = 'frontend' | 'dreamos' | 'dsh' | 'hub';

export interface JsonlEvent {
  v: 1;
  id: string;
  trace_id: string;
  span_id?: string;
  parent_span_id?: string | null;
  ts: string;                    // ISO8601
  system: JsonlSystem;
  layer: string;
  node?: string;
  event_type: string;
  status: 'ok' | 'fail' | 'skip';
  duration_ms?: number;
  payload_ref?: string | null;
  error?: string | null;
  meta?: Record<string, unknown>;
}

/**
 * 统一 events root 解析 (P1)
 * 优先级: WORKBUDDY_EVENTS_ROOT > dreambuddy-v2/events
 * 注意: 前端 cwd = 3.1-FRONTEND, 所以 ../events = dreambuddy-v2/events
 */
function getEventsRoot(): string {
  if (process.env.WORKBUDDY_EVENTS_ROOT) return process.env.WORKBUDDY_EVENTS_ROOT;
  return path.resolve(process.cwd(), '..', 'events');
}

function getTodayFileName(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}.jsonl`;
}

function ensureDir(dir: string): void {
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
}

/**
 * 同步追加写入 JSONL 事件 (单行 JSON + \n)
 * 失败兜底: console.warn, 不抛出
 */
export function writeJsonlEvent(event: JsonlEvent): void {
  if (process.env.MONITOR_JSONL_DISABLE === '1') return;
  try {
    const dir = path.join(getEventsRoot(), event.system);
    ensureDir(dir);
    const file = path.join(dir, getTodayFileName());
    const line = JSON.stringify(event) + '\n';
    fs.appendFileSync(file, line, 'utf-8');
  } catch (err) {
    // 降级: 不阻断业务
    console.warn('[jsonl-writer] write failed:', (err as Error).message);
  }
}

/**
 * 生成 span_id (8 位随机)
 */
export function genSpanId(): string {
  return Math.random().toString(36).slice(2, 10);
}

/**
 * 生成事件 id (uuid v4 简化版)
 */
export function genEventId(): string {
  return `evt_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
}
