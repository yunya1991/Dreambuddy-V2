import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";

// Dev mock: 与列表 API 的 MOCK_PROPOSALS id 对应
const MOCK_DETAIL: Record<string, any> = {
  "mock-btc-trend": {
    id: "mock-btc-trend",
    title: "BTC 趋势跟踪策略 — 4H EMA 排列确认",
    status: "APPROVED",
    type: "TREND",
    direction: "LONG",
    symbol: "BTC/USDT",
    confidence: 0.82,
    edgeScore: 1.35,
    description: "4H 周期 EMA7/EMA25/EMA99 多头排列,价格回踩 EMA25 获支撑,RSI 55 健康区间,MACD 金叉延续。趋势强度评分 8.2/10,建议顺势做多。",
    rawInput: '{"tf":"4h","indicators":{"ema7":67500,"ema25":66800,"ema99":64200,"rsi":55,"macd":"golden_cross"},"regime":"trending_up"}',
    source: "AI_SKILL",
    regime: "trending_up",
    stopLoss: 65800,
    takeProfit: 71200,
    leverage: 3,
    positionSize: 0.15,
    createdAt: new Date(Date.now() - 86400000 * 2).toISOString(),
    tasks: [
      { id: "task-btc-1", name: "BTC 4H 趋势确认", status: "completed", totalTrades: 12 },
      { id: "task-btc-2", name: "BTC 仓位管理", status: "running", totalTrades: null },
    ],
  },
  "mock-eth-meanrev": {
    id: "mock-eth-meanrev",
    title: "ETH 均值回归策略 — RSI 超卖反弹",
    status: "EXECUTING",
    type: "MEAN_REVERSION",
    direction: "LONG",
    symbol: "ETH/USDT",
    confidence: 0.71,
    edgeScore: 0.92,
    description: "ETH 1H RSI 触及 28 超卖区,价格偏离布林带下轨,历史超卖后 24h 反弹概率 73%。轻仓做多,止损布林下轨外。",
    rawInput: '{"tf":"1h","rsi":28,"bollinger":"lower_touch","reversal_prob":0.73}',
    source: "AI_SKILL",
    regime: "range_bound",
    stopLoss: 2480,
    takeProfit: 2620,
    leverage: 2,
    positionSize: 0.1,
    createdAt: new Date(Date.now() - 86400000).toISOString(),
    tasks: [
      { id: "task-eth-1", name: "ETH 1H RSI 监控", status: "running", totalTrades: 5 },
    ],
  },
  "mock-sol-breakout": {
    id: "mock-sol-breakout",
    title: "SOL 突破策略 — 区间上沿放量",
    status: "DRAFT",
    type: "BREAKOUT",
    direction: "LONG",
    symbol: "SOL/USDT",
    confidence: 0.58,
    edgeScore: 0.45,
    description: "SOL 在 145-160 区间震荡 6 天,今日成交量放大 2.3 倍,价格测试上沿 160。若放量突破 160 则跟进做多。",
    rawInput: '{"range":{"low":145,"high":160},"volume_ratio":2.3,"breakout_level":160}',
    source: "RULE_BASED",
    regime: "range_bound",
    stopLoss: 153,
    takeProfit: 175,
    leverage: 3,
    positionSize: 0.12,
    createdAt: new Date().toISOString(),
    tasks: [],
  },
};

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  try {
    const s = await prisma.strategy.findUnique({
      where: { id },
      include: { tasks: { select: { id:true, status:true, tradeCount:true, lastExecutionAt:true, nextExecutionAt:true } } },
    });
    if (s) {
      return NextResponse.json({ success:true, data: {
        ...s,
        title: s.name,
        createdAt: s.createdAt.toISOString(),
        tasks: s.tasks,
      } });
    }
    // 数据库查不到时返回 mock(开发模式)
    if (MOCK_DETAIL[id]) {
      return NextResponse.json({ success: true, data: MOCK_DETAIL[id] });
    }
    return NextResponse.json({ success:false, error:"not_found" }, {status:404});
  } catch(err) {
    // DB 异常时返回 mock
    if (MOCK_DETAIL[id]) {
      return NextResponse.json({ success: true, data: MOCK_DETAIL[id] });
    }
    return NextResponse.json({ success:false, error: err instanceof Error?err.message:"db_error" }, {status:500});
  }
}
