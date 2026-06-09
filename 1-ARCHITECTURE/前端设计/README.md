# 前端设计文档索引

> **版本**: v1.0
> **更新日期**: 2026-05-14

---

## 📚 文档列表

### 架构设计

| 文档 | 描述 | 状态 |
|------|------|------|
| [ARCHITECTURE.md](./ARCHITECTURE.md) | 系统架构设计 | ✅ |
| [FRONTEND_ARCHITECTURE.md](./FRONTEND_ARCHITECTURE.md) | 前端架构详细设计 | ✅ |

### 功能模块

| 文档 | 描述 | 状态 |
|------|------|------|
| [USER_SYSTEM_DESIGN.md](./USER_SYSTEM_DESIGN.md) | 用户系统设计 | ✅ |
| [API_CONFIG_DESIGN.md](./API_CONFIG_DESIGN.md) | API配置设计 | ✅ |
| [TRADING_CONFIG_DESIGN.md](./TRADING_CONFIG_DESIGN.md) | 交易参数设计 | ✅ |
| [STRATEGY_CONFIG_DESIGN.md](./STRATEGY_CONFIG_DESIGN.md) | 策略设置设计 | ✅ |
| [CHANNEL_DESIGN.md](./CHANNEL_DESIGN.md) | 通信通道设计 | ✅ |

### 交互设计

| 文档 | 描述 | 状态 |
|------|------|------|
| [INTENT_ROUTER.md](./INTENT_ROUTER.md) | 用户意图路由 | ✅ |
| [UI_SPEC.md](./UI_SPEC.md) | UI设计规范 | ✅ |
| [UI_ROADMAP.md](./UI_ROADMAP.md) | UI开发路线图 | ✅ |

### 集成设计

| 文档 | 描述 | 状态 |
|------|------|------|
| [FRONTEND_WB_INTEGRATION.md](./FRONTEND_WB_INTEGRATION.md) | WorkBuddy集成 | ✅ |
| [CHAIN_ORCHESTRATOR.md](./CHAIN_ORCHESTRATOR.md) | 链式编排设计 | ✅ |
| [TECH_STACK_EVALUATION.md](./TECH_STACK_EVALUATION.md) | 技术栈评估 | ✅ |

---

## 🏗️ 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                 Dream Universal Gateway                     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   ┌─────────────────────────────────────────────────────┐   │
│   │                  用户界面层                           │   │
│   │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌───────┐ │   │
│   │  │ Dashboard│  │ Settings │  │ Reports │  │ Chat  │ │   │
│   │  └─────────┘  └─────────┘  └─────────┘  └───────┘ │   │
│   └─────────────────────────────────────────────────────┘   │
│                             │                               │
│   ┌─────────────────────────────────────────────────────┐   │
│   │                  状态管理层                           │   │
│   │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌───────┐ │   │
│   │  │ auth    │  │ chat    │  │ config  │  │credit │ │   │
│   │  │ store   │  │ store   │  │ store   │  │ store │ │   │
│   │  └─────────┘  └─────────┘  └─────────┘  └───────┘ │   │
│   └─────────────────────────────────────────────────────┘   │
│                             │                               │
│   ┌─────────────────────────────────────────────────────┐   │
│   │                  核心库层                             │   │
│   │  ┌─────────┐  ┌─────────┐  ┌─────────┐             │   │
│   │  │  auth   │  │ task    │  │ prisma  │             │   │
│   │  │         │  │ manager │  │ client  │             │   │
│   │  └─────────┘  └─────────┘  └─────────┘             │   │
│   └─────────────────────────────────────────────────────┘   │
│                             │                               │
└─────────────────────────────┼───────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────┐
│                    中台服务层                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ 产物中台     │  │ WorkBuddy   │  │ 百炼API     │       │
│  │ Artifact Hub │  │              │  │              │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
└─────────────────────────────────────────────────────────────┘
```

---

## 📊 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| 框架 | Next.js 14 | App Router |
| 语言 | TypeScript | 类型安全 |
| UI | TailwindCSS | 样式框架 |
| 状态 | Zustand | 状态管理 |
| 数据库 | Prisma + PostgreSQL | ORM |
| 认证 | NextAuth.js | JWT认证 |
| 部署 | Docker | 容器化 |

---

## 🚀 快速链接

- [系统架构](./ARCHITECTURE.md)
- [用户系统](./USER_SYSTEM_DESIGN.md)
- [API配置](./API_CONFIG_DESIGN.md)
- [WorkBuddy集成](./FRONTEND_WB_INTEGRATION.md)
