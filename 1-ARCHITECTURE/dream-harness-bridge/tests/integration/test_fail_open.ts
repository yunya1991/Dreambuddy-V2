/**
 * L2-FA-4: FAIL-OPEN 铁律验证
 *
 * 验证当 Python server 不可用时，所有 IPC 调用返回 degraded，不抛异常。
 *
 * 测试用例:
 * 1. TC-1: recognizeViaAlgorithm — Python server 不可用 → degraded=True
 * 2. TC-2: shadowReview — Python server 不可用 → degraded/skipped
 * 3. TC-3: requestAgentTakeover — Python server 不可用 → degraded=True + CONTINUE
 * 4. TC-4: requestLabel — Python server 不可用 → degraded=True
 * 5. TC-5: publishModelUpdate — Python server 不可用 → degraded=True
 *
 * 来源: SPEC_ALGORITHM_DRIVEN_TRAINING_LOOP.md FAIL-OPEN 铁律
 */

import { describe, it, expect } from "vitest";
import { spawn, ChildProcess } from "node:child_process";
import { resolve } from "node:path";
import { recognizeViaAlgorithm } from "../../packages/bridge-core/src/algorithm-listener";
import { shadowReview } from "../../packages/bridge-core/src/shadow-reviewer";
import { requestAgentTakeover } from "../../packages/bridge-core/src/agent-takeover";
import { requestLabel } from "../../packages/bridge-core/src/label-requester";
import { publishModelUpdate } from "../../packages/bridge-core/src/training-data-bridge";

/**
 * 创建一个已退出的假 Python 进程（模拟 kill -9 后的状态）
 */
function createDeadProcess(): ChildProcess {
  const proc = spawn("python3", ["-c", "import sys; sys.exit(1)"], {
    stdio: ["pipe", "pipe", "pipe"],
  });
  return proc;
}

async function waitForExit(proc: ChildProcess): Promise<void> {
  return new Promise((resolve) => {
    if (proc.exitCode !== null || proc.killed) {
      resolve();
      return;
    }
    proc.once("exit", () => resolve());
  });
}

describe("L2-FA-4: FAIL-OPEN 铁律", () => {
  it("TC-1: recognizeViaAlgorithm — Python server 不可用 → degraded=True", async () => {
    const deadProc = createDeadProcess();
    await waitForExit(deadProc);

    const result = await recognizeViaAlgorithm(deadProc, {
      user_message: "BTC 多少钱",
    });

    expect(result.degraded).toBe(true);
    expect(result.intent_type).toBe("UNCERTAIN");
    expect(result.confidence).toBe(0);
    // 不抛异常 = PASS
  }, 15000);

  it("TC-2: shadowReview — Python server 不可用 → degraded/skipped", async () => {
    const deadProc = createDeadProcess();
    await waitForExit(deadProc);

    const result = await shadowReview(deadProc, {
      intent_type: "TREND_FOLLOWING",
      confidence: 0.7,
      tier: "T1",
    });

    // 采样跳过 → skipped + degraded=false
    // 采样命中 + IPC 失败 → skipped + degraded=true
    // 两种情况都返回 skipped
    expect(result.review_result).toBe("skipped");
    // 不抛异常 = PASS
  }, 15000);

  it("TC-3: requestAgentTakeover — Python server 不可用 → degraded=True + CONTINUE", async () => {
    const deadProc = createDeadProcess();
    await waitForExit(deadProc);

    const result = await requestAgentTakeover(deadProc, {
      tier: "T3",
      confidence: 0.9,
    });

    expect(result.degraded).toBe(true);
    expect(result.decision).toBe("CONTINUE");
    expect(result.agent_delegated).toBe(false);
    // 不抛异常 = PASS
  }, 15000);

  it("TC-4: requestLabel — Python server 不可用 → degraded=True", async () => {
    const deadProc = createDeadProcess();
    await waitForExit(deadProc);

    const result = await requestLabel(deadProc, {
      user_message: "ETH 行情",
      intent_type: "UNCERTAIN",
      confidence: 0.3,
      tier: "T1",
    });

    expect(result.degraded).toBe(true);
    expect(result.sample_id).toBeNull();
    // 不抛异常 = PASS
  }, 15000);

  it("TC-5: publishModelUpdate — Python server 不可用 → degraded=True", async () => {
    const deadProc = createDeadProcess();
    await waitForExit(deadProc);

    const result = await publishModelUpdate(deadProc, {
      model_id: "test_model",
      version: "0.0.1",
      metrics: { accuracy: 0.5 },
      dataset_size: 100,
      training_params: {},
    });

    expect(result.degraded).toBe(true);
    expect(result.registered).toBe(false);
    // 不抛异常 = PASS
  }, 15000);
});
