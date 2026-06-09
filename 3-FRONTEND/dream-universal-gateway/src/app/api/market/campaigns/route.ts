import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";

export async function GET() {
  try {
    const strategies = await prisma.strategy.findMany({
      select: { id:true, name:true, type:true, status:true, direction:true, symbol:true, confidence:true, createdAt:true },
      orderBy: { createdAt: "desc" }, take: 100,
    });
    return NextResponse.json({ success: true, data: strategies.map(s=>({
      ...s, createdAt: s.createdAt.toISOString()
    })) });
  } catch(err) {
    return NextResponse.json({ success:false, error: err instanceof Error ? err.message : "db_error" }, { status:500 });
  }
}