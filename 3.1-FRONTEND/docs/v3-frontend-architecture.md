# DreamBuddy v3.1 前端技术文档

> 版本: v3.1 | 日期: 2026-10-10 | 状态: 已实现（P0-P3 全部完成）
> 定位: WorkBuddy OS SACG 四层架构前端实现
> 约束: 独立端口 3001 运行，与 3.0 前端（3-FRONTEND/dream-universal-gateway）隔离

---

## 第一章：项目概述与目标

### 1.1 项目定位

DreamBuddy v3.1 前端是 AI 驱动的加密货币交易平台的全量重构版本。它以 WorkBuddy OS 的 SACG (Sense-Arrange-Compute-Graph) 模型作为顶层设计约束，将前端架构从"以页面为中心的 God Component 模式"彻底转向"以 SACG 四层架构为骨架的领域驱动前端模式"。

核心定位公式:

```
v3.1 Frontend = SACG 四层可视化 + 双交易模式 UI + 三屏交易系统 + SSE 流式交互 + 认知记忆系统
```

### 1.2 核心目标与达成状态

| 编号 | 目标 | 对齐维度 | 验收标准 | 状态 |
|------|------|----------|----------|------|
| G1 | SACG 架构完全对齐 | 全局 | 四层各有独立可视化面板，层间数据流可追踪 | ✅ 已完成 |
| G2 | 消除 God Component | 架构 | 单文件不超过 300 行，最大组件不超过 5 个 useState | ✅ 已完成 |
| G3 | 单一职责状态管理 | Store | 12 个 Zustand store 各管各的领域，无跨域耦合 | ✅ 已完成 |
| G4 | 端口隔离部署 | 运维 | 3.0 跑在 3000，v3.1 跑在 3001，独立项目 | ✅ 已完成 |
| G5 | 模块化 API 集成 | 集成 | 20 个 API 域各自封装，统一错误处理，SSE 标准化 | ✅ 已完成 |
| G6 | 双交易模式支持 | 业务 | AI Skill + Classic 两种模式各自有完整 UI 链路 | ✅ 已完成 |
| G7 | 三屏交易系统独立页面 | 业务 | Screen1/2/3 + Pipeline 各自独立面板 + 数据联动 + 方向约束链路可视化 | ✅ 已完成 |
| G8 | 认知记忆系统 | 业务 | recall/record/verify 认知闭环 + 用户记忆 + 技能/文档索引 | ✅ 已完成 |

### 1.3 技术栈

| 维度 | 选型 | 说明 |
|------|------|------|
| 框架 | Next.js 15.4 (App Router) | `src/app/` 目录结构，Server + Client Component 混合渲染 |
| 样式 | Tailwind CSS v4 (`@tailwindcss/postcss`) | 无 `tailwind.config.js`，通过 CSS `@theme` 定义设计 token |
| 语言 | TypeScript 5.7 (strict) | 所有组件、store、工具函数均为 `.ts`/`.tsx` |
| 状态管理 | Zustand 5.0 | 12 个 store 按领域拆分 |
| 流式通信 | SSE (Server-Sent Events) | 9 种事件类型标准化处理 |
| 数据可视化 | Recharts 3.8 + SVG | 三屏图表、基本面图表使用 recharts，DAG/BAC 使用原生 SVG |
| AI SDK | @ai-sdk/openai 1.0 + @ai-sdk/react 1.0 | AI 驱动的对话和意图处理 |
| 认证 | NextAuth.js v5 (Session) + @auth/prisma-adapter | Prisma 数据库适配器，支持 Session 管理 |
| 数据库 | Prisma 6.19 + @prisma/client | 用户、提案、审批等持久化 |
| 加密 | bcryptjs 3.0 | 密码哈希 |
| Markdown | react-markdown 10.1 | 消息和报告渲染 |
| 图标 | Inline SVG (V3InlineSVG) | 不使用图标库，通过 V3InlineSVG 组件统一管理 |
| ID 生成 | nanoid 5.1 | 唯一 ID 生成 |
| 类型校验 | zod 3.24 | API 请求/响应类型验证 |

### 1.4 项目隔离策略

```
3.0 Frontend (PORT 3000)              3.1 Frontend (PORT 3001)
3-FRONTEND/dream-universal-gateway/    3.1-FRONTEND/
┌─────────────────────────┐            ┌─────────────────────────────┐
│ src/app/                │            │ src/app/                    │
│ ├── dashboard/          │            │ ├── dashboard/             │
│ ├── chat/               │            │ │   ├── trade/             │
│ ├── login/              │            │ │   ├── classic/           │
│ └── api/                │            │ │   ├── fundamental/       │
│                         │            │ │   ├── three-screens/    │
│ (v2 三栏对话式界面)      │            │ │   ├── monitor/          │
│                         │            │ │   ├── memory/            │
│                         │            │ │   ├── settings/          │
│                         │            │ │   ├── reports/           │
│                         │            │ │   ├── ranking/           │
│                         │            │ │   ├── governance/        │
│                         │            │ │   └── ...                │
│                         │            │ ├── chat/                  │
│                         │            │ ├── board/ (治理/审批)      │
│                         │            │ ├── login/ register/         │
│                         │            │ └── api/ (96+ 端点)         │
└─────────────────────────┘            └─────────────────────────────┘
```

隔离要点:

1. **独立项目**: 3.1-FRONTEND 是独立的 Next.js 项目，有自己的 `package.json`、`tsconfig.json`、`next.config.ts`
2. **路由无前缀**: 页面直接在 `src/app/` 下，通过 `/dashboard/...` 路径访问（非 `/v3/dashboard`）
3. **API 自建**: 3.1 拥有独立的 API Routes（96+ 端点），不共享 3.0 的 API
4. **Store 独立**: Store 在 `src/stores/` 下，不修改 3.0 的 stores
5. **组件独立**: 组件在 `src/components/features/` 和 `src/components/V3*.tsx` 下
6. **启动方式**: `next dev -p 3001` 启动

---

## 第二章：实现现状

### 2.1 代码统计

| 维度 | 数据 |
|------|------|
| 页面路由 (page.tsx) | 56 个 |
| API 路由 (route.ts) | 96+ 个 |
| 组件文件 (features/) | 100+ 个 |
| 基础组件 (V3*.tsx) | 8 个 (V3Card/V3Button/V3Badge/V3StatusDot/V3Tooltip/V3InlineSVG/V3Spinner/V3Empty) |
| Store | 12 个 (含 index.ts) |
| Lib 文件 | 160+ 个 (含 planner/ 21文件、orchestration/、SACG五训练循环、cognitive/、case/ 等) |
| Layout 文件 | 3 个 (root / dashboard / classic) |

### 2.2 功能域与页面映射

| 功能域 | 路由 | 页面数 | 组件数 | 状态 |
|--------|------|--------|--------|------|
| 概览 | `/dashboard` | 1 | LiveStatusPanel | ✅ |
| AI 交易 | `/dashboard/trade` | 1 | ChatPanel + 18个Chat子组件 | ✅ |
| 交易榜单 | `/dashboard/ranking` | 1 | 4个组件 (DecisionCard/RankingCard/RankingMonitor/PrefillOrderBanner) | ✅ |
| 经典系统 | `/dashboard/classic` | 2 (含 [subtab]) | 8个组件 (Indicator/GovernanceFlow/Phase/Generation/Management/Signals等) | ✅ |
| 基本面 | `/dashboard/fundamental` | 1 | 17个组件 (Flow/Macro/Onchain/Valuation/Sentiment/Intermarket/Breadth/WhaleTracker/UTXOAge/MVRVZone/SentimentHeatmap等) | ✅ |
| 三屏系统 | `/dashboard/three-screens` | 6 (总览+screen1/2/3+pipeline+[screen]) | Screen1/2/3Panel + PipelineView + 3个charts | ✅ |
| SACG 监控 | `/dashboard/monitor` | 5 (总览+compute/graph/arrange/sense) | 5个组件 (ReflectorPanel/CrossValidationPanel/SenseConfidenceGauge/SACGOverview/DAGGraphView) | ✅ |
| 记忆管理 | `/dashboard/memory` | 5 (总览+user/dze/skills/docs) | 6个组件 (RecordExperienceForm/MemoryTimeline/DZEChainView/SkillIndexView/DocIndexView/MemoryTabNav) | ✅ |
| 设置 | `/dashboard/settings` | 1 | 5个组件 (ApiKeyManager/TradingParamsPanel/StrategyManager/CompletenessWizard/ChannelManager) | ✅ |
| 治理 | `/dashboard/governance` | 1 | GovernanceScreen | ✅ |
| 人工审批 | `/board/approval` | 1 | GovernanceScreen (共享) | ✅ |
| 提案管理 | `/board/proposals` | 2 (列表+[id]) | — | ✅ |
| 绩效评审 | `/board/review` | 1 | — | ✅ |
| 报告 | `/dashboard/reports` | 2 (列表+[id]) | ReportsScreen | ✅ |
| Notebook | `/dashboard/notebook` | 1 | 7个组件 (NotebookPanel/ArtifactGallery/TaskCard/ActiveDZEChain/StepActionMenu/StepProgress/ActiveStrategyChain) | ✅ |
| Token监控 | `/dashboard/token-monitor` | 1 | TokenMonitorPanel + TokenMonitorBadge | ✅ |
| 图压缩 | `/dashboard/graph-compression` | 1 | GraphCompressionVisualizer | ✅ |
| Chat | `/chat` | 1 | 共享Chat组件 | ✅ |
| 工作流 | `/dashboard/workflow` | 1 | 3个组件 (WorkflowCard/WorkflowStatusBadge/WorkflowStepList) | ✅ |
| 情报流 | `/dashboard/feed` | 1 | — | ✅ |
| 情绪看板 | `/dashboard/mood-board` | 1 | MoodBoardPanel (共享) | ✅ |
| 简报 | `/dashboard/briefing` | 1 | — | ✅ |
| BDSM | `/dashboard/bdsm` | 1 | — | ✅ |
| 运维 | `/dashboard/ops` | 1 | — | ✅ |
| 元标注 | `/dashboard/meta-labeling` | 1 | — | ✅ |
| 市场营销 | `/dashboard/market` | 6 (总览+segments/effectiveness/distribution/campaigns/audit) | — | ✅ |
| 测试可视化 | `/dashboard/test-visualization` | 1 | — | ✅ |
| 登录/注册/验证 | `/login` `/register` `/verify-email` | 3 | — | ✅ |
| 充值 | `/recharge` | 1 | — | ✅ |

### 2.3 侧边栏导航

侧边栏定义在 [dashboard/layout.tsx](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND/src/app/dashboard/layout.tsx) 中，共 12 个一级导航项:

| 序号 | 标签 | 路由 | 图标 | 备注 |
|------|------|------|------|------|
| 1 | 概览 | `/dashboard` | ◉ | 主控台 |
| 2 | AI 交易 | `/dashboard/trade` | ⚡ | ChatPanel + SSE 流式 |
| 3 | 交易榜单 | `/dashboard/ranking` | 🏆 | 决策排行+预填单 |
| 4 | 经典系统 | `/dashboard/classic` | 📊 | C0-C8 全链 |
| 5 | 基本面 | `/dashboard/fundamental` | 📈 | 17个分析组件 |
| 6 | 三屏系统 | `/dashboard/three-screens` | 🖥 | Elder 三屏 |
| 7 | SACG 监控 | `/dashboard/monitor` | 🔍 | 四层可视化 |
| 8 | 记忆管理 | `/dashboard/memory` | 🧠 | 用户/DZE/技能/文档 |
| 9 | 设置 | `/dashboard/settings` | ⚙ | API/交易/策略/渠道 |
| 10 | 治理 | `/dashboard/governance` | 🏛 | 治理流程 |
| 11 | 人工审批 | `/board/approval` | 🛡️ | Badge 显示待审批数 |
| 12 | 报告 | `/dashboard/reports` | 📋 | 产物中台 |

侧边栏特性:
- 可折叠（折叠时宽 56px / 展开时 192px）
- 人工审批项支持 Badge（轮询 `/api/board/approval/pending`，30s 间隔）
- 路由高亮: `pathname === item.href` 或 `pathname.startsWith(item.href)`

---

## 第三章：架构设计

### 3.1 路由架构

#### 完整页面路由映射

```
src/app/
├── layout.tsx                        → RootLayout (全局 html/body)
├── page.tsx                           → 首页 (重定向到 /dashboard)
├── login/page.tsx                     → 登录页
├── register/page.tsx                  → 注册页
├── verify-email/page.tsx              → 邮箱验证页
├── recharge/page.tsx                  → 充值页
├── chat/page.tsx                      → 独立聊天页
│
├── dashboard/
│   ├── layout.tsx                     → DashboardLayout (Sidebar + Content)
│   ├── page.tsx                       → 概览 (主控台)
│   │
│   ├── trade/page.tsx                 → AI 交易 (ChatPanel + ChainTracker)
│   ├── ranking/page.tsx               → 交易榜单
│   ├── classic/
│   │   ├── layout.tsx                 → Classic 独立 layout
│   │   ├── page.tsx                   → 经典系统入口
│   │   └── [subtab]/page.tsx          → 经典子标签 (动态路由)
│   ├── fundamental/page.tsx           → 基本面分析
│   │
│   ├── three-screens/
│   │   ├── page.tsx                   → 三屏总览
│   │   ├── screen1/page.tsx           → 战略层（周线方向）
│   │   ├── screen2/page.tsx           → 战术层（日线预设）
│   │   ├── screen3/page.tsx           → 执行层（实时执行）
│   │   ├── pipeline/page.tsx          → 全链路流水线
│   │   └── [screen]/page.tsx          → 动态屏幕路由
│   │
│   ├── monitor/
│   │   ├── page.tsx                   → SACG 监控总览
│   │   ├── sense/page.tsx             → S 层 - 意图识别
│   │   ├── arrange/page.tsx           → A 层 - 图编排 DAG
│   │   ├── compute/page.tsx           → C 层 - 执行追踪
│   │   └── graph/page.tsx             → G 层 - BAC 压缩+回放
│   │
│   ├── memory/
│   │   ├── page.tsx                   → 记忆总览
│   │   ├── user/page.tsx              → 用户偏好记忆
│   │   ├── dze/page.tsx               → D-Z-E 工程链
│   │   ├── skills/page.tsx            → 技能索引
│   │   └── docs/page.tsx              → 文档索引
│   │
│   ├── settings/page.tsx              → 系统设置
│   ├── governance/page.tsx            → 治理面板
│   ├── reports/page.tsx               → 报告列表
│   ├── notebook/page.tsx              → Notebook
│   ├── token-monitor/page.tsx         → Token 监控
│   ├── graph-compression/page.tsx     → 图压缩可视化
│   ├── mood-board/page.tsx            → 情绪看板
│   ├── briefing/page.tsx              → 简报
│   ├── bdsm/page.tsx                  → BDSM 模块
│   ├── ops/page.tsx                   → 运维
│   ├── meta-labeling/page.tsx         → 元标注
│   ├── feed/page.tsx                  → 情报流
│   ├── workflow/page.tsx              → 工作流
│   ├── test-visualization/page.tsx    → 测试可视化
│   └── market/                        → 市场营销
│       ├── page.tsx
│       ├── segments/page.tsx
│       ├── effectiveness/page.tsx
│       ├── distribution/page.tsx
│       ├── campaigns/page.tsx
│       └── audit/page.tsx
│
├── board/
│   ├── page.tsx                       → 治理总览
│   ├── approval/page.tsx              → 人工审批
│   ├── proposals/page.tsx            → 提案列表
│   ├── proposals/[id]/page.tsx        → 提案详情
│   └── review/page.tsx                → 绩效评审
│
├── reports/[id]/page.tsx              → 报告详情
│
└── api/                               → API Routes (96+ 端点)
    ├── auth/[...nextauth]/route.ts    → NextAuth 认证
    ├── task/                          → 任务执行 (stream/result/confirm)
    ├── intent/                        → 意图识别 (evaluate/steer)
    ├── cognitive/                     → 认知系统 (recall/record/verify/stats/health/unified/knowledge)
    ├── config/                        → 配置管理 (api-keys/trading-params/strategies/channels)
    ├── classic/                       → 经典系统 (gate-thresholds/approvals/pipeline-state)
    ├── board/                         → 治理 (proposals/approval/review/metrics)
    ├── user/                          → 用户 (signin/checkin/me)
    ├── user-memory/                   → 用户记忆 (preferences/notes/health)
    ├── notebook/                      → 笔记本 (sync/tasks/step/state)
    ├── monitor/                       → 监控 (stats/stream/events/proactive)
    ├── market/                        → 市场 (yahoo/global/segments/effectiveness/distribution/campaigns/audit/content/route)
    ├── onchain/                       → 链上数据 (btc/panewslab/bgeometrics/datacenter)
    ├── data/                          → 数据 (macro/chain/market)
    ├── ops/                           → 运维 (decision-levels/queues)
    ├── compression/                   → 图压缩 (stats)
    ├── feed/                          → 情报流
    ├── briefings/                     → 简报
    ├── mood-board/                    → 情绪看板
    ├── meta-labeling/                 → 元标注
    ├── positions/                      → 持仓
    ├── trade-orders/                  → 交易订单
    ├── price/                         → 价格
    ├── artifacts/                     → 产物文件
    ├── artifact/                      → 产物
    ├── chain/                         → 链路产物
    ├── reports/                       → 报告
    ├── recharge/                      → 充值
    ├── register/                      → 注册
    ├── kyc/                           → KYC
    ├── customer/                      → 客户
    └── skills/                        → 技能 (index)
    └── docs/                          → 文档 (sync/index)
```

#### 路由与 SACG 层映射

| 路由 | 主要 SACG 层 | 辅助层 | 说明 |
|------|--------------|--------|------|
| `/dashboard` | 全部 | — | 三屏概览 + SACG 状态 |
| `/dashboard/trade` | S + C | A | 意图识别(S) → 链路执行(C) |
| `/dashboard/classic` | S + C | A | 经典交易模式 |
| `/dashboard/fundamental` | C | G | 执行层产物展示 + 图存储查询 |
| `/dashboard/three-screens` | 全部 | — | 应用层：调用 A/C/F/G 域能力 |
| `/dashboard/monitor` | 全部 | — | SACG 四层独立可视化 |
| `/dashboard/memory` | G | S | 图存储层 + 意图识别反馈 |
| `/dashboard/settings` | — | — | 配置管理 |
| `/dashboard/governance` | A | C | 图编排层治理 + 执行层审计 |
| `/dashboard/reports` | G | C | 图存储产物 + 执行产物关联 |

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
│           │  └─────────────────────────────────────────────┘       │
├───────────┼─────────────────────────────────────────────────────────┤
│           │  A (Arrange/编排) - 图编排层                           │
│  颜色     │  ┌─────────────────────────────────────────────┐       │
│  #3B82F6  │  │ DAG 图可视化 (节点+边)                         │       │
│  蓝色     │  │ 节点状态: pending/active/done/skipped/failed  │       │
│           │  │ ACFTG 链展示 (纵轴=阶段, 横轴=链)              │       │
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
│           │  └─────────────────────────────────────────────┘       │
├───────────┼─────────────────────────────────────────────────────────┤
│           │  G (Graph/存储) - 图存储层                             │
│  颜色     │  ┌─────────────────────────────────────────────┐       │
│  #EF4444  │  │ BAC 三层压缩可视化:                            │       │
│  红色     │  │   Blueprint → Architecture → Chronicle      │       │
│           │  │ 压缩比率仪表盘                                 │       │
│           │  │ Checkpointing 时间线                           │       │
│           │  │ 历史回放播放器 (Play/Pause/Seek)               │       │
│           │  └─────────────────────────────────────────────┘       │
└───────────┴─────────────────────────────────────────────────────────┘
```

#### SACG 组件实现映射

| SACG 层 | 组件 | 路径 | 功能 |
|---------|------|------|------|
| S (Sense) | SenseConfidenceGauge | `features/monitor/` | 意图置信度仪表 |
| S (Sense) | ClarifyCard | `features/chat/` | 意图澄清交互 |
| A (Arrange) | DAGGraphView | `features/monitor/` | DAG 图可视化 |
| A (Arrange) | OrchestrationPanel | `features/orchestration/` | 编排面板 |
| C (Compute) | ReflectorPanel | `features/monitor/` | Reflector 决策面板 |
| C (Compute) | CrossValidationPanel | `features/monitor/` + `features/chain/` | 三链交叉验证 |
| C (Compute) | ChainTracker | `features/chain/` | 链追踪面板 |
| C (Compute) | ChainStepCard | `features/chain/` | 单步骤卡片 |
| C (Compute) | ReflectorDecisionBadge | `features/chain/` | Reflector 决策标记 |
| C (Compute) | SACELayerBadge | `features/chain/` | SACG 层级标记 |
| C (Compute) | StepInterventionPanel | `features/chain/` | 步骤干预面板 |
| G (Graph) | SACGOverview | `features/monitor/` | SACG 四层总览 |
| G (Graph) | BACTimeline | `features/sacg/` | BAC 压缩时间线 |
| G (Graph) | HistoryPlayer | `features/sacg/` | 历史回放播放器 |
| G (Graph) | GraphCompressionVisualizer | `features/graph-compression/` | 图压缩可视化 |
| 全部 | ThinkingCard | `features/chat/` | AI 思考过程展示 |

### 3.3 三屏交易系统 — 应用层

三屏交易系统是 WorkBuddy OS 架构中的**实际应用层**，位于能力层之上。它调用 A_domain（执行闭环/情报闭环）、C_domain（经典指标）、F_domain（基本面）等能力模块来完成交易决策和执行。

#### Elder 三屏体系前端映射

| 屏 | 战略角色 | 路由 | 核心组件 | 调用的能力模块 | 输出 |
|:---|:---|:---|:---|:---|:---|
| **Screen1** | 战略层（周线方向） | `/dashboard/three-screens/screen1` | Screen1Panel + RadarDimensions + ConfidenceGauge | A0矛盾论, A1调研, A2第一性原理, A3策略设计 | direction(LONG/SHORT), score(0-100), strategy_type |
| **Screen2** | 战术层（日线预设） | `/dashboard/three-screens/screen2` | Screen2Panel + FundamentalBars | dream-backtest, dream-bayesian-opt, A4验证 | 三大预设 + 信号强度 + 仓位建议 |
| **Screen3** | 执行层（实时执行） | `/dashboard/three-screens/screen3` | Screen3Panel | A7门禁, A4验证, C3门禁, A5执行, A6情报, A9离场 | 仓位状态 + 执行日志 + 离场报告 |
| **Pipeline** | 全链路视角 | `/dashboard/three-screens/pipeline` | PipelineView | 全部上述模块 | 链路健康度 + 方向约束传递 |

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
  │
  └─── 记忆更新 ───→ Memory / Chronicle
```

#### 三屏状态管理

三屏交易系统使用独立的 Zustand store: [three-screens-store.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND/src/stores/three-screens-store.ts)

#### 三屏辅助组件

| 组件 | 路径 | 功能 |
|------|------|------|
| ConfidenceGauge | `features/three-screens/charts/` | 置信度仪表盘 |
| RadarDimensions | `features/three-screens/charts/` | 七维雷达图 |
| FundamentalBars | `features/three-screens/charts/` | 基本面柱状图 |
| BullBearDebate | `features/chain/` | 大师辩论面板 |

### 3.4 状态管理架构

#### Zustand Store 清单

```
src/stores/
├── index.ts                      → 统一导出
├── session-store.ts              → 会话、消息、输入状态
├── chain-store.ts                → 链状态、步骤追踪、Reflector 决策
├── trading-store.ts              → 交易模式、参数、余额
├── classic-store.ts              → 经典系统完整状态 (C0-C8)
├── three-screens-store.ts        → 三屏交易系统状态 (Screen1/2/3 + 方向约束)
├── monitor-store.ts              → SACG 监控事件、管道状态
├── memory-store.ts               → 记忆系统状态 (DZE链)
├── user-memory-store.ts          → 用户偏好记忆 (notes/preferences)
├── notebook-store.ts             → Notebook 任务和步骤状态
├── ui-store.ts                   → 面板折叠、主题、语言
├── api-config-store.ts           → API 配置 (密钥/交易参数/策略/渠道)
└── auth-store.ts                 → 认证 (NextAuth Session)
```

#### Store 职责说明

| Store | 职责 | 关键状态 |
|------|------|----------|
| useSessionStore | 会话管理 | sessions[], messages[], isStreaming, inputValue, lastIntent |
| useChainStore | 链路追踪 (C+A) | activeChain, steps[], reflectorHistory[], dagNodes[], dagEdges[], artifacts[] |
| useTradingStore | AI Skill 交易 | mode('ai_skill'\|'classic'), balance, positions[], sChainTraces[], params |
| useClassicStore | 经典交易 (C0-C8) | phases[C0-C8], activePhase, governance, config |
| useThreeScreensStore | 三屏系统 | screen1/2/3 data, directionConstraint, presetConstraint |
| useMonitorStore | SACG 监控 | layers[S/A/C/G], pipeline, sseConnection |
| useMemoryStore | 记忆系统 | dzeChains[D/Z/E], preferences[], stats |
| useUserMemoryStore | 用户记忆 | notes[], preferences[], health |
| useNotebookStore | Notebook | tasks[], activeTask, steps[], artifacts[] |
| useUIStore | UI 状态 | sidebarCollapsed, rightPanelCollapsed, theme, commandPaletteOpen |
| useApiConfigStore | API 配置 | apiKeys[], tradingParams, strategies[], channels[] |
| useAuthStore | 认证 | session, user, loginState |

### 3.5 组件层级设计

```
src/components/
├── V3Card.tsx                    → 基础卡片
├── V3Button.tsx                  → 基础按钮
├── V3Badge.tsx                   → 基础徽章
├── V3StatusDot.tsx               → 状态圆点
├── V3Tooltip.tsx                 → 工具提示
├── V3InlineSVG.tsx               → 内联 SVG 图标
├── V3Spinner.tsx                 → 加载动画
├── V3Empty.tsx                   → 空状态
│
└── features/                     → 业务功能组件 (按域分层)
    ├── chat/                     → 对话域 (19个组件)
    │   ├── ChatPanel.tsx         → 聊天面板 (主容器)
    │   ├── ChatInput.tsx         → 输入区+快捷命令
    │   ├── MessageItem.tsx       → 单条消息
    │   ├── StreamingIndicator.tsx → 流式输出指示器
    │   ├── ThinkingCard.tsx      → AI 思考过程卡片
    │   ├── ClarifyCard.tsx       → 意图澄清卡片
    │   ├── SteerPanel.tsx        → 引导面板
    │   ├── SynthesisChart.tsx    → 综合图表
    │   ├── InsightCard.tsx       → 洞察卡片
    │   ├── RecommendationCard.tsx → 推荐卡片
    │   ├── ReportExport.tsx      → 报告导出
    │   ├── MoodBoardPanel.tsx    → 情绪看板
    │   ├── StepConfirmation.tsx  → 步骤确认
    │   ├── EnhancementHints.tsx  → 增强提示
    │   ├── MonitorHooks.tsx      → 监控钩子
    │   ├── ExecutionReviewHooks.tsx → 执行审查钩子
    │   ├── StrategyHooks.tsx     → 策略钩子
    │   ├── DecisionHooks.tsx     → 决策钩子
    │   └── DimensionHooks.tsx    → 维度钩子
    │
    ├── chain/                    → 链路追踪域 (7个组件)
    │   ├── ChainTracker.tsx      → 链追踪面板
    │   ├── ChainStepCard.tsx     → 单步骤卡片
    │   ├── StepInterventionPanel.tsx → 步骤干预
    │   ├── BullBearDebate.tsx    → 多空辩论
    │   ├── SACELayerBadge.tsx    → SACG 层级标记
    │   ├── ReflectorDecisionBadge.tsx → Reflector 决策标记
    │   └── CrossValidationPanel.tsx → 三链交叉验证
    │
    ├── three-screens/            → 三屏交易域 (7个组件)
    │   ├── Screen1Panel.tsx      → 战略层
    │   ├── Screen2Panel.tsx      → 战术层
    │   ├── Screen3Panel.tsx      → 执行层
    │   ├── PipelineView.tsx      → 全链路视图
    │   └── charts/               → 图表子组件
    │       ├── ConfidenceGauge.tsx
    │       ├── RadarDimensions.tsx
    │       └── FundamentalBars.tsx
    │
    ├── fundamental/              → 基本面域 (17个组件)
    │   ├── FundamentalGrid.tsx  → 基本面网格
    │   ├── OverviewPanel.tsx     → 综合概览
    │   ├── FlowPanel.tsx         → 资金流向
    │   ├── MacroPanel.tsx        → 宏观经济
    │   ├── MacroDashboard.tsx    → 宏观面板
    │   ├── IntermarketPanel.tsx  → 跨市场分析
    │   ├── SentimentPanel.tsx    → 市场情绪
    │   ├── SentimentHeatmap.tsx  → 情绪热力图
    │   ├── ValuationPanel.tsx    → 估值模型
    │   ├── OnchainPanel.tsx      → 链上数据
    │   ├── OnchainMetrics.tsx    → 链上指标
    │   ├── BreadthPanel.tsx      → 市场广度
    │   ├── ModuleDetail.tsx      → 模块详情
    │   ├── NetFlowTrendChart.tsx → 净流趋势图
    │   ├── WhaleTracker.tsx      → 巨鲸追踪
    │   ├── UTXOAgeDistribution.tsx → UTXO 年龄分布
    │   └── MVRVZoneChart.tsx     → MVRV 区域图
    │
    ├── classic/                  → 经典交易域 (8个组件)
    │   ├── IndicatorPanel.tsx    → 指标面板
    │   ├── GovernanceFlow.tsx    → 治理流程
    │   ├── GovernancePanelEnhanced.tsx → 增强治理面板
    │   ├── ClassicPhaseIndicator.tsx → 阶段指示器
    │   ├── ClassicPhasePanel.tsx → 经典阶段面板
    │   ├── GenerationPanel.tsx   → 生成面板
    │   ├── ManagementPanel.tsx   → 管理面板
    │   └── SignalsPanel.tsx      → 信号面板
    │
    ├── monitor/                  → SACG 监控域 (5个组件)
    │   ├── SACGOverview.tsx      → SACG 四层总览
    │   ├── DAGGraphView.tsx      → DAG 图可视化
    │   ├── ReflectorPanel.tsx    → Reflector 决策面板
    │   ├── CrossValidationPanel.tsx → 交叉验证面板
    │   └── SenseConfidenceGauge.tsx → 意图置信度仪表
    │
    ├── sacg/                     → SACG 历史回放 (2个组件)
    │   ├── BACTimeline.tsx       → BAC 压缩时间线
    │   └── HistoryPlayer.tsx     → 历史回放播放器
    │
    ├── memory/                   → 记忆域 (6个组件)
    │   ├── RecordExperienceForm.tsx → 经验记录表单
    │   ├── MemoryTimeline.tsx    → 记忆时间线
    │   ├── DZEChainView.tsx      → D-Z-E 链视图
    │   ├── MemoryTabNav.tsx     → 记忆标签导航
    │   ├── SkillIndexView.tsx   → 技能索引视图
    │   └── DocIndexView.tsx     → 文档索引视图
    │
    ├── settings/                 → 设置域 (5个组件)
    │   ├── ApiKeyManager.tsx    → API 密钥管理
    │   ├── TradingParamsPanel.tsx → 交易参数面板
    │   ├── StrategyManager.tsx  → 策略管理
    │   ├── CompletenessWizard.tsx → 完整性向导
    │   └── ChannelManager.tsx   → 通信渠道管理
    │
    ├── notebook/                 → Notebook 域 (7个组件)
    │   ├── NotebookPanel.tsx    → Notebook 面板
    │   ├── ArtifactGallery.tsx  → 产物画廊
    │   ├── TaskCard.tsx         → 任务卡片
    │   ├── ActiveDZEChain.tsx   → 活跃 DZE 链
    │   ├── ActiveStrategyChain.tsx → 活跃策略链
    │   ├── StepActionMenu.tsx   → 步骤操作菜单
    │   └── StepProgress.tsx     → 步骤进度
    │
    ├── ranking/                  → 排行榜域 (4个组件)
    │   ├── DecisionCard.tsx     → 决策卡片
    │   ├── RankingCard.tsx      → 排名卡片
    │   ├── RankingMonitor.tsx    → 排行监控
    │   └── PrefillOrderBanner.tsx → 预填单横幅
    │
    ├── governance/               → 治理域 (1个组件)
    │   └── GovernanceScreen.tsx → 治理面板
    │
    ├── reports/                  → 报告域 (1个组件)
    │   └── ReportsScreen.tsx    → 报告页面
    │
    ├── workflow/                 → 工作流域 (3个组件)
    │   ├── WorkflowCard.tsx     → 工作流卡片
    │   ├── WorkflowStatusBadge.tsx → 状态徽章
    │   └── WorkflowStepList.tsx → 步骤列表
    │
    ├── orchestration/           → 编排域 (1个组件)
    │   └── OrchestrationPanel.tsx → 编排面板
    │
    ├── dashboard/               → 仪表盘域 (1个组件)
    │   └── LiveStatusPanel.tsx → 实时状态面板
    │
    ├── token-monitor/           → Token 监控域 (2个组件)
    │   ├── TokenMonitorPanel.tsx → Token 监控面板
    │   └── TokenMonitorBadge.tsx → Token 监控徽章
    │
    └── graph-compression/       → 图压缩域 (1个组件)
        └── GraphCompressionVisualizer.tsx → 图压缩可视化
```

#### 组件层级关系

```
Layout 层
  └── DashboardLayout (src/app/dashboard/layout.tsx)
       ├── Sidebar (内联在 layout 中)
       └── Content Area
            └── Page 层 (src/app/dashboard/*/page.tsx)
                 └── Feature 层 (src/components/features/*)
                      └── Primitive 层 (src/components/V3*.tsx)
```

### 3.6 Lib 架构

```
src/lib/
├── v3/api/                       → API Client 层 (20个域模块)
│   ├── client.ts                 → ApiClient 基类
│   ├── index.ts                  → 统一导出
│   ├── task.ts                   → 任务执行 API
│   ├── chat.ts                   → 对话 API
│   ├── market.ts                 → 市场数据 API
│   ├── trade.ts                  → 交易 API
│   ├── config.ts                 → 配置管理 API
│   ├── user.ts                   → 用户 API
│   ├── reports.ts                → 报告 API
│   ├── monitor.ts                → 监控 API
│   ├── intent.ts                 → 意图识别 API
│   ├── notebook.ts               → 笔记本 API
│   ├── ops.ts                    → 运维 API
│   ├── orchestrate.ts            → 编排 API
│   ├── chain.ts                  → 链路产物 API
│   ├── board.ts                  → 治理 API
│   ├── fundamental.ts            → 基本面 API
│   ├── feed.ts                   → 消息流 API
│   ├── auth.ts                   → 认证 API
│   ├── artifact.ts               → 产物文件 API
│   └── register.ts               → 注册 API
│
├── planner/                      → 规划引擎 (21个文件)
│   ├── planner.ts                → 主规划器
│   ├── chain-planner.ts          → 链规划器
│   ├── dynamic-node-planner.ts   → 动态节点规划
│   ├── cross-validator.ts        → 交叉验证器
│   ├── voting-calculator.ts      → 投票计算器
│   ├── confidence-evaluator.ts   → 置信度评估器
│   ├── skill-selector.ts         → 技能选择器
│   ├── skills-registry.ts        → 技能注册表
│   ├── module-registry.ts        → 模块注册表
│   ├── chains-registry.ts        → 链注册表
│   ├── bridge-client.ts          → 桥接客户端
│   ├── methodology-executor.ts   → 方法论执行器
│   ├── intent-clarification-engine.ts → 意图澄清引擎
│   ├── intent-spec-writer.ts     → 意图规范编写器
│   ├── node-gap-supplementer.ts  → 节点缺口补充器
│   ├── tdd-execution-wrapper.ts  → TDD 执行包装器
│   ├── supplement-memory-store.ts → 补充记忆存储
│   ├── superpowers-skill-adapter.ts → 超能力技能适配器
│   ├── superpowers-skill-fs.ts   → 超能力技能文件系统
│   └── ... (types, index等)
│
├── orchestration/                → 编排层
│   ├── llm-bridge.ts             → LLM 桥接
│   ├── superpower-llm-bridge.ts  → 超能力 LLM 桥接
│   ├── skill-llm-bridge-adapter.ts → 技能 LLM 桥接适配器
│   ├── market-data-bridge.ts    → 市场数据桥接
│   └── node-prompts.ts           → 节点提示词
│
├── cognitive/                    → 认知系统
│   ├── cognitive-context-fetcher.ts → 认知上下文获取器
│   ├── cognitive-context-builder.ts → 认知上下文构建器
│   ├── cognitive-client.ts       → 认知客户端
│   └── trae-memory-bridge.ts     → Trae 记忆桥接
│
├── case/                          → 案例检索
│   ├── case-retriever.ts         → 案例检索器
│   ├── case-verify-bridge.ts     → 案例验证桥接
│   ├── case-bank-client.ts       → 案例库客户端
│   └── solution-encoder.ts       → 解决方案编码器
│
├── SACG 五训练循环
│   ├── s-intent-training-loop.ts → S 层意图训练循环
│   ├── c-reflection-training-loop.ts → C 层反思训练循环
│   ├── g-graph-training-loop.ts  → G 层图训练循环
│   ├── dsh-path-training-loop.ts → DSH 路径训练循环
│   └── llm-prompt-training-loop.ts → LLM 提示训练循环
│
├── dynamic-chain/                → 动态链
│   ├── executor.ts               → 执行器
│   ├── runner.ts                 → 运行器
│   ├── graph-planner.ts          → 图规划器
│   ├── reflect-engine.ts         → 反思引擎
│   └── types.ts
│
├── dev-chain/                    → 开发链
│   ├── chain-controller.ts
│   ├── route.ts
│   ├── steps/index.ts
│   └── types.ts
│
├── strategy/                     → 策略
│   ├── chain-controller.ts
│   ├── route.ts
│   ├── types.ts
│   ├── index.ts
│   └── steps/ (analysis/research/design/validate/execute)
│
├── compressor-adapter/          → 压缩适配器
│   ├── adapter.ts
│   ├── orchestrate-adapter.ts
│   ├── external-stub.ts
│   ├── fallback.ts
│   ├── types.ts
│   └── index.ts
│
├── scheduler/                    → 调度器
│   ├── cost-keeper.ts            → 成本保持器
│   ├── skip-gate.ts             → 跳过门禁
│   └── index.ts
│
├── notebook/                     → Notebook
│   ├── step-controller.ts
│   └── types.ts
│
├── intent/                       → 意图识别
│   ├── smart-router.ts
│   ├── fallback-engine.ts
│   ├── intent-memory.ts
│   ├── intent-descriptions.ts
│   └── index.ts
│
├── memory/                       → 记忆
│   └── user-preference-memory.ts
│
├── 核心服务
│   ├── task-manager.ts           → 任务管理器
│   ├── intent-router.ts          → 意图路由器
│   ├── sse-dispatcher.ts        → SSE 分发器
│   ├── sse-client.ts            → SSE 客户端
│   ├── use-sse.ts               → SSE Hook
│   ├── api-client.ts            → API 客户端 (旧版)
│   ├── auth.ts                  → 认证
│   ├── auth-runtime.ts          → 认证运行时
│   ├── encryption.ts            → 加密
│   ├── prisma.ts                → Prisma 客户端
│   ├── uid.ts                   → 唯一 ID 生成
│   ├── trace-id.ts              → 追踪 ID
│   ├── trading-mode.ts          → 交易模式
│   ├── trading-hook.ts          → 交易 Hook
│   ├── bridge-client.ts         → 桥接客户端
│   ├── monitor-bus.ts           → 监控总线
│   ├── token-monitor.ts         → Token 监控
│   ├── use-token-monitor.ts     → Token 监控 Hook
│   ├── use-monitor-data.ts      → 监控数据 Hook
│   ├── reflection-gates.ts      → 反思门禁
│   ├── reflection-engine.ts     → 反思引擎
│   ├── quality-gate.ts          → 质量门禁
│   ├── eval-layer.ts            → 评估层
│   ├── drift-detector.ts        → 漂移检测器
│   ├── imitation-counter.ts     → 模仿计数器
│   ├── evolution-agent.ts       → 进化代理
│   ├── skill-orchestration-executor.ts → 技能编排执行器
│   ├── skill-selector.ts        → 技能选择器
│   ├── research-orchestrator.ts → 研究编排器
│   ├── knowledge-ingest.ts      → 知识摄入
│   ├── knowledge-loader.ts      → 知识加载器
│   ├── knowledge-rag.ts         → 知识 RAG
│   ├── summary-agent.ts        → 摘要代理
│   ├── graph-reflection-bridge.ts → 图反思桥接
│   ├── bdsm-api.ts              → BDSM API
│   ├── three-screens-api.ts    → 三屏 API
│   ├── three-screens-mapper.ts → 三屏映射器
│   ├── classic-system-api.ts   → 经典系统 API
│   ├── classic-system-bridge.ts → 经典系统桥接
│   ├── classic-system-client.ts → 经典系统客户端
│   ├── classic-system-hooks.ts → 经典系统 Hooks
│   ├── market-data-fetcher.ts  → 市场数据获取器
│   ├── market-data-adapter.ts  → 市场数据适配器
│   ├── test-market-adapter.ts   → 测试市场适配器
│   ├── tavily-service.ts        → Tavily 服务
│   ├── dsh-execution-engine.ts  → DSH 执行引擎
│   ├── c-drive.ts               → C 驱动
│   ├── c-reflection-training-loop.ts → C 反思训练循环
│   ├── user-memory-client.ts    → 用户记忆客户端
│   ├── module-api-client.ts     → 模块 API 客户端
│   ├── jsonl-writer.ts          → JSONL 写入器
│   ├── development-route-uids.ts → 开发路由 UID
│   ├── dev-user.ts              → 开发用户
│   ├── strategy-lifecycle-service.ts → 策略生命周期服务
│   ├── strategy-task-order-service.ts → 策略任务顺序服务
│   ├── strategy-task-order.ts   → 策略任务顺序
│   └── strategy-artifacts.ts    → 策略产物
```

---

## 第四章：API 集成方案

### 4.1 API Client 层

API Client 封装在 [src/lib/v3/api/client.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND/src/lib/v3/api/client.ts) 中，基于 fetch 封装:

- 支持 GET/POST/PUT/PATCH/DELETE
- 统一错误处理和重试
- SSE 专用方法

### 4.2 API 分组

按 20 个业务域分组，每组一个 API 模块文件:

```
src/lib/v3/api/
├── client.ts                 → ApiClient 基类
├── index.ts                  → 统一导出
├── task.ts                   → 任务执行
├── chat.ts                   → 对话
├── market.ts                 → 市场数据
├── trade.ts                  → 交易
├── config.ts                 → 配置管理
├── user.ts                   → 用户
├── reports.ts                → 报告
├── monitor.ts                → 监控
├── intent.ts                 → 意图识别
├── notebook.ts               → 笔记本
├── ops.ts                    → 运维
├── orchestrate.ts             → 编排
├── chain.ts                  → 链路产物
├── board.ts                  → 治理
├── fundamental.ts            → 基本面
├── feed.ts                   → 消息流
├── auth.ts                   → 认证
├── artifact.ts               → 产物文件
└── register.ts               → 注册
```

### 4.3 认知系统 API

3.1 新增的认知系统 API 端点:

| 方法 | 路径 | 用途 |
|------|------|------|
| POST | /api/cognitive/recall | 检索历史经验 |
| POST | /api/cognitive/record | 记录新经验 |
| POST | /api/cognitive/verify | 验证已有记忆（贝叶斯置信度更新） |
| GET | /api/cognitive/stats | 记忆统计 |
| GET | /api/cognitive/health | 健康检查 |
| POST | /api/cognitive/unified | 统一认知查询 |
| GET | /api/cognitive/knowledge | 知识检索 |

### 4.4 SSE 流式集成

#### 9 种事件类型处理策略

| 事件类型 | 数据方向 | 处理策略 | UI 响应 |
|----------|----------|----------|---------|
| `started` | Server → Client | 标记任务开始，初始化追踪 UI | 显示 "正在处理..." 动画 |
| `thinking` | Server → Client | 显示 AI 思考过程 | ThinkingCard 组件 |
| `progress` | Server → Client | 更新链路步骤进度 | ChainTracker 步骤状态更新 |
| `text_delta` | Server → Client | 流式追加文本 | MessageItem 实时追加 |
| `data_card` | Server → Client | 渲染结构化数据卡片 | 消息流中插入卡片 |
| `artifact_ref` | Server → Client | 记录产物引用 | 参考报告区域新增引用 |
| `action_required` | Server → Client | 需要用户操作 | StepConfirmation 弹窗 |
| `done` | Server → Client | 标记任务完成 | 链追踪状态更新为 completed |
| `error` | Server → Client | 错误处理 | 显示错误提示，根据 retryable 显示重试 |

### 4.5 错误处理策略

| 错误类型 | 处理方式 | 重试策略 | 用户提示 |
|----------|----------|----------|----------|
| 网络超时 | 显示重试按钮 | 自动重试 2 次，间隔 3s | "网络连接超时，请重试" |
| 401 未授权 | 跳转登录页 | 不重试 | "登录已过期，请重新登录" |
| 403 权限不足 | 显示提示 | 不重试 | "当前操作需要更高级别权限" |
| 429 限流 | 排队等待 | 指数退避，最多 5 次 | "请求过于频繁，稍后重试" |
| 500 服务错误 | 显示重试按钮 | 自动重试 1 次 | "服务异常，请稍后重试" |
| SSE 连接断开 | 自动重连 | 指数退避，最多 10 次 | "连接中断，正在重连..." |

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
| `xl` | >= 1280px | 展开 (192px) | 展开 | 完整 |
| `lg` | 1024-1279px | 折叠 (56px, 仅图标) | 展开 | 双栏+图标侧栏 |
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

---

## 第六章：实施进度

### P0 — 基础架构 ✅ 已完成

| 任务 | 状态 | 交付物 |
|------|------|--------|
| 端口 3001 启动配置 | ✅ | `next dev -p 3001` |
| RootLayout + DashboardLayout | ✅ | `src/app/layout.tsx` + `src/app/dashboard/layout.tsx` |
| Sidebar 导航 (12项) | ✅ | 内联在 DashboardLayout 中 |
| 路由骨架 (56个 page.tsx) | ✅ | `src/app/` 下全部页面 |
| Zustand stores (12个) | ✅ | `src/stores/` 下全部 store |
| API Client 封装 (20个域) | ✅ | `src/lib/v3/api/` |
| SSE Hook (useSSE) | ✅ | `src/lib/use-sse.ts` |
| Primitive 组件 (8个 V3*) | ✅ | `src/components/V3*.tsx` |

### P1 — 核心交易功能 ✅ 已完成

| 任务 | 状态 | 交付物 |
|------|------|--------|
| ChatPanel + 18个子组件 | ✅ | `features/chat/` |
| ChainTracker + 7个链路组件 | ✅ | `features/chain/` |
| SSE 事件→Store 分发 | ✅ | `src/lib/sse-dispatcher.ts` |
| SenseConfidenceGauge | ✅ | `features/monitor/` |
| 交易参数管理面板 | ✅ | `features/settings/TradingParamsPanel.tsx` |
| 策略管理面板 | ✅ | `features/settings/StrategyManager.tsx` |
| API 密钥管理面板 | ✅ | `features/settings/ApiKeyManager.tsx` |
| 通信渠道管理 | ✅ | `features/settings/ChannelManager.tsx` |
| 完整性向导 | ✅ | `features/settings/CompletenessWizard.tsx` |
| ThreeScreens 总览 + Screen1/2/3 + Pipeline | ✅ | `features/three-screens/` |

### P2 — 经典交易 + 基本面 ✅ 已完成

| 任务 | 状态 | 交付物 |
|------|------|--------|
| ClassicScreen + 8个组件 | ✅ | `features/classic/` |
| 经典子标签动态路由 | ✅ | `classic/[subtab]/page.tsx` |
| GovernanceFlow 组件 | ✅ | `features/classic/GovernanceFlow.tsx` |
| FundamentalScreen + 17个组件 | ✅ | `features/fundamental/` |

### P3 — SACG 高级可视化 + 记忆 + 治理 ✅ 已完成

| 任务 | 状态 | 交付物 |
|------|------|--------|
| SACG 监控 (5个组件) | ✅ | `features/monitor/` |
| DAGGraphView | ✅ | `features/monitor/DAGGraphView.tsx` |
| BACTimeline + HistoryPlayer | ✅ | `features/sacg/` |
| 记忆系统 (6个组件) | ✅ | `features/memory/` |
| GovernanceScreen | ✅ | `features/governance/` |
| ReportsScreen | ✅ | `features/reports/` |
| GraphCompressionVisualizer | ✅ | `features/graph-compression/` |

### 后续增量 (P3+)

| 任务 | 状态 | 交付物 |
|------|------|--------|
| Notebook (7个组件) | ✅ | `features/notebook/` |
| 排行榜 (4个组件) | ✅ | `features/ranking/` |
| 工作流 (3个组件) | ✅ | `features/workflow/` |
| Token 监控 (2个组件) | ✅ | `features/token-monitor/` |
| 编排面板 | ✅ | `features/orchestration/` |
| 认知系统 API (7端点) | ✅ | `api/cognitive/` |
| SACG 五训练循环 | ✅ | `src/lib/*-training-loop.ts` |
| 用户记忆系统 | ✅ | `api/user-memory/` + `stores/user-memory-store.ts` |
| 技能/文档索引 | ✅ | `api/skills/` + `api/docs/` |
| 市场营销 (6个子页面) | ✅ | `dashboard/market/` |

---

## 附录

### 附录 A：96+ API 端点索引

#### 1. 认证 (/api/auth, /api/user, /api/register) — 5 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| * | /api/auth/[...nextauth] | NextAuth 认证 |
| POST | /api/user/signin | 用户登录 |
| POST | /api/user/checkin | 用户签到 |
| GET | /api/user/me | 获取当前用户 |
| POST | /api/register | 用户注册 |

#### 2. 任务执行 (/api/task) — 4 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| POST | /api/task | 创建任务 |
| POST | /api/task/stream | SSE 流式任务追踪 |
| POST | /api/task/confirm | 确认执行 |
| GET | /api/task/result/[id] | 获取任务结果 |

#### 3. 意图识别 (/api/intent) — 2 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| POST | /api/intent/evaluate | 意图评估 |
| POST | /api/intent/steer | 意图引导 |

#### 4. 认知系统 (/api/cognitive) — 7 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| POST | /api/cognitive/recall | 检索经验 |
| POST | /api/cognitive/record | 记录经验 |
| POST | /api/cognitive/verify | 验证记忆 |
| GET | /api/cognitive/stats | 记忆统计 |
| GET | /api/cognitive/health | 健康检查 |
| POST | /api/cognitive/unified | 统一查询 |
| GET | /api/cognitive/knowledge | 知识检索 |

#### 5. 配置管理 (/api/config) — 12 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| GET/POST/PUT/DELETE | /api/config/api-keys | API 密钥 CRUD |
| POST | /api/config/api-keys/test | 测试 API 连接 |
| GET/PUT | /api/config/trading-params | 交易参数 |
| POST | /api/config/trading-params/pause | 暂停交易 |
| POST | /api/config/trading-params/resume | 恢复交易 |
| POST | /api/config/trading-params/reset-daily | 重置日亏损 |
| GET/POST | /api/config/strategies | 策略列表/创建 |
| POST | /api/config/strategies/parse | 解析策略 |
| POST | /api/config/strategies/[id]/apply | 应用策略 |
| POST | /api/config/strategies/[id]/pause | 暂停策略 |
| GET/POST/PUT/DELETE | /api/config/channels | 通信渠道 CRUD |
| POST | /api/config/channels/[id]/test | 测试渠道 |

#### 6. 经典系统 (/api/classic) — 3 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| GET/PUT | /api/classic/gate-thresholds | 门禁阈值 |
| GET/POST | /api/classic/approvals | 审批管理 |
| GET/PUT | /api/classic/pipeline-state | 管线状态 |

#### 7. 治理 (/api/board) — 7 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | /api/board/metrics | 治理指标 |
| GET/POST | /api/board/proposals | 提案管理 |
| GET/PUT/DELETE | /api/board/proposals/[id] | 提案详情 |
| POST | /api/board/proposals/[id]/votes | 提案投票 |
| GET | /api/board/review | 绩效评审 |
| GET | /api/board/approval/pending | 待审批列表 |
| GET | /api/board/approval/summary | 审批摘要 |
| GET/PUT | /api/board/approval/[id] | 审批操作 |

#### 8. 用户记忆 (/api/user-memory) — 5 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| GET/POST | /api/user-memory/preferences | 用户偏好 |
| GET/POST | /api/user-memory/notes | 笔记列表/创建 |
| GET/PUT/DELETE | /api/user-memory/notes/[id] | 笔记详情 |
| POST | /api/user-memory/notes/[id]/promote | 笔记提升 |
| GET | /api/user-memory/health | 健康检查 |

#### 9. 监控 (/api/monitor) — 4 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | /api/monitor/stats | 监控统计 |
| GET | /api/monitor/stream | SSE 监控流 |
| GET | /api/monitor/events | 监控事件 |
| GET | /api/monitor/proactive | 主动监控 |

#### 10. 市场数据 (/api/market, /api/data, /api/onchain, /api/price) — 15 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | /api/market/yahoo | Yahoo 市场数据 |
| GET | /api/market/global | 全球市场数据 |
| GET | /api/market/segments | 市场细分 |
| GET | /api/market/effectiveness | 市场效果 |
| GET | /api/market/distribution | 市场分布 |
| GET | /api/market/campaigns | 营销活动 |
| GET | /api/market/audit | 市场审计 |
| GET | /api/market/content | 市场内容 |
| GET | /api/market/route | 市场路由 |
| GET | /api/data/macro | 宏观数据 |
| GET | /api/data/chain | 链上数据 |
| GET | /api/data/market | 市场数据 |
| GET | /api/onchain/btc | BTC 链上数据 |
| GET | /api/onchain/panewslab | PanewLab 数据 |
| GET | /api/onchain/bgeometrics | BGeometrics 数据 |
| GET | /api/onchain/datacenter | 数据中心 |
| GET | /api/price/[symbol] | 价格查询 |

#### 11. Notebook (/api/notebook) — 5 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| GET/POST | /api/notebook | Notebook 列表/创建 |
| GET/POST | /api/notebook/tasks | 任务管理 |
| POST | /api/notebook/step | 步骤操作 |
| GET/PUT | /api/notebook/state | 状态管理 |
| POST | /api/notebook/sync | 同步 |

#### 12. 技能/文档 (/api/skills, /api/docs) — 3 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | /api/skills/index | 技能索引 |
| GET | /api/docs/index | 文档索引 |
| POST | /api/docs/sync | 文档同步 |

#### 13. 其他端点

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | /api/positions | 持仓查询 |
| GET/POST | /api/trade-orders | 交易订单 |
| GET/POST | /api/artifacts | 产物列表 |
| GET | /api/artifacts/[id] | 产物详情 |
| GET | /api/artifact | 产物文件 |
| GET | /api/chain/artifacts | 链路产物 |
| GET/POST | /api/reports | 报告列表/生成 |
| POST | /api/reports/generate | 生成报告 |
| GET/POST | /api/briefings | 简报 |
| GET | /api/briefings/[id] | 简报详情 |
| GET/POST | /api/feed | 情报流 |
| GET/POST | /api/mood-board | 情绪看板 |
| GET/POST | /api/meta-labeling | 元标注 |
| GET | /api/compression/stats | 图压缩统计 |
| GET | /api/ops/decision-levels | 决策层级 |
| GET | /api/ops/queues | 队列状态 |
| POST | /api/recharge | 充值 |
| GET/POST | /api/kyc | KYC |
| GET/POST | /api/customer | 客户 |

### 附录 B：Store 索引

| Store | 文件路径 | 职责 |
|------|----------|------|
| useSessionStore | `src/stores/session-store.ts` | 会话、消息、输入 |
| useChainStore | `src/stores/chain-store.ts` | 链路追踪、DAG |
| useTradingStore | `src/stores/trading-store.ts` | 交易模式、余额 |
| useClassicStore | `src/stores/classic-store.ts` | 经典系统 C0-C8 |
| useThreeScreensStore | `src/stores/three-screens-store.ts` | 三屏系统 |
| useMonitorStore | `src/stores/monitor-store.ts` | SACG 监控 |
| useMemoryStore | `src/stores/memory-store.ts` | DZE 记忆链 |
| useUserMemoryStore | `src/stores/user-memory-store.ts` | 用户偏好记忆 |
| useNotebookStore | `src/stores/notebook-store.ts` | Notebook |
| useUIStore | `src/stores/ui-store.ts` | UI 状态 |
| useApiConfigStore | `src/stores/api-config-store.ts` | API 配置 |
| useAuthStore | `src/stores/auth-store.ts` | 认证 |

### 附录 C：UI_SPEC 参考规范

3.1 前端的 UI 设计规范同时参考以下两份 UI_SPEC:

1. [3-FRONTEND/dream-universal-gateway/docs/UI_SPEC.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/docs/UI_SPEC.md) (v2.3, 3.0 时代)
2. [1-ARCHITECTURE/前端设计/UI_SPEC.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/前端设计/UI_SPEC.md) (v2.3, 3.0 时代)

> **注**: 两份 UI_SPEC 内容相同，描述 3.0 时代的三栏对话式界面。3.1 已远超此设计，但仍保留以下有效规范:
> - 色彩系统 (§1.2): 基础色板 + 分析阶段色
> - API 配置面板 (§4): 交易所/AI模型/数据源分类
> - 通信渠道面板 (§5): Telegram/微信/企业微信/Email/Discord/Slack
> - 交易设置面板 (§5.5): 交易金额/杠杆/亏损限制/门禁拦截
> - 策略设置面板 (§5.6): 推荐策略/信号策略/运行中策略

### 附录 D：关键文件索引

| 文件 | 路径 | 说明 |
|------|------|------|
| 综合技术文档 | `docs/v3-frontend-architecture.md` | 本文档 |
| 项目配置 | `package.json` | 依赖和脚本 |
| TypeScript 配置 | `tsconfig.json` | 类型检查配置 |
| Next.js 配置 | `next.config.ts` | Next.js 配置 |
| Prisma Schema | `prisma/schema.prisma` | 数据库模型 |
| RootLayout | `src/app/layout.tsx` | 全局布局 |
| DashboardLayout | `src/app/dashboard/layout.tsx` | 仪表盘布局 (含 Sidebar) |
| ClassicLayout | `src/app/dashboard/classic/layout.tsx` | 经典系统布局 |
| Store 索引 | `src/stores/index.ts` | 统一导出 |
| API Client | `src/lib/v3/api/client.ts` | API 基类 |
| API 索引 | `src/lib/v3/api/index.ts` | 统一导出 |
| SSE Hook | `src/lib/use-sse.ts` | SSE 流式连接 |
| SSE 分发器 | `src/lib/sse-dispatcher.ts` | SSE 事件分发 |
| 任务管理器 | `src/lib/task-manager.ts` | 任务执行核心 |
| 意图路由器 | `src/lib/intent-router.ts` | 意图识别路由 |
| 规划引擎 | `src/lib/planner/` | 21个规划文件 |
| SACG 架构文档 | `../1-ARCHITECTURE/WORKBUDDY_OS_MODULAR_ARCHITECTURE.md` | 52 模块注册表 |
| 三屏系统文档 | `../2-KNOWLEDGE/1-TRADING/三屏系统架构.md` | Screen1/2/3 职责 |
