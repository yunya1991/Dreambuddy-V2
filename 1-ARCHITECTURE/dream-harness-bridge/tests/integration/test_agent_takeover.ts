/**
 * P0-4-S2: Agent 接管 IPC 闭环集成测试
 *
 * 测试用例:
 * 1. TC-1: T3 查询 → agent_delegated=True + decision=INSERT_BEFORE
 * 2. TC-2: 非 T3 查询 → decision=CONTINUE
 * 3. TC-3: FAIL-OPEN — Python server 不可用时返回 degraded + CONTINUE
 *
 * 来源: SPEC_ALGORITHM_DRIVEN_TRAINING_LOOP.md Phase 0-4
 */

import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { spawn, ChildProcess } from "node:child_process";
import { resolve } from "node:path";
import { startPythonIPCServer, stopPythonIPCServer } from "../../packages/bridge-core/src/python-ipc";
import { requestAgentTakeover } from "../../packages/bridge-core/src/agent-takeover";

const PYTHON_SERVER_PATH = resolve(
  __dirname,
  "..",
  "..",
  "packages",
  "python-server",
  "server.py"
);

describe("P0-4: Agent 接管 IPC 闭环", () => {
  let pyServer: ChildProcess | null = null;

  beforeEach(async () => {
    pyServer = await startPythonIPCServer({
      serverPath: PYTHON_SERVER_PATH,
      env: { ENABLE_ALGORITHM_LAYER: "1" },
    });
  });

  afterEach(async () => {
    if (pyServer) {
      await stopPythonIPCServer(pyServer);
      pyServer = null;
    }
  });

  it("TC-1: T3 查询 → agent_delegated=True + decision=INSERT_BEFORE", async () => {
    const result = await requestAgentTakeover(pyServer!, {
      tier: "T3",
      confidence: 0.9,
    });

    expect(result.degraded).toBe(false);
    expect(result.agent_delegated).toBe(true);
    expect(result.decision).toBe("INSERT_BEFORE");
  });

  it("TC-2: 非 T3 查询 → decision=CONTINUE", async () => {
    const result = await requestAgentTakeover(pyServer!, {
      tier: "T1",
      confidence: 0.5,
    });

    expect(result.degraded).toBe(false);
    expect(result.agent_delegated).toBe(false);
    expect(result.decision).toBe("CONTINUE");
  });

  it("TC-3: FAIL-OPEN — Python server 不可用时返回 degraded + CONTINUE", async () => {
    const fakeProcess = spawn("python3", ["-c", "import sys; sys.exit(1)"], {
      stdio: ["pipe", "pipe", "pipe"],
    });

    await new Promise<void>((resolve) => {
      fakeProcess.on("exit", () => resolve());
    });

    const result = await requestAgentTakeover(fakeProcess, {
      tier: "T3",
      confidence: 0.9,
    });

    expect(result.degraded).toBe(true);
    expect(result.decision).toBe("CONTINUE");
  }, 15000);
});
