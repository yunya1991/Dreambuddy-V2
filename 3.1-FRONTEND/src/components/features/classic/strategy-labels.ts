/**
 * 策略字段中文映射表
 *
 * 供 ManagementPanel 和 GenerationPanel 共用，将策略 JSON 中的英文键名和枚举值
 * 转换为用户可读的中文名称，并提供 tooltip 解释。
 */

// 字段 → 中文名
export const FIELD_LABELS: Record<string, string> = {
  strategy_id: '策略ID',
  cloned_from: '克隆自',
  family: '策略类型',
  tier: '评级',
  stage: '状态',
  owner: '归属',
  source_zip: '源文件',
  profit_factor: '盈亏比',
  trades: '交易数',
  winrate: '胜率',
  profit_total_pct: '总收益',
  max_drawdown_pct: '最大回撤',
  sharpe_ratio: '夏普比率',
  sortino_ratio: 'Sortino',
  backtest_days: '回测天数',
};

// 字段 → tooltip 解释
export const FIELD_TOOLTIPS: Record<string, string> = {
  profit_factor: '盈利总额/亏损总额。>1.5为良好，2.0+为优秀，<1为亏损',
  winrate: '盈利交易占总交易比例。>50%为良，趋势策略40%+也可接受',
  sharpe_ratio: '风险调整后收益。>1为良，>2为优，<0为亏损',
  max_drawdown_pct: '从最高点到最低点的最大跌幅。越小越好，<-20%为高风险',
  profit_total_pct: '回测期间总收益率',
  trades: '回测期间总交易笔数。<30笔统计意义不足',
  tier: 'S=公理级 A=可信 B=待验证 C=假设 D=已证伪',
  family: '策略逻辑分类：趋势/均值回归/动量/突破/网格',
  stage: '策略生命周期：运行中/草稿/归档/测试中',
  source_zip: '策略源码 zip 包，Freqtrade 可加载执行',
  cloned_from: '该策略克隆自哪个基线策略',
};

// 枚举值 → 中文
export const ENUM_LABELS: Record<string, Record<string, string>> = {
  family: {
    trend: '趋势跟随',
    mean_revert: '均值回归',
    momentum: '动量',
    breakout: '突破',
    grid: '网格',
  },
  stage: {
    active: '运行中',
    draft: '草稿',
    archived: '归档',
    testing: '测试中',
    research: '研究中',
  },
  tier: {
    S: '公理级',
    A: '可信',
    B: '待验证',
    C: '假设',
    D: '已证伪',
    unrated: '未评级',
  },
};

// 评级颜色
export const TIER_COLORS: Record<string, string> = {
  S: 'bg-amber-600/20 text-amber-400',
  A: 'bg-emerald-600/20 text-emerald-400',
  B: 'bg-cyan-600/20 text-cyan-400',
  C: 'bg-slate-600/20 text-slate-400',
  D: 'bg-rose-600/20 text-rose-400',
  unrated: 'bg-slate-700/20 text-slate-500',
};

/**
 * 从对象中获取嵌套值（支持 metrics_summary.profit_factor 等路径）
 */
export function getNestedValue(obj: any, key: string): any {
  if (!obj) return undefined;
  // 直接键
  if (key in obj) return obj[key];
  // 嵌套 metrics_summary
  if (obj.metrics_summary && key in obj.metrics_summary) return obj.metrics_summary[key];
  return undefined;
}

/**
 * 格式化字段值用于展示
 */
export function formatValue(key: string, value: any): string {
  if (value === null || value === undefined) return '-';
  // 枚举转中文
  for (const category of Object.keys(ENUM_LABELS)) {
    if (key === category && ENUM_LABELS[category][value]) {
      return ENUM_LABELS[category][value];
    }
  }
  // 百分比类
  if (key === 'winrate' || key === 'max_drawdown_pct' || key === 'profit_total_pct') {
    const num = typeof value === 'number' ? value : parseFloat(value);
    return `${(num * 100).toFixed(1)}%`;
  }
  // 比率类
  if (key === 'profit_factor' || key === 'sharpe_ratio' || key === 'sortino_ratio') {
    const num = typeof value === 'number' ? value : parseFloat(value);
    return num.toFixed(2);
  }
  // 整数
  if (key === 'trades' || key === 'backtest_days') {
    return String(Math.round(value));
  }
  // 默认
  return String(value);
}
