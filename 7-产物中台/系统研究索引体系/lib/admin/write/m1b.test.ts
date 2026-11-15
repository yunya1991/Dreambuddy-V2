// ============================================================================
// M1b 单测（SPEC-7 §14）：状态机白名单 / monitor 白名单 / Bridge 契约与结果映射
// 只覆盖纯逻辑，不连库、不连 27（fetch 用桩替换）。
// ============================================================================

import test from "node:test";
import assert from "node:assert/strict";
import { AdminError } from "../errors.ts";
import {
  assertOrderTransition,
  assertStrategyTransition,
  assertTaskTransition,
  assertTradingStatusTarget,
} from "./state-machines.ts";
import { isAdminFileKey, planMonitorPatch, repoRoot, resolveConfigPath } from "./file-config.ts";
import {
  BRIDGE_CONFIG_KEYS,
  bridgeFailureWarning,
  putGovernanceConfig,
  syncStrategyStatus,
  syncTradingConfig,
} from "./bridge.ts";

function expectAdminError(fn: () => void, code: string, messagePart?: string) {
  assert.throws(fn, (error: unknown) => {
    assert.ok(error instanceof AdminError, "应抛出 AdminError");
    assert.equal(error.code, code);
    if (messagePart) assert.ok(error.message.includes(messagePart), error.message);
    return true;
  });
}

// ---------------------------------------------------------------- 状态机

test("策略状态机：合法迁移放行", () => {
  assert.doesNotThrow(() => assertStrategyTransition("APPROVED", "APPLIED"));
  assert.doesNotThrow(() => assertStrategyTransition("APPLIED", "PAUSED"));
  assert.doesNotThrow(() => assertStrategyTransition("PAUSED", "APPLIED"));
  assert.doesNotThrow(() => assertStrategyTransition("DRAFT", "APPROVED"));
});

test("策略状态机：非法迁移/同值/终态一律 RULE_BLOCKED", () => {
  expectAdminError(() => assertStrategyTransition("APPLIED", "DRAFT"), "RULE_BLOCKED");
  expectAdminError(() => assertStrategyTransition("EXPIRED", "APPLIED"), "RULE_BLOCKED");
  expectAdminError(() => assertStrategyTransition("PAUSED", "PAUSED"), "RULE_BLOCKED");
});

test("任务状态机：ACTIVE↔PAUSED，COMPLETED 终态", () => {
  assert.doesNotThrow(() => assertTaskTransition("ACTIVE", "PAUSED"));
  assert.doesNotThrow(() => assertTaskTransition("PAUSED", "ACTIVE"));
  assert.doesNotThrow(() => assertTaskTransition("FAILED", "ACTIVE"));
  expectAdminError(() => assertTaskTransition("COMPLETED", "ACTIVE"), "RULE_BLOCKED");
  expectAdminError(() => assertTaskTransition("ACTIVE", "FAILED"), "RULE_BLOCKED");
});

test("订单状态机：仅 PENDING→CANCELLED、PAID→COMPLETED", () => {
  assert.doesNotThrow(() => assertOrderTransition("PENDING", "CANCELLED"));
  assert.doesNotThrow(() => assertOrderTransition("PAID", "COMPLETED"));
  expectAdminError(() => assertOrderTransition("PENDING", "COMPLETED"), "RULE_BLOCKED");
  expectAdminError(() => assertOrderTransition("PAID", "CANCELLED"), "RULE_BLOCKED");
  expectAdminError(() => assertOrderTransition("COMPLETED", "CANCELLED"), "RULE_BLOCKED");
});

test("交易状态：管理员不得直接置 LOCKED", () => {
  assert.doesNotThrow(() => assertTradingStatusTarget("ACTIVE"));
  assert.doesNotThrow(() => assertTradingStatusTarget("PAUSED"));
  assert.doesNotThrow(() => assertTradingStatusTarget("FROZEN"));
  expectAdminError(() => assertTradingStatusTarget("LOCKED"), "RULE_BLOCKED", "LOCKED");
});

// ---------------------------------------------------------------- monitor 白名单

const MONITOR_BASE = {
  systems: {
    yijing: { enabled: true, max_idle_minutes: 30 },
    bdsm: { enabled: false, max_idle_minutes: 60 },
  },
  interval_minutes: 60,
};

test("monitor 白名单：合法 key 产出 before/after/next", () => {
  const plan = planMonitorPatch(MONITOR_BASE, {
    "systems.yijing.enabled": false,
    "systems.bdsm.max_idle_minutes": 15,
  });
  assert.deepEqual(plan.before, {
    "systems.yijing.enabled": true,
    "systems.bdsm.max_idle_minutes": 60,
  });
  assert.deepEqual(plan.after, {
    "systems.yijing.enabled": false,
    "systems.bdsm.max_idle_minutes": 15,
  });
  const next = plan.next as typeof MONITOR_BASE;
  assert.equal(next.systems.yijing.enabled, false);
  assert.equal(next.systems.bdsm.max_idle_minutes, 15);
  // 原对象不被就地修改
  assert.equal(MONITOR_BASE.systems.yijing.enabled, true);
});

test("monitor 白名单：越权 key / 未知系统 / 非法取值全部拒绝", () => {
  expectAdminError(
    () => planMonitorPatch(MONITOR_BASE, { "interval_minutes": 5 }),
    "VALIDATION_FAILED",
  );
  expectAdminError(
    () => planMonitorPatch(MONITOR_BASE, { "systems.unknown_sys.enabled": true }),
    "RULE_BLOCKED",
  );
  expectAdminError(
    () => planMonitorPatch(MONITOR_BASE, { "systems.yijing.webhook": "http://x" }),
    "VALIDATION_FAILED",
  );
  expectAdminError(
    () => planMonitorPatch(MONITOR_BASE, { "systems.yijing.enabled": "yes" }),
    "VALIDATION_FAILED",
  );
  expectAdminError(
    () => planMonitorPatch(MONITOR_BASE, { "systems.yijing.max_idle_minutes": 0 }),
    "VALIDATION_FAILED",
  );
  expectAdminError(
    () => planMonitorPatch(MONITOR_BASE, { "systems.yijing.max_idle_minutes": 1.5 }),
    "VALIDATION_FAILED",
  );
  expectAdminError(
    () => planMonitorPatch(MONITOR_BASE, { "systems.yijing.max_idle_minutes": 1441 }),
    "VALIDATION_FAILED",
  );
  expectAdminError(() => planMonitorPatch(MONITOR_BASE, {}), "VALIDATION_FAILED");
});

test("fileKey 枚举与路径约束", () => {
  assert.equal(isAdminFileKey("monitor"), true);
  assert.equal(isAdminFileKey("../../etc/passwd"), false);
  assert.equal(isAdminFileKey(""), false);
  const p = resolveConfigPath("monitor");
  assert.ok(p.startsWith(repoRoot()));
  assert.ok(p.endsWith("15-监控告警系统/config/monitor_config.json"));
});

// ---------------------------------------------------------------- Bridge 契约

function stubFetch(handler: (url: string, init: RequestInit) => Response) {
  const original = globalThis.fetch;
  const calls: Array<{ url: string; init: RequestInit }> = [];
  globalThis.fetch = (async (input: string | URL | Request, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const requestInit = init || {};
    calls.push({ url, init: requestInit });
    return handler(url, requestInit);
  }) as typeof fetch;
  return {
    calls,
    restore() {
      globalThis.fetch = original;
    },
  };
}

test("Bridge：交易开关与状态合并进同一 trading 命名空间", async () => {
  process.env.GOVERNANCE_ADMIN_TOKEN = "test-token";
  const stub = stubFetch(() =>
    Response.json({ ok: true, config: {} }),
  );
  try {
    const outcome = await syncTradingConfig({ liveTradingEnabled: false, status: "PAUSED" });
    assert.equal(outcome.ok, true);
    assert.equal(stub.calls.length, 1);
    const body = JSON.parse(String(stub.calls[0].init.body));
    assert.deepEqual(body, {
      [BRIDGE_CONFIG_KEYS.tradingNamespace]: {
        [BRIDGE_CONFIG_KEYS.liveTradingEnabled]: false,
        [BRIDGE_CONFIG_KEYS.tradingStatus]: "PAUSED",
      },
    });
    const headers = stub.calls[0].init.headers as Record<string, string>;
    assert.equal(headers["X-Admin-Token"], "test-token");
  } finally {
    stub.restore();
  }
});

test("Bridge：27 返回非 2xx → ok:false 且保留 patch 供补偿", async () => {
  process.env.GOVERNANCE_ADMIN_TOKEN = "test-token";
  const stub = stubFetch(() => Response.json({ error: "boom" }, { status: 500 }));
  try {
    const outcome = await putGovernanceConfig({ trading: { live_trading_enabled: true } });
    assert.equal(outcome.ok, false);
    assert.equal(outcome.error, "boom");
    const warning = bridgeFailureWarning("bridge_sync_failed", outcome);
    assert.deepEqual(warning.patch, { trading: { live_trading_enabled: true } });
    assert.equal(warning.attempts, 1);
  } finally {
    stub.restore();
  }
});

test("Bridge：缺少 GOVERNANCE_ADMIN_TOKEN 直接失败，不发请求", async () => {
  delete process.env.GOVERNANCE_ADMIN_TOKEN;
  const stub = stubFetch(() => Response.json({ ok: true }));
  try {
    const outcome = await putGovernanceConfig({ trading: { live_trading_enabled: true } });
    assert.equal(outcome.ok, false);
    assert.match(outcome.error || "", /GOVERNANCE_ADMIN_TOKEN/);
    assert.equal(stub.calls.length, 0);
  } finally {
    stub.restore();
  }
});

test("Bridge：网络异常归一为 ok:false（不抛出）", async () => {
  process.env.GOVERNANCE_ADMIN_TOKEN = "test-token";
  const stub = stubFetch(() => {
    throw new Error("ECONNREFUSED");
  });
  try {
    const outcome = await syncStrategyStatus("S-1", "PAUSED");
    assert.equal(outcome.ok, false);
    assert.match(outcome.error || "", /ECONNREFUSED/);
  } finally {
    stub.restore();
  }
});

test("Bridge：策略下发写入 strategy_status[strategyId]", async () => {
  process.env.GOVERNANCE_ADMIN_TOKEN = "test-token";
  const stub = stubFetch(() => Response.json({ ok: true }));
  try {
    const outcome = await syncStrategyStatus("S-9", "PAUSED");
    assert.equal(outcome.ok, true);
    const body = JSON.parse(String(stub.calls[0].init.body));
    assert.equal(body[BRIDGE_CONFIG_KEYS.strategyStatusNamespace]["S-9"].status, "PAUSED");
  } finally {
    stub.restore();
  }
});
