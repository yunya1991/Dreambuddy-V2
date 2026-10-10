# 图结构上下文压缩 — 工程索引

> **版本**：v1.0 | **更新日期**：2026-10-11
> **模块定位**：基于图结构的上下文压缩引擎（TypeScript）

## 1. 模块概览

图结构上下文压缩系统将复杂的决策上下文建模为有向图，通过增量压缩、语义压缩、分片压缩等策略，在保持语义完整性的前提下降低上下文体积，支持 HITL（人在回路）交互与可视化。

## 2. 目录结构

```
6-图结构上下文压缩/
├── docs/
│   └── ENGINEERING_INDEX.md       # 本文件
├── README.md                      # 模块入口
├── SPEC.md                        # 需求规格
├── IMPLEMENTATION.md              # 实现说明
├── TECHNICAL-DOC.md               # 技术文档
├── THEORY-AND-PRACTICE.md         # 理论与实践
├── index.ts                       # 模块入口
├── compressor.ts                  # 压缩器基类
├── incremental-compressor.ts      # 增量压缩
├── semantic-compressor.ts         # 语义压缩
├── sharded-compressor.ts          # 分片压缩
├── graph-state.ts                 # 图状态管理
├── graph-executor.ts              # 图执行器
├── graph-parallel.ts              # 并行执行
├── graph-hitl.ts                  # 人在回路交互
├── graph-checkpointer.ts          # 检查点
├── intent-gateway.ts              # 意图网关
├── blueprint.ts / blueprint-registry.ts  # 蓝图系统
├── contract.ts                    # 契约定义
├── architecture.ts                # 架构定义
├── chronicle.ts                   # 编年史
├── visualization.ts               # 可视化
├── types.ts / models.ts           # 类型与模型
├── planner/                       # 规划器
├── demo/                          # 演示
└── skills/                        # 相关 SKILL
```

## 3. 设计文档

| 文档 | 说明 |
|------|------|
| [README.md](../README.md) | 模块入口与快速开始 |
| [SPEC.md](../SPEC.md) | 需求规格 |
| [IMPLEMENTATION.md](../IMPLEMENTATION.md) | 实现说明 |
| [TECHNICAL-DOC.md](../TECHNICAL-DOC.md) | 技术文档 |
| [THEORY-AND-PRACTICE.md](../THEORY-AND-PRACTICE.md) | 理论与实践 |

## 4. 核心组件

| 组件 | 文件 | 职责 |
|------|------|------|
| 压缩器基类 | compressor.ts | 压缩策略抽象 |
| 增量压缩 | incremental-compressor.ts | 增量式上下文压缩 |
| 语义压缩 | semantic-compressor.ts | 语义级压缩 |
| 分片压缩 | sharded-compressor.ts | 分片并行压缩 |
| 图状态 | graph-state.ts | 图节点/边状态管理 |
| 图执行器 | graph-executor.ts | 图执行调度 |
| HITL | graph-hitl.ts | 人在回路交互 |
| 意图网关 | intent-gateway.ts | 意图路由 |
| 蓝图系统 | blueprint.ts | 可复用决策蓝图 |

## 5. 测试

- graph-state.test.ts
- graph-parallel.test.ts
- graph-integration.test.ts
- graph-hitl.test.ts
- graph-hitl-integration.test.ts
- graph-parallel-integration.test.ts
