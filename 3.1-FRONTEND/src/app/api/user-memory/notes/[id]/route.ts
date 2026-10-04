/**
 * /api/user-memory/notes/[id]
 *  - DELETE : 删除指定笔记
 *  - PATCH  : 标记笔记为已沉淀（promoted_to=VM-xxx），P3 审批流使用
 *
 * 硬约束 (VM-1786242777697):
 *  - 沉淀后原 user:note:* 保留（仅标记 promoted_to），不删除
 *  - 禁止自动迁移，必须人工触发
 *
 * FAIL-OPEN: 后端不可达返回 503 + {degraded: true}。
 */
import { NextResponse } from 'next/server';
import { callUserMemory } from '@/lib/user-memory-client';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function DELETE(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!id) {
    return NextResponse.json({ error: 'missing note id' }, { status: 400 });
  }
  const result = await callUserMemory('delete_note', { id });

  if (!result.ok) {
    return NextResponse.json(
      { degraded: true, error: result.error, traceback: result.traceback },
      { status: 503 }
    );
  }
  return NextResponse.json(result.data);
}

export async function PATCH(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let body: { promoted_to?: string };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: 'invalid JSON body' }, { status: 400 });
  }

  if (!body.promoted_to) {
    return NextResponse.json({ error: 'missing required field: promoted_to' }, { status: 400 });
  }

  const result = await callUserMemory('mark_promoted', { id, promoted_to: body.promoted_to });

  if (!result.ok) {
    return NextResponse.json(
      { degraded: true, error: result.error, traceback: result.traceback },
      { status: 503 }
    );
  }
  return NextResponse.json(result.data);
}
