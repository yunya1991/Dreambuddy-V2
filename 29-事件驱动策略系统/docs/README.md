# 文档索引

> **版本**：v1.0 | **更新日期**：2026-10-04（迁移独立化，对齐 DOC_STANDARD L3 五文档标准）

## 标准五件套（SSoT，对齐 DOC_STANDARD L3）

| 文档 | 版本 | 说明 |
|------|------|------|
| [README.md](./README.md) | - | 文档索引（本文件） |
| [ENGINEERING_INDEX.md](./ENGINEERING_INDEX.md) | v1.0 | 模块工程索引 |
| [TECHNICAL_DESIGN.md](./TECHNICAL_DESIGN.md) | v1.0 | 模块技术设计 |
| [API_SPEC.md](./API_SPEC.md) | v1.0 | 模块接口规格 |
| [CHANGELOG.md](./CHANGELOG.md) | v1.0 | 模块变更记录 |

## 模块定位

事件驱动策略子交易系统 — 独立子交易系统（与 BCRM2.0、BDSM 平级），专注离散单点宏观事件的冲击响应。

### 核心组件

| 组件 | 职责 |
|------|------|
| EventDrivenStrategy | 5 维评分策略引擎 |
| EventDrivenTrader | 独立子交易系统执行器 |
| ConvictionScorer | 6 因子置信度评分 |
| EventDominanceController | 宏观事件主导控制器 |
| EventCaseLibrary | FOMC 事件案例库 |

## 关联 SPEC

- [SPEC-事件驱动策略独立化-共享事件层与弹性约束.md](../../23-四层闭环自进化交易架构/SPEC-事件驱动策略独立化-共享事件层与弹性约束.md) v1.2
- [SPEC-事件驱动策略P0盲区修复-非农CPI加息预期.md](../../23-四层闭环自进化交易架构/SPEC-事件驱动策略P0盲区修复-非农CPI加息预期.md) v1.0
- [SPEC-美国宏观事件驱动交易策略.md](../../23-四层闭环自进化交易架构/SPEC-美国宏观事件驱动交易策略.md)
