# 文档索引

> **更新日期**：2026-10-01（补建 README，对齐 DOC_STANDARD L3 五文档标准）
> **模块定位**：V15 经典马丁策略（标杆）— 承载 V9 红线基线的马丁网格策略

## 标准五件套（SSoT，对齐 DOC_STANDARD L3）

| 文档 | 版本 | 说明 |
|------|------|------|
| [README.md](./README.md) | - | 文档索引（本文件） |
| [ENGINEERING_INDEX.md](./ENGINEERING_INDEX.md) | v5.1 | 模块工程索引 |
| [TECHNICAL_DESIGN.md](./TECHNICAL_DESIGN.md) | v5.1 | 模块技术设计 |
| [API_SPEC.md](./API_SPEC.md) | v3.1 | 模块接口规格 |
| [CHANGELOG.md](./CHANGELOG.md) | v5.1 | 模块变更记录 |

## 专题文档

| 文档 | 说明 |
|------|------|
| [AI_ENHANCEMENT_ROADMAP.md](./AI_ENHANCEMENT_ROADMAP.md) | AI 增强路线图 |
| [CONFIGURATION_GUIDE.md](./CONFIGURATION_GUIDE.md) | 配置指南 |
| [dual_baseline_ab_framework.md](./dual_baseline_ab_framework.md) | 双基线 AB 框架 |

## 子目录

- [a8_analysis/](./a8_analysis/) — A8 分析报告
- [superpowers/](./superpowers/) — 能力规格文档

## 架构要点

- **V9 红线基线**（不可变）：TP 4%×vol_mult / 加仓间隔 8%×vol_mult / MAX_ADDONS=4 / 无固定止损
- **权威实现**：`core/v15_trader.py`（3142 行完整版，含 DirectionGate/Phase D/TimingGate）
- **三层风控**：L1 事前门禁（PreTradeGate）→ L2 仓位管理（PositionSizer）→ L3 事后离场（ExitEngine）
