/**
 * GET /api/cognitive/l4
 * L4 元认知层状态聚合 — 供前端应用/训练系统查询。
 *
 * 返回 WorkspaceBus/SelfModel/PredictionErrorGate/ReflectionNode/MetacogHarness
 * 的实时状态 + 最近一次 recall/record/verify 的 L4 输出。
 *
 * FAIL-OPEN: 后端不可达返回 503 + {degraded: true}。
 */
import { NextResponse } from 'next/server';
import { callCognitive } from '@/lib/cognitive-client';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET() {
  const result = await callCognitive('l4_status', {});

  if (!result.ok) {
    return NextResponse.json(
      { degraded: true, error: result.error, traceback: result.traceback },
      { status: 503 }
    );
  }

  return NextResponse.json(result.data);
}
