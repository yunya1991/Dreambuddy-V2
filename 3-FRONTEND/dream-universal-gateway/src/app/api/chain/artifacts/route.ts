import { NextRequest, NextResponse } from "next/server";

const HUB_BASE_URL = process.env.HUB_BASE_URL || "http://49.233.123.96:3456";

export async function GET(request: NextRequest) {
  const workflowType = request.nextUrl.searchParams.get("workflow_type") ?? "";
  const qs = workflowType ? `?workflow_type=${encodeURIComponent(workflowType)}` : "";
  try {
    const res = await fetch(`${HUB_BASE_URL}/api/chain/artifacts${qs}`, {
      headers: { Accept: "application/json" },
      next: { revalidate: 30 },
    });
    if (!res.ok) {
      return NextResponse.json(
        { success: false, error: `Hub returned ${res.status}` },
        { status: res.status }
      );
    }
    const data = await res.json();
    return NextResponse.json({ success: true, data });
  } catch (err) {
    return NextResponse.json(
      { success: false, error: err instanceof Error ? err.message : "hub_unavailable" },
      { status: 503 }
    );
  }
}
