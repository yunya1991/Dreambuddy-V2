# QMM Phase 2 — 在线门禁设计

**日期**: 2026-05-13
**范围**: V2 仓库 (dream-multiskill-v2)
**依赖**: `math` / `statistics`（零外部依赖）
**执行优先级**: Phase A P1（保守线 — V2 在线门禁，Phase 1 完成后启动）

---

## 一、目标

在 Phase 1 离线内核基础上，增加回测门禁能力，使 QMM 产出可通过验证后供 A 系列消费。

- **回测验证**：walk-forward 证明 QMM 信号增量收益
- **过拟合检测**：train/test gap 检测
- **漂移监控**：PSI + 性能漂移
- **A 系列消费**：通过门禁的信号可被 A 系列 entrypoint 可选加载

---

## 二、回测框架

### 2.1 Walk-Forward 验证

```
事件序列: [e1, e2, e3, ..., eN]  (按 ts_start 排序)

Fold 1: train=[e1..e10], test=[e11..e15]
Fold 2: train=[e1..e15], test=[e16..e20]
...
Fold M: train=[e1..e(N-k)], test=[e(N-k+1)..eN]

每个 fold:
  1. 从 train 计算基线统计（regime 分布、象限中心、方向比例）
  2. 对 test 中每个事件，用 QMM 预测方向（基于 train 基线）
  3. 与实际 pnl 方向对比，计算准确率

聚合:
  - 总准确率 = 所有 fold 正确预测数 / 总预测数
  - 各 regime 准确率 = 按 regime 分组的准确率
  - 高置信度子集准确率 = uncertainty < 0.3 的子集准确率
```

### 2.2 实现设计

```python
class Backtester:
    def __init__(self, n_folds: int = 5, min_train: int = 10, min_test: int = 5):
        self.n_folds = n_folds
        self.min_train = min_train
        self.min_test = min_test

    def run(self, events: List[CleanedEvent]) -> BacktestResult:
        """执行 walk-forward 回测。"""
        folds = self._split_folds(events)
        fold_results = []

        for train, test in folds:
            # 从 train 计算基线
            baseline = self._compute_baseline(train)

            # 对 test 中每个事件预测方向
            predictions = []
            for ev in test:
                pred = self._predict_direction(ev, baseline)
                predictions.append({
                    "event_id": ev.event_id,
                    "predicted_direction": pred,
                    "actual_direction": "UP" if ev.pnl_pct and ev.pnl_pct > 0 else "DOWN",
                    "correct": pred == ("UP" if ev.pnl_pct and ev.pnl_pct > 0 else "DOWN"),
                })

            fold_acc = sum(1 for p in predictions if p["correct"]) / max(len(predictions), 1)
            fold_results.append({
                "fold_accuracy": round(fold_acc, 4),
                "predictions": predictions,
            })

        # 聚合
        all_correct = sum(
            sum(1 for p in fr["predictions"] if p["correct"])
            for fr in fold_results
        )
        all_total = sum(len(fr["predictions"]) for fr in fold_results)

        return BacktestResult(
            total_predictions=all_total,
            overall_accuracy=round(all_correct / max(all_total, 1), 4),
            fold_accuracies=[fr["fold_accuracy"] for fr in fold_results],
            train_test_gap=self._compute_gap(fold_results),
            by_regime=self._compute_by_regime(fold_results),
        )

    def _predict_direction(self, event: CleanedEvent, baseline: Dict) -> str:
        """基于基线的简单预测（确定性方法）。"""
        # 策略：如果事件 regime 与基线主导 regime 一致，用基线方向
        # 否则用事件自身的 quadrant x 方向
        if event.regime == baseline.get("dominant_regime"):
            return baseline.get("dominant_direction", "FLAT")
        return "UP" if event.quadrant_x > 0 else ("DOWN" if event.quadrant_x < 0 else "FLAT")
```

### 2.3 门禁通过条件

| 指标 | 阈值 | 说明 |
|------|------|------|
| 方向预测准确率 | > 55% | 优于随机 (50%) |
| 高置信度子集准确率 | > 65% | uncertainty < 0.3 的子集 |
| 跨 regime 准确率 | > 50% 每个 regime | 不在单一 regime 过拟合 |
| train/test gap | < 10% | 无显著过拟合 |

---

## 三、过拟合检测

### 3.1 实现设计

```python
def detect_overfitting(backtest_result: BacktestResult) -> OverfitReport:
    """过拟合检测。

    检查:
    1. train/test gap > 10% → 过拟合
    2. fold 间方差大 → 不稳定
    3. 单一 regime 准确率远高于其他 → regime 过拟合
    """
    gap = backtest_result.train_test_gap
    fold_var = statistics.variance(backtest_result.fold_accuracies) if len(backtest_result.fold_accuracies) >= 2 else 0

    # Regime 过拟合检测
    regime_max_gap = 0
    for reg, accs in backtest_result.by_regime.items():
        if accs and len(accs) >= 2:
            reg_gap = max(accs) - min(accs)
            regime_max_gap = max(regime_max_gap, reg_gap)

    is_overfit = gap > 0.10 or fold_var > 0.01 or regime_max_gap > 0.30

    return OverfitReport(
        is_overfit=is_overfit,
        train_test_gap=round(gap, 4),
        fold_variance=round(fold_var, 6),
        regime_max_gap=round(regime_max_gap, 4),
        recommendation="SIMPLIFY" if is_overfit else "ACCEPT",
    )
```

---

## 四、漂移监控

### 4.1 PSI (Population Stability Index)

```python
def compute_psi(expected_dist: Dict[str, float],
                actual_dist: Dict[str, float]) -> float:
    """PSI = Σ (actual_i - expected_i) * ln(actual_i / expected_i)

    解释:
    - PSI < 0.1: 无显著变化
    - 0.1 <= PSI < 0.2: 中度变化
    - PSI >= 0.2: 显著变化 → 漂移检测
    """
    psi = 0.0
    all_keys = set(expected_dist.keys()) | set(actual_dist.keys())
    for key in all_keys:
        expected = expected_dist.get(key, 0.001)  # 平滑
        actual = actual_dist.get(key, 0.001)
        psi += (actual - expected) * math.log(actual / expected)
    return round(max(0, psi), 4)
```

### 4.2 性能漂移

```python
def detect_performance_drift(recent_pnls: List[float],
                             baseline_mean: float,
                             baseline_std: float) -> float:
    """Z-score of recent mean vs baseline."""
    if not recent_pnls or baseline_std == 0:
        return 0.0
    recent_mean = statistics.mean(recent_pnls)
    z_score = abs(recent_mean - baseline_mean) / baseline_std
    return round(z_score, 4)
```

### 4.3 漂移报告

```python
def check_drift(events: List[CleanedEvent],
                baseline_stats: Dict) -> DriftReport:
    """综合漂移检查。"""
    # 分布漂移 (象限分布 PSI)
    current_x_dist = _bin_quadrant_x(events)
    psi_x = compute_psi(baseline_stats.get("x_distribution", {}), current_x_dist)

    # 性能漂移
    recent = events[-10:] if len(events) >= 10 else events
    recent_pnls = [e.pnl_pct for e in recent if e.pnl_pct is not None]
    perf_drift = detect_performance_drift(
        recent_pnls,
        baseline_stats.get("pnl_mean", 0),
        baseline_stats.get("pnl_std", 1),
    )

    # 综合判断
    drift_detected = psi_x >= 0.2 or perf_drift >= 2.0

    return DriftReport(
        drift_detected=drift_detected,
        drift_type="DISTRIBUTION" if psi_x >= 0.2 else ("PERFORMANCE" if perf_drift >= 2.0 else "NONE"),
        severity=round(max(psi_x / 0.2, perf_drift / 2.0), 4),
        psi_x=psi_x,
        performance_drift=perf_drift,
        recommendation="RECALIBRATE" if drift_detected else "NO_ACTION",
    )
```

---

## 五、A 系列消费模式

### 5.1 消费协议

A 系列 entrypoint 中可选加载 QMM 信号：

```python
def _load_qmm_signals(regime: Optional[str] = None) -> Optional[Dict]:
    """加载 QMM 信号（可选，不阻塞）。

    条件:
    1. signals_index.json 存在
    2. gate_status == "PASSED"
    3. 否则返回 None (fail-closed)
    """
    try:
        signals_path = qmm_dir() / "signals_index.json"
        if not signals_path.exists():
            return None
        data = json.loads(signals_path.read_text())
        if data.get("gate_status") != "PASSED":
            return None
        return data
    except Exception:
        return None
```

### 5.2 A 系列使用示例

```python
# A3_simulation/entrypoint.py 中的可选增强
def _pick_strategy_mode(signal_score, volatility, market_regime):
    # 原有逻辑...
    mode = "trend_follow" if signal_score >= 60 else "mean_revert"

    # QMM 增强（可选）
    qmm = _load_qmm_signals(market_regime)
    if qmm:
        # 如果 QMM 趋势状态与当前策略不一致，降低置信度
        if qmm.get("trend_state") == "DOWN" and mode == "trend_follow":
            confidence = max(0.5, confidence - 0.2)  # 降低但不下调至零

    return mode
```

**关键原则**：
- QMM 信号仅作为参考，不替换现有决策逻辑
- 未通过门禁的信号不被消费
- A 系列 entrypoint 不强制依赖 QMM

---

## 六、门禁输出

```python
@dataclass
class GateResult:
    backtest: BacktestResult
    overfitting: OverfitReport
    drift: DriftReport
    passed: bool
    reason_codes: List[str]

def run_gate(events: List[CleanedEvent],
           baseline_stats: Dict) -> GateResult:
    """执行完整门禁检查。"""
    bt = Backtester().run(events)
    of = detect_overfitting(bt)
    dr = check_drift(events, baseline_stats)

    passed = (
        bt.overall_accuracy > 0.55 and
        not of.is_overfit and
        not dr.drift_detected
    )

    reason_codes = []
    if bt.overall_accuracy <= 0.55:
        reason_codes.append("LOW_ACCURACY")
    if of.is_overfit:
        reason_codes.append("OVERFITTING_DETECTED")
    if dr.drift_detected:
        reason_codes.append("DRIFT_DETECTED")

    return GateResult(
        backtest=bt,
        overfitting=of,
        drift=dr,
        passed=passed,
        reason_codes=reason_codes,
    )
```

门禁结果写入 `signals_index.json` 的 `gate_status` 和 `gate_results` 字段。

---

## 七、验收标准

| 标准 | 要求 |
|------|------|
| walk-forward 可执行 | 至少 5 folds，每 fold train/test 有足够数据 |
| 门禁判断正确 | 准确率 < 55% → FAILED, > 55% + 无过拟合 → PASSED |
| 漂移检测触发 | PSI >= 0.2 或 Z-score >= 2.0 → 漂移 |
| A 系列安全消费 | gate_status != PASSED 时返回 None |
| 零外部依赖 | 纯 math/statistics |
| 可复现 | 相同输入相同输出 |
