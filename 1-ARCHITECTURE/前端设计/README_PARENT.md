# Dream Universal Gateway

> 通用AI对话入口 — 意图识别+产物路由驱动的金融决策助手

## 核心设计

**系统灵魂是意图识别，不是链路可视化。**

用户用自然语言表达需求，系统在后台：
1. 识别用户意图（问行情？要分析？想交易？）
2. 检索已有产物（有没有现成的分析可以直接用？）
3. 智能路由（直接返回/增量更新/按需执行链路）
4. 隐藏内部术语（用户看到"深度分析"，不是"A2第一性原理"）

## 三层架构

```
Layer 1: 通用AI前端入口 (/chat)    ← 本项目核心
Layer 2: 产物中台 (/feed :3456)    ← 现有Next.js项目
Layer 3: 产物源 (~/.workbuddy/)    ← 现有文件系统
```

## 四大独立功能设置

| 功能 | 定位 | 入口 | 文档 |
|------|------|------|------|
| **API配置** | 交易所/LLM/数据源连接凭证 | ⚙️ API配置 | API_CONFIG_DESIGN.md |
| **交易参数** | 交易行为约束+下单门禁 | 💰 交易设置 | TRADING_CONFIG_DESIGN.md ⭐ |
| **策略设置** | 交易策略选择+定时执行 | 🎯 策略设置 | STRATEGY_CONFIG_DESIGN.md ⭐ |
| **通信渠道** | 消息推送通道(TG/微信) | 📡 通信渠道 | CHANNEL_DESIGN.md |

> 四者互不耦合，用户可只配置其中之一。策略执行需要API+交易参数同时就绪。

## 文档索引

| 文档 | 说明 | 优先级 |
|------|------|--------|
| [docs/INTENT_ROUTER.md](docs/INTENT_ROUTER.md) | **意图识别与路由引擎（系统灵魂，核心文档）** | ⭐⭐⭐ |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 总体架构方案 | ⭐⭐⭐ |
| [docs/TRADING_CONFIG_DESIGN.md](docs/TRADING_CONFIG_DESIGN.md) | **交易参数配置+下单门禁（v2.1新增核心）** | ⭐⭐⭐ |
| [docs/STRATEGY_CONFIG_DESIGN.md](docs/STRATEGY_CONFIG_DESIGN.md) | **策略设置+定时执行（v2.2新增核心）** | ⭐⭐⭐ |
| [docs/UI_SPEC.md](docs/UI_SPEC.md) | 前端UI详细规范（含术语禁用清单） | ⭐⭐ |
| [docs/API_CONFIG_DESIGN.md](docs/API_CONFIG_DESIGN.md) | API连接凭证管理 | ⭐⭐ |
| [docs/CHANNEL_DESIGN.md](docs/CHANNEL_DESIGN.md) | 通信渠道功能详细设计 | ⭐ |
| [docs/CHAIN_ORCHESTRATOR.md](docs/CHAIN_ORCHESTRATOR.md) | 内部链路执行器（用户不可见） | ⭐ |

## 设计原则

| 原则 | 说明 |
|------|------|
| 意图即路由 | 用户表达=意图识别=处理路径决策 |
| 产物优先 | 已有产物先检索复用，不重跑全链路 |
| 隐藏内部 | 用户看到"分析行情"，不是"A2第一性原理" |
| 门禁必过 | 交易操作必须通过TradingGate门禁校验 |
| 策略驱动 | 策略推荐(A4推送)+自定义策略(A系列调研)→定时执行 |

## 处理策略

| 策略 | 条件 | 资源消耗 |
|------|------|----------|
| 产物直返 | 已有产物充足且时效<4h | 0次LLM调用 |
| 增量更新 | 已有产物可用但需补充 | 1次LLM调用 |
| 部分链路 | 部分阶段产物缺失 | 2-3次LLM调用 |
| 完整链路 | 无可用产物/用户要求全面分析 | 5+次LLM调用 |

## 目录结构

```
3-FRONTEND/dream-universal-gateway/
├── docs/               # 设计文档
├── frontend/           # 前端组件（开发时集成到 web/ 目录）
├── backend/            # 后端逻辑（开发时集成到 web/app/api/ 目录）
└── shared/             # 共享类型和工具
```

## 实施阶段

| 阶段 | 目标 | 预计 |
|------|------|------|
| P0 | 意图引擎+核心对话+API配置+交易参数配置 | 1.5周 |
| P1 | 链路执行+进度展示(用户语言) | 1周 |
| P2 | 通信渠道(TG/微信) | 1周 |
| P3 | 持久化与多会话 | 1周 |
| P4 | 通用化扩展 | 2周 |

## 开发说明

> Layer 1 和 Layer 2 共享同一个 Next.js 项目。
> 实际开发时，组件直接写在 `~/.workbuddy/skills/dream-exit-skill-v2/web/` 下，
> 本仓库作为规划文档和独立模块的开发暂存区。
