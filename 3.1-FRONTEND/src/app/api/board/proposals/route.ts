import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";

// Dev mock: 数据库为空时返回示例提案,保证开发模式可见
// P1: status 对齐 Prisma 枚举 (EXECUTING→APPLIED), 加 dataSource:'mock' 标记
const MOCK_PROPOSALS = [
  {
    id: "mock-btc-trend",
    title: "BTC 趋势跟踪策略 — 4H EMA 排列确认",
    status: "APPROVED",
    type: "TREND",
    direction: "LONG",
    symbol: "BTC/USDT",
    confidence: 0.82,
    edgeScore: 1.35,
    regime: "trending_up",
    createdAt: new Date(Date.now() - 86400000 * 2).toISOString(),
  },
  {
    id: "mock-eth-meanrev",
    title: "ETH 均值回归策略 — RSI 超卖反弹",
    status: "APPLIED",
    type: "MEAN_REVERSION",
    direction: "LONG",
    symbol: "ETH/USDT",
    confidence: 0.71,
    edgeScore: 0.92,
    regime: "range_bound",
    createdAt: new Date(Date.now() - 86400000).toISOString(),
  },
  {
    id: "mock-sol-breakout",
    title: "SOL 突破策略 — 区间上沿放量",
    status: "DRAFT",
    type: "BREAKOUT",
    direction: "LONG",
    symbol: "SOL/USDT",
    confidence: 0.58,
    edgeScore: 0.45,
    regime: "range_bound",
    createdAt: new Date().toISOString(),
  },
];

export async function GET() {
  try {
    const strategies = await prisma.strategy.findMany({
      select: { id:true, name:true, status:true, type:true, direction:true, symbol:true,
               confidence:true, edgeScore:true, regime:true, createdAt:true },
      orderBy: { createdAt: "desc" }, take: 100,
    });

    // P1: dataSource 嵌入每个 Proposal 对象内 (不放信封顶层 sibling, 因 api-client 解构丢弃)
    const list = strategies.length > 0
      ? strategies.map(s => ({
          id: s.id, title: s.name, status: s.status, type: s.type || "CUSTOM",
          department: "strategy", direction: s.direction, symbol: s.symbol,
          confidence: s.confidence, edgeScore: s.edgeScore,
          createdAt: s.createdAt.toISOString(),
          dataSource: 'db' as const,
        }))
      : MOCK_PROPOSALS.map(p => ({ ...p, dataSource: 'mock' as const }));

    return NextResponse.json({ success: true, data: list });
  } catch (err) {
    // DB 异常时也返回 mock,保证页面可用
    return NextResponse.json({
      success: true,
      data: MOCK_PROPOSALS.map(p => ({ ...p, dataSource: 'mock' as const })),
    });
  }
}
