"""
CausalEngine — 因果推断引擎（非 LLM·数据驱动）

蓝本：causalml（Uber）+ NOTEARS 因果结构学习
核心思想：区分因果关系 vs 虚假关联（相关≠因果）

核心能力：
  1. learn_dag          — NOTEARS 学习变量间因果 DAG
  2. estimate_ate       — DML/元学习器估计平均处理效应（ATE）
  3. estimate_cate      — 异质性处理效应（CATE），条件于特征
  4. detect_spurious    — 虚假关联检测（混淆变量导致的伪相关）
  5. causal_influence   — 变量间因果影响力评分

依赖降级：
  - causalml 可用 → DML/S/X/T/R-learner 估计 ATE/CATE
  - causalml 不可用 → 线性回归 + 偏相关分析降级
  - networkx 用于 DAG 可视化与拓扑排序

硬约束：
  - HC-AGI-02: 异常→中性兜底（sharpe=0, conf=0.5, action=HOLD）
  - HC-AGI-08: 因果引擎最小样本量≥500

FAIL-OPEN：任何步骤异常 → 返回空/保守结果，不 crash。
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)

# causalml 惰性导入标志（避免 eager import 触发 shap→cv2 段错误）
_CAUSALML_AVAILABLE: bool | None = None
_CAUSALML_MODELS = None  # 缓存 {LRS, BaseT, XGBT}

# networkx 惰性导入标志
_NX_AVAILABLE: bool | None = None

# A3: 样本不足告警去重 — 同一 key 只告警一次，避免热路径刷屏
# (路径数 << MIN_SAMPLES 时 estimate_ate/learn_dag 每次调用都会命中该分支)
_INSUFFICIENT_WARNED: set[str] = set()


def _warn_insufficient_once(key: str, msg: str, *args: Any) -> None:
    """[HC-AGI-08] 样本不足告警去重：首次 WARNING，后续降级为 DEBUG."""
    if key in _INSUFFICIENT_WARNED:
        logger.debug(msg, *args)
        return
    _INSUFFICIENT_WARNED.add(key)
    logger.warning(msg, *args)


def _ensure_causalml():
    """惰性导入 causalml，避免模块加载时触发 cv2/OMP 段错误。
    只在真正需要因果推断时调用。"""
    global _CAUSALML_AVAILABLE, _CAUSALML_MODELS
    if _CAUSALML_AVAILABLE is not None:
        return _CAUSALML_AVAILABLE
    try:
        from causalml.inference.meta import LRSRegressor, BaseTRegressor, XGBTRegressor
        _CAUSALML_MODELS = {"LRS": LRSRegressor, "BaseT": BaseTRegressor, "XGBT": XGBTRegressor}
        _CAUSALML_AVAILABLE = True
    except Exception:  # noqa: BLE001
        _CAUSALML_AVAILABLE = False
        _CAUSALML_MODELS = None
        logger.debug("[FO-AGI-02] causalml 不可用，使用降级因果推断")
    return _CAUSALML_AVAILABLE


def _ensure_networkx():
    """惰性导入 networkx。"""
    global _NX_AVAILABLE
    if _NX_AVAILABLE is not None:
        return _NX_AVAILABLE
    try:
        import networkx as nx  # noqa: F401
        _NX_AVAILABLE = True
    except Exception:  # noqa: BLE001
        _NX_AVAILABLE = False
    return _NX_AVAILABLE


class CausalEngine:
    """因果推断引擎.

    区分因果关系 vs 虚假关联，为策略提供因果依据而非纯相关.
    """

    MIN_SAMPLES = 500  # HC-AGI-08: 因果引擎最小样本量

    def __init__(self, min_samples: Optional[int] = None) -> None:
        self.min_samples = min_samples or self.MIN_SAMPLES
        self._dag: Optional[Any] = None  # networkx.DiGraph 或 None
        self._adj_matrix: Optional[np.ndarray] = None  # 邻接矩阵
        self._feature_names: list[str] = []

    # ------------------------------------------------------------------
    # 1. 因果 DAG 学习（NOTEARS 简化版）
    # ------------------------------------------------------------------
    def learn_dag(self, data: np.ndarray, feature_names: Optional[list[str]] = None) -> dict:
        """学习变量间因果 DAG.

        使用简化版 NOTEARS：基于偏相关系数阈值化构建 DAG.
        完整 NOTEARS 需要连续优化，这里用偏相关 + 阈值近似.

        Args:
            data: (n_samples, n_features) 数据矩阵
            feature_names: 变量名列表
        Returns:
            dict: {
                "adj_matrix": np.ndarray,  # 邻接矩阵
                "edges": list[tuple],      # (from, to, weight) 边列表
                "feature_names": list[str],
                "n_edges": int,
                "method": "notears_partial_corr",
            }
        FAIL-OPEN: 样本不足或异常 → 空 DAG
        """
        try:
            data = np.asarray(data, dtype=np.float64)
            if data.ndim != 2 or data.shape[0] < self.min_samples:
                _warn_insufficient_once(
                    "learn_dag", "[HC-AGI-08] 因果引擎样本量不足(< %d)，返回空DAG",
                    self.min_samples)
                return {"adj_matrix": np.zeros((data.shape[1], data.shape[1])),
                        "edges": [], "feature_names": feature_names or [],
                        "n_edges": 0, "method": "insufficient_samples"}

            n_features = data.shape[1]
            if feature_names is None:
                feature_names = [f"X{i}" for i in range(n_features)]
            self._feature_names = feature_names

            # 计算偏相关矩阵
            pcorr = self._partial_correlation(data)

            # 阈值化：|偏相关| > 0.3 视为有因果边
            threshold = 0.3
            adj = (np.abs(pcorr) > threshold).astype(float) * pcorr
            np.fill_diagonal(adj, 0.0)  # 去除自环

            # 确保 DAG（无环）：保留上三角（近似因果方向）
            # 真正的 NOTEARS 会用连续优化，这里用偏相关符号+大小近似方向
            for i in range(n_features):
                for j in range(i + 1, n_features):
                    if adj[i, j] != 0 and adj[j, i] != 0:
                        # 双向边：保留绝对值较大的方向
                        if abs(adj[i, j]) >= abs(adj[j, i]):
                            adj[j, i] = 0.0
                        else:
                            adj[i, j] = 0.0

            self._adj_matrix = adj
            edges = []
            for i in range(n_features):
                for j in range(n_features):
                    if adj[i, j] != 0:
                        edges.append((feature_names[i], feature_names[j], float(adj[i, j])))

            # 构建 networkx DAG
            if _ensure_networkx():
                import networkx as nx
                G = nx.DiGraph()
                G.add_nodes_from(feature_names)
                for f, t, w in edges:
                    G.add_edge(f, t, weight=w)
                self._dag = G

            return {
                "adj_matrix": adj,
                "edges": edges,
                "feature_names": feature_names,
                "n_edges": len(edges),
                "method": "notears_partial_corr",
            }
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-02] learn_dag failed: %s", e)
            return {"adj_matrix": np.zeros((0, 0)), "edges": [],
                    "feature_names": [], "n_edges": 0, "method": "error"}

    @staticmethod
    def _partial_correlation(data: np.ndarray) -> np.ndarray:
        """计算偏相关矩阵（基于精度矩阵）.

        偏相关 = 控制其他变量后两变量的条件相关.
        使用协方差矩阵的逆（精度矩阵）计算.
        """
        n, p = data.shape
        # 标准化
        data_std = (data - data.mean(axis=0)) / (data.std(axis=0) + 1e-10)
        # 协方差矩阵
        cov = np.cov(data_std, rowvar=False)
        # 精度矩阵（协方差的逆）
        try:
            precision = np.linalg.inv(cov + np.eye(p) * 1e-6)
        except np.linalg.LinAlgError:
            precision = np.linalg.pinv(cov)
        # 偏相关 = -precision[i,j] / sqrt(precision[i,i] * precision[j,j])
        diag = np.sqrt(np.diag(precision))
        diag = np.where(diag == 0, 1e-10, diag)
        pcorr = -precision / np.outer(diag, diag)
        np.fill_diagonal(pcorr, 1.0)
        return pcorr

    # ------------------------------------------------------------------
    # 2. 平均处理效应（ATE）估计
    # ------------------------------------------------------------------
    def estimate_ate(
        self,
        X: np.ndarray,
        treatment: np.ndarray,
        y: np.ndarray,
        method: str = "dml",
    ) -> dict:
        """估计平均处理效应（ATE）.

        Args:
            X: (n, d) 协变量
            treatment: (n,) 处理变量（0/1）
            y: (n,) 结果变量
            method: "dml"（双重机器学习）| "s"（S-learner）| "t"（T-learner）
        Returns:
            dict: {
                "ate": float,           # 平均处理效应（点估计）
                "lower_bound": float,   # 置信下界
                "upper_bound": float,   # 置信上界
                "method": str,
                "significant": bool,    # 置信区间不含0
                "ci_method": str,       # A2: "block_bootstrap"（自相关稳健，SPEC §2.5）
                "effect_size": float,   # A2: Cohen's d = ate/std(y)
                "positivity": dict,     # A2: 重叠/positivity 诊断（仅诊断不阻断）
                "trial_count": int,     # A2: 预注册试错次数（评审 m6）
                "fdr_adjusted": bool,   # A2: 是否做多重比较校正
            }
        FAIL-OPEN: 样本不足或异常 → ate=0, 不显著

        A2 增强：CI 统一采用 stationary block bootstrap（块长≈⌈n^(1/3)⌉），
        因 causalml 仅提供 i.i.d. bootstrap（对重叠时序样本失真，SPEC §2.5）。
        点估计仍用 causalml（若可用），CI 用线性 ATE 代理的 block bootstrap 标准误。
        """
        try:
            X = np.asarray(X, dtype=np.float64)
            treatment = np.asarray(treatment, dtype=np.int32)
            y = np.asarray(y, dtype=np.float64)

            if len(y) < self.min_samples:
                _warn_insufficient_once(
                    "estimate_ate", "[HC-AGI-08] ATE样本量不足(< %d)，返回中性结果",
                    self.min_samples)
                return {"ate": 0.0, "lower_bound": 0.0, "upper_bound": 0.0,
                        "method": "insufficient_samples", "significant": False,
                        "ci_method": "asymptotic", "effect_size": 0.0,
                        "positivity": None, "trial_count": 1, "fdr_adjusted": False}

            # 1. 点估计：causalml 优先，否则线性降级
            if _ensure_causalml() and method in ("dml", "s", "t"):
                point = self._causalml_ate(X, treatment, y, method)
            else:
                point = self._linear_ate(X, treatment, y)
            ate = float(point["ate"])
            method_label = str(point["method"])

            # 2. stationary block bootstrap CI（自相关稳健；SPEC §2.5）
            se = self._block_bootstrap_se(X, treatment, y)
            half = 1.96 * se
            lb, ub = ate - half, ate + half

            std_y = float(np.std(y))
            effect_size = ate / std_y if std_y > 0 else 0.0
            return {
                "ate": ate,
                "lower_bound": float(lb),
                "upper_bound": float(ub),
                "method": method_label,
                "significant": not (lb <= 0 <= ub),
                "ci_method": "block_bootstrap",
                "effect_size": float(effect_size),
                "positivity": self._positivity_diagnostics(X, treatment, y, ate),
                "trial_count": 1,
                "fdr_adjusted": False,
            }
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-02] estimate_ate failed: %s", e)
            return {"ate": 0.0, "lower_bound": 0.0, "upper_bound": 0.0,
                    "method": "error", "significant": False,
                    "ci_method": "asymptotic", "effect_size": 0.0,
                    "positivity": None, "trial_count": 1, "fdr_adjusted": False}

    def _causalml_ate(self, X, treatment, y, method) -> dict:
        """使用 causalml 估计 ATE 点估计（CI 由 estimate_ate 统一 block bootstrap）."""
        try:
            if method == "dml":
                from causalml.inference.meta import LRSRegressor
                te = LRSRegressor().estimate_ate(X, treatment, y)[0]
            elif method == "s":
                from causalml.inference.meta import BaseSRegressor
                from sklearn.linear_model import LinearRegression
                te = BaseSRegressor(learner=LinearRegression()).estimate_ate(X, treatment, y)[0]
            else:  # t
                from causalml.inference.meta import BaseTRegressor
                from sklearn.linear_model import LinearRegression
                te = BaseTRegressor(learner=LinearRegression()).estimate_ate(X, treatment, y)[0]

            ate = float(np.mean(te)) if hasattr(te, "__len__") else float(te)
            return {"ate": ate, "method": f"causalml_{method}"}
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-02] causalml ATE failed, falling back to linear: %s", e)
            return self._linear_ate(X, treatment, y)

    def _linear_ate(self, X, treatment, y) -> dict:
        """线性回归降级估计 ATE 点估计: y ~ treatment + X（CI 由 estimate_ate 统一处理）."""
        try:
            T = treatment.reshape(-1, 1).astype(np.float64)
            X_design = np.hstack([T, X])
            coef, *_ = np.linalg.lstsq(X_design, y, rcond=None)
            return {"ate": float(coef[0]), "method": "linear_regression"}
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-02] linear ATE failed: %s", e)
            return {"ate": 0.0, "method": "error"}

    # -- A2: stationary block bootstrap（自相关稳健 CI）--------------------
    @staticmethod
    def _stationary_block_index(n: int, block_len: int, rng) -> np.ndarray:
        """stationary block bootstrap 索引（circular 环绕，块长固定）."""
        n_blocks = int(np.ceil(n / block_len))
        starts = rng.integers(0, n, size=n_blocks)
        offsets = np.arange(block_len)
        idx = (starts[:, None] + offsets[None, :]).reshape(-1) % n
        return idx[:n]

    def _block_bootstrap_se(
        self, X: np.ndarray, treatment: np.ndarray, y: np.ndarray,
        n_boot: int = 200, seed: int = 42,
    ) -> float:
        """线性 ATE 代理的 stationary block bootstrap 标准误（SPEC §2.5）.

        源B 时序重叠 → 不得用 i.i.d. 重采样；块长 ≈ ⌈n^(1/3)⌉。
        """
        n = int(len(y))
        block_len = max(1, int(round(n ** (1.0 / 3.0))))
        Xd = np.hstack([treatment.reshape(-1, 1).astype(np.float64), X])
        rng = np.random.default_rng(seed)
        stats = np.empty(n_boot, dtype=np.float64)
        for i in range(n_boot):
            idx = self._stationary_block_index(n, block_len, rng)
            try:
                coef, *_ = np.linalg.lstsq(Xd[idx], y[idx], rcond=None)
                stats[i] = float(coef[0])
            except Exception:  # noqa: BLE001
                stats[i] = 0.0
        if n_boot <= 1:
            return 0.0
        return float(np.std(stats, ddof=1))

    def _positivity_diagnostics(
        self, X: np.ndarray, treatment: np.ndarray, y: np.ndarray, ate: float,
    ) -> Optional[dict]:
        """重叠/positivity 诊断（仅诊断不阻断，SPEC §2.5）.

        报告倾向得分尾部占比与 trimming（p∈[0.05,0.95]）前后 ATE 差。
        """
        try:
            from sklearn.linear_model import LogisticRegression

            ps = LogisticRegression(max_iter=200).fit(X, treatment).predict_proba(X)[:, 1]
            n = int(len(y))
            tail = float(np.mean((ps < 0.05) | (ps > 0.95)))
            keep = (ps >= 0.05) & (ps <= 0.95)
            Xd = np.hstack([treatment.reshape(-1, 1).astype(np.float64), X])
            if int(keep.sum()) >= max(50, int(0.1 * n)):
                coef, *_ = np.linalg.lstsq(Xd[keep], y[keep], rcond=None)
                ate_trimmed = float(coef[0])
            else:
                ate_trimmed = float(ate)
            return {"tail_ratio": tail, "n_tail": int(tail * n),
                    "ate_trimmed": ate_trimmed, "trimmed_n": int(keep.sum())}
        except Exception as e:  # noqa: BLE001
            logger.debug("[A2] positivity diagnostic FAIL-OPEN: %s", e)
            return {"tail_ratio": None, "n_tail": None,
                    "ate_trimmed": None, "trimmed_n": None}

    # ------------------------------------------------------------------
    # 3. 异质性处理效应（CATE）估计
    # ------------------------------------------------------------------
    def estimate_cate(
        self,
        X: np.ndarray,
        treatment: np.ndarray,
        y: np.ndarray,
    ) -> dict:
        """估计异质性处理效应（CATE）.

        CATE = E[Y(1) - Y(0) | X=x]，即条件于特征的个体处理效应.

        Args:
            X: (n, d) 协变量
            treatment: (n,) 处理变量
            y: (n,) 结果变量
        Returns:
            dict: {
                "cate": np.ndarray,      # 每个样本的 CATE
                "method": str,
                "heterogeneity_score": float,  # CATE 变异程度
            }
        FAIL-OPEN: 异常 → cate=0
        """
        try:
            X = np.asarray(X, dtype=np.float64)
            treatment = np.asarray(treatment, dtype=np.int32)
            y = np.asarray(y, dtype=np.float64)

            if len(y) < self.min_samples:
                return {"cate": np.zeros(len(y)), "method": "insufficient_samples",
                        "heterogeneity_score": 0.0}

            if _ensure_causalml():
                return self._causalml_cate(X, treatment, y)
            return self._linear_cate(X, treatment, y)
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-02] estimate_cate failed: %s", e)
            return {"cate": np.zeros(len(y) if 'y' in dir() else 0),
                    "method": "error", "heterogeneity_score": 0.0}

    def _causalml_cate(self, X, treatment, y) -> dict:
        """causalml CATE 估计（T-learner + sklearn，避免 xgboost 在 numpy2 下崩溃）"""
        try:
            from causalml.inference.meta import BaseTRegressor
            from sklearn.ensemble import RandomForestRegressor
            t_learner = BaseTRegressor(learner=RandomForestRegressor(n_estimators=50, random_state=42))
            cate = t_learner.fit_predict(X, treatment, y)
            cate = np.asarray(cate).ravel()
            hetero = float(np.std(cate) / (np.mean(np.abs(cate)) + 1e-10))
            return {"cate": cate, "method": "causalml_rf_t",
                    "heterogeneity_score": hetero}
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-02] causalml CATE failed: %s", e)
            return self._linear_cate(X, treatment, y)

    def _linear_cate(self, X, treatment, y) -> dict:
        """线性 CATE：y ~ treatment * X，交互项系数 = CATE"""
        try:
            from sklearn.linear_model import LinearRegression

            n, d = X.shape
            # 交互特征: treatment * X
            T = treatment.reshape(-1, 1)
            interactions = T * X
            X_design = np.hstack([T, X, interactions])

            reg = LinearRegression()
            reg.fit(X_design, y)

            # CATE = treatment系数 + sum(interaction_coef * X_i)
            base_effect = reg.coef_[0]
            interaction_coefs = reg.coef_[1 + d:]  # 交互项系数
            cate = base_effect + X @ interaction_coefs

            hetero = float(np.std(cate) / (np.mean(np.abs(cate)) + 1e-10))
            return {"cate": cate, "method": "linear_interaction",
                    "heterogeneity_score": hetero}
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-02] linear CATE failed: %s", e)
            return {"cate": np.zeros(len(y)), "method": "error",
                    "heterogeneity_score": 0.0}

    # ------------------------------------------------------------------
    # 4. 虚假关联检测
    # ------------------------------------------------------------------
    def detect_spurious(self, data: np.ndarray, feature_names: Optional[list[str]] = None) -> dict:
        """检测虚假关联（由混淆变量导致的伪相关）.

        虚假关联 = 两变量相关但无直接因果路径，相关性由第三个变量（混淆因子）驱动.
        检测方法：若 A-B 相关，但控制 C 后 A-B 偏相关≈0，则 A-B 是虚假关联.

        Args:
            data: (n, p) 数据矩阵
            feature_names: 变量名
        Returns:
            dict: {
                "spurious_pairs": list[dict],  # 虚假关联对
                "correlations": list[dict],     # 所有高相关对
                "n_spurious": int,
            }
        FAIL-OPEN: 异常 → 空列表
        """
        try:
            data = np.asarray(data, dtype=np.float64)
            n, p = data.shape
            if n < self.min_samples or p < 3:
                return {"spurious_pairs": [], "correlations": [], "n_spurious": 0}

            if feature_names is None:
                feature_names = [f"X{i}" for i in range(p)]

            # 相关矩阵
            corr = np.corrcoef(data, rowvar=False)
            # 偏相关矩阵
            pcorr = self._partial_correlation(data)

            correlations = []
            spurious_pairs = []

            for i in range(p):
                for j in range(i + 1, p):
                    raw_corr = abs(corr[i, j])
                    partial_corr = abs(pcorr[i, j])
                    if raw_corr > 0.5:  # 高相关
                        correlations.append({
                            "pair": (feature_names[i], feature_names[j]),
                            "raw_correlation": float(corr[i, j]),
                            "partial_correlation": float(pcorr[i, j]),
                        })
                        # 虚假关联：相关高但偏相关低（控制其他变量后消失）
                        if partial_corr < 0.2 and raw_corr > 0.5:
                            spurious_pairs.append({
                                "pair": (feature_names[i], feature_names[j]),
                                "raw_correlation": float(corr[i, j]),
                                "partial_correlation": float(pcorr[i, j]),
                                "confounders": self._find_confounders(data, i, j, feature_names),
                            })

            return {
                "spurious_pairs": spurious_pairs,
                "correlations": correlations,
                "n_spurious": len(spurious_pairs),
            }
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-02] detect_spurious failed: %s", e)
            return {"spurious_pairs": [], "correlations": [], "n_spurious": 0}

    @staticmethod
    def _find_confounders(data, i, j, feature_names) -> list[str]:
        """找出变量 i 和 j 的混淆因子（与两者都相关的第三个变量）"""
        confounders = []
        n, p = data.shape
        for k in range(p):
            if k == i or k == j:
                continue
            corr_ik = abs(np.corrcoef(data[:, i], data[:, k])[0, 1])
            corr_jk = abs(np.corrcoef(data[:, j], data[:, k])[0, 1])
            if corr_ik > 0.4 and corr_jk > 0.4:
                confounders.append(feature_names[k])
        return confounders

    # ------------------------------------------------------------------
    # 5. 因果影响力评分
    # ------------------------------------------------------------------
    def causal_influence(self, data: np.ndarray, feature_names: Optional[list[str]] = None) -> dict:
        """计算每个变量的因果影响力（基于 DAG 的出边权重和）.

        影响力 = 该变量作为原因指向其他变量的边权重之和.

        Returns:
            dict: {
                "influence_scores": dict,  # {feature_name: score}
                "ranked_features": list[str],  # 按影响力降序
            }
        """
        try:
            dag_result = self.learn_dag(data, feature_names)
            adj = dag_result["adj_matrix"]
            names = dag_result["feature_names"]

            if len(adj) == 0:
                return {"influence_scores": {}, "ranked_features": []}

            # 出边权重和 = 行和
            influence = np.sum(np.abs(adj), axis=1)
            scores = {names[i]: float(influence[i]) for i in range(len(names))}
            ranked = sorted(scores, key=lambda k: scores[k], reverse=True)
            return {"influence_scores": scores, "ranked_features": ranked}
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-02] causal_influence failed: %s", e)
            return {"influence_scores": {}, "ranked_features": []}

    # ------------------------------------------------------------------
    # 6. Phase 6: ATE 分桶动态校准 (替换 ImpactMultiplier 硬编码表)
    # ------------------------------------------------------------------
    def calibrate_multipliers(
        self,
        factor_matrix: np.ndarray,
        factor_names: list[str],
        returns: np.ndarray,
        phases: list[str],
        name_to_dim: dict[str, str],
    ) -> dict[str, dict[str, dict[str, float]]]:
        """按 cycle_phase 分桶，用 ATE 估计每个维度的因果影响力.

        Phase 6 (SPEC §8): 数据驱动校准替换 ImpactMultiplier.MULTIPLIER_TABLE 硬编码.

        对每个 (phase, dimension)：
          1. 选取该 dimension 下所有因子，取均值作为该维度的聚合因子
          2. treatment = 聚合因子 > 中位数 (1) 或 <= 中位数 (0)
          3. y = 未来收益率
          4. estimate_ate → 该维度因子"高"时对收益率的平均处理效应
          5. ATE 显著 → 该维度在该阶段有因果效应，保留/放大 multiplier
             ATE 不显著 → 该维度在该阶段无因果效应，衰减 multiplier

        Args:
            factor_matrix: (n_samples, n_factors) 因子矩阵
            factor_names: 因子名列表 (与 factor_matrix 列对齐)
            returns: (n_samples,) 未来收益率 (对齐每个样本)
            phases: (n_samples,) 每个样本的 cycle_phase 标签
            name_to_dim: {factor_name: dimension} 映射 (C1/C2/.../news)

        Returns:
            ate_results: {
                phase: {
                    dimension: {
                        "ate": float,
                        "significant": bool,
                        "lower_bound": float,
                        "upper_bound": float,
                        "n_samples": int,
                    }
                }
            }
            缺失/不足时该 (phase, dimension) 不在结果中。
        """
        try:
            factor_matrix = np.asarray(factor_matrix, dtype=np.float64)
            returns = np.asarray(returns, dtype=np.float64)
            phases = list(phases)
            n = len(returns)

            if n == 0 or factor_matrix.shape[0] != n:
                return {}

            # 构建 dimension → factor_indices 映射
            dim_to_cols: dict[str, list[int]] = {}
            for i, fname in enumerate(factor_names):
                dim = name_to_dim.get(fname)
                if dim is not None:
                    dim_to_cols.setdefault(dim, []).append(i)

            ate_results: dict[str, dict[str, dict[str, float]]] = {}

            for phase in set(phases):
                if not phase or phase == "neutral":
                    continue

                phase_mask = np.array([p == phase for p in phases])
                phase_n = int(np.sum(phase_mask))
                if phase_n < self.min_samples:
                    # 该阶段样本不足，跳过 ATE 估计
                    continue

                phase_results: dict[str, dict[str, float]] = {}
                # 该阶段的因子子集
                phase_factors = factor_matrix[phase_mask]  # (phase_n, n_factors)
                for dim, cols in dim_to_cols.items():
                    # 该维度聚合因子 = 列均值
                    dim_factor = np.nanmean(phase_factors[:, cols], axis=1)
                    y_phase = returns[phase_mask]

                    # 去除 NaN
                    valid = ~np.isnan(dim_factor) & ~np.isnan(y_phase)
                    if np.sum(valid) < self.min_samples:
                        continue

                    dim_f = dim_factor[valid]
                    y_v = y_phase[valid]

                    # treatment = 聚合因子 > 中位数
                    median_val = np.median(dim_f)
                    treatment = (dim_f > median_val).astype(np.int32)

                    # 协变量 = 该维度外的所有其他维度聚合因子
                    other_cols = [c for d, cs in dim_to_cols.items() if d != dim for c in cs]
                    if other_cols:
                        X = np.nanmean(phase_factors[valid][:, other_cols], axis=1, keepdims=True)
                    else:
                        X = np.zeros((int(np.sum(valid)), 1))

                    ate_res = self.estimate_ate(X, treatment, y_v, method="dml")
                    phase_results[dim] = {
                        "ate": float(ate_res["ate"]),
                        "significant": bool(ate_res["significant"]),
                        "lower_bound": float(ate_res["lower_bound"]),
                        "upper_bound": float(ate_res["upper_bound"]),
                        "n_samples": int(np.sum(valid)),
                    }

                if phase_results:
                    ate_results[phase] = phase_results

            return ate_results
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-02] calibrate_multipliers failed: %s", e)
            return {}

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------
    def backend_status(self) -> dict:
        """报告后端依赖状态"""
        return {
            "causalml": _ensure_causalml(),
            "networkx": _ensure_networkx(),
            "min_samples": self.min_samples,
        }
