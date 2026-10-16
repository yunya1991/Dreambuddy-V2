# SPEC · 双链路可观测性与状态同步修复
> **版本**: v0.1 | **日期**: 2026-10-15 | **状态**: 待评审
> **模块**: 23-四层闭环自进化交易架构 / `dreambuddy_evolution`
> **关联**: `engines/deep_reasoning_engine.py`、`engines/sde_solver.py`、`evolution_pipeline.py`、`core/contradiction_identifier.py`、`core/cross_validation_gate.py`、`11-易经推理系统/scripts/memory_l4/polling_trader.py`
> **定位**: 可观测性/正确性修复——修复链路二状态上报断链，补齐链路一推理输出可观测性，疏通 W6 权重自学习样本链路。
> **来源**: 2026-10-15 双链路深入排查（矛盾论链路 + 矛盾 Transformer 链路）发现的 4 项问题。

---

## 0 · 背景与问题清单

双链路架构（矛盾论 v3.0 链路 + 矛盾 Transformer 链路）经代码与运行时排查，确认均在推理、无崩溃性 bug，但存在以下问题：

| # | 问题 | 严重度 | 证据 |
|---|------|--------|------|
| P1 | **链路二状态上报断链**：`deep_reasoning_engine._sde_backend_used` 初始化为 `unavailable` 后从未被更新，快照 `neural_sde_backend` 恒为 `unavailable`（假象）；实际后端状态在 `sde_solver._sde_backend_used` 中更新，两者未同步 | P0 | 快照 2000 条记录全部 `unavailable`，但日志 2026-10-15 01:31:37 记录模型加载成功且懒加载仅在预测被调用时触发 |
| P2 | **链路一推理输出不可观测**：主矛盾识别结果（维度/方向/强度）不写 INFO 日志、不进快照，运行时完全不可观测 | P1 | 日志中无任何主矛盾识别输出；快照字段列表无 `primary_contradiction` |
| P3 | **W6 权重自学习从未生效**：`data/contradiction_samples.json` 不存在，样本从未持久化，识别器一直用默认权重 `[0.40, 0.15, 0.25, 0.20]`，链路一『自进化』实际未发生 | P1 | 磁盘无样本文件；`MIN_SAMPLES=500` 从未达到 |
| P4 | **交叉验证门禁无心跳**：CrossValidationGate 静默运行（FAIL-OPEN 设计），无周期性输出，无法确认双链路交汇在工作 | P2 | 日志中零条门禁记录（含质变未触发的正常期） |

**硬约束（不可破坏）**: HC-AGI-02（异常→中性兜底）、HC-AGI-03（FAIL-OPEN + 6 层堆栈 + 5 分钟 3 次告警）、HC-AGI-07（新模块默认关）；FAIL-OPEN 铁律；所有修复不得改变交易决策行为（P1/P2/P4 纯可观测性，P3 仅疏通既有学习机制）。

---

## 1 · 目标与非目标

### 1.1 目标
1. 快照 `neural_sde_backend` 字段反映真实后端状态（torchsde/euler_maruyama/garch/gbm）。
2. 主矛盾识别结果每周期可观测：INFO 日志 + 快照字段。
3. W6 样本记录链路疏通，`contradiction_samples.json` 开始积累，权重自学习可发生。
4. 交叉验证门禁周期性心跳日志，双链路交汇可确认。

### 1.2 非目标
- 不改任何交易决策逻辑、门禁判定阈值、调制契约。
- 不改 NeuralSDE 模型本身、不重训练。
- 不引入新的外部依赖。

---

## 2 · 修复设计

### 2.1 P0：backend_status 状态同步（一行级改动）

**文件**: `engines/deep_reasoning_engine.py`

**现状**:
```python
self._sde_backend_used: str = "unavailable"   # L67，初始化后从未更新
def backend_status(self) -> dict:
    return {"neural_sde_backend": self._sde_backend_used, ...}  # L89，读旧值
```

**修复**: `backend_status()` 改为委托读取求解器真实状态：
```python
def backend_status(self) -> dict:
    return {
        "timesfm": self._timesfm_available,
        "timesfm_api": self._timesfm_api,
        "signatory": self._signatory_available,
        "neural_sde": self._torch_available,
        "neural_sde_trained": self._sde._neural_sde_loaded,
        "neural_sde_backend": self._sde._sde_backend_used,  # ← 委托求解器
    }
```
保留 `self._sde_backend_used` 实例变量向后兼容（旧测试引用），但不再作为状态源。

**验证**: 修复后快照 `neural_sde_backend` 应出现 `torchsde` 或 `euler_maruyama`（模型已加载且激活时）。

### 2.2 P1：链路一推理输出可观测

**文件**: `evolution_pipeline.py`（主矛盾识别段之后，约 L1027）

**新增日志**（每周期 1 条 INFO，与 PathDiscovery 日志同频）:
```python
if primary_contradiction is not None:
    logger.info(
        "[Contradiction] dim=%s dir=%s strength=%.3f tf=%s",
        primary_contradiction.get("dimension"),
        primary_contradiction.get("direction"),
        float(primary_contradiction.get("strength", 0.0)),
        primary_contradiction.get("timeframe", "?"),
    )
```

**快照字段**：主流程返回 dict 已含 `primary_contradiction`（L1364），需在 `polling_trader.py` 快照构建处（约 L12440 `_agi_snap` dict）透传精简字段：
```python
_pc = _result.get("primary_contradiction") or {}
_agi_snap["primary_contradiction"] = {
    "dimension": _pc.get("dimension"),
    "direction": _pc.get("direction"),
    "strength": _pc.get("strength"),
} if _pc else None
```

**日志量控制**: 每周期每 symbol 1 条，与现有 `[PathDiscovery]` 两行日志同量级，不显著增加日志体积（当前日志约 10MB/天，预计增幅 <10%）。

### 2.3 P1：W6 样本链路疏通

**文件**: `core/contradiction_identifier.py`

**现状分析**: `_weight_learner.label_previous()` 在 `_label_previous_from_market`（L365）中被调用，但 `data/contradiction_samples.json` 从未生成。需先定位断点：
- 检查 `record_sample`（样本写入入口）的调用方——若主流程从未调用，则样本永远为空；
- 检查 `_label_previous_from_market` 的触发条件（market_data 是否携带所需字段）。

**修复方向**（二选一，排查后定）:
- 方案 A：若 `record_sample` 无调用方 → 在主流程主矛盾识别后记录当期样本（维度/方向/强度/时间戳），下一周期由 `label_previous` 用实际收益标注；
- 方案 B：若调用链存在但条件不满足 → 修复条件判断（如 market_data 字段名不匹配）。

**验证**: 运行 ≥2 个周期后 `data/contradiction_samples.json` 出现且行数递增；样本达 500 后日志出现 `[W6] auto-learned weights`。

### 2.4 P2：交叉验证门禁心跳

**文件**: `evolution_pipeline.py`（交叉验证段，约 L1160 后）

**心跳日志**（每 symbol 每 N=50 周期 1 条 INFO，避免刷屏）:
```python
self._cv_heartbeat_count = getattr(self, "_cv_heartbeat_count", 0) + 1
if self._cv_heartbeat_count % 50 == 0:
    logger.info(
        "[CrossValidation] heartbeat #%d G_dim=%s A_dim=%s conf_mult=%.2f shift=%s",
        self._cv_heartbeat_count, _g_dim, _a_dim,
        cv_result.get("confidence_mult", 1.0), cv_result.get("shift_signal", False),
    )
```

**验证**: 日志中每 50 周期出现一条心跳，G_dim/A_dim 非空（Granger 管线激活时）。

---

## 3 · 实施顺序与验证

| 步骤 | 内容 | 验证方式 | 风险 |
|------|------|----------|------|
| S1 | P0 状态同步 | 快照 backend 字段变为真实后端 | 极低（纯读侧） |
| S2 | P1 主矛盾日志+快照 | 日志出现 [Contradiction] 行；快照含字段 | 低（纯可观测） |
| S3 | P2 门禁心跳 | 日志出现 [CrossValidation] heartbeat | 低 |
| S4 | P1 W6 链路排查+修复 | 样本文件生成并递增 | 中（需先排查断点，修复后观察 500 样本积累期） |

S1-S3 可一次提交；S4 单独提交并观察。

## 4 · 回滚
- S1-S3 均为纯可观测性改动，回滚即 revert 提交，无状态残留。
- S4 若样本记录异常，删除 `contradiction_samples.json` 即回到默认权重（与现状等价）。
