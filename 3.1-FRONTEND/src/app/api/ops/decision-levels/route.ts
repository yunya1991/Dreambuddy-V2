import { NextRequest, NextResponse } from "next/server";

const HUB_BASE_URL = process.env.HUB_BASE_URL || "http://127.0.0.1:3467";

export async function GET(_request: NextRequest) {
  try {
    const res = await fetch(`${HUB_BASE_URL}/api/ops/decision-levels`, {
      headers: { Accept: "application/json" },
      next: { revalidate: 60 },
    });
    if (!res.ok) {
      return NextResponse.json(
        { success: false, error: `Hub returned ${res.status}` },
        { status: res.status }
      );
    }
    return NextResponse.json(await res.json());
  } catch (err) {
    // Hub unavailable — return mock data for frontend fallback
    return NextResponse.json(
      {
        success: true,
        mock: true,
        levels: [
          { level: "L1", label: "常规决策", description: "低风险常规操作", requires_board_approval: false, auto_threshold: 10000 },
          { level: "L2", label: "重要决策", description: "中等风险操作", requires_board_approval: false, auto_threshold: 100000 },
          { level: "L3", label: "重大决策", description: "高风险操作", requires_board_approval: true, auto_threshold: 1000000 },
        ],
      },
      { status: 200 }
    );
  }
}
