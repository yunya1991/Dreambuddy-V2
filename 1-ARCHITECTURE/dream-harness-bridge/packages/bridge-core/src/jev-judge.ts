/**
 * Jev (TypeSafe System One Model) TS 侧调用器
 *
 * 职责:
 * 1. 构建 jev_judge IPC 请求（复用 anasbekheit evaluate 契约）
 * 2. 发送到 Python server，读取响应
 * 3. FAIL-OPEN: 任何异常返回 degraded，不阻塞调用方
 *
 * 接口契约（复用 anasbekheit/typesafe-jev-mcp evaluate）:
 *   Request:  { state, questions: { name: {type, instructions, criteria} } }
 *   Response: { model, answers: { name: {type, noul|choice|score, ...} }, usage }
 *
 * 边界守护（HC-9 硬约束）:
 * - 只调用 IPC，不做任何交易判断
 * - 禁止出现交易判断逻辑（技术指标判断、仓位判断、盈亏判断、方向判断）
 *
 * HC-5 边界守护:
 * - 不计算 reward（response 中不应包含 reward 字段，Python 侧已保证）
 *
 * 来源: Jev 引入调研（2026-09-22）
 */

import type { ChildProcess } from "node:child_process";
import {
  createProtocolClient,
  CURRENT_SCHEMA_VERSION,
  type IPCResponse,
} from "./sdk/protocol-client";

// ============================================================
// 类型定义（复用 anasbekheit evaluate 契约）
// ============================================================

/** Jev 三种原语的问题定义 */
export type JevQuestion =
  | { type: "noul"; instructions: string }
  | {
      type: "choice";
      instructions: string;
      criteria: Record<string, string>;
    }
  | {
      type: "score";
      instructions: string;
      criteria: string[];
    };

/** Jev 三种原语的回答 */
export type JevAnswer =
  | { type: "noul"; noul: number }
  | {
      type: "choice";
      choice: string;
      confidence: number;
      probabilities: Record<string, number>;
    }
  | {
      type: "score";
      score: number;
      legend: Record<string, string>;
      probabilities: Record<string, number>;
      confidence: number;
    };

/** jev_judge 请求参数 */
export interface JevJudgeParams {
  state: unknown;
  questions: Record<string, JevQuestion>;
}

/** jev_judge 返回结果 */
export interface JevJudgeResult {
  model?: string;
  answers: Record<string, JevAnswer>;
  usage?: { input_tokens?: number; output_tokens?: number };
  degraded: boolean;
  reason?: string;
}

// ============================================================
// IPC 调用
// ============================================================

/**
 * 调用 jev_judge IPC
 *
 * @param pyServer Python IPC server 子进程
 * @param params 判断参数（state + questions）
 * @returns Jev 判断结果（FAIL-OPEN 时返回 degraded）
 *
 * HC-9: 此函数只调用 IPC，不做任何判断
 */
export async function judgeViaJev(
  pyServer: ChildProcess,
  params: JevJudgeParams
): Promise<JevJudgeResult> {
  const client = createProtocolClient({ version: CURRENT_SCHEMA_VERSION });

  // 1. 构建 IPC 请求
  const request = client.buildRequest("jev_judge", {
    state: params.state,
    questions: params.questions,
  });

  // 2. 发送并读取响应（带超时 + 按行过滤非 IPC 内容）
  const rawLine = await new Promise<string | null>((resolve) => {
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
          // 非 JSON 行，忽略
        }
      }
    };

    pyServer.stdout.on("data", onData);
    pyServer.stdin.write(JSON.stringify(request) + "\n");
  });

  // 3. 无响应 → FAIL-OPEN
  if (!rawLine) {
    return {
      answers: {},
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
      answers: {},
      degraded: true,
      reason: `IPC 响应解析失败: ${e instanceof Error ? e.message : String(e)}`,
    };
  }

  if (!response.ok) {
    return {
      answers: {},
      degraded: true,
      reason: response.error?.message,
    };
  }

  return response.result as JevJudgeResult;
}
