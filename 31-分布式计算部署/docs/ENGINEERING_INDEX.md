# 分布式计算部署 — 工程索引

> **版本**：v1.0 | **更新日期**：2026-10-14
> **模块定位**：线上线下协同部署编排层（三层异构协同：认知聚合 / 竞赛择优 / 协作训练）

## 1. 模块概览

分布式协同部署方案：云端常驻实时交易+前端入口，线下承担训练/优化等重计算，通过任务队列+心跳实现协同与故障降级。

## 2. 目录结构

```
31-分布式计算部署/
├── docs/
│   ├── SPEC-分布式计算协同部署方案.md   # 核心设计 SPEC
│   ├── ENGINEERING_INDEX.md            # 本文件
│   ├── TECHNICAL_DESIGN.md            # 技术设计
│   ├── API_SPEC.md                     # 接口规格
│   ├── CHANGELOG.md                    # 变更日志
│   ├── DEPLOYMENT_CHECKLIST.md         # 部署检查清单
│   └── README.md                       # 文档索引
├── phase1/                             # 云端核心上线脚本
├── phase2/                             # 协同增强脚本
└── README.md                           # 模块入口
```

## 3. 设计文档

| 文档 | 说明 |
|------|------|
| [SPEC-分布式计算协同部署方案.md](./SPEC-分布式计算协同部署方案.md) | 完整架构设计（模块分工、通信机制、降级策略、成本、实施路线） |
| [SPEC-本地远端双写分叉治理与torch可用性.md](./SPEC-本地远端双写分叉治理与torch可用性.md) | 认知库多节点聚合 + torch 部署决策 |
| [RESEARCH-分布式计算核心逻辑-三层异构协同.md](./RESEARCH-分布式计算核心逻辑-三层异构协同.md) | 三层架构深度调研（评分 8.9/10） |
| [STATUS-已实现待实现清单.md](./STATUS-已实现待实现清单.md) | **完整清单：已实现 / 待实现 / 依赖关系 / 实施顺序** |
| [TECHNICAL_DESIGN.md](./TECHNICAL_DESIGN.md) | 技术设计（架构、部署分阶段、关键决策、降级策略） |
| [API_SPEC.md](./API_SPEC.md) | 接口规格（部署脚本、服务端口、健康检查、环境变量） |
| [DEPLOYMENT_CHECKLIST.md](./DEPLOYMENT_CHECKLIST.md) | 部署检查清单 |
| [PLAN-本地远端双写分叉治理与torch可用性.md](./PLAN-本地远端双写分叉治理与torch可用性.md) | 实施计划（TDD） |
| [CHANGELOG.md](./CHANGELOG.md) | 变更日志 |

## 4. 核心组件（规划中）

| 组件 | 职责 | 实现状态 |
|------|------|---------|
| Scheduler | 任务分发、Worker 管理、能力路由 | 待实现 |
| HeartbeatMonitor | 线下节点健康检测 | 待实现 |
| Degrader | 故障降级切换 | 待实现 |
| FallbackLib | 各子系统降级算法 | 待实现 |
| WorkerAgent | 线下任务执行代理 | 待实现 |

## 5. 关联子系统

| 子系统 | 云端部分 | 线下部分 |
|--------|---------|---------|
| V15 马丁策略 | 实时盯盘 | — |
| 事件驱动策略 | 实时事件检测 | — |
| BCRM2.0 | 推理 | 训练/优化 |
| BDSM | 快照 | 全量扫描 |
| 战略层 | 风控执行 | 参数优化 |
| 自进化系统 | 推理 | 训练/回测 |

## 6. 实施进度

| 阶段 | 内容 | 状态 |
|------|------|------|
| Phase 1 | 云端核心上线 | ✅ 已完成 |
| Phase 2 | 协同增强（易经/产物中台/M25-M28） | ✅ 已完成 |
| Phase 3 | 数据管道（18采集/19回填/DAL维护） | ✅ 已完成 |
| Phase 4 | 认知守护 + DreamOS 编排 | ✅ 已完成 |
| Phase 6 | 冗余单元（yijing-monitor/ranking-trigger） | ✅ 已完成 |
| Phase 7 | torch + 认知库多节点聚合 v2 | ✅ 已完成 |
| Phase 2' | 任务队列+线下Worker | ⏳ 待启动 |
| Phase 3' | 降级接管（Degrader/FallbackLib） | ⏳ 待启动 |
| Phase 4' | 多线下机器支持 | ⏳ 待启动 |
| **三层-N1** | 认知分层共享（scope） | ⏳ P0 待启动 |
| **三层-N3** | CompetitionOrchestrator 竞赛框架 | ⏳ P0 待启动 |
| **三层-N8** | 前端协作训练（权重 delta） | ⏳ P1 待启动 |

> 完整清单见 [STATUS-已实现待实现清单.md](./STATUS-已实现待实现清单.md)
