import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";

export async function GET() {
  try {
    // Map strategy status changes as audit trail
    const strategies = await prisma.strategy.findMany({
      select: { id:true, name:true, status:true, type:true, direction:true, updatedAt:true },
      orderBy: { updatedAt: "desc" }, take: 50,
    });
    const data = strategies.map(s => ({
      id: s.id,
      action: `strategy.${s.status?.toLowerCase()??"update"}`,
      resource: s.name,
      actor: "system",
      result: (["APPROVED","APPLIED"].includes(s.status??"") ? "success" : s.status==="EXPIRED" ? "failure" : "pending") as "success"|"failure"|"pending",
      details: `${s.type} · ${s.direction}`,
      timestamp: s.updatedAt?.toISOString() ?? new Date().toISOString(),
    }));
    return NextResponse.json({ success: true, data });
  } catch(err) {
    return NextResponse.json({ success:false, error: err instanceof Error ? err.message : "db_error" }, { status:500 });
  }
}