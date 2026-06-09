import { NextResponse } from "next/server";

const HUB_BASE_URL = process.env.HUB_BASE_URL || "http://127.0.0.1:3456";

export async function GET() {
  try {
    const res = await fetch(`${HUB_BASE_URL}/ops/decision-levels`, {
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
    return NextResponse.json(
      { success: false, error: err instanceof Error ? err.message : "hub_unavailable" },
      { status: 503 }
    );
  }
}
