/** SPEC-52 F5 — 读取本地 DSH profile 的已安装插件 */
import { NextRequest, NextResponse } from 'next/server';
import { listDshProfile } from '@/lib/dsh/plugins';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const profile = request.nextUrl.searchParams.get('profile') || 'sandbox';
  try {
    return NextResponse.json({ ok: true, data: await listDshProfile(profile) });
  } catch (e) {
    return NextResponse.json(
      {
        ok: false,
        data: null,
        error: { code: 'DSH_PROFILE_UNAVAILABLE', message: e instanceof Error ? e.message : '读取 profile 失败' },
      },
      { status: 503 },
    );
  }
}
