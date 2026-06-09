import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";

export async function GET() {
  try {
    const strategies = await prisma.strategy.findMany({
      select: {
        id: true,
        name: true,
        description: true,
        type: true,
        status: true,
        source: true,
        regime: true,
        createdAt: true,
      },
      orderBy: { createdAt: "desc" },
    });

    const items = strategies.map(s => ({
      id: s.id,
      title: s.name,
      tags: [
        s.type?.toLowerCase() ?? "custom",
        s.regime ?? "general",
        s.source ?? "internal",
      ].filter(Boolean),
      department: "strategy",
      type: s.type ?? "CUSTOM",
      date: s.createdAt.toISOString().slice(0, 10),
      status: (["APPROVED","APPLIED"].includes(s.status ?? "") ? "completed"
             : s.status === "DRAFT" ? "processing"
             : "unknown") as "completed" | "processing" | "failed" | "unknown",
      excerpt: s.description ?? undefined,
      url: "",
    }));

    return NextResponse.json({ success: true, data: items });
  } catch (err) {
    return NextResponse.json(
      { success: false, error: err instanceof Error ? err.message : "db_error" },
      { status: 500 }
    );
  }
}