/** SPEC-52 F5 — 真实安装：dsh plugin --profile <p> add <pkg>（仅白名单 + 沙箱） */
import { NextRequest, NextResponse } from 'next/server';
import { DshInstallError, installDshPlugin } from '@/lib/dsh/plugins';
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
    const data = await installDshPlugin(body.id, body.profile || 'sandbox');
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
        error: { code: 'PLUGIN_INSTALL_FAILED', message: e instanceof Error ? e.message : '安装失败' },
      },
      { status: 500 },
    );
  }
}
