/**
 * POST /api/user-memory/notes/[id]/promote
 * 用户笔记沉淀审批流 (P3 Step 5):
 *  - Step 1: 从 user_memory.db 取笔记 content (callUserMemory list_notes)
 *  - Step 2: 调 callCognitive('record', ...) 写入 VM-* (平台层 cognitive_memory.db)
 *  - Step 3: 调 callUserMemory('mark_promoted', ...) 标记原笔记 promoted_to (用户层)
 *  - 原笔记保留不删除 (硬约束 VM-1786242777697)
 *
 * 硬约束 (SPEC-COG-P1P3 §4.4):
 *  - 必须用户主动 POST, 禁止定时任务自动迁移
 *  - 沉淀后原 user:note:* 保留 (标记 promoted_to), 不删除
 *
 * Body:
 *   quality_level (default "B") - S/A/B/C/D
 *   tags (string, comma-separated)
 *
 * FAIL-OPEN: 任一后端不可达返回 503 + {degraded: true}
 */
import { NextResponse } from 'next/server';
import { callCognitive } from '@/lib/cognitive-client';
import { callUserMemory, type UserNote } from '@/lib/user-memory-client';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!id) {
    return NextResponse.json({ error: 'missing note id' }, { status: 400 });
  }

  let body: { quality_level?: string; tags?: string };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: 'invalid JSON body' }, { status: 400 });
  }

  const qualityLevel = String(body.quality_level || 'B');
  const tags = String(body.tags || '');

  // Step 1: 从 user_memory.db 取笔记 content
  const listResult = await callUserMemory<{ notes: UserNote[]; count: number }>('list_notes', { user_id: 'default' });
  if (!listResult.ok || !listResult.data || !listResult.data.notes) {
    return NextResponse.json(
      { degraded: true, error: listResult.error, traceback: listResult.traceback },
      { status: 503 }
    );
  }
  const note = listResult.data.notes.find(n => n.id === id);
  if (!note || !note.content) {
    return NextResponse.json({ error: 'note not found or empty content' }, { status: 404 });
  }

  // Step 2: 调 cognitive record 写入 VM-* (平台层)
  const recordContent = note.title ? `${note.title}\n\n${note.content}` : note.content;
  const recordResult = await callCognitive<{ memory_id?: string; id?: string }>('record', {
    content: recordContent,
    quality_level: qualityLevel,
    tags,
  });
  if (!recordResult.ok || !recordResult.data) {
    return NextResponse.json(
      { degraded: true, error: recordResult.error, traceback: recordResult.traceback },
      { status: 503 }
    );
  }
  const promotedTo = recordResult.data.memory_id || recordResult.data.id || '';
  if (!promotedTo) {
    return NextResponse.json(
      { degraded: true, error: 'record returned no memory_id' },
      { status: 502 }
    );
  }

  // Step 3: 标记原笔记 promoted_to (用户层, 保留不删除)
  const markResult = await callUserMemory<{ id: string; promoted_to: string; updated: number }>(
    'mark_promoted',
    { id, promoted_to: promotedTo }
  );
  if (!markResult.ok || !markResult.data) {
    // VM 已写入但用户层标记失败 — 部分成功, 返回 warning
    return NextResponse.json(
      {
        degraded: true,
        error: markResult.error,
        traceback: markResult.traceback,
        promoted_to: promotedTo,
        warning: 'VM written but user note mark failed',
      },
      { status: 503 }
    );
  }

  return NextResponse.json({
    note_id: id,
    promoted_to: promotedTo,
    marked: markResult.data,
  });
}
