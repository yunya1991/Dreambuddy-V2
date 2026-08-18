# DreamBuddy v3 前端重构综合技术文档

> 版本: v3.0 | 日期: 2026-07-05 | 状态: 架构规划
> 定位: WorkBuddy OS SACG 四层架构前端对齐方案
> 约束: 新端口 3001 独立运行，不改动现有 v2 前端代码

---

## 第一章：项目概述与目标

### 1.1 项目定位

DreamBuddy v3 前端是 AI 驱动的加密货币交易平台的全量重构版本。它不仅仅是一个 UI 重写，更是将前端架构从"以页面为中心的 God Component 模式"彻底转向"以 SACG 四层架构为骨架的领域驱动前端模式"。v3 前端以 WorkBuddy OS 的 SACG (Sense-Arrange-Compute-Graph) 模型作为顶层设计约束，确保每一个页面、每一个组件、每一条数据流都能在 SACG 模型中找到清晰的位置。

核心定位公式:

```
v3 Frontend = SACG 四层可视化 + 双交易模式 UI + 三屏交易系统 + SSE 流式交互
```

### 1.2 核心目标

| 编号 | 目标 | 对齐维度 | 验收标准 |
|------|------|----------|----------|
| G1 | SACG 架构完全对齐 | 全局 | 四层各有独立可视化面板，层间数据流可追踪 |
| G2 | 消除 God Component | 架构 | 单文件不超过 300 行，最大组件不超过 5 个 useState |
| G3 | 单一职责状态管理 | Store | 10 个 Zustand store 各管各的领域，无跨域耦合 |
| G4 | 端口隔离部署 | 运维 | v2 跑在 3000，v3 跑在 3001，共享同一套 API Routes |
| G5 | 模块化 API 集成 | 集成 | 19 个 API 域各自封装，统一错误处理，SSE 标准化 |
| G6 | 双交易模式支持 | 业务 | AI Skill + Classic 两种模式各自有完整 UI 链路 |
| G7 | 三屏交易系统独立页面 | 业务 | Elder 三屏交易作为独立应用层页面，Screen1/2/3 各自独立面板 + 数据联动 + 方向约束链路可视化 |
| G8 | 零新增依赖 | 约束 | 不使用 lucide-react，不安装新 npm 包，纯文件操作迁移 |

### 1.3 技术栈选型与约束

| 维度 | 选型 | 约束说明 |
|------|------|----------|
| 框架 | Next.js 15.5 (App Router) | 使用 `src/app/` 目录结构，Server Component + Client Component 混合渲染 |
| 样式 | Tailwind CSS v4 (`@tailwindcss/postcss`) | 无 `tailwind.config.js`，通过 CSS `@theme` 定义设计 token |
| 语言 | TypeScript (strict) | 所有组件、store、工具函数均为 `.ts`/`.tsx` |
| 状态管理 | Zustand | 轻量级，与 v2 现有 stores 架构一致，按领域拆分 |
| 流式通信 | SSE (Server-Sent Events) | 9 种事件类型标准化处理 |
| 图标 | Inline SVG | 不使用 lucide-react 或其他图标库 |
| 数据可视化 | CSS + SVG | 不引入 chart.js / recharts，用原生 SVG 绘图 |
| 依赖管理 | 无 npm/pnpm 安装能力 | 所有新模块通过纯文件复制创建 |
| 认证 | NextAuth.js v5 (Session) | 复用 v2 的 auth 配置和 middleware |

### 1.4 新端口隔离策略

```
v2 Frontend (PORT 3000)          v3 Frontend (PORT 3001)
┌─────────────────────────┐      ┌─────────────────────────┐
│ src/app/                │      │ src/app/v3/             │
│ ├── dashboard/          │      │ ├── dashboard/          │
│ ├── chat/               │      │ │   ├── trade/          │
│ ├── login/              │      │ │   ├── classic/        │
│ └── api/ (shared)       │      │ │   ├── fundamental/    │
│                         │      │ │   ├── monitor/        │
│                         │      │ │   ├── memory/         │
│                         │      │ │   ├── settings/       │
│                         │      │ │   ├── reports/        │
│                         │      │ │   └── governance/     │
└─────────────────────────┘      │ ├── layout.tsx (独立)   │
         │                       │ └── page.tsx            │
         │                       └─────────────────────────┘
         │                                   │
         └─────── 共享 API Routes ───────────┘
              (src/app/api/* 不变)
```

隔离策略要点:

1. **路由隔离**: v3 所有页面放在 `src/app/v3/` 目录下，通过 `/v3/dashboard` 等路径访问
2. **布局隔离**: v3 拥有独立的 `layout.tsx`，不继承 v2 的 layout
3. **API 共享**: 92 个 API 端点完全复用，v3 只需做前端 Client 层封装
4. **Store 隔离**: v3 在 `src/stores/v3/` 下创建新 store，不修改 v2 的 `src/stores/`
5. **组件隔离**: v3 组件放在 `src/components/v3/` 下，不改动 v2 组件
6. **启动隔离**: 通过 `next dev -p 3001` 启动，v2 保持 `next dev -p 3000` 不变

---

## 第二章：现状分析

### 2.1 v2 前端问题总结

#### God Component 问题清单

| 文件 | 行数 | useState | fetch 调用 | useEffect | 核心问题 |
|------|------|----------|-----------|-----------|----------|
| `dashboard/page.tsx` | 7522 | 95 | 58 | 6 | 所有 Dashboard 功能堆叠在单文件 |
| `task-manager.ts` | 127KB (约 3200 行) | — | — | — | 意图识别+路由+链路执行+产物管理全部耦合 |
| `api/chat/route.ts` | 5188+ | — | — | — | SSE 处理+意图路由+链路编排+结果格式化全部内联 |
| `classic-system-api.ts` | — | — | — | — | 13 个子标签页逻辑耦合在一个模块 |

#### 架构缺失问题

| 问题域 | 现状 | 影响 |
|--------|------|------|
| hooks 目录 | 不存在 | 所有自定义逻辑写在组件内部，无法复用 |
| utils 目录 | 不存在 | 工具函数散落在各 lib 文件中 |
| Store 粒度 | 6 个粗粒度 store | chat-store 管消息+流式+UI 状态混杂 |
| 组件层级 | 扁平化 | 无 Layout/Screen/Feature/Primitive 分层 |
| 错误处理 | 每处独立 try-catch | 无统一错误边界和重试策略 |
| 类型安全 | 部分 any 类型 | API 响应类型覆盖不全 |

### 2.2 代码统计

| 维度 | v2 数据 | v3 目标 |
|------|----------|----------|
| lib 文件数 | 77 | 80+ (新增 hooks/utils) |
| 组件文件数 | 20 | 60+ (分层架构) |
| 最大文件行数 | 7522 (dashboard) | < 300 |
| useState 总数 | 95+ (单文件) | < 5 (单组件) |
| fetch 调用点 | 58 (单文件) | 统一走 API Client |
| Store 数量 | 6 | 9 (按领域细分) |
| API Route 文件 | 92 个端点 | 不变 (共享) |
| 页面路由 | 12 个 | 20+ (v3 新增) |

### 2.3 模块可复用性评估表

#### 可直接迁移模块 (15 个)

| 模块 | 路径 | 迁移难度 | 注意事项 |
|------|------|----------|----------|
| types/index.ts | `src/types/index.ts` | 低 | 已包含完整的类型定义，可直接引用 |
| intent/fallback-engine.ts | `src/lib/intent/` | 低 | 纯函数，无 UI 依赖 |
| intent/intent-memory.ts | `src/lib/intent/` | 低 | 文件 I/O 操作，需确认路径 |
| trading-mode.ts | `src/lib/trading-mode.ts` | 低 | 枚举+工具函数 |
| strategy/types.ts | `src/lib/strategy/types.ts` | 低 | 纯类型定义 |
| reflection-gates.ts | `src/lib/reflection-gates.ts` | 低 | 核心 Reflector 逻辑，需适配前端调用 |
| monitor-bus.ts | `src/lib/monitor-bus.ts` | 中 | 服务端模块，前端通过 SSE 消费 |
| token-monitor.ts | `src/lib/token-monitor.ts` | 低 | 监控逻辑，需确认触发方式 |
| scheduler/cost-keeper.ts | `src/lib/scheduler/` | 低 | Token 计费逻辑 |
| scheduler/skip-gate.ts | `src/lib/scheduler/` | 低 | 链路跳过决策逻辑 |
| compressor-adapter/ | `src/lib/compressor-adapter/` | 低 | BAC 压缩适配层 |
| bridge-client.ts | `src/lib/bridge-client.ts` | 低 | WorkBuddy 桥接客户端 |
| uid.ts | `src/lib/uid.ts` | 低 | 唯一 ID 生成器 |
| encryption.ts | `src/lib/encryption.ts` | 低 | AES 加密工具 |

#### 需适配迁移模块 (3 个)

| 模块 | 路径 | 适配内容 |
|------|------|----------|
| intent/smart-router.ts | `src/lib/intent/` | 需将服务端 LLM 调用改为 API 调用 |
| knowledge-rag.ts | `src/lib/knowledge-rag.ts` | 需适配前端无文件系统环境 |
| auth.ts | `src/lib/auth.ts` | 需适配 v3 的 Session 管理方式 |

#### 需完全重写模块 (14 个)

| 模块 | 原路径 | 重写原因 |
|------|--------|----------|
| dashboard/page.tsx | `src/app/dashboard/` | 7522 行 God Component，需拆分为 10+ 组件 |
| task-manager.ts | `src/lib/task-manager.ts` | 127KB 耦合体，需拆分为 intent/chain/result 三个模块 |
| strategy/chain-controller.ts | `src/lib/strategy/` | 链路控制逻辑需对齐 SACG C 层设计 |
| dynamic-chain/executor.ts | `src/lib/dynamic-chain/` | 动态链执行需适配 Reflector 6 决策模型 |
| dynamic-chain/runner.ts | `src/lib/dynamic-chain/` | 同上 |
| dynamic-chain/graph-planner.ts | `src/lib/dynamic-chain/` | DAG 编排需对齐 SACG A 层 |
| dynamic-chain/reflect-engine.ts | `src/lib/dynamic-chain/` | 反思引擎需对齐 SACG C 层 Reflector |
| classic-system-api.ts | `src/lib/` | 13 子标签页逻辑需拆分 |
| classic-system-bridge.ts | `src/lib/` | 需适配新 API Client 架构 |
| classic-system-client.ts | `src/lib/` | 同上 |
| classic-system-hooks.ts | `src/lib/` | 需重写为标准 React Hooks |
| notebook/step-controller.ts | `src/lib/notebook/` | 需适配 v3 Notebook UI |
| orchestration/ | `src/lib/orchestration/` | 全部 6 个文件需适配 SACG A 层 |
| graph-reflection-bridge.ts | `src/lib/` | 需对齐 SACG G 层 BAC 压缩模型 |

---

## 第三章：v3 架构设计

### 3.1 路由架构

#### 完整页面路由映射表

```
src/app/v3/
├── layout.tsx                    → V3AppShell (独立 layout)
├── page.tsx                      → 重定向到 /v3/dashboard
│
├── login/
│   └── page.tsx                  → 登录页 (复用 v2 认证逻辑)
│
├── dashboard/
│   ├── layout.tsx                → DashboardLayout (Sidebar + TopBar + Content)
│   ├── page.tsx                  → 主控台三屏概览
│   │
│   ├── trade/                    → AI Skill 交易
│   │   ├── page.tsx              → 交易主页面 (聊天面板 + S 链追踪)
│   │   ├── chain/                → S 系列链追踪子页面
│   │   │   └── [chainId]/
│   │   │       └── page.tsx      → 单链详情 (步骤/决策/产物)
│   │   └── strategies/           → 策略管理
│   │       ├── page.tsx          → 策略列表
│   │       └── [strategyId]/
│   │           └── page.tsx      → 策略详情+回测结果
│   │
│   ├── classic/                  → 经典交易系统
│   │   ├── page.tsx              → 经典主页面 (C0-C8 全链)
│   │   ├── scan/                 → 宏观扫描 (C1)
│   │   ├── universe/             → 品种池扫描 (C2)
│   │   ├── gate/                 → 门禁检查 (C3)
│   │   ├── arena/                → 竞技场评审 (C4)
│   │   ├── select/               → 策略选择 (C5)
│   │   ├── signal/               → 信号审查 (C6)
│   │   ├── exit/                 → 离场监控 (C7)
│   │   ├── audit/                → 追踪审计 (C8)
│   │   └── governance/           → 治理流程 (Draft→Gate→Approval→Apply→Audit)
│   │       └── [proposalId]/
│   │           └── page.tsx      → 审批详情
│   │
│   ├── fundamental/              → 基本面分析
│   │   ├── page.tsx              → 基本面总览
│   │   ├── overview/             → 综合概览
│   │   ├── onchain/              → 链上数据
│   │   ├── macro/                → 宏观经济
│   │   ├── sentiment/            → 市场情绪
│   │   ├── flow/                 → 资金流向
│   │   ├── valuation/            → 估值模型
│   │   ├── narrative/            → 叙事分析
│   │   ├── news/                 → 新闻日历
│   │   ├── breadth/              → 市场广度
│   │   ├── calendar/             → 事件日历
│   │   └── intermarket/          → 跨市场分析
│   │
│   ├── three-screens/            → 三屏交易系统（应用层）
│   │   ├── page.tsx              → 三屏总览（Screen1/2/3 状态仪表盘）
│   │   ├── screen1/              → 第一屏：战略层（周线方向判定）
│   │   │   └── page.tsx          → 七维牛熊评分 + 方向锚 + 大师辩论
│   │   ├── screen2/              → 第二屏：战术层（日线入场预设）
│   │   │   └── page.tsx          → 三大预设价位 + 回测验证 + 贝叶斯优化
│   │   ├── screen3/              → 第三屏：执行层（实时监控与执行）
│   │   │   └── page.tsx          → A7门禁→A4验证→Gate→A5入场→A6监控→A9离场
│   │   ├── pipeline/             → 执行流水线
│   │   │   └── page.tsx          → 全链路执行状态 + 方向约束传递可视化
│   │   └── history/              → 交易历史
│   │       └── page.tsx          → 历史交易记录 + 离场报告
│   │
│   ├── monitor/                  → SACG 监控面板
│   │   ├── page.tsx              → SACG 四层可视化总览
│   │   ├── sense/               → S 层 - 意图识别
│   │   ├── arrange/              → A 层 - 图编排 DAG
│   │   ├── compute/              → C 层 - 执行追踪
│   │   └── graph/                → G 层 - BAC 压缩+回放
│   │
│   ├── memory/                   → 记忆与自进化
│   │   ├── page.tsx              → 记忆系统总览
│   │   ├── dze/                 → D-Z-E 工程链
│   │   └── preferences/          → 用户偏好记忆
│   │
│   ├── settings/                 → 系统设置
│   │   ├── page.tsx              → 设置总览
│   │   ├── api-keys/             → API 密钥管理
│   │   ├── trading-params/       → 交易参数
│   │   ├── strategies/           → 策略配置
│   │   └── channels/             → 通信渠道
│   │
│   ├── reports/                  → 研报与产物中台
│   │   ├── page.tsx              → 产物列表+筛选
│   │   └── [reportId]/
│   │       └── page.tsx          → 产物详情
│   │
│   └── governance/               → 治理面板
│       ├── page.tsx              → 治理总览 (审批/提案/绩效)
│       ├── proposals/            → 策略提案
│       ├── review/               → 绩效评审
│       └── approval/
│           └── [id]/
│               └── page.tsx      → 审批操作页
```

#### 路由与 SACG 层映射

| 路由前缀 | 主要 SACG 层 | 辅助层 | 说明 |
|----------|--------------|--------|------|
| `/v3/dashboard/` | 全部 | — | 三屏概览，每屏对应一个 SACG 层高亮 |
| `/v3/dashboard/trade/` | S + C | A | 意图识别输入(S) → 链路执行(C) |
| `/v3/dashboard/classic/` | S + C | A | 同上，经典模式 |
| `/v3/dashboard/fundamental/` | C | G | 执行层产物展示 + 图存储查询 |
| `/v3/dashboard/monitor/` | 全部 | — | SACG 四层独立可视化 |
| `/v3/dashboard/memory/` | G | S | 图存储层 + 意图识别反馈 |
| `/v3/dashboard/settings/` | — | — | 配置管理，不直接对应 SACG |
| `/v3/dashboard/reports/` | G | C | 图存储产物 + 执行产物关联 |
| `/v3/dashboard/governance/` | A | C | 图编排层治理 + 执行层审计 |

### 3.2 SACG 前端映射

#### 四层架构 UI 表达模型

```
┌─────────────────────────────────────────────────────────────────────┐
│                        SACG 四层前端映射总览                          │
├───────────┬─────────────────────────────────────────────────────────┤
│           │  S (Sense/感知) - 意图识别层                            │
│  颜色     │  ┌─────────────────────────────────────────────┐       │
│  #8B5CF6  │  │ 意图置信度仪表盘 (0-1 gauge)                  │       │
│  紫色     │  │ 三层价值模型:                                  │       │
│           │  │   L1: Intent → Objective (收敛)              │       │
│           │  │   L2: OKRSet (展开)                           │       │
│           │  │   L3: ExecutionBlueprint (工程化)             │       │
│           │  │ 意图历史热力图                                  │       │
│           │  └─────────────────────────────────────────────┘       │
├───────────┼─────────────────────────────────────────────────────────┤
│           │  A (Arrange/编排) - 图编排层                           │
│  颜色     │  ┌─────────────────────────────────────────────┐       │
│  #3B82F6  │  │ DAG 图可视化 (节点+边)                         │       │
│  蓝色     │  │ 节点状态: pending/active/done/skipped/failed  │       │
│           │  │ ACFTG 链展示 (纵轴=阶段, 横轴=链)              │       │
│           │  │ 动态编排过程动画                               │       │
│           │  │ GraphPlanner 决策日志                           │       │
│           │  └─────────────────────────────────────────────┘       │
├───────────┼─────────────────────────────────────────────────────────┤
│           │  C (Compute/执行) - 模块执行层                         │
│  颜色     │  ┌─────────────────────────────────────────────┐       │
│  #22C55E  │  │ 动态链执行追踪面板                              │       │
│  绿色     │  │ Reflector 6 决策可视化:                        │       │
│           │  │   CONTINUE / REDO / INSERT_BEFORE             │       │
│           │  │   JUMP_TO / EARLY_TERMINATE / SKIP            │       │
│           │  │ 三链交叉验证投票面板                            │       │
│           │  │ 上下文压缩进度条                                │       │
│           │  └─────────────────────────────────────────────┘       │
├───────────┼─────────────────────────────────────────────────────────┤
│           │  G (Graph/存储) - 图存储层                             │
│  颜色     │  ┌─────────────────────────────────────────────┐       │
│  #EF4444  │  │ BAC 三层压缩可视化:                            │       │
│  红色     │  │   Blueprint → Architecture → Chronicle      │       │
│           │  │ 压缩比率仪表盘                                 │       │
│           │  │ Checkpointing 时间线                           │       │
│           │  │ 历史回放播放器 (Play/Pause/Seek)               │       │
│           │  │ 产物版本树                                     │       │
│           │  └─────────────────────────────────────────────┘       │
└───────────┴─────────────────────────────────────────────────────────┘
```

#### S 层：意图识别可视化

```typescript
// S 层 UI 数据结构
interface SenseLayerViewModel {
  // 三层价值模型
  layer1: {
    intent: string;           // 原始意图 "分析BTC"
    objective: string;       // 收敛后目标 "判断BTC短期方向"
    convergenceScore: number; // 收敛置信度 0.85
  };
  layer2: {
    okrSet: OKRItem[];       // 展开的 OKR 集合
    // [{ objective: "完成多时间框架分析", keyResults: [...] }]
  };
  layer3: {
    blueprint: string;       // 工程化蓝图 ID
    chainAssignment: string;  // 分配的链路 S2_ANALYSIS
    estimatedSteps: number;  // 预估步骤数
  };
  // 意图置信度
  confidence: {
    overall: number;          // 总置信度
    domain: number;          // 领域置信度
    task: number;             // 任务置信度
    method: 'llm' | 'rule' | 'default';
  };
}
```

#### A 层：图编排 DAG 可视化

```typescript
// A 层 DAG 节点数据结构
interface ArrangeDAGNode {
  id: string;
  name: string;
  status: 'pending' | 'active' | 'done' | 'skipped' | 'failed';
  layer: 'S' | 'A' | 'C' | 'G';
  // DAG 边
  dependencies: string[];      // 依赖的节点 ID
  dependents: string[];        // 被依赖的节点 ID
  // ACFTG 链信息
  chainType: string;           // 'S' | 'C' | 'A' | 'F'
  stage: string;               // 思维阶段
  // 动态编排
  isDynamic: boolean;          // 是否为动态插入节点
  plannerDecision: string;     // GraphPlanner 决策日志
  // 性能指标
  latencyMs: number;
  tokensUsed: number;
}

// A 层 DAG 边数据结构
interface ArrangeDAGEdge {
  from: string;
  to: string;
  type: 'dependency' | 'data_flow' | 'control_flow';
  status: 'waiting' | 'active' | 'completed';
}
```

#### C 层：执行追踪面板

```typescript
// Reflector 6 决策类型
type ReflectorDecision =
  | 'CONTINUE'           // 继续下一步
  | 'REDO'               // 重做当前步
  | 'INSERT_BEFORE'      // 在当前步前插入新步
  | 'JUMP_TO'            // 跳转到指定步
  | 'EARLY_TERMINATE'    // 提前终止
  | 'SKIP';              // 跳过当前步

interface ComputeStepViewModel {
  stepId: string;
  chainId: string;
  stage: string;
  status: 'pending' | 'running' | 'done' | 'redo' | 'skipped' | 'failed';
  // Reflector 决策
  reflector: {
    decision: ReflectorDecision;
    reasoning: string;
    confidence: number;
  };
  // 三链交叉验证
  crossValidation: {
    chainA: { vote: 'approve' | 'reject' | 'abstain'; reasoning: string };
    chainB: { vote: 'approve' | 'reject' | 'abstain'; reasoning: string };
    chainC: { vote: 'approve' | 'reject' | 'abstain'; reasoning: string };
    finalDecision: 'approved' | 'rejected' | 'tie_break';
  };
  // 上下文压缩
  compression: {
    originalTokens: number;
    compressedTokens: number;
    ratio: number;
  };
}
```

#### G 层：BAC 压缩可视化 + 历史回放

```typescript
// BAC 三层压缩数据结构
interface GraphLayerViewModel {
  // Blueprint 层 - 原始蓝图
  blueprint: {
    id: string;
    nodes: GraphNode[];
    edges: GraphEdge[];
    totalTokens: number;
    createdAt: string;
  };
  // Architecture 层 - 架构压缩
  architecture: {
    id: string;
    compressedNodes: GraphNode[];
    compressionRatio: number;
    preservedPatterns: string[];
  };
  // Chronicle 层 - 编年史
  chronicle: {
    id: string;
    timeline: ChronicleEntry[];
    checkpoints: Checkpoint[];
  };
}

interface Checkpoint {
  id: string;
  timestamp: string;
  blueprintSnapshot: string;
  architectureSnapshot: string;
  triggerReason: string;   // 'milestone' | 'error' | 'manual' | 'periodic'
}

interface ChronicleEntry {
  timestamp: string;
  event: string;
  layer: 'B' | 'A' | 'C';
  summary: string;
  artifactRef?: string;
}
```

### 3.3 三屏交易系统 — 应用层

三屏交易系统是 WorkBuddy OS 架构中的**实际应用层**，位于能力层之上。它调用 A_domain（执行闭环/情报闭环）、C_domain（经典指标）、F_domain（基本面）等能力模块来完成交易决策和执行。三屏交易系统拥有独立页面，不混入 AI Skill 或 Classic 交易页，因为它代表的是「基于模型系统的完整交易执行流程」。

#### 应用层定位

```
┌─────────────────────────────────────────────────────────┐
│                   应用层 (Application Layer)               │
│                                                         │
│   ┌─────────────────────────────────────────────┐       │
│   │  三屏交易系统 (Three-Screen Trading System)  │       │
│   │  独立页面: /v3/dashboard/three-screens       │       │
│   └──────────────────┬──────────────────────────┘       │
│                      │ 调用能力层模块                      │
├──────────────────────┼──────────────────────────────────┤
│   SACG 四层          │ 能力层 (Capability Layer)           │
│   ┌──────┐           │                                   │
│   │  S   │           │  A_domain: A0矛盾论, A1调研,       │
│   │  A   │◄──────────│    A2第一性原理, A3策略设计,        │
│   │  C   │           │    A4验证, A5执行, A6情报,         │
│   │  G   │           │    A7门禁, A8复盘, A9离场           │
│   └──────┘           │  C_domain: C1技术扫描, C2品种池      │
│                      │  F_domain: F1新闻, F2资金流         │
│                      │  G_domain: 宪法, 合规, 风控          │
│                      │  T_domain: 搜索, 产物, 记忆         │
└──────────────────────┴──────────────────────────────────┘
```

#### Elder 三屏体系前端映射

| 屏 | 战略角色 | 路由 | 核心内容 | 调用的能力模块 | 输出 |
|:---|:---|:---|:---|:---|:---|
| **Screen1** | 战略层（周线方向） | `/v3/dashboard/three-screens/screen1` | 七维牛熊评分仪表盘 + MA200 方向锚 + 大师辩论面板 | A0矛盾论, A1调研, A2第一性原理, A3策略设计 | direction(LONG/SHORT), score(0-100), strategy_type |
| **Screen2** | 战术层（日线预设） | `/v3/dashboard/three-screens/screen2` | 三大预设价位表（入场/加仓/止盈止损）+ 回测验证 + 贝叶斯参数优化面板 | dream-backtest, dream-bayesian-opt, A4验证 | 三大预设 + 信号强度 + 仓位建议 |
| **Screen3** | 执行层（实时执行） | `/v3/dashboard/three-screens/screen3` | 执行流水线可视化: A7门禁→A4验证→Gate→A5入场→A6监控→A9离场 | A7门禁, A4验证, C3门禁, A5执行, A6情报, A9离场 | 仓位状态 + 执行日志 + 离场报告 |
| **Pipeline** | 全链路视角 | `/v3/dashboard/three-screens/pipeline` | Screen1→2→3 完整数据流可视化 + 方向约束传递追踪 | 全部上述模块 | 链路健康度 + 瓶颈检测 |

#### 三屏数据流与方向约束

```
Screen1 (战略层)
  │ 输出: direction=LONG, score=82, confidence=0.78
  │ 方向锚: MA200 三日确认
  │
  ├─── 方向约束 (硬性) ───→ Screen2 (战术层)
  │                          │ 必须在 LONG 方向下计算预设
  │                          │ 入场价位 = Screen1 方向 + 日线分析
  │                          │ 输出: 入场价/加仓价/止盈价/止损价
  │                          │
  │                          └─── 预设约束 (唯一参考) ───→ Screen3 (执行层)
  │                                                         │ 入场必须参照 Screen2 预设
  │                                                         │ 方向必须来自 Screen1
  │                                                         │ 内部流水线: A7→A4→Gate→A5→A6→A9
  │                                                         │ A6 监控持续运行，实时调整
  │                                                         │ A9 满足条件触发强制离场
  │
  └─── 记忆更新 ───→ Memory / Chronicle
```

#### 三屏交易系统 UI 数据结构

```typescript
// Screen1 视图模型
interface Screen1ViewModel {
  symbol: string;
  // 七维牛熊评分
  dimensions: {
    technical: { score: number; signal: string };     // 技术面
    halving: { score: number; signal: string };       // 减半周期
    miner: { score: number; signal: string };         // 矿工指标
    onchain: { score: number; signal: string };       // 链上数据
    macro: { score: number; signal: string };         // 宏观经济
    intermarket: { score: number; signal: string };   // 跨市场
    sentiment: { score: number; signal: string };     // 市场情绪
  };
  // 方向锚
  directionAnchor: {
    ma200Status: 'above' | 'below' | 'crossing';
    threeDayConfirm: boolean;
    direction: 'LONG' | 'SHORT';
    overallScore: number;  // 0-100 综合评分
    confidence: number;    // 0-1
  };
  // 大师辩论
  debate: {
    bullCase: string;
    bearCase: string;
    synthesis: string;
  };
  // 状态
  status: 'idle' | 'analyzing' | 'done' | 'error';
  updatedAt: string;
}

// Screen2 视图模型
interface Screen2ViewModel {
  symbol: string;
  directionConstraint: 'LONG' | 'SHORT';  // 来自 Screen1
  // 三大预设价位
  presets: {
    entry: { price: number; strength: 'strong' | 'moderate' | 'weak' };
    addPosition: { price: number; size: number };
    takeProfit: { price: number; levels: number[] };
    stopLoss: { price: number; levels: number[] };
  };
  // 回测验证
  backtest: {
    winRate: number;
    avgReturn: number;
    maxDrawdown: number;
    sampleSize: number;
  };
  // 贝叶斯优化
  bayesianOpt: {
    bestParams: Record<string, number>;
    iterations: number;
    improvement: number;
  };
  status: 'idle' | 'waiting_screen1' | 'computing' | 'done' | 'error';
}

// Screen3 视图模型
interface Screen3ViewModel {
  symbol: string;
  directionConstraint: 'LONG' | 'SHORT';  // 来自 Screen1
  presetConstraint: Screen2ViewModel['presets'];  // 来自 Screen2
  // 执行流水线
  pipeline: {
    steps: PipelineStep[];
    currentStep: string;
    triggeredAt: string | null;
  };
  // 持仓状态
  position: {
    isOpen: boolean;
    size: number;
    entryPrice: number;
    currentPrice: number;
    unrealizedPnl: number;
    leverage: number;
  };
  // A6 监控
  monitor: {
    alertCount: number;
    lastAlertAt: string;
    activeAlerts: Alert[];
  };
}

// Pipeline 步骤
interface PipelineStep {
  id: string;           // A7_GATE | A4_VALIDATE | C3_GATE | A5_ENTRY | A6_MONITOR | A9_EXIT
  name: string;
  status: 'pending' | 'active' | 'passed' | 'failed' | 'skipped';
  decision: string;
  timestamp: string | null;
  details: string;
}
```

#### 三屏状态管理

三屏交易系统需要一个独立的 Zustand store 来管理跨屏数据和方向约束传递：

```typescript
// src/stores/v3/three-screens-store.ts
interface ThreeScreensState {
  // 全局状态
  activeScreen: 'overview' | 'screen1' | 'screen2' | 'screen3' | 'pipeline' | 'history';
  symbol: string;

  // Screen1
  screen1: Screen1ViewModel | null;
  // Screen2
  screen2: Screen2ViewModel | null;
  // Screen3
  screen3: Screen3ViewModel | null;

  // 方向约束传递
  directionConstraint: {
    direction: 'LONG' | 'SHORT' | null;
    source: 'screen1' | 'manual' | null;
    lockedAt: string | null;
  };

  // 预设约束传递
  presetConstraint: Screen2ViewModel['presets'] | null;

  // 操作
  setActiveScreen: (screen: ThreeScreensState['activeScreen']) => void;
  setSymbol: (symbol: string) => void;
  updateScreen1: (data: Partial<Screen1ViewModel>) => void;
  updateScreen2: (data: Partial<Screen2ViewModel>) => void;
  updateScreen3: (data: Partial<Screen3ViewModel>) => void;
  propagateDirection: (direction: 'LONG' | 'SHORT') => void;
  propagatePresets: (presets: Screen2ViewModel['presets']) => void;
  resetAll: () => void;
}
```

#### 关键集成点

1. **方向约束硬传递**: Screen1 输出的 direction 作为硬性约束写入 `directionConstraint`，Screen2 和 Screen3 必须读取此约束，不允许自行判断方向
2. **Screen2 等待机制**: Screen2 在 `directionConstraint` 为 null 时处于 `waiting_screen1` 状态，不执行任何计算
3. **Screen3 唯一入场参考**: Screen3 的入场信号必须来自 Screen2 预设，不允许独立生成入场逻辑
4. **记忆回写**: 每次完整三屏执行结束后，结果写入 G 层 Chronicle 和记忆系统，供后续查询和回放

### 3.4 状态管理架构

#### Zustand Store 拆分方案

```
src/stores/v3/
├── index.ts                      → 统一导出
├── session-store.ts              → 会话、消息、输入状态
├── chain-store.ts                → 链状态、步骤追踪、Reflector 决策
├── trading-store.ts              → 交易模式、参数、余额
├── classic-store.ts              → 经典系统完整状态 (C0-C8)
├── three-screens-store.ts        → 三屏交易系统状态 (Screen1/2/3 + 方向约束)
├── monitor-store.ts              → SACG 监控事件、管道状态
├── memory-store.ts               → 记忆系统状态
├── ui-store.ts                  → 面板折叠、主题、语言
├── api-config-store.ts           → API 配置 (迁移自 v2)
└── auth-store.ts                 → 认证 (迁移自 v2)
```

#### Store 详细设计

**1. useSessionStore** — 会话管理

```typescript
interface SessionState {
  // 会话列表
  sessions: ChatSession[];
  activeSessionId: string | null;
  // 消息状态
  messages: ChatMessage[];
  isStreaming: boolean;
  currentStreamContent: string;
  // 输入状态
  inputValue: string;
  inputMode: 'chat' | 'command';
  // 意图识别结果 (S 层)
  lastIntent: IntentRecognitionResult | null;
  // Actions
  createSession: () => string;
  switchSession: (id: string) => void;
  sendMessage: (content: string) => Promise<void>;
  appendStreamDelta: (delta: string) => void;
  setLastIntent: (intent: IntentRecognitionResult) => void;
}
```

**2. useChainStore** — 链路追踪 (C 层 + A 层部分)

```typescript
interface ChainState {
  // 当前执行的链
  activeChain: {
    chainId: string;
    chainType: string;          // 'S' | 'C' | 'A' | 'F'
    chainName: string;
    status: 'idle' | 'running' | 'paused' | 'completed' | 'failed';
    startedAt: string;
    completedAt?: string;
  } | null;
  // 步骤列表
  steps: ComputeStepViewModel[];
  activeStepIndex: number;
  // Reflector 决策历史
  reflectorHistory: ReflectorDecisionRecord[];
  // DAG 数据 (A 层)
  dagNodes: ArrangeDAGNode[];
  dagEdges: ArrangeDAGEdge[];
  // 链产物
  artifacts: ChainArtifact[];
  // Actions
  setActiveChain: (chain: ActiveChain) => void;
  updateStep: (stepId: string, update: Partial<ComputeStepViewModel>) => void;
  addReflectorDecision: (record: ReflectorDecisionRecord) => void;
  updateDAGNode: (nodeId: string, update: Partial<ArrangeDAGNode>) => void;
}
```

**3. useTradingStore** — AI Skill 交易

```typescript
interface TradingState {
  // 交易模式
  mode: 'ai_skill' | 'classic';
  // AI Skill 状态
  aiSkill: {
    isConnected: boolean;
    activeStrategies: StrategyView[];
    balance: BalanceInfo | null;
    positions: PositionInfo[];
    recentSignals: TradingSignal[];
  };
  // S 系列链追踪
  sChainTraces: SChainTrace[];
  // 交易参数
  params: TradingParamsView | null;
  // Actions
  setMode: (mode: 'ai_skill' | 'classic') => void;
  updateBalance: (balance: BalanceInfo) => void;
  addSignal: (signal: TradingSignal) => void;
  setSChainTrace: (trace: SChainTrace) => void;
}
```

**4. useClassicStore** — 经典交易系统

```typescript
interface ClassicState {
  // C0-C8 各阶段状态
  phases: {
    C0_DIRECT_ANSWER: PhaseStatus;
    C1_MACRO_SCAN: PhaseStatus;
    C2_UNIVERSE_SCAN: PhaseStatus;
    C3_GATE_CHECK: PhaseStatus;
    C4_ARENA_REVIEW: PhaseStatus;
    C5_STRATEGY_SELECT: PhaseStatus;
    C6_SIGNAL_REVIEW: PhaseStatus;
    C7_EXIT_MONITOR: PhaseStatus;
    C8_TRACKING_AUDIT: PhaseStatus;
  };
  // 当前激活的阶段
  activePhase: string;
  // 治理流程
  governance: {
    proposals: GovernanceProposal[];
    activeProposalId: string | null;
    governanceStage: 'draft' | 'gate' | 'approval' | 'apply' | 'audit';
  };
  // 交易配置 (经典指标)
  config: {
    knowledgeSource: number;    // 10-经典指标
    indicatorSet: string[];
    timeframe: string;
  };
  // Actions
  setPhaseStatus: (phase: string, status: PhaseStatus) => void;
  setActivePhase: (phase: string) => void;
  updateGovernance: (update: Partial<ClassicGovernance>) => void;
}
```

**5. useMonitorStore** — SACG 监控

```typescript
interface MonitorState {
  // SACG 四层状态
  layers: {
    S: { status: 'idle' | 'active' | 'error'; events: MonitorEvent[] };
    A: { status: 'idle' | 'active' | 'error'; events: MonitorEvent[] };
    C: { status: 'idle' | 'active' | 'error'; events: MonitorEvent[] };
    G: { status: 'idle' | 'active' | 'error'; events: MonitorEvent[] };
  };
  // 管道状态
  pipeline: {
    activePipelines: PipelineStatus[];
    throughput: { rps: number; avgLatencyMs: number };
  };
  // SSE 连接状态
  sseConnection: 'disconnected' | 'connecting' | 'connected' | 'error';
  // Actions
  pushEvent: (layer: 'S' | 'A' | 'C' | 'G', event: MonitorEvent) => void;
  setSSEStatus: (status: string) => void;
  updatePipeline: (update: Partial<PipelineInfo>) => void;
}
```

**6. useMemoryStore** — 记忆系统

```typescript
interface MemoryState {
  // D-Z-E 工程链
  dzeChains: {
    D: { status: string; records: MemoryRecord[] };
    Z: { status: string; records: MemoryRecord[] };
    E: { status: string; records: MemoryRecord[] };
  };
  // 用户偏好记忆
  preferences: UserPreference[];
  // 记忆统计
  stats: {
    totalMemories: number;
    compressionRatio: number;
    lastEvolutionAt: string;
  };
  // Actions
  updateDZEChain: (chain: 'D' | 'Z' | 'E', update: Partial<DZEChainState>) => void;
  setPreferences: (prefs: UserPreference[]) => void;
}
```

**7. useUIStore** — UI 状态

```typescript
interface UIState {
  // 布局
  sidebarCollapsed: boolean;
  rightPanelCollapsed: boolean;
  activeRightTab: 'analysis' | 'market' | 'reports' | 'settings';
  // 主题
  theme: 'dark' | 'light';
  // 语言
  locale: 'zh-CN' | 'en-US';
  // Command Palette
  commandPaletteOpen: boolean;
  // 通知
  notifications: Notification[];
  // Actions
  toggleSidebar: () => void;
  toggleRightPanel: () => void;
  setTheme: (theme: 'dark' | 'light') => void;
  toggleCommandPalette: () => void;
}
```

**8. useApiConfigStore** — API 配置 (迁移)

```typescript
// 迁移自 v2 src/stores/config-store.ts
// 管理的配置域: API Keys / Trading Params / Strategies / Channels
// 迁移时保持接口不变，仅调整内部 fetch 调用走统一 API Client
```

**9. useAuthStore** — 认证 (迁移)

```typescript
// 迁移自 v2 src/stores/auth-store.ts
// 管理: session / user profile / login state
// 迁移时保持 NextAuth Session 机制不变
```

### 3.4 组件层级设计

```
src/components/v3/
├── layout/                          → Layout 层
│   ├── AppShell.tsx                → 应用外壳 (全屏容器)
│   ├── Sidebar.tsx                 → 左侧导航栏
│   ├── TopBar.tsx                  → 顶部栏 (面包屑/搜索/用户)
│   ├── CommandPalette.tsx          → 命令面板 (Cmd+K)
│   └── NotificationToast.tsx       → 通知提示
│
├── screens/                         → Screen 层 (页面级容器)
│   ├── DashboardScreen.tsx          → 主控台三屏概览
│   ├── TradeScreen.tsx              → AI Skill 交易页
│   ├── ClassicScreen.tsx            → 经典交易页
│   ├── FundamentalScreen.tsx        → 基本面分析页
│   ├── ThreeScreensPage.tsx         → 三屏交易系统总览
│   ├── MonitorScreen.tsx           → SACG 监控页
│   ├── MemoryScreen.tsx            → 记忆管理页
│   ├── SettingsScreen.tsx          → 系统设置页
│   ├── ReportsScreen.tsx           → 产物中台页
│   └── GovernanceScreen.tsx         → 治理面板页
│
├── features/                        → Feature 层 (业务功能组件)
│   ├── chat/
│   │   ├── ChatPanel.tsx           → 聊天面板
│   │   ├── MessageList.tsx          → 消息列表
│   │   ├── MessageItem.tsx         → 单条消息
│   │   ├── ChatInput.tsx           → 输入区+快捷命令
│   │   └── StreamingIndicator.tsx  → 流式输出指示器
│   │
│   ├── chain/
│   │   ├── ChainTracker.tsx        → 链追踪面板
│   │   ├── ChainStepCard.tsx       → 单步骤卡片
│   │   ├── ReflectorDecisionBadge.tsx → Reflector 决策标记
│   │   ├── CrossValidationPanel.tsx → 三链交叉验证面板
│   │   └── SACELayerBadge.tsx      → SACG 层级标记
│   │
│   ├── data/
│   │   ├── DataView.tsx            → 数据视图容器
│   │   ├── MarketSnapshot.tsx      → 市场快照
│   │   ├── BalanceCard.tsx          → 余额卡片
│   │   └── PositionTable.tsx        → 持仓表格
│   │
│   ├── sacg/
│   │   ├── SACGVisualizer.tsx      → SACG 四层总览可视化
│   │   ├── SenseConfidenceGauge.tsx → 意图置信度仪表
│   │   ├── ThreeLayerValueModel.tsx → 三层价值模型展示
│   │   ├── DAGGraphView.tsx        → DAG 图可视化
│   │   ├── ReflectorPanel.tsx      → Reflector 决策面板
│   │   ├── BACTimeline.tsx         → BAC 压缩时间线
│   │   └── HistoryPlayer.tsx       → 历史回放播放器
│   │
│   ├── classic/
│   │   ├── ClassicPhasePanel.tsx   → 经典系统阶段面板
│   │   ├── GovernanceFlow.tsx       → 治理流程 UI
│   │   ├── PhaseIndicator.tsx      → 阶段指示器 (C0-C8)
│   │   └── IndicatorConfig.tsx     → 经典指标配置
│   │
│   ├── fundamental/
│   │   ├── FundamentalGrid.tsx      → 基本面指标网格
│   │   ├── OnchainMetrics.tsx      → 链上数据
│   │   ├── MacroDashboard.tsx      → 宏观面板
│   │   └── SentimentHeatmap.tsx    → 情绪热力图
│   │
│   ├── three-screens/
│   │   ├── Screen1Panel.tsx        → 战略层：七维牛熊评分 + 方向锚
│   │   ├── Screen2Panel.tsx        → 战术层：三大预设价位 + 回测
│   │   ├── Screen3Panel.tsx        → 执行层：流水线 + 持仓状态
│   │   ├── PipelineView.tsx         → 全链路方向约束传递可视化
│   │   ├── DirectionAnchor.tsx     → MA200 方向锚指示器
│   │   ├── DebatePanel.tsx          → 大师辩论面板
│   │   ├── PresetPriceTable.tsx    → 预设价位表
│   │   ├── ExecutionPipeline.tsx   → A7→A4→Gate→A5→A6→A9 流水线
│   │   └── ConstraintFlow.tsx      → 方向约束→预设约束传递箭头
│   │
│   ├── memory/
│   │   ├── DZEChainView.tsx        → D-Z-E 链视图
│   │   ├── MemoryTimeline.tsx       → 记忆时间线
│   │   └── PreferenceEditor.tsx    → 偏好编辑器
│   │
│   ├── settings/
│   │   ├── ApiKeyManager.tsx       → API 密钥管理
│   │   ├── TradingParamsEditor.tsx → 交易参数编辑
│   │   ├── StrategyManager.tsx     → 策略管理
│   │   └── ChannelManager.tsx       → 通信渠道管理
│   │
│   └── reports/
│       ├── ArtifactList.tsx        → 产物列表
│       ├── ArtifactDetail.tsx      → 产物详情
│       └── ArtifactFilter.tsx      → 产物筛选
│
├── primitives/                      → Primitive 层 (原子组件)
│   ├── Button.tsx
│   ├── Card.tsx
│   ├── Badge.tsx
│   ├── Dialog.tsx
│   ├── Tooltip.tsx
│   ├── StatusDot.tsx
│   ├── ProgressBar.tsx
│   ├── Tabs.tsx
│   ├── Select.tsx
│   ├── Input.tsx
│   ├── Switch.tsx
│   ├── Spinner.tsx
│   ├── Avatar.tsx
│   └── icons/                      → Inline SVG 图标
│       ├── icon-search.tsx
│       ├── icon-chart.tsx
│       ├── icon-gear.tsx
│       ├── icon-shield.tsx
│       ├── icon-brain.tsx
│       ├── icon-database.tsx
│       └── ...
│
└── hooks/                           → 自定义 Hooks
    ├── useSSE.ts                   → SSE 流式连接
    ├── useAPI.ts                   → 统一 API 调用
    ├── useChainTracker.ts          → 链追踪逻辑
    ├── useRealtimeData.ts          → 实时数据轮询
    ├── useKeyboard.ts              → 键盘快捷键
    └── useDebounce.ts              → 防抖
```

#### 组件层级关系图

```
Layout 层
  └── AppShell
       ├── Sidebar (导航路由)
       ├── TopBar (搜索/通知/用户)
       └── Content Area
            └── Screen 层
                 └── TradeScreen (页面容器)
                      ├── Feature 层
                      │    ├── ChatPanel
                      │    │    ├── MessageList
                      │    │    │    └── MessageItem (含 Primitive)
                      │    │    └── ChatInput (含 Primitive)
                      │    ├── ChainTracker
                      │    │    ├── ChainStepCard
                      │    │    │    ├── ReflectorDecisionBadge
                      │    │    │    └── CrossValidationPanel
                      │    │    └── SACELayerBadge
                      │    └── DataView
                      │         ├── MarketSnapshot
                      │         └── BalanceCard
                      └── Primitive 层 (通过 Feature 间接引用)
```

---

## 第四章：API 集成方案

### 4.1 API Client 层封装设计

```typescript
// src/lib/v3/api/client.ts

/**
 * 统一 API Client
 * - 基于 fetch 封装
 * - 支持标准 REST 和 SSE
 * - 统一错误处理和重试
 */

interface ApiClientConfig {
  baseUrl: string;         // 默认 ''
  timeout: number;         // 默认 30000ms
  retries: number;         // 默认 2
  headers?: Record<string, string>;
}

class ApiClient {
  private config: ApiClientConfig;

  async get<T>(path: string, options?: RequestInit): Promise<ApiResponse<T>> { /*...*/ }
  async post<T>(path: string, body?: unknown): Promise<ApiResponse<T>> { /*...*/ }
  async put<T>(path: string, body?: unknown): Promise<ApiResponse<T>> { /*...*/ }
  async patch<T>(path: string, body?: unknown): Promise<ApiResponse<T>> { /*...*/ }
  async delete<T>(path: string): Promise<ApiResponse<T>> { /*...*/ }

  // SSE 专用
  async sse<T>(path: string, body: unknown, handlers: SSEHandlers<T>): AbortController { /*...*/ }
}

interface ApiResponse<T> {
  success: boolean;
  data: T;
  error?: ApiError;
}

interface ApiError {
  code: string;
  message: string;
  retryable: boolean;
  details?: unknown;
}
```

### 4.2 API 分组

按 19 个业务域分组，每组一个 API 模块文件:

```
src/lib/v3/api/
├── client.ts                 → ApiClient 基类
├── index.ts                  → 统一导出
├── task-api.ts               → 任务执行 (5 端点)
├── chat-api.ts               → 对话 (2 端点)
├── market-api.ts             → 市场数据 (8 端点)
├── trade-api.ts              → 交易 (1 端点)
├── config-api.ts             → 配置管理 (14 端点)
├── user-api.ts               → 用户 (4 端点)
├── reports-api.ts            → 研报 (1 端点)
├── monitor-api.ts            → 监控 (3 端点)
├── intent-api.ts             → 意图识别 (2 端点)
├── notebook-api.ts           → 笔记本 (8 端点)
├── ops-api.ts                → 运维 (2 端点)
├── orchestrate-api.ts         → 编排 (2 端点)
├── chain-api.ts              → 链路产物 (1 端点)
├── board-api.ts              → 治理 (5 端点)
├── fundamental-api.ts        → 基本面 (2 端点)
├── feed-api.ts               → 消息流 (1 端点)
├── auth-api.ts               → 认证 (NextAuth, 无自定义端点)
├── artifact-api.ts           → 产物文件 (1 端点)
└── register-api.ts           → 注册 (1 端点)
```

### 4.3 SSE 流式集成方案

#### 9 种事件类型处理策略

| 事件类型 | 数据方向 | 处理策略 | UI 响应 |
|----------|----------|----------|---------|
| `started` | Server → Client | 标记任务开始，初始化追踪 UI | 显示 "正在处理..." 动画 |
| `thinking` | Server → Client | 显示 AI 思考过程 | 在 ChatPanel 中显示思考卡片 (ThinkingCard) |
| `progress` | Server → Client | 更新链路步骤进度 | ChainTracker 中对应步骤状态更新为 running |
| `text_delta` | Server → Client | 流式追加文本 | MessageItem 实时追加文本内容 |
| `data_card` | Server → Client | 渲染结构化数据卡片 | 在消息流中插入 DataCard 组件 |
| `artifact_ref` | Server → Client | 记录产物引用 | 在参考报告区域新增一条引用卡片 |
| `action_required` | Server → Client | 需要用户操作 | 弹出 Dialog 或在消息中显示操作按钮 |
| `done` | Server → Client | 标记任务完成 | 更新链追踪状态为 completed，停止流式动画 |
| `error` | Server → Client | 错误处理 | 显示错误提示，根据 retryable 决定是否显示重试按钮 |

#### SSE Hook 设计

```typescript
// src/components/v3/hooks/useSSE.ts

interface UseSSEOptions {
  url: string;
  body: unknown;
  onEvent: (event: SSEEvent) => void;
  onError?: (error: Error) => void;
  onComplete?: () => void;
  autoStart?: boolean;
}

function useSSE(options: UseSSEOptions) {
  // 返回:
  // - status: 'idle' | 'connecting' | 'streaming' | 'completed' | 'error'
  // - abort: () => void
  // - start: () => void
  // - retry: () => void
}
```

#### SSE 事件分发到 Store

```typescript
// SSE 事件到达后，根据类型分发到不同的 Zustand Store:
function dispatchSSEEvent(event: SSEEvent): void {
  switch (event.type) {
    case 'started':
      useChainStore.getState().setActiveChain(event.data.chain);
      break;
    case 'progress':
      useChainStore.getState().updateStep(event.data.stepId, { status: 'running', progress: event.data.progress });
      break;
    case 'text_delta':
      useSessionStore.getState().appendStreamDelta(event.data.content);
      break;
    case 'data_card':
      // 插入到消息流
      break;
    case 'artifact_ref':
      useChainStore.getState().addArtifact(event.data);
      break;
    case 'action_required':
      // 触发 UI 弹窗
      break;
    case 'done':
      useChainStore.getState().updateStep(event.data.stepId, { status: 'done' });
      useSessionStore.getState().stopStreaming();
      break;
    case 'error':
      useMonitorStore.getState().pushEvent('C', { type: 'error', data: event.data });
      break;
  }
}
```

### 4.4 错误处理与重试策略

| 错误类型 | 处理方式 | 重试策略 | 用户提示 |
|----------|----------|----------|----------|
| 网络超时 | 显示重试按钮 | 自动重试 2 次，间隔 3s | "网络连接超时，请重试" |
| 401 未授权 | 跳转登录页 | 不重试 | "登录已过期，请重新登录" |
| 403 权限不足 | 显示提示 | 不重试 | "当前操作需要更高级别权限" |
| 429 限流 | 排队等待 | 指数退避，最多 5 次 | "请求过于频繁，稍后重试" |
| 500 服务错误 | 显示重试按钮 | 自动重试 1 次 | "服务异常，请稍后重试" |
| SSE 连接断开 | 自动重连 | 指数退避，最多 10 次 | "连接中断，正在重连..." |
| LLM 降级 | 降级到备用模型 | 自动切换 | "AI 模型切换中..." |

---

## 第五章：设计规范

### 5.1 配色方案

#### 基础色板

```css
/* v3 Design Tokens — 通过 CSS @theme 定义 (Tailwind v4) */

/* 背景色 */
--color-bg-primary: #0a0e17;       /* 主背景 — deep navy */
--color-bg-secondary: #111827;      /* 面板/卡片背景 */
--color-bg-tertiary: #1e293b;       /* 输入框/可交互区域 */
--color-bg-elevated: #1a2332;        /* 浮层/弹窗背景 */

/* 文本色 */
--color-text-primary: #f1f5f9;      /* 主文字 */
--color-text-secondary: #94a3b8;    /* 辅助文字 */
--color-text-tertiary: #64748b;     /* 禁用/提示文字 */
--color-text-accent: #3b82f6;       /* 链接/高亮文字 */

/* 边框色 */
--color-border-default: #1e293b;
--color-border-hover: #334155;
--color-border-active: #3b82f6;

/* 功能色 */
--color-success: #22c55e;           /* 涨/通过/完成 */
--color-danger: #ef4444;            /* 跌/失败/拦截 */
--color-warning: #f59e0b;          /* 警告/注意 */
--color-info: #06b6d4;              /* 信息/中性 */
```

#### SACG 四层配色映射

```
S (Sense)   #8B5CF6  紫色  — 意图识别、置信度、三层价值模型
A (Arrange) #3B82F6  蓝色  — DAG 编排、节点状态、GraphPlanner
C (Compute) #22C55E  绿色  — 执行追踪、Reflector 决策、验证通过
G (Graph)   #EF4444  红色  — BAC 压缩、历史回放、Checkpoint
```

这四色在 UI 中的使用规则:
- **Sidebar 导航**: 每个一级导航项左侧有 SACG 层色条
- **Badge/Tag**: 链路步骤上的 SACELayerBadge 使用对应层色
- **进度条**: 四层各自的进度条使用对应层色
- **DAG 节点**: 节点边框色表示所属 SACG 层
- **状态面板**: 四层监控面板的 Tab 使用对应层色高亮

#### 链系列色

| 链系列 | 颜色 | 用途 |
|--------|------|------|
| S 系列 (S0-S5) | #8B5CF6 紫色 | 前端策略思维链 |
| C 系列 (C0-C8) | #06B6D4 青色 | 经典交易模式链 |
| A 系列 (A1-A9) | #3B82F6 蓝色 | 后端 cron 交易链 |
| D-Z-E 系列 | #F59E0B 琥珀色 | 工程开发链 |

### 5.2 响应式断点策略

| 断点 | 宽度范围 | Sidebar | 右侧面板 | 布局模式 |
|------|----------|---------|----------|----------|
| `xl` | >= 1280px | 展开 (240px) | 展开 (320px) | 三栏完整 |
| `lg` | 1024-1279px | 折叠 (64px, 仅图标) | 展开 (320px) | 双栏+图标侧栏 |
| `md` | 768-1023px | 折叠 (隐藏) | 抽屉模式 | 单栏+抽屉 |
| `sm` | < 768px | 隐藏 (汉堡菜单) | 底部弹窗 | 纯对话模式 |

### 5.3 字体规范

| 用途 | 字体 | 字号 | 字重 |
|------|------|------|------|
| 页面标题 | Inter, system-ui | 24px / 1.5rem | 700 (bold) |
| 区域标题 | Inter, system-ui | 18px / 1.125rem | 600 (semibold) |
| 正文 | Inter, system-ui | 14px / 0.875rem | 400 (normal) |
| 辅助文字 | Inter, system-ui | 12px / 0.75rem | 400 (normal) |
| 数据数字 | JetBrains Mono, monospace | 14px / 0.875rem | 500 (medium) |
| 大数字 | JetBrains Mono, monospace | 28px / 1.75rem | 700 (bold) |
| 代码 | JetBrains Mono, monospace | 13px / 0.8125rem | 400 (normal) |

### 5.4 间距与圆角规范

| 用途 | 间距值 | Tailwind Class |
|------|--------|----------------|
| 页面边距 | 24px | `p-6` |
| 区域间距 | 16px | `gap-4` |
| 组件内间距 | 12px | `p-3` |
| 紧凑间距 | 8px | `gap-2` |
| 元素间距 | 4px | `gap-1` |

| 用途 | 圆角值 | Tailwind Class |
|------|--------|----------------|
| 卡片 | 8px | `rounded-lg` |
| 按钮 | 6px | `rounded-md` |
| 输入框 | 6px | `rounded-md` |
| Badge | 9999px | `rounded-full` |
| 弹窗 | 12px | `rounded-xl` |
| 小元素 | 4px | `rounded` |

---

## 第六章：实施路线图 P0-P3

### P0 — 基础架构搭建

**目标**: 建立 v3 前端骨架，能独立运行在 3001 端口

| 任务编号 | 任务 | 预估时间 | 依赖 | 交付物 |
|----------|------|----------|------|--------|
| P0-1 | 端口 3001 启动配置 | 0.5h | — | `next dev -p 3001` 可运行 |
| P0-2 | v3 layout.tsx + AppShell | 2h | P0-1 | 独立布局，不继承 v2 |
| P0-3 | Sidebar 导航组件 | 2h | P0-2 | 10 个一级导航（含三屏交易），SACG 层色条 |
| P0-4 | TopBar 组件 | 1h | P0-2 | 面包屑+搜索+通知+用户 |
| P0-5 | 路由骨架 (所有 page.tsx 占位) | 2h | P0-2 | 20+ 路由文件创建，`/` 重定向到 `/v3/dashboard` |
| P0-6 | Zustand stores 初始化 (10 个) | 4h | P0-2 | `src/stores/v3/` 下全部 store 文件（含 three-screens-store） |
| P0-7 | API Client 封装 | 3h | P0-2 | `src/lib/v3/api/client.ts` + 19 个域模块 |
| P0-8 | SSE Hook (useSSE) | 2h | P0-7 | 9 种事件类型标准化处理 |
| P0-9 | Primitive 组件库 (15 个) | 4h | P0-2 | Button/Card/Badge/Dialog 等 |
| P0-10 | Inline SVG 图标集 | 2h | P0-2 | 20+ 个常用图标 |
| P0-11 | 错误边界 + 全局错误处理 | 1h | P0-2 | ErrorBoundary 组件 |
| P0-12 | useAPI Hook | 1h | P0-7 | 统一 API 调用 Hook |

**P0 总预估**: 24.5h (约 3 个工作日)

**P0 验收标准**:
- `localhost:3001/v3/dashboard` 可访问
- Sidebar 导航可切换到所有子路由
- API Client 可成功调用至少 3 个现有端点
- SSE 连接可建立并接收事件
- 所有 Primitive 组件在 Storybook 或测试页中可见

### P1 — 核心交易功能

**目标**: 完成 AI Skill 交易核心页面，用户可通过对话触发 S 系列链

| 任务编号 | 任务 | 预估时间 | 依赖 | 交付物 |
|----------|------|----------|------|--------|
| P1-1 | ChatPanel 组件 | 3h | P0 | 消息列表+输入框+快捷命令 |
| P1-2 | MessageList 虚拟滚动 | 2h | P1-1 | 长消息列表性能优化 |
| P1-3 | StreamingIndicator 组件 | 1h | P0-8 | 流式输出实时渲染 |
| P1-4 | SSE 事件→Store 分发器 | 3h | P0-8, P0-6 | dispatchSSEEvent 完成 |
| P1-5 | ChainTracker 组件 | 4h | P1-4 | S 系列链步骤可视化 |
| P1-6 | ReflectorDecisionBadge | 2h | P1-5 | 6 种 Reflector 决策可视化 |
| P1-7 | CrossValidationPanel | 3h | P1-5 | 三链交叉验证投票 UI |
| P1-8 | SenseConfidenceGauge | 2h | P0-6 | S 层意图置信度仪表 |
| P1-9 | ThreeLayerValueModel | 2h | P1-8 | 三层价值模型展开 UI |
| P1-10 | 交易参数管理面板 | 3h | P0-7 | 迁移自 v2 SettingsTrading |
| P1-11 | 策略 CRUD 面板 | 4h | P0-7 | 迁移自 v2 StrategyPanel |
| P1-12 | API 密钥管理面板 | 3h | P0-7 | 迁移自 v2 SettingsAPI |
| P1-13 | 可复用模块迁移 (15 个) | 4h | P0 | types, intent, trading-mode 等 |
| P1-14 | TradeScreen 整合 | 3h | P1-1~P1-12 | `/v3/dashboard/trade` 完整页面 |
| P1-15 | DataCard + MarketSnapshot | 2h | P0-7 | 数据卡片+市场概览 |
| P1-16 | ThreeScreens 总览页 | 3h | P0 | `/v3/dashboard/three-screens` 三屏状态仪表盘 |
| P1-17 | Screen1 战略层面板 | 4h | P1-16 | 七维牛熊评分 + MA200 方向锚 + 大师辩论 |
| P1-18 | Screen2 战术层面板 | 4h | P1-16, P1-17 | 三大预设价位 + 回测验证 + 贝叶斯优化 + 方向约束等待态 |
| P1-19 | Screen3 执行层面板 | 4h | P1-16, P1-18 | A7→A4→Gate→A5→A6→A9 流水线可视化 + 持仓状态 |
| P1-20 | Pipeline 全链路页 | 3h | P1-17~P1-19 | Screen1→2→3 方向约束传递可视化 |

**P1 总预估**: 61h (约 8 个工作日)

**P1 验收标准**:
- `/v3/dashboard/trade` 可正常对话，消息流式输出
- S 系列链触发后，ChainTracker 实时更新步骤状态
- Reflector 决策可视化正确展示 6 种决策类型
- 交易参数/策略/API密钥 CRUD 全部可用
- 15 个可复用模块全部迁移并可在 v3 中引用
- `/v3/dashboard/three-screens` 三屏总览页可访问
- Screen1 七维牛熊评分 + 方向锚正确渲染
- Screen2 方向约束等待态正常工作，预设价位表完整
- Screen3 执行流水线 A7→A4→Gate→A5→A6→A9 可视化
- Pipeline 页面展示 Screen1→2→3 方向约束传递链路

### P2 — 经典交易 + 基本面

**目标**: 完成经典交易系统全链路 + 基本面分析面板

| 任务编号 | 任务 | 预估时间 | 依赖 | 交付物 |
|----------|------|----------|------|--------|
| P2-1 | ClassicScreen 主框架 | 3h | P0 | 经典交易页面骨架 |
| P2-2 | PhaseIndicator (C0-C8) | 2h | P2-1 | 阶段进度条 |
| P2-3 | ClassicPhasePanel 通用组件 | 3h | P2-2 | 各阶段通用面板 |
| P2-4 | C1 MacroScan 面板 | 3h | P2-3 | 宏观扫描可视化 |
| P2-5 | C2 UniverseScan 面板 | 3h | P2-3 | 品种池扫描表格 |
| P2-6 | C3 GateCheck 面板 | 2h | P2-3 | 门禁检查结果 |
| P2-7 | C4 ArenaReview 面板 | 3h | P2-3 | 竞技场评审 UI |
| P2-8 | C5 StrategySelect 面板 | 3h | P2-3 | 策略选择+对比 |
| P2-9 | C6 SignalReview 面板 | 2h | P2-3 | 信号审查列表 |
| P2-10 | C7 ExitMonitor 面板 | 3h | P2-3 | 离场监控实时追踪 |
| P2-11 | C8 TrackingAudit 面板 | 2h | P2-3 | 追踪审计日志 |
| P2-12 | GovernanceFlow 组件 | 4h | P2-1 | Draft→Gate→Approval→Apply→Audit 流程 UI |
| P2-13 | FundamentalScreen 骨架 | 2h | P0 | 基本面总览 |
| P2-14 | OnchainMetrics 面板 | 3h | P2-13 | 链上数据可视化 |
| P2-15 | MacroDashboard 面板 | 3h | P2-13 | 宏观经济指标 |
| P2-16 | SentimentHeatmap | 3h | P2-13 | 情绪热力图 (SVG) |
| P2-17 | 基本面子页面 (10 个) | 6h | P2-13 | overview/flow/valuation/narrative/news/breadth/calendar/intermarket |

**P2 总预估**: 52h (约 6-7 个工作日)

**P2 验收标准**:
- `/v3/dashboard/classic` 可完整展示 C0-C8 全链
- 治理流程 5 阶段可正常流转
- `/v3/dashboard/fundamental` 所有 11 个子页面可访问
- 基本面数据可通过 API 正确渲染

### P3 — SACG 高级可视化

**目标**: 完成 SACG 四层完整可视化 + 记忆管理 + 治理 + 产物中台

| 任务编号 | 任务 | 预估时间 | 依赖 | 交付物 |
|----------|------|----------|------|--------|
| P3-1 | MonitorScreen 骨架 | 2h | P0 | SACG 监控四层 Tab |
| P3-2 | SACGVisualizer 总览 | 4h | P3-1 | 四层状态全局面板 |
| P3-3 | DAGGraphView | 6h | P3-1 | DAG 图 SVG 渲染 (节点+边+动画) |
| P3-4 | DAGGraphView 动态更新 | 3h | P3-3 | 节点状态实时更新动画 |
| P3-5 | ReflectorPanel (完整) | 4h | P3-1 | 6 决策历史列表+详情 |
| P3-6 | BACTimeline | 4h | P3-1 | B→A→C 压缩可视化时间线 |
| P3-7 | HistoryPlayer | 4h | P3-6 | Play/Pause/Seek 回放控件 |
| P3-8 | MemoryScreen 骨架 | 2h | P0 | 记忆系统总览 |
| P3-9 | DZEChainView | 4h | P3-8 | D-Z-E 工程链可视化 |
| P3-10 | MemoryTimeline | 3h | P3-8 | 记忆演进时间线 |
| P3-11 | GovernanceScreen | 3h | P0 | 治理面板完整页面 |
| P3-12 | ReportsScreen | 3h | P0 | 产物中台列表+详情 |
| P3-13 | ArtifactFilter + 搜索 | 2h | P3-12 | 按链/层/时间/类型筛选 |
| P3-14 | DashboardScreen 三屏概览 | 4h | P1, P2, P3-2 | 主控台三屏概览整合 |
| P3-15 | CommandPalette | 3h | P0-2 | Cmd+K 快捷操作面板 |

**P3 总预估**: 51h (约 6-7 个工作日)

**P3 验收标准**:
- `/v3/dashboard/monitor` 四层可视化完整可用
- DAG 图可渲染节点+边，支持动态更新
- BAC 压缩时间线可播放回放
- `/v3/dashboard/memory` D-Z-E 链可视化可用
- `/v3/dashboard/governance` 治理流程完整
- `/v3/dashboard/reports` 产物筛选+详情可用
- 主控台概览整合三屏交易系统状态 + SACG 监控数据

---

## 附录

### 附录 A：92 个 API 端点完整索引

#### 1. 任务执行 (/api/task) — 5 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| POST | /api/task | 创建任务 (写 task 文件 + 触发执行) |
| GET | /api/task | 查询任务状态 (支持 list/detail 两种模式) |
| POST | /api/task/stream | SSE 流式任务追踪 |
| POST | /api/task/confirm | 确认执行 (用户二次确认) |
| GET | /api/task/result/[id] | 获取任务结果 |

#### 2. 对话 (/api/chat) — 2 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| POST | /api/chat | 发送对话消息 (SSE 流式响应) |
| GET | /api/chat | 获取会话历史 |

#### 3. 市场数据 (/api/market) — 8 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | /api/market/snapshot | 市场数据快照 (价格/费率/持仓) |
| POST | /api/market/query | 市场数据查询 (自定义参数) |
| GET | /api/market/route | 市场路由信息 |
| GET | /api/market/segments | 市场细分数据 |
| GET | /api/market/campaigns | 营销活动数据 |
| GET | /api/market/content | 市场内容数据 |
| GET | /api/market/distribution | 市场分布数据 |
| GET | /api/market/effectiveness | 市场效果数据 |
| GET | /api/market/audit | 市场审计数据 |

#### 4. 交易 (/api/trade) — 1 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | /api/trade/balance | 查询交易余额 (OKX API 代理) |

#### 5. 配置 (/api/config) — 14 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | /api/config/api-keys | 获取 API 密钥列表 |
| POST | /api/config/api-keys | 创建 API 密钥 (加密存储) |
| PUT | /api/config/api-keys | 更新 API 密钥 |
| DELETE | /api/config/api-keys | 删除 API 密钥 |
| POST | /api/config/api-keys/test | 测试 API 密钥连通性 |
| GET | /api/config/trading-params | 获取交易参数 |
| PATCH | /api/config/trading-params | 更新交易参数 |
| POST | /api/config/trading-params/pause | 暂停交易 |
| POST | /api/config/trading-params/resume | 恢复交易 |
| POST | /api/config/trading-params/reset-daily | 重置日亏损 |
| GET | /api/config/strategies | 获取策略列表 |
| POST | /api/config/strategies | 创建策略 |
| PATCH | /api/config/strategies | 更新策略 |
| DELETE | /api/config/strategies | 删除策略 |
| POST | /api/config/strategies/parse | 策略自然语言解析 |
| POST | /api/config/strategies/[id]/apply | 应用策略 (创建定时任务) |
| POST | /api/config/strategies/[id]/pause | 暂停策略 |
| GET | /api/config/channels | 获取通信渠道列表 |
| POST | /api/config/channels | 创建通信渠道 |
| PATCH | /api/config/channels | 更新通信渠道 |
| DELETE | /api/config/channels | 删除通信渠道 |
| POST | /api/config/channels/[id]/test | 测试通信渠道 |

#### 6. 用户 (/api/user) — 4 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | /api/user/me | 获取当前用户信息 |
| POST | /api/user/signin | 用户登录 |
| GET | /api/user/signin | 获取登录状态 |
| POST | /api/user/checkin | 每日签到 (POST) |
| GET | /api/user/checkin | 签到状态 (GET) |

#### 7. 研报 (/api/reports) — 1 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | /api/reports | 获取研报列表/详情 |

#### 8. 监控 (/api/monitor) — 3 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | /api/monitor/events | 获取监控事件列表 |
| GET | /api/monitor/stats | 获取监控统计数据 |
| GET | /api/monitor/stream | SSE 监控流 |

#### 9. 意图 (/api/intent) — 2 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | /api/intent/analyze | 意图分析 (GET 模式) |
| POST | /api/intent/memory | 意图记忆写入 |
| GET | /api/intent/memory | 意图记忆读取 |

#### 10. 笔记本 (/api/notebook) — 8 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | /api/notebook | 获取笔记本列表 |
| POST | /api/notebook | 创建笔记本 |
| PATCH | /api/notebook | 更新笔记本 |
| GET | /api/notebook/state | 获取状态 |
| PUT | /api/notebook/state | 更新状态 |
| GET | /api/notebook/step | 获取步骤 |
| POST | /api/notebook/step | 创建步骤 |
| PATCH | /api/notebook/step | 更新步骤 |
| GET | /api/notebook/tasks | 获取任务列表 |
| POST | /api/notebook/tasks | 创建任务 |
| PATCH | /api/notebook/tasks | 更新任务 |
| POST | /api/notebook/sync | 同步笔记本 |
| GET | /api/notebook/sync | 获取同步状态 |

#### 11. 运维 (/api/ops) — 2 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | /api/ops/queues | 获取任务队列信息 |
| GET | /api/ops/decision-levels | 获取决策层级信息 |

#### 12. 编排 (/api/orchestrate) — 2 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| POST | /api/orchestrate | 触发编排执行 |
| GET | /api/orchestrate | 获取编排状态 |

#### 13. 链路产物 (/api/chain) — 1 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | /api/chain/artifacts | 获取链路产物列表 |

#### 14. 治理 (/api/board) — 5 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | /api/board/proposals | 获取策略提案列表 |
| GET | /api/board/proposals/[id] | 获取提案详情 |
| GET | /api/board/approval/pending | 获取待审批列表 |
| GET | /api/board/approval/summary | 获取审批摘要 |
| POST | /api/board/approval/[id] | 提交审批操作 |
| GET | /api/board/review | 获取绩效评审 |

#### 15. 基本面 (/api/fundamental) — 2 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | /api/fundamental/[...path] | 获取基本面数据 (通配路径) |
| POST | /api/fundamental/[...path] | 提交基本面查询 |

#### 16. 消息流 (/api/feed) — 1 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | /api/feed | 获取消息流/产物 Feed |

#### 17. 认证 (/api/auth) — 1 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| * | /api/auth/[...nextauth] | NextAuth.js 认证路由 (GET/POST) |

#### 18. 产物文件 (/api/artifact) — 1 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | /api/artifact | 获取产物文件列表/内容 |

#### 19. 注册 (/api/register) — 1 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| POST | /api/register | 用户注册 |

### 附录 B：52 个 OS 模块在前端的映射关系

| 编号 | OS 模块 | SACG 层 | v3 前端映射 | 路由 |
|------|---------|---------|-------------|------|
| 1 | IntentRouter | S | SenseConfidenceGauge + ThreeLayerValueModel | /v3/dashboard/trade |
| 2 | FallbackEngine | S | useSessionStore.lastIntent | 贯穿所有页面 |
| 3 | IntentMemory | S | MemoryTimeline (意图记忆部分) | /v3/dashboard/memory |
| 4 | SmartRouter | S | ChatInput (意图预提示) | /v3/dashboard/trade |
| 5 | GraphPlanner | A | DAGGraphView | /v3/dashboard/monitor/arrange |
| 6 | ChainOrchestrator | A | ChainTracker + PhaseIndicator | /v3/dashboard/trade |
| 7 | DynamicChain Executor | C | ChainStepCard + ReflectorDecisionBadge | /v3/dashboard/trade |
| 8 | ReflectEngine | C | ReflectorPanel + CrossValidationPanel | /v3/dashboard/monitor/compute |
| 9 | GraphPlanner Runner | C | ChainTracker (动态更新) | /v3/dashboard/trade |
| 10 | BAC Compressor | G | BACTimeline + HistoryPlayer | /v3/dashboard/monitor/graph |
| 11 | Checkpoint Manager | G | HistoryPlayer (Checkpoint 跳转) | /v3/dashboard/monitor/graph |
| 12 | TradingGate | C | BalanceCard (门禁状态) | /v3/dashboard/trade |
| 13 | TradingParams Registry | C | TradingParamsEditor | /v3/dashboard/settings/trading-params |
| 14 | StrategyEngine | C | StrategyManager | /v3/dashboard/settings/strategies |
| 15 | StrategyLibrary | C | StrategyManager (模板列表) | /v3/dashboard/settings/strategies |
| 16 | Backtester | C | 回测结果面板 | /v3/dashboard/trade/strategies/[id] |
| 17 | CreditsManager | C | 积分面板 | /v3/dashboard/settings |
| 18 | UserSystem | S | useAuthStore + UserProfileCard | 贯穿所有页面 |
| 19 | AuthService | S | useAuthStore | 贯穿所有页面 |
| 20 | ConfigStore | G | useApiConfigStore | /v3/dashboard/settings |
| 21 | ArtifactAssessor | S | ArtifactFilter (产物评分) | /v3/dashboard/reports |
| 22 | ChatEngine | S | ChatPanel + useSessionStore | /v3/dashboard/trade |
| 23 | LLMBridge | C | StreamingIndicator (流式状态) | /v3/dashboard/trade |
| 24 | ChainExecutor | C | ChainTracker (执行状态) | /v3/dashboard/trade |
| 25 | SkillInvoker | C | ChainStepCard (Skill 子节点) | /v3/dashboard/trade |
| 26 | ArtifactWriter | G | ArtifactDetail | /v3/dashboard/reports/[id] |
| 27 | TaskManager | C | useChainStore (任务追踪) | /v3/dashboard/trade |
| 28 | MonitorBus | G | useMonitorStore (事件总线) | /v3/dashboard/monitor |
| 29 | TokenMonitor | C | TokenMonitorBadge | 贯穿所有页面 |
| 30 | CostKeeper | C | 交易成本统计面板 | /v3/dashboard/trade |
| 31 | SkipGate | C | ChainStepCard (SKIP 状态) | /v3/dashboard/trade |
| 32 | CompressorAdapter | G | BACTimeline | /v3/dashboard/monitor/graph |
| 33 | BridgeClient | C | 连接状态指示 | TopBar |
| 34 | KnowledgeRAG | S | 知识源选择 (ai_skill: 2/6) | /v3/dashboard/trade |
| 35 | Encryption | G | ApiKeyManager (密钥脱敏) | /v3/dashboard/settings/api-keys |
| 36 | UID Generator | S | 后端工具，前端不直接映射 | — |
| 37 | ReflectionGates | C | ReflectorPanel (决策逻辑) | /v3/dashboard/monitor/compute |
| 38 | StrategyTaskOrder | C | StrategyManager (任务关联) | /v3/dashboard/settings/strategies |
| 39 | StrategyLifecycle | C | StrategyManager (生命周期) | /v3/dashboard/settings/strategies |
| 40 | StrategyArtifacts | G | ArtifactDetail (策略产物) | /v3/dashboard/reports/[id] |
| 41 | MarketDataAdapter | C | MarketSnapshot | /v3/dashboard/trade |
| 42 | ClassicSystemAPI | C | ClassicPhasePanel (全阶段) | /v3/dashboard/classic |
| 43 | ClassicSystemBridge | C | ClassicScreen (桥接层) | /v3/dashboard/classic |
| 44 | ClassicSystemClient | C | ClassicScreen (客户端层) | /v3/dashboard/classic |
| 45 | GovernanceBoard | A | GovernanceFlow + GovernanceScreen | /v3/dashboard/governance |
| 46 | NotebookStepController | C | NotebookPanel (步骤控制) | /v3/dashboard/memory |
| 47 | OrchestrationPanel | A | DAGGraphView (编排可视化) | /v3/dashboard/monitor/arrange |
| 48 | LLMBridge (Orchestration) | A | DAGGraphView (节点耗时) | /v3/dashboard/monitor/arrange |
| 49 | MarketDataBridge | A | MarketSnapshot (数据源) | /v3/dashboard/trade |
| 50 | SuperpowerLLMBridge | A | SenseConfidenceGauge (SuperWorker) | /v3/dashboard/monitor/sense |
| 51 | SkillLLMBridgeAdapter | A | ChainStepCard (Skill 调用状态) | /v3/dashboard/trade |
| 52 | GraphReflectionBridge | G | BACTimeline + HistoryPlayer | /v3/dashboard/monitor/graph |

### 附录 C：可复用模块迁移清单

| 模块 | 当前路径 | 迁移目标 | 迁移方式 | 难度 | 注意事项 |
|------|----------|----------|----------|------|----------|
| types/index.ts | src/types/ | 直接引用 | 无需复制，v3 直接 import | 低 | 保持向后兼容 |
| intent/fallback-engine.ts | src/lib/intent/ | src/lib/v3/intent/ | 复制+微调 | 低 | 确认依赖路径 |
| intent/intent-memory.ts | src/lib/intent/ | src/lib/v3/intent/ | 复制+微调 | 低 | 文件路径需适配 |
| trading-mode.ts | src/lib/ | src/lib/v3/ | 复制 | 低 | 纯枚举定义 |
| strategy/types.ts | src/lib/strategy/ | src/lib/v3/strategy/ | 复制 | 低 | 纯类型定义 |
| reflection-gates.ts | src/lib/ | src/lib/v3/ | 复制+适配 | 低 | 部分函数需服务端调用，前端仅用决策逻辑 |
| monitor-bus.ts | src/lib/ | src/lib/v3/ | 仅前端消费端 | 中 | 前端不 emit，仅接收 |
| token-monitor.ts | src/lib/ | src/lib/v3/ | 复制 | 低 | 监控逻辑可复用 |
| scheduler/cost-keeper.ts | src/lib/scheduler/ | src/lib/v3/scheduler/ | 复制 | 低 | Token 计费纯逻辑 |
| scheduler/skip-gate.ts | src/lib/scheduler/ | src/lib/v3/scheduler/ | 复制 | 低 | 跳过决策纯逻辑 |
| compressor-adapter/ | src/lib/ | src/lib/v3/ | 复制 | 低 | BAC 适配接口 |
| bridge-client.ts | src/lib/ | src/lib/v3/ | 复制+适配 | 中 | HTTP 调用需走 API Client |
| uid.ts | src/lib/ | src/lib/v3/ | 复制 | 低 | 纯函数 |
| encryption.ts | src/lib/ | src/lib/v3/ | 复制 | 低 | AES 加密逻辑 |
| intent/smart-router.ts | src/lib/intent/ | src/lib/v3/intent/ | 复制+重写 | 高 | LLM 调用需改为 API 调用 |
| knowledge-rag.ts | src/lib/ | src/lib/v3/ | 重写 | 高 | 无文件系统，需改为 API 调用 |
| auth.ts | src/lib/ | src/lib/v3/ | 适配 | 中 | 改用 NextAuth Session |

### 附录 D：风险与依赖说明

| 风险 | 严重度 | 概率 | 影响 | 缓解策略 |
|------|--------|------|------|----------|
| v2 dashboard/page.tsx 拆分遗漏 | 高 | 中 | 拆分后功能缺失 | 先做完整的功能清单对照表，逐项验证 |
| SACG 四层可视化 SVG 复杂度超预期 | 中 | 高 | P3 延期 | 准备 CSS 降级方案，先用简单表格展示 |
| 无 npm 安装限制导致无法引入必要工具 | 中 | 确定 | 开发效率降低 | 所有工具函数手写，SVG 手绘 |
| SSE 连接稳定性 | 中 | 中 | 实时数据丢失 | 自动重连 + 指数退避 + 本地缓存 |
| task-manager.ts 127KB 拆分引入回归 | 高 | 中 | 核心链路执行失败 | 拆分后运行全部现有测试 |
| v3 路由与 v2 冲突 | 低 | 低 | 页面路由异常 | v3 路由全部在 `/v3/` 前缀下 |
| Zustand Store 跨域数据同步 | 中 | 中 | 数据不一致 | 严格按领域划分，跨域通过事件通信 |
| Tailwind v4 无配置文件限制 | 低 | 确定 | 自定义值受限 | 通过 CSS @theme 和 @utility 自定义 |
| 基本面数据 API 响应格式不稳定 | 中 | 中 | 渲染异常 | API Client 做数据校验和降级 |
| 经典系统 13 子标签页工作量超预期 | 高 | 高 | P2 延期 | 优先实现核心 C0-C5，C6-C8 可延后 |
| 三屏交易系统数据联动复杂 | 中 | 中 | 数据不一致 | 使用共享 Zustand store 作为数据源 |
| 移动端适配延后 | 低 | 确定 | 移动端体验差 | P0-P3 仅桌面端，移动端单独迭代 |

---

> 文档版本: v3.0 | 总行数: (见文件实际行数) | 覆盖范围: 架构规划全量
> 关联文档: ARCHITECTURE.md, UI_SPEC.md, UI_ROADMAP.md, CHAIN_ORCHESTRATOR.md, FRONTEND_WB_INTEGRATION.md
