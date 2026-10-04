/**
 * 三屏趋势系统 API 客户端
 *
 * 调用 11-易经推理系统/data_server_fixed.py (端口 8765) 暴露的
 * 三屏趋势策略接口：
 *   - GET /api/trend-screen?symbol=BTC   三屏趋势信号（Screen1 战略层）
 *   - GET /api/v4-wave-strategy?symbol=BTC  V4+波浪互斥融合策略（Screen2/3）
 *
 * 后端已设置 Access-Control-Allow-Origin: *，可直接从浏览器跨域调用。
 */

const TREND_BASE = process.env.NEXT_PUBLIC_TREND_SYSTEM_URL || 'http://127.0.0.1:8765';

async function trendRequest<T = any>(endpoint: string): Promise<T> {
  const url = `${TREND_BASE}${endpoint}`;
  // GET 请求不设置 Content-Type，避免触发 CORS 预检（OPTIONS）
  // 后端 BaseHTTPRequestHandler 不支持 OPTIONS 方法
  // 设置 30s 超时（后端首次请求可能需要 15-20s 从 OKX 拉取数据）
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 30_000);

  try {
    const response = await fetch(url, {
      method: 'GET',
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new Error(`Trend API Error: ${response.status} ${response.statusText}`);
    }

    return response.json();
  } finally {
    clearTimeout(timeoutId);
  }
}

// ============================================================
// 类型定义（后端返回结构）
// ============================================================

export interface TrendConsistencyTf {
  static_direction: string;
  dynamic_direction: string;
  final_direction: string;
  core_direction: string;
  confidence: number;
  reversal_score: number;
  bull_count: number;
  bear_count: number;
  avg_speed: number;
  avg_acceleration: number;
  signals: Array<{ indicator: string; direction: string; speed: number; acceleration: number }>;
}

export interface TrendScreenData {
  symbol: string;
  spot_inst: string;
  price: number;
  generated_at: string;
  timeframes: { weekly: number; daily: number; '4h': number; '1h': number };
  trend_consistency: {
    weekly: TrendConsistencyTf;
    daily: TrendConsistencyTf;
    consistent: boolean;
    overall_direction: string;
    consistency_confidence: number;
  };
  bayesian_confidence: {
    direction: string;
    confidence: number;
    bull_probability: number;
    bear_probability: number;
  };
  fundamental_data: {
    direction: string;
    confidence: number;
    reports: Array<{ type: string; title: string; direction: string; confidence: number }>;
    bull_count: number;
    bear_count: number;
    total_reports: number;
  };
  freqtrade_signals: {
    '1h': { signal: string; confidence: number; strategy: string };
    '4h': { signal: string; confidence: number; strategy: string };
  };
  technical_fundamental_fusion: {
    technical: { direction: string; confidence: number };
    fundamental: { direction: string; confidence: number };
    consistent: boolean;
    final_direction: string;
    final_confidence: number;
  };
  final_signal: {
    direction: string;
    confidence: number;
    trend_consistent: boolean;
    fusion_consistent: boolean;
    freqtrade_consistent: boolean;
    action: string;
    position: { position_pct: number; tier: string };
    decision_reason: string;
  };
  account: { equity: number; available: number };
  position: any;
}

export interface V4WaveStrategyData {
  symbol: string;
  spot_inst: string;
  current_price: number;
  data_days: number;
  generated_at: string;
  v4_strategy: {
    strategy_name: string;
    is_btc: boolean;
    action: string;
    direction: string;
    position_pct: number;
    raw_position: number;
    state: string;
  };
  wave_strategy: {
    wave_signal: string;
    wave_label: string;
    current_wave: number;
    wave_confidence: number;
    wave_direction: string;
    wave_position_pct: number;
    wave_physics_confidence: number;
    wave_eta: number;
    wave_kinetic_score: number;
    wave_trailing_stop_pct: number;
    wave_take_profit_pct: number;
    total_position_pct: number;
    final_action: string;
    final_direction: string;
    fusion_rule: string;
    enabled: boolean;
  };
  physics_assessment: {
    enabled: boolean;
    weak_trend: boolean;
    current_eta: number;
    physics_confidence: number;
    components: {
      trend_score: number;
      reversal_score: number;
      support_score: number;
      kinetic_score: number;
    };
  };
  final_decision: {
    action: string;
    direction: string;
    position_pct: number;
    adjusted_position_pct: number;
    fusion_rule: string;
  };
  account: { equity: number; available: number };
  position: {
    coin: string;
    side: string;
    size: number;
    entry_px: number;
    leverage: number;
    upnl: number;
    mark_px?: number;
  } | null;
  all_positions: Array<{
    coin: string;
    side: string;
    size: number;
    entry_px: number;
    leverage: number;
    upnl: number;
  }>;
  strategy_line: string;
  mode: string;
}

// ============================================================
// 数据驱动三屏分析（技术面 + 数据中心基本面）
// ============================================================

export interface FundamentalDimension {
  direction: string;
  confidence: number;
  value?: number;
  weight: number;
}

export interface DataDrivenScreensData {
  symbol: string;
  price: number;
  generated_at: string;
  screen1: {
    direction: string;
    confidence: number;
    technical: { direction: string; confidence: number };
    fundamental_dimensions: Record<string, FundamentalDimension>;
    fundamental_direction: string;
    fundamental_confidence: number;
    fundamental_score: number;
    fusion: { consistent: boolean; reason: string };
    debate: string;
  };
  screen2: {
    direction_constraint: string;
    volatility: {
      avg_speed: number;
      avg_acceleration: number;
      reversal_score: number;
      vol_multiplier: number;
    };
    derivatives: {
      funding_rate: number;
      funding_direction: string;
      options_oi: number;
    };
    presets: Array<{
      id: string;
      symbol: string;
      entry: number;
      stop: number;
      target: number;
      timeframe: string;
      confidence: number;
      take_profit_pct: number;
      stop_loss_pct: number;
    }>;
    backtest: { winRate: number; avgR: number; maxDD: number; sharpe: number };
  };
  screen3: {
    entry_signals: {
      final_action: string;
      direction: string;
      confidence: number;
    };
    pipeline: Array<{
      id: string;
      name: string;
      status: string;
      output?: string;
    }>;
    position_state: any;
    monitor_alerts: Array<{
      id: string;
      level: string;
      message: string;
      timestamp: string;
    }>;
  };
  fundamental_data: Record<string, any>;
  summary: string;
}

// ============================================================
// API 方法
// ============================================================

export const ThreeScreensAPI = {
  /** 获取三屏趋势信号（Screen1 战略层数据） */
  async fetchTrendScreen(symbol: string = 'BTC'): Promise<TrendScreenData> {
    return trendRequest<TrendScreenData>(`/api/trend-screen?symbol=${encodeURIComponent(symbol)}`);
  },

  /** 获取 V4+波浪互斥融合策略（Screen2 战术层 + Screen3 执行层数据） */
  async fetchV4WaveStrategy(symbol: string = 'BTC'): Promise<V4WaveStrategyData> {
    return trendRequest<V4WaveStrategyData>(`/api/v4-wave-strategy?symbol=${encodeURIComponent(symbol)}`);
  },

  /** 获取数据驱动三屏分析（技术面 + 数据中心基本面多维数据） */
  async fetchDataDrivenScreens(symbol: string = 'BTC'): Promise<DataDrivenScreensData> {
    return trendRequest<DataDrivenScreensData>(`/api/data-driven-screens?symbol=${encodeURIComponent(symbol)}`);
  },

  /** 一次性获取三屏完整数据（并行请求 trend-screen + v4-wave-strategy + data-driven-screens） */
  async fetchAll(symbol: string = 'BTC'): Promise<{
    trend: TrendScreenData;
    wave: V4WaveStrategyData;
    dataDriven: DataDrivenScreensData | null;
  }> {
    const [trend, wave, dataDriven] = await Promise.allSettled([
      this.fetchTrendScreen(symbol),
      this.fetchV4WaveStrategy(symbol),
      this.fetchDataDrivenScreens(symbol),
    ]);

    return {
      trend: trend.status === 'fulfilled' ? trend.value : ({} as TrendScreenData),
      wave: wave.status === 'fulfilled' ? wave.value : ({} as V4WaveStrategyData),
      dataDriven: dataDriven.status === 'fulfilled' ? dataDriven.value : null,
    };
  },
};

export default ThreeScreensAPI;
