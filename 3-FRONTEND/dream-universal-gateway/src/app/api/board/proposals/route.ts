import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";

export async function GET() {
  try {
    const strategies = await prisma.strategy.findMany({
      select: { id:true, name:true, status:true, type:true, direction:true, symbol:true,
               confidence:true, edgeScore:true, regime:true, createdAt:true },
      orderBy: { createdAt: "desc" }, take: 100,
    });
    return NextResponse.json({ success:true, data: strategies.map(s=>({
      id:s.id, title:s.name, status:s.status, type:s.type||"CUSTOM",
      department:"strategy", direction:s.direction, symbol:s.symbol,
      confidence:s.confidence, edgeScore:s.edgeScore,
      createdAt:s.createdAt.toISOString(),
    })) });
  } catch(err) {
    return NextResponse.json({ success:false, error: err instanceof Error?err.message:"db_error" }, {status:500});
  }
}