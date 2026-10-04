import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";

// P1: 提案投票路由
// POST /api/board/proposals/:id/votes — 创建投票 (voter 硬编码 anonymous, P2 接 next-auth)
// GET  /api/board/proposals/:id/votes — 列出该提案所有投票

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  try {
    const { vote } = await req.json();
    if (vote !== "FOR" && vote !== "AGAINST") {
      return NextResponse.json(
        { success: false, error: "invalid_vote" },
        { status: 400 }
      );
    }
    // P1: voter 硬编码 anonymous, P2 接 next-auth session.user.uid + 校验登录态 + 防一人多投
    const created = await prisma.proposalVote.create({
      data: { proposalId: id, voter: "anonymous", vote },
    });
    return NextResponse.json({ success: true, id: created.id });
  } catch (err) {
    return NextResponse.json(
      { success: false, error: err instanceof Error ? err.message : "db_error" },
      { status: 500 }
    );
  }
}

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  try {
    const votes = await prisma.proposalVote.findMany({
      where: { proposalId: id },
      select: { id: true, vote: true, createdAt: true },
      orderBy: { createdAt: "desc" },
    });
    return NextResponse.json({ success: true, data: votes });
  } catch (err) {
    return NextResponse.json(
      { success: false, error: err instanceof Error ? err.message : "db_error" },
      { status: 500 }
    );
  }
}
