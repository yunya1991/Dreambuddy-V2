# 实施计划：大小周期弹性边界约束（CycleBoundsConstraint）

> **关联 Spec：** [2026-08-19-morph-cycle-dynamic-correction-design.md §三bis](../specs/2026-08-19-morph-cycle-dynamic-correction-design.md)
> **创建日期：** 2026-08-19
> **状态：** 待执行
> **作者：** TRAE Code Assistant
> **方法论：** TDD（Red-Green-Refactor）

---

## 0. 计划概览

### 0.1 总体路径

按 Spec §3bis.10 实施顺序，共 11 个任务，分 4 个阶段：

| 阶段 | 任务 | 范围 | 验收 |
|------|------|------|------|
| **阶段 A：超参与核心插值** | T1-T3 | CYCLE_BOUNDS_* 超参、`_interp_cycle_bounds()`、边界缓存 | T_CB1, T_CB7 单测通过 |
| **阶段 B：三类调整动作** | T4-T6 | FFT 振幅缩放、预测曲线回拉、越界信号检测 | T_CB2, T_CB3, T_CB4 单测通过 |
| **阶段 C：集成与联动** | T7-T9 | predict() 集成轨道三、storage 扩展、_maybe_anchor_correct 读 hint | T_CB5, T_CB6 集成测试通过 |
| **阶段 D：API 与回测** | T10-T11 | 新增 API、WalkForward 回测验证 | API 冒烟测试 + 回测报告 |

### 0.2 依赖关系

```
T1 (新增超参)
    ↓
T2 (_interp_cycle_bounds) ← 依赖 T1
    ↓
T3 (边界缓存 _get_cycle_bounds) ← 依赖 T2
    ↓
T4 (FFT 振幅缩放) ← 依赖 T3
T5 (预测曲线回拉) ← 依赖 T3
T6 (越界信号检测) ← 依赖 T3
    ↓ (T4/T5/T6 可并行)
T7 (predict() 集成轨道三) ← 依赖 T4, T5, T6
    ↓
T8 (storage 扩展 overshoot_hint) ← 独立可前置
T9 (_maybe_anchor_correct 读 hint 降冷却) ← 依赖 T7, T8
    ↓
T10 (新增 API /api/morph/cycle_bounds) ← 依赖 T7
T11 (WalkForward 回测验证) ← 依赖 T7, T9
```

### 0.3 风险控制

- 每个任务严格按 TDD 流程：先写失败测试 → 最小实现通过 → 重构
- `CYCLE_BOUNDS_ENABLED` 默认 `False`，确保 CLI 默认字节等价 Phase 0（硬约束兼容性）
- 阶段 C 前不修改 `predict()` 主流程，避免影响现有双轨修正
- WalkForward 回测需对比开启/关闭边界约束的预测精度，仅当精度提升才允许 promote

### 0.4 测试运行器约定

- 测试目录：`11-易经推理系统/scripts/memory_l4/bcrm2/tests/`
- 测试文件命名：`test_cycle_bounds_<功能>.py`
- 运行命令：`cd 11-易经推理系统/scripts/memory_l4/bcrm2 && python -m pytest tests/test_cycle_bounds_*.py -v`

---

## 阶段 A：超参与核心插值

### T1：新增 CYCLE_BOUNDS_* 超参

**目标：** 在 `morph_cycle_predictor.py` 中新增大周期弹性边界约束的所有超参。

**文件：** `11-易经推理系统/scripts/memory_l4/bcrm2/morph_cycle_predictor.py`

**实现内容：**

```python
# ── 大周期弹性边界约束超参 ───────────────────────────────────
CYCLE_BOUNDS_ENABLED = False         # 总开关（默认 False 以保持 CLI 字节等价）
CYCLE_BOUNDS_INTERP = True            # 启用插值边界（False 时用硬命中）
CYCLE_BOUNDS_DECAY_DEFAULT = 0.20     # 黔回拉强度（越界部分保留比例）
CYCLE_BOUNDS_DECAY_BY_PHASE = {       # 按 phase_hint 定制回拉强度
    "蓄力": 0.15, "上升": 0.20, "顶部": 0.25,
    "顶点": 0.30, "下跌": 0.25, "底部": 0.20,
    "底点": 0.30, "磨底": 0.15,
}
CYCLE_BOUNDS_AMPLITUDE_MULT = 1.5     # 振幅上限 = (hi - mean) × 此倍数
CYCLE_BOUNDS_OVERSHOOT_TRIGGER = 5    # 现实曲线连续越界 N 天 → 触发锚点大调整
```

**TDD 流程：**

1. **RED**：写测试 `test_cycle_bounds_hyperparams_exist`，断言所有超参存在且默认值正确
   - `CYCLE_BOUNDS_ENABLED == False`（CLI 默认字节等价）
   - `CYCLE_BOUNDS_DECAY_BY_PHASE["顶点"] == 0.30`
   - `CYCLE_BOUNDS_OVERSHOOT_TRIGGER == 5`
2. **Verify RED**：运行测试，确认因超参未定义而失败
3. **GREEN**：在 `morph_cycle_predictor.py` 顶部新增超参常量
4. **Verify GREEN**：运行测试通过

**验证命令：**
```bash
cd 11-易经推理系统/scripts/memory_l4/bcrm2 && python -m pytest tests/test_cycle_bounds_hyperparams.py -v
```

---

### T2：`_interp_cycle_bounds()` 插值实现（T_CB1）

**目标：** 根据大周期 `t_rel_current` 在 `CYCLE4Y_PARAM_RANGES` 两个相邻锚点间线性插值，得到小周期边界参数。

**文件：** `11-易经推理系统/scripts/memory_l4/bcrm2/morph_cycle_predictor.py`

**函数签名：**

```python
def _interp_cycle_bounds(self, t_rel_current: float) -> Dict[str, Any]:
    """从大周期 t_rel 位置插值得到小周期边界参数。

    在 CYCLE4Y_PARAM_RANGES 两个相邻锚点间线性插值：
      - level_lo / level_hi / level_mean 按位置比例插值
      - phase_hint 取距离更近的锚点
      - decay_strength 由 phase_hint 查表得到
      - amplitude_cap = (level_hi - level_mean) × CYCLE_BOUNDS_AMPLITUDE_MULT

    返回：
      {
        "t_rel_current": float,
        "phase_hint": str,
        "level_lo": float,
        "level_hi": float,
        "level_mean": float,
        "amplitude_cap": float,
        "decay_strength": float,
      }
    """
```

**插值算法：**

1. 遍历 `CYCLE4Y_PARAM_RANGES`，找到 `t_rel_current` 落在哪两个锚点的 `t_rel_mean` 之间
2. 计算位置比例 `alpha = (t_rel_current - t_left) / (t_right - t_left)`
3. 线性插值：`level_lo = left.level_range[0] × (1-alpha) + right.level_range[0] × alpha`（level_hi、level_mean 同理）
4. `phase_hint` 取距离更近的锚点（alpha < 0.5 取 left，否则取 right）
5. 边界情况：
   - `t_rel_current < 第一个锚点`：用第一个锚点的 range
   - `t_rel_current > 最后一个锚点`：用最后一个锚点的 range

**TDD 流程：**

1. **RED**：写测试 `test_interp_cycle_bounds_between_anchors`
   - t_rel=200（在"主升浪加速" 180 和"繁荣过热中段" 365 之间）
   - 断言 level_lo/hi/mean 按比例插值，误差 < 0.01
   - 断言 phase_hint 为 "主升浪加速"（距离 180 更近）
2. **Verify RED**：运行测试，确认因方法未实现而失败
3. **GREEN**：实现 `_interp_cycle_bounds()`
4. **Verify GREEN**：运行测试通过
5. 补充边界测试：
   - `test_interp_cycle_bounds_before_first_anchor`：t_rel=-10，用第一个锚点
   - `test_interp_cycle_bounds_after_last_anchor`：t_rel=2000，用最后一个锚点
   - `test_interp_cycle_bounds_exact_anchor`：t_rel=480，正好命中"极端狂热顶"，无插值

**验证命令：**
```bash
cd 11-易经推理系统/scripts/memory_l4/bcrm2 && python -m pytest tests/test_cycle_bounds_interp.py -v
```

---

### T3：边界缓存 `_get_cycle_bounds()`（T_CB7）

**目标：** 进程内缓存边界参数，同日同 symbol 多次 predict 只计算 1 次。

**文件：** `11-易经推理系统/scripts/memory_l4/bcrm2/morph_cycle_predictor.py`

**函数签名：**

```python
_CYCLE_BOUNDS_CACHE: Dict[str, Tuple[float, Dict]] = {}  # symbol → (t_rel, bounds)

def _get_cycle_bounds(self, symbol: str, cycle_4y: Dict) -> Dict:
    """获取边界参数（带缓存）。

    若缓存中 t_rel 与当前一致，直接返回缓存；否则重新插值。
    """
```

**TDD 流程：**

1. **RED**：写测试 `test_cycle_bounds_cache_hit`
   - 第一次调用 `_get_cycle_bounds(symbol, cycle_4y)` → 返回 bounds
   - 第二次调用相同 symbol 和 cycle_4y → 返回相同 bounds
   - 断言 `_interp_cycle_bounds` 只被调用 1 次（用 spy 或计数器）
2. **Verify RED**：运行测试失败
3. **GREEN**：实现带缓存的 `_get_cycle_bounds()`
4. **Verify GREEN**：运行测试通过
5. 补充测试：
   - `test_cycle_bounds_cache_invalidation`：t_rel 变化时缓存失效，重新计算

**验证命令：**
```bash
cd 11-易经推理系统/scripts/memory_l4/bcrm2 && python -m pytest tests/test_cycle_bounds_cache.py -v
```

---

## 阶段 B：三类调整动作

### T4：FFT 振幅缩放（动作A，T_CB2）

**目标：** 小周期 FFT top-3 叠加后，若振幅超过 `amplitude_cap`，用 tanh 软缩放。

**文件：** `11-易经推理系统/scripts/memory_l4/bcrm2/morph_cycle_predictor.py`

**函数签名：**

```python
def _scale_fft_amplitude(self,
                          theoretical_full: np.ndarray,
                          bounds: Dict[str, Any]) -> Tuple[np.ndarray, Dict[str, Any]]:
    """对 FFT 叠加曲线应用大周期振幅约束。

    若 FFT 振幅 > amplitude_cap，用 tanh 软缩放（不硬截断）。

    返回：
      (scaled_theoretical, {"applied": bool, "scale_factor": float, "original_amp": float})
    """
```

**TDD 流程：**

1. **RED**：写测试 `test_fft_amplitude_scale_triggered`
   - 构造 FFT 曲线振幅 = 2.0，bounds.amplitude_cap = 0.75
   - 断言缩放后振幅 ≤ 0.75 × 1.1（允许 10% 容差）
   - 断言返回的 `applied == True`
2. **Verify RED**：运行测试失败
3. **GREEN**：实现 `_scale_fft_amplitude()`
4. **Verify GREEN**：运行测试通过
5. 补充测试：
   - `test_fft_amplitude_no_scale_when_within_bounds`：振幅 < cap 时不缩放，`applied == False`
   - `test_fft_amplitude_tanh_smoothness`：缩放后曲线平滑，无突变

**验证命令：**
```bash
cd 11-易经推理系统/scripts/memory_l4/bcrm2 && python -m pytest tests/test_cycle_bounds_fft_scale.py -v
```

---

### T5：预测曲线回拉（动作B，T_CB3）

**目标：** 对预测曲线每个点应用弹性边界，越界部分按 decay 比例回拉。

**文件：** `11-易经推理系统/scripts/memory_l4/bcrm2/morph_cycle_predictor.py`

**函数签名：**

```python
def _pullback_forecast(self,
                        forecast_vals: List[float],
                        bounds: Dict[str, Any]) -> Tuple[List[float], Dict[str, Any]]:
    """对预测曲线应用弹性边界回拉。

    对每个点 v：
      - v < level_lo → v = level_lo - (level_lo - v) × decay
      - v > level_hi → v = level_hi + (v - level_hi) × decay
      - 否则不变

    返回：
      (pulled_forecast, {"applied": bool, "overshoot_count": int})
    """
```

**TDD 流程：**

1. **RED**：写测试 `test_forecast_pullback_overshoot_up`
   - bounds = {level_lo: 3.5, level_hi: 4.0, decay_strength: 0.30}
   - forecast_vals = [4.5]（越上界 0.5）
   - 断言回拉后 = 4.0 + 0.5 × 0.30 = 4.15，误差 < 0.01
2. **Verify RED**：运行测试失败
3. **GREEN**：实现 `_pullback_forecast()`
4. **Verify GREEN**：运行测试通过
5. 补充测试：
   - `test_forecast_pullback_overshoot_down`：v=2.0，越下界 1.5，回拉后 = 3.5 - 1.5 × 0.30 = 3.05
   - `test_forecast_no_pullback_within_bounds`：v=3.8（在 [3.5, 4.0] 内），不回拉
   - `test_forecast_mixed_points`：混合越界和未越界点，只回拉越界点

**验证命令：**
```bash
cd 11-易经推理系统/scripts/memory_l4/bcrm2 && python -m pytest tests/test_cycle_bounds_pullback.py -v
```

---

### T6：越界信号检测（动作C，T_CB4）

**目标：** 检测现实曲线越界事件，记录但不调整值；连续越界 ≥ 5 天时标记需触发大调整。

**文件：** `11-易经推理系统/scripts/memory_l4/bcrm2/morph_cycle_predictor.py`

**函数签名：**

```python
def _check_overshoot_events(self,
                             level_hist: List[float],
                             dates: List[str],
                             bounds: Dict[str, Any]) -> List[Dict[str, Any]]:
    """检测现实曲线越界事件。

    现实曲线不调整，仅记录越界事件。
    若连续越界天数 ≥ CYCLE_BOUNDS_OVERSHOOT_TRIGGER (5)，
    最后一个事件标记 need_anchor_correct = True。

    返回：
      [{"date", "level", "bound", "direction", "magnitude", "need_anchor_correct"}, ...]
    """
```

**TDD 流程：**

1. **RED**：写测试 `test_overshoot_detection_single_event`
   - bounds = {level_lo: -0.4, level_hi: 0.4}
   - level_hist = [0.0, 0.5, 0.3]（第 2 天越上界 0.1）
   - 断言检测到 1 个越界事件，direction="up"，magnitude=0.1
   - 断言 need_anchor_correct == False（连续越界 < 5 天）
2. **Verify RED**：运行测试失败
3. **GREEN**：实现 `_check_overshoot_events()`
4. **Verify GREEN**：运行测试通过
5. 补充测试：
   - `test_overshoot_streak_triggers_anchor_correct`：连续 5 天越界，最后一个事件 `need_anchor_correct == True`
   - `test_overshoot_streak_broken_resets`：连续 4 天越界 + 1 天未越界 + 1 天越界，`need_anchor_correct == False`
   - `test_overshoot_no_events_within_bounds`：全部在边界内，返回空列表

**验证命令：**
```bash
cd 11-易经推理系统/scripts/memory_l4/bcrm2 && python -m pytest tests/test_cycle_bounds_overshoot.py -v
```

---

## 阶段 C：集成与联动

### T7：`predict()` 集成轨道三（T_CB6）

**目标：** 在 `predict()` 主流程中插入轨道三调用，应用边界约束。同时确保 `CYCLE_BOUNDS_ENABLED=False` 时字节等价。

**文件：** `11-易经推理系统/scripts/memory_l4/bcrm2/morph_cycle_predictor.py`

**集成点：** 在 `predict()` 方法的轨道一、轨道二之后，生成预测快照之前：

```python
def predict(self, symbol: str, hist_days: int = 60, forecast_days: int = 20) -> Dict:
    # ... 既有轨道二（大调整） ...
    # ... 既有轨道一（小修正） ...

    # 轨道三：大周期边界约束（NEW）
    cycle_bounds = None
    overshoot_events = []
    bounds_correction = {"applied": False}
    if CYCLE_BOUNDS_ENABLED:
        cycle_4y = cycle4y_theory(anchor_overrides=self.storage.get_anchor_state(symbol))
        bounds = self._get_cycle_bounds(symbol, cycle_4y)
        # 动作A：FFT 振幅缩放
        theoretical_full, fft_info = self._scale_fft_amplitude(theoretical_full, bounds)
        # 动作B：预测曲线回拉
        forecast_vals, pb_info = self._pullback_forecast(forecast_vals, bounds)
        # 动作C：越界信号检测
        overshoot_events = self._check_overshoot_events(level_hist, dates, bounds)
        cycle_bounds = bounds
        bounds_correction = {
            "applied": True,
            "fft": fft_info,
            "pullback": pb_info,
            "overshoot_count": len(overshoot_events),
        }

    # ... 生成预测快照 ...
    return {
        "series": {...},
        "cycle_bounds": cycle_bounds,
        "overshoot_events": overshoot_events,
        "correction": {..., "bounds": bounds_correction},
    }
```

**TDD 流程：**

1. **RED**：写测试 `test_predict_with_bounds_disabled_byte_equivalent`（T_CB6）
   - `CYCLE_BOUNDS_ENABLED = False`
   - 调用 `predict()` 两次：一次有边界约束代码，一次无（git stash）
   - 断言两次输出完全一致（字节等价）
2. **Verify RED**：运行测试失败（因 predict() 尚未集成轨道三）
3. **GREEN**：在 `predict()` 中插入轨道三代码，受 `CYCLE_BOUNDS_ENABLED` 开关控制
4. **Verify GREEN**：运行测试通过
5. 补充测试：
   - `test_predict_with_bounds_enabled_returns_cycle_bounds`：开启后返回 `cycle_bounds` 字段
   - `test_predict_with_bounds_enabled_returns_overshoot_events`：开启后返回 `overshoot_events` 字段

**验证命令：**
```bash
cd 11-易经推理系统/scripts/memory_l4/bcrm2 && python -m pytest tests/test_cycle_bounds_predict_integration.py -v
```

---

### T8：storage 扩展 `overshoot_hint` 字段

**目标：** 在 `morph_anchor_state` 表扩展 `overshoot_hint` 字段，存储越界触发提示。

**文件：** `11-易经推理系统/scripts/memory_l4/bcrm2/storage.py`

**实现内容：**

1. `morph_anchor_state` 表新增 `overshoot_hint TEXT` 字段（JSON: `{reason, streak, detected_at}`）
2. 新增 `save_anchor_hint(symbol, reason, streak)` 方法
3. 新增 `get_anchor_hint(symbol)` 方法
4. 数据库迁移：`ALTER TABLE morph_anchor_state ADD COLUMN overshoot_hint TEXT`

**TDD 流程：**

1. **RED**：写测试 `test_save_and_get_anchor_hint`
   - 调用 `save_anchor_hint("BTCUSDT", "overshoot_streak", 5)`
   - 调用 `get_anchor_hint("BTCUSDT")`
   - 断言返回 `{reason: "overshoot_streak", streak: 5, detected_at: <非空>}`
2. **Verify RED**：运行测试失败
3. **GREEN**：实现表扩展和 CRUD 方法
4. **Verify GREEN**：运行测试通过
5. 补充测试：
   - `test_anchor_hint_overwrites_previous`：多次保存，后者覆盖前者
   - `test_anchor_hint_returns_none_when_not_set`：未保存时返回 None

**验证命令：**
```bash
cd 11-易经推理系统/scripts/memory_l4/bcrm2 && python -m pytest tests/test_cycle_bounds_storage_hint.py -v
```

---

### T9：`_maybe_anchor_correct` 读取 hint 降冷却（T_CB5）

**目标：** 当检测到 `overshoot_hint` 时，将大调整冷却从 72h 降至 24h。

**文件：** `11-易经推理系统/scripts/memory_l4/bcrm2/morph_cycle_predictor.py`

**实现内容：**

在 `_maybe_anchor_correct()` 方法的冷却判断中，读取 `overshoot_hint`：

```python
def _maybe_anchor_correct(self, symbol: str) -> Optional[Dict]:
    # 读取越界提示
    hint = self.storage.get_anchor_hint(symbol)
    cooldown_hours = ANCHOR_SWITCH_COOLDOWN_HOURS  # 默认 72h
    if hint and hint.get("reason") == "overshoot_streak":
        cooldown_hours = 24  # 降至 24h

    # ... 既有冷却判断逻辑，使用 cooldown_hours ...
```

**TDD 流程：**

1. **RED**：写测试 `test_anchor_correct_cooldown_reduced_by_overshoot`（T_CB5）
   - 保存 `overshoot_hint`（streak=5）
   - 模拟上次大调整在 30 小时前（超过 24h 但不足 72h）
   - 调用 `_maybe_anchor_correct()`
   - 断言大调整被触发（因冷却降至 24h）
2. **Verify RED**：运行测试失败
3. **GREEN**：在 `_maybe_anchor_correct()` 中读取 hint 并调整冷却
4. **Verify GREEN**：运行测试通过
5. 补充测试：
   - `test_anchor_correct_normal_cooldown_without_hint`：无 hint 时，30 小时前的大调整不触发（不足 72h）
   - `test_anchor_correct_hint_consumed_after_trigger`：大调整触发后，hint 被清除

**验证命令：**
```bash
cd 11-易经推理系统/scripts/memory_l4/bcrm2 && python -m pytest tests/test_cycle_bounds_anchor_hint_cooldown.py -v
```

---

## 阶段 D：API 与回测

### T10：新增 API `/api/morph/cycle_bounds`

**目标：** 新增 API 供前端单独查询大周期对小周期的弹性边界参数。

**文件：** `11-易经推理系统/data_server_fixed.py`

**实现内容：**

```python
@app.route("/api/morph/cycle_bounds", methods=["GET"])
def get_cycle_bounds(symbol: str = "BTCUSDT"):
    """返回大周期对小周期的弹性边界参数。"""
    cycle_4y = cycle4y_theory(today=None, samples=365,
                              anchor_overrides=storage.get_anchor_state(symbol))
    bounds = predictor._interp_cycle_bounds(cycle_4y["t_rel_current"])
    return {"ok": True, "symbol": symbol, "cycle_4y": cycle_4y, "bounds": bounds}
```

**TDD 流程：**

1. **RED**：写测试 `test_api_cycle_bounds_returns_valid_response`
   - GET `/api/morph/cycle_bounds?symbol=BTCUSDT`
   - 断言 `ok == True`
   - 断言 `bounds` 包含 level_lo/hi/mean/amplitude_cap/decay_strength/phase_hint
2. **Verify RED**：运行测试失败（API 未定义）
3. **GREEN**：实现 API 路由
4. **Verify GREEN**：运行测试通过

**验证命令：**
```bash
cd 11-易经推理系统 && python -m pytest tests/test_api_cycle_bounds.py -v
```

---

### T11：WalkForward 回测验证

**目标：** 对比开启/关闭边界约束的预测精度，验证边界约束是否提升预测质量。

**文件：** `11-易经推理系统/scripts/memory_l4/bcrm2/eval_walkforward.py`（新建或扩展）

**回测方案：**

1. 基线 A：`CYCLE_BOUNDS_ENABLED = False`（关闭边界约束）
2. 基线 B：`CYCLE_BOUNDS_ENABLED = True`（开启边界约束）
3. 回测周期：过去 90 天，每日 predict 并记录误差
4. 对比指标：
   - MAE（平均绝对误差）
   - RMSE（均方根误差）
   - 方向准确率
5. 通过标准：基线 B 的 MAE 比基线 A 降低 ≥ 5%（否则不 promote）

**TDD 流程：**

1. **RED**：写测试 `test_walkforward_baseline_comparison`
   - 运行 90 天回测，分别开启/关闭边界约束
   - 断言生成对比报告，包含 MAE/RMSE/方向准确率
2. **Verify RED**：运行测试失败
3. **GREEN**：实现回测脚本
4. **Verify GREEN**：运行测试通过
5. 实际回测运行：
   ```bash
   cd 11-易经推理系统/scripts/memory_l4/bcrm2 && python eval_walkforward.py --days 90 --compare-bounds
   ```

**验证命令：**
```bash
cd 11-易经推理系统/scripts/memory_l4/bcrm2 && python -m pytest tests/test_walkforward_bounds.py -v
```

---

## 验收清单

### 单元测试（T_CB1-T_CB7）

| 测试 ID | 对应任务 | 通过标准 |
|---|---|---|
| T_CB1 | T2 | t_rel 在两锚点间时，level_lo/hi 按位置比例插值，误差 < 0.01 |
| T_CB2 | T4 | FFT 振幅 > amplitude_cap 时被软缩放，缩放后振幅 ≤ amplitude_cap × 1.1 |
| T_CB3 | T5 | 预测值越界时被回拉，回拉后值 = clip + overshoot × decay，误差 < 0.01 |
| T_CB4 | T6 | 现实曲线原样输出，越界事件被记录但不调整值 |
| T_CB5 | T9 | 连续越界 ≥ 5 天时写入 overshoot_hint，下次 _maybe_anchor_correct 冷却降至 24h |
| T_CB6 | T7 | CYCLE_BOUNDS_ENABLED=False 时，predict() 输出与无边界约束时完全一致 |
| T_CB7 | T3 | 同日同 symbol 多次 predict，_interp_cycle_bounds 只计算 1 次 |

### 集成验收

- [ ] 所有 T_CB1-T_CB7 单测通过
- [ ] `predict()` 返回结构包含 `cycle_bounds` 和 `overshoot_events` 字段
- [ ] `CYCLE_BOUNDS_ENABLED=False` 时 CLI 默认字节等价
- [ ] WalkForward 回测：开启边界约束后 MAE 降低 ≥ 5%
- [ ] 新增 API `/api/morph/cycle_bounds` 可正常调用

### 硬约束兼容性

- [ ] CLI 默认字节等价（`CYCLE_BOUNDS_ENABLED=False`）
- [ ] 无偏不变量（边界关闭时等价 Phase 0）
- [ ] 双基线 AB 对比（轨道三走 shadow → promote 流程）
- [ ] 三层架构（边界约束在 Phase A 前置层，不触及 BCRM 2.0 核心层）

---

## 执行顺序与里程碑

| 里程碑 | 完成任务 | 交付物 |
|---|---|---|
| M1：核心插值可用 | T1, T2, T3 | 边界参数可从大周期 t_rel 推导 |
| M2：三类动作可用 | T4, T5, T6 | FFT缩放/预测回拉/越界检测 |
| M3：predict() 集成完成 | T7, T8, T9 | 4 条曲线 + 边界参数 + 越界事件 |
| M4：API 与回测 | T10, T11 | API 可用 + 回测验证报告 |

---

## 附录：文件变更清单

| 文件 | 变更类型 | 任务 |
|---|---|---|
| `11-易经推理系统/scripts/memory_l4/bcrm2/morph_cycle_predictor.py` | 修改 | T1-T7, T9 |
| `11-易经推理系统/scripts/memory_l4/bcrm2/storage.py` | 修改 | T8 |
| `11-易经推理系统/data_server_fixed.py` | 修改 | T10 |
| `11-易经推理系统/scripts/memory_l4/bcrm2/eval_walkforward.py` | 新建/扩展 | T11 |
| `11-易经推理系统/scripts/memory_l4/bcrm2/tests/test_cycle_bounds_*.py` | 新建 | T1-T11 |
