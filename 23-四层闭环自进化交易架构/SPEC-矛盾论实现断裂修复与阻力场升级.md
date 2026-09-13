# SPEC: 矛盾论实现断裂修复与阻力场升级

> **状态：** Spec（待评审·v1）
> **创建：** 2026-09-12
> **前置：** [SPEC-主要矛盾识别与最小阻力路径设计.md](./SPEC-主要矛盾识别与最小阻力路径设计.md)
> **理论文档：** [三维度矛盾论理论框架.md](./docs/三维度矛盾论理论框架.md) v3.0
> **目标：** 修复现有矛盾论体系 3 个实现断裂——阻力向量缺微观数据、HJB 路径权重不足、矛盾调制未扩展到 ResistanceVector 层
> **硬约束：** FAIL-OPEN 铁律不可破坏；模块化开关默认关闭；不破坏现有 805 测试；HJB HC-AGI-15/16/17 不可降级

---

## 一 · 问题陈述

### 1.1 三个实现断裂

| 断裂 | 描述 | 严重程度 | 代码位置 |
|:---:|------|:---:|---|
| **断裂 1** | 阻力向量 R_up/R_down 缺少微观结构数据（资金费率、订单簿、OI），只用 3 组件（筹码 50%+清算 30%+趋势 20%） | P0 | [resistance_vector.py L219-L228](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/core/resistance_vector.py#L219-L228) |
| **断裂 2** | HJB 路径规划器已完整实现（二维网格+逆向动态规划+三级降级链），但结果仅 30% 权重调制路径评分，不是最终路径决策者 | P1 | [evolution_pipeline.py _select_optimal_path](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/evolution_pipeline.py#L652-L813) |
| **断裂 3** | 矛盾调制只在 HJB Lagrangian 内部生效（L160-L176），ResistanceVector.calculate() 不接收 primary_contradiction | P1 | [resistance_vector.py calculate()](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/core/resistance_vector.py#L343-L408) |

### 1.2 额外改造点

| 改造点 | 描述 | 严重程度 |
|:---:|------|:---:|
| **改造 4** | strategic FREEZE 时强制输出 short（L544-L555），应改为双候选竞争 | P2 |
| **改造 5** | Bellman tracker 为 per-symbol 一维 V 值，应扩展为 (symbol, regime) 二维 | P3 |

### 1.3 已确认的数据源可用性

| 数据源 | 已有采集代码 | 位置 |
|--------|:---:|------|
| 资金费率 (funding_rate) | ✅ | ftc_gene_innovation.py L74-L84 (`CD-FUNDING-SENT-EXTREME`) |
| 持仓量 (OI) | ✅ | okx_market.py L47-L49 (`_fetch_open_interest`) |
| 订单簿 (orderbook) | ⚠️ 需确认 | okx_market.py 中搜索 |

---

## 二 · 改造方案

### 2.1 改造 1（P0）：阻力向量升级——引入微观结构数据

**文件**：`dreambuddy_evolution/core/resistance_vector.py`

**当前公式**：
```python
W_UP = (0.5, 0.3, 0.2)  # 筹码 / 清算 / 趋势
R_up = max(0.0, min(1.0, 0.5 - 0.38 * combined_up))
```

**改造后公式**：
```python
# 6 组件加权（开关启用时）
W_UP_V2 = (0.20, 0.15, 0.15, 0.20, 0.15, 0.15)
# 筹码 / 清算 / 趋势 / 资金费率 / 订单簿 / OI背离
```

**新增 3 个计算函数**：

| 函数 | 输入 | 计算逻辑 | 输出 |
|------|------|---------|------|
| `_calc_funding_pressure(data)` | `data["funding_rate"]` | `funding_rate > 0 → 做多拥挤 → 做多阻力↑` | `[-1, +1]` |
| `_calc_orderbook_imbalance(data)` | `data["bids_depth"]`, `data["asks_depth"]` | `bid_depth / (bid_depth + ask_depth) - 0.5` | `[-1, +1]` |
| `_calc_oi_divergence(data)` | `data["oi_current"]`, `data["oi_prev"]` | `OI 增加方向 = 新仓涌入 → 该方向阻力↑` | `[-1, +1]` |

**设计原则**：
- 新组件全部 FAIL-OPEN，数据缺失时回退 0.0
- 新增 `enable_microstructure_resistance` 开关（默认关），激活后才用 6 组件，否则保持 3 组件
- 权重总和 = 1.0，不改变 `0.5 - 0.38 × combined` 的整体公式

### 2.2 改造 3（P1）：矛盾调制扩展到 ResistanceVector 层

**文件**：`dreambuddy_evolution/core/resistance_vector.py`

**当前**：`calculate(self, data, flags=None)` — 不接收 `primary_contradiction`

**改造后**：`calculate(self, data, flags=None, primary_contradiction=None)`

**调制逻辑**（与 HJB Lagrangian 完全一致）：
```python
if primary_contradiction is not None:
    pc_dir = primary_contradiction.get("direction", "neutral")
    pc_strength = max(0.0, min(1.0, float(primary_contradiction.get("strength", 0.0))))
    if pc_dir == "long" and pc_strength >= 0.01:
        R_up *= (1.0 - 0.3 * pc_strength)    # 做多阻力降低
        R_down *= (1.0 + 0.5 * pc_strength)  # 做空阻力升高
    elif pc_dir == "short" and pc_strength >= 0.01:
        R_up *= (1.0 + 0.5 * pc_strength)
        R_down *= (1.0 - 0.3 * pc_strength)
```

**设计原则**：
- 调制系数与 HJB Lagrangian 一致（对齐 -30%，逆向 +50%）
- `primary_contradiction=None` 时无调制，完全向后兼容
- 调用方在已有矛盾识别后，将结果传入 `calculate()`

### 2.3 改造 2（P1）：HJB 路径规划权重提升

**文件**：`dreambuddy_evolution/evolution_pipeline.py` `_select_optimal_path`

**当前**：HJB 结果 30% 权重调制评分

**改造后**：

| 模式 | HJB 权重 | 信号融合权重 | 条件 |
|------|:---:|:---:|------|
| 默认（开关关） | 30% | 70% | `enable_hjb_dominant = False` |
| **增强模式** | **70%** | 30% | `enable_hjb_dominant = True` + HJB 收敛 |
| 降级模式 | 0% | 100% | HJB 不收敛（已有三级降级链） |

**新增开关**：`enable_hjb_dominant`（默认关）

### 2.4 改造 4（P2）：strategic FREEZE 双候选

**文件**：`dreambuddy_evolution/evolution_pipeline.py` L544-L555

**当前**：FREEZE → 强制 `direction: "short"`

**改造后**：FREEZE → 输出 short + neutral 双候选，由矛盾识别和 HJB 评分竞争

### 2.5 改造 5（P3）：Bellman tracker 状态空间扩展

**文件**：`dreambuddy_evolution/core/bellman_tracker.py`

**当前**：`td_update(symbol, reward, next_symbol)` — per-symbol 一维

**改造后**：`td_update(symbol, regime, reward, next_symbol, next_regime)` — per-symbol×regime 二维

**设计**：
- regime 来源：BTC Regime Classifier 输出（bull/bear/range）
- V 值矩阵：`V[symbol][regime]`
- 向后兼容：`regime=None` 时退化为单维

---

## 三 · 依赖关系与执行顺序

```
改造1 (阻力向量+微观数据) ←─ 基础，无依赖
    ↓
改造3 (矛盾调制扩展到 RV 层) ←─ 依赖改造1
    ↓
改造2 (HJB 权重提升) ←─ 依赖改造1+改造3
    ↓                               ↑（并行）
改造4 (FREEZE 双候选)     改造5 (Bellman 扩展)
```

---

## 四 · 开关设计

| 开关 | 默认 | 作用 |
|------|:---:|------|
| `enable_microstructure_resistance` | False | 启用 6 组件阻力向量（改造1） |
| `enable_rv_contradiction_modulation` | False | RV 层矛盾调制（改造3） |
| `enable_hjb_dominant` | False | HJB 权重 70%（改造2） |

---

## 五 · 测试计划

| 改造 | 测试文件 | 测试内容 |
|------|---------|---------|
| 改造1 | test_resistance_vector_microstructure.py | 6 组件计算 + FAIL-OPEN + 开关守卫 |
| 改造3 | test_rv_contradiction_modulation.py | 矛盾调制一致性 + 向后兼容 |
| 改造2 | test_hjb_dominant_mode.py | 权重切换 + 降级链 |
| 改造4 | test_freeze_dual_candidate.py | 双候选竞争 |
| 改造5 | test_bellman_regime.py | 二维 V 值 + 兼容 |
| **全量** | 全量回归 | 805+ 测试 0 回归 |

---

## 六 · 落地后预期效果

| 维度 | 改造前 | 改造后 |
|------|--------|--------|
| 阻力向量数据源 | 3 组件 | 6 组件 |
| 矛盾调制生效范围 | 仅 HJB 内部 | HJB + RV 双层 |
| HJB 路径决策权重 | 30% | 70%（增强模式） |
| FREEZE 路径 | 强制 short | 双候选竞争 |
| Bellman 状态空间 | per-symbol 一维 | per-symbol×regime 二维 |
