# 架构设计

> **版本**: v3.0 | **更新日期**: 2026-07-31
> **定位**: 1-ARCHITECTURE 目录入口，指向架构唯一事实源（SSoT）
> **架构 SSoT**: ★ [SYSTEM_ARCHITECTURE_OVERVIEW.md](./SYSTEM_ARCHITECTURE_OVERVIEW.md) v3.0 — 所有架构争议以此为准

---

## 架构唯一事实源（SSoT）

**所有架构设计、硬约束、模块边界、技术债全景以 [SYSTEM_ARCHITECTURE_OVERVIEW.md](./SYSTEM_ARCHITECTURE_OVERVIEW.md) v3.0 为准。**

SSoT v3.0 覆盖 12 章：

- 三层架构（OS内核 + 能力层 + 应用层）
- 三大思维链 + 三大核心闭环 + A0 矛盾论
- 认知系统 + 记忆进化（开发闭环 ↔ 交易闭环对称）
- 公司中枢（六部门 + 双中台 + 双交易流 + 四层合规）
- 硬约束清单（违反即 bug）+ 技术债 103 项全景

> ⚠️ 本 README 不再重复架构内容。如需了解架构，直接阅读 SSoT。

---

## 本目录文档索引

### 架构总览

| 文档 | 路径 | 状态 |
|------|------|------|
| ★ SSoT 架构总览 v3.0 | [SYSTEM_ARCHITECTURE_OVERVIEW.md](./SYSTEM_ARCHITECTURE_OVERVIEW.md) | ✅ 草稿待评审 |
| 交易模块总览 | [TRADING_MODULES_OVERVIEW.md](./TRADING_MODULES_OVERVIEW.md) | 🟡 与 v3.0 对齐 |
| 三链调度清单 | [THREE_CHAIN_DISPATCH_CHECKLIST.md](./THREE_CHAIN_DISPATCH_CHECKLIST.md) | 🟡 与 v3.0 对齐 |
| 超能力集成 | [SUPERPOWERS_INTEGRATION_UPGRADE.md](./SUPERPOWERS_INTEGRATION_UPGRADE.md) | 🟡 参考 |
| 旧模块化架构（归档） | [WORKBUDDY_OS_MODULAR_ARCHITECTURE.md](./WORKBUDDY_OS_MODULAR_ARCHITECTURE.md) | 📦 归档参考，决策以 v3.0 为准 |

### 子目录

| 子目录 | 内容 | 入口 |
|--------|------|------|
| 中台设计/ | 产物中台、网关中台、公司中枢 | [README.md](./中台设计/README.md) |
| 前端设计/ | 前端架构、UI 规范 | [README.md](./前端设计/README.md) |
| 工作索引/ | SKILL 索引、部门矩阵、工具映射 | [README.md](./工作索引/README.md) |
| FAQ/ | 常见问题 | [README.md](./FAQ/README.md) |
| dreamos/ | DreamOS CLI | [docs/ENGINEERING_INDEX.md](./dreamos/docs/ENGINEERING_INDEX.md) |

---

## 子系统架构文档

7 个交易子系统（10/11/12/13/14/16/17）的技术设计文档见 [0-系统文档管理/2-文档地图/SYSTEM_MAP.md](../0-系统文档管理/2-文档地图/SYSTEM_MAP.md) §L2。

---

## 快速导航

| 需求 | 去哪看 |
|------|--------|
| 了解整体架构 | [SSoT v3.0](./SYSTEM_ARCHITECTURE_OVERVIEW.md) |
| 找某个文档 | [文档地图 SYSTEM_MAP](../0-系统文档管理/2-文档地图/SYSTEM_MAP.md) |
| 找某个主题 | [主题地图 TOPIC_MAP](../0-系统文档管理/2-文档地图/TOPIC_MAP.md) |
| 架构文档地图 | [ARCHITECTURE_MAP](../0-系统文档管理/2-文档地图/ARCHITECTURE_MAP.md) |
| 技术债清单 | [DEBT_INDEX.md](../DEBT_INDEX.md) |

---

**文档版本**: v3.0
**最后更新**: 2026-07-31
**关联**: [SSoT](./SYSTEM_ARCHITECTURE_OVERVIEW.md) · [0-系统文档管理](../0-系统文档管理/)
