/** SPEC-52 F4/F7 — 用量明细 + 按维度聚合（账本只追加） */
import { NextRequest, NextResponse } from 'next/server';
import { summarizeUsage } from '@/lib/billing/meter';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const limitRaw = Number(request.nextUrl.searchParams.get('limit') ?? '50');
  const limit = Number.isFinite(limitRaw) ? Math.min(Math.max(Math.trunc(limitRaw), 1), 500) : 50;
  const summary = await summarizeUsage(limit);
  return NextResponse.json({ ok: true, data: summary });
}
