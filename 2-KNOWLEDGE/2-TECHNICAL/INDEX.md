# 2-TECHNICAL — 技术运维知识

> 技术域知识库：Hermes Agent 体系架构、Cron 调度、飞书集成、部署维护。
> L3 领域知识层 — 上层：[0-SCHEMA/](../0-SCHEMA/) |
> 同层：其他L3域 [1-TRADING/](../1-TRADING/)、[3-THEORY/](../3-THEORY/)、[4-OPERATIONS/](../4-OPERATIONS/) → 下层：[5-METHODOLOGY/](../5-METHODOLOGY/)
> 源：`~/.hermes/skills/` 及项目 runtime 经验沉淀。

## 文件列表

| 文件 | 说明 | 来源 Skill / 组件 |
|:---|---|:---:|
| [Hermes-架构](./Hermes-架构.md) | Hermes Agent 核心架构：Gateway、Cron、Skill、Plugin | hermes-core, a-series-intraday-architecture |
| [Cron-调度](./Cron-调度.md) | A 系列 cron 任务链、Guard 机制、execution_loop 状态机 | hermes-cron-maintenance, a-series-intraday-architecture |
| [飞书集成指南](./飞书集成指南.md) | lark-cli 用法、Base/OKR/审批/文档/IM 调用与陷阱 | feishu-integration, feishu-orchestrator, lark-shared |
| [部署与维护](./部署与维护.md) | 腾讯云部署、GitHub 同步、环境变量、系统维护 | 运维实践沉淀 |
| [A系列SILENT产出诊断](./A系列SILENT产出诊断.md) | A4/A5 零字节根因分析与修复方向 | 2026-06-15 架构升级验证 |
| [数据管道](./数据管道.md) | 数据源清单/ETL流程/新鲜度标准/降级策略 | 数据管道体系 |

## 关联域

- **1-TRADING/**：交易业务知识（三屏、马丁、风控）
- **4-OPERATIONS/**：运营治理（审批、OKR、索引体系）

## 建设原则

1. 每个文件独立解决一个技术概念，可单独引用
2. 只保留架构模式、命令参考、坑点陷阱，不复制运行时原始数据
3. 末尾注明 `最后更新：YYYY-MM-DD`
4. Skills 为权威源，KB 做跨域蒸馏和补充编排

最后更新：2026-06-15 | 总文件数：7（含INDEX）
