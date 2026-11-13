/**
 * GET /api/product/entitlement
 * SPEC-52 F2：前端读取产品包开通状态（只读；真实门禁在服务端各处）。
 */
import { NextResponse } from 'next/server';
import { getEntitlement } from '@/lib/product/entitlement';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET() {
  return NextResponse.json({ ok: true, data: getEntitlement() });
}
