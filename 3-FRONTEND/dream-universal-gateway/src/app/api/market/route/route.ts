import { NextResponse } from "next/server";

export async function GET() {
  try {
    const hubBaseUrl = process.env.HUB_BASE_URL || "http://127.0.0.1:3467";
    const res = await fetch(`${hubBaseUrl}/market/route`, {
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
