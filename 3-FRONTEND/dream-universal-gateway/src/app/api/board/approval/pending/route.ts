import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";

export async function GET() {
  try {
    const strategies = await prisma.strategy.findMany({
      where: { status: "DRAFT" },
      select: { id:true, name:true, direction:true, symbol:true, type:true, confidence:true, description:true, createdAt:true },
      orderBy: { createdAt: "desc" }, take: 20,
    });
    return NextResponse.json({ success:true, data: strategies.map(s=>({
      id:s.id, title:s.name, direction:s.direction, symbol:s.symbol, type:s.type||"CUSTOM",
      confidence:s.confidence, description:s.description, createdAt:s.createdAt.toISOString(),
    })) });
  } catch(err) {
    return NextResponse.json({ success:false, error: err instanceof Error?err.message:"db_error" }, {status:500});
  }
}