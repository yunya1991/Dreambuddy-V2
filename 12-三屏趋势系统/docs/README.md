# 文档索引

> **更新日期**：2026-10-01（补建 README，对齐 DOC_STANDARD L3 五文档标准）
> **主线策略**：V4 + 波浪互斥融合 — BTC 年化 56.43%，夏普 1.41，回撤 -43.31%

## 标准五件套（SSoT，对齐 DOC_STANDARD L3）

| 文档 | 版本 | 说明 |
|------|------|------|
| [README.md](./README.md) | - | 文档索引（本文件） |
| [ENGINEERING_INDEX.md](./ENGINEERING_INDEX.md) | v4.0.0 | 模块工程索引（1045 行） |
| [TECHNICAL_DESIGN.md](./TECHNICAL_DESIGN.md) | v4.0 | 模块技术设计（2006 行） |
| [API_SPEC.md](./API_SPEC.md) | v4.0.0 | 模块接口规格（1220 行） |
| [CHANGELOG.md](./CHANGELOG.md) | v4.0.0 | 模块变更记录（419 行） |

## 专题文档

| 文档 | 版本 | 说明 |
|------|------|------|
| [PITD_PHYSICS_ALGORITHM_DESIGN.md](./PITD_PHYSICS_ALGORITHM_DESIGN.md) | v1.0 | PITD 物理数学趋势推理算法详细设计（母文档：TECHNICAL_DESIGN §9） |
| [PITD_PHYSICS_APPLICATION_FRAMEWORK.md](./PITD_PHYSICS_APPLICATION_FRAMEWORK.md) | v1.0 | PITD 物理引擎应用框架（9 年 BTC/ETH 回测验证） |
| [STRATEGY_LINES.md](./STRATEGY_LINES.md) | v1.0 | 策略线管理总纲（主副线物理隔离） |
| [trend-screen-system-design.md](./trend-screen-system-design.md) | v2.0 | **历史参考**：早期设计文档，已被 TECHNICAL_DESIGN.md v4.0 替代 |

## 子目录

- [reports/](./reports/) — A8 反思报告与外部参考（a8_self_criticism_report_20260713.md + github_mature_solutions_reference.md）

## 系统边界

| 职责 | 归属 |
|------|------|
| 趋势方向判定 + 置信度评估 + 仓位计算 | **12-三屏趋势系统**（本模块） |
| 入场信号精选（Freqtrade 多策略投票） | 10-经典指标系统 |
| 离场决策（ClassicExitSystem 四层优先级） | 10-经典指标系统 |
| 基本面数据 | A 系列研报 |
