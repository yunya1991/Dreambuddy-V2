import { NextResponse } from 'next/server';
import { fetchClassicGateThresholds } from '@/lib/classic-system-bridge';

export async function GET() {
  const result = await fetchClassicGateThresholds();
  return NextResponse.json({
    ok: result.ok,
    data: result.data,
    error: result.error,
    trace_id: result.trace_id,
  }, { status: result.ok ? 200 : 502 });
}
