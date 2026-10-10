import { NextRequest, NextResponse } from "next/server";

const HUB_BASE_URL = process.env.HUB_BASE_URL || "http://127.0.0.1:3467";

export async function GET(request: NextRequest) {
  const qs = request.nextUrl.searchParams.toString()
    ? `?${request.nextUrl.searchParams.toString()}`
    : "";
  try {
    const res = await fetch(`${HUB_BASE_URL}/api/ops/queues${qs}`, {
      headers: { Accept: "application/json" },
      next: { revalidate: 5 },
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
        total_tasks: 0,
        pending_tasks: 0,
        processing_tasks: 0,
        completed_tasks: 0,
        failed_tasks: 0,
        avg_latency_ms: 0,
        queue_depth_by_department: {},
        items: [],
      },
      { status: 200 }
    );
  }
}
