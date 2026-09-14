/**
 * F-10: 反思维决策跨语言语义等价性测试
 *
 * 测试目标（RED → GREEN）:
 * 1. 每种反思维决策 TS 构建请求 → Python 处理 → 响应回到 TS，验证 decision 字段等价
 * 2. CONTINUE: TS 发送 → Python 回显 decision=CONTINUE
 * 3. REDO: TS 发送 → Python 回显 decision=REDO
 * 4. INSERT_BEFORE: TS 发送含 target_step → Python 回显 decision=INSERT_BEFORE + target_step
 * 5. JUMP_TO: TS 发送含 target_step → Python 回显 decision=JUMP_TO + target_step
 * 6. EARLY_TERMINATE: TS 发送 → Python 回显 decision=EARLY_TERMINATE
 * 7. 非法 decision → 错误响应
 * 8. Python reflection_handler 直接调用语义等价
 *
 * 来源: SPEC v0.3 七补.1 F-10
 */

import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { spawn, ChildProcess, execSync } from "node:child_process";
import { resolve } from "node:path";
import {
  createProtocolClient,
  CURRENT_SCHEMA_VERSION,
} from "../../packages/bridge-core/src/sdk/protocol-client";
import {
  startPythonIPCServer,
  stopPythonIPCServer,
} from "../../packages/bridge-core/src/python-ipc";
import {
  buildReflectionRequest,
  parseReflectionResponse,
  ReflectionProtocolError,
  REFLECTION_METHOD,
  VALID_DECISIONS,
} from "../../packages/bridge-core/src/reflection-protocol";

const PYTHON_SERVER_PATH = resolve(
  __dirname,
  "..",
  "..",
  "packages",
  "python-server",
  "server.py"
);

const REFLECTION_HANDLER_PATH = resolve(
  __dirname,
  "..",
  "..",
  "packages",
  "python-server",
  "reflection_handler.py"
);

describe("F-10: 反思维决策跨语言语义等价性测试", () => {
  let pyServer: ChildProcess | null = null;
  let client: ReturnType<typeof createProtocolClient>;

  beforeEach(async () => {
    pyServer = await startPythonIPCServer({
      serverPath: PYTHON_SERVER_PATH,
    });
    client = createProtocolClient({ version: CURRENT_SCHEMA_VERSION });
  });

  afterEach(async () => {
    if (pyServer) {
      await stopPythonIPCServer(pyServer);
      pyServer = null;
    }
  });

  describe("1. IPC 跨语言语义等价（TS 构建 → Python 回显 → TS 解析）", () => {
    it("CONTINUE: TS 发送 → Python 回显 decision=CONTINUE", async () => {
      const request = buildReflectionRequest("CONTINUE", { reason: "next step ready" });
      const rawLine = await sendAndReadRaw(pyServer!, JSON.stringify(request));

      expect(rawLine).not.toBeNull();
      const result = parseReflectionResponse(rawLine!);

      expect(result.decision).toBe("CONTINUE");
      expect(result.executed).toBe(true);
      expect(result.params.decision).toBe("CONTINUE");
    });

    it("REDO: TS 发送 → Python 回显 decision=REDO", async () => {
      const request = buildReflectionRequest("REDO", { reason: "retry current step" });
      const rawLine = await sendAndReadRaw(pyServer!, JSON.stringify(request));

      expect(rawLine).not.toBeNull();
      const result = parseReflectionResponse(rawLine!);

      expect(result.decision).toBe("REDO");
      expect(result.executed).toBe(true);
      expect(result.params.decision).toBe("REDO");
    });

    it("INSERT_BEFORE: TS 发送含 target_step → Python 回显 decision=INSERT_BEFORE + target_step", async () => {
      const request = buildReflectionRequest("INSERT_BEFORE", {
        target_step: 3,
        reason: "insert validation step",
      });
      const rawLine = await sendAndReadRaw(pyServer!, JSON.stringify(request));

      expect(rawLine).not.toBeNull();
      const result = parseReflectionResponse(rawLine!);

      expect(result.decision).toBe("INSERT_BEFORE");
      expect(result.executed).toBe(true);
      expect(result.params.target_step).toBe(3);
      expect(result.params.decision).toBe("INSERT_BEFORE");
    });

    it("JUMP_TO: TS 发送含 target_step → Python 回显 decision=JUMP_TO + target_step", async () => {
      const request = buildReflectionRequest("JUMP_TO", {
        target_step: "step-5",
        reason: "skip to sync phase",
      });
      const rawLine = await sendAndReadRaw(pyServer!, JSON.stringify(request));

      expect(rawLine).not.toBeNull();
      const result = parseReflectionResponse(rawLine!);

      expect(result.decision).toBe("JUMP_TO");
      expect(result.executed).toBe(true);
      expect(result.params.target_step).toBe("step-5");
      expect(result.params.decision).toBe("JUMP_TO");
    });

    it("EARLY_TERMINATE: TS 发送 → Python 回显 decision=EARLY_TERMINATE", async () => {
      const request = buildReflectionRequest("EARLY_TERMINATE", {
        reason: "all goals achieved",
      });
      const rawLine = await sendAndReadRaw(pyServer!, JSON.stringify(request));

      expect(rawLine).not.toBeNull();
      const result = parseReflectionResponse(rawLine!);

      expect(result.decision).toBe("EARLY_TERMINATE");
      expect(result.executed).toBe(true);
      expect(result.params.decision).toBe("EARLY_TERMINATE");
    });
  });

  describe("2. 全量决策覆盖（确保 5 种决策全部等价）", () => {
    // 动态生成 5 种决策的测试用例，确保无一遗漏
    const cases: Array<[string, Record<string, unknown>]> = [
      ["CONTINUE", {}],
      ["REDO", {}],
      ["INSERT_BEFORE", { target_step: 1 }],
      ["JUMP_TO", { target_step: 2 }],
      ["EARLY_TERMINATE", {}],
    ];

    cases.forEach(([decision, extra]) => {
      it(`${decision}: 全量覆盖 — decision 字段语义等价`, async () => {
        const request = buildReflectionRequest(
          decision as (typeof VALID_DECISIONS)[number],
          extra
        );
        // 验证 TS 构建的请求结构
        expect(request.method).toBe(REFLECTION_METHOD);
        expect(request.schema_version).toBe(CURRENT_SCHEMA_VERSION);
        expect(request.params.decision).toBe(decision);

        // 发送到 Python 并解析回显
        const rawLine = await sendAndReadRaw(pyServer!, JSON.stringify(request));
        expect(rawLine).not.toBeNull();

        const result = parseReflectionResponse(rawLine!);
        expect(result.decision).toBe(decision);
        expect(result.params.decision).toBe(decision);
      });
    });

    it("VALID_DECISIONS 恰好包含 5 种决策且无遗漏", () => {
      expect(VALID_DECISIONS).toHaveLength(5);
      expect(VALID_DECISIONS).toContain("CONTINUE");
      expect(VALID_DECISIONS).toContain("REDO");
      expect(VALID_DECISIONS).toContain("INSERT_BEFORE");
      expect(VALID_DECISIONS).toContain("JUMP_TO");
      expect(VALID_DECISIONS).toContain("EARLY_TERMINATE");
    });
  });

  describe("3. 非法 decision 错误处理", () => {
    it("非法 decision → buildReflectionRequest 抛出错误（TS 侧校验）", () => {
      expect(() =>
        buildReflectionRequest("INVALID_DECISION" as never, {})
      ).toThrow(ReflectionProtocolError);
    });

    it("非法 decision → parseReflectionResponse 检测到错误（响应侧校验）", async () => {
      // 绕过 buildReflectionRequest 校验，直接发送非法 decision
      const rawRequest = JSON.stringify({
        schema_version: CURRENT_SCHEMA_VERSION,
        message_type: "request",
        method: REFLECTION_METHOD,
        params: { decision: "NOT_A_REAL_DECISION" },
        id: "illegal-test-id",
        timestamp: new Date().toISOString(),
      });

      const rawLine = await sendAndReadRaw(pyServer!, rawRequest);
      expect(rawLine).not.toBeNull();

      // Python server.py 会 echo 回非法 decision，parseReflectionResponse 应检测到
      expect(() => parseReflectionResponse(rawLine!)).toThrow(
        ReflectionProtocolError
      );
    });

    it("INSERT_BEFORE 缺少 target_step → buildReflectionRequest 抛出", () => {
      expect(() =>
        buildReflectionRequest("INSERT_BEFORE", { reason: "no target" })
      ).toThrow(ReflectionProtocolError);
    });

    it("JUMP_TO 缺少 target_step → buildReflectionRequest 抛出", () => {
      expect(() =>
        buildReflectionRequest("JUMP_TO", { reason: "no target" })
      ).toThrow(ReflectionProtocolError);
    });

    it("CONTINUE 不需要 target_step → 不抛出", () => {
      expect(() => buildReflectionRequest("CONTINUE", {})).not.toThrow();
    });
  });

  describe("4. Python reflection_handler 直接调用语义等价性", () => {
    it("handle_reflection(CONTINUE) → {decision, executed, params}", () => {
      const output = runPythonReflection("CONTINUE", {});
      expect(output.ok).toBe(true);
      expect(output.result.decision).toBe("CONTINUE");
      expect(output.result.executed).toBe(true);
      expect(output.result.params).toEqual({});
    });

    it("handle_reflection(REDO) → {decision, executed, params}", () => {
      const output = runPythonReflection("REDO", {});
      expect(output.ok).toBe(true);
      expect(output.result.decision).toBe("REDO");
    });

    it("handle_reflection(INSERT_BEFORE) with target_step → 正确结构", () => {
      const output = runPythonReflection("INSERT_BEFORE", { target_step: 3 });
      expect(output.ok).toBe(true);
      expect(output.result.decision).toBe("INSERT_BEFORE");
      expect(output.result.params.target_step).toBe(3);
    });

    it("handle_reflection(JUMP_TO) with target_step → 正确结构", () => {
      const output = runPythonReflection("JUMP_TO", { target_step: "step-5" });
      expect(output.ok).toBe(true);
      expect(output.result.decision).toBe("JUMP_TO");
      expect(output.result.params.target_step).toBe("step-5");
    });

    it("handle_reflection(EARLY_TERMINATE) → 正确结构", () => {
      const output = runPythonReflection("EARLY_TERMINATE", {});
      expect(output.ok).toBe(true);
      expect(output.result.decision).toBe("EARLY_TERMINATE");
    });

    it("handle_reflection(非法 decision) → 错误响应", () => {
      const output = runPythonReflection("INVALID", {});
      expect(output.ok).toBe(false);
      expect(output.error.code).toBe("INVALID_DECISION");
    });

    it("handle_reflection(INSERT_BEFORE) 缺少 target_step → 错误响应", () => {
      const output = runPythonReflection("INSERT_BEFORE", {});
      expect(output.ok).toBe(false);
      expect(output.error.code).toBe("MISSING_TARGET_STEP");
    });

    it("TS↔Python decision 语义完全一致（5 种决策逐一对照）", () => {
      // TS 侧 buildReflectionRequest 不抛 + Python 侧 handle_reflection 返回 ok
      const pairs: Array<[string, Record<string, unknown>]> = [
        ["CONTINUE", {}],
        ["REDO", {}],
        ["INSERT_BEFORE", { target_step: 1 }],
        ["JUMP_TO", { target_step: 2 }],
        ["EARLY_TERMINATE", {}],
      ];

      pairs.forEach(([decision, params]) => {
        // TS 侧
        const tsReq = buildReflectionRequest(
          decision as (typeof VALID_DECISIONS)[number],
          params
        );
        expect(tsReq.params.decision).toBe(decision);

        // Python 侧
        const pyResult = runPythonReflection(decision, params);
        expect(pyResult.ok).toBe(true);
        expect(pyResult.result.decision).toBe(decision);
        expect(pyResult.result.executed).toBe(true);

        // 语义等价: TS 发送的 decision == Python 回显的 decision
        expect(tsReq.params.decision).toBe(pyResult.result.decision);
      });
    });
  });

  describe("5. 跨语言 IPC 链路完整性", () => {
    it("反思维决策请求 method=reflection → Python 回显 method=reflection", async () => {
      const request = buildReflectionRequest("CONTINUE", {});
      const rawLine = await sendAndReadRaw(pyServer!, JSON.stringify(request));
      expect(rawLine).not.toBeNull();

      const parsed = JSON.parse(rawLine!);
      expect(parsed.ok).toBe(true);
      expect(parsed.result.echo.method).toBe(REFLECTION_METHOD);
    });

    it("schema_version 跨语言保持一致", async () => {
      const request = buildReflectionRequest("CONTINUE", {});
      const rawLine = await sendAndReadRaw(pyServer!, JSON.stringify(request));
      expect(rawLine).not.toBeNull();

      const parsed = JSON.parse(rawLine!);
      expect(parsed.schema_version).toBe(CURRENT_SCHEMA_VERSION);
    });

    it("连续多决策请求链路稳定", async () => {
      const decisions: Array<[string, Record<string, unknown>]> = [
        ["CONTINUE", {}],
        ["REDO", {}],
        ["JUMP_TO", { target_step: 1 }],
        ["EARLY_TERMINATE", {}],
      ];

      for (const [decision, params] of decisions) {
        const request = buildReflectionRequest(
          decision as (typeof VALID_DECISIONS)[number],
          params
        );
        const rawLine = await sendAndReadRaw(pyServer!, JSON.stringify(request));
        expect(rawLine).not.toBeNull();

        const result = parseReflectionResponse(rawLine!);
        expect(result.decision).toBe(decision);
      }
    });
  });
});

/**
 * 辅助函数：发送原始 JSON 字符串并读取一行响应
 * 参考: tests/integration/test_f03_linkage_alive.ts sendAndReadRaw
 */
async function sendAndReadRaw(
  pyServer: ChildProcess,
  rawMessage: string
): Promise<string | null> {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      resolve(null);
    }, 5000);

    if (!pyServer.stdin || !pyServer.stdout) {
      clearTimeout(timeout);
      reject(new Error("Python server stdin/stdout 不可用"));
      return;
    }

    const onData = (chunk: Buffer) => {
      clearTimeout(timeout);
      pyServer.stdout?.removeListener("data", onData);
      resolve(chunk.toString().trim());
    };

    pyServer.stdout.once("data", onData);
    pyServer.stdin.write(rawMessage + "\n");
  });
}

/**
 * 辅助函数：直接调用 Python reflection_handler.handle_reflection
 * 通过 CLI 方式验证 Python 侧语义等价性
 */
function runPythonReflection(
  decision: string,
  params: Record<string, unknown>
): { ok: boolean; result?: { decision: string; executed: boolean; params: Record<string, unknown> }; error?: { code: string; message: string } } {
  const arg = JSON.stringify({ decision, params });
  const cmd = `python3 "${REFLECTION_HANDLER_PATH}" '${arg.replace(/'/g, "'\\''")}'`;
  const output = execSync(cmd, {
    timeout: 10000,
    encoding: "utf-8",
    stdio: ["pipe", "pipe", "pipe"],
  });
  return JSON.parse(output.trim());
}
