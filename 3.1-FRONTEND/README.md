# DreamBuddy v3 Frontend

> 独立于 `3-FRONTEND/dream-universal-gateway/` 的 v3 前端项目中心。
> 实际运行代码在 `3-FRONTEND/` 下（Next.js 项目），本目录管理设计文档、核心组件规范和开发索引。

## 目录结构

```
3.1-FRONTEND/
├── README.md                           ← 你在这里
├── docs/
│   └── v3-frontend-architecture.md      ← 综合技术文档（1751行）
│       ├── 第一章：项目概述与目标
│       ├── 第二章：现状分析
│       ├── 第三章：v3 架构设计（路由 + SACG映射 + 三屏应用层 + 状态管理 + 组件层级）
│       ├── 第四章：API 集成方案
│       ├── 第五章：设计规范
│       ├── 第六章：P0-P3 实施路线图
│       └── 附录 A-D
├── design/
│   └── v2-design-draft/                ← v2 设计稿（.design 文件，仅供参考）
├── components/                         ← 组件规范目录（设计参考）
│   ├── layout/                         ← AppShell / Sidebar / TopBar
│   ├── primitives/                     ← Button / Card / Badge / Dialog 等
│   └── features/                       ← 业务功能组件
│       ├── chat/                       ← ChatPanel / MessageList / ChatInput
│       ├── chain/                      ← ChainTracker / ReflectorBadge / CrossValidation
│       ├── trade/                      ← TradeScreen 相关
│       ├── classic/                    ← ClassicScreen / PhasePanel / GovernanceFlow
│       ├── fundamental/                ← FundamentalScreen / SentimentHeatmap
│       ├── three-screens/              ← Screen1/2/3 / Pipeline / DirectionAnchor
│       ├── monitor/                    ← SACGVisualizer / DAGGraphView / BACTimeline
│       ├── memory/                     ← DZEChainView / MemoryTimeline
│       ├── settings/                   ← ApiKeyManager / TradingParams / StrategyManager
│       ├── reports/                    ← ArtifactList / ArtifactFilter
│       └── governance/                 ← GovernanceScreen / ApprovalFlow
├── stores/                             ← Zustand Store 规范
├── hooks/                              ← 自定义 Hook 规范
├── lib/                                ← 工具库规范
│   ├── api/                            ← API Client 封装
│   ├── utils/                          ← 通用工具函数
│   └── types/                          ← 类型定义
└── assets/                             ← 设计资源
```

## 关键文件索引

| 文件 | 位置 | 说明 |
|------|------|------|
| v3 综合技术文档 | `docs/v3-frontend-architecture.md` | 路由/架构/Store/组件/API/路线图 |
| v3 运行代码 | `../3-FRONTEND/dream-universal-gateway/src/app/v3/` | 实际 Next.js 页面 |
| v3 主题样式 | `../3-FRONTEND/dream-universal-gateway/src/app/v3/v3-theme.css` | CSS 变量和工具类 |
| v3 Layout | `../3-FRONTEND/dream-universal-gateway/src/app/v3/layout.tsx` | 独立布局 |
| v3 AppShell | `../3-FRONTEND/dream-universal-gateway/src/app/v3/components/V3AppShell.tsx` | 布局骨架 |
| v3 Sidebar | `../3-FRONTEND/dream-universal-gateway/src/app/v3/components/V3Sidebar.tsx` | 10 导航项 |
| v3 TopBar | `../3-FRONTEND/dream-universal-gateway/src/app/v3/components/V3TopBar.tsx` | 页面标题+状态 |
| SACG 架构文档 | `../1-ARCHITECTURE/WORKBUDDY_OS_MODULAR_ARCHITECTURE.md` | 52 模块注册表 |
| 三屏系统文档 | `../2-KNOWLEDGE/1-TRADING/三屏系统架构.md` | Screen1/2/3 职责 |

## 实施进度

| 阶段 | 状态 | 内容 |
|------|------|------|
| P0 文档 | 已完成 | 技术文档 + 三屏应用层补充 |
| P0 骨架 | 已完成 | Layout + Sidebar + TopBar + 路由占位 + 主题 |
| P1 核心交易 | 待开始 | ChatPanel / SSE / ChainTracker / 设置面板 |
| P1 三屏系统 | 待开始 | Screen1/2/3 + Pipeline + DirectionConstraint |
| P2 经典+基本面 | 待开始 | ClassicScreen / FundamentalScreen |
| P3 SACG 可视化 | 待开始 | DAG / BAC / D-Z-E / Governance |

## 端口规划

| 前端 | 端口 | 路由前缀 |
|------|------|----------|
| v2 (现有) | 3000 | `/dashboard`, `/v2/` |
| v3 (新) | 3001 | `/v3/dashboard/` |
