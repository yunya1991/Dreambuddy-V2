/** SPEC-52 F5/F7 — 插件启停审计 */
import { NextRequest, NextResponse } from 'next/server';
import { readPluginAudit } from '@/lib/plugins/registry';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const limitRaw = Number(request.nextUrl.searchParams.get('limit') ?? '50');
  const limit = Number.isFinite(limitRaw) ? Math.min(Math.max(Math.trunc(limitRaw), 1), 200) : 50;
  return NextResponse.json({ ok: true, data: await readPluginAudit(limit) });
}
