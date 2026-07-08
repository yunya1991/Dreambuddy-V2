# QMM 双轨执行计划

**日期**: 2026-05-13
**状态**: Phase A 启动

---

## 一、总览

QMM 分两条轨道并行推进 Phase A（2-3 周），完成后按收敛判断决定后续方向。

```
Phase A (并行)                    Phase B (收敛后)
────────────                      ────────────
V2 基线 ──→ 零依赖确定性基线       │ 胜率高 → 走激进
V5 原型 ──→ numpy/sklearn 全链路   │ 胜率低 → 走保守
                                    ↓
                            回测门禁判断（见第五节）
```

---

## 二、Phase A — V2 基线（保守线）

**目标**：实现 phase-1 最小集，零外部依赖，输出固定契约 JSON。

### 2.1 交付清单

| 模块 | 文件 | 功能 | 优先级 |
|------|------|------|--------|
| 数据类型 | `scripts/memory_l4/qmm/types.py` | CleanedEvent, ScreenResult, MDRResult, QMMOutput | P0 |
| 路径管理 | `scripts/memory_l4/qmm/paths.py` | qmm_dir() 输出路径 | P0 |
| 数据准备 | `scripts/memory_l4/qmm/data_prep.py` | 从 L4 cases 提取事件 + 清洗 | P0 |
| 三屏对齐 | `scripts/memory_l4/qmm/triple_screen.py` | 长/中/短期窗口对齐 | P0 |
| 阻力方向 | `scripts/memory_l4/qmm/mrd.py` | 象限密度 → 最小阻力 | P0 |
| 引擎入口 | `scripts/memory_l4/qmm/engine.py` | run_qmm() 单入口 | P0 |
| 趋势速度 | `scripts/memory_l4/qmm/trend_velocity.py` | 速度/加速度/变化点 | P1 |
| 不确定性 | `scripts/memory_l4/qmm/uncertainty.py` | 多因子不确定性量化 | P1 |

### 2.2 不做的事

- 不引入 numpy/sklearn/scipy
- 不修改 scripts/memory_l4/ 下任何已有文件
- 不实现 ML 训练、漂移监控、回测门禁（这些是 Phase A V5 原型的事）

### 2.3 验收标准

| 标准 | 检查方法 |
|------|----------|
| 零行现有代码修改 | `git diff main -- scripts/memory_l4/` 不含已有文件 |
| 零外部依赖 | 仅 import math/statistics/json/dataclasses/pathlib |
| 输出契约固定 | 输出 JSON 严格匹配 QMMOutput schema |
| fail-closed | 输入不足 → UNKNOWN + uncertainty=1.0 |
| 版本三元组 | 输出包含 data_version / feature_def_version / qmm_version |
| 可运行 | 给定 `.workbuddy/memory_l4/cases/` 数据，能产出 JSON |

### 2.4 交付形式

合入 main 的 PR，分支命名遵循 `feature/qmm-v2-baseline`。

---

## 三、Phase A — V5 原型（激进线）

**目标**：用 numpy/sklearn 快速搭建完整 QMM 链路，跑一次 walk-forward 回测，验证 ML 是否优于确定性基线。

### 3.1 交付清单

| 模块 | 功能 | 优先级 |
|------|------|--------|
| EventEncoder | 从 TradeCase 提取特征 → 向量 | P0 |
| VectorSpace | 相似度检索 + 简单聚类 | P0 |
| SignalGenerator | 向量加权 → 趋势方向 | P0 |
| TripleScreenAligner | 三屏信号对齐（参考 V5 vision Section 3.3.1）| P0 |
| MemoryTrainer | sklearn GradientBoosting 方向预测 | P0 |
| LeastResistanceCalculator | 多维阻力 → 方向判断（参考 V5 vision Section 四）| P1 |
| 回测框架 | walk-forward 回测（参考 phase-2.md）| P0 |
| 过拟合检测 | train/test gap + fold 方差 | P1 |

### 3.2 数据要求

| 指标 | 最低要求 | 理想要求 |
|------|----------|----------|
| TradeCase 数量 | 50+ | 100+ |
| 覆盖 regime | 3+ | 5+ |
| 时间跨度 | 30 天 | 90 天 |

### 3.3 验收标准

| 标准 | 检查方法 |
|------|----------|
| 回测可执行 | walk-forward 至少 5 folds |
| 胜率可计算 | 输出方向预测准确率 |
| 可复现 | 固定 random_state=42 |
| 降级安全 | ML 失败时降级到确定性基线 |

### 3.4 交付形式

独立分支 `feature/qmm-v5-prototype`，不合并到 main，仅作为验证产物。

---

## 四、Phase A 时间线

```
Week 1:
  V2 基线 ──→ types.py + paths.py + data_prep.py + 单元测试
  V5 原型 ──→ EventEncoder + VectorSpace + SignalGenerator

Week 2:
  V2 基线 ──→ triple_screen.py + mrd.py + engine.py + 端到端运行
  V5 原型 ──→ MemoryTrainer + TripleScreenAligner + 回测框架

Week 3:
  V2 基线 ──→ trend_velocity.py + uncertainty.py + 完善输出
  V5 原型 ──→ walk-forward 回测 + 过拟合检测 + 收敛判断
```

---

## 五、Phase B — 收敛判断

Phase A 完成后，按以下门禁决定后续方向。

### 5.1 判断标准

在 V5 原型的 walk-forward 回测中：

| 条件 | 结论 | 后续行动 |
|------|------|----------|
| ML 准确率 >55% **且** 高置信度子集 >65% | 走激进 | 放弃 V3→V4 分阶段计划 |
| ML 准确率 > 确定性基线 +5% | 走激进 | 在 V2 直接引入 V5 核心 ML 组件 |
| ML 准确率 ≤55% **或** 高置信度子集 ≤65% | 走保守 | 走 V2→V3→V4 路线 |
| ML 准确率 ≤ 确定性基线 | 走保守 | V5 退回为远景文档 |
| train/test gap >15% | 过拟合 | 走保守 + V5 需要正则化 |
| fold 间方差 >0.01 | 不稳定 | 走保守 + 增加数据量 |

### 5.2 激进路线后续

如果判断走激进：

1. 在 `dream-multiskill-v2` 中直接引入 V5 核心 ML 组件
2. V2 基线保留为降级路径
3. `phase-3.md` / `phase-4.md` 文档降级为"历史备选方案"
4. 新建 `constraints/qmm/ml-integration.md` 描述 ML 集成方案

### 5.3 保守路线后续

如果判断走保守：

1. 按 `phase-2.md` 实现 V2 在线门禁
2. 门禁通过后，启动 `phase-3.md` V3 仓库
3. V5 原型分支保留为研究参考
4. 新建独立 V3 仓库，从 V2 复制

---

## 六、风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| V5 原型快速验证失败 | 浪费 2-3 周 | 限定 3 周上限，到时间必须做判断 |
| V2 基线拖延 | 无保底 | V2 基线是 P0 任务，必须先完成 |
| 精力分散 | 两头都慢 | 明确 P0 优先级，P1 可延后 |
| 数据不足 | 回测不可靠 | 如果 <50 TradeCase，推迟收敛判断 |
