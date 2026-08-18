# 全项目文档索引 — INDEX

> **版本**: v2.1 | **更新日期**: 2026-08-02
> **定位（视角 B）**: **文档导航中枢，不是架构内容本身**。由 0-系统文档管理 维护，告诉你「到哪里找什么文档」。
> **架构唯一事实源（SSoT）**: 所有架构争议以 [1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md](../1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md) v3.0 为准。
> **维护**: 每次新增/删除文档时同步更新；由 `4-工具与自动化/doc_coverage.py` 自动校验（已建成）

---

## 🎯 视角 B 文档分层模型（重要！）

```
0-系统文档管理/                    ← 你在这里：导航中枢（地图 + 规范 + 治理）
├── 告诉你「文档有哪些、到哪找」    （SYSTEM_MAP / ARCHITECTURE_MAP / TOPIC_MAP）
├── 告诉你「文档该怎么写」          （DOC_STANDARD / DOC_CLASSIFICATION / 5 套模板）
└── 告诉你「文档债有哪些、怎么治」  （DOC_DEBT_INDEX / DOC_LIFECYCLE / QUALITY_AUDIT）

1-ARCHITECTURE/                    ← 架构主入口（SSoT 所在地）
└── SYSTEM_ARCHITECTURE_OVERVIEW.md v3.0  ← ★ 唯一架构事实源
    ├── 三层架构（OS内核 + 能力层 + 应用层）
    ├── 认知系统 + 记忆进化 + 双闭环对称
    ├── 硬约束清单（违反即 bug）
    └── 技术债 103 项全景 + 修复批次规划

各子系统 10/11/12/13/14/16-xxx/    ← 子系统级 5 文档标准
    └── README / ENGINEERING_INDEX / TECHNICAL_DESIGN / API_SPEC / CHANGELOG
```

---

## L0 — 顶层元文档

| 文档 | 路径 | 职责 |
|------|------|------|
| 项目入口 | [README.md](../README.md) | 极简入口，指向 0号系统 |
| 文档管理中枢 | [0-系统文档管理/README.md](./README.md) | 文档体系的元层管理（本目录说明） |
| 文档规范 | [0-系统文档管理/1-规范体系/DOC_STANDARD.md](./1-规范体系/DOC_STANDARD.md) | 文档编写规范 + 5 套模板 |
| 文档分类 | [0-系统文档管理/1-规范体系/DOC_CLASSIFICATION.md](./1-规范体系/DOC_CLASSIFICATION.md) | L0-L4 分级 + A/B/C 质量分级 |
| 技术债（代码） | [DEBT_INDEX.md](../DEBT_INDEX.md) v2.4 | 103 项代码债全景 + 8 分类 + 4 优先级 + 修复路线图 |
| 文档债 | [0-系统文档管理/3-文档治理/DOC_DEBT_INDEX.md](./3-文档治理/DOC_DEBT_INDEX.md) | 文档类债务登记与跟踪 |
| 贡献指南 | [CONTRIBUTING.md](../CONTRIBUTING.md) | 项目贡献流程 |

---

## L1 — 顶层架构与治理

| 文档 | 路径 | 职责 | 状态 |
|------|------|------|------|
| ★ **架构总览（SSoT）** | [1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md](../1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md) **v3.0** | **架构唯一事实源**：三层架构 + SACG OS内核 + 认知系统 + 双闭环 + 硬约束 + 技术债全景 | ✅ 草稿待评审 |
| （历史归档）旧模块化架构 | [1-ARCHITECTURE/WORKBUDDY_OS_MODULAR_ARCHITECTURE.md](../1-ARCHITECTURE/WORKBUDDY_OS_MODULAR_ARCHITECTURE.md) v1.1 | TS 视角早期设计，仅作迁移参考，**所有决策以 v3.0 为准** | 📦 归档参考 |
| （历史归档）旧总览 | [1-ARCHITECTURE/README.md](../1-ARCHITECTURE/README.md) | 描述旧"六大核心系统"，与实际子系统目录 10-16 不匹配 | ⚠️ 待替换 |
| 治理章程 | [2-GOVERNANCE/GOVERNANCE_CHARTER.md](../2-GOVERNANCE/GOVERNANCE_CHARTER.md) | 系统根本大法（宪法级） | ✅ |
| 治理系统 | [2-GOVERNANCE/GOVERNANCE_SYSTEM.md](../2-GOVERNANCE/GOVERNANCE_SYSTEM.md) | 六部门 + 双中台 + 四层合规体系设计 | 🟡 部分 |
| 合规规则 | [2-GOVERNANCE/COMPLIANCE_RULES.md](../2-GOVERNANCE/COMPLIANCE_RULES.md) | 合规检查清单 | 🟡 部分 |
| 审计日志 | [2-GOVERNANCE/AUDIT_LOGS.md](../2-GOVERNANCE/AUDIT_LOGS.md) | 审计记录 | ⚠️ |
| 知识库入口 | [2-KNOWLEDGE/INDEX.md](../2-KNOWLEDGE/INDEX.md) | 交易/技术/理论领域知识库 | ✅ |
| 记忆系统架构 | [4-MEMORY/MEMORY_SYSTEM.md](../4-MEMORY/MEMORY_SYSTEM.md) · [4-MEMORY/6-应用记忆索引/MEMORY_INTERFACE_SPEC.md](../4-MEMORY/6-应用记忆索引/MEMORY_INTERFACE_SPEC.md) | L0/L1/L2 三层记忆 + 7+2 接口契约 + 贝叶斯进化 v2 | 🟡 参考 v3.0 §6, §10.2 |
| 业务管理 | [5-BUSINESS/BUSINESS_SYSTEM.md](../5-BUSINESS/BUSINESS_SYSTEM.md) | 业务运营系统设计 | ⚠️ |
| 交易中台 | [6-TRADING/TRADING_SYSTEM.md](../6-TRADING/TRADING_SYSTEM.md) | A0-A9 交易流水线与 SKILL 引擎 | 🟡 |
| 前端系统 | [3-FRONTEND/FRONTEND_SYSTEM.md](../3-FRONTEND/FRONTEND_SYSTEM.md) | 前端架构设计 | ⚠️ 待更新 |

---

## L2 — 子系统文档（7 个交易子系统）

> 每个子系统遵循 [DOC_STANDARD.md](./1-规范体系/DOC_STANDARD.md) 规范，5 文档齐全。

### 10-经典指标系统

| 文档 | 路径 | 版本 |
|------|------|------|
| README | [10-经典指标系统/README.md](../10-经典指标系统/README.md) | - |
| 工程索引 | [10-经典指标系统/docs/ENGINEERING_INDEX.md](../10-经典指标系统/docs/ENGINEERING_INDEX.md) | v1.1 |
| 技术设计 | [10-经典指标系统/docs/TECHNICAL_DESIGN.md](../10-经典指标系统/docs/TECHNICAL_DESIGN.md) | v2.0 |
| 接口规格 | [10-经典指标系统/docs/API_SPEC.md](../10-经典指标系统/docs/API_SPEC.md) | v1.1 |
| 变更日志 | [10-经典指标系统/docs/CHANGELOG.md](../10-经典指标系统/docs/CHANGELOG.md) | v1.1 |

### 11-易经推理系统

| 文档 | 路径 | 版本 |
|------|------|------|
| README | [11-易经推理系统/README.md](../11-易经推理系统/README.md) | - |
| 工程索引 | [11-易经推理系统/docs/ENGINEERING_INDEX.md](../11-易经推理系统/docs/ENGINEERING_INDEX.md) | v2.6 |
| 技术设计 | [11-易经推理系统/docs/TECHNICAL_DESIGN.md](../11-易经推理系统/docs/TECHNICAL_DESIGN.md) | v2.9 |
| 接口规格 | [11-易经推理系统/docs/API_SPEC.md](../11-易经推理系统/docs/API_SPEC.md) | v2.9 |
| 变更日志 | [11-易经推理系统/docs/CHANGELOG.md](../11-易经推理系统/docs/CHANGELOG.md) | v2.9 |

### 12-三屏趋势系统

| 文档 | 路径 | 版本 |
|------|------|------|
| README | [12-三屏趋势系统/README.md](../12-三屏趋势系统/README.md) | - |
| 工程索引 | [12-三屏趋势系统/docs/ENGINEERING_INDEX.md](../12-三屏趋势系统/docs/ENGINEERING_INDEX.md) | v4.0.0 |
| 技术设计 | [12-三屏趋势系统/docs/TECHNICAL_DESIGN.md](../12-三屏趋势系统/docs/TECHNICAL_DESIGN.md) | v4.0 |
| 接口规格 | [12-三屏趋势系统/docs/API_SPEC.md](../12-三屏趋势系统/docs/API_SPEC.md) | v4.0.0 |
| 变更日志 | [12-三屏趋势系统/docs/CHANGELOG.md](../12-三屏趋势系统/docs/CHANGELOG.md) | v4.0.0 |

### 13-通用风控模块

| 文档 | 路径 | 版本 |
|------|------|------|
| README | [13-通用风控模块/README.md](../13-通用风控模块/README.md) | - |
| 工程索引 | [13-通用风控模块/docs/ENGINEERING_INDEX.md](../13-通用风控模块/docs/ENGINEERING_INDEX.md) | - |
| 技术设计 | [13-通用风控模块/docs/TECHNICAL_DESIGN.md](../13-通用风控模块/docs/TECHNICAL_DESIGN.md) | - |
| 接口规格 | [13-通用风控模块/docs/API_SPEC.md](../13-通用风控模块/docs/API_SPEC.md) | v1.1.0 |
| 变更日志 | [13-通用风控模块/docs/CHANGELOG.md](../13-通用风控模块/docs/CHANGELOG.md) | v1.1.0 |

### 14-V15经典马丁策略（标杆）

| 文档 | 路径 | 版本 |
|------|------|------|
| README | [14-V15经典马丁策略/README.md](../14-V15经典马丁策略/README.md) | - |
| 工程索引 | [14-V15经典马丁策略/docs/ENGINEERING_INDEX.md](../14-V15经典马丁策略/docs/ENGINEERING_INDEX.md) | v5.1 |
| 技术设计 | [14-V15经典马丁策略/docs/TECHNICAL_DESIGN.md](../14-V15经典马丁策略/docs/TECHNICAL_DESIGN.md) | v5.1 |
| 接口规格 | [14-V15经典马丁策略/docs/API_SPEC.md](../14-V15经典马丁策略/docs/API_SPEC.md) | v3.1 |
| 变更日志 | [14-V15经典马丁策略/docs/CHANGELOG.md](../14-V15经典马丁策略/docs/CHANGELOG.md) | v5.1 |

### 16-调控系统

| 文档 | 路径 | 版本 |
|------|------|------|
| README | [16-调控系统/README.md](../16-调控系统/README.md) | - |
| 工程索引 | [16-调控系统/docs/ENGINEERING_INDEX.md](../16-调控系统/docs/ENGINEERING_INDEX.md) | v2.0 |
| 技术设计 | [16-调控系统/docs/TECHNICAL_DESIGN.md](../16-调控系统/docs/TECHNICAL_DESIGN.md) | v2.0 |
| 接口规格 | [16-调控系统/docs/API_SPEC.md](../16-调控系统/docs/API_SPEC.md) | v2.0 |
| 变更日志 | [16-调控系统/docs/CHANGELOG.md](../16-调控系统/docs/CHANGELOG.md) | v2.0 |

### 17-V4波浪策略系统

| 文档 | 路径 | 版本 |
|------|------|------|
| README | [17-v4-wave-strategy/README.md](../17-v4-wave-strategy/README.md) | v1.0 |
| 工程索引 | [17-v4-wave-strategy/docs/ENGINEERING_INDEX.md](../17-v4-wave-strategy/docs/ENGINEERING_INDEX.md) | v1.0 |
| 技术设计 | [17-v4-wave-strategy/docs/TECHNICAL_DESIGN.md](../17-v4-wave-strategy/docs/TECHNICAL_DESIGN.md) | v1.0 |
| 接口规格 | [17-v4-wave-strategy/docs/API_SPEC.md](../17-v4-wave-strategy/docs/API_SPEC.md) | v1.0 |
| 变更日志 | [17-v4-wave-strategy/docs/CHANGELOG.md](../17-v4-wave-strategy/docs/CHANGELOG.md) | v1.0 |

---

## L3 — 辅助系统与实验性模块

| 模块 | 路径 | 文档状态 | 说明 |
|------|------|----------|------|
| 8-FEISHU 飞书协作 | [8-FEISHU/README.md](../8-FEISHU/README.md) | ✅ README完整 | 人机协作信息层：5群组+2Bot+审批+Bitable+Wiki+Cron |
| 3-EVOLUTION | [3-EVOLUTION/README.md](../3-EVOLUTION/README.md) | 🟡 README v0.2 | TypeScript 进化引擎，实验状态 |
| 6-图结构上下文压缩 | [6-图结构上下文压缩/README.md](../6-图结构上下文压缩/README.md) | 🟡 README v0.2 + 4 非标准文档 | 实验性图结构压缩 |
| 7-产物中台 | [7-产物中台/docs/ENGINEERING_INDEX.md](../7-产物中台/docs/ENGINEERING_INDEX.md) | 🟡 部分（TECHNICAL_DESIGN 已补） | 产物中台与索引体系 |
| 15-监控告警系统 | [15-监控告警系统/docs/ENGINEERING_INDEX.md](../15-监控告警系统/docs/ENGINEERING_INDEX.md) | 🟡 部分（IDX+TD 已补） | 监控告警，待补 API_SPEC/CHANGELOG |
| AGENT协作工具 | [AGENT协作工具/](../AGENT协作工具/) | ⚠️ 仅SKILL.md | 多Agent开发协作辅助（非主线，后期明确接口） |
| deploy/ | [deploy/INDEX.md](../deploy/INDEX.md) | ✅ INDEX.md | 部署配置体系：一键部署+Hermes预部署包+systemd服务 |
| experiments/ | [experiments/](../experiments/) | ❌ 无文档 | AB 交易实验 |
| 1-ARCHITECTURE/dreamos | [1-ARCHITECTURE/dreamos/docs/ENGINEERING_INDEX.md](../1-ARCHITECTURE/dreamos/docs/ENGINEERING_INDEX.md) | ⚠️ 部分完整 | DreamOS CLI |
| **0-系统文档管理/4-工具与自动化** | [4-工具与自动化/README.md](./4-工具与自动化/README.md) | ✅ 已建成 4 脚本 | doc_lint/doc_coverage/index_generator/link_checker |
| **0-系统文档管理/3-文档治理/audits** | [audits/2026-08_月度审计报告.md](./3-文档治理/audits/2026-08_月度审计报告.md) | ✅ 首份报告 | 月度审计报告归档 |

---

## 按主题索引

> 完整主题索引见 [TOPIC_MAP.md](./2-文档地图/TOPIC_MAP.md)

| 主题 | 关键文档 |
|------|---------|
| 风控 | [13-通用风控模块/docs/](../13-通用风控模块/docs/) · [2-KNOWLEDGE/1-TRADING/风控体系.md](../2-KNOWLEDGE/1-TRADING/风控体系.md) |
| 离场决策 | [16-调控系统/docs/](../16-调控系统/docs/) · [10-经典指标系统/classic_exit_system.py](../10-经典指标系统/classic_exit_system.py) · [11-易经推理系统/scripts/memory_l4/yijing_exit_system.py](../11-易经推理系统/scripts/memory_l4/yijing_exit_system.py) |
| BCRM | [11-易经推理系统/docs/TECHNICAL_DESIGN.md](../11-易经推理系统/docs/TECHNICAL_DESIGN.md) |
| 交易策略 | [12-三屏趋势系统/docs/](../12-三屏趋势系统/docs/) · [14-V15经典马丁策略/docs/](../14-V15经典马丁策略/docs/) · [17-v4-wave-strategy/](../17-v4-wave-strategy/) |
| 波浪策略 | [17-v4-wave-strategy/ewave_strategy_adapter.py](../17-v4-wave-strategy/ewave_strategy_adapter.py) · [17-v4-wave-strategy/backtest_results/](../17-v4-wave-strategy/backtest_results/) |
| 人机协作 | [8-FEISHU/README.md](../8-FEISHU/README.md) · [6-TRADING/scripts/feishu_notify.py](../6-TRADING/scripts/feishu_notify.py) |
| 架构设计 | [ARCHITECTURE_MAP.md](./2-文档地图/ARCHITECTURE_MAP.md) v2.0 · [1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md](../1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md) v3.0 |

---

## 文档覆盖率统计

| 层级 | 模块数 | 文档齐全 | 部分完整 | 缺失 | 覆盖率 |
|------|--------|----------|----------|------|--------|
| L2 子系统 | 7 | 7 | 0 | 0 | 100% |
| L3 辅助模块 | 9 | 2 | 6 | 1 | 44% |
| **合计** | **16** | **9** | **6** | **1** | **69%** |

> 统计由 `4-工具与自动化/doc_coverage.py` 生成；L3 较上期（39%→44%）提升，15/7 号补建技术设计文档。完整审计见 [3-文档治理/audits/2026-08_月度审计报告.md](./3-文档治理/audits/2026-08_月度审计报告.md)。

---

**维护说明**: 新增/删除文档时同步更新本索引；由 `4-工具与自动化/doc_coverage.py` + `link_checker.py` 自动校验（已建成）。
