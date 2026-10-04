/**
 * GET /api/cognitive/stats
 * 获取记忆系统统计（包裹 MCP stdio stats 为 HTTP）。
 *
 * FAIL-OPEN: 后端不可达返回 503 + {degraded: true}。
 */
import { NextResponse } from 'next/server';
import { callCognitive } from '@/lib/cognitive-client';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET() {
  const result = await callCognitive('stats', {});

  if (!result.ok) {
    return NextResponse.json(
      { degraded: true, error: result.error, traceback: result.traceback },
      { status: 503 }
    );
  }

  return NextResponse.json(result.data);
}
