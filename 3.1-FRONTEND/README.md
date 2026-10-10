# DreamBuddy v3.1 Frontend

> AI 驱动的加密货币交易平台前端，基于 SACG 四层架构。
> 独立 Next.js 项目，运行在端口 3001。

## 快速开始

```bash
cd 3.1-FRONTEND
npm install
npm run dev          # 启动开发服务器 (localhost:3001)
npm run build        # 生产构建
npm run start        # 生产模式启动
npm run lint         # ESLint 检查
npm run test         # Jest 测试
```

## 目录结构

```
3.1-FRONTEND/
├── README.md                           ← 你在这里
├── package.json                        ← 依赖和脚本
├── next.config.ts                      ← Next.js 配置
├── tsconfig.json                        ← TypeScript 配置
├── prisma/
│   └── schema.prisma                   ← 数据库模型
├── docs/
│   └── v3-frontend-architecture.md     ← 综合技术文档
├── design/
│   └── v2-design-draft/                ← v2 设计稿（仅供参考）
│
└── src/
    ├── app/                            ← Next.js App Router
    │   ├── layout.tsx                  ← RootLayout
    │   ├── page.tsx                    ← 首页 (重定向到 /dashboard)
    │   ├── login/ register/ verify-email/ recharge/
    │   ├── chat/                       ← 独立聊天页
    │   ├── dashboard/                  ← 仪表盘
    │   │   ├── layout.tsx              ← DashboardLayout (含 Sidebar 12项导航)
    │   │   ├── page.tsx                ← 概览
    │   │   ├── trade/                  ← AI 交易
    │   │   ├── ranking/                ← 交易榜单
    │   │   ├── classic/                ← 经典系统 (含 [subtab] 动态路由)
    │   │   ├── fundamental/            ← 基本面
    │   │   ├── three-screens/          ← 三屏系统 (screen1/2/3 + pipeline)
    │   │   ├── monitor/                ← SACG 监控 (sense/arrange/compute/graph)
    │   │   ├── memory/                 ← 记忆 (user/dze/skills/docs)
    │   │   ├── settings/               ← 系统设置
    │   │   ├── governance/             ← 治理
    │   │   ├── reports/                ← 报告
    │   │   ├── notebook/               ← Notebook
    │   │   ├── token-monitor/           ← Token 监控
    │   │   ├── graph-compression/       ← 图压缩
    │   │   ├── mood-board/ briefing/ bdsm/ ops/ meta-labeling/ feed/ workflow/
    │   │   ├── market/                  ← 市场营销 (6个子页面)
    │   │   └── test-visualization/
    │   ├── board/                      ← 治理/审批/提案/评审
    │   ├── reports/[id]/               ← 报告详情
    │   └── api/                        ← API Routes (96+ 端点)
    │
    ├── components/                     ← 组件
    │   ├── V3Card.tsx V3Button.tsx V3Badge.tsx V3StatusDot.tsx
    │   ├── V3Tooltip.tsx V3InlineSVG.tsx V3Spinner.tsx V3Empty.tsx
    │   └── features/                   ← 业务功能组件 (按域分层)
    │       ├── chat/                   ← 对话 (19个组件)
    │       ├── chain/                  ← 链路追踪 (7个组件)
    │       ├── three-screens/          ← 三屏 (7个组件 + charts/)
    │       ├── fundamental/            ← 基本面 (17个组件)
    │       ├── classic/               ← 经典交易 (8个组件)
    │       ├── monitor/                ← SACG 监控 (5个组件)
    │       ├── sacg/                   ← BAC/历史回放 (2个组件)
    │       ├── memory/                 ← 记忆 (6个组件)
    │       ├── settings/              ← 设置 (5个组件)
    │       ├── notebook/              ← Notebook (7个组件)
    │       ├── ranking/               ← 排行榜 (4个组件)
    │       ├── governance/            ← 治理
    │       ├── reports/               ← 报告
    │       ├── workflow/              ← 工作流 (3个组件)
    │       ├── orchestration/         ← 编排
    │       ├── dashboard/             ← 仪表盘
    │       ├── token-monitor/         ← Token 监控 (2个组件)
    │       └── graph-compression/     ← 图压缩
    │
    ├── stores/                         ← Zustand Store (12个)
    │   ├── session-store.ts  chain-store.ts  trading-store.ts
    │   ├── classic-store.ts  three-screens-store.ts  monitor-store.ts
    │   ├── memory-store.ts  user-memory-store.ts  notebook-store.ts
    │   ├── ui-store.ts  api-config-store.ts  auth-store.ts
    │   └── index.ts
    │
    └── lib/                            ← 工具库 (160+ 文件)
        ├── v3/api/                     ← API Client (20个域模块)
        ├── planner/                    ← 规划引擎 (21个文件)
        ├── orchestration/              ← 编排层
        ├── cognitive/                  ← 认知系统
        ├── case/                       ← 案例检索
        ├── dynamic-chain/              ← 动态链
        ├── dev-chain/                  ← 开发链
        ├── strategy/                   ← 策略
        ├── compressor-adapter/         ← 压缩适配器
        ├── scheduler/                  ← 调度器
        ├── notebook/                   ← Notebook
        ├── intent/                     ← 意图识别
        ├── memory/                     ← 记忆
        └── ... (task-manager, sse-dispatcher, auth, encryption, prisma 等)
```

## 关键文件索引

| 文件 | 位置 | 说明 |
|------|------|------|
| 综合技术文档 | `docs/v3-frontend-architecture.md` | 路由/架构/Store/组件/API/路线图 |
| 项目配置 | `package.json` | 依赖 (Next.js 15.4 / React 19 / Zustand 5 / Recharts 3.8 / @ai-sdk) |
| DashboardLayout | `src/app/dashboard/layout.tsx` | 仪表盘布局 (含 12 项 Sidebar 导航) |
| Store 索引 | `src/stores/index.ts` | 12 个 Zustand store 统一导出 |
| API Client | `src/lib/v3/api/client.ts` | 统一 API 封装 |
| 规划引擎 | `src/lib/planner/` | 21 个文件，含链规划/交叉验证/技能选择 |
| SACG 架构文档 | `../1-ARCHITECTURE/WORKBUDDY_OS_MODULAR_ARCHITECTURE.md` | 52 模块注册表 |
| 三屏系统文档 | `../2-KNOWLEDGE/1-TRADING/三屏系统架构.md` | Screen1/2/3 职责 |
| UI 设计规范 | `../3-FRONTEND/dream-universal-gateway/docs/UI_SPEC.md` | 色彩/布局/组件设计 (v2.3, 参考) |

## 代码统计

| 维度 | 数量 |
|------|------|
| 页面路由 (page.tsx) | 56 |
| API 路由 (route.ts) | 96+ |
| 组件 (features/ + V3*) | 100+ |
| Store | 12 |
| Lib 文件 | 160+ |

## 实施进度

| 阶段 | 状态 | 内容 |
|------|------|------|
| P0 基础架构 | ✅ 已完成 | Layout + Sidebar + 路由 + Store + API Client + SSE + Primitive |
| P1 核心交易 | ✅ 已完成 | ChatPanel + ChainTracker + 三屏系统 + 设置面板 |
| P2 经典+基本面 | ✅ 已完成 | ClassicScreen + FundamentalScreen (17个组件) |
| P3 SACG 可视化 | ✅ 已完成 | DAG/BAC/记忆/治理/报告/图压缩 |
| P3+ 增量 | ✅ 已完成 | Notebook + 排行榜 + 工作流 + 认知系统 + 训练循环 + 用户记忆 |

## 端口规划

| 前端 | 端口 | 项目路径 | 说明 |
|------|------|----------|------|
| 3.0 (旧) | 3000 | `3-FRONTEND/dream-universal-gateway/` | v2 三栏对话式界面 |
| 3.1 (当前) | 3001 | `3.1-FRONTEND/` | SACG 四层架构 + 完整交易系统 |

## 技术栈

- **框架**: Next.js 15.4 (App Router)
- **语言**: TypeScript 5.7 (strict)
- **UI**: Tailwind CSS v4 + Inline SVG (无图标库)
- **状态**: Zustand 5.0 (12 个按领域拆分)
- **可视化**: Recharts 3.8 + 原生 SVG
- **AI**: @ai-sdk/openai + @ai-sdk/react
- **认证**: NextAuth.js v5 + Prisma
- **测试**: Jest + @testing-library/react
