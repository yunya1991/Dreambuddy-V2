/**
 * POST /api/dsh/execute
 * DSH 能力代理（SPEC-20261111-C §3.5 / T-C5）：仅 HTTP 转发，不 spawn、不直接 fs。
 *
 * Body: { capability: string, payload?: object, trace_id?: string }
 * 上游：`DSH_API_BASE`（未配置 → 503 + degraded:true，FAIL-OPEN）
 * 超时：60s
 *
 * 链路（GAP-2 trace_id 全链透传）：
 *   请求头 X-Request-Id / X-Trace-Id → body.trace_id → 上游请求头 → 上游响应 trace_id → 响应头 X-Request-Id
 */
import { NextRequest, NextResponse } from 'next/server';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const TIMEOUT_MS = 60_000;

/** 从请求头取链路 ID（api-client 统一用 X-Request-Id） */
function headerTraceId(req: NextRequest): string | undefined {
  return req.headers.get('x-request-id') ?? req.headers.get('x-trace-id') ?? undefined;
}

/** 统一出口：回显链路 ID，前端 envelope.trace_id 可继续沿链传递 */
function jsonWithTrace(body: unknown, status: number, traceId?: string) {
  return NextResponse.json(body, {
    status,
    ...(traceId ? { headers: { 'X-Request-Id': traceId } } : {}),
  });
}

export async function POST(req: NextRequest) {
  const inboundTraceId = headerTraceId(req);
  const base = process.env.DSH_API_BASE?.trim();
  if (!base) {
    return jsonWithTrace(
      { degraded: true, error: 'DSH_API_BASE 未配置，无法代理 DSH 能力' },
      503,
      inboundTraceId,
    );
  }

  const body = (await req.json().catch(() => null)) as
    | { capability?: unknown; payload?: unknown; trace_id?: unknown }
    | null;
  const capability = body?.capability;
  if (typeof capability !== 'string' || capability.length === 0) {
    return jsonWithTrace({ degraded: true, error: 'missing capability' }, 400, inboundTraceId);
  }

  const traceId =
    inboundTraceId ?? (typeof body?.trace_id === 'string' ? body.trace_id : undefined);

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  // 云端 /execute 开启 Bearer 鉴权后，代理也必须带同一 token（否则一律 401）
  const token = process.env.DSH_API_TOKEN?.trim();
  try {
    const upstream = await fetch(`${base.replace(/\/+$/, '')}/execute`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(traceId ? { 'X-Request-Id': traceId } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({
        capability,
        payload: body?.payload ?? {},
        trace_id: traceId,
      }),
      signal: controller.signal,
    });
    const data = await upstream.json().catch(() => ({}));
    const echoed =
      data && typeof data === 'object' && typeof (data as { trace_id?: unknown }).trace_id === 'string'
        ? (data as { trace_id: string }).trace_id
        : traceId;
    return jsonWithTrace(data, upstream.status, echoed);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return jsonWithTrace({ degraded: true, error: `upstream_error: ${message}` }, 504, traceId);
  } finally {
    clearTimeout(timer);
  }
}

/** 探活：是否已配置上游（前端据此展示「DSH 未连接」） */
export async function GET() {
  const configured = Boolean(process.env.DSH_API_BASE?.trim());
  return NextResponse.json({ configured, degraded: !configured }, { status: configured ? 200 : 503 });
}
