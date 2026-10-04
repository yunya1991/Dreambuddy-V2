/**
 * P0-2b-S3: Layer 1 算法识别 TS 侧调用器
 *
 * 职责:
 * 1. 构建 algorithm_recognize IPC 请求
 * 2. 发送到 Python server，读取响应
 * 3. FAIL-OPEN: 任何异常返回 degraded，不阻塞交易热路径
 *
 * 来源: SPEC_ALGORITHM_DRIVEN_TRAINING_LOOP.md Phase 0-2b
 * 边界: 只调用 IPC，不做交易判断（HC-9）
 */

import type { ChildProcess } from "node:child_process";
import {
  createProtocolClient,
  CURRENT_SCHEMA_VERSION,
  type IPCResponse,
} from "./sdk/protocol-client";

export interface AlgorithmRecognizeParams {
  user_message?: string;
  market?: Record<string, unknown>;
  signals?: unknown[];
  memory?: Record<string, unknown>;
  knowledge_hits?: unknown[];
  context?: Record<string, unknown>;
  symbol?: string;
}

export interface AlgorithmRecognizeResult {
  intent_type: string;
  confidence: number;
  tier: string;
  base_chain: string[];
  agent_takeover_needed: boolean;
  degraded: boolean;
  reason?: string;
  rationale?: string;
  complexity_rationale?: string;
}

/**
 * 调用 algorithm_recognize IPC
 *
 * @param pyServer Python IPC server 子进程
 * @param params 识别参数
 * @returns 算法识别结果（FAIL-OPEN 时返回 degraded）
 */
export async function recognizeViaAlgorithm(
  pyServer: ChildProcess,
  params: AlgorithmRecognizeParams
): Promise<AlgorithmRecognizeResult> {
  const client = createProtocolClient({ version: CURRENT_SCHEMA_VERSION });

  // 1. 构建 IPC 请求
  const request = client.buildRequest("algorithm_recognize", params as Record<string, unknown>);

  // 2. 发送并读取响应（带超时）
  // 注意: DreamOS 模块 import 时可能向 stdout 输出非 IPC 内容，
  // 需要按行过滤，只处理包含 schema_version 的 JSON 行
  const rawLine = await new Promise<string | null>((resolve) => {
    const timer = setTimeout(() => {
      resolve(null);
    }, 10000);  // 10s 超时（DreamOS import 可能较慢）

    if (!pyServer.stdin || !pyServer.stdout) {
      clearTimeout(timer);
      resolve(null);
      return;
    }

    let buffer = "";
    const onData = (chunk: Buffer) => {
      buffer += chunk.toString();
      const lines = buffer.split("\n");
      // 保留最后一行（可能不完整）
      buffer = lines.pop() || "";
      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) continue;
        try {
          const parsed = JSON.parse(trimmed);
          // 只处理包含 schema_version 的 IPC 响应行
          if (parsed.schema_version && parsed.message_type === "response") {
            clearTimeout(timer);
            pyServer.stdout?.removeListener("data", onData);
            resolve(trimmed);
            return;
          }
        } catch {
          // 非 JSON 行（DreamOS 模块输出），忽略
        }
      }
    };

    pyServer.stdout.on("data", onData);
    pyServer.stdin.write(JSON.stringify(request) + "\n");
  });

  // 3. 无响应 → FAIL-OPEN
  if (!rawLine) {
    return {
      intent_type: "UNCERTAIN",
      confidence: 0.0,
      tier: "T1",
      base_chain: [],
      agent_takeover_needed: false,
      degraded: true,
      reason: "IPC 超时或 Python server 无响应",
    };
  }

  // 4. 解析响应
  let response: IPCResponse;
  try {
    response = client.parseResponse(rawLine);
  } catch (e) {
    return {
      intent_type: "UNCERTAIN",
      confidence: 0.0,
      tier: "T1",
      base_chain: [],
      agent_takeover_needed: false,
      degraded: true,
      reason: `IPC 响应解析失败: ${e instanceof Error ? e.message : String(e)}`,
    };
  }

  if (!response.ok) {
    // FAIL-OPEN: 返回 degraded
    return {
      intent_type: "UNCERTAIN",
      confidence: 0.0,
      tier: "T1",
      base_chain: [],
      agent_takeover_needed: false,
      degraded: true,
      reason: response.error?.message,
    };
  }

  return response.result as AlgorithmRecognizeResult;
}
