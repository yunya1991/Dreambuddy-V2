// ============================================================================
// 推荐策略引擎: 基线策略配置
// ============================================================================
// 提供 v9 / v15 基线策略的标准参数，供回测引擎使用
// v9 = 原始经验策略（马丁 + 连涨跌 + MEC）
// v15 = 最终基线策略（斐波那契 + 布林带 + 马丁）
// ============================================================================

export type BaselineVersion = "v9" | "v15";

// ----------------------------------------------------------------------------
// v9 基线策略（原始经验策略）
// ----------------------------------------------------------------------------

export interface V9BaselineParams {
  id: "baseline-v9";
  version: string;
  name: "V9 原始经验策略";
  description: string;

  // 入场条件
  entryConditions: {
    long: string;   // "连续跌≥4日 + MEC≥2"
    short: string;  // "连续涨≥3日 + MEC≥2"
  };

  // MEC 三维评分
  mecDimensions: string[];

  // 马丁策略参数
  martingale: {
    addonGapPct: number;    // BTC 加仓间隔 %
    takeProfitPct: number;  // BTC 止盈 %
    maxLevels: number;      // 最大加仓层数
    stopLossMult: number;   // Level3加满后均价止损倍数
  };

  // 历史回测参考（长周期 2023-2026，BTC $200）
  referencePerformance: {
    period: string;
    btc: { returnPct: number; maxDD: number; sharpe: number };
    solBull: { returnPct: number; maxDD: number; sharpe: number };
    solLong: { returnPct: number; maxDD: number; sharpe: number };
    ethLong: { returnPct: number; maxDD: number; sharpe: number };
  };

  // 升版门槛（对比基准）
  upgradeThresholds: {
    minBetterIndicators: 2; // 每标的至少 2 项不劣于基线
    sharpeTolerance: number;
    maxDDTolerance: number;  // 正数 = 允许更差
    returnTolerance: number;
  };
}

export const V9_BASELINE: V9BaselineParams = {
  id: "baseline-v9",
  version: "v9.0",
  name: "V9 原始经验策略",
  description: "马丁策略 + 经验法则（涨三不追/跌四不压 + MEC动能衰竭评分）",

  entryConditions: {
    long: "连续跌≥4日 + MEC≥2 → LONG 马丁",
    short: "连续涨≥3日 + MEC≥2 → SHORT 马丁",
  },

  mecDimensions: [
    "动量衰减 — 价格是否出现连续涨/跌势能减弱",
    "量能背离 — 涨/跌时成交量是否配合不足",
    "势能接近关键MA — 是否接近 SMA30/65/128/200 重要均线",
  ],

  martingale: {
    addonGapPct: 8,      // 每跌 8%×vol_mult 加仓一次
    takeProfitPct: 4,   // 均价 + 4%×vol_mult 止盈
    maxLevels: 3,       // Level3 加满后启用均价止损
    stopLossMult: 1.20, // 均价 × 1.20 止损（SHORT反之）
  },

  referencePerformance: {
    period: "2023-2026 (BTC 长周期)",
    btc: { returnPct: 23.80, maxDD: 4.62, sharpe: 0.670 },
    solBull: { returnPct: 9.22, maxDD: 4.32, sharpe: 1.500 },
    solLong: { returnPct: 44.55, maxDD: 5.80, sharpe: 0.940 },
    ethLong: { returnPct: 4.99, maxDD: 11.94, sharpe: -0.120 },
  },

  upgradeThresholds: {
    minBetterIndicators: 2,
    sharpeTolerance: -0.05,
    maxDDTolerance: 0.5,  // 允许回撤多 0.5%
    returnTolerance: -1.0,
  },
};

// ----------------------------------------------------------------------------
// v15 基线策略（最终基线策略，更优的对照）
// ----------------------------------------------------------------------------

export interface V15BaselineParams {
  id: "baseline-v15";
  version: string;
  name: "V15 最终基线策略";
  description: string;

  // 入场条件
  entryConditions: {
    aboveAll: string; // "BTC全线上方 → Fib回调38.2-61.8% + RSI<55 → LONG马丁"
    belowAll: string; // "BTC全线下方 → Fib反弹38.2-61.8% + RSI>45 → SHORT马丁"
    inZone: string;   // "震荡区 → BB下轨+RSI<35 → LONG单层; BB上轨+RSI>65 → SHORT单层"
  };

  // 均线周期
  maPeriods: number[];

  // 马丁策略参数（按区域分级）
  martingale: {
    aboveBelow: {
      fibZone: [number, number];      // 黄金区 50-61.8%, 浅区 38.2-50%
      sizeMultGold: number;            // 黄金区仓位倍数
      sizeMultShallow: number;         // 浅区仓位倍数
      addonGapPct: number;
      takeProfitPct: number;
    };
    inZone: {
      sizeMult: number;               // 单层仓位（无马丁）
    };
  };

  // 历史回测参考（长周期 2023-2026，BTC $200）
  referencePerformance: {
    period: string;
    btc: { returnPct: number; maxDD: number; sharpe: number };
    solBull: { returnPct: number; maxDD: number; sharpe: number };
    solLong: { returnPct: number; maxDD: number; sharpe: number };
    ethLong: { returnPct: number; maxDD: number; sharpe: number };
  };

  upgradeThresholds: {
    minBetterIndicators: 2;
    sharpeTolerance: number;
    maxDDTolerance: number;
    returnTolerance: number;
  };
}

export const V15_BASELINE: V15BaselineParams = {
  id: "baseline-v15",
  version: "v15.0",
  name: "V15 最终基线策略",
  description: "马丁策略 + 斐波那契入场 + 布林带均值回归",

  entryConditions: {
    aboveAll: "Fib回调 38.2%-61.8% + RSI<55 → LONG 马丁",
    belowAll: "Fib反弹 38.2%-61.8% + RSI>45 → SHORT 马丁",
    inZone: "BB下轨+RSI<35 → LONG单层; BB上轨+RSI>65 → SHORT单层",
  },

  maPeriods: [30, 65, 128, 200],

  martingale: {
    aboveBelow: {
      fibZone: [38.2, 61.8],
      sizeMultGold: 1.0,      // 黄金区 50-61.8% 满仓
      sizeMultShallow: 0.5,   // 浅区 38.2-50% 半仓
      addonGapPct: 8,
      takeProfitPct: 4,
    },
    inZone: {
      sizeMult: 0.5,          // 单层，不加仓
    },
  },

  referencePerformance: {
    period: "2023-2026 (BTC 长周期)",
    btc: { returnPct: 23.80, maxDD: 4.62, sharpe: 0.670 },
    solBull: { returnPct: 9.22, maxDD: 4.32, sharpe: 1.500 },
    solLong: { returnPct: 44.55, maxDD: 5.80, sharpe: 0.940 },
    ethLong: { returnPct: 4.99, maxDD: 11.94, sharpe: -0.120 },
  },

  upgradeThresholds: {
    minBetterIndicators: 2,
    sharpeTolerance: -0.05,
    maxDDTolerance: 0.5,
    returnTolerance: -1.0,
  },
};

// ----------------------------------------------------------------------------
// 基线对比判定逻辑
// ----------------------------------------------------------------------------

export interface BaselineComparisonResult {
  isBetter: boolean;
  betterCount: number;  // 优于基线的指标数量
  sharpeBetter: boolean;
  ddBetter: boolean;    // 回撤更小
  returnBetter: boolean;

  // 差值（正数表示策略优于基线）
  sharpeDiff: number;
  ddDiff: number;      // 负数表示回撤减少
  returnDiff: number;

  // 基线参考值
  baselineSharpe: number;
  baselineMaxDD: number;
  baselineReturn: number;
}

/**
 * 对比策略性能与基线，返回对比结果
 */
export function compareWithBaseline(
  strategy: {
    sharpeRatio: number;
    maxDrawdown: number; // 回撤（正数表示回撤）
    totalReturn: number;
  },
  baselineVersion: BaselineVersion,
  thresholds?: { sharpeTolerance?: number; maxDDTolerance?: number; returnTolerance?: number }
): BaselineComparisonResult {
  const baseline = baselineVersion === "v15" ? V15_BASELINE : V9_BASELINE;
  const ref = baseline.referencePerformance.btc;

  const t = thresholds || {
    sharpeTolerance: baseline.upgradeThresholds.sharpeTolerance,
    maxDDTolerance: baseline.upgradeThresholds.maxDDTolerance,
    returnTolerance: baseline.upgradeThresholds.returnTolerance,
  };

  const sharpeBetter = strategy.sharpeRatio >= ref.sharpe + (t.sharpeTolerance ?? 0);
  const ddBetter = strategy.maxDrawdown <= ref.maxDD + (t.maxDDTolerance ?? 0); // 回撤越小越好
  const returnBetter = strategy.totalReturn >= ref.returnPct + (t.returnTolerance ?? 0);

  const betterCount = [sharpeBetter, ddBetter, returnBetter].filter(Boolean).length;
  const isBetter = betterCount >= baseline.upgradeThresholds.minBetterIndicators;

  return {
    isBetter,
    betterCount,
    sharpeBetter,
    ddBetter,
    returnBetter,
    sharpeDiff: strategy.sharpeRatio - ref.sharpe,
    ddDiff: ref.maxDD - strategy.maxDrawdown, // 正数表示回撤减少
    returnDiff: strategy.totalReturn - ref.returnPct,
    baselineSharpe: ref.sharpe,
    baselineMaxDD: ref.maxDD,
    baselineReturn: ref.returnPct,
  };
}

/**
 * 获取指定版本的基线策略配置
 */
export function getBaseline(version: BaselineVersion): V9BaselineParams | V15BaselineParams {
  return version === "v15" ? V15_BASELINE : V9_BASELINE;
}

/**
 * 获取两个版本的基线配置
 */
export function getAllBaselines(): { v9: V9BaselineParams; v15: V15BaselineParams } {
  return { v9: V9_BASELINE, v15: V15_BASELINE };
}
