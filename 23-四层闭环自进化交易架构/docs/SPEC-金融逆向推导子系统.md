# SPEC — 金融逆向推导子系统（方向3）

> **版本**: v0.1 (2026-10-10)
> **状态**: 草案（待评审）
> **来源**: REA逆向工程思维三方向调研
> **定位**: 23-四层闭环自进化交易架构的子系统，用REA逆向推导思维优化交易决策
> **父SPEC**: [23-四层闭环自进化交易架构](../README.md)

---

## 0. 核心洞察

REA的本质是 **"从结果反推输入"** 的逆向工程思维。映射到交易：

```
正向链（现有）：矛盾系统(回测=过去规律) + 矛盾Transformer(当下力量) → 预测 → 开仓
逆向链（新增）：交易结果 → 反推哪个环节判断错 → 定位问题 → 训练/优化
```

这与算法优化中的"反向传播"异曲同工：
| 算法优化 | 金融逆向推导 |
|---|---|
| 前向传播 forward | 矛盾系统+矛盾Transformer预测 |
| 损失函数 loss | PnL / CS一致性得分 |
| 反向传播 backward | ReverseDeriver：从结果反推每维度误差 |
| 梯度 gradient | 每维度的 prediction_error |
| 参数更新 SGD | ESS/gmax/因子权重调整 |
| 学习率 lr | 奖惩步长（±0.02/±0.05） |

**关键差异**：算法优化是连续可微的，交易决策是离散的（long/short/wait），所以用"维度级误差归因"代替梯度，用"奖惩表"代替SGD更新。

---

## 1. 现状基线

### 1.1 现有反思闭环

`ReflectionEngine`（[reflection_engine.py](../dreambuddy_evolution/engines/reflection_engine.py)）已有：
- `create_snapshot`：开仓瞬间记录 `{d*, ess_dir, cbr_top1_outcome, cluster_id, ...}`
- `calculate_cs`：CS = 0.4·cos(d*,real) + 0.3·cos(ESS,real) + 0.3·sign_match(CBR,real)
- `apply_reward`：四维奖惩表 → ess_delta, gmax_mult, cluster_weight_mult

### 1.2 缺口

CS是**整体一致性得分**，但**没有定位"哪个矛盾维度判断错了"**。REA的逆向推导可以补上这一层：
- 不知道是C1(资金)错了还是C3(技术)错了
- 不知道是因子计算错还是权重不对
- 奖惩是"黑箱"整体调整，无法精准归因

---

## 2. 系统架构

```
┌──────────────────────────────────────────────────────────────────┐
│                    正向预测链（现有）                              │
│  矛盾系统(回测) + 矛盾Transformer(当下) → d*, ESS, CBR → 开仓     │
└──────────────────────────────┬───────────────────────────────────┘
                               │ 开仓快照（扩展）
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│              扩展后的 create_snapshot                             │
│  + 每维度判断: {C1:dir, C2:dir, C3:dir, ...}                     │
│  + 每维度因子权重: {C1: {因子:权重}, ...}                         │
│  + attention_weights: cross_attention输出                         │
└──────────────────────────────┬───────────────────────────────────┘
                               │ 交易结果
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│              ReverseDeriver（新增）                                │
│  Step1: 每维度预测方向 vs 实际方向 → per_dimension_correctness    │
│  Step2: 主要矛盾判断是否正确 → 假失败/真失败判定                   │
│  Step3: 证据链回溯 → 因子值/权重/数据源定位根因                    │
│  Step4: 输出逆向Evidence {wrong_dim, root_cause, confidence}     │
└──────────────────────────────┬───────────────────────────────────┘
                               │ 逆向Evidence
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│              精准奖惩（增强 apply_reward）                         │
│  - 错误维度因子降权，正确维度因子升权                              │
│  - 错误案例入库（CBR/KNN）                                        │
│  - 止损/止盈/超时参数逆向优化                                      │
└──────────────────────────────────────────────────────────────────┘
```

---

## 3. 核心组件设计

### 3.1 扩展 create_snapshot

**目标**：记录每维度判断 + 因子权重 + attention_weights，为逆向推导提供输入。

**改动**：
```python
def create_snapshot(
    self,
    symbol: str,
    u_open: float,
    action: str,
    level0_dstar: str,
    ess_id: str,
    ess_dir: str,
    cbr_sim: float,
    cbr_top1_outcome: str,
    cluster_id: str,
    # === 新增 ===
    dimension_predictions: dict[str, str] | None = None,  # {C1: "long", C2: "short", ...}
    dimension_factors: dict[str, dict[str, float]] | None = None,  # {C1: {因子名: 权重}, ...}
    attention_weights: list[float] | None = None,  # cross_attention输出
    factor_values: dict[str, float] | None = None,  # 实际因子值
) -> dict[str, Any]:
    snapshot = {
        # ... 原有字段 ...
        "dimension_predictions": dimension_predictions or {},
        "dimension_factors": dimension_factors or {},
        "attention_weights": attention_weights or [],
        "factor_values": factor_values or {},
    }
    return snapshot
```

**数据来源**：
- `dimension_predictions`：从 `PrimaryContradictionIdentifier.identify(paths, ...)` 的**输入 `paths`** 中提取每路径 `direction`，通过 `SOURCE_DIM_MAP`（bdsm→C1, trend_following/grid_trading→C2, bcrm→C3, strategic→C4, deep_reasoning→C6, synthesized→C7, l2_gene→C8）映射到维度。**注意**：`identify()` 返回值 `primary` 只含整体 direction/confidence/strength/dimension，不含每维度方向
- `dimension_factors`：来自矛盾Transformer的 `factor_head_mask` 和权重
- `attention_weights`：来自 `cross_attention` 的 `last_attn_weights`
- `factor_values`：来自各因子计算引擎的实际输出值

### 3.2 ReverseDeriver（新增组件）

**文件**：`dreambuddy_evolution/engines/reverse_deriver.py`

**核心方法**：
```python
class ReverseDeriver:
    def derive(self, snapshot: dict, outcome: dict) -> ReverseDeriveResult:
        """从交易结果反推哪个维度判断错。"""

    def _per_dimension_correctness(self, snapshot, outcome) -> dict[str, bool]:
        """Step1: 每维度预测方向 vs 实际方向"""

    def _primary_dimension_check(self, snapshot, per_dim_cs) -> str:
        """Step2: 主要矛盾判断是否正确 → false_failure / true_failure / correct"""

    def _evidence_trace(self, snapshot, wrong_dim) -> dict:
        """Step3: 证据链回溯 — 因子值/权重/数据源"""

    def _output_evidence(self, wrong_dim, root_cause, confidence, known_gaps) -> dict:
        """Step4: 输出逆向Evidence"""
```

**ReverseDeriveResult 结构**：
```python
@dataclass
class ReverseDeriveResult:
    per_dimension_correctness: dict[str, bool]   # {C1: True, C2: False, ...}
    per_dimension_cs: dict[str, float]           # {C1: 1.0, C2: -1.0, ...}
    wrong_dimensions: list[str]                  # 判断错误的维度列表
    root_cause: str                              # 根因描述
    root_cause_type: str                         # factor_error / weight_error / data_error / unknown
    confidence: float                            # 0.0-1.0
    known_gaps: list[str]                        # 已知局限
    optimization_action: str                     # 建议的优化动作
```

**FAIL-OPEN 设计**：

逆向推导失败时**不阻塞主交易流程**，返回中性结果：

```python
class ReverseDeriver:
    def derive(self, snapshot: dict, outcome: dict) -> ReverseDeriveResult:
        try:
            # 正常推导流程
            ...
        except Exception as e:
            logger.warning("[FO] ReverseDeriver fail: %s", e)
            return self._neutral_result(snapshot, outcome)

    def _neutral_result(self, snapshot, outcome) -> ReverseDeriveResult:
        """FAIL-OPEN 中性结果：不做任何因子调整。"""
        return ReverseDeriveResult(
            per_dimension_correctness={},
            per_dimension_cs={},
            wrong_dimensions=[],
            root_cause="reverse_derive_failed",
            root_cause_type="unknown",
            confidence=0.0,
            known_gaps=["逆向推导失败，无法归因"],
            optimization_action="no_adjustment",
        )
```

**FAIL-OPEN 触发条件**：
| 条件 | 处理 |
|---|---|
| snapshot 缺 dimension_predictions | 返回 neutral，known_gaps=["缺少维度预测数据"] |
| outcome 缺 real_direction | 返回 neutral，known_gaps=["缺少实际方向"] |
| 因子值缺失/类型错误 | 跳过该维度，不影响其他维度 |
| confidence < 0.3 | optimization_action="no_adjustment"（不自动调整） |
| 任何未捕获异常 | 返回 neutral_result，记录日志 |

### 3.3 增强 apply_reward（精准奖惩）

**目标**：基于 ReverseDeriveResult 精准调整因子权重，而非整体调整。

**改动**：
```python
def apply_reward_with_derive(
    self,
    cs: float,
    outcome: str,
    cluster_id: str,
    ess_id: str,
    gmax: float,
    derive_result: ReverseDeriveResult,  # 新增
) -> dict[str, Any]:
    base_reward = self.apply_reward(cs, outcome, cluster_id, ess_id, gmax)

    # 精准因子奖惩
    factor_adjustments = {}
    for dim, correct in derive_result.per_dimension_correctness.items():
        if not correct:
            # 错误维度的因子降权
            for factor, weight in snapshot["dimension_factors"].get(dim, {}).items():
                factor_adjustments[factor] = weight * 0.9  # 降权10%
        else:
            # 正确维度的因子升权
            for factor, weight in snapshot["dimension_factors"].get(dim, {}).items():
                factor_adjustments[factor] = weight * 1.05  # 升权5%

    return {**base_reward, "factor_adjustments": factor_adjustments}
```

---

## 4. 矛盾维度定义

参照 [矛盾Transformer架构.md](./矛盾Transformer架构.md) 的C1-C8维度：

| 维度 | 名称 | 数据来源 |
|---|---|---|
| C1 | 资金流 | 大单/主力资金净流入 |
| C2 | 情绪面 | 多空比/恐慌贪婪 |
| C3 | 技术面 | K线/指标/形态 |
| C4 | 宏观面 | 利率/通胀/事件 |
| C6 | 时序结构 | Hurst/序列相关性 |
| C7 | 隐性维度 | 未公开信息代理 |
| C8 | 宏观交叉 | 跨市场相关性 |

每维度输出 `{direction: long/short/neutral, strength: 0-1, confidence: 0-1}`。

---

## 5. 训练/优化器应用

逆向推导的产出可驱动4类优化：

### 5.1 因子权重优化
- 某维度持续判断错 → 降低该维度因子权重
- 已有 `_maybe_auto_adjust_weight` 雏形，扩展为维度级

### 5.2 案例库训练（CBR/KNN）
- 错误案例入库，标注 `{wrong_dim, root_cause}`
- 下次类似场景（相同wrong_dim模式）降权或避开

### 5.3 策略参数调整
- 止损/止盈/超时参数的逆向优化
- 若多次"方向对但被扫损"（CS≥0.7&SL）→ 放宽止损
- 若多次"方向对但超时"→ 延长持仓时间

### 5.4 矛盾Transformer微调
- 用逆向推导的标注数据（哪个维度该赢）微调 `factor_head_mask`
- 降低错误维度的head权重

---

## 6. 与 REA Evidence 结构的统一

逆向推导的输出 `ReverseDeriveResult` 复用 33-REA 的 Evidence 结构：
- `level`：derivation（从观察推导）
- `provenance`：{snapshot_id, outcome_id, dimensions_checked}
- `confidence`：0.0-1.0
- `known_gaps`：["未考虑滑点影响", "因子值可能有延迟"]

这样金融逆向推导的Evidence和工程逆向的Evidence结构统一，可统一入库认知记忆系统。

---

## 7. 实施路线（TDD）

每个任务遵循 **RED → GREEN → REFACTOR** 循环：

### P0 — ReverseDeriver核心（1-2天）
- **RED**：写测试断言 `ReverseDeriver.derive(snapshot含{C1:long,C2:short}, outcome=real_short)` 返回 `per_dimension_correctness={C1:False, C2:True}`
- **GREEN**：扩展 `create_snapshot` 字段 + 实现 `ReverseDeriver.derive()` 四步法
- **REFACTOR**：四步法提取为独立方法，FAIL-OPEN 中性结果独立

### P1 — 精准奖惩集成（1天）
- **RED**：写测试断言 `apply_reward_with_derive(cs=-0.5, derive_result含wrong_dim=[C1])` 返回 `factor_adjustments` 中 C1 因子降权
- **GREEN**：实现 `apply_reward_with_derive` + 接入 polling_trader 结算
- **REFACTOR**：因子奖惩逻辑独立，不影响现有四维奖惩表

### P2 — 训练/优化器闭环（2-3天）
- **RED**：写测试断言错误案例入库后 CBR 检索返回该案例
- **GREEN**：错误案例入库 + 参数逆向优化 + factor_head_mask 微调
- **REFACTOR**：优化器抽象为独立接口，支持多种优化策略

### P3 — 持续优化
- **RED**：写回测断言逆向推导启用后胜率提升
- **GREEN**：多维度联合归因 + 认知记忆集成 + 回测验证
- **REFACTOR**：归因算法可插拔

---

## 8. 验收标准

### P0 验收
1. `create_snapshot` 可记录 dimension_predictions/dimension_factors
2. `ReverseDeriver.derive()` 输出 per_dimension_correctness + root_cause + confidence + known_gaps
3. 单元测试覆盖：全对/全错/部分对/假失败/真失败 5种场景

### P1 验收
1. `apply_reward_with_derive` 输出 factor_adjustments
2. 端到端：开仓→结算→逆向推导→精准奖惩 全链路通

### P2 验收
1. 错误案例自动入库，标注wrong_dim
2. 参数优化有实际效果（回测对比）

---

## 9. 风险与约束

| 风险 | 应对 |
|---|---|
| 维度判断数据采集开销 | 复用矛盾Transformer已有输出，不额外计算 |
| 逆向推导根因定位不准 | confidence<0.5 时不自动调整，只记录 |
| 过度拟合历史错误 | 因子调整有边界（权重∈[0.1, 2.0]）+ 冷却期 |
| 与现有奖惩冲突 | base_reward优先，factor_adjustments是增量 |

---

## 10. 与其他系统的关系

| 系统 | 关系 |
|---|---|
| **ReflectionEngine** | 扩展其 create_snapshot + apply_reward |
| **PrimaryContradictionIdentifier** | 提供输入 paths（含每路径 direction，经 SOURCE_DIM_MAP 映射为 dimension_predictions） |
| **cross_attention** | 提供 attention_weights |
| **33-REA逆向解析工程** | 复用Evidence数据结构 |
| **认知记忆系统** | 逆向Evidence可入库 |

---

## 附录：与算法优化的完整类比

| 阶段 | 算法优化 | 金融逆向推导 |
|---|---|---|
| 前向 | forward(input) → output | 矛盾系统+Transformer → d*/ESS/CBR |
| 损失 | loss_fn(output, target) | CS(d*, ESS, CBR vs real) + PnL |
| 反向 | backward() → gradients | ReverseDeriver → per_dimension_error |
| 优化器 | SGD/Adam 更新参数 | apply_reward 更新 ESS/gmax/因子权重 |
| 学习率 | lr | ess_delta 步长 (±0.01/±0.02/±0.05) |
| 正则化 | weight_decay | 权重边界 [0.1, 2.0] + 冷却期 |
| 早停 | early_stopping | 冷启动阈值（样本<20不调整） |
