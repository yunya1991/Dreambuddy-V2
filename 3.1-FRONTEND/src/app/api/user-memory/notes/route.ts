/**
 * /api/user-memory/notes
 *  - GET  : 列出当前用户所有笔记
 *  - POST : 创建新笔记
 *
 * FAIL-OPEN: 后端不可达返回 503 + {degraded: true}。
 */
import { NextResponse } from 'next/server';
import { callUserMemory, type UserNote } from '@/lib/user-memory-client';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(req: Request) {
  const url = new URL(req.url);
  const user_id = url.searchParams.get('user_id') || 'default';
  const result = await callUserMemory<{ notes: UserNote[]; count: number }>('list_notes', { user_id });

  if (!result.ok) {
    return NextResponse.json(
      { degraded: true, error: result.error, traceback: result.traceback },
      { status: 503 }
    );
  }
  return NextResponse.json(result.data);
}

export async function POST(req: Request) {
  let body: { user_id?: string; title?: string; content?: string; tags?: string };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: 'invalid JSON body' }, { status: 400 });
  }

  if (!body.content) {
    return NextResponse.json({ error: 'missing required field: content' }, { status: 400 });
  }

  const result = await callUserMemory('create_note', {
    user_id: body.user_id || 'default',
    title: body.title || '',
    content: body.content,
    tags: body.tags || '',
  });

  if (!result.ok) {
    return NextResponse.json(
      { degraded: true, error: result.error, traceback: result.traceback },
      { status: 503 }
    );
  }
  return NextResponse.json(result.data);
}
