/**
 * GET /api/user-memory/health
 * 用户层记忆健康检查 + 物理隔离验证。
 *
 * 验证项:
 *  - status: healthy
 *  - physical_isolation: true（user_memory.db 内无 VM- 前缀记录）
 *  - counts: preferences / notes
 *
 * FAIL-OPEN: 后端不可达返回 503 + {degraded: true}。
 */
import { NextResponse } from 'next/server';
import { callUserMemory, type UserMemoryHealth } from '@/lib/user-memory-client';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET() {
  const result = await callUserMemory<UserMemoryHealth>('health', {});

  if (!result.ok) {
    return NextResponse.json(
      { degraded: true, error: result.error, traceback: result.traceback },
      { status: 503 }
    );
  }
  return NextResponse.json(result.data);
}
