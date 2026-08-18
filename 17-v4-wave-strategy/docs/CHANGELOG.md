# 变更日志 — V4 减半周期 + 艾略特波浪互斥融合趋势策略

> **版本**: v1.0 | **更新日期**: 2026-07-31
> **定位**: 记录每次变更的原因、内容、验证方式，对齐 [DOC_STANDARD.md](../../0-系统文档管理/1-规范体系/DOC_STANDARD.md) §3.5
> **关联文档**: [ENGINEERING_INDEX.md](./ENGINEERING_INDEX.md) · [TECHNICAL_DESIGN.md](./TECHNICAL_DESIGN.md) · [API_SPEC.md](./API_SPEC.md) · [README.md](../README.md)

---

## [v1.0] - 2026-07-31

### 新增

- **变更内容**: 17-v4-wave-strategy 子系统初始文档体系建立（5 份标准文档全部补齐）
  - 新增 `README.md`：用户文档，含概述、目录结构、快速开始、核心功能、配置说明、回测结果摘要、FAQ
  - 新增 `docs/ENGINEERING_INDEX.md` v1.0：工程索引，含模块定位、完整目录树、文件清单（含函数数和关键函数名）、核心流程索引、配置参数索引、测试体系、技术债务、快速导航
  - 新增 `docs/TECHNICAL_DESIGN.md` v1.0：技术设计，含概述、架构设计（V4 引擎+波浪识别+互斥融合）、核心算法（减半周期逃顶+艾略特波浪识别+互斥逻辑，含公式/伪代码）、数据流、接口设计、状态管理、配置管理、错误处理、扩展性设计
  - 新增 `docs/API_SPEC.md` v1.0：接口规格，覆盖 11 个 Python API + 2 个 CLI 接口的签名、参数、返回值、调用示例、错误码、版本管理
  - 新增 `docs/CHANGELOG.md` v1.0：变更日志（本文件）

- **影响范围**:
  - `17-v4-wave-strategy/README.md`（新建）
  - `17-v4-wave-strategy/docs/ENGINEERING_INDEX.md`（新建）
  - `17-v4-wave-strategy/docs/TECHNICAL_DESIGN.md`（新建）
  - `17-v4-wave-strategy/docs/API_SPEC.md`（新建）
  - `17-v4-wave-strategy/docs/CHANGELOG.md`（新建）

- **验证方式**:
  - 文档头部均包含版本号 v1.0、更新日期 2026-07-31、定位说明、关联文档链接
  - ENGINEERING_INDEX 文件清单已标注函数数与关键函数名（如 `compute_v4_wave_signal()`, `identify_waves()`, `_fuse_positions()` 等）
  - TECHNICAL_DESIGN 含核心算法说明（减半周期相位公式、ZigZag 算法、艾略特三大硬规则、互斥融合伪代码、物理增强公式）
  - 文件命名使用大写+下划线（ENGINEERING_INDEX.md / TECHNICAL_DESIGN.md / API_SPEC.md / CHANGELOG.md）
  - 内容基于实际代码编写：
    - 回测数据来源于 `backtest_results/v4_wave_9year_btc.json` 与 `v4_wave_independent_btc.json`
    - 接口签名来源于 `v4_wave_engine.py`、`halving_top_exit_strategy.py`、`ewave_recognizer.py`、`ewave_strategy_adapter.py`、`data/market_data.py`、`live/v4_wave_trader.py`、`backtest_v4_wave.py` 实际代码
    - 配置参数来源于 `WaveConfig` dataclass 与 `HalvingTopExitStrategy.__init__` 实际默认值

- **回滚策略**:
  - 文档为新增内容，无破坏性变更
  - 如需回滚：`git rm 17-v4-wave-strategy/README.md 17-v4-wave-strategy/docs/` 即可恢复至无文档状态
  - 不影响任何代码逻辑与运行时行为

### 文档基线建立说明

本次变更是 17-v4-wave-strategy 子系统的**文档补齐任务**，对应 DOC_STANDARD.md §7 子系统文档状态对照表中 "17-v4-wave-strategy" 行的首次登记。变更前该子系统代码完整但 5 文档全缺；变更后达到文档评级 A 标准（5 个文档全部完整，文件级索引到函数级）。

文档基线版本统一为 v1.0，后续任何代码/接口/架构变更需按 DOC_STANDARD.md §5 变更维护流程同步更新对应文档并追加 CHANGELOG 记录。

---

## 变更类型说明

| 类型 | 说明 |
|------|------|
| **新增** | 添加新功能、新文件、新接口 |
| **修改** | 修改已有功能、重构、优化 |
| **修复** | 修复 bug、缺陷、错误 |
| **删除** | 移除废弃功能、文件、接口 |

---

**文档版本**: v1.0
**最后更新**: 2026-07-31
