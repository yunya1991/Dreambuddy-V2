// ============================================================================
// 交易榜单: 手动触发生成 API
// ============================================================================
// POST /api/trading-ranking/trigger
// 1. spawn python3 coin_fundamental_ranker.py → 输出 JSON 基本面信号
// 2. 解析 JSON → 映射 TradingRankingItem + DecisionCard 7 模块
// 3. saveRanking() 写入 Prisma SQLite
// 4. getRealtimeHub().publish('trading-ranking', ...) 推送实时事件
// ============================================================================

import { NextRequest, NextResponse } from "next/server";
import { spawn } from "child_process";
import path from "path";
import os from "os";
import { saveRanking, type TradingRankingItem, type DecisionCard } from "@/lib/trading-ranking-service";
import { getRealtimeHub } from "@/lib/realtime-hub";

export const dynamic = "force-dynamic";

// Python 评分脚本路径
function getRankerScriptPath(): string {
  return path.join(
    os.homedir(),
    "WorkBuddy",
    "dreambuddy-v2",
    "11-易经推理系统",
    "scripts",
    "memory_l4",
    "force_vector",
    "coin_fundamental_ranker.py",
  );
}

// ============================================================================
// 类型定义 — Python 脚本输出的信号格式
// ============================================================================

interface KlineData {
  inst_id: string;
  price: number;
  atr: number;
  high: number;
  low: number;
  candle_count: number;
}

interface PythonSignal {
  coin: string;
  asset_class: string; // crypto_usdt / us_stock / precious_metal
  fundamental_score: number; // [-1.0, +1.0]
  rank: string; // S / A / B / C
  sub_signals: Record<string, number>;
  data_quality: string; // sufficient / partial / insufficient
  confidence: number; // [0.0, 1.0]
  timestamp: string;
  error: string | null;
  current_phase: string;
  phase_confidence: number;
  phase_switch_triggers: string[];
  phase_strategy_hint: Record<string, unknown>;
  current_price: number; // 实时市场价（USD），0 表示不可用
  atr: number; // 14 日 ATR（USD），0 表示不可用
  kline_data?: KlineData | null;
}

// ============================================================================
// 映射函数
// ============================================================================

/** asset_class → category */
function mapCategory(assetClass: string): TradingRankingItem["category"] {
  switch (assetClass) {
    case "crypto_usdt":
      return "crypto";
    case "us_stock":
      return "index";
    case "precious_metal":
      return "commodity";
    default:
      return "crypto";
  }
}

/** rank + score → signal */
function mapSignal(rank: string, score: number): TradingRankingItem["signal"] {
  switch (rank) {
    case "S":
      return "STRONG_BUY";
    case "A":
      return "BUY";
    case "C":
      return score <= -0.5 ? "STRONG_SELL" : "SELL";
    case "B":
    default:
      if (score > 0.1) return "WEAK_BUY";
      if (score < -0.1) return "WEAK_SELL";
      return "NEUTRAL";
  }
}

/** rank → riskLevel */
function mapRiskLevel(rank: string): DecisionCard["riskLevel"] {
  switch (rank) {
    case "S":
    case "A":
      return "expert";
    case "B":
      return "intermediate";
    case "C":
    default:
      return "novice";
  }
}

/** 从 sub_signals 提取看多/看空逻辑 */
function buildLogic(
  subSignals: Record<string, number>,
  confidence: number,
  phaseHint: Record<string, unknown>,
): DecisionCard["logic"] {
  const bullish: string[] = [];
  const bearish: string[] = [];

  for (const [name, val] of Object.entries(subSignals)) {
    if (val > 0.3) {
      bullish.push(`${name}: +${val.toFixed(2)}`);
    } else if (val < -0.3) {
      bearish.push(`${name}: ${val.toFixed(2)}`);
    }
  }

  // 从 phase_strategy_hint 补充逻辑
  const hintSummary = phaseHint?.summary ?? phaseHint?.description;
  if (typeof hintSummary === "string" && hintSummary.length > 0) {
    bullish.push(`阶段策略: ${hintSummary.slice(0, 80)}`);
  }

  return {
    bullish: bullish.length > 0 ? bullish : ["综合评分偏多"],
    bearish: bearish.length > 0 ? bearish : ["暂无明显看空信号"],
    confidence,
  };
}

/** 从 phase_switch_triggers 构建事件日历 */
function buildEvents(
  triggers: string[],
  timestamp: string,
): DecisionCard["events"] {
  if (!triggers || triggers.length === 0) {
    return [{
      date: timestamp.slice(0, 10),
      name: "无重大事件",
      impact: "中性",
    }];
  }
  return triggers.slice(0, 5).map((t, i) => ({
    date: timestamp.slice(0, 10),
    name: t,
    impact: i === 0 ? "高" : "中",
  }));
}

/** 生成 DecisionCard — 使用真实市场价 + ATR 计算入场/止损/止盈 */
function buildDecisionCard(signal: PythonSignal): DecisionCard {
  const score = signal.fundamental_score;
  const realPrice = signal.current_price ?? 0;
  const realAtr = signal.atr ?? 0;

  // 判断方向：买入信号用多头布局，卖出信号用空头布局
  const isBullish = score >= 0;

  // entry / stopLoss / takeProfit 计算
  let entryPrice: number;
  let stopLoss: number;
  let takeProfit: number[];
  let range: [number, number];
  let batches: { price: number; ratio: number }[];

  if (realPrice > 0) {
    // 真实市场价作为入场价
    entryPrice = +realPrice.toFixed(4);
    // ATR 优先用真实值，否则用价格的 3% 作为波动率代理
    const atr = realAtr > 0 ? realAtr : realPrice * 0.03;
    if (isBullish) {
      // 多头: 入场=当前价, 止损=price-2*ATR, 止盈=price+3*ATR, price+5*ATR
      range = [+(entryPrice - atr * 0.5).toFixed(4), +(entryPrice + atr * 0.5).toFixed(4)];
      batches = [
        { price: +entryPrice.toFixed(4), ratio: 0.5 },
        { price: +(entryPrice - atr * 0.3).toFixed(4), ratio: 0.3 },
        { price: +(entryPrice + atr * 0.2).toFixed(4), ratio: 0.2 },
      ];
      stopLoss = +(entryPrice - 2 * atr).toFixed(4);
      takeProfit = [
        +(entryPrice + 3 * atr).toFixed(4),
        +(entryPrice + 5 * atr).toFixed(4),
      ];
    } else {
      // 空头: 入场=当前价, 止损=price+2*ATR, 止盈=price-3*ATR, price-5*ATR
      range = [+(entryPrice - atr * 0.5).toFixed(4), +(entryPrice + atr * 0.5).toFixed(4)];
      batches = [
        { price: +entryPrice.toFixed(4), ratio: 0.5 },
        { price: +(entryPrice + atr * 0.3).toFixed(4), ratio: 0.3 },
        { price: +(entryPrice - atr * 0.2).toFixed(4), ratio: 0.2 },
      ];
      stopLoss = +(entryPrice + 2 * atr).toFixed(4);
      takeProfit = [
        +(entryPrice - 3 * atr).toFixed(4),
        +(entryPrice - 5 * atr).toFixed(4),
      ];
    }
  } else {
    // 真实价格不可用：标记为 0，前端展示"行情获取失败"
    entryPrice = 0;
    range = [0, 0];
    batches = [{ price: 0, ratio: 1.0 }];
    stopLoss = 0;
    takeProfit = [0, 0];
  }

  return {
    entry: {
      price: entryPrice,
      range,
      batches,
    },
    stopLoss,
    takeProfit,
    events: buildEvents(signal.phase_switch_triggers, signal.timestamp),
    riskLevel: mapRiskLevel(signal.rank),
    historicalAnalogy: signal.current_phase === "P1_EXPECTATION"
      ? "类比预期驱动阶段历史行情（P1）"
      : signal.current_phase === "P3_VALUATION_RECOVERY"
        ? "类比估值修复阶段历史行情（P3）"
        : "类比收入扩张阶段历史行情（P2）",
    logic: buildLogic(signal.sub_signals, signal.confidence, signal.phase_strategy_hint),
  };
}

/** PythonSignal → TradingRankingItem */
function mapToRankingItem(signal: PythonSignal, rank: number): TradingRankingItem {
  return {
    rank,
    symbol: signal.coin,
    category: mapCategory(signal.asset_class),
    score: signal.fundamental_score,
    signal: mapSignal(signal.rank, signal.fundamental_score),
    confidence: signal.confidence,
    decisionCard: buildDecisionCard(signal),
    date: signal.timestamp.slice(0, 10),
  };
}

/** 应用 6+2+2 品类配比约束 */
function applyCategoryConstraint(items: TradingRankingItem[]): TradingRankingItem[] {
  const crypto = items.filter(i => i.category === "crypto");
  const commodity = items.filter(i => i.category === "commodity");
  const index = items.filter(i => i.category === "index");

  const selected: TradingRankingItem[] = [];
  // 6 crypto
  selected.push(...crypto.slice(0, 6));
  // 2 commodity
  selected.push(...commodity.slice(0, 2));
  // 2 index
  selected.push(...index.slice(0, 2));

  // 不足 10 条时用剩余项补齐
  if (selected.length < 10) {
    const usedSymbols = new Set(selected.map(i => i.symbol));
    const remaining = items.filter(i => !usedSymbols.has(i.symbol));
    while (selected.length < 10 && remaining.length > 0) {
      selected.push(remaining.shift()!);
    }
  }

  // 重新排序并赋 rank
  selected.sort((a, b) => b.score - a.score);
  selected.forEach((item, idx) => {
    item.rank = idx + 1;
  });

  return selected.slice(0, 10);
}

// ============================================================================
// POST 处理
// ============================================================================

export async function POST(request: NextRequest) {
  try {
    const body = await request.json().catch(() => ({}));
    const force = body.force === true;

    const scriptPath = getRankerScriptPath();

    const fs = await import("node:fs");
    if (!fs.existsSync(scriptPath)) {
      return NextResponse.json(
        {
          success: false,
          error: `评分脚本不存在: ${scriptPath}`,
          hint: "请确保 coin_fundamental_ranker.py 位于正确路径",
        },
        { status: 404 },
      );
    }

    const runId = `ranking-${Date.now()}`;

    // 异步 fire-and-forget：脚本需约 30-60 秒（OKX 统一行情+并发获取），同步 await 会阻塞
    // 整个 3456 服务导致 today API 不可用。改为后台执行，立即返回 runId。
    void runRankerAsync(runId, scriptPath, force);

    return NextResponse.json({
      success: true,
      runId,
      message: "榜单生成任务已提交，约 1 分钟后完成。可调用 /api/trading-ranking/today 查询最新榜单。",
      status: "running",
    });
  } catch (error) {
    console.error("[trading-ranking/trigger]", error);
    return NextResponse.json(
      { success: false, error: "触发生成失败" },
      { status: 500 },
    );
  }
}

// ============================================================================
// 后台执行评分脚本（fire-and-forget，不阻塞 HTTP 响应）
// ============================================================================
async function runRankerAsync(runId: string, scriptPath: string, force: boolean) {
  try {
    const { spawn } = await import("node:child_process");

    const { stdout, stderr, exitCode } = await new Promise<{
      stdout: string;
      stderr: string;
      exitCode: number | null;
    }>((resolve) => {
      let output = "";
      let errorOutput = "";

      const args = [scriptPath];
      if (force) args.push("--force");

      const proc = spawn("python3", args, {
        env: { ...process.env, PYTHONUNBUFFERED: "1" },
      });

      proc.stdout.on("data", (data) => {
        output += data.toString();
      });

      proc.stderr.on("data", (data) => {
        errorOutput += data.toString();
      });

      proc.on("close", (code) => {
        resolve({ stdout: output, stderr: errorOutput, exitCode: code });
      });

      // 超时保护：15 分钟（榜单 4h 一次的低频任务，代码驱动不浪费 token）
      setTimeout(() => {
        proc.kill();
        resolve({
          stdout: output,
          stderr: errorOutput + "\n[timeout] 评分脚本执行超时（15分钟）",
          exitCode: -1,
        });
      }, 15 * 60 * 1000);
    });

    if (exitCode !== 0) {
      console.error(`[trigger ${runId}] 脚本失败 exit=${exitCode}`, stderr.slice(-500));
      return;
    }

    // 解析 JSON 输出
    let signals: PythonSignal[];
    try {
      signals = JSON.parse(stdout);
    } catch {
      console.error(`[trigger ${runId}] JSON 解析失败`, stdout.slice(-300));
      return;
    }

    if (!Array.isArray(signals) || signals.length === 0) {
      console.error(`[trigger ${runId}] 无有效信号`);
      return;
    }

    // 映射 + 品类配比约束
    const allItems = signals.map((s, idx) => mapToRankingItem(s, idx + 1));
    const top10 = applyCategoryConstraint(allItems);

    // 持久化到 DB
    const saveResult = await saveRanking(top10);

    // 推送实时事件
    try {
      const hub = getRealtimeHub();
      hub.publish("trading-ranking", {
        type: "ranking-updated",
        summary: `今日 Top10 榜单已生成：${top10.length} 条推荐，榜首 ${top10[0]?.symbol ?? "—"}`,
        detail: `评分脚本输出 ${signals.length} 条信号，配比约束后取 ${top10.length} 条。保存到 DB：${saveResult.success ? "成功" : "失败"}。`,
        requestId: runId,
        status: saveResult.success ? "completed" : "failed",
        data: {
          totalSignals: signals.length,
          savedCount: saveResult.count,
          topSymbol: top10[0]?.symbol,
          topScore: top10[0]?.score,
        },
      });
    } catch {
      // FAIL-OPEN
    }

    console.log(
      `[trigger ${runId}] 完成：signals=${signals.length} saved=${saveResult.count} ` +
        `dbSaved=${saveResult.success} top=${top10[0]?.symbol}(${top10[0]?.score})`,
    );
  } catch (err) {
    console.error(`[trigger ${runId}] 后台执行异常`, err);
  }
}
