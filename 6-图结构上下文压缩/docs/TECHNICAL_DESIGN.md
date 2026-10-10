# 图结构上下文压缩 — 技术设计

> **版本**：v1.0 | **更新日期**：2026-10-11
> **完整技术文档**：见根目录 [TECHNICAL-DOC.md](../TECHNICAL-DOC.md)

## 1. 架构概述

图结构上下文压缩系统将决策上下文建模为有向图，通过多种压缩策略在保持语义完整性的前提下降低体积。

## 2. 核心模块

| 模块 | 文件 | 职责 |
|------|------|------|
| 压缩器基类 | [compressor.ts](../compressor.ts) | 压缩策略抽象接口 |
| 增量压缩 | [incremental-compressor.ts](../incremental-compressor.ts) | 增量式上下文压缩 |
| 语义压缩 | [semantic-compressor.ts](../semantic-compressor.ts) | 语义级压缩 |
| 分片压缩 | [sharded-compressor.ts](../sharded-compressor.ts) | 分片并行压缩 |
| 图状态 | [graph-state.ts](../graph-state.ts) | 图节点/边状态管理 |
| 图执行器 | [graph-executor.ts](../graph-executor.ts) | 图执行调度 |
| 并行执行 | [graph-parallel.ts](../graph-parallel.ts) | 并行图执行 |
| HITL | [graph-hitl.ts](../graph-hitl.ts) | 人在回路交互 |
| 意图网关 | [intent-gateway.ts](../intent-gateway.ts) | 意图路由 |
| 蓝图系统 | [blueprint.ts](../blueprint.ts) | 可复用决策蓝图 |

## 3. 详细设计

完整技术设计、数据结构、算法流程见 [TECHNICAL-DOC.md](../TECHNICAL-DOC.md)，理论基础见 [THEORY-AND-PRACTICE.md](../THEORY-AND-PRACTICE.md)，实现细节见 [IMPLEMENTATION.md](../IMPLEMENTATION.md)。
