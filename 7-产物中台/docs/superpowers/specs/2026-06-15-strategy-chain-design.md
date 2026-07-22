# 策略思维链设计方案

**版本**: v1.0
**日期**: 2026-06-15
**状态**: 已确认
**负责人**: AI助手

---

## 1. 背景与目标

### 1.1 问题背景

现有系统采用D-Z-E（调研-实施-执行）三链模式，这是为开发和治理场景设计的思维链。对于前端用户的金融策略分析需求，D-Z-E链过于复杂且不契合。

### 1.2 目标

为前端用户设计一套轻量级、步进式的**S系列策略思维链**，专门用于：
- 金融交易策略分析
- 市场研究与调研
- 策略设计、验证与执行跟踪

### 1.3 设计原则

- **用户导向**：符合交易员的思维习惯
- **渐进式复杂度**：根据问题复杂度自动调整步数
- **步进确认**：每步需要用户确认，确保用户掌控
- **可扩展性**：未来可扩展为星型协作模式

---

## 2. 架构设计

### 2.1 S系列思维链定义

```
S1_调研 → S2_分析 → S3_设计 → S4_验证 → S5_执行/跟踪
```

| 步骤 | 名称 | 英文 | 职责 | 输出 |
|------|------|------|------|------|
| S1 | 调研 | Research | 市场数据、行情、技术指标、新闻收集 | 市场现状摘要、支持阻力位、情绪指标 |
| S2 | 分析 | Analysis | 多维度分析（技术面、基本面、情绪面） | 趋势判断、关键价位、风险因素 |
| S3 | 设计 | Design | 制定具体策略（入场点、止损、止盈、仓位） | 完整策略方案、情景推演 |
| S4 | 验证 | Validate | 回测验证、风险评估、模拟推演 | 胜率、回撤、夏普比率、最坏情景 |
| S5 | 执行 | Execute | 生成执行计划、跟踪调整 | 执行清单、跟踪提醒 |

### 2.2 复杂度分级

| 模式 | 启用条件 | 步数 | 确认节点 |
|------|----------|------|----------|
| 快速模式 | 简单查询/信号判断 | S1或S2 | 可选 |
| 标准模式 | 常规策略分析 | S1→S2→S3 | 每步确认 |
| 深度模式 | 复杂研究/重大决策 | S1→S2→S3→S4→S5 | 每步确认 |

### 2.3 与现有系统的关系

```
┌─────────────────────────────────────────────────────┐
│                    智能路由引擎                      │
│                  Smart Router                       │
└─────────────────────────────────────────────────────┘
                          │
        ┌─────────────────┼─────────────────┐
        ↓                 ↓                 ↓
┌───────────────┐ ┌───────────────┐ ┌───────────────┐
│   D-Z-E链     │ │   S系列链     │ │   A系列链     │
│  (开发治理)   │ │  (策略分析)   │ │  (快速交易)   │
│               │ │               │ │               │
│ D1→D4        │ │ S1→S5        │ │ A1→A5        │
│ Z1→Z4        │ │               │ │               │
│ E1→E3        │ │               │ │               │
└───────────────┘ └───────────────┘ └───────────────┘
```

- **D-Z-E链**：保留不变，用于开发/治理场景
- **S系列链**：新增，专门用于策略分析
- **A系列链**：保留，用于快速交易辅助

---

## 3. 类型定义

### 3.1 核心类型

```typescript
// 步骤状态
export type StrategyStepStatus = "pending" | "active" | "done" | "skipped";

// 步骤定义
export const STRATEGY_STEPS = [
  { number: 1 as const, id: "S1_RESEARCH", name: "调研", icon: "🔍" },
  { number: 2 as const, id: "S2_ANALYSIS", name: "分析", icon: "🧠" },
  { number: 3 as const, id: "S3_DESIGN", name: "设计", icon: "🎯" },
  { number: 4 as const, id: "S4_VALIDATE", name: "验证", icon: "✅" },
  { number: 5 as const, id: "S5_EXECUTE", name: "执行", icon: "⚡" },
] as const;

// 单步记录
export interface StrategyStep {
  id: string;
  number: 1 | 2 | 3 | 4 | 5;
  name: string;
  icon: string;
  status: StrategyStepStatus;
  output: string;
  artifacts: string[];
  notes: string;
  startedAt?: string;
  completedAt?: string;
}

// 策略链状态
export interface StrategyChainState {
  scope: string;
  currentStep: string | null;
  steps: StrategyStep[];
  createdAt: string;
  modifiedAt: string;
}

// 复杂度模式
export type StrategyComplexity = "quick" | "standard" | "deep";

// 策略任务
export interface StrategyTask {
  id: string;
  sessionId: string;
  title: string;
  intent: IntentType;
  userInput: string;
  complexity: StrategyComplexity;
  chainState: StrategyChainState;
  entities: Record<string, string>;
  credits: { estimated: number; used: number };
}
```

---

## 4. 路由设计

### 4.1 意图识别与路由映射

```typescript
const STRATEGY_ROUTE_MAP: Record<IntentType, RouteConfig> = {
  // 简单查询 → 快速模式
  market_query: {
    complexity: "quick",
    steps: ["S1_RESEARCH"],
    requiresConfirmation: false,
  },

  // 深度分析 → 标准/深度模式
  deep_analysis: {
    complexity: "standard",
    steps: ["S1_RESEARCH", "S2_ANALYSIS", "S3_DESIGN"],
    requiresConfirmation: true,
  },

  // 情景模拟 → 深度模式
  scenario_sim: {
    complexity: "deep",
    steps: ["S1_RESEARCH", "S2_ANALYSIS", "S3_DESIGN", "S4_VALIDATE"],
    requiresConfirmation: true,
  },

  // 策略验证 → 标准模式
  strategy_verify: {
    complexity: "standard",
    steps: ["S2_ANALYSIS", "S3_DESIGN", "S4_VALIDATE"],
    requiresConfirmation: true,
  },

  // 执行交易 → 深度模式
  execute_trade: {
    complexity: "deep",
    steps: ["S1_RESEARCH", "S2_ANALYSIS", "S3_DESIGN", "S4_VALIDATE", "S5_EXECUTE"],
    requiresConfirmation: true,
  },
};
```

### 4.2 命令路由

```typescript
const STRATEGY_COMMAND_ROUTE_MAP: Record<string, CommandConfig> = {
  "/行情": { intent: "market_query", steps: ["S1_RESEARCH"] },
  "/分析": { intent: "deep_analysis", steps: ["S1_RESEARCH", "S2_ANALYSIS", "S3_DESIGN"] },
  "/推演": { intent: "scenario_sim", steps: ["S1_RESEARCH", "S2_ANALYSIS", "S3_DESIGN", "S4_VALIDATE"] },
  "/验证": { intent: "strategy_verify", steps: ["S2_ANALYSIS", "S3_DESIGN", "S4_VALIDATE"] },
  "/开仓": { intent: "execute_trade", steps: ["S1_RESEARCH", "S2_ANALYSIS", "S3_DESIGN", "S4_VALIDATE", "S5_EXECUTE"] },
};
```

---

## 5. 步进控制器

### 5.1 状态机

```
                    ┌──────────────┐
                    │   pending    │
                    └──────────────┘
                           │
                           ↓ 用户发起
                    ┌──────────────┐
              ────→ │   active     │ ←──────┐
                    └──────────────┘        │
                           │               │
                           │ 完成/确认     │ 暂停/修改
                           ↓               │
                    ┌──────────────┐        │
                    │    done      │ ───────┘
                    └──────────────┘
                           │
                           │ 跳过
                           ↓
                    ┌──────────────┐
                    │   skipped    │
                    └──────────────┘
```

### 5.2 用户决策

每步完成后，用户可选择：
- **继续(Continue)**：进入下一步
- **跳过(Skip)**：跳过当前步，进入下下一步
- **暂停(Pause)**：暂停，稍后继续
- **修改(Modify)**：返回修改当前步输出

---

## 6. 文件结构

```
src/lib/strategy/
├── types.ts              # S系列类型定义
├── route.ts              # 策略路由引擎
├── steps/
│   ├── research.ts       # S1_调研
│   ├── analysis.ts        # S2_分析
│   ├── design.ts          # S3_设计
│   ├── validate.ts        # S4_验证
│   └── execute.ts         # S5_执行
├── chain-controller.ts   # 链状态机控制器
└── index.ts              # 导出入口
```

---

## 7. 实现计划

### 7.1 Phase 1: 核心基础设施
- [ ] 创建 `src/lib/strategy/types.ts`
- [ ] 创建 `src/lib/strategy/route.ts`
- [ ] 更新 `smart-router.ts` 集成S系列路由

### 7.2 Phase 2: 步骤实现
- [ ] 实现 S1_调研
- [ ] 实现 S2_分析
- [ ] 实现 S3_设计
- [ ] 实现 S4_验证
- [ ] 实现 S5_执行

### 7.3 Phase 3: 控制器与集成
- [ ] 实现链状态机控制器
- [ ] 集成到 chat API
- [ ] 更新前端notebook界面

### 7.4 Phase 4: 测试与优化
- [ ] 单元测试
- [ ] 集成测试
- [ ] 用户体验优化

---

## 8. 参考项目

- **TradingAgents** (TauricResearch/TradingAgents)
  - 多Agent量化交易框架
  - UCLA+MIT研究团队开发
  - Apache-2.0开源协议
  - 86K+ GitHub Stars

---

## 9. 变更日志

| 日期 | 版本 | 变更内容 |
|------|------|----------|
| 2026-06-15 | v1.0 | 初始版本 |

