# QMM Phase 3 — V3 仓库 + ML 训练闭环设计

**日期**: 2026-05-13
**范围**: V3 独立仓库（从 V2 复制构建）
**新增依赖**: `numpy` / `scikit-learn` / `scipy`（可选）
**状态**: Phase B 备选（仅当 V5 原型回测失败时启动）
**收敛策略**: 如果 V5 原型胜率 >55%，跳过此阶段直接引入 V5 ML 组件

---

## 一、前提条件

Phase 3 仅在以下条件满足后启动：

1. **Phase 1+2 已完成**：V2 中确定性基线稳定运行
2. **回测门禁通过**：确定性基线在多个 regime 上稳定胜过简单策略
3. **数据量充足**：至少 50+ TradeCase，覆盖 3+ regime
4. **V3 仓库已创建**：从 V2 完整复制，建立独立 CI/CD

---

## 二、V3 仓库定位

```
V2 (dream-multiskill-v2)                    V3 (独立仓库)
───────────────────────────                 ────────────────
确定性基线 (Phase 1+2)                      ML 训练闭环 (Phase 3)
- 纯 math/statistics                        - numpy/sklearn/scipy
- 等权 1/N                                  - 学习型权重
- 无随机性                                  - 固定 random_state
- 作为稳定基线保留                          - 探索性研究分支

V3 是 V2 的超集：保留所有确定性能力，ML 组件仅在确定性基线之上做增量。
ML 组件可开关，不启用时退化为 V2 确定性行为。
```

---

## 三、新增能力

### 3.1 MemoryTrainer — ML 训练器

**仅在确定性基线被证明优于简单策略后引入**。

```python
class MemoryTrainer:
    """基于历史 TradeCase 训练方向预测模型。

    特征:
    - quadrant_x, quadrant_y
    - pnl_pct, severity
    - stage_coverage (A0-A9 覆盖数)
    - regime (one-hot)
    - time_decay

    标签:
    - direction (UP if pnl_pct > 0 else DOWN)

    模型:
    - GradientBoostingClassifier (可解释性强)
    - 或 RandomForestClassifier (鲁棒性好)
    """
    def __init__(self, model_type: str = "gradient_boosting", random_state: int = 42):
        self.random_state = random_state  # 固定种子保证可复现
        self.model = None

    def train(self, X_train, y_train) -> Dict:
        """训练并返回训练指标。"""
        # 固定 random_state
        self.model = GradientBoostingClassifier(
            n_estimators=100,
            max_depth=3,  # 限制深度防止过拟合
            learning_rate=0.1,
            random_state=self.random_state,
        )
        self.model.fit(X_train, y_train)
        return {
            "train_accuracy": self.model.score(X_train, y_train),
            "feature_importances": dict(zip(feature_names, self.model.feature_importances_)),
        }
```

**约束遵守**：
- 所有 ML 模型固定 `random_state` 保证可复现（约束 0.5）
- 模型权重随产物存储，支持再生（约束 0.5）
- ML 输出与确定性基线并行输出，取优者（约束 0.3）

### 3.2 过拟合检测 — 增强版

```python
class OverfittingDetector:
    """增强过拟合检测（ML 场景）。"""

    def deflated_sharpe_ratio(self, sharpe: float, n_trades: int,
                              n_strategies: int) -> float:
        """Bailey-Lopez de Prado Deflated Sharpe Ratio.

        考虑多重测试偏差:
        DSR = Sharpe * sqrt(N) / sqrt(1 - skewness*Sharpe/sqrt(N-1)
                                     + (kurtosis-1)*Sharpe^2/(4*(N-1)))
        简化版:
        DSR = Sharpe * sqrt(1 / (1 + (n_strategies - 1) / n_trades))
        """
        penalty = math.sqrt(1.0 / (1.0 + (n_strategies - 1) / max(n_trades, 1)))
        return round(sharpe * penalty, 4)

    def complexity_penalty(self, n_features: int, n_samples: int) -> float:
        """复杂度惩罚 = 1 - (n_features / sqrt(n_samples))。

        如果 n_features > sqrt(n_samples)，惩罚为负 → 过参数化。
        """
        return round(1.0 - n_features / math.sqrt(max(n_samples, 1)), 4)
```

### 3.3 漂移监控 — 增强版

```python
class DriftMonitor:
    """增强漂移监控（ML 场景）。"""

    def concept_drift_test(self, recent_data: np.ndarray,
                           baseline_data: np.ndarray) -> Dict:
        """Mann-Whitney U 检验检测概念漂移。"""
        if len(recent_data) < 10 or len(baseline_data) < 10:
            return {"status": "INSUFFICIENT_DATA"}

        from scipy.stats import mannwhitneyu
        stat, p_value = mannwhitneyu(recent_data, baseline_data, alternative='two-sided')

        if p_value < 0.05:
            return {
                "status": "CONCEPT_DRIFT_DETECTED",
                "p_value": round(float(p_value), 6),
                "recommendation": "RETRAIN_MODEL",
            }
        return {"status": "NO_DRIFT", "p_value": round(float(p_value), 4)}

    def feature_drift(self, current_features: np.ndarray,
                      baseline_features: np.ndarray) -> Dict[str, float]:
        """逐特征 PSI 检测。"""
        # 将连续特征分箱后计算 PSI
        ...
```

### 3.4 VectorSpace 在线路径

```python
class VectorSpaceOnline:
    """VectorSpace 在线路径（预计算 + 缓存）。

    离线阶段:
    1. 对所有 TradeCase 运行 kmeans 聚类
    2. 将 cluster assignment 和 center 写入 JSON 缓存

    在线阶段:
    1. 新 case 到达时，计算到各 center 的距离
    2. 分配到最近 cluster
    3. 返回 cluster 内的历史案例作为相似案例
    """
    def __init__(self, cache_path: Path):
        self.cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}

    def find_similar(self, new_case: Dict, top_k: int = 5) -> List[str]:
        """在线查找相似案例（无需 kmeans）。"""
        # 计算到各 cluster center 的距离
        distances = []
        for cid, center in self.cache.get("centers", {}).items():
            dist = self._euclidean(new_case, center)
            distances.append((cid, dist))
        distances.sort(key=lambda x: x[1])

        # 返回最近 cluster 中的案例
        nearest_cluster = distances[0][0] if distances else None
        if nearest_cluster:
            return self.cache.get("clusters", {}).get(nearest_cluster, [])[:top_k]
        return []
```

**约束遵守**：
- VectorSpace 在线路径使用预计算缓存，不运行 kmeans（约束 0.8）
- 离线聚类可配置，默认 10 clusters
- 在线查找为纯距离计算，无随机性

---

## 四、ML 组件开关设计

```python
@dataclass
class QMMConfig:
    ml_enabled: bool = False           # ML 组件开关
    ml_model_type: str = "gradient_boosting"
    ml_random_state: int = 42
    fallback_to_deterministic: bool = True  # ML 失败时降级到确定性基线

def run_qmm_v3(cases, distills, config: QMMConfig = QMMConfig()):
    """QMM V3 入口（V2 的超集）。"""
    # 1. 确定性基线（总是运行）
    det_result = run_qmm_deterministic(cases, distills)  # V2 逻辑

    if not config.ml_enabled:
        return det_result  # 退化到 V2

    # 2. ML 预测（可选）
    try:
        ml_result = run_qmm_ml(cases, distills, config)
    except Exception:
        if config.fallback_to_deterministic:
            return det_result  # ML 失败 → 降级到确定性
        raise

    # 3. 选择更优结果（回测证明）
    if ml_result.get("backtest_accuracy", 0) > det_result.get("backtest_accuracy", 0):
        return ml_result
    return det_result
```

---

## 五、验收标准

| 标准 | 要求 |
|------|------|
| ML 可开关 | ml_enabled=False 时退化为 V2 确定性行为 |
| 可复现 | 所有 ML 模型固定 random_state |
| 漂移冻结 | 漂移检测触发后自动冻结 ML 输出 |
| 降级安全 | ML 失败时降级到确定性基线 |
| 增量收益 | ML 准确率必须 > 确定性基线才使用 |
| 独立仓库 | V3 与 V2 完全解耦 |
