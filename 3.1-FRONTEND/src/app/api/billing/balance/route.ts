/** SPEC-52 F4/F7 — CU 余额（服务端计量，前端只展示） */
import { NextResponse } from 'next/server';
import { summarizeUsage } from '@/lib/billing/meter';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET() {
  const summary = await summarizeUsage(1);
  return NextResponse.json({
    ok: true,
    data: {
      balance_cu: summary.balance_cu,
      base_cu: summary.base_cu,
      spent_cu: summary.spent_cu,
      reserved_cu: summary.reserved_cu,
      unit_price_cny: summary.unit_price_cny,
    },
  });
}
