/**
 * 三屏趋势数据映射层
 *
 * 将后端 8765 端口返回的原始数据映射到前端 store 的
 * Screen1Data / Screen2Data / Screen3Data 结构。
 */
import type {
  Screen1Data, Screen2Data, Screen3Data, PipelineStep,
} from '@/stores';
import type { TrendScreenData, V4WaveStrategyData, DataDrivenScreensData } from './three-screens-api';

// 方向字符串转换
function dirToAnchor(dir: string): 'bullish' | 'bearish' | 'neutral' {
  const d = (dir || '').toUpperCase();
  if (d === 'BULL' || d === 'LONG') return 'bullish';
  if (d === 'BEAR' || d === 'SHORT') return 'bearish';
  return 'neutral';
}

function dirLabel(dir: string): string {
  const d = (dir || '').toUpperCase();
  if (d === 'BULL' || d === 'LONG') return '看多';
  if (d === 'BEAR' || d === 'SHORT') return '看空';
  return '中性';
}

// 置信度转 score（0-100），带兜底
function scoreOf(value: number | undefined | null, fallback = 0): number {
  if (typeof value !== 'number' || !isFinite(value)) return fallback;
  return Math.max(0, Math.min(100, Math.round(value)));
}

// ============================================================
// Screen1 — 战略层（来源：/api/trend-screen）
// ============================================================

export function mapScreen1(trend: TrendScreenData, dataDriven?: DataDrivenScreensData | null): Screen1Data {
  const tc = trend.trend_consistency || {} as any;
  const weekly = tc.weekly || {};
  const daily = tc.daily || {};
  const bc = trend.bayesian_confidence || {};
  const ft = trend.technical_fundamental_fusion || {};
  const fs = trend.final_signal || {};
  const freq = trend.freqtrade_signals || {};

  // 七维评分：用后端实际数据填充
  const dimensions: Screen1Data['dimensions'] = {
    // 宏观 — 周线方向置信度（大周期方向）
    macro: {
      score: scoreOf(weekly.confidence),
      label: dirLabel(weekly.final_direction),
    },
    // 链上 — Freqtrade 4h 信号置信度（资金面投票）
    onchain: {
      score: scoreOf(freq['4h']?.confidence),
      label: freq['4h']?.signal || 'HOLD',
    },
    // 技术面 — 趋势一致性置信度（周线+日线综合）
    technical: {
      score: scoreOf(tc.consistency_confidence),
      label: tc.consistent ? '一致' : '分歧',
    },
    // 情绪 — Freqtrade 1h 信号置信度（短线情绪）
    sentiment: {
      score: scoreOf(freq['1h']?.confidence),
      label: freq['1h']?.signal || 'HOLD',
    },
    // 基本面 — 技术面/基本面融合的基本面置信度
    fundamental: {
      score: scoreOf(ft.fundamental?.confidence),
      label: dirLabel(ft.fundamental?.direction),
    },
    // 时机 — 日线逆转评分（逆转信号强度，越高越可能反转）
    timing: {
      score: scoreOf(daily.reversal_score),
      label: (daily.reversal_score ?? 0) > 50 ? '逆转' : '顺势',
    },
    // 风险 — 贝叶斯置信度（综合概率评估）
    risk: {
      score: scoreOf(bc.confidence),
      label: dirLabel(bc.direction),
    },
  };

  // 从 data-driven-screens 获取基本面维度数据
  const ddScreen1 = dataDriven?.screen1;
  const fundamentalDirection = ddScreen1 ? dirToAnchor(ddScreen1.fundamental_direction) : undefined;
  const fundamentalConfidence = ddScreen1 ? scoreOf(ddScreen1.fundamental_confidence) : undefined;
  const fundamentalDimensions = ddScreen1?.fundamental_dimensions;
  const fusionConsistent = ddScreen1?.fusion?.consistent;
  const fusionReason = ddScreen1?.fusion?.reason;

  // 优先使用 data-driven 的 debate（包含技术面+基本面融合分析）
  const debate = ddScreen1?.debate || fs.decision_reason || '';

  return {
    directionAnchor: dirToAnchor(fs.direction),
    dimensions,
    debate,
    updatedAt: Date.now(),
    fundamentalDirection,
    fundamentalConfidence,
    fundamentalDimensions,
    fusionConsistent,
    fusionReason,
  };
}

// ============================================================
// Screen2 — 战术层（来源：/api/v4-wave-strategy）
// ============================================================

// 策略线固定回测指标（9年回测验证）
const STRATEGY_LINE_BACKTEST = {
  winRate: 0.58,
  avgR: 1.3,
  maxDD: 0.4331,
  sharpe: 1.41,
};

export function mapScreen2(wave: V4WaveStrategyData, trend?: TrendScreenData, dataDriven?: DataDrivenScreensData | null): Screen2Data {
  const fd = wave.final_decision || {};
  const ws = wave.wave_strategy || {};
  const vs = wave.v4_strategy || {};
  const pa = wave.physics_assessment || {};

  // 方向约束
  const directionConstraint = dirToAnchor(fd.direction);

  // 预设策略：从 V4 + 波浪策略构建入场预设
  const currentPrice = wave.current_price || 0;
  const trailingStopPct = ws.wave_trailing_stop_pct || 0.06;
  const takeProfitPct = ws.wave_take_profit_pct || 0.15;
  const isLong = fd.direction === 'BULL' || fd.action === 'ENTER_LONG';

  const presets: Screen2Data['presets'] = [];

  // V4 主策略预设
  if (vs.action && vs.action !== 'WAIT') {
    presets.push({
      id: `v4-${wave.symbol}`,
      symbol: wave.symbol,
      entry: currentPrice,
      stop: isLong ? currentPrice * (1 - trailingStopPct) : currentPrice * (1 + trailingStopPct),
      target: isLong ? currentPrice * (1 + takeProfitPct) : currentPrice * (1 - takeProfitPct),
      timeframe: '1D',
      confidence: vs.position_pct || 0,
      takeProfitPct: takeProfitPct * 100,
      stopLossPct: trailingStopPct * 100,
    });
  }

  // 波浪策略预设（互斥融合）
  if (ws.enabled && ws.final_action && ws.final_action !== 'WAIT') {
    presets.push({
      id: `wave-${wave.symbol}`,
      symbol: wave.symbol,
      entry: currentPrice,
      stop: isLong ? currentPrice * (1 - trailingStopPct) : currentPrice * (1 + trailingStopPct),
      target: isLong ? currentPrice * (1 + takeProfitPct) : currentPrice * (1 - takeProfitPct),
      timeframe: '1D',
      confidence: ws.wave_confidence || 0,
      takeProfitPct: takeProfitPct * 100,
      stopLossPct: trailingStopPct * 100,
    });
  }

  // 从 data-driven-screens 补充预设策略
  const ddPresets = dataDriven?.screen2?.presets || [];
  for (const p of ddPresets) {
    if (!presets.find(x => x.id === p.id)) {
      presets.push({
        id: p.id,
        symbol: p.symbol,
        entry: p.entry,
        stop: p.stop,
        target: p.target,
        timeframe: p.timeframe,
        confidence: p.confidence,
        takeProfitPct: p.take_profit_pct,
        stopLossPct: p.stop_loss_pct,
      });
    }
  }

  // 贝叶斯优化信息（从物理置信度映射）
  const bayesianOpt = {
    iterations: pa.enabled ? 1 : 0,
    bestParams: {
      position_pct: fd.adjusted_position_pct || fd.position_pct || 0,
      physics_confidence: pa.physics_confidence || 0,
    } as Record<string, number>,
    improvement: pa.enabled ? (pa.physics_confidence - 0.5) : 0,
  };

  // 波动率和衍生品数据
  const ddScreen2 = dataDriven?.screen2;
  const volatility = ddScreen2?.volatility ? {
    avgSpeed: ddScreen2.volatility.avg_speed || 0,
    avgAcceleration: ddScreen2.volatility.avg_acceleration || 0,
    reversalScore: ddScreen2.volatility.reversal_score || 0,
    volMultiplier: ddScreen2.volatility.vol_multiplier || 1,
  } : undefined;

  const derivatives = ddScreen2?.derivatives ? {
    fundingRate: ddScreen2.derivatives.funding_rate || 0,
    fundingDirection: ddScreen2.derivatives.funding_direction || 'NEUTRAL',
    optionsOi: ddScreen2.derivatives.options_oi || 0,
  } : undefined;

  return {
    directionConstraint,
    presets,
    backtest: { ...STRATEGY_LINE_BACKTEST },
    bayesianOpt,
    volatility,
    derivatives,
    updatedAt: Date.now(),
  };
}

// ============================================================
// Screen3 — 执行层（来源：/api/v4-wave-strategy 的 position + final_decision）
// ============================================================

export function mapScreen3(wave: V4WaveStrategyData, trend?: TrendScreenData): Screen3Data {
  const fd = wave.final_decision || {};
  const pos = wave.position;
  const currentPrice = wave.current_price || 0;

  // 执行流水线步骤
  const action = fd.action || 'WAIT';
  const isEnter = action.startsWith('ENTER');
  const isWait = action === 'WAIT';

  const pipeline: PipelineStep[] = [
    {
      id: 'A7_GATE',
      name: 'A7 风控门禁',
      status: isEnter ? 'done' : isWait ? 'done' : 'pending',
      output: isEnter ? '通过' : '未触发',
    },
    {
      id: 'A4_VALIDATE',
      name: 'A4 方案验证',
      status: isEnter ? 'done' : 'pending',
      output: isEnter ? `方向=${fd.direction}` : undefined,
    },
    {
      id: 'C3_GATE',
      name: 'C3 门禁检查',
      status: isEnter ? 'done' : 'pending',
      output: isEnter ? `仓位=${(fd.adjusted_position_pct || 0).toFixed(4)}` : undefined,
    },
    {
      id: 'A5_ENTRY',
      name: 'A5 入场执行',
      status: pos ? 'done' : isEnter ? 'running' : 'pending',
      output: pos ? `持仓${pos.size}` : isEnter ? '待执行' : undefined,
    },
    {
      id: 'A6_MONITOR',
      name: 'A6 情报监控',
      status: pos ? 'running' : 'pending',
      output: pos ? '监控中' : undefined,
    },
    {
      id: 'A9_EXIT',
      name: 'A9 离场评估',
      status: pos ? 'running' : 'pending',
      output: pos ? '持仓中' : undefined,
    },
  ];

  // 持仓状态
  let positionState: Screen3Data['positionState'] = null;
  if (pos) {
    positionState = {
      symbol: pos.coin || wave.symbol,
      side: pos.side || 'LONG',
      size: pos.size || 0,
      entry: pos.entry_px || 0,
      current: currentPrice,
      pnl: pos.upnl || 0,
    };
  }

  // 监控告警
  const monitorAlerts: Screen3Data['monitorAlerts'] = [];
  const pa = wave.physics_assessment || {};
  const ws = wave.wave_strategy || {};

  if (pa.enabled && pa.weak_trend) {
    monitorAlerts.push({
      id: 'weak-trend',
      level: 'warning',
      message: `弱趋势(η=${pa.current_eta?.toFixed(4)})，物理置信度调节仓位`,
      timestamp: Date.now(),
    });
  }

  if (ws.wave_signal === 'WAIT' && isEnter) {
    monitorAlerts.push({
      id: 'wave-wait',
      level: 'info',
      message: `波浪信号 WAIT，以 V4 主策略为准（融合规则: ${fd.fusion_rule}）`,
      timestamp: Date.now(),
    });
  }

  if (!pos && isEnter) {
    monitorAlerts.push({
      id: 'pending-entry',
      level: 'info',
      message: `入场信号已触发（${action}），等待执行`,
      timestamp: Date.now(),
    });
  }

  if (pos && pos.upnl < 0) {
    monitorAlerts.push({
      id: 'unrealized-loss',
      level: 'warning',
      message: `浮动亏损 ${pos.upnl.toFixed(2)} USDT`,
      timestamp: Date.now(),
    });
  }

  return {
    pipeline,
    positionState,
    monitorAlerts,
    updatedAt: Date.now(),
  };
}

// ============================================================
// 完整映射入口
// ============================================================

export interface ThreeScreensMappedData {
  screen1: Screen1Data;
  screen2: Screen2Data;
  screen3: Screen3Data;
  price?: number;
  summary?: string;
}

export function mapThreeScreens(
  trend: TrendScreenData,
  wave: V4WaveStrategyData,
  dataDriven?: DataDrivenScreensData | null,
): ThreeScreensMappedData {
  return {
    screen1: mapScreen1(trend, dataDriven),
    screen2: mapScreen2(wave, trend, dataDriven),
    screen3: mapScreen3(wave, trend),
    price: dataDriven?.price || trend.price || wave.current_price,
    summary: dataDriven?.summary,
  };
}
