/**
 * GET /api/cognitive/health
 * 认知系统健康检查（包裹 MCP stdio health 为 HTTP）。
 *
 * FAIL-OPEN: 后端不可达返回 503 + {degraded: true}。
 */
import { NextResponse } from 'next/server';
import { callCognitive } from '@/lib/cognitive-client';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET() {
  const result = await callCognitive('health', {});

  if (!result.ok) {
    return NextResponse.json(
      { degraded: true, error: result.error, traceback: result.traceback },
      { status: 503 }
    );
  }

  return NextResponse.json(result.data);
}
