import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  try {
    const { verdict } = await req.json();
    if (verdict !== "approved" && verdict !== "rejected") {
      return NextResponse.json({ success:false, error:"invalid_verdict" }, {status:400});
    }
    const newStatus = verdict === "approved" ? "APPROVED" : "EXPIRED";
    await prisma.strategy.update({ where: { id }, data: { status: newStatus } });
    return NextResponse.json({ success: true, verdict });
  } catch(err) {
    return NextResponse.json({ success:false, error: err instanceof Error?err.message:"db_error" }, {status:500});
  }
}
