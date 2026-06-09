import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";

export async function GET() {
  try {
    const channels = await prisma.channelConfig.findMany({
      select: {
        id: true,
        channelType: true,
        label: true,
        isOnline: true,
        createdAt: true,
      },
      orderBy: { createdAt: "desc" },
    });

    const data = channels.map(ch => ({
      id: ch.id,
      channelType: ch.channelType,
      messageType: "channel_config",
      status: (ch.isOnline ? "sent" : "pending") as "sent" | "pending",
      recipient: ch.label,
      sentAt: ch.createdAt.toISOString(),
    }));

    return NextResponse.json({ success: true, data });
  } catch (err) {
    return NextResponse.json({ success: false, error: err instanceof Error ? err.message : "db_error" }, { status: 500 });
  }
}
