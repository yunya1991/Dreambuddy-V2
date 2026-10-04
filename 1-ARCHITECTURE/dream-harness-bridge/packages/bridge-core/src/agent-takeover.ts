/**
 * P0-4-S2: Layer 3 Agent 接管 TS 侧调用器
 *
 * 职责:
 * 1. 调用 agent_takeover IPC，获取 Agent 接管决策
 * 2. 复用 ReflectionDecision 类型校验返回的 decision 字段
 * 3. FAIL-OPEN: 任何异常返回 degraded + CONTINUE，不阻塞交易热路径
 *
 * 来源: SPEC_ALGORITHM_DRIVEN_TRAINING_LOOP.md Phase 0-4
 * 边界: 只返回 ReflectionDecision，不做交易判断（HC-9）
 */

import type { ChildProcess } from "node:child_process";
import {
  createProtocolClient,
  CURRENT_SCHEMA_VERSION,
  type IPCResponse,
} from "./sdk/protocol-client";
import { VALID_DECISIONS, type ReflectionDecision } from "./reflection-protocol";

export interface AgentTakeoverResult {
  decision: ReflectionDecision;
  target_step: string | null;
  agent_delegated: boolean;
  degraded: boolean;
  reason?: string;
}

/**
 * 调用 agent_takeover IPC
 *
 * @param pyServer Python IPC server 子进程
 * @param algorithmResult 算法识别结果
 * @returns Agent 接管决策（FAIL-OPEN 时返回 degraded + CONTINUE）
 */
export async function requestAgentTakeover(
  pyServer: ChildProcess,
  algorithmResult: Record<string, unknown>
): Promise<AgentTakeoverResult> {
  const client = createProtocolClient({ version: CURRENT_SCHEMA_VERSION });

  const request = client.buildRequest("agent_takeover", {
    algorithm_result: algorithmResult,
  });

  // 发送并读取响应（带超时 + 按行过滤非 IPC 内容）
  const rawLine = await new Promise<string | null>((resolve) => {
    const timer = setTimeout(() => {
      resolve(null);
    }, 10000);

    if (!pyServer.stdin || !pyServer.stdout) {
      clearTimeout(timer);
      resolve(null);
      return;
    }

    let buffer = "";
    const onData = (chunk: Buffer) => {
      buffer += chunk.toString();
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) continue;
        try {
          const parsed = JSON.parse(trimmed);
          const hasVersion = typeof parsed.schema_version === "string";
          const isResponse = parsed.message_type === "response";
          const matched = hasVersion && isResponse;
          if (matched) {
            clearTimeout(timer);
            pyServer.stdout?.removeListener("data", onData);
            resolve(trimmed);
            return;
          }
        } catch {
          // 非 JSON 行，忽略
        }
      }
    };

    pyServer.stdout.on("data", onData);
    pyServer.stdin.write(JSON.stringify(request) + "\n");
  });

  // 无响应 → FAIL-OPEN
  if (!rawLine) {
    return {
      decision: "CONTINUE",
      target_step: null,
      agent_delegated: false,
      degraded: true,
      reason: "IPC 超时或 Python server 无响应",
    };
  }

  // 解析响应
  let response: IPCResponse;
  try {
    response = client.parseResponse(rawLine);
  } catch (e) {
    return {
      decision: "CONTINUE",
      target_step: null,
      agent_delegated: false,
      degraded: true,
      reason: `IPC 响应解析失败: ${e instanceof Error ? e.message : String(e)}`,
    };
  }

  if (!response.ok) {
    return {
      decision: "CONTINUE",
      target_step: null,
      agent_delegated: false,
      degraded: true,
      reason: response.error?.message,
    };
  }

  const result = response.result as Record<string, unknown>;
  const decisionStr = String(result.decision);

  // 校验 decision 值在合法枚举内
  const isValidDecision = (VALID_DECISIONS as string[]).includes(decisionStr);
  if (!isValidDecision) {
    return {
      decision: "CONTINUE",
      target_step: null,
      agent_delegated: false,
      degraded: true,
      reason: `非法 decision: ${decisionStr}`,
    };
  }

  return {
    decision: decisionStr as ReflectionDecision,
    target_step: (result.target_step as string | null) ?? null,
    agent_delegated: Boolean(result.agent_delegated),
    degraded: Boolean(result.degraded),
    reason: result.reason as string | undefined,
  };
}
