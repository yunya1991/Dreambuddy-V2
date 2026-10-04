/**
 * POST /api/cognitive/record
 * 记录新经验到认知系统（包裹 MCP stdio record 为 HTTP）。
 *
 * Body:
 *   content (required) - 经验内容
 *   quality_level (default "C") - S/A/B/C/D
 *   tags (string, comma-separated)
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

  const content = String(body.content || '').trim();
  if (!content) {
    return NextResponse.json(
      { degraded: true, error: 'missing content field' },
      { status: 400 }
    );
  }

  const qualityLevel = String(body.quality_level || 'C');
  const tags = String(body.tags || '');

  const result = await callCognitive('record', {
    content,
    quality_level: qualityLevel,
    tags,
  });

  if (!result.ok) {
    return NextResponse.json(
      { degraded: true, error: result.error, traceback: result.traceback },
      { status: 503 }
    );
  }

  return NextResponse.json(result.data);
}
