// GET/PUT /api/visual/cards/config（SPEC-54 R3b）
// - userId 只取 session，请求体/查询串里的 userId 只用于越权校验（不一致 → 403）
// - 响应统一 code 字段，前端按 code 分级，不用 HTTP 状态区分业务分支

import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/lib/auth';
import {
  readCardsConfig,
  writeCardsConfig,
  type CardPanelInput,
} from '@/lib/visual/cards-config';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const MAX_ID_LEN = 200;
const MAX_PANELS = 200;

type Json = Record<string, unknown>;

function fail(code: string, status: number, reason?: string) {
  return NextResponse.json({ ok: false, code, ...(reason ? { reason } : {}) }, { status });
}

function cleanId(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function normalizePanels(raw: unknown): CardPanelInput[] | null {
  if (!Array.isArray(raw)) return null;
  const panels: CardPanelInput[] = [];
  for (const item of raw) {
    if (!item || typeof item !== 'object') return null;
    const row = item as Json;
    const panelKey = cleanId(row.panel_key);
    const capabilityId = cleanId(row.capability_id);
    if (!panelKey || !capabilityId) return null;
    if (panelKey.length > MAX_ID_LEN || capabilityId.length > MAX_ID_LEN) return null;
    const args = row.args;
    if (args !== undefined && args !== null && typeof args !== 'object') return null;
    panels.push({
      panel_key: panelKey,
      capability_id: capabilityId,
      args: (args as Record<string, unknown>) ?? {},
      data_provenance: typeof row.data_provenance === 'string' ? row.data_provenance : 'pool',
    });
  }
  return panels.length > MAX_PANELS ? null : panels;
}

export async function GET(request: NextRequest) {
  const session = await auth();
  if (!session?.user?.id) return fail('unauthorized', 401);

  const claimed = cleanId(request.nextUrl.searchParams.get('userId'));
  if (claimed && claimed !== session.user.id) return fail('forbidden', 403);

  const tabId = cleanId(request.nextUrl.searchParams.get('tabId'));
  try {
    return NextResponse.json(await readCardsConfig(session.user.id, tabId || undefined));
  } catch (err) {
    return fail('error', 500, err instanceof Error ? err.message : String(err));
  }
}

export async function PUT(request: NextRequest) {
  const session = await auth();
  if (!session?.user?.id) return fail('unauthorized', 401);

  let body: Json;
  try {
    body = (await request.json()) as Json;
  } catch {
    return fail('invalid_params', 400, 'body 必须是 JSON 对象');
  }
  if (!body || typeof body !== 'object') return fail('invalid_params', 400);

  const claimed = cleanId(body.userId);
  if (claimed && claimed !== session.user.id) return fail('forbidden', 403);

  const tabId = cleanId(body.tabId);
  if (!tabId || tabId.length > MAX_ID_LEN) {
    return fail('invalid_params', 400, 'tabId 不能为空且长度 ≤ 200');
  }
  const panels = normalizePanels(body.panels);
  if (panels === null) {
    return fail('invalid_params', 400, 'panels 必须是数组且每项含 panel_key/capability_id');
  }

  try {
    const result = await writeCardsConfig(session.user.id, tabId, panels);
    const status = result.code === 'payload_too_large' ? 413 : 200;
    return NextResponse.json(result, { status });
  } catch (err) {
    return fail('error', 500, err instanceof Error ? err.message : String(err));
  }
}
