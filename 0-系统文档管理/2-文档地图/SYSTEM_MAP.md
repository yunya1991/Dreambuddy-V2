# 全系统文档地图 — SYSTEM_MAP

> **版本**: v2.0 | **更新日期**: 2026-07-31
> **定位**: 按系统组织的全项目文档导航地图（对齐 SSoT v3.0）
> **关联**: [INDEX.md](../INDEX.md) · [TOPIC_MAP.md](./TOPIC_MAP.md) · [ARCHITECTURE_MAP.md](./ARCHITECTURE_MAP.md)

---

## 系统全景

DreamBuddy-V2 由 **1 个文档元层 + 7 个顶层模块 + 7 个交易子系统 + 6 个辅助模块** 组成。

```
DreamBuddy-V2/
│
├── 0-系统文档管理/              📚 元层（本目录）
├── 1-ARCHITECTURE/              🏛️ 架构设计
├── 2-GOVERNANCE/                ⚖️ 治理合规
├── 2-KNOWLEDGE/                 📖 知识库
├── 3-FRONTEND/                  🎨 前端系统
├── 4-MEMORY/                    🧠 记忆系统
├── 5-BUSINESS/                  💼 业务管理
├── 6-TRADING/                   📈 交易系统
│
├── 10-经典指标系统/             🎯 核心交易决策引擎
├── 11-易经推理系统/             ☯️ BCRM + 易经推理
├── 12-三屏趋势系统/             📊 V4+波浪趋势策略
├── 13-通用风控模块/             🛡️ 三层风控体系
├── 14-V15经典马丁策略/          💰 马丁格尔策略（标杆）
├── 16-调控系统/                 🎛️ 宏观离场调控
├── 17-v4-wave-strategy/         🌊 V4波浪策略
│
├── 3-EVOLUTION/                 🧬 进化引擎（实验）
├── 6-图结构上下文压缩/          🔗 图压缩（实验）
├── 7-产物中台/                  📦 产物管理
├── 15-监控告警系统/             🚨 监控告警
└── experiments/                 🧪 AB 交易实验
```

---

## L0 — 文档元层

### 0-系统文档管理

| 属性 | 值 |
|------|-----|
| 定位 | 全项目文档体系的元层管理中枢 |
| 主入口 | [README.md](../../0-系统文档管理/README.md) |
| 索引 | [INDEX.md](../../0-系统文档管理/INDEX.md) |

**核心文档**：
- [1-规范体系/DOC_STANDARD.md](../../0-系统文档管理/1-规范体系/DOC_STANDARD.md) — 文档编写规范
- [1-规范体系/DOC_CLASSIFICATION.md](../../0-系统文档管理/1-规范体系/DOC_CLASSIFICATION.md) — 文档分类体系
- [2-文档地图/SYSTEM_MAP.md](../../0-系统文档管理/2-文档地图/SYSTEM_MAP.md) — 本文件
- [3-文档治理/DOC_DEBT_INDEX.md](../../0-系统文档管理/3-文档治理/DOC_DEBT_INDEX.md) — 文档技术债

---

## L1 — 顶层模块

### 1-ARCHITECTURE（架构设计）

| 属性 | 值 |
|------|-----|
| 定位 | 整体架构文档+设计文档+索引 |
| 主入口 | [README.md](../../1-ARCHITECTURE/README.md) ⚠️ 过时 |
| 状态 | ✅ SSoT v3.0 已建立（[SYSTEM_ARCHITECTURE_OVERVIEW.md](../../1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md)）；README 待重构（DD-002） |

**关键文档**：
- [SYSTEM_ARCHITECTURE_OVERVIEW.md](../../1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md)
- [工作索引/SKILL_INDEX.md](../../1-ARCHITECTURE/工作索引/SKILL_INDEX.md)
- [中台设计/COMPANY_CENTRAL_HUB.md](../../1-ARCHITECTURE/中台设计/COMPANY_CENTRAL_HUB.md)
- [dreamos/docs/ENGINEERING_INDEX.md](../../1-ARCHITECTURE/dreamos/docs/ENGINEERING_INDEX.md)

### 2-GOVERNANCE（治理合规）

| 属性 | 值 |
|------|-----|
| 定位 | 合规+门禁+审计 |
| 主入口 | [README.md](../../2-GOVERNANCE/README.md) |

**关键文档**：
- [GOVERNANCE_CHARTER.md](../../2-GOVERNANCE/GOVERNANCE_CHARTER.md)
- [COMPLIANCE_RULES.md](../../2-GOVERNANCE/COMPLIANCE_RULES.md)
- [AUDIT_LOGS.md](../../2-GOVERNANCE/AUDIT_LOGS.md)

### 2-KNOWLEDGE（知识库）

| 属性 | 值 |
|------|-----|
| 定位 | 从 Skills 蒸馏的跨领域系统知识 |
| 主入口 | [INDEX.md](../../2-KNOWLEDGE/INDEX.md) |
| 状态 | ✅ 五大域完整（TRADING/TECHNICAL/THEORY/OPERATIONS/METHODOLOGY） |

**关键子目录**：
- [1-TRADING/](../../2-KNOWLEDGE/1-TRADING/) — 交易领域知识（9 文件）
- [2-TECHNICAL/](../../2-KNOWLEDGE/2-TECHNICAL/) — 技术运维知识（5 文件）
- [3-THEORY/](../../2-KNOWLEDGE/3-THEORY/) — 哲学/理论（4 文件）
- [4-OPERATIONS/](../../2-KNOWLEDGE/4-OPERATIONS/) — 运营治理（6 文件）
- [5-METHODOLOGY/](../../2-KNOWLEDGE/5-METHODOLOGY/) — 方法论（5 文件）

### 其他顶层模块

| 模块 | 入口 | 说明 |
|------|------|------|
| [3-FRONTEND](../../3-FRONTEND/) | [FRONTEND_SYSTEM.md](../../3-FRONTEND/FRONTEND_SYSTEM.md) | 前端架构 |
| [4-MEMORY](../../4-MEMORY/) | [MEMORY_SYSTEM.md](../../4-MEMORY/MEMORY_SYSTEM.md) | 记忆学习 |
| [5-BUSINESS](../../5-BUSINESS/) | [BUSINESS_SYSTEM.md](../../5-BUSINESS/BUSINESS_SYSTEM.md) | 业务运营 |
| [6-TRADING](../../6-TRADING/) | [TRADING_SYSTEM.md](../../6-TRADING/TRADING_SYSTEM.md) | A0-A9 流水线 |

---

## L2 — 交易子系统

> 7 个子系统均遵循 [DOC_STANDARD.md](../1-规范体系/DOC_STANDARD.md) 规范，5 文档齐全。

### 10-经典指标系统

| 属性 | 值 |
|------|-----|
| 定位 | 核心交易决策引擎，16 层信号体系 |
| 主入口 | [README.md](../../10-经典指标系统/README.md) |
| 核心服务 | ml_trade_service.py（端口 8092）、classic_exit_system.py、carry_service.py |
| 文档评级 | A |

**文档清单**：
- [docs/ENGINEERING_INDEX.md](../../10-经典指标系统/docs/ENGINEERING_INDEX.md) v1.1
- [docs/TECHNICAL_DESIGN.md](../../10-经典指标系统/docs/TECHNICAL_DESIGN.md) v2.0
- [docs/API_SPEC.md](../../10-经典指标系统/docs/API_SPEC.md) v1.1
- [docs/CHANGELOG.md](../../10-经典指标系统/docs/CHANGELOG.md) v1.1

### 11-易经推理系统

| 属性 | 值 |
|------|-----|
| 定位 | BCRM 2.0 + 易经推理 + 辩证 ML |
| 主入口 | [README.md](../../11-易经推理系统/README.md) |
| 核心模块 | polling_trader.py、yijing_exit_system.py、bcrm2_adapter.py、bcrm2/exit_manager.py |
| 文档评级 | A |

**文档清单**：
- [docs/ENGINEERING_INDEX.md](../../11-易经推理系统/docs/ENGINEERING_INDEX.md) v2.7
- [docs/TECHNICAL_DESIGN.md](../../11-易经推理系统/docs/TECHNICAL_DESIGN.md) v4.4
- [docs/API_SPEC.md](../../11-易经推理系统/docs/API_SPEC.md) v2.9
- [docs/CHANGELOG.md](../../11-易经推理系统/docs/CHANGELOG.md) v2.9

### 12-三屏趋势系统

| 属性 | 值 |
|------|-----|
| 定位 | V4+波浪互斥融合趋势策略 |
| 主入口 | [README.md](../../12-三屏趋势系统/README.md) |
| 核心模块 | engine.py、signals.py、ml/halving_top_exit_strategy.py |
| 文档评级 | A |

**文档清单**：
- [docs/ENGINEERING_INDEX.md](../../12-三屏趋势系统/docs/ENGINEERING_INDEX.md) v4.0.0
- [docs/TECHNICAL_DESIGN.md](../../12-三屏趋势系统/docs/TECHNICAL_DESIGN.md) v4.0
- [docs/API_SPEC.md](../../12-三屏趋势系统/docs/API_SPEC.md) v4.0.0
- [docs/CHANGELOG.md](../../12-三屏趋势系统/docs/CHANGELOG.md) v4.0.0

### 13-通用风控模块

| 属性 | 值 |
|------|-----|
| 定位 | 三层风控（事前门禁/仓位/事后离场）+ L1 评估 + ML |
| 主入口 | [README.md](../../13-通用风控模块/README.md) |
| 核心模块 | core/engine.py（RiskEngine）、core/l1_assessor.py、core/ml_model.py |
| 文档评级 | A |

**文档清单**：
- [docs/ENGINEERING_INDEX.md](../../13-通用风控模块/docs/ENGINEERING_INDEX.md)
- [docs/TECHNICAL_DESIGN.md](../../13-通用风控模块/docs/TECHNICAL_DESIGN.md)
- [docs/API_SPEC.md](../../13-通用风控模块/docs/API_SPEC.md) v1.1.0
- [docs/CHANGELOG.md](../../13-通用风控模块/docs/CHANGELOG.md) v1.1.0

### 14-V15经典马丁策略（标杆）

| 属性 | 值 |
|------|-----|
| 定位 | V15 马丁格尔策略，文档标杆 |
| 主入口 | [README.md](../../14-V15经典马丁策略/README.md) |
| 核心模块 | core/v15_signal.py、core/v15_trader.py、lib/v15_api_server.py |
| 文档评级 | A（标杆） |

**文档清单**：
- [docs/ENGINEERING_INDEX.md](../../14-V15经典马丁策略/docs/ENGINEERING_INDEX.md) v5.1
- [docs/TECHNICAL_DESIGN.md](../../14-V15经典马丁策略/docs/TECHNICAL_DESIGN.md) v5.1
- [docs/API_SPEC.md](../../14-V15经典马丁策略/docs/API_SPEC.md) v3.1
- [docs/CHANGELOG.md](../../14-V15经典马丁策略/docs/CHANGELOG.md) v5.1

### 16-调控系统

| 属性 | 值 |
|------|-----|
| 定位 | 跨系统宏观战略离场决策层 |
| 主入口 | [README.md](../../16-调控系统/README.md) |
| 核心模块 | core/unified_position_query.py、core/skill_engine.py、core/a9_exit_decision.py |
| 文档评级 | A |

**文档清单**：
- [docs/ENGINEERING_INDEX.md](../../16-调控系统/docs/ENGINEERING_INDEX.md) v2.0
- [docs/TECHNICAL_DESIGN.md](../../16-调控系统/docs/TECHNICAL_DESIGN.md) v2.0
- [docs/API_SPEC.md](../../16-调控系统/docs/API_SPEC.md) v2.0
- [docs/CHANGELOG.md](../../16-调控系统/docs/CHANGELOG.md) v2.0

### 17-v4-wave-strategy

| 属性 | 值 |
|------|-----|
| 定位 | V4 减半周期 exit + 艾略特波浪互斥融合策略 |
| 主入口 | [README.md](../../17-v4-wave-strategy/README.md) |
| 核心模块 | ewave_strategy_adapter.py、halving_cycle_exit.py |
| 文档评级 | A |

**文档清单**：
- [docs/ENGINEERING_INDEX.md](../../17-v4-wave-strategy/docs/ENGINEERING_INDEX.md) v1.0
- [docs/TECHNICAL_DESIGN.md](../../17-v4-wave-strategy/docs/TECHNICAL_DESIGN.md) v1.0
- [docs/API_SPEC.md](../../17-v4-wave-strategy/docs/API_SPEC.md) v1.0
- [docs/CHANGELOG.md](../../17-v4-wave-strategy/docs/CHANGELOG.md) v1.0

---

## L3 — 辅助模块

| 模块 | 路径 | 文档状态 | 说明 |
|------|------|----------|------|
| 3-EVOLUTION | [3-EVOLUTION/](../../3-EVOLUTION/) | ⚠️ 无文档 | TypeScript 进化引擎 |
| 6-图结构压缩 | [6-图结构上下文压缩/](../../6-图结构上下文压缩/) | ⚠️ 有 SPEC/TECHNICAL-DOC | 实验性 |
| 7-产物中台 | [7-产物中台/docs/](../../7-产物中台/docs/) | ⚠️ 部分完整 | 产物管理 |
| 15-监控告警 | [15-监控告警系统/](../../15-监控告警系统/) | ⚠️ 仅 README | 监控告警 |
| experiments | [experiments/](../../experiments/) | ❌ 无文档 | AB 交易实验 |
| dreamos | [1-ARCHITECTURE/dreamos/docs/](../../1-ARCHITECTURE/dreamos/docs/) | ⚠️ 部分完整 | DreamOS CLI |

---

**文档版本**: v2.0
**最后更新**: 2026-07-31
