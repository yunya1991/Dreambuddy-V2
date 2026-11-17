# 文档索引

> **更新日期**：2026-11-17（新增交易主链 SSoT：分层框架/三类信号/开平仓数据流）
> **模块定位**：四层闭环自进化交易架构 — 观察→推断→实验→反思→回馈自进化策略引擎

## 标准五件套（SSoT，对齐 DOC_STANDARD L3）

| 文档 | 说明 |
|------|------|
| [README.md](./README.md) | 文档索引（本文件） |
| [ENGINEERING_INDEX.md](./ENGINEERING_INDEX.md) | 模块工程索引（文件级，含 N0–N15 / E0–E6 代码映射） |
| [TECHNICAL_DESIGN.md](./TECHNICAL_DESIGN.md) | 模块技术设计（**仅基因三层准入**） |
| [API_SPEC.md](./API_SPEC.md) | 模块接口规格（v1.2：新增 trace_id/path_info/v1.2 契约） |
| [CHANGELOG.md](./CHANGELOG.md) | 模块变更记录（v1.16 基因创新治理：版本控制+三级审核门禁） |

## 交易主链 SSoT

| 文档 | 说明 |
|------|------|
| [TRADING_FRAMEWORK_AND_SIGNAL_FLOW.md](./TRADING_FRAMEWORK_AND_SIGNAL_FLOW.md) | 分层交易框架、三类信号、开/平仓数据流、关联键与产物；监控口径引用 15 TD §13 |

## 专题文档

| 文档 | 说明 |
|------|------|
| [neural_sde_design.md](./neural_sde_design.md) | NeuralSDE 路径依赖 SDE 设计（v1.0, 生产最优 MAE=269.51, 优于 GARCH 3.3x） |
| [entry_bcrm_soft_weight_design.md](./entry_bcrm_soft_weight_design.md) | BCRM 软权重入场设计 |
| [三维度矛盾论理论框架.md](./三维度矛盾论理论框架.md) | 矛盾论 v3.0 理论升级指南（被 6 个 core/*.py 引用） |
| [矛盾Transformer架构.md](./矛盾Transformer架构.md) | 矛盾 Transformer 与交叉验证门禁架构 |
| [矛盾论与Transformer架构融合方案.md](./矛盾论与Transformer架构融合方案.md) | 双链路融合方案 |
| [SPEC-23离场平仓逐项调查与验证-20261114.md](./SPEC-23离场平仓逐项调查与验证-20261114.md) | 离场/平仓算法调查、回测与实盘验证 |
| [REVIEW-23离场平仓算法梳理与评估-20261114.md](./REVIEW-23离场平仓算法梳理与评估-20261114.md) | 离场/平仓算法评审 |

## 子目录

- [audit_reports/](./audit_reports/) — 审计报告归档（20 份，Sep 12-16：audit/data_quality/model_validation/risk/sre 5 类）

## 根层 SPEC 文档（8 份，4 Active + 4 Hold）

> 详细路径与状态见 [ENGINEERING_INDEX.md §8 快速导航](./ENGINEERING_INDEX.md#8-快速导航)

| SPEC | 状态 | 说明 |
|------|------|------|
| [SPEC-AGI升级蓝图.md](../SPEC-AGI升级蓝图.md) | Active | AGI 5 Phase 升级蓝图 |
| [SPEC-数据管线打通与能力落地.md](../SPEC-数据管线打通与能力落地.md) | Active | 数据管线 SPEC |
| [SPEC-金融思维链层FTC设计.md](../SPEC-金融思维链层FTC设计.md) | Active | FTC 设计 SPEC |
| [SPEC-趋势跟踪正金字塔与网格策略落地.md](../SPEC-趋势跟踪正金字塔与网格策略落地.md) | Active | 趋势跟踪+网格 SPEC |
| [SPEC-主要矛盾识别与最小阻力路径设计.md](../SPEC-主要矛盾识别与最小阻力路径设计.md) | **Hold** | 待评审 v1（被 test_primary_contradiction_detector 引用） |
| [SPEC-矛盾论实现断裂修复与阻力场升级.md](../SPEC-矛盾论实现断裂修复与阻力场升级.md) | **Hold** | 待评审 v1（被 test_resistance_field_upgrade 引用） |
| [SPEC-美国宏观事件驱动交易策略.md](../SPEC-美国宏观事件驱动交易策略.md) | **Hold** | v2.0 已纳入深度调研（策略默认关闭） |
| [SPEC-非线性多阶段最优路径理论调研框架.md](../SPEC-非线性多阶段最优路径理论调研框架.md) | **Hold** | 理论调研 v0.5（被 6 个 core/*.py 引用） |
| [SPEC-ds4架构借鉴与系统增强.md](../SPEC-ds4架构借鉴与系统增强.md) | **Spec（待评审）** | ds4 推理引擎七大架构维度借鉴与系统增强（v1.0，2026-10-04） |

> **Hold 保护**：4 份 SPEC 为未闭环调研/待评审 SPEC，按 dream-scattered-file-cleanup skill Step 2 状态机 Hold 保护规则，cleanup 跳过。

---

**文档版本**：v1.3
**最后更新**：2026-11-17
