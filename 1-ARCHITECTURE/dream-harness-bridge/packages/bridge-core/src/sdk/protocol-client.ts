/**
 * F-01: IPC 契约版本化 — TS 侧 Protocol Client SDK
 *
 * 职责：
 * 1. 构建 IPC 请求（自动注入 schema_version）
 * 2. 解析 IPC 响应（验证 schema_version）
 * 3. 版本握手（与 Python server 协商兼容性）
 * 4. semver 兼容性检查（MAJOR 不同=不兼容，MINOR/PATCH=兼容）
 *
 * 来源: SPEC v0.3 七补.1 F-01
 * 调研: A3 契约式设计 + A6 跨语言通信
 */

import { randomUUID } from "node:crypto";
import type { ChildProcess } from "node:child_process";

export const CURRENT_SCHEMA_VERSION = "1.0.0";

export class ProtocolHandshakeError extends Error {
  code: string;
  constructor(code: string, message: string) {
    super(message);
    this.name = "ProtocolHandshakeError";
    this.code = code;
  }
}

export interface IPCRequest {
  schema_version: string;
  message_type: "request";
  method: string;
  params: Record<string, unknown>;
  id: string;
  timestamp: string;
}

export interface IPCResponse {
  schema_version: string;
  message_type: "response";
  ok: boolean;
  result?: unknown;
  error?: { code: string; message: string };
  constraint_passed?: boolean;
  id: string;
  timestamp: string;
}

export interface HandshakeResult {
  ok: boolean;
  serverVersion: string;
  compatible: boolean;
  error?: ProtocolHandshakeError;
}

export interface ProtocolClientOptions {
  version: string;
}

export function createProtocolClient(options: ProtocolClientOptions) {
  const clientVersion = options.version;

  function buildRequest(
    method: string,
    params: Record<string, unknown>
  ): IPCRequest {
    return {
      schema_version: clientVersion,
      message_type: "request" as const,
      method,
      params,
      id: randomUUID(),
      timestamp: new Date().toISOString(),
    };
  }

  function buildResponse(
    ok: boolean,
    result: unknown,
    opts?: { constraintPassed?: boolean; id?: string }
  ): IPCResponse {
    return {
      schema_version: clientVersion,
      message_type: "response" as const,
      ok,
      result: ok ? result : undefined,
      error: ok ? undefined : (result as { code: string; message: string }),
      constraint_passed: opts?.constraintPassed,
      id: opts?.id ?? randomUUID(),
      timestamp: new Date().toISOString(),
    };
  }

  /**
   * semver 兼容性检查
   * MAJOR 不同 = 不兼容
   * MINOR/PATCH 不同 = 兼容（向后兼容）
   */
  function checkCompatibility(serverVersion: string): {
    compatible: boolean;
  } {
    const clientMajor = parseInt(clientVersion.split(".")[0], 10);
    const serverMajor = parseInt(serverVersion.split(".")[0], 10);
    return { compatible: clientMajor === serverMajor };
  }

  /**
   * 解析 IPC 响应（验证 schema_version）
   * 缺少 schema_version → 抛出 ProtocolHandshakeError
   */
  function parseResponse(rawMessage: string): IPCResponse {
    let parsed: unknown;
    try {
      parsed = JSON.parse(rawMessage);
    } catch {
      throw new ProtocolHandshakeError(
        "INVALID_JSON",
        "IPC 响应不是合法 JSON"
      );
    }

    const obj = parsed as Record<string, unknown>;
    if (!obj.schema_version) {
      throw new ProtocolHandshakeError(
        "MISSING_SCHEMA_VERSION",
        "IPC 响应缺少 schema_version 字段（F-01 契约要求）"
      );
    }

    const response = obj as unknown as IPCResponse;
    const compat = checkCompatibility(response.schema_version);
    if (!compat.compatible) {
      throw new ProtocolHandshakeError(
        "VERSION_MISMATCH",
        `schema_version 不兼容：client=${clientVersion} server=${response.schema_version}`
      );
    }

    return response;
  }

  /**
   * 与 Python server 做版本握手
   * 发送 handshake_request → 接收 handshake_response → 验证兼容性
   */
  async function handshake(pyServer: ChildProcess): Promise<HandshakeResult> {
    if (!pyServer.stdin || !pyServer.stdout) {
      return {
        ok: false,
        serverVersion: "unknown",
        compatible: false,
        error: new ProtocolHandshakeError(
          "IPC_UNAVAILABLE",
          "Python server stdin/stdout 不可用"
        ),
      };
    }

    // 发送握手请求
    const handshakeReq = {
      schema_version: clientVersion,
      message_type: "handshake_request" as const,
      id: randomUUID(),
      timestamp: new Date().toISOString(),
    };
    pyServer.stdin.write(JSON.stringify(handshakeReq) + "\n");

    // 读取握手响应（带超时）
    const handshakeResp = await readLineWithTimeout(pyServer, 5000);

    if (!handshakeResp) {
      return {
        ok: false,
        serverVersion: "unknown",
        compatible: false,
        error: new ProtocolHandshakeError(
          "HANDSHAKE_TIMEOUT",
          "Python server 握手响应超时（5s）"
        ),
      };
    }

    let resp: Record<string, unknown>;
    try {
      resp = JSON.parse(handshakeResp);
    } catch {
      return {
        ok: false,
        serverVersion: "unknown",
        compatible: false,
        error: new ProtocolHandshakeError(
          "INVALID_HANDSHAKE_RESPONSE",
          "Python server 握手响应不是合法 JSON"
        ),
      };
    }

    const serverVersion = (resp.schema_version as string) ?? "unknown";
    const compat = checkCompatibility(serverVersion);

    return {
      ok: compat.compatible,
      serverVersion,
      compatible: compat.compatible,
      error: compat.compatible
        ? undefined
        : new ProtocolHandshakeError(
            "VERSION_MISMATCH",
            `版本不兼容：client=${clientVersion} server=${serverVersion}（MAJOR 不同）`
          ),
    };
  }

  return {
    buildRequest,
    buildResponse,
    checkCompatibility,
    parseResponse,
    handshake,
    get version() {
      return clientVersion;
    },
  };
}

/**
 * 带超时读取 Python server stdout 一行
 */
function readLineWithTimeout(
  pyServer: ChildProcess,
  timeoutMs: number
): Promise<string | null> {
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      resolve(null);
    }, timeoutMs);

    const onData = (chunk: Buffer) => {
      clearTimeout(timer);
      pyServer.stdout?.removeListener("data", onData);
      resolve(chunk.toString().trim());
    };

    pyServer.stdout?.once("data", onData);
  });
}
