/**
 * P0-5: 训练数据闭环 TS 侧标注请求器
 *
 * 职责:
 * 1. 构建 request_label IPC 请求，将难例样本（confidence < 0.55）发送到 Python server
 * 2. 按行过滤 stdout，只处理包含 schema_version 和 message_type="response" 的 JSON 行
 *    （DreamOS 模块 import 时可能向 stdout 输出非 IPC 内容）
 * 3. FAIL-OPEN: 任何异常返回 degraded，不阻塞交易热路径
 *
 * 来源: SPEC_ALGORITHM_DRIVEN_TRAINING_LOOP.md Phase 0-5
 * 边界守护（HC-9 硬约束）:
 * - 只调用 IPC 透传难例样本，不做任何交易判断
 * - 禁止出现交易判断逻辑（技术指标判断、仓位判断、盈亏判断、方向判断）
 * - 不计算 reward（reward 由 DreamOS 内部 EvolutionEngine 独占）
 */

import type { ChildProcess } from "node:child_process";
import {
  createProtocolClient,
  CURRENT_SCHEMA_VERSION,
  type IPCResponse,
} from "./sdk/protocol-client";

export interface LabelRequestResult {
  status: string;
  sample_id: string | null;
  degraded: boolean;
  reason?: string;
}

/**
 * 调用 request_label IPC
 *
 * @param pyServer Python IPC server 子进程
 * @param algorithmResult 算法识别结果（含 user_message, intent_type, confidence, tier 等）
 * @returns 标注请求结果（FAIL-OPEN 时返回 degraded）
 *
 * HC-9: 此函数只调用 IPC 透传难例样本，不做任何交易判断
 */
export async function requestLabel(
  pyServer: ChildProcess,
  algorithmResult: Record<string, unknown>
): Promise<LabelRequestResult> {
  const client = createProtocolClient({ version: CURRENT_SCHEMA_VERSION });

  // 1. 构建 IPC 请求
  // 直接透传所有字段（algorithm_result / label / label_source / user_message 等）
  // Python handle_request_label 从顶层提取各字段
  const request = client.buildRequest("request_label", algorithmResult);

  // 2. 发送并读取响应（带超时 + 按行过滤非 IPC 内容）
  // 注意: DreamOS 模块 import 时可能向 stdout 输出非 IPC 内容，
  // 需要按行过滤，只处理包含 schema_version 的 JSON 行
  const rawLine = await new Promise<string | null>((resolve) => {
    const timer = setTimeout(() => {
      resolve(null);
    }, 10000); // 10s 超时（DreamOS import 可能较慢）

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
      status: "degraded",
      sample_id: null,
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
      status: "degraded",
      sample_id: null,
      degraded: true,
      reason: `IPC 响应解析失败: ${e instanceof Error ? e.message : String(e)}`,
    };
  }

  if (!response.ok) {
    // FAIL-OPEN: 返回 degraded
    return {
      status: "degraded",
      sample_id: null,
      degraded: true,
      reason: response.error?.message,
    };
  }

  const result = response.result as Record<string, unknown>;
  return {
    status: typeof result.status === "string" ? result.status : "unknown",
    sample_id: (result.sample_id as string | null) ?? null,
    degraded: Boolean(result.degraded),
    reason: result.reason as string | undefined,
  };
}
