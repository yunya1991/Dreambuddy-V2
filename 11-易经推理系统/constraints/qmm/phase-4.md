# QMM Phase 4 — V4 仓库 + QMM V2 内核设计

**日期**: 2026-05-13
**范围**: V4 独立仓库（从 V3 复制构建）
**依赖**: 完整 ML 栈 + 表征学习 + 知识图谱
**状态**: Phase B 备选（仅当保守路线被选中时，作为远期目标）
**收敛策略**: 走激进路线时此文档降级为历史参考

---

## 一、前提条件

Phase 4 仅在以下条件满足后启动：

1. **Phase 3 已完成**：V3 中 ML 训练闭环稳定运行
2. **ML 持续优于确定性基线**：连续 3 个回测周期 ML 准确率 > 确定性基线
3. **V4 仓库已创建**：从 V3 完整复制，建立独立 CI/CD
4. **数据量充足**：至少 200+ TradeCase，覆盖 5+ regime，跨 2+ 市场

---

## 二、V4 仓库定位

```
V2 (dream-multiskill-v2)          V3 (独立仓库)              V4 (独立仓库)
────────────────────────          ─────────────              ─────────────
确定性基线                        ML 训练闭环                QMM V2 完整内核
- Phase 1+2                      - Phase 3                   - Phase 4
- 保守基线保留                   - ML 探索分支保留           - 生产级量化内核

V4 是最终形态:
- L4 认知层 + QMM 量化层完整融合
- L4 数学公式全部由 QMM 驱动
- 支持跨市场迁移学习
- 完整的训练→验证→部署→监控闭环
```

---

## 三、新增能力

### 3.1 QMM V2 内核 — 替代 L4 静态公式

V4 中 QMM 不再只是 Sidecar，而是成为 L4 的量化驱动内核：

| L4 现有静态公式 | QMM V2 动态替代 |
|-----------------|-----------------|
| x = clamp(pnl/5.0, -1, 1) | 波动率调整的象限计算: x = clamp(pnl / (vol * scale), -1, 1) |
| y = 0.4*y_perf + 0.4*y_consistency + 0.2*y_human | 基于回测的动态权重: y = f(regime, data_quality, recency) |
| similarity: 0.4/0.4/0.2 固定权重 | 基于 regime 的自适应权重 |
| pattern_maturity: 0.35/0.25/0.25/0.15 | 基于历史回测的动态权重 |
| evolution_metrics: 简单增长率 | 时间序列建模 (ARIMA/ETS) |

**迁移策略**：
- 逐步替换，每次替换一个公式
- 每次替换后必须通过回测门禁（约束 0.4）
- 旧公式保留为降级路径
- 版本三元组记录哪个公式版本生效

### 3.2 表征学习 — 记忆向量

```python
class MemoryEmbedder:
    """将 TradeCase 编码为向量表征。

    方法:
    1. 从 TradeCase 提取结构化特征 (quadrant, pnl, regime, stages, tags)
    2. 使用训练好的编码器 (如 autoencoder) 映射到低维向量
    3. 向量用于: 相似性检索、聚类、模式识别

    注意: 这是真正的 embedding，不同于 Phase 1 的简单特征列表。
    """
    def __init__(self, model_path: Path, dim: int = 32):
        self.dim = dim
        self.model = self._load_model(model_path)

    def encode(self, case: Dict) -> np.ndarray:
        """编码单个 TradeCase 为向量。"""
        features = self._extract_features(case)
        return self.model.encode(features)

    def batch_encode(self, cases: List[Dict]) -> np.ndarray:
        """批量编码。"""
        return np.array([self.encode(c) for c in cases])
```

**约束遵守**：
- Embedding 模型固定 random_state（约束 0.5）
- 向量仅用于离线研究和召回辅助（约束 0.8）
- 在线路径使用预计算向量 + 最近邻查找

### 3.3 学习型权重

```python
class AdaptiveWeightOptimizer:
    """基于回测的自适应权重学习。

    方法:
    1. 定义候选权重空间 (grid search or Bayesian optimization)
    2. 对每组权重运行 walk-forward 回测
    3. 选择最优权重
    4. 定期重优化（应对漂移）
    """
    def optimize(self, cases: List[Dict], param_space: Dict) -> Dict:
        """搜索最优权重。"""
        best_score = -1
        best_params = None

        for params in self._iterate_params(param_space):
            score = self._evaluate_params(cases, params)
            if score > best_score:
                best_score = score
                best_params = params

        return best_params
```

**约束遵守**：
- 学习型权重必须通过回测门禁（约束 0.3/0.4）
- 未通过门禁时使用等权 1/N 基线
- 权重版本纳入版本三元组（约束 0.6）

### 3.4 知识图谱 — 跨市场模式关联

```python
class MemoryKnowledgeGraph:
    """构建记忆知识图谱。

    节点:
    - TradeCase (交易案例)
    - Regime (市场状态)
    - Pattern (模式, 来自聚类)
    - Distill (蒸馏记录)

    边:
    - similar_to (相似案例)
    - same_regime (同一市场状态)
    - same_cluster (同一聚类)
    - supports (支持某蒸馏)
    - contradicts (矛盾案例)

    用途:
    - 跨市场模式迁移
    - 矛盾案例发现
    - 知识推理
    """
    def build(self, cases: List[Dict], distills: List[Dict]) -> Dict:
        """构建知识图谱。"""
        nodes = self._build_nodes(cases, distills)
        edges = self._build_edges(cases, distills)
        return {"nodes": nodes, "edges": edges}

    def query_patterns(self, regime: str) -> List[Dict]:
        """查询某 regime 下的模式。"""
        ...
```

---

## 四、完整训练→验证→部署→监控闭环

```
训练 (Training)
    ↓
    从历史 TradeCase 训练 Embedder + Weight Optimizer
    ↓
验证 (Validation)
    ↓
    Walk-Forward 回测 + DSR + 交叉验证
    ↓
门禁 (Gate)
    ↓
    满足条件 → 部署到线上
    不满足 → 回退到确定性基线
    ↓
部署 (Deployment)
    ↓
    QMM V2 替代 L4 静态公式，驱动量化计算
    ↓
监控 (Monitoring)
    ↓
    PSI + 概念漂移 + 性能漂移
    ↓
触发 (Trigger)
    ↓
    漂移检测 → 冻结线上模型 → 触发重训练
    ↓
    回到 训练 步骤
```

---

## 五、与 V2/V3 的关系

| 仓库 | 角色 | 进化状态 |
|------|------|----------|
| V2 | 保守基线 | Phase 1+2 完成后停止进化 |
| V3 | ML 探索分支 | Phase 3 完成后停止进化 |
| V4 | 生产级内核 | 持续进化 |

V2 和 V3 作为历史基线保留，V4 从 V3 复制后独立演进。

---

## 六、验收标准

| 标准 | 要求 |
|------|------|
| L4 数学公式全部 QMM 驱动 | 无硬编码静态公式 |
| 跨市场迁移 | 支持 2+ 市场的模式迁移 |
| 完整闭环 | 训练→验证→部署→监控→重训练自动化 |
| 降级安全 | 所有 ML 组件有确定性降级路径 |
| 独立仓库 | V4 与 V2/V3 完全解耦 |
| 版本可追溯 | 版本三元组记录每个公式/模型版本 |
