/**
 * P0-5: 训练数据闭环 TS 侧桥梁
 *
 * 职责:
 * 1. publishModelUpdate — 调用 publish_model_update IPC，注册新模型版本到 DreamOS
 * 2. fetchTrainingDataset — 调用 fetch_training_dataset IPC，拉取已标注训练数据集
 * 3. 按行过滤 stdout，只处理包含 schema_version 和 message_type="response" 的 JSON 行
 *    （DreamOS 模块 import 时可能向 stdout 输出非 IPC 内容）
 * 4. FAIL-OPEN: 任何异常返回 degraded，不阻塞交易热路径
 *
 * 来源: SPEC_ALGORITHM_DRIVEN_TRAINING_LOOP.md Phase 0-5
 * 边界守护（HC-9 硬约束）:
 * - 只调用 IPC 透传模型元数据 / 拉取数据集，不做任何交易判断
 * - 禁止出现交易判断逻辑（技术指标判断、仓位判断、盈亏判断、方向判断）
 * - 不计算 reward（reward 由 DreamOS 内部 EvolutionEngine 独占）
 */

import type { ChildProcess } from "node:child_process";
import {
  createProtocolClient,
  CURRENT_SCHEMA_VERSION,
  type IPCRequest,
  type IPCResponse,
} from "./sdk/protocol-client";

export interface ModelUpdateResult {
  registered: boolean;
  degraded: boolean;
  reason?: string;
}

export interface TrainingDatasetResult {
  dataset: unknown[];
  count: number;
  degraded: boolean;
  reason?: string;
}

/**
 * 通用 IPC 调用：发送请求 → 按行过滤 stdout → 解析响应
 * 超时 10s，FAIL-OPEN 返回 null
 */
async function _sendAndReadLine(
  pyServer: ChildProcess,
  request: IPCRequest
): Promise<string | null> {
  return new Promise<string | null>((resolve) => {
    const timer = setTimeout(() => {
      resolve(null);
    }, 10000); // 10s 超时

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
}

/**
 * 调用 publish_model_update IPC — 注册新模型版本到 DreamOS
 *
 * @param pyServer Python IPC server 子进程
 * @param modelInfo 模型信息（含 model_id, version, metrics, dataset_size, training_params）
 * @returns 注册结果（FAIL-OPEN 时返回 degraded）
 *
 * HC-9: 此函数只调用 IPC 透传模型元数据，不做任何交易判断
 */
export async function publishModelUpdate(
  pyServer: ChildProcess,
  modelInfo: Record<string, unknown>
): Promise<ModelUpdateResult> {
  const client = createProtocolClient({ version: CURRENT_SCHEMA_VERSION });
  const request = client.buildRequest("publish_model_update", modelInfo);

  const rawLine = await _sendAndReadLine(pyServer, request);

  // 无响应 → FAIL-OPEN
  if (!rawLine) {
    return {
      registered: false,
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
      registered: false,
      degraded: true,
      reason: `IPC 响应解析失败: ${e instanceof Error ? e.message : String(e)}`,
    };
  }

  if (!response.ok) {
    return {
      registered: false,
      degraded: true,
      reason: response.error?.message,
    };
  }

  const result = response.result as Record<string, unknown>;
  return {
    registered: Boolean(result.registered),
    degraded: Boolean(result.degraded),
    reason: result.reason as string | undefined,
  };
}

/**
 * 调用 fetch_training_dataset IPC — 拉取已标注训练数据集
 *
 * @param pyServer Python IPC server 子进程
 * @param query 查询参数（含可选 limit）
 * @returns 数据集结果（FAIL-OPEN 时返回空数组 + degraded）
 *
 * HC-9: 此函数只调用 IPC 拉取数据集，不做任何交易判断
 */
export async function fetchTrainingDataset(
  pyServer: ChildProcess,
  query: { limit?: number }
): Promise<TrainingDatasetResult> {
  const client = createProtocolClient({ version: CURRENT_SCHEMA_VERSION });
  const request = client.buildRequest("fetch_training_dataset", {
    limit: query.limit,
  });

  const rawLine = await _sendAndReadLine(pyServer, request);

  // 无响应 → FAIL-OPEN
  if (!rawLine) {
    return {
      dataset: [],
      count: 0,
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
      dataset: [],
      count: 0,
      degraded: true,
      reason: `IPC 响应解析失败: ${e instanceof Error ? e.message : String(e)}`,
    };
  }

  if (!response.ok) {
    return {
      dataset: [],
      count: 0,
      degraded: true,
      reason: response.error?.message,
    };
  }

  const result = response.result as Record<string, unknown>;
  const dataset = Array.isArray(result.dataset) ? result.dataset : [];
  return {
    dataset,
    count: typeof result.count === "number" ? result.count : dataset.length,
    degraded: Boolean(result.degraded),
    reason: result.reason as string | undefined,
  };
}
