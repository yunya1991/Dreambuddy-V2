import { NextResponse } from "next/server";
import { invokeDreamAgent } from "@/lib/dream-agent-gateway";
import type { DreamAgentInvokeInput } from "@/lib/types";

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as DreamAgentInvokeInput;
    const result = await invokeDreamAgent(body);
    return NextResponse.json(result);
  } catch (error) {
    return NextResponse.json(
      {
        success: false,
        error:
          error instanceof Error ? error.message : "Dream Agent invoke failed",
      },
      { status: 502 },
    );
  }
}
