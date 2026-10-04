import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import path from "path";
import { prisma } from "@/lib/prisma-data-hub";

export const dynamic = "force-dynamic";

/**
 * GET /api/ops/traces — L1 可观测性试点 (SPEC-20260929)
 *
 * Query 参数:
 *   ?trace_id=xxx        按 trace_id 精确查询 (返回跨系统完整事件列表)
 *   ?date=YYYY-MM-DD     按日期过滤 (默认今天)
 *   ?system=frontend     按系统过滤 (frontend|dreamos|dsh|hub)
 *   ?limit=N             返回上限 (默认 200, 最大 2000)
 *   ?source=pg|jsonl     强制指定数据源 (默认 pg, 失败时 fallback jsonl)
 *
 * 数据源优先级: PostgreSQL (物化视图) > JSONL (SSOT fallback)
 */

interface TraceEvent {
  v: number;
  id: string;
  trace_id: string;
  span_id?: string;
  parent_span_id?: string | null;
  ts: string;
  system: string;
  layer: string;
  node?: string;
  event_type: string;
  status: string;
  duration_ms?: number | null;
  payload_ref?: string | null;
  error?: string | null;
  meta?: Record<string, unknown>;
}

const SYSTEMS = ["frontend", "dreamos", "dsh", "hub"] as const;

/**
 * 统一 events root 解析 (P1)
 * 优先级: WORKBUDDY_EVENTS_ROOT 环境变量 > ~/.workbuddy/events (monitor-bus 落盘位置)
 */
function eventsRoot(): string {
  if (process.env.WORKBUDDY_EVENTS_ROOT) return process.env.WORKBUDDY_EVENTS_ROOT;
  const os = require("os");
  return path.join(os.homedir(), ".workbuddy", "events");
}

function todayDate(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function readJsonlFile(filePath: string): TraceEvent[] {
  if (!fs.existsSync(filePath)) return [];
  const lines: TraceEvent[] = [];
  try {
    const raw = fs.readFileSync(filePath, "utf-8");
    for (const line of raw.split("\n")) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      try {
        lines.push(JSON.parse(trimmed) as TraceEvent);
      } catch { /* skip corrupted line */ }
    }
  } catch { /* file read error */ }
  return lines;
}

// ============================================================================
// PostgreSQL 查询
// ============================================================================

async function queryFromPostgreSQL(
  traceId: string,
  date: string,
  system: string,
  limit: number
): Promise<TraceEvent[]> {
  const events: TraceEvent[] = [];

  // 查询 dreamos_sessions
  if (!system || system === "dreamos") {
    const sessions = await prisma.dreamosSession.findMany({
      where: {
        ...(traceId ? { traceId } : {}),
        startTs: {
          gte: new Date(`${date}T00:00:00Z`),
          lt: new Date(`${date}T23:59:59Z`),
        },
      },
      include: { spans: true },
      orderBy: { startTs: "asc" },
      take: limit,
    });

    for (const s of sessions) {
      events.push({
        v: 1,
        id: `sess_${s.id}`,
        trace_id: s.traceId,
        ts: s.startTs.toISOString(),
        system: "dreamos",
        layer: "graph",
        node: s.graphName,
        event_type: "graph_execute",
        status: s.status === "completed" ? "ok" : s.status === "failed" ? "fail" : "ok",
        duration_ms: s.durationMs,
        meta: {
          session_id: s.sessionId,
          total_nodes: s.totalNodes,
          executed_nodes: s.executedNodes,
          budget_tokens: s.budgetTokens,
          used_tokens: s.usedTokens,
          termination_reason: s.terminationReason,
          ...((s.extra as Record<string, unknown>) || {}),
        },
      });

      for (const span of s.spans) {
        events.push({
          v: 1,
          id: `span_${span.id}`,
          trace_id: span.traceId,
          span_id: span.spanId,
          parent_span_id: span.parentSpanId,
          ts: span.startTs.toISOString(),
          system: "dreamos",
          layer: "node",
          node: span.nodeId,
          event_type: "node.execute",
          status: span.status,
          duration_ms: span.durationMs,
          error: span.errorMessage,
          meta: {
            node_type: span.nodeType,
            allocated_tokens: span.allocatedTokens,
            used_tokens: span.usedTokens,
            confidence: span.confidence ? Number(span.confidence) : null,
            ...((span.meta as Record<string, unknown>) || {}),
          },
        });
      }
    }
  }

  // 查询 dsh_subagent_calls
  if (!system || system === "dsh") {
    const calls = await prisma.dshSubagentCall.findMany({
      where: {
        ...(traceId ? { traceId } : {}),
        createdAt: {
          gte: new Date(`${date}T00:00:00Z`),
          lt: new Date(`${date}T23:59:59Z`),
        },
      },
      orderBy: { createdAt: "asc" },
      take: limit,
    });

    for (const c of calls) {
      events.push({
        v: 1,
        id: `dsh_${c.id}`,
        trace_id: c.traceId,
        ts: c.createdAt.toISOString(),
        system: "dsh",
        layer: "bridge",
        node: c.subagentType,
        event_type: "subagent_call",
        status: c.status,
        duration_ms: c.durationMs,
        error: c.errorMessage,
        meta: {
          subagent_type: c.subagentType,
          request: c.requestPayload,
          response: c.responsePayload,
        },
      });
    }
  }

  return events;
}

// ============================================================================
// JSONL 查询 (fallback)
// ============================================================================

function queryFromJsonl(
  traceId: string,
  date: string,
  system: string,
  limit: number
): TraceEvent[] {
  const systemsToScan = system
    ? [system as (typeof SYSTEMS)[number]]
    : [...SYSTEMS];

  const allEvents: TraceEvent[] = [];

  for (const sys of systemsToScan) {
    const filePath = path.join(eventsRoot(), sys, `${date}.jsonl`);
    const events = readJsonlFile(filePath);
    if (traceId) {
      allEvents.push(...events.filter((e) => e.trace_id === traceId));
    } else {
      allEvents.push(...events);
    }
  }

  allEvents.sort((a, b) => a.ts.localeCompare(b.ts));
  return allEvents.slice(0, limit);
}

// ============================================================================
// API Handler
// ============================================================================

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const traceId = searchParams.get("trace_id") || "";
    const date = searchParams.get("date") || todayDate();
    const system = searchParams.get("system") || "";
    const limit = Math.min(parseInt(searchParams.get("limit") || "200", 10), 2000);
    const source = searchParams.get("source") || "pg"; // pg | jsonl

    let events: TraceEvent[] = [];
    let actualSource = source;

    if (source === "pg") {
      try {
        events = await queryFromPostgreSQL(traceId, date, system, limit);
      } catch (pgError) {
        console.warn("[ops/traces] PostgreSQL query failed, falling back to JSONL:", pgError);
        actualSource = "jsonl";
        events = queryFromJsonl(traceId, date, system, limit);
      }
    } else {
      events = queryFromJsonl(traceId, date, system, limit);
    }

    // 按 ts 排序 (时间戳正序)
    events.sort((a, b) => a.ts.localeCompare(b.ts));

    const limited = events.slice(0, limit);

    // 构建 timeline 摘要
    const systemsFound = [...new Set(limited.map((e) => e.system))];
    const layersFound = [...new Set(limited.map((e) => e.layer))];
    const errors = limited.filter((e) => e.status === "fail");
    const totalDuration = limited.reduce(
      (sum, e) => sum + (e.duration_ms || 0),
      0
    );

    return NextResponse.json({
      success: true,
      data: {
        events: limited,
        total: limited.length,
        trace_id: traceId || undefined,
        date,
        source: actualSource,
        summary: {
          systems: systemsFound,
          layers: layersFound,
          error_count: errors.length,
          total_duration_ms: totalDuration,
          first_event_ts: limited[0]?.ts || null,
          last_event_ts: limited[limited.length - 1]?.ts || null,
        },
      },
    });
  } catch (err) {
    return NextResponse.json(
      { success: false, error: String(err) },
      { status: 500 }
    );
  }
}
