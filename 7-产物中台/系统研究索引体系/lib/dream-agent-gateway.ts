import { randomUUID } from "node:crypto";
import { getRealtimeHub } from "./realtime-hub.ts";
import type {
  DreamAgentInvokeInput,
  DreamAgentInvokeSuccess,
} from "./types.ts";

const DEFAULT_AGENT_BASE =
  process.env.DREAM_AGENT_API_BASE || "http://127.0.0.1:5001";

export async function invokeDreamAgent(
  input: DreamAgentInvokeInput,
): Promise<DreamAgentInvokeSuccess> {
  const requestId = randomUUID();
  const hub = getRealtimeHub();

  hub.publish("dream-agent", {
    type: "request.queued",
    summary: "Dream Agent 请求已进入中台队列",
    requestId,
    status: "queued",
  });

  hub.publish("dream-agent", {
    type: "request.started",
    summary: "Dream Agent 请求已从中台发往后端",
    requestId,
    status: "streaming",
    data: { user_input: input.user_input },
  });

  let response: Response;
  try {
    response = await fetch(`${DEFAULT_AGENT_BASE}/dream-agent/invoke`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Dream Agent backend failed";
    hub.publish("dream-agent", {
      type: "request.failed",
      summary: `Dream Agent 后端调用失败: ${message}`,
      requestId,
      status: "failed",
    });
    throw error;
  }

  if (!response.ok) {
    hub.publish("dream-agent", {
      type: "request.failed",
      summary: `Dream Agent 后端调用失败: ${response.statusText}`,
      requestId,
      status: "failed",
    });
    throw new Error(response.statusText || "Dream Agent backend failed");
  }

  const data = (await response.json()) as {
    success: boolean;
    response?: string;
    error?: string;
  };

  if (!data.success || !data.response) {
    hub.publish("dream-agent", {
      type: "request.failed",
      summary: data.error || "Dream Agent 返回失败",
      requestId,
      status: "failed",
    });
    throw new Error(data.error || "Dream Agent returned failure");
  }

  hub.publish("dream-agent", {
    type: "request.completed",
    summary: "Dream Agent 请求已完成",
    requestId,
    status: "completed",
  });

  return { success: true, response: data.response, requestId };
}
