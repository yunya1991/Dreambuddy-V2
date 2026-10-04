/**
 * /api/user-memory/preferences
 *  - GET  : 读取当前用户所有偏好
 *  - POST : 写入/更新偏好（key + value）
 *
 * FAIL-OPEN: 后端不可达返回 503 + {degraded: true}。
 * runtime='nodejs' + force-dynamic（P0 实测验证必加）。
 */
import { NextResponse } from 'next/server';
import { callUserMemory, type UserPreference } from '@/lib/user-memory-client';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(req: Request) {
  const url = new URL(req.url);
  const user_id = url.searchParams.get('user_id') || 'default';
  const result = await callUserMemory<{ preferences: UserPreference[]; count: number }>('get_prefs', { user_id });

  if (!result.ok) {
    return NextResponse.json(
      { degraded: true, error: result.error, traceback: result.traceback },
      { status: 503 }
    );
  }
  return NextResponse.json(result.data);
}

export async function POST(req: Request) {
  let body: { user_id?: string; key?: string; value?: string };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: 'invalid JSON body' }, { status: 400 });
  }

  if (!body.key) {
    return NextResponse.json({ error: 'missing required field: key' }, { status: 400 });
  }

  const result = await callUserMemory('set_pref', {
    user_id: body.user_id || 'default',
    key: body.key,
    value: body.value ?? '',
  });

  if (!result.ok) {
    return NextResponse.json(
      { degraded: true, error: result.error, traceback: result.traceback },
      { status: 503 }
    );
  }
  return NextResponse.json(result.data);
}
