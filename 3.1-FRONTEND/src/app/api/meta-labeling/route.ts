import { NextResponse } from "next/server";

/**
 * F6: Meta-Labeling API 端点
 *
 * L1 信号 → L2 盈利概率判断 → 执行/观望/跳过决策矩阵
 *
 * 当前实现：从 page.tsx 提取的简化 L2 模型（基于信号置信度 + 源历史胜率）
 * 后续接入：11-易经推理系统/scripts/memory_l4/bcrm2/meta_labeling_features_v2.py
 *          （5 大类 25 个 L2 特征：时间维度/宏观环境/信号稀有度/市场结构/跨资产验证）
 *
 * GET /api/meta-labeling                  返回所有 L1 信号的 L2 决策结果
 * GET /api/meta-labeling?decision=execute 只返回执行类信号
 */

interface L1Signal {
  source: string;
  name: string;
  direction: "long" | "short" | "neutral";
  confidence: number;
}

interface MetaLabelResult {
  signal: L1Signal;
  winProbability: number; // L2 盈利概率 0-1
  expectedValue: number; // 期望值
  decision: "execute" | "observe" | "skip";
  sizeMultiplier: number; // 仓位倍数
}

// 模拟 L1 信号 (实际应由 subagent signals 聚合)
const MOCK_SIGNALS: L1Signal[] = [
  { source: "technical", name: "EMA排列", direction: "long", confidence: 0.72 },
  { source: "technical", name: "RSI14", direction: "neutral", confidence: 0.45 },
  { source: "sentiment", name: "FGI", direction: "long", confidence: 0.6 },
  { source: "macro", name: "利率预期", direction: "short", confidence: 0.65 },
  { source: "risk", name: "VaR95", direction: "short", confidence: 0.55 },
  { source: "portfolio", name: "漂移度", direction: "neutral", confidence: 0.4 },
];

// L2 Meta-Labeling 模型 (简化版: 基于信号置信度 + 源历史胜率)
// TODO: 接入 meta_labeling_features_v2.py 的 5 大类 25 个 L2 特征
const SOURCE_WIN_RATE: Record<string, number> = {
  technical: 0.58,
  sentiment: 0.52,
  macro: 0.61,
  flow: 0.55,
  valuation: 0.56,
  onchain: 0.54,
  risk: 0.63,
  portfolio: 0.5,
};

function computeMetaLabel(signal: L1Signal): MetaLabelResult {
  const baseWinRate = SOURCE_WIN_RATE[signal.source] ?? 0.5;
  // L2 胜率 = 基础胜率 * 置信度调整因子
  const confAdjust = 0.7 + 0.6 * signal.confidence; // 0.7 ~ 1.3
  const winProb = Math.min(0.95, baseWinRate * confAdjust);

  // 期望值 = 胜率 * 平均盈利 - (1-胜率) * 平均亏损 (假设 盈亏比 1.5)
  const avgWin = 0.03;
  const avgLoss = 0.02;
  const ev = winProb * avgWin - (1 - winProb) * avgLoss;

  // 决策
  let decision: MetaLabelResult["decision"];
  let sizeMultiplier: number;
  if (signal.direction === "neutral") {
    decision = "skip";
    sizeMultiplier = 0;
  } else if (winProb >= 0.6 && ev > 0) {
    decision = "execute";
    sizeMultiplier = winProb >= 0.7 ? 1.5 : 1.0;
  } else if (winProb >= 0.52) {
    decision = "observe";
    sizeMultiplier = 0.5;
  } else {
    decision = "skip";
    sizeMultiplier = 0;
  }

  return { signal, winProbability: winProb, expectedValue: ev, decision, sizeMultiplier };
}

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const decisionFilter = searchParams.get("decision") as MetaLabelResult["decision"] | null;

  const results = MOCK_SIGNALS.map(computeMetaLabel);
  const filtered = decisionFilter ? results.filter((r) => r.decision === decisionFilter) : results;

  return NextResponse.json({
    success: true,
    results: filtered,
    total: filtered.length,
    source: "mock-l2", // 标识当前数据源为简化 L2 模型，后续接入真实后端后改为 'bcrm2-v2'
    timestamp: new Date().toISOString(),
  });
}
