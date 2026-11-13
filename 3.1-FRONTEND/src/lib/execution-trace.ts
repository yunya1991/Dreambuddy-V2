/**
 * 执行链 trace 台账（服务端，append-only JSONL）。
 *
 * 依据：SPEC-20261113-THREE-BUSINESS-CLOSED-LOOPS §6.4 + PLAN Phase 2（T2-1~T2-4）
 * 判定消费方：1-ARCHITECTURE/registry/scripts/bcl_gate_check.py G-BCL-3
 *   （按 task_id 聚合，要求 created/route/execute/accept/settle 五阶段齐全、同请求 trace 唯一）
 *
 * 台账路径：BCL_TRACE_RECORDS_PATH 环境变量优先，默认 <repo>/events/frontend/execution_chain_trace.jsonl
 * （前端进程 cwd=3.1-FRONTEND，故 `../events` = dreambuddy-v2/events）
 *
 * FAIL-OPEN：任何写入失败只告警，不阻断业务。
 */

import fs from 'fs';
import path from 'path';
import { newTraceId } from './trace-id';

export { newTraceId };

export type TraceStage = 'created' | 'route' | 'execute' | 'accept' | 'settle';

export interface TraceStageRecord {
  /** 关联任务；L1 直答无任务时为空串（G-BCL-3 对 L1 按 trace_id 聚合） */
  task_id: string;
  trace_id: string;
  stage: TraceStage;
  /** 入口：l1（/api/data/query）/ l2（/api/task/stream，缺省） */
  entry?: 'l1' | 'l2';
  /** true 表示该请求已交接给 L2，L1 侧记录不参与执行单元统计 */
  handoff?: boolean;
  /** 显式降级标记；降级项必须同时给出 degraded_reason */
  degraded?: boolean;
  intent?: string;
  /** 路由决策：l1_direct / l2_handoff / l2_direct */
  route_decision?: string;
  /** 降级原因；降级项必须非空 */
  degraded_reason?: string;
  /** 验收结论：pass / fail */
  verdict?: string;
  duration_ms?: number;
  meta?: Record<string, unknown>;
}

export function getTraceLedgerPath(): string {
  const fromEnv = process.env.BCL_TRACE_RECORDS_PATH;
  if (fromEnv) return fromEnv;
  return path.resolve(process.cwd(), '..', 'events', 'frontend', 'execution_chain_trace.jsonl');
}

export function traceStage(record: TraceStageRecord): void {
  try {
    const file = getTraceLedgerPath();
    fs.mkdirSync(path.dirname(file), { recursive: true });
    const row = {
      schema_version: 'v1',
      source: 'execution_chain',
      ts: new Date().toISOString(),
      ...record,
      task_id: record.task_id || '',
    };
    fs.appendFileSync(file, JSON.stringify(row) + '\n', 'utf-8');
  } catch (err) {
    console.warn('[execution-trace] write failed:', (err as Error).message);
  }
}
