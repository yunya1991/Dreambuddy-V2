# 策略设置详细设计

> 版本: v1.3 | 日期: 2026-05-13 | 所属: Dream Universal Gateway
> **v1.3核心变更**: 新增积分体系(Credits)设计，与策略执行联动，积分不足时自动暂停策略，充值后恢复
> **v1.2核心变更**: 自定义策略输入从"结构化选择器"改为"自然语言+意图识别"，新增回测验证流程；技术指标/策略库不易漂移，定时执行效果更优
> **v1.1核心变更**: 自定义策略从"关键词→AI生成"重构为"技术指标信号策略"，引入策略库模板+A系列调优机制
> **v1.0核心变更**: 独立于API配置、交易参数、通信渠道的第四大功能设置

---

## 1. 设计哲学

### 1.1 为什么需要独立模块？

前三块功能解决了"连接(怎么连)"、"约束(怎么控)"、"通知(怎么传)"的问题，但缺少"策略(做什么)"这一核心业务配置。

```
API配置:  解决"连到哪里" → 连接层
交易参数: 解决"安全边界" → 约束层
通信渠道: 解决"通知渠道" → 通知层
策略设置: 解决"执行什么" → 业务层 ← 新增
```

### 1.2 四大独立功能

| 功能 | 定位 | 入口 | 配置文件 |
|------|------|------|----------|
| **API配置** | 连接凭证管理 | ⚙️ API配置 | api-keys.enc |
| **交易参数** | 交易行为约束 | 💰 交易设置 | trading-params.json |
| **通信渠道** | 消息推送通道 | 📡 通信渠道 | channels.enc |
| **策略设置** | 交易策略选择 | 🎯 策略设置 | strategies.json |

> 四者互不耦合，用户可只配置其中之一。但策略执行需要API配置+交易参数同时就绪。

### 1.3 策略设置 = 自动化交易的大脑

```
用户选择策略
      │
      ▼
┌──────────────────────────────────────┐
│  StrategyEngine (策略引擎)             │
│                                      │
│  · 推荐策略: A4定时推送 → 用户选择    │
│  · 自定义策略: 关键词 → A系列调研生成  │
│  · 策略应用 → 创建定时任务 → 自动执行  │
└──────────────────────────────────────┘
```

---

## 2. 策略分类

### 2.1 推荐策略 (Recommended Strategy)

**来源**: A4验证定时任务，每次执行后推送推荐策略到前端

```
A4定时任务执行 (1h/4h/1d)
      │
      ▼
┌──────────────────────────────────────┐
│  A4产出: 验证报告 + 策略建议          │
│  · 当前Regime匹配策略                 │
│  · 推荐操作: BUY/SHORT/SKIP          │
│  · 推荐杠杆/仓位                      │
│  · 推荐止损/止盈位                     │
│  · 置信度/Edge评分                    │
└──────────┬───────────────────────────┘
           │
           ▼
┌──────────────────────────────────────┐
│  策略推送到前端                        │
│  · 更新策略列表(增量，不覆盖)          │
│  · 新策略标记 [新] 徽章               │
│  · 置信度可视化展示                    │
└──────────────────────────────────────┘
```

**推荐策略特点**:
- 系统自动生成，每次A4执行更新一次
- 包含完整的A系列分析依据
- 附带置信度、Edge评分、历史胜率
- 用户查看后可选择"应用"或"忽略"

### 2.2 自定义策略 (Custom Strategy) — 技术指标信号策略

> **v1.2核心重构**: 用户输入方式从"结构化选择器"改为"自然语言+意图识别"。技术指标和策略库相对不易漂移，后期定时执行效果更优。自动化执行时必须带回测验证。

**来源**: 用户自然语言描述 → 意图识别解析技术指标条件 → 策略库匹配模板 → A系列分析调优 → 回测验证 → 输出

```
用户自然语言描述策略意图
(如: "RSI低于30并且MACD金叉的时候做多")
      │
      ▼
┌──────────────────────────────────────┐
│  前端: 发送 /api/config/strategies/  │
│  custom 请求                         │
│  Body: { rawInput, symbol }         │
└──────────┬───────────────────────────┘
           │
           ▼
┌──────────────────────────────────────┐
│  Step 1: 意图识别解析 (IntentParser)  │
│  · 识别策略意图: 做多/做空/...        │
│  · 提取技术指标: RSI, MACD, MA...     │
│  · 提取信号条件: 低于30, 金叉...      │
│  · 提取参数值: 周期14, 阈值30...      │
│  · 输出: parsedIntent →              │
│    signalConditions + signalLogic     │
└──────────┬───────────────────────────┘
           │
           ▼
┌──────────────────────────────────────┐
│  Step 2: 策略库匹配                   │
│  · 根据解析出的指标组合匹配模板        │
│  · 匹配度评分 + 参数预填充            │
│  · 未匹配 → 创建空白策略模板          │
└──────────┬───────────────────────────┘
           │
           ▼
┌──────────────────────────────────────┐
│  Step 3: A系列分析调优 (SSE流式)      │
│  · A1: 围绕指标信号进行市场侦察        │
│  · A2: 基于指标信号的第一性原理分析    │
│  · A3: 信号触发的情景推演+概率        │
│  · A4: 信号策略的验证方案设计          │
│  · 输出: 调优后的完整信号策略文件      │
└──────────┬───────────────────────────┘
           │
           ▼
┌──────────────────────────────────────┐
│  Step 4: 回测验证 (Backtester) ⭐NEW  │
│  · 基于调优后的策略参数执行历史回测    │
│  · 计算胜率/最大回撤/夏普比率          │
│  · 回测不达标 → A系列二次调优(1次)    │
│  · 回测达标 → 进入策略输出            │
│  · 技术指标不易漂移 → 定时执行效果优   │
└──────────┬───────────────────────────┘
           │
           ▼
┌──────────────────────────────────────┐
│  Step 5: 信号策略文件展示              │
│  · 用户可查看完整策略报告              │
│  · 回测结果展示(胜率/收益/回撤)       │
│  · 策略概要卡片展示(含指标参数)        │
│  · 用户点击"确认应用" → 创建定时任务   │
│  · 用户点击"存为草稿" → 保存待修改     │
│  · 支持下载策略文件(.md/.json)        │
└──────────────────────────────────────┘
```

**自定义策略(信号策略)特点**:
- **自然语言输入**：用户用日常语言描述策略意图，意图识别自动解析为结构化技术指标条件
- 聚焦技术指标信号（RSI/MACD/布林带/均线等），技术指标和策略库**不易漂移**，定时执行效果更优
- 策略库提供模板，A系列负责调优参数，双轮驱动
- **回测必过**：自动化执行前必须通过历史回测验证，不达标则二次调优
- 完整的A系列分析支撑（侦察→分析→推演→验证→回测）
- 生成后用户可预览、修改参数、再决定是否应用
- 应用时创建定时执行任务，信号触发时自动评估
- 支持策略下载（.md报告 / .json参数文件）

#### 2.2.1 技术指标体系

自定义策略围绕以下技术指标类别构建信号条件：

| 类别 | 指标 | 信号条件示例 | 参数 |
|------|------|-------------|------|
| **趋势类** | MA(均线) | MA5上穿MA20(金叉) | 周期(5/10/20/60/120) |
| | MACD | MACD金叉/死叉 | 快线/慢线/信号线周期 |
| | EMA | EMA交叉 | 周期 |
| **震荡类** | RSI | RSI<30(超卖) / RSI>70(超买) | 周期(默认14), 阈值 |
| | KDJ | K上穿D / K下穿D | 周期 |
| | StochRSI | 超买超卖区间 | K/D周期 |
| **波动类** | Bollinger Bands | 价格触及上轨/下轨 | 周期(默认20), 标准差倍数 |
| | ATR | ATR突破阈值 | 周期(默认14), 倍数 |
| **成交量** | Volume | 放量/缩量 | 对比周期, 放量倍数 |
| | OBV | OBV趋势方向 | - |
| **综合** | 自定义组合 | 多指标AND/OR组合 | - |

#### 2.2.2 策略库模板

策略库由用户后续建设，提供标准化的信号策略模板供匹配和调用：

```
策略库模板结构:
strategy_library/
├── trend_following/           # 趋势跟踪类
│   ├── ma_crossover.json      # 均线交叉策略模板
│   ├── macd_momentum.json     # MACD动量策略模板
│   └── ema_trend.json         # EMA趋势策略模板
├── mean_reversion/            # 均值回归类
│   ├── rsi_oversold.json      # RSI超卖反弹模板
│   ├── bollinger_bounce.json  # 布林带回归模板
│   └── kdj_golden.json        # KDJ金叉模板
├── breakout/                  # 突破类
│   ├── volume_breakout.json   # 放量突破模板
│   ├── bollinger_squeeze.json # 布林带收窄突破模板
│   └── range_breakout.json    # 区间突破模板
└── composite/                 # 组合策略类
    ├── trend_volume.json      # 趋势+量价确认模板
    └── multi_timeframe.json   # 多时间框架模板
```

**策略库模板Schema**:

```typescript
interface StrategyTemplate {
  id: string;                          // 模板ID: "tpl_ma_crossover"
  name: string;                        // 模板名称: "均线交叉策略"
  category: string;                    // 分类: "trend_following"
  description: string;                 // 描述
  
  // 信号条件定义
  signalConditions: SignalCondition[]; // 信号条件组(AND关系)
  
  // 默认参数
  defaultParams: {
    symbol: string;                    // 品种
    timeframe: string;                 // 时间框架
    direction: 'BUY' | 'SHORT';       // 默认方向
  };
  
  // 风控参数
  riskParams: {
    stopLossPercent: number;           // 默认止损%
    takeProfitPercent: number;         // 默认止盈%
    leverage: number;                  // 默认杠杆
  };
  
  // 匹配关键词(用于自动匹配)
  matchKeywords: string[];            // ["MA", "均线", "金叉", "crossover"]
  
  // 版本与状态
  version: string;
  isActive: boolean;
}

interface SignalCondition {
  indicator: string;                   // 指标名: "RSI", "MACD", "MA"
  condition: string;                   // 条件: "cross_above", "below", "above"
  params: Record<string, any>;         // 指标参数: { period: 14, threshold: 30 }
  operator?: 'AND' | 'OR';            // 与下一条件的逻辑关系(默认AND)
}
```

#### 2.2.3 自然语言 → 意图识别 → 策略库匹配流程

```
用户输入自然语言描述
(如: "RSI低于30且MACD金叉时做多")
      │
      ▼
┌──────────────────────────────────────┐
│  Step 1: 意图识别解析 (IntentParser)  │
│  · 识别策略方向: 做多/做空/观望       │
│  · 提取技术指标: RSI, MACD, MA...     │
│  · 提取信号条件: 低于/高于/上穿/下穿  │
│  · 提取参数值: 周期/阈值/倍数         │
│  · 提取逻辑关系: AND(且)/OR(或)       │
│  · 输出结构化: signalConditions[]     │
│                                      │
│  示例解析:                            │
│  "RSI低于30且MACD金叉时做多"          │
│  → direction: BUY                    │
│  → conditions: [                     │
│      RSI below 30 (AND),             │
│      MACD cross_above (AND)          │
│    ]                                 │
└──────────┬───────────────────────────┘
           │
           ▼
┌──────────────────────────────────────┐
│  Step 2: 策略库匹配                   │
│  · 按解析出的指标组合匹配模板          │
│  · 计算匹配度(0-100%)                 │
│  · 匹配度>80% → 直接使用模板+用户参数  │
│  · 匹配度50-80% → 模板+参数调整       │
│  · 匹配度<50% → 创建空白策略模板      │
└──────────┬───────────────────────────┘
           │
           ▼
┌──────────────────────────────────────┐
│  Step 3: A系列分析调优                │
│  · A1: 围绕信号条件进行市场侦察        │
│  · A2: 基于指标的深度分析              │
│  · A3: 信号触发情景推演               │
│  · A4: 信号策略验证                   │
│  · 调优建议: 参数微调、止损止盈优化    │
└──────────┬───────────────────────────┘
           │
           ▼
┌──────────────────────────────────────┐
│  Step 4: 回测验证 (Backtester) ⭐NEW  │
│  · 基于调优参数执行历史回测            │
│  · 计算关键指标:                      │
│    - 胜率(Win Rate)                   │
│    - 最大回撤(Max Drawdown)           │
│    - 夏普比率(Sharpe Ratio)           │
│    - 盈亏比(Profit Factor)           │
│  · 回测通过阈值:                      │
│    - 胜率≥45% | 回撤≤20% | PF≥1.2    │
│  · 不达标 → A系列二次调优(最多1次)    │
│  · 二次仍不达标 → 标记"回测未通过"     │
│    用户可选择: 降低仓位/修改参数/放弃  │
│  · 技术指标不易漂移 → 回测可信度高     │
└──────────┬───────────────────────────┘
           │
           ▼
┌──────────────────────────────────────┐
│  Step 5: 策略输出                     │
│  · 调优+回测后的信号策略文件          │
│  · 回测结果报告(含关键指标)           │
│  · 策略概要(含A系列调优建议)          │
│  · 三种操作: 应用/存为草稿/下载       │
└──────────────────────────────────────┘
```

**意图识别解析规则**:

| 自然语言模式 | 解析结果 |
|-------------|---------|
| "RSI低于30" / "RSI跌破30" / "RSI<30" | indicator: RSI, condition: below, value: 30 |
| "MACD金叉" / "MACD上穿信号线" | indicator: MACD, condition: cross_above |
| "MA5上穿MA20" / "5日线上穿20日线" | indicator: MA, condition: cross_above, params: {fast:5, slow:20} |
| "布林带下轨" / "触及BOLL下轨" | indicator: BOLL, condition: touch_lower |
| "且" / "并且" / "同时" / "AND" | operator: AND |
| "或" / "或者" / "OR" | operator: OR |
| "做多" / "买入" / "看多" | direction: BUY |
| "做空" / "卖出" / "看空" | direction: SHORT |
| "放量" / "成交量放大2倍" | indicator: Volume, condition: surge, params: {multiplier: 2} |

---

## 3. 策略Schema

### 3.1 推荐策略

```typescript
interface RecommendedStrategy {
  // ========== 身份标识 ==========
  id: string;                          // 策略唯一ID: "rec_20260513_001"
  type: 'recommended';                 // 策略类型
  source: 'A4';                        // 来源: A4推送

  // ========== 策略内容 ==========
  name: string;                        // 策略名称: "区间震荡-观望防守策略"
  description: string;                 // 策略描述(用户可见)
  regime: string;                     // 适用Regime: "RANGE_BOUND"

  // ========== 交易建议 ==========
  direction: 'BUY' | 'SHORT' | 'SKIP'; // 推荐方向
  symbol: string;                      // 品种: "BTC-USDT-SWAP"
  tradeType: 'spot' | 'swap';         // 交易类型
  leverage: number;                    // 推荐杠杆: 1-5
  positionSize: number;                // 推荐仓位: 0.1-1.0

  // ========== 风控参数 ==========
  stopLoss: number;                    // 止损价
  takeProfit: number;                  // 止盈价
  stopLossPercent: number;             // 止损百分比
  takeProfitPercent: number;           // 止盈百分比

  // ========== 评估指标 ==========
  confidence: number;                  // 置信度 0-100
  edgeScore: number;                   // Edge评分 -100~+100
  historicalWinRate?: number;          // 历史胜率(如有)

  // ========== A系列依据 ==========
  analysisBasis: {
    a1Summary: string;                // A1侦察摘要
    a2Summary: string;                // A2分析摘要
    a3Summary: string;                // A3推演摘要
    a4Summary: string;                // A4验证摘要
    scenarioProbs: {                   // 情景概率
      upside: number;                 // 上涨概率
      downside: number;               // 下跌概率
      range: number;                  // 区间概率
    };
  };

  // ========== 执行参数 ==========
  executionFrequency: '1h' | '4h' | '1d'; // 推荐执行频率
  validUntil?: string;                     // 策略有效期

  // ========== 关联产物 ==========
  artifactIds: string[];               // 关联的产物ID列表

  // ========== 元数据 ==========
  generatedAt: string;                 // 生成时间
  isRead: boolean;                     // 用户是否已读
  isApplied: boolean;                  // 用户是否已应用
  appliedAt?: string;                  // 应用时间
}
```

### 3.2 自定义策略（技术指标信号策略）

```typescript
interface CustomStrategy {
  // ========== 身份标识 ==========
  id: string;                          // 策略唯一ID: "custom_20260513_001"
  type: 'custom';                      // 策略类型
  source: 'user';                      // 来源: 用户自定义
  uid: string;                         // 创建用户UID

  // ========== 用户输入 (v1.2新增) ==========
  rawInput: string;                    // 用户原始自然语言输入
  // "RSI低于30并且MACD金叉的时候做多"

  // ========== 意图识别结果 (v1.2新增) ==========
  parsedIntent: {
    direction?: 'BUY' | 'SHORT' | 'SKIP'; // 识别出的策略方向
    signalConditions: SignalCondition[];   // 解析出的技术指标信号条件组
    signalLogic: 'AND' | 'OR';           // 条件间逻辑关系(默认AND)
    signalTimeframe?: string;             // 识别出的时间框架
    confidence: number;                   // 意图识别置信度 0-100
    rawEntities: string[];                // 识别出的原始实体词
    // ["RSI", "30", "MACD", "金叉", "做多"]
  };

  // ========== 策略库匹配 ==========
  templateId?: string;                 // 匹配的策略库模板ID
  templateMatchScore?: number;        // 匹配度(0-100)

  // ========== 策略内容 ==========
  name: string;                        // 策略名称(自动生成或用户命名)
  description: string;                 // 策略描述(自动生成)
  regime: string;                      // 适用Regime

  // ========== 交易建议(同推荐策略) ==========
  direction: 'BUY' | 'SHORT' | 'SKIP';
  symbol: string;
  tradeType: 'spot' | 'swap';
  leverage: number;
  positionSize: number;
  stopLoss: number;
  takeProfit: number;
  stopLossPercent: number;
  takeProfitPercent: number;

  // ========== 评估指标 ==========
  confidence: number;
  edgeScore: number;

  // ========== A系列调优依据 ==========
  analysisBasis: {
    a1Summary: string;                // A1侦察摘要(围绕信号条件)
    a2Summary: string;                // A2分析摘要(基于指标的深度分析)
    a3Summary: string;                // A3推演摘要(信号触发的情景)
    a4Summary: string;                // A4验证摘要(信号策略验证)
    scenarioProbs: {
      upside: number;
      downside: number;
      range: number;
    };
    tuningSuggestions?: string[];    // A系列调优建议
  };

  // ========== 回测结果 (v1.2新增) ==========
  backtestResult?: {
    status: 'pending' | 'running' | 'passed' | 'failed' | 'reoptimizing';
    // pending: 待回测 | running: 回测中 | passed: 通过 | failed: 未通过 | reoptimizing: 二次调优中
    period: string;                   // 回测区间: "2025-01-01~2026-05-13"
    totalSignals: number;              // 信号触发总次数
    winRate: number;                  // 胜率(%)
    maxDrawdown: number;              // 最大回撤(%)
    sharpeRatio: number;              // 夏普比率
    profitFactor: number;             // 盈亏比
    avgHoldTime: string;              // 平均持仓时间
    netProfit: number;                // 净收益(%)
    reoptimizeCount: number;          // 二次调优次数(最多1次)
    reoptimizeReason?: string;        // 二次调优原因
    passedAt?: string;               // 回测通过时间
  };

  // ========== 执行参数 ==========
  executionFrequency: '1h' | '4h' | '1d';
  signalTimeframe: '1m' | '5m' | '15m' | '1h' | '4h' | '1d'; // 信号检测时间框架

  // ========== 关联产物 ==========
  artifactIds: string[];

  // ========== 状态 ==========
  status: 'draft' | 'parsing' | 'matching' | 'analyzing' | 'backtesting' | 'approved' | 'applied' | 'expired';
  // draft: 草稿(用户输入自然语言中)
  // parsing: 意图识别解析中 (v1.2新增)
  // matching: 策略库匹配中
  // analyzing: A系列分析调优中
  // backtesting: 回测验证中 (v1.2新增)
  // approved: 用户已查看但未应用
  // applied: 用户已应用(已创建定时任务)
  // expired: 策略已过期

  // ========== 元数据 ==========
  createdAt: string;
  generatedAt?: string;               // A系列生成完成时间
  reviewedAt?: string;                 // 用户查看时间
  appliedAt?: string;                  // 应用时间
  expiredAt?: string;                  // 过期时间
}

// 信号条件定义
interface SignalCondition {
  id: string;                          // 条件ID
  indicator: string;                   // 指标名: "RSI", "MACD", "MA", "BOLL"
  indicatorLabel: string;              // 指标中文名: "RSI相对强弱", "MACD指标"
  condition: string;                   // 条件类型: "cross_above", "cross_below", "above", "below", "in_range"
  conditionLabel: string;              // 条件中文: "上穿", "下穿", "大于", "小于", "介于"
  params: Record<string, any>;         // 指标参数: { period: 14 }
  value?: number;                      // 阈值: 30, 70 等
  valueRange?: { min: number; max: number }; // 区间阈值
  operator: 'AND' | 'OR';             // 与下一条件的逻辑关系
  // v1.2: 以下字段由意图识别自动填充
  sourceText?: string;                 // 原始自然语言片段: "RSI低于30"
}

// 信号条件预设(后端意图识别使用，前端不再直接使用选择器)
interface SignalConditionPreset {
  indicator: string;
  label: string;
  aliases: string[];                    // 指标别名: ["RSI", "相对强弱", "rsi指标"]
  availableConditions: {
    value: string;                     // 条件类型值
    label: string;                     // 条件中文
    labelAliases: string[];            // 条件别名: ["金叉", "上穿", "交叉向上"]
    needsValue: boolean;              // 是否需要阈值
    valueType?: 'number' | 'range';   // 值类型
    defaultParams: Record<string, any>;
    paramSchema: ParamField[];         // 参数输入字段定义
  }[];
}

interface ParamField {
  key: string;
  label: string;
  type: 'number' | 'select';
  default: any;
  options?: { value: any; label: string }[];
  min?: number;
  max?: number;
  step?: number;
}
```

### 3.3 联合类型

```typescript
type Strategy = RecommendedStrategy | CustomStrategy;

// 策略列表
interface StrategyStore {
  version: string;
  updatedAt: string;
  recommendedStrategies: RecommendedStrategy[];
  customStrategies: CustomStrategy[];
}
```

---

## 4. A4策略推送机制

### 4.1 A4 SKILL增强

在A4 SKILL中增加策略推送到前端的功能：

```typescript
// A4执行完成后，自动生成推荐策略
async function generateRecommendedStrategy(
  a4Result: A4ValidationResult,
  context: ChainContext
): Promise<RecommendedStrategy> {

  // 1. 从A4验证结果提取策略建议
  const direction = a4Result.direction;      // BUY/SHORT/SKIP
  const confidence = a4Result.confidence;     // 置信度
  const edgeScore = a4Result.edgeScore;        // Edge评分

  // 2. 从A3推演结果提取情景概率
  const scenarioProbs = a4Result.scenarioProbs;

  // 3. 根据Regime确定执行频率
  const regime = context.marketState.regime;
  const executionFrequency = determineFrequency(regime);

  // 4. 构造推荐策略
  return {
    id: `rec_${formatDate(new Date())}_001`,
    type: 'recommended',
    source: 'A4',
    name: `${regimeLabel(regime)}-${directionLabel(direction)}策略`,
    description: generateDescription(a4Result),
    regime,
    direction,
    symbol: context.symbol || 'BTC-USDT-SWAP',
    tradeType: context.tradeType || 'spot',
    leverage: a4Result.recommendedLeverage,
    positionSize: a4Result.recommendedPosition,
    stopLoss: a4Result.stopLoss,
    takeProfit: a4Result.takeProfit,
    stopLossPercent: a4Result.stopLossPercent,
    takeProfitPercent: a4Result.takeProfitPercent,
    confidence,
    edgeScore,
    analysisBasis: {
      a1Summary: context.recentArtifacts.a1?.summary || '',
      a2Summary: context.recentArtifacts.a2?.summary || '',
      a3Summary: context.recentArtifacts.a3?.summary || '',
      a4Summary: a4Result.summary,
      scenarioProbs,
    },
    executionFrequency,
    artifactIds: context.recentArtifacts.allIds,
    generatedAt: new Date().toISOString(),
    isRead: false,
    isApplied: false,
  };
}

// Regime → 推荐频率映射
function determineFrequency(regime: string): '1h' | '4h' | '1d' {
  switch (regime) {
    case 'STRONG_BULL':
    case 'STRONG_BEAR':
      return '1h';      // 强趋势 → 高频监控
    case 'MODERATE_BULL':
    case 'MODERATE_BEAR':
      return '4h';      // 中等趋势 → 中频
    case 'RANGE_BOUND':
    default:
      return '1d';       // 区间震荡 → 低频
  }
}
```

### 4.2 A4推送流程

```
A4定时任务执行
      │
      ├── 1. 执行A4验证(现有逻辑不变)
      │
      ├── 2. 生成推荐策略(新增)
      │       │
      │       ▼
      │   generateRecommendedStrategy()
      │       │
      │       ▼
      │   写入 strategies.json (增量)
      │
      ├── 3. 推送通知(新增)
      │       │
      │       ▼
      │   通过通信渠道推送: "新策略推荐已更新"
      │
      └── 4. 前端更新(新增)
              │
              ▼
          SSE推送 strategy_update 事件
          (如果用户在线，实时更新策略列表)
```

### 4.3 A4 SKILL修改点

在A4 SKILL的执行末尾增加以下步骤：

1. **生成推荐策略**: 调用 `generateRecommendedStrategy()`
2. **写入策略存储**: 追加到 `~/.workbuddy/config/strategies.json`
3. **推送通知**: 通过现有通信渠道推送"新策略推荐"消息
4. **SSE推送**: 如果前端在线，推送 `strategy_update` 事件

---

## 5. 自定义策略(信号策略)生成流程

### 5.1 自然语言输入 → 意图识别 → 策略库匹配 → A系列调优 → 回测验证

```
用户在策略设置面板输入自然语言:
  "RSI低于30并且MACD金叉的时候做多"
      │
      ▼
┌──────────────────────────────────────┐
│  前端: 发送 /api/config/strategies/  │
│  custom 请求                         │
│  Body: {                             │
│    rawInput: "RSI低于30并且MACD金叉  │
│              的时候做多",             │
│    symbol: "BTC-USDT-SWAP"           │
│  }                                   │
└──────────┬───────────────────────────┘
           │
           ▼
┌──────────────────────────────────────┐
│  意图识别解析 (IntentParser)          │
│  · 方向: BUY (做多)                  │
│  · 指标1: RSI below 30 (AND)         │
│  · 指标2: MACD cross_above (AND)    │
│  · 识别置信度: 92%                   │
│  · 输出: signalConditions[]           │
└──────────┬───────────────────────────┘
           │
           ▼
┌──────────────────────────────────────┐
│  策略库匹配                           │
│  · 解析信号条件(指标+方向+参数)       │
│  · 按matchKeywords匹配策略库模板      │
│  · 匹配度评分: 85% → 使用模板调优    │
└──────────┬───────────────────────────┘
           │
           ▼
┌──────────────────────────────────────┐
│  A系列分析调优 (SSE流式)              │
│                                      │
│  ⠋ 正在侦察信号指标的市场环境...       │  ← A1
│  ✓ 市场侦察完成                       │
│  ⠋ 正在分析信号有效性...              │  ← A2
│  ✓ 信号分析完成                       │
│  ⠋ 正在推演信号触发情景...            │  ← A3
│  ✓ 情景推演完成                       │
│  ⠋ 正在验证信号策略可行性...          │  ← A4
│  ✓ 信号策略验证完成                   │
│                                      │
│  📄 信号策略报告已生成                 │
│  · A系列调优建议: RSI阈值建议调整为28 │
│  · MACD快线建议用8代替12以减少滞后    │
└──────────┬───────────────────────────┘
           │
           ▼
┌──────────────────────────────────────┐
│  回测验证 (Backtester) ⭐NEW          │
│                                      │
│  ⠋ 正在执行历史回测...                │
│  · 回测区间: 2025-01-01 ~ 2026-05-13 │
│  · 信号触发: 47次                     │
│  ⠋ 计算回测指标...                    │
│  ✓ 回测完成                           │
│                                      │
│  📊 回测结果:                         │
│  · 胜率: 61.7% ✅ (≥45%)             │
│  · 最大回撤: 12.3% ✅ (≤20%)         │
│  · 夏普比率: 1.42 ✅                 │
│  · 盈亏比: 1.68 ✅ (≥1.2)           │
│  · 净收益: +23.5%                    │
│                                      │
│  ✅ 回测通过，策略可用于实盘          │
│  · 技术指标不易漂移 → 定时执行效果优  │
└──────────┬───────────────────────────┘
           │
           ▼
┌──────────────────────────────────────┐
│  信号策略文件展示                      │
│  · 用户可查看完整策略报告             │
│  · 回测结果可视化(胜率/收益/回撤)     │
│  · 策略概要卡片展示(含指标参数+调优)  │
│  · 用户点击"确认应用" → 创建定时任务  │
│  · 用户点击"存为草稿" → 保存待修改    │
│  · 用户点击"下载" → 下载.md/.json    │
└──────────────────────────────────────┘
```

### 5.2 回测未通过时的二次调优流程

```
回测结果未通过阈值
(如: 胜率38% < 45%最低要求)
      │
      ▼
┌──────────────────────────────────────┐
│  系统判断: 需要二次调优               │
│  · 记录失败原因: 胜率不足             │
│  · 通知用户: "回测未通过，正在优化"   │
└──────────┬───────────────────────────┘
           │
           ▼
┌──────────────────────────────────────┐
│  A系列二次调优 (最多1次)              │
│  · 基于回测失败原因针对性调优          │
│  · 调整参数: 如放宽RSI阈值、          │
│    增加确认条件、调整止损止盈          │
│  · 重新生成策略                       │
└──────────┬───────────────────────────┘
           │
           ▼
┌──────────────────────────────────────┐
│  二次回测验证                         │
│  · 通过 → 正常输出                    │
│  · 仍不通过 → 标记"回测未通过"        │
│    用户可选:                          │
│    · 降低仓位(保守执行)               │
│    · 修改参数后重新生成               │
│    · 放弃此策略                       │
└──────────────────────────────────────┘
```

### 5.3 自定义策略生成API

```
POST /api/config/strategies/custom

Body:
{
  "rawInput": "RSI低于30并且MACD金叉的时候做多",
  "symbol": "BTC-USDT-SWAP",
  "uid": "user_001"
}

Response (SSE流式):
event: intent_parsed
data: { "direction": "BUY", "signalConditions": [{"indicator":"RSI","condition":"below","value":30,"operator":"AND","sourceText":"RSI低于30"},{"indicator":"MACD","condition":"cross_above","operator":"AND","sourceText":"MACD金叉"}], "signalLogic": "AND", "confidence": 92 }

event: progress
data: { "step": "策略库匹配", "detail": "正在匹配策略模板...", "matchScore": 85, "templateId": "tpl_rsi_oversold" }

event: progress
data: { "step": "市场侦察", "detail": "正在侦察RSI指标的市场环境..." }

event: progress
data: { "step": "信号分析", "detail": "正在分析RSI<30+MACD金叉信号有效性..." }

event: progress
data: { "step": "回测验证", "detail": "正在执行历史回测...", "backtestStatus": "running" }

event: backtest_result
data: { "status": "passed", "winRate": 61.7, "maxDrawdown": 12.3, "sharpeRatio": 1.42, "profitFactor": 1.68, "netProfit": 23.5 }

event: strategy_generated
data: {
  "strategy": {
    "id": "custom_20260513_001",
    "type": "custom",
    "name": "RSI超卖+MACD金叉做多策略",
    "description": "基于RSI超卖与MACD金叉双重确认的做多信号策略...",
    "rawInput": "RSI低于30并且MACD金叉的时候做多",
    "parsedIntent": {
      "direction": "BUY",
      "signalConditions": [...],
      "signalLogic": "AND",
      "confidence": 92,
      "rawEntities": ["RSI", "30", "MACD", "金叉", "做多"]
    },
    "templateId": "tpl_rsi_oversold",
    "templateMatchScore": 85,
    "direction": "BUY",
    "symbol": "BTC-USDT-SWAP",
    "leverage": 2,
    "confidence": 62,
    "edgeScore": 15,
    "backtestResult": {
      "status": "passed",
      "winRate": 61.7,
      "maxDrawdown": 12.3,
      "sharpeRatio": 1.42,
      "profitFactor": 1.68,
      "netProfit": 23.5,
      "totalSignals": 47,
      "period": "2025-01-01~2026-05-13"
    },
    "analysisBasis": {
      "tuningSuggestions": [
        "RSI阈值建议从30调整为28，历史回测胜率提升5%",
        "MACD快线建议用8代替12以减少滞后"
      ]
    }
  },
  "artifactId": "custom_strategy_20260513_001"
}
```

### 5.4 用户确认应用

```
POST /api/config/strategies/:id/apply

Body:
{
  "uid": "user_001",
  "exchangeConfigId": "okx_main",
  "executionFrequency": "4h"   // 用户选择执行频率
}

Response 200:
{
  "success": true,
  "taskId": "task_20260513_001",
  "strategyId": "custom_20260513_001",
  "nextExecutionAt": "2026-05-13T22:00:00+08:00",
  "message": "策略已应用，将按4h频率自动执行"
}
```

---

## 6. 策略应用 → 定时任务

### 6.1 应用流程

```
用户点击"确认应用"
      │
      ▼
┌──────────────────────────────────────┐
│  Step 1: 前置条件检查                 │
│  · API配置是否已验证？               │
│  · 交易参数是否已配置？              │
│  · 策略参数是否在交易参数边界内？     │
└──────────┬───────────────────────────┘
           │ 通过
           ▼
┌──────────────────────────────────────┐
│  Step 2: 策略→交易参数适配            │
│  · 策略杠杆 ≤ 用户杠杆上限？         │
│  · 策略仓位 ≤ 用户百分比？           │
│  · 品种在用户允许列表内？             │
│  · 越界 → 降级(同TradingGate逻辑)   │
└──────────┬───────────────────────────┘
           │ 适配完成
           ▼
┌──────────────────────────────────────┐
│  Step 3: 创建定时任务                 │
│  · 根据executionFrequency设定频率     │
│  · 关联用户UID + 交易所API           │
│  · 每次执行时:                       │
│    1. 获取最新A4验证结果              │
│    2. 匹配策略条件                   │
│    3. 通过TradingGate门禁            │
│    4. 执行下单                       │
│    5. 记录执行结果                   │
└──────────┬───────────────────────────┘
           │
           ▼
┌──────────────────────────────────────┐
│  Step 4: 启动任务                    │
│  · 注册到定时任务调度器              │
│  · 推送通知: "策略已应用"             │
│  · 记录审计日志                      │
└──────────────────────────────────────┘
```

### 6.2 定时任务执行流程

```
定时触发 (1h/4h/1d)
      │
      ▼
┌──────────────────────────────────────┐
│  Step 1: 获取最新市场状态              │
│  · 调用A6情报获取最新数据            │
│  · 对比策略条件是否仍然满足           │
└──────────┬───────────────────────────┘
           │
           ▼
┌──────────────────────────────────────┐
│  Step 2: 条件匹配                     │
│  · Regime是否匹配策略Regime？         │
│  · Edge是否在策略预期范围？           │
│  · 置信度是否满足阈值？               │
│  · 不匹配 → SKIP + 通知用户           │
└──────────┬───────────────────────────┘
           │ 匹配
           ▼
┌──────────────────────────────────────┐
│  Step 3: TradingGate门禁              │
│  · 查询用户UID的交易参数              │
│  · 执行8步门禁校验                    │
│  · 越界 → 降级或拦截                  │
└──────────┬───────────────────────────┘
           │ 通过
           ▼
┌──────────────────────────────────────┐
│  Step 4: 执行交易                     │
│  · 按策略参数+适配后参数下单          │
│  · 记录执行结果                      │
│  · 推送交易执行通知                   │
│  · 更新策略执行统计                   │
└──────────────────────────────────────┘
```

### 6.3 执行任务Schema

```typescript
interface StrategyExecutionTask {
  id: string;                           // 任务ID
  strategyId: string;                   // 关联策略ID
  uid: string;                         // 用户UID
  exchangeConfigId: string;             // 关联交易所API配置ID

  // 执行参数
  executionFrequency: '1h' | '4h' | '1d';
  nextExecutionAt: string;              // 下次执行时间
  lastExecutionAt?: string;             // 最近执行时间

  // 状态
  status: 'active' | 'paused' | 'completed' | 'failed';
  executionCount: number;               // 已执行次数
  skipCount: number;                     // 条件不匹配跳过次数
  tradeCount: number;                    // 实际交易次数

  // 执行历史
  history: StrategyExecutionRecord[];

  // 创建信息
  createdAt: string;
  createdBy: 'user' | 'system';
}

interface StrategyExecutionRecord {
  executedAt: string;
  triggerType: 'scheduled' | 'manual';   // 定时触发 or 手动触发
  conditionMatch: boolean;                // 条件是否匹配
  gateResult: 'passed' | 'blocked' | 'downgraded';
  tradeExecuted: boolean;                 // 是否实际执行交易
  tradeDirection?: 'BUY' | 'SHORT';
  tradeAmount?: number;
  tradeResult?: 'success' | 'partial' | 'failed';
  skipReason?: string;                    // 跳过原因
  blockReason?: string;                   // 门禁拦截原因
}
```

---

## 7. 后端API接口

### 7.1 获取策略列表

```
GET /api/config/strategies?type=recommended|custom&status=active|applied|draft

Response 200:
{
  "recommended": [
    {
      "id": "rec_20260513_001",
      "name": "区间震荡-观望防守策略",
      "direction": "SKIP",
      "regime": "RANGE_BOUND",
      "confidence": 65,
      "edgeScore": -10,
      "executionFrequency": "1d",
      "generatedAt": "2026-05-13T12:00:00+08:00",
      "isRead": false,
      "isApplied": false
    }
  ],
  "custom": [
    {
      "id": "custom_20260513_001",
      "name": "ETH突破跟进策略",
      "keywords": "ETH突破策略",
      "direction": "BUY",
      "confidence": 62,
      "status": "approved",
      "createdAt": "2026-05-13T14:00:00+08:00"
    }
  ]
}
```

### 7.2 获取策略详情

```
GET /api/config/strategies/:id

Response 200:
{
  "strategy": {
    "id": "rec_20260513_001",
    "type": "recommended",
    "name": "区间震荡-观望防守策略",
    "description": "当前RANGE_BOUND格局下，CPI 3.8%超预期导致宏观转鹰，建议观望防守...",
    "regime": "RANGE_BOUND",
    "direction": "SKIP",
    "symbol": "BTC-USDT-SWAP",
    "tradeType": "spot",
    "leverage": 1,
    "positionSize": 0,
    "stopLoss": 82100,
    "takeProfit": 78500,
    "confidence": 65,
    "edgeScore": -10,
    "analysisBasis": {
      "a1Summary": "宏观CPI 3.8%超预期，费率从负转正...",
      "a2Summary": "核心矛盾C1宏观vs技术，阻力最小方向区间...",
      "a3Summary": "区间50%/向下20%/向上18%...",
      "a4Summary": "验证结果：区间持续，建议观望...",
      "scenarioProbs": { "upside": 0.18, "downside": 0.20, "range": 0.50 }
    },
    "executionFrequency": "1d",
    "artifactIds": ["a1_research_20260513", "a2_first_principles_20260513"],
    "generatedAt": "2026-05-13T12:00:00+08:00",
    "isRead": false,
    "isApplied": false
  }
}
```

### 7.3 创建自定义策略(信号策略)

```
POST /api/config/strategies/custom

Body:
{
  "rawInput": "RSI低于30并且MACD金叉的时候做多",
  "symbol": "BTC-USDT-SWAP",
  "uid": "user_001"
}

注意: 用户输入自然语言，后端IntentParser自动解析为signalConditions。
不再需要前端传递结构化的signalConditions数组。

Response: SSE流式 (见 §5.3)
```

### 7.4 应用策略

```
POST /api/config/strategies/:id/apply

Body:
{
  "uid": "user_001",
  "exchangeConfigId": "okx_main",
  "executionFrequency": "4h"
}

Response 200:
{
  "success": true,
  "taskId": "task_20260513_001",
  "strategyId": "rec_20260513_001",
  "nextExecutionAt": "2026-05-13T16:00:00+08:00",
  "adaptations": [                       // 策略适配情况
    { "field": "leverage", "original": 3, "adapted": 2, "reason": "用户杠杆上限为2x" }
  ],
  "message": "策略已应用，将按4h频率自动执行"
}

Response 400 (前置条件未满足):
{
  "success": false,
  "reason": "API_NOT_CONFIGURED",
  "message": "请先完成API配置并验证连接",
  "missing": ["api_config", "trading_params"]
}
```

### 7.5 取消应用策略

```
POST /api/config/strategies/:id/unapply

Body:
{
  "uid": "user_001",
  "reason": "用户主动取消"
}

Response 200:
{
  "success": true,
  "taskId": "task_20260513_001",
  "status": "paused",
  "message": "策略已取消应用，相关定时任务已暂停"
}
```

### 7.6 标记策略已读

```
POST /api/config/strategies/:id/read

Response 200:
{ "success": true, "isRead": true }
```

### 7.7 删除策略

```
DELETE /api/config/strategies/:id

Response 200:
{
  "success": true,
  "cancelledTask": true,
  "message": "策略已删除，相关定时任务已取消"
}
```

### 7.8 获取执行任务列表

```
GET /api/config/strategies/tasks?uid=user_001

Response 200:
{
  "tasks": [
    {
      "id": "task_20260513_001",
      "strategyId": "rec_20260513_001",
      "strategyName": "区间震荡-观望防守策略",
      "executionFrequency": "4h",
      "status": "active",
      "nextExecutionAt": "2026-05-13T16:00:00+08:00",
      "executionCount": 3,
      "tradeCount": 1,
      "lastExecutionAt": "2026-05-13T12:00:00+08:00"
    }
  ]
}
```

### 7.9 手动执行策略

```
POST /api/config/strategies/tasks/:taskId/execute

Body:
{ "uid": "user_001" }

Response 200:
{
  "success": true,
  "conditionMatch": true,
  "gateResult": "passed",
  "tradeExecuted": true,
  "tradeDirection": "BUY",
  "tradeAmount": 500,
  "message": "策略手动执行成功"
}
```

---

## 8. 策略存储

### 8.1 存储文件

```
~/.workbuddy/config/
├── strategies.json           # 策略列表(推荐+自定义)
├── strategy-tasks.json       # 定时任务列表
└── strategy-executions.json  # 执行历史记录
```

### 8.2 策略列表示例

```json
{
  "version": "1.0",
  "updatedAt": "2026-05-13T14:00:00+08:00",
  "recommendedStrategies": [
    {
      "id": "rec_20260513_001",
      "type": "recommended",
      "source": "A4",
      "name": "区间震荡-观望防守策略",
      "description": "当前RANGE_BOUND格局下，建议观望防守...",
      "regime": "RANGE_BOUND",
      "direction": "SKIP",
      "symbol": "BTC-USDT-SWAP",
      "tradeType": "spot",
      "leverage": 1,
      "positionSize": 0,
      "stopLoss": 82100,
      "takeProfit": 78500,
      "stopLossPercent": 1.8,
      "takeProfitPercent": 2.6,
      "confidence": 65,
      "edgeScore": -10,
      "analysisBasis": {
        "a1Summary": "宏观CPI 3.8%超预期...",
        "a2Summary": "核心矛盾C1宏观vs技术...",
        "a3Summary": "区间50%/向下20%/向上18%...",
        "a4Summary": "验证结果：区间持续...",
        "scenarioProbs": { "upside": 0.18, "downside": 0.20, "range": 0.50 }
      },
      "executionFrequency": "1d",
      "artifactIds": ["a1_research_20260513"],
      "generatedAt": "2026-05-13T12:00:00+08:00",
      "isRead": false,
      "isApplied": false
    }
  ],
  "customStrategies": []
}
```

---

## 9. 前端组件设计

### 9.1 SettingsStrategy 组件树

```
SettingsStrategy
├── StrategyHeader
│   ├── StrategyCountBadge (推荐: 3 | 自定义: 1)
│   └── StrategyRefreshButton [刷新策略]
│
├── RecommendedStrategySection
│   ├── SectionHeader ("📋 推荐策略")
│   │   └── UpdateInfo ("A4最新推送: 12:00")
│   │
│   ├── RecommendedStrategyCard (策略1)
│   │   ├── StrategyBadge ("SKIP" | "BUY" | "SHORT")
│   │   ├── StrategyName ("区间震荡-观望防守策略")
│   │   ├── StrategyMeta ("RANGE_BOUND | 置信度65% | Edge -10")
│   │   ├── StrategyFrequency ("推荐频率: 1d")
│   │   ├── StrategyNewBadge [新] (isRead=false时显示)
│   │   ├── StrategyExpandButton [查看详情]
│   │   │   └── StrategyDetailPanel
│   │   │       ├── AnalysisBasisSection (A1-A4分析依据)
│   │   │       ├── ScenarioProbsChart (情景概率饼图)
│   │   │       ├── TradeParamsDisplay (推荐交易参数)
│   │   │       └── ArtifactLinks (关联产物链接)
│   │   └── StrategyApplyButton [应用此策略]
│   │
│   ├── RecommendedStrategyCard (策略2) ...
│   └── EmptyState ("暂无推荐策略，A4定时任务执行后将自动推送")
│
├── CustomStrategySection
│   ├── SectionHeader ("✏️ 信号策略")
│   │
│   ├── NaturalLanguageInput (v1.2: 替代SignalConditionBuilder)
│   │   ├── StrategyTextArea (自然语言输入框)
│   │   │   placeholder: "描述你的策略，如：RSI低于30并且MACD金叉时做多"
│   │   │   └── InputExamples (输入示例按钮组)
│   │   │       · "RSI超卖反弹"
│   │   │       · "均线金叉做多"
│   │   │       · "布林带回归"
│   │   │       · "放量突破"
│   │   ├── IntentPreview (意图识别预览面板)
│   │   │   ├── ParsedDirectionBadge ("方向: 做多 ✅")
│   │   │   ├── ParsedConditionsList (解析出的条件列表)
│   │   │   │   └── ParsedConditionItem (每个解析出的指标条件)
│   │   │   │       · "RSI 低于 30 [AND]" ← sourceText+解析结果
│   │   │   │       · "MACD 上穿信号线 [AND]"
│   │   │   ├── ParsedConfidenceBar (意图识别置信度条)
│   │   │   └── EditParsedButton [修正解析] ← 打开条件微调弹窗
│   │   ├── TemplateMatchBadge (策略库匹配度: 85%)
│   │   └── GenerateButton [生成信号策略]
│   │
│   ├── CustomStrategyCard (策略1)
│   │   ├── StrategyName ("RSI超卖+MACD金叉做多策略")
│   │   ├── SignalSummary ("RSI<30 ∧ MACD金叉 | 4h框架")
│   │   ├── StrategyStatus (draft/parsing/matching/analyzing/backtesting/approved/applied)
│   │   ├── BacktestBadge (v1.2: "回测: 通过 ✅ 胜率61.7%") ← NEW
│   │   ├── TuningBadge ("A系列调优: 2条建议")
│   │   ├── StrategyPreviewButton [查看策略]
│   │   │   └── StrategyPreviewPanel
│   │   │       ├── FullStrategyReport (完整策略报告)
│   │   │       ├── BacktestResultPanel (v1.2: 回测结果详情) ← NEW
│   │   │       │   ├── BacktestMetrics (胜率/回撤/夏普/盈亏比)
│   │   │       │   └── BacktestChart (收益曲线图)
│   │   │       ├── SignalParamsDisplay (信号参数+调优建议)
│   │   │       ├── TradeParamsDisplay (推荐交易参数)
│   │   │       ├── FrequencySelect (1h/4h/1d选择)
│   │   │       ├── DownloadButton [下载.md] [下载.json]
│   │   │       └── ConfirmApplyButton [确认应用]
│   │   └── StrategyDeleteButton [删除]
│   │
│   └── EmptyState ("用自然语言描述你的策略，AI将自动解析、匹配策略库并回测验证")
│
└── ActiveStrategySection
    ├── SectionHeader ("⚡ 运行中的策略")
    │
    ├── ActiveStrategyCard
    │   ├── StrategyName ("区间震荡-观望防守策略")
    │   ├── ExecutionFrequency ("执行频率: 4h")
    │   ├── NextExecutionAt ("下次执行: 16:00")
    │   ├── ExecutionStats ("已执行3次 | 交易1次 | 跳过2次")
    │   ├── PauseResumeButton [暂停/恢复]
    │   └── UnapplyButton [取消应用]
    │
    └── EmptyState ("暂无运行中的策略，应用策略后将显示在此")
```

### 9.2 策略生成进度展示

当自定义信号策略正在生成时，在对话中展示：

```
┌──────────────────────────────────────┐
│ 🤖 AI助手                            │
│                                      │
│ 🔄 正在生成信号策略                    │
│                                      │
│ 💬 你的意图: RSI低于30并且MACD金叉    │
│    → 解析为: RSI<30 ∧ MACD金叉 | 做多│
│    → 置信度: 92%                     │
│ 📋 策略库匹配: 85% (RSI超卖模板)     │
│                                      │
│ ✓ 信号指标市场环境侦察完成             │  ← A1
│   · RSI当前28，接近超卖区间           │
│ ✓ 信号有效性分析完成                   │  ← A2
│ ⠋ 正在推演信号触发情景...             │  ← A3
│ ⏳ 信号策略验证                        │  ← A4
│ ⏳ 历史回测验证                        │  ← Backtester ⭐NEW
│                                      │
│ 预计完成: ~3分钟                      │
└──────────────────────────────────────┘
```

生成完成后：

```
┌──────────────────────────────────────┐
│ 🤖 AI助手                            │
│                                      │
│ ✅ 信号策略已生成！                    │
│                                      │
│ 📋 RSI超卖+MACD金叉做多策略           │
│ ────────────────────────────────     │
│ 💬 原始输入: RSI低于30并且MACD金叉    │
│    → 解析: RSI<30 ∧ MACD金叉 | 做多  │
│ 信号框架: 4h                          │
│                                      │
│ 方向: 做多                            │
│ 品种: BTC-USDT-SWAP                   │
│ 杠杆: 2x | 仓位: 0.3x               │
│ 置信度: 62% | 优势评分: +15          │
│ 止损: $79,200 | 止盈: $83,500         │
│                                      │
│ 情景概率:                             │
│   上涨 35% | 区间 40% | 下跌 25%     │
│                                      │
│ 🔧 A系列调优建议:                     │
│   · RSI阈值建议从30→28，胜率提升5%   │
│   · MACD快线建议12→8，减少滞后       │
│                                      │
│ 📊 回测结果 ⭐NEW:                    │
│   回测区间: 2025-01 ~ 2026-05        │
│   胜率: 61.7% ✅ | 回撤: 12.3% ✅    │
│   夏普: 1.42 ✅ | 盈亏比: 1.68 ✅    │
│   信号触发47次 | 净收益+23.5%        │
│   💡 技术指标不易漂移，定时执行效果优  │
│                                      │
│ 推荐执行频率: 4h                     │
│                                      │
│ [查看完整报告] [确认应用] [存为草稿]  │
│ [下载.md] [下载.json]                │
└──────────────────────────────────────┘
```

---

## 10. SSE事件扩展

### 10.1 策略相关SSE事件

```typescript
type StrategySSEEvent =
  // 意图识别完成 (v1.2新增)
  | {
      type: 'intent_parsed';
      strategyId: string;
      rawInput: string;                  // 用户原始输入
      direction?: 'BUY' | 'SHORT' | 'SKIP';
      signalConditions: ParsedCondition[];  // 解析出的条件
      signalLogic: 'AND' | 'OR';
      confidence: number;                // 识别置信度 0-100
    }

  // 推荐策略更新
  | {
      type: 'strategy_update';
      strategyId: string;
      strategyType: 'recommended';
      strategyName: string;
      direction: 'BUY' | 'SHORT' | 'SKIP';
      confidence: number;
    }

  // 自定义策略-策略库匹配结果
  | {
      type: 'strategy_matching';
      strategyId: string;
      templateId?: string;
      templateName?: string;
      matchScore: number;              // 0-100
    }

  // 自定义策略生成进度
  | {
      type: 'strategy_generating';
      strategyId: string;
      phase: 'research' | 'analysis' | 'simulation' | 'validation' | 'backtesting';
      progress: number;             // 0-1
    }

  // 回测结果 (v1.2新增)
  | {
      type: 'backtest_result';
      strategyId: string;
      status: 'passed' | 'failed' | 'reoptimizing';
      winRate: number;
      maxDrawdown: number;
      sharpeRatio: number;
      profitFactor: number;
      netProfit: number;
      totalSignals: number;
      period: string;
      reoptimizeCount: number;       // 二次调优次数
    }

  // 自定义策略生成完成
  | {
      type: 'strategy_generated';
      strategyId: string;
      strategyName: string;
      direction: 'BUY' | 'SHORT' | 'SKIP';
      confidence: number;
      backtestPassed: boolean;       // v1.2: 回测是否通过
      tuningSuggestions?: string[];
    }

  // 策略执行结果
  | {
      type: 'strategy_executed';
      taskId: string;
      strategyId: string;
      result: 'traded' | 'skipped' | 'blocked';
      detail: string;
    };
```

---

## 11. 与其他模块的集成

### 11.1 与TRADING_CONFIG的关系

```
STRATEGY_CONFIG (业务层)            TRADING_CONFIG (约束层)
┌─────────────────────────┐      ┌─────────────────────────┐
│ Strategy                 │─────►│ TradingGate               │
│ · 策略推荐杠杆/仓位     │      │ · 校验策略参数在边界内    │
│ · 策略推荐方向          │      │ · 越界降级               │
│ · 策略执行频率          │      │ · 日/账户亏损检查         │
└─────────────────────────┘      └─────────────────────────┘

策略应用时:
  策略参数 → adaptStrategyToParams() → TradingGate门禁 → 通过/降级/拦截
```

### 11.2 与API_CONFIG的关系

```
STRATEGY_CONFIG (业务层)            API_CONFIG (连接层)
┌─────────────────────────┐      ┌─────────────────────────┐
│ 策略应用 → 需要交易所API │─────►│ ExchangeAPIConfig        │
│ · 定时任务需要API连接    │      │ · 提供交易执行通道       │
│ · 无API → 策略无法执行   │      │ · 环境校验(demo/live)   │
└─────────────────────────┘      └─────────────────────────┘
```

### 11.3 与CHANNEL的关系

```
STRATEGY_CONFIG (业务层)            CHANNEL (通知层)
┌─────────────────────────┐      ┌─────────────────────────┐
│ 策略推荐更新             │─────►│ 推送"新策略推荐"通知    │
│ 策略已应用               │─────►│ 推送"策略已应用"通知    │
│ 策略执行结果             │─────►│ 推送执行结果            │
│ 策略条件不匹配           │─────►│ 推送"策略跳过"通知     │
└─────────────────────────┘      └─────────────────────────┘
```

### 11.4 与CHAIN_ORCHESTRATOR的关系

```
STRATEGY_CONFIG (策略层)            CHAIN_ORCHESTRATOR (执行层)
┌─────────────────────────┐      ┌─────────────────────────┐
│ 推荐策略 ← A4验证产出   │◄────│ A4 Skill               │
│ 自定义策略 → 触发A系列  │────►│ A1→A2→A3→A4 执行       │
│ 策略应用 → 定时任务执行 │────►│ ChainExecutor 调度      │
└─────────────────────────┘      └─────────────────────────┘
```

### 11.5 与INTENT_ROUTER的关系

```
INTENT_ROUTER (路由层)              STRATEGY_CONFIG (策略层)
┌─────────────────────────┐      ┌─────────────────────────┐
│ 用户输入关键词           │─────►│ 触发自定义策略生成      │
│ 意图识别: strategy_custom│      │ · 路由到A系列调研       │
│ 意图识别: strategy_view │      │ · 展示策略列表          │
│ 意图识别: strategy_apply │      │ · 应用策略              │
└─────────────────────────┘      └─────────────────────────┘
```

### 11.7 与CREDITS(积分体系)的关系

```
STRATEGY_CONFIG (业务层)            CREDITS (积分体系)
┌─────────────────────────┐      ┌─────────────────────────┐
│ 策略执行                 │─────►│ 积分扣除                │
│ · 策略执行前检查积分余额 │      │ · 余额不足 → 策略暂停   │
│ · 执行频率影响积分消耗   │      │ · 充值后 → 策略自动恢复  │
│ · 深度分析报告消耗积分   │      │ · 积分变动 → 推送通知   │
└─────────────────────────┘      └─────────────────────────┘

策略执行积分扣费:
  执行前: 检查 credits_balance >= cost_per_execution
  通过:   扣费 → 执行策略 → 记录流水
  不足:   暂停策略 → 推送积分不足通知 → 等待充值恢复
```

**积分Schema**:

```typescript
interface CreditsAccount {
  uid: string;                          // 用户ID
  balance: number;                     // 可用积分余额
  totalEarned: number;                 // 累计获得
  totalSpent: number;                  // 累计消耗
  pendingCredits: number;              // 待生效积分
  expiringCredits: {                   // 即将过期积分
    amount: number;
    expiresAt: string;                // 过期时间
  }[];
}

interface CreditsTransaction {
  id: string;                          // 交易ID
  uid: string;                         // 用户ID
  type: 'earn' | 'spend';             // 收入/支出
  category: string;                    // 分类: recharge/signin/referral/bonus/strategy_execution/analysis_report
  amount: number;                      // 变动数量(正数)
  balance_after: number;              // 变动后余额
  description: string;                // 描述: "策略执行 - RSI超卖+MACD金叉 4h"
  relatedId?: string;                  // 关联ID: 策略ID/订单ID
  expiresAt?: string;                 // 过期时间(赠送积分)
  createdAt: string;                  // 交易时间
}

interface CreditsPackage {
  id: string;                          // 套餐ID: "pkg_starter"
  name: string;                        // 套餐名称: "体验套餐"
  credits: number;                     // 积分数: 1000
  bonus: number;                       // 赠送数: 0
  price: number;                       // 价格(¥): 9.9
  unitPrice: number;                   // 单价(¥/积分): 0.0099
  tag?: string;                        // 标签: "🔥 热门" | "⭐ 推荐"
  isActive: boolean;                   // 是否上架
}

// 策略执行积分消耗配置
interface StrategyExecutionCost {
  executionFrequency: '1h' | '4h' | '1d';
  costPerExecution: number;            // 每次执行消耗积分
  // 1h: 200 | 4h: 80 | 1d: 120
}

// 分析报告积分消耗配置
interface AnalysisCost {
  analysisType: string;                // 分析类型
  costPerAnalysis: number;             // 每次消耗积分
  // deep_analysis: 150 | intel_brief: 50
}
```

**积分扣费流程**:

```
策略定时触发
      │
      ▼
┌──────────────────────────────────────┐
│  Step 1: 积分余额检查                 │
│  · 查询用户积分余额                   │
│  · 判断是否 ≥ 执行消耗               │
│  · 余额充足 → 继续                   │
│  · 余额不足 → 暂停策略+推送通知      │
└──────────┬───────────────────────────┘
           │ 余额充足
           ▼
┌──────────────────────────────────────┐
│  Step 2: 预扣积分                     │
│  · 扣除对应频率的积分                  │
│  · 写入积分流水(strategy_execution)   │
│  · 关联策略ID和执行任务ID             │
└──────────┬───────────────────────────┘
           │ 扣费成功
           ▼
┌──────────────────────────────────────┐
│  Step 3: 执行策略                     │
│  · TradingGate门禁校验               │
│  · 条件匹配 → 交易执行               │
│  · 条件不匹配 → 跳过(积分已扣不退)    │
└──────────────────────────────────────┘
```

**积分不足恢复流程**:

```
积分不足 → 策略自动暂停 → 用户充值 → 积分到账 → 策略自动恢复
                                              │
                                              ▼
                                   推送通知: "策略已恢复运行"
```

### 11.6 模块关系全图

```
┌───────────────────┐     exchangeConfigId     ┌───────────────────┐
│ API_CONFIG        │◄─────────────────────────│ TRADING_CONFIG    │
│ · 连接凭证        │                          │ · 交易行为约束    │
│ · 密钥加密存储    │                          │ · 下单门禁        │
└───────┬───────────┘                          └─────────┬─────────┘
        │                                                │
        │ 策略应用需API                                  │ 策略参数需过门禁
        │                                                │
┌───────▼───────────┐                          ┌─────────▼─────────┐
│ STRATEGY_CONFIG   │──────────────────────────►│ CHANNEL            │
│ · 推荐策略(A4推送) │   策略事件通知           │ · 策略更新推送     │
│ · 自定义策略(A系列)│                          │ · 执行结果推送     │
│ · 定时任务执行     │                          │ · 条件不匹配通知   │
└───────────────────┘                          └───────────────────┘

四大独立模块: API配置(连接) / 交易参数(约束) / 策略设置(业务) / 通信渠道(通知)
策略执行需要API+交易参数同时就绪，通信渠道可选。

补充模块:
┌───────────────────┐
│ CREDITS (积分体系)  │
│ · 策略执行扣费      │
│ · 积分余额检查      │
│ · 不足自动暂停策略  │
│ · 充值后自动恢复    │
└─────────┬─────────┘
          │ 策略执行前扣费
          │ 余额不足 → 暂停
          ▼
   STRATEGY_CONFIG
```

---

## 12. 安全设计

### 12.1 策略执行安全

| 措施 | 说明 |
|------|------|
| 前置条件检查 | 应用策略前必须验证API配置和交易参数 |
| 积分余额检查 | 策略执行前必须验证积分余额充足 |
| 门禁必过 | 策略执行下单必须通过TradingGate |
| 参数降级 | 策略参数超出用户边界时自动降级 |
| 执行频率限制 | 最高1h，防止过度交易 |
| 单策略单任务 | 同一策略只能有一个活跃定时任务 |
| 手动暂停 | 用户可随时暂停/取消策略应用 |

### 12.2 审计追踪

| 事件 | 记录内容 |
|------|----------|
| 策略生成 | 时间+类型+关键词+A系列依据 |
| 策略应用 | 时间+UID+策略ID+适配情况 |
| 策略执行 | 时间+UID+条件匹配+门禁结果+交易结果+积分扣费 |
| 策略取消 | 时间+UID+原因 |
| 策略删除 | 时间+UID+策略ID |
| 积分扣费 | 时间+UID+策略ID+扣费金额+扣费后余额 |
| 积分充值 | 时间+UID+套餐+支付金额+到账积分 |

---

## 13. 当前约束与扩展路径

### 13.1 v1.0 约束

| 维度 | 约束 | 说明 |
|------|------|------|
| 品种 | 仅BTC | 后期扩展ETH/SOL等 |
| 策略来源 | A4推荐+自然语言意图识别→技术指标信号 | 后期支持策略市场 |
| 输入方式 | 自然语言+意图识别 | v1.2: 替代结构化选择器 |
| 回测 | 自动化执行前必过回测 | v1.2: 胜率≥45%回撤≤20%PF≥1.2 |
| 执行频率 | 1h/4h/1d三档 | 后期支持自定义频率 |
| 并发策略 | 1个活跃策略 | 后期支持多策略并行 |
| 策略有效期 | 7天自动过期 | 后期支持自定义有效期 |
| 积分体系 | 策略执行/分析消耗积分，不足暂停 | v1.2: 积分体系与策略执行联动 |

### 13.2 扩展路径

```
v1.0 (当前)              v1.5                v2.0
─────────────────────────────────────────────────────
BTC only          →  BTC + ETH       →  多品种
A4推荐+技术指标信号  →  +策略模板库     →  策略市场
1h/4h/1d频率      →  +自定义频率     →  AI自适应频率
单策略运行        →  多策略(优先级)  →  策略组合/组合回测
7天过期           →  自定义有效期    →  自动续期+衰退检测
积分扣费          →  +订阅制        →  积分+订阅双轨制
```
