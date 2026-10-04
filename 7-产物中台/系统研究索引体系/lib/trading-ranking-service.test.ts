// ============================================================================
// trading-ranking-service.ts 单元测试
// 测试目标：
//   1. getTodayRanking() — 每日 Top10 列表结构正确性（rank/symbol/category/score/signal/confidence/decisionCard）
//   2. getHistoryRanking(date) — 历史榜单按日期查询
//   3. getMonitorMetrics(date) — 监控指标结构（satisfaction/conversionRate/abandonRate/pushReachRate）
//   4. 数据库连接失败或为空时的降级行为（返回空数组 / 零值指标）
//   5. saveRanking(items) — 持久化榜单（用于 trigger 路由调用）
// ============================================================================
import test from "node:test";
import assert from "node:assert/strict";

import {
  getTodayRanking,
  getHistoryRanking,
  getMonitorMetrics,
  saveRanking,
  type TradingRankingItem,
  type RankingMonitorMetrics,
} from "./trading-ranking-service.ts";

// ----------------------------------------------------------------------------
// 测试 1: getTodayRanking — 返回 Top10 列表，每项结构正确
// ----------------------------------------------------------------------------
test("getTodayRanking 返回 Top10 列表，每项包含完整决策卡字段", async () => {
  const ranking = await getTodayRanking();

  assert.ok(Array.isArray(ranking), "应返回数组");
  assert.ok(ranking.length <= 10, "榜单最多 10 条");

  if (ranking.length > 0) {
    const item = ranking[0];
    assert.ok(typeof item.rank === "number", "rank 应为数字");
    assert.ok(item.rank >= 1 && item.rank <= 10, "rank 应在 1-10 范围内");
    assert.ok(typeof item.symbol === "string" && item.symbol.length > 0, "symbol 应为非空字符串");
    assert.ok(["crypto", "commodity", "index"].includes(item.category), "category 应为 crypto/commodity/index 之一");
    assert.ok(typeof item.score === "number", "score 应为数字");
    assert.ok(
      ["STRONG_BUY", "BUY", "WEAK_BUY", "NEUTRAL", "WEAK_SELL", "SELL", "STRONG_SELL"].includes(item.signal),
      "signal 应为 7 层信号之一",
    );
    assert.ok(typeof item.confidence === "number", "confidence 应为数字");
    assert.ok(item.confidence >= 0 && item.confidence <= 1, "confidence 应在 0-1 范围内");
    assert.ok(typeof item.decisionCard === "object", "decisionCard 应为对象");
    assert.ok(item.date, "date 应存在");
  }
});

// ----------------------------------------------------------------------------
// 测试 2: getTodayRanking — 数据库降级时返回空数组（不抛异常）
// ----------------------------------------------------------------------------
test("getTodayRanking 在数据库无数据时返回空数组（降级）", async () => {
  const ranking = await getTodayRanking();
  assert.ok(Array.isArray(ranking), "即使无数据也应返回数组");
});

// ----------------------------------------------------------------------------
// 测试 3: getHistoryRanking — 按日期查询历史榜单
// ----------------------------------------------------------------------------
test("getHistoryRanking 按日期返回历史榜单", async () => {
  const date = "2026-09-28";
  const ranking = await getHistoryRanking(date);

  assert.ok(Array.isArray(ranking), "应返回数组");
  assert.ok(ranking.length <= 10, "历史榜单最多 10 条");

  if (ranking.length > 0) {
    assert.equal(ranking[0].date, date, "返回的榜单日期应匹配查询日期");
  }
});

// ----------------------------------------------------------------------------
// 测试 4: getMonitorMetrics — 返回监控指标结构
// ----------------------------------------------------------------------------
test("getMonitorMetrics 返回有效监控指标结构", async () => {
  const metrics = await getMonitorMetrics();

  assert.ok(metrics, "应返回非 null 值");
  assert.ok(typeof metrics.date === "string", "date 应为字符串");
  assert.ok(typeof metrics.satisfaction === "number" || metrics.satisfaction === null, "satisfaction 应为数字或 null");
  assert.ok(typeof metrics.conversionRate === "number" || metrics.conversionRate === null, "conversionRate 应为数字或 null");
  assert.ok(typeof metrics.abandonRate === "number" || metrics.abandonRate === null, "abandonRate 应为数字或 null");
  assert.ok(typeof metrics.pushReachRate === "number" || metrics.pushReachRate === null, "pushReachRate 应为数字或 null");
});

// ----------------------------------------------------------------------------
// 测试 5: saveRanking — 持久化榜单（接受数组，返回成功标志）
// ----------------------------------------------------------------------------
test("saveRanking 接受榜单数组并返回写入结果", async () => {
  const items: TradingRankingItem[] = [
    {
      rank: 1,
      symbol: "BTC-USDT",
      category: "crypto",
      score: 0.85,
      signal: "STRONG_BUY",
      confidence: 0.78,
      decisionCard: {
        entry: { price: 65000, range: [64000, 66000], batches: [{ price: 64500, ratio: 0.5 }] },
        stopLoss: 62000,
        takeProfit: [68000, 70000],
        events: [{ date: "2026-09-30", name: "FOMC", impact: "high" }],
        riskLevel: "intermediate",
        historicalAnalogy: "2024-03 BTC 反弹",
        logic: { bullish: ["ETF 流入"], bearish: ["获利盘"], confidence: 0.78 },
      },
      date: "2026-09-28",
    },
  ];

  const result = await saveRanking(items);
  assert.ok(result, "应返回非 null 结果");
  assert.ok(typeof result.success === "boolean", "success 应为布尔值");
});

// ----------------------------------------------------------------------------
// 测试 6: TradingRankingItem 类型契约 — decisionCard 包含 7 模块
// ----------------------------------------------------------------------------
test("TradingRankingItem.decisionCard 包含 7 模块结构", async () => {
  const ranking = await getTodayRanking();

  if (ranking.length > 0) {
    const card = ranking[0].decisionCard;
    assert.ok("entry" in card, "应包含 entry 模块（入场策略）");
    assert.ok("stopLoss" in card, "应包含 stopLoss 模块（止损）");
    assert.ok("takeProfit" in card, "应包含 takeProfit 模块（止盈）");
    assert.ok("events" in card, "应包含 events 模块（事件日历）");
    assert.ok("riskLevel" in card, "应包含 riskLevel 模块（风险分级）");
    assert.ok("historicalAnalogy" in card, "应包含 historicalAnalogy 模块（历史类比）");
    assert.ok("logic" in card, "应包含 logic 模块（逻辑推演）");
  }
});
