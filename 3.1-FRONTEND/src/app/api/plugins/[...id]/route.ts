/**
 * SPEC-52 F5 — `POST /api/plugins/{id}/enable`
 *
 * 用 catch-all 承接含 `/` 的 scoped 包名（如 @puwenhui/dsh-rag-kb）：
 * 最后一段必须是 `enable`，其余段拼回插件 id。
 */
import { NextRequest, NextResponse } from 'next/server';
import { PluginError, setPluginEnabled } from '@/lib/plugins/registry';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string[] }> },
) {
  const { id } = await params;
  const segments = [...id];
  const action = segments.pop();
  if (action !== 'enable') {
    return NextResponse.json(
      { ok: false, data: null, error: { code: 'NOT_FOUND', message: '仅支持 /api/plugins/{id}/enable' } },
      { status: 404 },
    );
  }
  const pluginId = segments.join('/');

  let body: { enabled?: boolean; profile?: string };
  try {
    body = await request.json();
  } catch {
    body = {};
  }

  try {
    const item = await setPluginEnabled(
      pluginId,
      body.enabled !== false,
      body.profile || 'sandbox',
    );
    return NextResponse.json({ ok: true, data: item });
  } catch (e) {
    if (e instanceof PluginError) {
      return NextResponse.json(
        { ok: false, data: null, error: { code: e.code, message: e.message } },
        { status: e.code === 'PLUGIN_NOT_REGISTERED' ? 404 : 403 },
      );
    }
    return NextResponse.json(
      {
        ok: false,
        data: null,
        error: { code: 'PLUGIN_STATE_UNAVAILABLE', message: e instanceof Error ? e.message : '启停失败' },
      },
      { status: 500 },
    );
  }
}
