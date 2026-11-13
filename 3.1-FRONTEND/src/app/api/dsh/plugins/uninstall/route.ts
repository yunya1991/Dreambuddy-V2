/** SPEC-52 F5 — 卸载：dsh plugin --profile <p> remove <pkg>（核心 bundle 保护） */
import { NextRequest, NextResponse } from 'next/server';
import { DshInstallError, uninstallDshPlugin } from '@/lib/dsh/plugins';
import { entitlementDeniedPayload, isEntitled } from '@/lib/product/entitlement';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export const maxDuration = 200;

export async function POST(request: NextRequest) {
  if (!isEntitled()) {
    return NextResponse.json(entitlementDeniedPayload(), { status: 403 });
  }

  let body: { id?: string; profile?: string };
  try {
    body = await request.json();
  } catch {
    body = {};
  }
  if (!body.id) {
    return NextResponse.json(
      { ok: false, data: null, error: { code: 'PLUGIN_ID_REQUIRED', message: '缺少插件 id' } },
      { status: 400 },
    );
  }

  try {
    const data = await uninstallDshPlugin(body.id, body.profile || 'sandbox');
    return NextResponse.json({ ok: true, data });
  } catch (e) {
    if (e instanceof DshInstallError) {
      return NextResponse.json(
        { ok: false, data: null, error: { code: e.code, message: e.message } },
        { status: 403 },
      );
    }
    return NextResponse.json(
      {
        ok: false,
        data: null,
        error: { code: 'PLUGIN_UNINSTALL_FAILED', message: e instanceof Error ? e.message : '卸载失败' },
      },
      { status: 500 },
    );
  }
}
