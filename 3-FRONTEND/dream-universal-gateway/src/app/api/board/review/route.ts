import { NextResponse } from "next/server";

export async function GET() {
  try {
    const hubBaseUrl = process.env.HUB_BASE_URL || "http://127.0.0.1:3456";
    const res = await fetch(`${hubBaseUrl}/chain/performance`, {
      headers: { Accept: "application/json" },
      next: { revalidate: 15 },
    });
    if (!res.ok) {
      return NextResponse.json(
        { success: false, error: `Hub returned ${res.status}` },
        { status: res.status }
      );
    }
    const json = await res.json();
    const perf = (json.data ?? []) as Array<{
      perf_id: string;
      workflow_id: string;
      workflow_type: string;
      total_trades: number;
      win_rate: number;
      pnl: number;
      recorded_at: string;
    }>;
    return NextResponse.json({
      success: true,
      data: perf.slice(0, 20).map((p) => ({
        id: p.perf_id,
        strategyName: p.workflow_id,
        status: p.workflow_type,
        totalTrades: p.total_trades ?? 0,
        winRate: p.win_rate ?? 0,
        pnl: p.pnl ?? 0,
        score: null,
        review: null,
        appliedAt: p.recorded_at ?? null,
      })),
    });
  } catch(err) {
    return NextResponse.json({ success:false, error: err instanceof Error?err.message:"db_error" }, {status:500});
  }
}
