# 文档索引

> **更新日期**：2026-10-01（补建 README，对齐 DOC_STANDARD L3 五文档标准）
> **模块定位**：数据访问层 — Dreambuddy 统一数据访问抽象（DAL），支持 JSON Legacy / SQLite / PostgreSQL 多后端

## 标准五件套（SSoT，对齐 DOC_STANDARD L3）

| 文档 | 说明 |
|------|------|
| [README.md](./README.md) | 文档索引（本文件） |
| [ENGINEERING_INDEX.md](./ENGINEERING_INDEX.md) | 模块工程索引 |
| [TECHNICAL_DESIGN.md](./TECHNICAL_DESIGN.md) | 模块技术设计 |
| [API_SPEC.md](./API_SPEC.md) | 模块接口规格 |
| [CHANGELOG.md](./CHANGELOG.md) | 模块变更记录 |

## 专题文档

| 文档 | 说明 | 状态 |
|------|------|------|
| [SCHEMA_DESIGN.md](./SCHEMA_DESIGN.md) | 数据库 Schema 设计 | Active |
| [MIGRATION_PLAN.md](./MIGRATION_PLAN.md) | 迁移执行计划 SOP（P0-P3 已完成，P4 待触发） | **Hold**（未闭环） |

## 核心目录

- `dreambuddy_dal/` — DAL 核心实现（protocols + implementations + migrations）
- `tests/` — 测试套件
- `launchd/` — Cron 三件套（backup / integrity / rotate）
