# 文档索引

> **更新日期**：2026-10-01（补建 README，对齐 DOC_STANDARD L3 五文档标准）
> **模块定位**：图结构上下文压缩 — SACG（Sense/Aware/Compute/Grow）四层内核中 C 层（Compute 计算层）核心功能

## 标准五件套（SSoT，对齐 DOC_STANDARD L3）

| 文档 | 说明 |
|------|------|
| [README.md](./README.md) | 文档索引（本文件） |
| [ENGINEERING_INDEX.md](./ENGINEERING_INDEX.md) | 模块工程索引 |
| [TECHNICAL_DESIGN.md](./TECHNICAL_DESIGN.md) | 模块技术设计 |
| [API_SPEC.md](./API_SPEC.md) | 模块接口规格 |
| [CHANGELOG.md](./CHANGELOG.md) | 模块变更记录 |

## 归档文档（历史参考）

- [SPEC.md](./archive/SPEC.md) — 双维度编排架构规范 v1.0（2026-06-21，已被 TECHNICAL_DESIGN.md 替代）
- [IMPLEMENTATION.md](./archive/IMPLEMENTATION.md) — 实施计划 v1.0（2026-06-21，已消费）
- [TECHNICAL-DOC.md](./archive/TECHNICAL-DOC.md) — 图文笔记压缩模型（2026-06-27，早期技术文档）
- [THEORY-AND-PRACTICE.md](./archive/THEORY-AND-PRACTICE.md) — 理论与实践调研（2026-06-27，早期调研文档）

## 核心目录

- 根层 `*.ts` — SACG C 层核心实现（graph-state/executor/parallel/hitl/checkpointer/compressor/intent-gateway）
- `planner/` — 规划器实现
- `demo/` — Demo 脚本（含会话 demo 归档）
- `skills/` — 相关 SKILL
