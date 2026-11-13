/** SPEC-52 F5 — 插件市场列表（白名单驱动，deny-by-default） */
import { NextResponse } from 'next/server';
import { listPlugins, summarizeGroups } from '@/lib/plugins/registry';
import { isEntitled } from '@/lib/product/entitlement';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET() {
  try {
    const items = await listPlugins();
    return NextResponse.json({
      ok: true,
      data: {
        items,
        counts: summarizeGroups(items),
        product_entitled: isEntitled(),
      },
    });
  } catch (e) {
    return NextResponse.json(
      {
        ok: false,
        data: null,
        error: { code: 'PLUGIN_REGISTRY_UNAVAILABLE', message: e instanceof Error ? e.message : '读取白名单失败' },
      },
      { status: 503 },
    );
  }
}
