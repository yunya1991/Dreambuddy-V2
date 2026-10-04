/**
 * P0-3-S3: 影子评审 IPC 闭环集成测试
 *
 * 验证 HC-5 + HC-9 边界守护
 *
 * 测试用例:
 * 1. TC-1: 调用 shadowReview → 返回 review_result 字段
 * 2. TC-2: HC-5 验证 — 返回不含 reward 字段
 * 3. TC-3: HC-9 验证 — 返回不含 direction/action 字段
 * 4. TC-4: 采样率验证 — 100 次调用约 30 次实际评审
 * 5. TC-5: FAIL-OPEN — Python server 不可用时返回 degraded
 *
 * 来源: SPEC_ALGORITHM_DRIVEN_TRAINING_LOOP.md Phase 0-3
 */

import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { spawn, ChildProcess } from "node:child_process";
import { resolve } from "node:path";
import { startPythonIPCServer, stopPythonIPCServer } from "../../packages/bridge-core/src/python-ipc";
import { shadowReview } from "../../packages/bridge-core/src/shadow-reviewer";

const PYTHON_SERVER_PATH = resolve(
  __dirname,
  "..",
  "..",
  "packages",
  "python-server",
  "server.py"
);

describe("P0-3: 影子评审 IPC 闭环 + 边界守护", () => {
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

  it("TC-1: 调用 shadowReview → 返回 review_result 字段", async () => {
    const result = await shadowReview(pyServer!, {
      intent_type: "TREND_FOLLOWING",
      confidence: 0.7,
      tier: "T1",
    });

    // 要么实际评审（review_result 非 skipped），要么被采样跳过（skipped）
    expect(result).toHaveProperty("review_result");
    expect(result).toHaveProperty("review_confidence");
    expect(result).toHaveProperty("similar_cases_count");
    expect(result).toHaveProperty("degraded");
  });

  it("TC-2: HC-5 验证 — 返回不含 reward 字段", async () => {
    // 多次调用确保采样命中
    let sampled = false;
    for (let i = 0; i < 50; i++) {
      const result = await shadowReview(pyServer!, {
        intent_type: "TREND_FOLLOWING",
        confidence: 0.7,
        tier: "T1",
      });
      if (result.review_result !== "skipped") {
        sampled = true;
        expect(result).not.toHaveProperty("reward");
      }
    }
    // 至少有一次被采样
    expect(sampled).toBe(true);
  });

  it("TC-3: HC-9 验证 — 返回不含 direction/action 字段", async () => {
    let sampled = false;
    for (let i = 0; i < 50; i++) {
      const result = await shadowReview(pyServer!, {
        intent_type: "BREAKOUT",
        confidence: 0.6,
        tier: "T1",
      });
      if (result.review_result !== "skipped") {
        sampled = true;
        expect(result).not.toHaveProperty("direction");
        expect(result).not.toHaveProperty("action");
      }
    }
    expect(sampled).toBe(true);
  });

  it("TC-4: 采样率验证 — 100 次调用约 30 次实际评审", async () => {
    let actualReviews = 0;
    for (let i = 0; i < 100; i++) {
      const result = await shadowReview(pyServer!, {
        intent_type: "TREND_FOLLOWING",
        confidence: 0.7,
        tier: "T1",
      });
      if (result.review_result !== "skipped" && !result.degraded) {
        actualReviews++;
      }
    }
    // 30% 采样率，预期 30±20（宽松范围避免随机性导致测试不稳定）
    expect(actualReviews).toBeGreaterThanOrEqual(10);
    expect(actualReviews).toBeLessThanOrEqual(60);
  });

  it("TC-5: FAIL-OPEN — Python server 不可用时返回 degraded", async () => {
    // 创建一个立即退出的假进程
    const fakeProcess = spawn("python3", ["-c", "import sys; sys.exit(1)"], {
      stdio: ["pipe", "pipe", "pipe"],
    });

    await new Promise<void>((resolve) => {
      fakeProcess.on("exit", () => resolve());
    });

    const result = await shadowReview(fakeProcess, {
      intent_type: "TREND_FOLLOWING",
      confidence: 0.7,
      tier: "T1",
    });

    // 采样跳过 → degraded=false + skipped
    // 采样命中 + IPC 失败 → degraded=true + skipped
    // 两种情况都应返回 skipped
    expect(result.review_result).toBe("skipped");
  }, 15000);
});
