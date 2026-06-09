import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  try {
    const s = await prisma.strategy.findUnique({
      where: { id },
      include: { tasks: { select: { id:true, status:true, tradeCount:true, lastExecutionAt:true, nextExecutionAt:true } } },
    });
    if (!s) return NextResponse.json({ success:false, error:"not_found" }, {status:404});
    return NextResponse.json({ success:true, data: {
      ...s,
      title: s.name,
      createdAt: s.createdAt.toISOString(),
      tasks: s.tasks,
    } });
  } catch(err) {
    return NextResponse.json({ success:false, error: err instanceof Error?err.message:"db_error" }, {status:500});
  }
}
