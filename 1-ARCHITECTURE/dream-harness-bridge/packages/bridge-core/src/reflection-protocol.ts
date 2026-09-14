/**
 * F-10: 反思维决策跨语言语义等价性 — TS 侧协议定义
 *
 * 职责:
 * 1. 定义 ReflectionDecision 类型（CONTINUE/REDO/INSERT_BEFORE/JUMP_TO/EARLY_TERMINATE）
 * 2. buildReflectionRequest: 构建反思维决策 IPC 请求（含 decision 合法性校验）
 * 3. parseReflectionResponse: 解析反思维决策 IPC 响应（提取并校验 decision 字段）
 *
 * DreamBuddy C 层反思维决策机制 5 种决策:
 * - CONTINUE: 继续执行下一步
 * - REDO: 重新执行当前步骤
 * - INSERT_BEFORE: 在当前步骤前插入新步骤
 * - JUMP_TO: 跳转到指定步骤
 * - EARLY_TERMINATE: 提前终止
 *
 * 来源: SPEC v0.3 七补.1 F-10
 */

import { randomUUID } from "node:crypto";
import { CURRENT_SCHEMA_VERSION } from "./sdk/protocol-client";

/** 反思维决策类型 */
export type ReflectionDecision =
  | "CONTINUE"
  | "REDO"
  | "INSERT_BEFORE"
  | "JUMP_TO"
  | "EARLY_TERMINATE";

/** 合法的反思维决策列表 */
export const VALID_DECISIONS: ReflectionDecision[] = [
  "CONTINUE",
  "REDO",
  "INSERT_BEFORE",
  "JUMP_TO",
  "EARLY_TERMINATE",
];

/** 需要 target_step 参数的决策 */
const DECISIONS_REQUIRING_TARGET_STEP: ReflectionDecision[] = [
  "INSERT_BEFORE",
  "JUMP_TO",
];

/** IPC 方法名 */
export const REFLECTION_METHOD = "reflection";

/** 反思维决策参数 */
export interface ReflectionParams {
  decision: ReflectionDecision;
  /** INSERT_BEFORE / JUMP_TO 必须提供 */
  target_step?: string | number;
  /** 决策原因（可选） */
  reason?: string;
  [key: string]: unknown;
}

/** 反思维决策 IPC 请求 */
export interface ReflectionRequest {
  schema_version: string;
  message_type: "request";
  method: typeof REFLECTION_METHOD;
  params: ReflectionParams;
  id: string;
  timestamp: string;
}

/** 反思维决策解析结果 */
export interface ReflectionResult {
  decision: ReflectionDecision;
  executed: boolean;
  params: ReflectionParams;
}

/** 反思维决策 IPC 响应（server.py echo 格式） */
export interface ReflectionResponse {
  schema_version: string;
  message_type: "response";
  ok: boolean;
  result?: {
    echo?: {
      method?: string;
      params?: ReflectionParams;
    };
  };
  error?: { code: string; message: string };
  constraint_passed?: boolean;
  id: string;
  timestamp: string;
}

/** 反思维决策协议错误 */
export class ReflectionProtocolError extends Error {
  code: string;
  constructor(code: string, message: string) {
    super(message);
    this.name = "ReflectionProtocolError";
    this.code = code;
  }
}

function isValidDecision(value: unknown): value is ReflectionDecision {
  return (
    typeof value === "string" &&
    (VALID_DECISIONS as string[]).includes(value)
  );
}

/**
 * 构建反思维决策 IPC 请求
 *
 * 1. 校验 decision 合法性（非法 → 抛 ReflectionProtocolError）
 * 2. INSERT_BEFORE / JUMP_TO 必须提供 target_step
 * 3. 自动注入 schema_version / method / id / timestamp
 *
 * @param decision 反思维决策类型
 * @param params 额外参数（target_step / reason 等）
 */
export function buildReflectionRequest(
  decision: ReflectionDecision,
  params?: Partial<Omit<ReflectionParams, "decision">>
): ReflectionRequest {
  if (!isValidDecision(decision)) {
    throw new ReflectionProtocolError(
      "INVALID_DECISION",
      `非法反思维决策: ${String(decision)}（合法值: ${VALID_DECISIONS.join("/")})`
    );
  }

  if (
    DECISIONS_REQUIRING_TARGET_STEP.includes(decision) &&
    (params?.target_step === undefined || params?.target_step === null)
  ) {
    throw new ReflectionProtocolError(
      "MISSING_TARGET_STEP",
      `${decision} 需要 target_step 参数`
    );
  }

  const fullParams: ReflectionParams = {
    decision,
    ...params,
  };

  return {
    schema_version: CURRENT_SCHEMA_VERSION,
    message_type: "request" as const,
    method: REFLECTION_METHOD,
    params: fullParams,
    id: randomUUID(),
    timestamp: new Date().toISOString(),
  };
}

/**
 * 解析反思维决策 IPC 响应
 *
 * 从 server.py 的 echo 响应中提取 decision 字段并校验语义等价性:
 * 1. ok=false → 抛错（携带 error.code）
 * 2. result.echo.params.decision 必须存在且合法
 * 3. 返回 {decision, executed, params}
 *
 * @param rawMessage Python server 返回的原始 NDJSON 字符串
 */
export function parseReflectionResponse(rawMessage: string): ReflectionResult {
  let parsed: unknown;
  try {
    parsed = JSON.parse(rawMessage);
  } catch {
    throw new ReflectionProtocolError(
      "INVALID_JSON",
      "反思维决策响应不是合法 JSON"
    );
  }

  const resp = parsed as ReflectionResponse;

  if (!resp.ok) {
    throw new ReflectionProtocolError(
      "REFLECTION_RESPONSE_ERROR",
      `反思维决策响应失败: ${resp.error?.code ?? "UNKNOWN"} - ${
        resp.error?.message ?? ""
      }`
    );
  }

  const echoParams = resp.result?.echo?.params;
  if (!echoParams) {
    throw new ReflectionProtocolError(
      "INVALID_ECHO",
      "反思维决策响应缺少 result.echo.params"
    );
  }

  const decisionField = echoParams.decision;
  if (!decisionField) {
    throw new ReflectionProtocolError(
      "MISSING_DECISION",
      "反思维决策响应缺少 decision 字段"
    );
  }

  if (!isValidDecision(decisionField)) {
    throw new ReflectionProtocolError(
      "INVALID_DECISION",
      `非法 decision 字段: ${String(decisionField)}（合法值: ${VALID_DECISIONS.join(
        "/"
      )})`
    );
  }

  return {
    decision: decisionField,
    executed: true,
    params: echoParams,
  };
}
