/**
 * GET /api/cognitive/recall
 * 检索认知记忆（包裹 MCP stdio recall 为 HTTP）。
 *
 * Query:
 *   context (required) - 任务描述或关键词
 *   top_k (default 5)
 *   min_quality (default "C") - S/A/B/C/D
 *
 * FAIL-OPEN: 后端不可达返回 503 + {degraded: true}, 不抛异常。
 */
import { NextRequest, NextResponse } from 'next/server';
import { callCognitive } from '@/lib/cognitive-client';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(req: NextRequest) {
  const context = req.nextUrl.searchParams.get('context') || '';
  const topKRaw = req.nextUrl.searchParams.get('top_k') || '5';
  const minQuality = req.nextUrl.searchParams.get('min_quality') || 'C';

  if (!context) {
    return NextResponse.json(
      { degraded: true, error: 'missing context param' },
      { status: 400 }
    );
  }

  const topK = Math.max(1, Math.min(50, parseInt(topKRaw, 10) || 5));

  const result = await callCognitive('recall', { context, top_k: topK, min_quality: minQuality });

  if (!result.ok) {
    return NextResponse.json(
      { degraded: true, error: result.error, traceback: result.traceback },
      { status: 503 }
    );
  }

  return NextResponse.json(result.data);
}
