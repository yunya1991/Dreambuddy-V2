/**
 * POST /api/cognitive/verify
 * 验证记忆并触发贝叶斯置信度更新（包裹 MCP stdio verify 为 HTTP）。
 *
 * Body:
 *   memory_id (required) - VM-xxx
 *   success (boolean, default true)
 *
 * FAIL-OPEN: 后端不可达返回 503 + {degraded: true}。
 */
import { NextRequest, NextResponse } from 'next/server';
import { callCognitive } from '@/lib/cognitive-client';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function POST(req: NextRequest) {
  let body: Record<string, unknown>;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json(
      { degraded: true, error: 'invalid JSON body' },
      { status: 400 }
    );
  }

  const memoryId = String(body.memory_id || '').trim();
  if (!memoryId) {
    return NextResponse.json(
      { degraded: true, error: 'missing memory_id field' },
      { status: 400 }
    );
  }

  const success = body.success !== false;

  const result = await callCognitive('verify', { memory_id: memoryId, success });

  if (!result.ok) {
    return NextResponse.json(
      { degraded: true, error: result.error, traceback: result.traceback },
      { status: 503 }
    );
  }

  return NextResponse.json(result.data);
}
