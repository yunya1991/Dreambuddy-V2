import { NextResponse } from "next/server";

export async function GET() {
  try {
    const hubBaseUrl = process.env.HUB_BASE_URL || "http://49.233.123.96:3456";
    const res = await fetch(`${hubBaseUrl}/api/market/route`, {
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
    return NextResponse.json({ success: true, data: json.data ?? [] });
  } catch (err) {
    return NextResponse.json({ success: false, error: err instanceof Error ? err.message : "db_error" }, { status: 500 });
  }
}
