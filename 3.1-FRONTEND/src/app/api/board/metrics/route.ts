import { NextResponse } from "next/server";

// Dev mock: 董事会总览指标
const MOCK_METRICS = {
  total_traces: 1284,
  total_decisions: 342,
  total_artifacts: 856,
  pending_approvals: 5,
  recent_performance: {
    avg_win_rate: 0.62,
    total_pnl: 1842.5,
    trade_count: 47,
  },
  department_breakdown: {
    research: 45,
    trading: 38,
    risk: 12,
    ops: 8,
    strategy: 27,
  },
};

export async function GET() {
  // 开发模式直接返回 mock 数据
  return NextResponse.json({ success: true, data: MOCK_METRICS });
}
