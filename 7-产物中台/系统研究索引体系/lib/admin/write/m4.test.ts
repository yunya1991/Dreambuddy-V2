// ============================================================================
// M4 单测（SPEC-7 §13 M4 / R1 / R10）：Bridge 契约与 3.1 同源漂移守卫
// 直接读取 3.1 的 classic-system-bridge.ts 原文，断言两端下发契约一致；
// 任一端改键/改命名空间都会让本用例失败，从而强制双端同步评审。
// ============================================================================

import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { repoRoot } from "./file-config.ts";
import { BRIDGE_CONFIG_KEYS } from "./bridge.ts";

const FRONTEND_BRIDGE = path.join(
  repoRoot(),
  "3.1-FRONTEND",
  "src",
  "lib",
  "classic-system-bridge.ts",
);

function readFrontendBridge(): string {
  return fs.readFileSync(FRONTEND_BRIDGE, "utf-8");
}

test("Bridge 契约：3.1 源文件存在（漂移守卫的比对基准）", () => {
  assert.ok(fs.existsSync(FRONTEND_BRIDGE), `3.1 bridge 不存在：${FRONTEND_BRIDGE}`);
});

test("Bridge 契约：PUT 路径与鉴权头与 3.1 同源", () => {
  const source = readFrontendBridge();
  assert.ok(source.includes('"/api/v1/config"'), "3.1 应 PUT /api/v1/config");
  assert.ok(source.includes('"X-Admin-Token"'), "3.1 应使用 X-Admin-Token 鉴权头");
  assert.ok(source.includes('method: "PUT"'), "3.1 config 下发应为 PUT");
});

test("Bridge 契约：trading 命名空间与 live_trading_enabled 键与 3.1 一致", () => {
  const source = readFrontendBridge();
  assert.equal(BRIDGE_CONFIG_KEYS.tradingNamespace, "trading");
  assert.equal(BRIDGE_CONFIG_KEYS.liveTradingEnabled, "live_trading_enabled");

  // 3.1 下发形态：JSON.stringify({ trading: tradingConfig })，键名 live_trading_enabled
  assert.ok(source.includes("{ trading: tradingConfig }"), "3.1 应以 trading 命名空间下发");
  assert.ok(
    source.includes('tradingConfig["live_trading_enabled"]'),
    "3.1 应写 live_trading_enabled 键",
  );
});

test("Bridge 契约：中台扩展键不与 3.1 现有键冲突（trading_status / strategy_status）", () => {
  const source = readFrontendBridge();
  assert.equal(BRIDGE_CONFIG_KEYS.tradingStatus, "trading_status");
  assert.equal(BRIDGE_CONFIG_KEYS.strategyStatusNamespace, "strategy_status");
  // 3.1 不消费这两个键/命名空间；若未来 3.1 引入，本断言失败以触发契约评审
  assert.equal(source.includes('"trading_status"'), false, "3.1 已引入 trading_status，需评审契约");
  assert.equal(
    source.includes('"strategy_status"'),
    false,
    "3.1 已引入 strategy_status，需评审契约",
  );
});

test("Bridge 契约：常量集合稳定（新增键必须同步本文与 3.1）", () => {
  assert.deepEqual(Object.keys(BRIDGE_CONFIG_KEYS).sort(), [
    "liveTradingEnabled",
    "strategyStatusNamespace",
    "tradingNamespace",
    "tradingStatus",
  ]);
});
