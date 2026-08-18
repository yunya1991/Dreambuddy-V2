/**
 * 资产标的调研引擎 - 类型定义
 * Asset Research Engine - Type Definitions
 */

// ==================== 核心枚举 ====================

/** 经济周期四阶段 */
export type CyclePhase = 'recovery' | 'overheat' | 'stagflation' | 'recession';

/** 资产大类 */
export type AssetCategory =
  | 'stock'        // 股票
  | 'bond'         // 债券
  | 'commodity'    // 商品
  | 'cash'         // 现金/货币
  | 'crypto';      // 加密货币

/** 资产子类 */
export type AssetSubCategory =
  // 股票子类
  | 'tech' | 'financial' | 'energy' | 'consumer' | 'cyclical'
  // 债券子类
  | 'treasury' | 'credit' | 'convertible' | 'high_yield'
  // 商品子类
  | 'precious_metal' | 'energy_commodity' | 'industrial_metal' | 'agricultural'
  // 现金/货币子类
  | 'usd' | 'cny' | 'eur' | 'jpy'
  // 加密子类
  | 'mainstream_crypto' | 'exchange_token' | 'layer2' | 'defi' | 'infrastructure';

/** 趋势方向 */
export type TrendDirection = 'up' | 'down' | 'flat';

/** 配置方向 */
export type AllocationDirection = 'overweight' | 'neutral' | 'underweight';

/** 数据新鲜度 */
export type DataFreshness = 'fresh' | 'acceptable' | 'stale';

/** 区域设置 */
export type Region = 'global' | 'us' | 'cn';

// ==================== 数据结构 ====================

/** 宏观经济指标 */
export interface MacroIndicator {
  name: string;                    // 指标名称
  value: string;                   // 数值
  unit?: string;                   // 单位
  trend: TrendDirection;           // 趋势
  source: string;                  // 数据来源
  timestamp: string;                // 数据时间
  freshness: DataFreshness;         // 新鲜度
}

/** 周期判定结果 */
export interface CycleAssessment {
  currentPhase: CyclePhase;
  confidence: number;              // 0-1 置信度
  indicators: MacroIndicator[];     // 判定依据的指标
  rationale: string;               // 判定理由
  phaseProbability?: Record<CyclePhase, number>;  // 各阶段概率（v3使用）
}

/** 子类资产 */
export interface SubCategoryAsset {
  name: AssetSubCategory;
  displayName: string;              // 显示名称
  priority: number;                 // 优先级（1-N，数字越小优先级越高）
  direction: AllocationDirection;
  rationale: string;               // 推荐理由
  cyclePreference: CyclePhase[];    // 偏好的周期
}

/** 大类资产配置 */
export interface AssetAllocation {
  category: AssetCategory;
  displayName: string;
  weight: number;                   // 建议配置比例（0-100%）
  direction: AllocationDirection;
  subCategories: SubCategoryAsset[];
}

/** 数据来源引用 */
export interface DataSourceRef {
  name: string;
  url?: string;
  timestamp: string;
}

/** 研究选项 */
export interface ResearchOptions {
  region?: Region;
  customIndicators?: MacroIndicator[];
  dataSources?: ('tavily' | 'custom')[];
  runAllVersions?: boolean;         // 是否并行运行所有版本
}

// ==================== 研究结果 ====================

/** 单版本研究结果 */
export interface ResearchResult {
  version: string;
  engineName: string;
  timestamp: string;
  region: Region;

  cycle: CycleAssessment;
  assetAllocation: AssetAllocation[];
  topSubCategories: SubCategoryAsset[];  // 综合排名前10的子类

  report: string;                   // Markdown报告
  dataSources: DataSourceRef[];
  confidence: number;              // 整体置信度 0-1
  metadata?: Record<string, unknown>;
}

/** 多版本对比结果 */
export interface VersionComparison {
  versions: string[];
  cycleAgreement: number;              // 周期判断一致度 0-1
  allocationCorrelation: number;        // 配置相关性 0-1
  topSubCategoriesOverlap: number;     // 推荐子类重合度 0-1
  recommendation: string;
  rollbackCandidate?: string;          // 回退候选版本
  details: {
    cyclePhase: Record<string, CyclePhase>;
    topAssets: Record<string, string[]>;
  };
}

/** 多版本研究结果 */
export interface MultiVersionResult {
  results: ResearchResult[];
  comparison?: VersionComparison;
  bestVersion?: string;
}

// ==================== 引擎接口 ====================

/** 资产研究引擎接口 */
export interface AssetResearchEngine {
  readonly version: string;
  readonly name: string;
  readonly description: string;

  run(options?: ResearchOptions): Promise<ResearchResult>;
  getCyclePhase(): CyclePhase;
  getAssetAllocation(phase: CyclePhase): AssetAllocation[];
}

// ==================== 数据获取 ====================

/** Tavily搜索结果 */
export interface TavilySearchResult {
  url: string;
  title: string;
  content: string;
  publishedDate?: string;
}

/** 指标提取结果 */
export interface IndicatorExtraction {
  indicator: MacroIndicator;
  rawText: string;
  confidence: number;              // 提取置信度
}

// ==================== 常量配置 ====================

/** 周期配置 */
export const CYCLE_CONFIG: Record<CyclePhase, {
  displayName: string;
  description: string;
  growth: 'up' | 'down';
  inflation: 'up' | 'down';
}> = {
  recovery: {
    displayName: '复苏期',
    description: '经济上行，通胀下行。货币政策宽松，企业盈利改善。',
    growth: 'up',
    inflation: 'down'
  },
  overheat: {
    displayName: '过热期',
    description: '经济上行，通胀上行。产能利用率高，通胀压力显现。',
    growth: 'up',
    inflation: 'up'
  },
  stagflation: {
    displayName: '滞胀期',
    description: '经济下行，通胀上行。增长放缓，通胀高企。',
    growth: 'down',
    inflation: 'up'
  },
  recession: {
    displayName: '衰退期',
    description: '经济下行，通胀下行。需求萎缩，通缩风险。',
    growth: 'down',
    inflation: 'down'
  }
};

/** 资产类别配置 */
export const ASSET_CATEGORY_CONFIG: Record<AssetCategory, {
  displayName: string;
  displayNameEn: string;
}> = {
  stock: { displayName: '股票', displayNameEn: 'Stock' },
  bond: { displayName: '债券', displayNameEn: 'Bond' },
  commodity: { displayName: '商品', displayNameEn: 'Commodity' },
  cash: { displayName: '现金/货币', displayNameEn: 'Cash/Currency' },
  crypto: { displayName: '加密货币', displayNameEn: 'Cryptocurrency' }
};

/** 子类显示名称映射 */
export const SUB_CATEGORY_DISPLAY: Record<AssetSubCategory, { name: string; category: AssetCategory }> = {
  // 股票
  tech: { name: '科技股', category: 'stock' },
  financial: { name: '金融股', category: 'stock' },
  energy: { name: '能源股', category: 'stock' },
  consumer: { name: '消费股', category: 'stock' },
  cyclical: { name: '周期股', category: 'stock' },
  // 债券
  treasury: { name: '国债', category: 'bond' },
  credit: { name: '信用债', category: 'bond' },
  convertible: { name: '可转债', category: 'bond' },
  high_yield: { name: '高收益债', category: 'bond' },
  // 商品
  precious_metal: { name: '贵金属', category: 'commodity' },
  energy_commodity: { name: '能源', category: 'commodity' },
  industrial_metal: { name: '工业金属', category: 'commodity' },
  agricultural: { name: '农产品', category: 'commodity' },
  // 现金/货币
  usd: { name: '美元', category: 'cash' },
  cny: { name: '人民币', category: 'cash' },
  eur: { name: '欧元', category: 'cash' },
  jpy: { name: '日元', category: 'cash' },
  // 加密
  mainstream_crypto: { name: '主流币(BTC/ETH)', category: 'crypto' },
  exchange_token: { name: '平台币', category: 'crypto' },
  layer2: { name: '二层网络', category: 'crypto' },
  defi: { name: 'DeFi', category: 'crypto' },
  infrastructure: { name: '基建公链', category: 'crypto' }
};

// ==================== 回测类型 ====================

/** 回测配置 */
export interface BacktestConfig {
  initialCapital?: number;          // 初始资金
  commission?: number;              // 交易佣金比例
  slippage?: number;                // 滑点比例
  rebalanceThreshold?: number;      // 再平衡阈值
  minTradeAmount?: number;          // 最小交易金额
}

/** 回测交易记录 */
export interface BacktestTrade {
  date: string;
  action: 'buy' | 'sell';
  asset: string;
  amount: number;
  price: number;
  value: number;
}

/** 期间表现 */
export interface PeriodPerformance {
  period: number;
  startDate: string;
  endDate: string;
  cyclePhase: CyclePhase;
  return: number;
  startValue: number;
  endValue: number;
  tradesCount: number;
}

/** 回测指标 */
export interface BacktestMetrics {
  totalReturn: number;             // 总收益率
  annualizedReturn: number;        // 年化收益率
  sharpeRatio: number;             // 夏普比率
  maxDrawdown: number;             // 最大回撤
  winRate: number;                 // 胜率
  avgHoldingPeriod: number;         // 平均持仓期（天）
  turnoverRate: number;            // 换手率
}

/** 回测结果 */
export interface BacktestResult {
  config: Required<BacktestConfig>;
  startDate: string;
  endDate: string;
  initialCapital: number;
  finalValue: number;
  metrics: BacktestMetrics;
  periodPerformances: PeriodPerformance[];
  trades: BacktestTrade[];
  versionComparison?: Record<string, BacktestResult>;
}

// ==================== 告警类型 ====================

/** 告警类型 */
export type AlertType =
  | 'cycle_change'       // 周期变化
  | 'confidence_drop'    // 置信度下降
  | 'allocation_change'  // 配置变化
  | 'risk_warning'       // 风险警告
  | 'version_fallback'   // 版本回退
  | 'daily_report';      // 日常报告

/** 告警严重程度 */
export type AlertSeverity = 'low' | 'medium' | 'high' | 'critical';

/** 告警渠道 */
export type AlertChannel = 'lark' | 'email' | 'webhook' | 'console';

/** 告警配置 */
export interface AlertConfig {
  enabled?: boolean;
  channels?: AlertChannel[];
  larkWebhookUrl?: string;
  emailConfig?: {
    host: string;
    port: number;
    user: string;
    password: string;
    from: string;
    to: string[];
  };
  webhookConfigs?: Array<{
    url: string;
    method?: 'POST' | 'GET';
    headers?: Record<string, string>;
  }>;
  cooldownMinutes?: number;        // 告警冷却时间（分钟）
  severityThresholds?: {           // 严重程度阈值
    critical: number;
    high: number;
    medium: number;
    low: number;
  };
}

/** 告警 */
export interface Alert {
  id: string;
  type: AlertType;
  title: string;
  message: string;
  severity: AlertSeverity;
  timestamp: string;
  data?: Record<string, unknown>;
}

// ==================== 导出类型 ====================

/** 导出格式 */
export type ExportFormat = 'markdown' | 'html' | 'json' | 'csv' | 'pdf';

/** 导出选项 */
export interface ExportOptions {
  format: ExportFormat;
  includeRawData?: boolean;
  template?: 'default' | 'minimal' | 'detailed';
  language?: 'zh-CN' | 'en-US';
}

// ==================== 定时任务类型 ====================

/** 定时任务配置 */
export interface ScheduleConfig {
  id?: string;
  name: string;
  cronExpression: string;
  enabled?: boolean;
  region?: Region;
  runAllVersions?: boolean;
}

/** 定时任务状态 */
export interface ScheduleJob {
  id: string;
  name: string;
  cronExpression: string;
  enabled: boolean;
  lastRun?: string;
  nextRun?: string;
  runCount: number;
  successCount: number;
}
