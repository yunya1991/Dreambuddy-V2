/**
 * /api/dreamos — 前端 → DreamOS 桥接端点（S2）
 * 20260829-bridge
 *
 * POST 同步/异步编排：
 *   body: { query: string, symbol?: string, price?: number,
 *           mode?: "sync"|"async"（默认 async）,
 *           intent_hint?: object, intent_type?: string（正典意图名） }
 *   mode=async → { ok, cycle_id, status:"accepted" }（立即返回，前端轮询）
 *   mode=sync  → { ok, action, confidence, rationale, ... }（降级兜底）
 *
 * GET 轮询：?cycle_id=xxx → { ok, status, result? }
 * GET 健康：?health=1 → DreamOS health/status
 *
 * 纪律：只读分析桥（无下单副作用）；行情装配与 MCP 桥对齐
 *   （symbol→coin 双写，缺价格时不注入、由 DreamOS 侧降级）。
 */
import { NextRequest, NextResponse } from "next/server";
import { dreamos, type DreamOSRunPayload } from "@/lib/dreamos/client";

export const runtime = "nodejs";
export const maxDuration = 200; // 秒；仅 sync 模式会贴到上限

function fail(message: string, status = 400) {
  return NextResponse.json({ ok: false, error: message }, { status });
}

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);

  if (searchParams.get("health") !== null) {
    try {
      const [health, status] = await Promise.all([dreamos.health(), dreamos.status()]);
      return NextResponse.json({ ok: true, health, status });
    } catch (e) {
      return fail(`DreamOS 不可达: ${e instanceof Error ? e.message : String(e)}`, 502);
    }
  }

  const cycleId = searchParams.get("cycle_id");
  if (!cycleId) return fail("缺少 cycle_id（或传 ?health=1）");
  try {
    const r = await dreamos.getResult(cycleId);
    return NextResponse.json({ ok: true, ...r });
  } catch (e) {
    return fail(`轮询失败: ${e instanceof Error ? e.message : String(e)}`, 502);
  }
}

export async function POST(req: NextRequest) {
  let body: Record<string, unknown>;
  try {
    body = await req.json();
  } catch {
    return fail("请求体必须是 JSON");
  }

  const query = typeof body.query === "string" ? body.query.trim() : "";
  if (!query) return fail("缺少 query");

  const symbol = typeof body.symbol === "string" ? body.symbol.toUpperCase() : "BTC";
  const price = typeof body.price === "number" && body.price > 0 ? body.price : undefined;
  const mode = body.mode === "sync" ? "sync" : "async";
  const canonIntent = typeof body.intent_type === "string" ? body.intent_type : undefined;

  // 行情装配（与 MCP 桥 dreamos_run_analysis 对齐：symbol/coin 双写）
  const marketData: Record<string, unknown> = { symbol, coin: symbol };
  if (price !== undefined) marketData.price = price;

  const payload: DreamOSRunPayload = {
    user_input: query,
    market_data: marketData,
    context: { source: "frontend_bridge", ...(canonIntent ? { canon_intent: canonIntent } : {}) },
  };

  // intent_hint：优先用调用方显式传入；否则若给了正典意图名则走映射表
  if (body.intent_hint && typeof body.intent_hint === "object") {
    payload.intent_hint = body.intent_hint as DreamOSRunPayload["intent_hint"];
  } else if (canonIntent) {
    const { lookupDreamOSDirective } = await import("@/lib/dreamos/intent-canon-map");
    const d = lookupDreamOSDirective(canonIntent);
    if (d) {
      payload.intent_hint = {
        intent_type: d.intent_type,
        confidence: d.confidence,
        chain: d.chain,
        provenance: "frontend_canon",
        canon_intent: canonIntent,
      };
    }
  }

  try {
    if (mode === "async") {
      const r = await dreamos.runAsync(payload);
      return NextResponse.json({ ok: true, mode: "async", ...r });
    }
    const r = await dreamos.run(payload);
    return NextResponse.json({
      ok: !r.error,
      mode: "sync",
      cycle_id: r.cycle_id,
      action: r.action,
      confidence: r.confidence,
      rationale: r.rationale,
      tokens_used: r.tokens_used,
      latency_ms: r.latency_ms,
      result: r,
    });
  } catch (e) {
    return fail(`DreamOS 编排失败: ${e instanceof Error ? e.message : String(e)}`, 502);
  }
}
