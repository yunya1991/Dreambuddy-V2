/**
 * P0-3-S1: Layer 2 影子评审 TS 侧调用器
 *
 * 职责:
 * 1. 采样 30% 流量，对算法识别结果做"影子评审"
 * 2. 调用 shadow_review IPC，获取评审结果
 * 3. FAIL-OPEN: 任何异常返回 degraded，不阻塞交易热路径
 *
 * 边界守护（HC-9 硬约束）:
 * - 只调用 IPC，不做任何交易判断
 * - 禁止出现交易判断逻辑（技术指标判断、仓位判断、盈亏判断、方向判断）
 * - 评审结果只产出标注元数据，不下交易指令
 *
 * HC-5 边界守护:
 * - 不计算 reward（reward 由 EvolutionEngine 内部 tanh(pnl_pct/0.02) 计算）
 * - response 中不应包含 reward 字段
 *
 * 来源: SPEC_ALGORITHM_DRIVEN_TRAINING_LOOP.md Phase 0-3
 */

import type { ChildProcess } from "node:child_process";
import {
  createProtocolClient,
  CURRENT_SCHEMA_VERSION,
  type IPCResponse,
} from "./sdk/protocol-client";

export interface ShadowReviewParams {
  algorithm_result: {
    intent_type?: string;
    confidence?: number;
    tier?: string;
    base_chain?: string[];
    agent_takeover_needed?: boolean;
    [key: string]: unknown;
  };
}

export interface ShadowReviewResult {
  review_result: string;  // "consistent" | "divergent" | "uncertain" | "skipped"
  review_confidence: number;
  similar_cases_count: number;
  degraded: boolean;
  reason?: string;
}

const SHADOW_REVIEW_SAMPLE_RATE = 0.30;

/**
 * 影子评审 — 采样调用 shadow_review IPC
 *
 * @param pyServer Python IPC server 子进程
 * @param algorithmResult 算法识别结果
 * @returns 评审结果（FAIL-OPEN 时返回 degraded）
 *
 * HC-9: 此函数只调用 IPC，不做任何交易判断
 */
export async function shadowReview(
  pyServer: ChildProcess,
  algorithmResult: ShadowReviewParams["algorithm_result"]
): Promise<ShadowReviewResult> {
  // 采样: 30% 流量送评审
  const sampled = Math.random();
  const shouldReview = sampled < SHADOW_REVIEW_SAMPLE_RATE;

  if (!shouldReview) {
    return {
      review_result: "skipped",
      review_confidence: 0.0,
      similar_cases_count: 0,
      degraded: false,
      reason: "not_sampled",
    };
  }

  const client = createProtocolClient({ version: CURRENT_SCHEMA_VERSION });

  // 构建 IPC 请求
  const request = client.buildRequest("shadow_review", {
    algorithm_result: algorithmResult,
  } as Record<string, unknown>);

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
      review_result: "skipped",
      review_confidence: 0.0,
      similar_cases_count: 0,
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
      review_result: "skipped",
      review_confidence: 0.0,
      similar_cases_count: 0,
      degraded: true,
      reason: `IPC 响应解析失败: ${e instanceof Error ? e.message : String(e)}`,
    };
  }

  if (!response.ok) {
    return {
      review_result: "skipped",
      review_confidence: 0.0,
      similar_cases_count: 0,
      degraded: true,
      reason: response.error?.message,
    };
  }

  const result = response.result as ShadowReviewResult;
  // HC-5 验证: response 不应包含 reward 字段
  // （Python 侧 handle_shadow_review 保证不返回 reward）
  return result;
}
