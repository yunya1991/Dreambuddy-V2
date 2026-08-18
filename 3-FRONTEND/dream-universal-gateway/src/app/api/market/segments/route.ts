import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";

export async function GET() {
  try {
    const users = await prisma.user.findMany({
      select: { uid: true, role: true },
    });

    const byRole = { FREE: 0, PRO: 0, ADMIN: 0 };
    for (const u of users) {
      const r = u.role as keyof typeof byRole;
      if (r in byRole) byRole[r]++;
    }

    return NextResponse.json({
      success: true,
      data: { total: users.length, byRole },
    });
  } catch (err) {
    return NextResponse.json(
      { success: false, error: err instanceof Error ? err.message : "db_error" },
      { status: 500 }
    );
  }
}
