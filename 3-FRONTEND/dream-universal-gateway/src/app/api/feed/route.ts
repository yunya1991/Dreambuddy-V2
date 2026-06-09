import { NextRequest, NextResponse } from "next/server";

const HUB_BASE_URL = process.env.HUB_BASE_URL || "http://127.0.0.1:3467";

export async function GET(request: NextRequest) {
  const workflowType = request.nextUrl.searchParams.get("workflow_type") ?? "";
  const qs = workflowType ? `?workflow_type=${encodeURIComponent(workflowType)}` : "";
  try {
    const res = await fetch(`${HUB_BASE_URL}/chain/artifacts${qs}`, {
      headers: { Accept: "application/json" },
      next: { revalidate: 15 },
    });
    if (!res.ok) return NextResponse.json({ success:false, error:`Hub ${res.status}` }, {status:res.status});
    const hubData = await res.json();

    // Flatten and normalize: if workflowType specified, return items array; else flatten both
    let items: unknown[];
    if (workflowType === "legacy_chain" || workflowType === "trading_v2") {
      items = hubData.items ?? [];
    } else {
      items = [...(hubData.legacy_chain ?? []), ...(hubData.trading_v2 ?? [])];
    }

    // Sort by created_at descending
    (items as Array<{created_at:string}>).sort((a,b)=>b.created_at.localeCompare(a.created_at));

    return NextResponse.json({ success:true, data: items });
  } catch(err) {
    return NextResponse.json({ success:false, error: err instanceof Error?err.message:"hub_unavailable" }, {status:503});
  }
}
