# 0-系统文档管理 — DreamBuddy-V2 工程文档管理中枢

> **版本**: v1.1 | **更新日期**: 2026-07-27
> **定位**: 面向人类开发者的工程文档系统（Single Source of Truth）
> **一句话**: 文档的文档 — 在哪找、怎么写、怎么管
> **核心闭环**: AI 记忆(上下文) → 代码实践 → A8校验 → 更新工程文档(SSoT) → 蒸馏反哺 AI 记忆

---

## 这个目录是什么？

0号系统是 **DreamBuddy-V2 面向人类开发者的工程文档体系**，是全项目的唯一事实来源（SSoT）。

它不替代任何子系统的具体文档（10-经典指标系统、11-易经推理系统等各有自己的 `docs/`），而是回答三个问题：

| 问题 | 对应章节 | 价值 |
|------|---------|------|
| **在哪找？** | [2-文档地图/](./2-文档地图/) | 5 秒内定位任意文档 |
| **怎么写？** | [1-规范体系/](./1-规范体系/) | 统一模板，开箱即用 |
| **怎么管？** | [3-文档治理/](./3-文档治理/) | 生命周期、质量审计、债务跟踪 |

---

## 与 4-MEMORY (AI 记忆系统) 的关系

| 维度 | 0-系统文档管理 (本系统) | 4-MEMORY |
|------|------------------------|----------|
| **面向对象** | 人类开发者 | AI Agent |
| **核心诉求** | 工业级标准、完整性 | 高效性、结构化、动态性 |
| **内容性质** | **理论知识载体** (SSoT) | **AI 上下文索引** (摘要) |
| **维护方式** | 人工维护、代码审查 | AI 自动蒸馏、Consolidation 压缩 |
| **内容体量** | 详细、全量、包含解释 | 极致压缩、一条一行、结构化 |

**关系总结**：本系统（0-系统文档管理）是唯一事实来源（SSoT），AI 记忆系统（4-MEMORY）是其摘要和索引。AI 在进行代码开发前会读取摘要（记忆），开发完成后通过 A8 校验反向更新本系统的文档，随后文档再被蒸馏回 AI 记忆，形成开发闭环。

---

## 目录结构

```
0-系统文档管理/
├── README.md                    # 本文件 — 总入口
├── INDEX.md                     # 全项目文档索引（机器可读目录树）
│
├── 1-规范体系/                   # 怎么写
│   ├── DOC_STANDARD.md          # 文档编写规范（迁移自 PROJECT_DOC_STANDARD.md）
│   ├── DOC_CLASSIFICATION.md    # 文档分类体系（L0-L3 分级 + 角色定义）
│   └── TEMPLATES/               # 文档模板集
│       ├── README_TEMPLATE.md
│       ├── ENGINEERING_INDEX_TEMPLATE.md
│       ├── TECHNICAL_DESIGN_TEMPLATE.md
│       ├── API_SPEC_TEMPLATE.md
│       └── CHANGELOG_TEMPLATE.md
│
├── 2-文档地图/                   # 在哪找
│   ├── SYSTEM_MAP.md            # 全系统文档地图（按系统分）
│   ├── TOPIC_MAP.md             # 主题索引（按主题分，跨系统）
│   └── ARCHITECTURE_MAP.md      # 架构文档地图（顶层架构 + 模块关系）
│
├── 3-文档治理/                   # 怎么管
│   ├── DOC_LIFECYCLE.md         # 文档生命周期（创建→评审→发布→维护→归档）
│   ├── DOC_QUALITY_AUDIT.md     # 文档质量审计标准与流程
│   ├── DOC_DEBT_INDEX.md        # 文档技术债清单（从 DEBT_INDEX.md DOC 类抽离）
│   └── RELEASE_NOTES.md         # 文档体系本身的版本日志
│
└── 4-工具与自动化/               # 自动化工具（占位，后续建设）
    └── README.md
```

---

## 快速导航

### 我要找文档

| 我想了解... | 去哪看 |
|------------|--------|
| 全项目有哪些系统/模块 | [SYSTEM_MAP.md](./2-文档地图/SYSTEM_MAP.md) |
| 某个具体子系统的 API | [SYSTEM_MAP.md](./2-文档地图/SYSTEM_MAP.md) → 对应子系统 → `docs/API_SPEC.md` |
| 项目整体架构 | [ARCHITECTURE_MAP.md](./2-文档地图/ARCHITECTURE_MAP.md) |
| 某个主题（如"风控"/"离场"/"BCRM"） | [TOPIC_MAP.md](./2-文档地图/TOPIC_MAP.md) |
| 技术债清单 | [DEBT_INDEX.md](../DEBT_INDEX.md)（代码债）+ [DOC_DEBT_INDEX.md](./3-文档治理/DOC_DEBT_INDEX.md)（文档债） |

### 我要写文档

| 我要写... | 用什么模板 | 看什么规范 |
|----------|-----------|-----------|
| 新子系统的 README | [README_TEMPLATE.md](./1-规范体系/TEMPLATES/README_TEMPLATE.md) | [DOC_STANDARD.md](./1-规范体系/DOC_STANDARD.md) §3.4 |
| 工程索引 | [ENGINEERING_INDEX_TEMPLATE.md](./1-规范体系/TEMPLATES/ENGINEERING_INDEX_TEMPLATE.md) | [DOC_STANDARD.md](./1-规范体系/DOC_STANDARD.md) §3.1 |
| 技术设计文档 | [TECHNICAL_DESIGN_TEMPLATE.md](./1-规范体系/TEMPLATES/TECHNICAL_DESIGN_TEMPLATE.md) | [DOC_STANDARD.md](./1-规范体系/DOC_STANDARD.md) §3.2 |
| 接口规格 | [API_SPEC_TEMPLATE.md](./1-规范体系/TEMPLATES/API_SPEC_TEMPLATE.md) | [DOC_STANDARD.md](./1-规范体系/DOC_STANDARD.md) §3.3 |
| 变更日志 | [CHANGELOG_TEMPLATE.md](./1-规范体系/TEMPLATES/CHANGELOG_TEMPLATE.md) | [DOC_STANDARD.md](./1-规范体系/DOC_STANDARD.md) §3.5 |

### 我要管文档

| 我要... | 去哪看 |
|--------|--------|
| 了解文档生命周期 | [DOC_LIFECYCLE.md](./3-文档治理/DOC_LIFECYCLE.md) |
| 审计文档质量 | [DOC_QUALITY_AUDIT.md](./3-文档治理/DOC_QUALITY_AUDIT.md) |
| 查看文档技术债 | [DOC_DEBT_INDEX.md](./3-文档治理/DOC_DEBT_INDEX.md) |
| 了解文档体系变更 | [RELEASE_NOTES.md](./3-文档治理/RELEASE_NOTES.md) |

---

## 与现有文档体系的关系

| 现有文档 | 关系 | 说明 |
|---------|------|------|
| [PROJECT_DOC_STANDARD.md](../PROJECT_DOC_STANDARD.md) | **迁移源** | 内容已迁移到 [1-规范体系/DOC_STANDARD.md](./1-规范体系/DOC_STANDARD.md)，根目录保留重定向链接 |
| [DEBT_INDEX.md](../DEBT_INDEX.md) | **分工** | DEBT_INDEX 管代码债，DOC 类债务细化到 [3-文档治理/DOC_DEBT_INDEX.md](./3-文档治理/DOC_DEBT_INDEX.md) |
| [2-KNOWLEDGE/](../2-KNOWLEDGE/) | **互补** | 2-KNOWLEDGE 管交易/技术/理论领域知识，0号系统管文档本身 |
| [1-ARCHITECTURE/](../1-ARCHITECTURE/) | **引用** | 0号系统在 [ARCHITECTURE_MAP.md](./2-文档地图/ARCHITECTURE_MAP.md) 中索引架构文档 |
| 各子系统 `docs/` | **不变** | 0号系统提供导航指向，不替代子系统文档 |

---

## 设计原则

1. **元层不越权** — 0号系统只管"文档怎么管"，不管架构设计本身
2. **索引可自动化** — INDEX.md 结构化，后续可用脚本生成与校验
3. **模板优先** — 新增文档必须从模板开始，避免风格漂移
4. **单一入口** — 全项目文档只有一个总入口：本 README
5. **与代码同步** — 文档变更与代码变更在同一个 PR 中完成

---

## 文档版本

- **v1.0** (2026-07-25): 0号系统建立，迁移 PROJECT_DOC_STANDARD，建立文档地图与治理体系

---

**维护者**: DreamBuddy v2
**关联文档**: [PROJECT_DOC_STANDARD.md](../PROJECT_DOC_STANDARD.md) · [DEBT_INDEX.md](../DEBT_INDEX.md) · [README.md](../README.md)
