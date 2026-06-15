# 🏛️ Dream-MultiSkill v2 架构归档
> **原始仓库**: yunya1991/dream-multiskill-v2
> **归档日期**: 2026-06-13
> **状态**: 已蒸馏→6-TRADING/knowledge/ 知识库 + 本索引
> **原始仓库已删除**，以下为不可丢失的逻辑闭环

---

## 五层架构

| 层 | 目录 | 核心职能 | 文档 |
|:---|:---|:---|:---:|
| **0-CORE** | 宪法+知识+记忆+治理 | 系统最高指导、元知识管理 | [📄](00-CORE-宪法与治理.md) |
| **1-TRADE** | A0-A9 交易决策链 | 交易主链路：调研→分析→策略→验证→执行→监控→审计 | [📄](01-TRADE-交易决策链.md) |
| **2-INTEL** | 分析+研究+数据 | 情报分析、大师研讨、数据加工 | [📄](02-INTEL-情报分析体系.md) |
| **3-SUPPORT** | 运营+合规+成本 | 秘书服务、运营管理、绩效审查 | [📄](03-SUPPORT-运营支持体系.md) |
| **4-GENERIC** | 通用工具 | 搜索(Tavily)、GitHub、Skill创建 | [📄](04-GENERIC-通用工具.md) |

## 工作流 & 约束

| 模块 | 内容 | 文档 |
|:---|:---|:---:|
| **WORKFLOWS** | 交易决策/记忆层/进化/知识 | [📄](WORKFLOWS-工作流.md) |
| **CONSTRAINTS** | QMM/宪法/系统索引/规范 | [📄](CONSTRAINTS-约束层.md) |

---

## 调用指南

### 路径1：决策时直接引用
```
需要哲学依据      → 00-CORE-宪法与治理.md   §1.x
需要交易决策流程   → 01-TRADE-交易决策链.md  §A.x
需要大师参考       → 6-TRADING/knowledge/master_profiles/INDEX.md
需要Regime判断     → 6-TRADING/knowledge/regime_patterns/regime_definitions.md
需要风险/评分      → 6-TRADING/knowledge/strategy_scores/scoring_system.md
```

### 路径2：遵循治理meta-chain
```
元认知指令 → 加载 governance-meta-chain
            → 读取本归档中对应层的文档
            → 结合 6-TRADING/knowledge/ 实际数据
            → 执行分析/决策
```

### 路径3：Skill加载
部分核心逻辑已作为 Hermes Skill 存在：
- `dream-contradiction-theory` — A0矛盾分析
- `dream-exit-skill-v2` — A9离场决策
- `dream-intelligence-monitor` — A6情报监控
- `dream-first-principles` — A2第一性原理
- `dream-knowledge` — 知识检索框架
- `master-seminar` — 大师研讨
- `governance-meta-chain` — 元认知治理

> 缺失的SKILL（如 A1/A3/A4/A5/A7/A8）可直接参考本归档的 `1-TRADE` 文档中的逻辑结构，用 Hermes 原生 skill 实现。

---

## 与已有架构的关系

```
Dreambuddy-V2/
├── 1-ARCHITECTURE/
│   ├── dream-multiskill-v2/    ← 本归档 (dream系统逻辑闭环)
│   ├── FAQ/                    原有FAQ
│   ├── 中台设计/              原有中台设计
│   ├── 前端设计/              原有前端设计
│   └── 工作索引/              原有工作索引
├── 6-TRADING/
│   ├── knowledge/              ← 实际数据层 (大师/Regime/评分)
│   ├── skills/                 ← 集成后的Hermes skill
│   └── scripts/                ← 自动化脚本
└── ...
```
