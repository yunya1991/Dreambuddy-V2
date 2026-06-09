import { createRealtimeStream } from "@/lib/realtime-sse";
import type { RealtimeChannel } from "@/lib/types";

const CHANNELS: RealtimeChannel[] = ["dream-agent", "meeting", "system"];

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const channel = searchParams.get("channel") as RealtimeChannel | null;

  if (!channel || !CHANNELS.includes(channel)) {
    return new Response(JSON.stringify({ error: "Invalid channel" }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }

  return new Response(createRealtimeStream(channel), {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
