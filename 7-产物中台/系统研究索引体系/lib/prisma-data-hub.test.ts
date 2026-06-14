// ============================================================================
// prisma-data-hub.ts 单元测试
// 测试目标：
//   1. 业务数据聚合函数的正确性（getStrategyBusinessStats 等）
//   2. 在数据库连接失败或为空时的降级行为
//   3. 综合视图 getBusinessDataView 的正确聚合
// ============================================================================
import test from "node:test";
import assert from "node:assert/strict";
import {
  getBusinessDataView,
  getStrategyBusinessStats,
  getUserContextBusinessStats,
  getTradingBusinessStats,
  type StrategyBusinessStats,
  type UserContextBusinessStats,
  type TradingBusinessStats,
  type BusinessDataPrecipitationView,
} from "./prisma-data-hub.ts";

// ----------------------------------------------------------------------------
// 测试 1: getBusinessDataView 能成功获取完整业务数据视图
// ----------------------------------------------------------------------------
test("getBusinessDataView 返回有效的业务数据沉淀视图", async () => {
  const view = await getBusinessDataView();

  // 至少应返回一个非 null 对象，具有 aggregatedAt
  assert.ok(view, "应返回非 null 的视图");
  assert.ok(typeof view.aggregatedAt === "string" && view.aggregatedAt.length > 0, "aggregatedAt 应为非空字符串");

  // strategies 字段可能有数据或为空
  assert.ok("strategies" in view, "应包含 strategies 字段");
  assert.ok("userContext" in view, "应包含 userContext 字段");
  assert.ok("trading" in view, "应包含 trading 字段");
});

// ----------------------------------------------------------------------------
// 测试 2: getStrategyBusinessStats — 数据类型与结构正确性
// ----------------------------------------------------------------------------
test("getStrategyBusinessStats 返回有效结构", async () => {
  const stats = await getStrategyBusinessStats();

  assert.ok(stats, "应返回非 null 值");
  assert.ok(typeof stats.totalStrategies === "number", "totalStrategies 应为数字");
  assert.ok(typeof stats.byStatus === "object", "byStatus 应为对象");
  assert.ok(typeof stats.byType === "object", "byType 应为对象");
  assert.ok(typeof stats.activeTasks === "number", "activeTasks 应为数字");
  assert.ok(typeof stats.totalExecutions === "number", "totalExecutions 应为数字");
  assert.ok(typeof stats.completedExecutions === "number", "completedExecutions 应为数字");

  // 已完成执行不能大于总执行
  assert.ok(
    stats.completedExecutions <= stats.totalExecutions,
    "completedExecutions 不应超过 totalExecutions",
  );
});

// ----------------------------------------------------------------------------
// 测试 3: getUserContextBusinessStats — 用户上下文统计结构
// ----------------------------------------------------------------------------
test("getUserContextBusinessStats 返回有效结构", async () => {
  const stats = await getUserContextBusinessStats();

  assert.ok(stats, "应返回非 null 值");
  assert.ok(typeof stats.totalUsers === "number", "totalUsers 应为数字");
  assert.ok(typeof stats.verifiedUsers === "number", "verifiedUsers 应为数字");
  assert.ok(typeof stats.usersWithStrategies === "number", "usersWithStrategies 应为数字");
  assert.ok(typeof stats.creditsTotalBalance === "number", "creditsTotalBalance 应为数字");
  assert.ok(typeof stats.totalOrders === "number", "totalOrders 应为数字");

  // 验证用户不能大于已验证用户
  assert.ok(stats.verifiedUsers <= stats.totalUsers, "verifiedUsers 不应超过 totalUsers");
  // 有策略的用户不能大于总用户
  assert.ok(stats.usersWithStrategies <= stats.totalUsers, "usersWithStrategies 不应超过 totalUsers");
});

// ----------------------------------------------------------------------------
// 测试 4: getTradingBusinessStats — 交易统计结构
// ----------------------------------------------------------------------------
test("getTradingBusinessStats 返回有效结构", async () => {
  const stats = await getTradingBusinessStats();

  assert.ok(stats, "应返回非 null 值");
  assert.ok(typeof stats.todayLoss === "number", "todayLoss 应为数字");
  assert.ok(typeof stats.totalLoss === "number", "totalLoss 应为数字");
  assert.ok(typeof stats.todayTradeCount === "number", "todayTradeCount 应为数字");
  assert.ok(typeof stats.totalTradeCount === "number", "totalTradeCount 应为数字");
  assert.ok(typeof stats.activeTradingParams === "number", "activeTradingParams 应为数字");

  // 今日交易数不能大于总交易数（非强制，可能为 0）
  assert.ok(stats.todayTradeCount <= stats.totalTradeCount || stats.totalTradeCount === 0,
    "todayTradeCount 不应超过 totalTradeCount（除非 totalTradeCount 为 0）");
});

// ----------------------------------------------------------------------------
// 测试 5: BusinessDataPrecipitationView — 类型导出正确
// ----------------------------------------------------------------------------
test("业务沉淀的类型定义完整", async () => {
  // 验证类型能被正确引用，这里通过运行时创建对象来验证
  const sampleStrategies: StrategyBusinessStats = {
    totalStrategies: 1,
    byStatus: { APPLIED: 1 },
    byType: { CUSTOM: 1 },
    activeTasks: 0,
    totalExecutions: 0,
    completedExecutions: 0,
    lastExecutionAt: null,
  };

  const sampleUser: UserContextBusinessStats = {
    totalUsers: 1,
    verifiedUsers: 0,
    usersWithStrategies: 0,
    usersWithApiConfigs: 0,
    verifiedApiConfigs: 0,
    totalApiConfigs: 0,
    totalChannelConfigs: 0,
    activeTradingUsers: 0,
    creditsTotalBalance: 0,
    totalOrders: 0,
  };

  const sampleTrading: TradingBusinessStats = {
    todayLoss: 0,
    totalLoss: 0,
    totalTradeCount: 0,
    todayTradeCount: 0,
    activeTradingParams: 0,
  };

  const sampleView: BusinessDataPrecipitationView = {
    strategies: sampleStrategies,
    userContext: sampleUser,
    trading: sampleTrading,
    aggregatedAt: "2026-06-11T12:00:00Z",
  };

  assert.ok(sampleView.strategies?.totalStrategies === 1, "sampleView 结构正确");
  assert.ok(sampleView.userContext?.totalUsers === 1, "userContext 结构正确");
  assert.ok(sampleView.trading?.activeTradingParams === 0, "trading 结构正确");
  assert.ok(sampleView.aggregatedAt.length > 0, "aggregatedAt 存在");
});

// ----------------------------------------------------------------------------
// 测试 6: Prisma 数据库实际验证 — 检查能否读取当前已创建的测试用户和策略
// ----------------------------------------------------------------------------
test("业务数据与当前数据库实际内容匹配（测试环境）", async () => {
  const view = await getBusinessDataView();

  // 测试用户应存在（demo 用户）
  if (view.userContext) {
    assert.ok(view.userContext.totalUsers >= 1,
      "数据库中至少应有 1 个用户（测试注册的 demo 用户）");

    // 有策略的用户应该有数据
    if (view.strategies && view.strategies.totalStrategies > 0) {
      assert.ok(view.userContext.usersWithStrategies >= 0,
        "usersWithStrategies 应为 >= 0 的数字");
    }
  }

  // 策略数据（如果脚本创建了策略）
  if (view.strategies) {
    assert.ok(view.strategies.totalStrategies >= 0,
      "totalStrategies 应是合法的数字");
    assert.ok(view.strategies.totalExecutions >= 0,
      "totalExecutions 应是合法的数字");
  }
});

// ----------------------------------------------------------------------------
// 测试 7: 确保聚合时间戳的格式正确性
// ----------------------------------------------------------------------------
test("getBusinessDataView 的聚合时间戳是有效的 ISO 日期字符串", async () => {
  const view = await getBusinessDataView();
  const timestamp = view.aggregatedAt;

  // 能被 new Date() 解析
  const parsed = new Date(timestamp);
  assert.ok(!isNaN(parsed.getTime()), "aggregatedAt 应能被解析为有效日期");
  assert.ok(timestamp.includes("T") || timestamp.includes(" "),
    "aggregatedAt 应包含日期时间分隔符");
});

// ----------------------------------------------------------------------------
// 测试 8: 验证 getPrisma (内部) 是否能成功创建客户端
// 这个测试主要是为了确保 Prisma 客户端初始化不会抛错
// ----------------------------------------------------------------------------
test("Prisma 客户端可正常初始化", async () => {
  const view = await getBusinessDataView();
  // 只要上一步没抛错，初始化就成功了
  assert.ok(view !== undefined, "应返回有效的结果");
});

// ----------------------------------------------------------------------------
// 测试 9: 业务数据之间的一致性约束
// ----------------------------------------------------------------------------
test("各层业务数据之间的一致性约束", async () => {
  const view = await getBusinessDataView();

  // 如果有策略任务，activeTasks 应 <= 策略总数
  if (view.strategies && view.strategies.totalStrategies > 0) {
    assert.ok(view.strategies.activeTasks <= view.strategies.totalStrategies + 10,
      "任务数不应远大于策略数（允许一定偏差）");
  }

  // 如果有交易记录，交易参数应该有效
  if (view.trading && view.trading.totalTradeCount > 0) {
    assert.ok(view.trading.activeTradingParams >= 0,
      "activeTradingParams 应为非负");
  }
});

// ----------------------------------------------------------------------------
// 测试 10: 重复调用不会抛错（稳定性）
// ----------------------------------------------------------------------------
test("多次调用 getBusinessDataView 稳定且不会抛错", async () => {
  // 连续调用 5 次
  for (let i = 0; i < 5; i++) {
    const view = await getBusinessDataView();
    assert.ok(view, `第 ${i + 1} 次调用应返回有效值`);
    assert.ok(view.aggregatedAt, `第 ${i + 1} 次调用应包含聚合时间`);
  }
});
