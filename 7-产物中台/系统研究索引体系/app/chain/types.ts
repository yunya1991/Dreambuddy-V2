/**
 * Chain 页面 A4/A5 类型定义
 * 版本: v1.0
 * 说明: 支持 A4(验证仓) 和 A5(执行仓) 的分组显示
 */

/* ─── A4/A5 单个持仓组 ─── */
export interface PositionGroup {
  hasPosition: boolean;
  instId?: string;
  side?: string;        // "LONG" | "SHORT"
  sz?: string;          // 持仓数量
  lever?: string;       // 杠杆倍数
  upl?: string;         // 未实现盈亏
  uplRatio?: string;    // 盈亏比例
  holdHours?: number;   // 持仓时长
  entryPx?: number;    // 入场价格
  liqPx?: number;      // 强平价格
  posId?: string;       // 持仓 ID
}

/* ─── 挂单信息 ─── */
export interface Order {
  instId: string;
  ordId: string;
  side: 'open' | 'close';
  posSide: 'long' | 'short';
  ordType: 'limit' | 'post_only' | 'market';
  px: string;
  sz: string;
  state: 'live' | 'filled' | 'canceled';
  description?: string;
  cTime?: string;       // 创建时间
}

/* ─── 策略信息 ─── */
export interface StrategyInfo {
  name: string;
  signal?: string;
  confidence?: number;   // 0-1 或 0-100
  keyLevels?: number[];   // 关键价位
  stopLoss?: number;      // 止损价
  takeProfit?: number;    // 止盈价
}

/* ─── A4/A5 持仓分组 ─── */
export interface PhasePosition {
  a4: PositionGroup;
  a5: PositionGroup;
}

/* ─── A4/A5 挂单分组 ─── */
export interface PhaseOrders {
  a4: Order[];
  a5: Order[];
}

/* ─── A4/A5 策略分组 ─── */
export interface PhaseStrategy {
  a4?: StrategyInfo;
  a5?: StrategyInfo;
}

/* ─── Chain 页面完整持仓数据 ─── */
export interface ChainPosition {
  hasPosition: boolean;
  positions: PhasePosition;
  orders: PhaseOrders;
  strategy?: PhaseStrategy;
  position_source?: 'a4' | 'a5';
  timestamp?: string;
  market_regime?: string;   // 市场环境
  final_decision?: string;   // 决策结果
}

/* ─── Chain 页面策略摘要 ─── */
export interface StrategySummary {
  // A3 战略指令
  a3?: {
    regime?: string;      // 市场环境: "趋势延续", "震荡", "假突破风险"等
    direction?: string;   // 方向: "多头试探", "空头试探", "观望"等
    keyLevel?: string;    // 关键价位
    confidence?: number;  // 置信度 0-100
    scenario?: string;    // 主导情景
    timestamp?: string;
    source?: string;      // 产物文件名
  };
  // A4 战术验证
  a4?: {
    signal?: string;      // 验证信号
    confidence?: number;  // 置信度
    validationStatus?: 'pass' | 'fail' | 'pending';
    validationMethod?: string;
    timestamp?: string;
    source?: string;
  };
  // A5 战术执行
  a5?: {
    triggerConditions?: string;    // 触发条件
    si?: number;                  // Signal Index
    edge?: number;                // Edge 值
    regimeFit?: number;           // Regime Fit
    action?: string;              // 执行动作
    timestamp?: string;
    source?: string;
  };
  // A9 离场决策
  a9?: {
    riskLevel?: 'low' | 'medium' | 'high' | 'critical';
    decision?: string;           // HOLD / EXIT / REDUCE
    reason?: string;              // 决策原因
    timestamp?: string;
    // L0-L2 风控状态
    l0Status?: 'pass' | 'fail';
    l1Status?: 'pass' | 'fail' | 'warning';
    l2Status?: 'pass' | 'warning';
  };
  // 更新时间
  lastUpdated?: string;
}

/* ─── Phase 样式配置 ─── */
export interface PhaseStyle {
  bg: string;           // 背景色
  border: string;        // 边框色
  text: string;          // 标题文字色
  badge: string;         // 标签色
  icon: string;          // 图标
  label: string;         // 显示名
}

/* ─── Phase 样式预设 ─── */
export const PHASE_STYLES: Record<'a4' | 'a5', PhaseStyle> = {
  a4: {
    bg: '#FFF3E0',
    border: '#FF9800',
    text: '#E65100',
    badge: '#FFCC80',
    icon: '🔶',
    label: 'A4 验证仓'
  },
  a5: {
    bg: '#E8F5E9',
    border: '#4CAF50',
    text: '#2E7D32',
    badge: '#A5D6A7',
    icon: '🔷',
    label: 'A5 执行仓'
  }
};

/* ─── 向后兼容：旧日志格式转换 ─── */
export function normalizeToChainPosition(logData: any): ChainPosition {
  // 新格式：直接返回
  if (logData && logData.positions) {
    return {
      hasPosition: logData.hasPosition || false,
      positions: {
        a4: logData.positions.a4 || { hasPosition: false },
        a5: logData.positions.a5 || { hasPosition: false }
      },
      orders: {
        a4: logData.orders?.a4 || [],
        a5: logData.orders?.a5 || []
      },
      strategy: logData.strategy,
      position_source: logData.position_source,
      timestamp: logData.timestamp,
      market_regime: logData.market_regime,
      final_decision: logData.final_decision
    } as ChainPosition;
  }

  // 旧格式：兼容处理
  const legacyPos = logData?.position || logData;
  return {
    hasPosition: !!(legacyPos?.hasPosition || legacyPos?.instId || legacyPos?.sz),
    positions: {
      a4: { hasPosition: false },
      a5: {
        hasPosition: !!(legacyPos?.hasPosition || legacyPos?.instId || legacyPos?.sz),
        instId: legacyPos?.instId || legacyPos?.posId || 'BTC-USDT-SWAP',
        side: legacyPos?.side || (legacyPos?.posSide === 'short' ? 'SHORT' : 'LONG'),
        sz: legacyPos?.sz || legacyPos?.position || '0',
        lever: legacyPos?.lever || legacyPos?.lever || '3',
        upl: legacyPos?.upl || legacyPos?.unrealizedPnl || '0',
        uplRatio: legacyPos?.uplRatio,
        holdHours: legacyPos?.holdHours || legacyPos?.hold_hours,
        entryPx: legacyPos?.entryPx || legacyPos?.avgPx || legacyPos?.entry_price,
        liqPx: legacyPos?.liqPx || legacyPos?.liqPx,
        posId: legacyPos?.posId || legacyPos?.posId
      }
    },
    orders: { a4: [], a5: [] },
    strategy: undefined,
    position_source: 'a5',
    timestamp: logData?.timestamp || new Date().toISOString()
  } as ChainPosition;
}
