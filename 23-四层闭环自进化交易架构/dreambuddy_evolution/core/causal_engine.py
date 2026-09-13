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
                logger.warning("[HC-AGI-08] 因果引擎样本量不足(< %d)，返回空DAG", self.min_samples)
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
                "ate": float,           # 平均处理效应
                "lower_bound": float,   # 置信下界
                "upper_bound": float,   # 置信上界
                "method": str,
                "significant": bool,    # 置信区间不含0
            }
        FAIL-OPEN: 样本不足或异常 → ate=0, 不显著
        """
        try:
            X = np.asarray(X, dtype=np.float64)
            treatment = np.asarray(treatment, dtype=np.int32)
            y = np.asarray(y, dtype=np.float64)

            if len(y) < self.min_samples:
                logger.warning("[HC-AGI-08] ATE样本量不足(< %d)，返回中性结果", self.min_samples)
                return {"ate": 0.0, "lower_bound": 0.0, "upper_bound": 0.0,
                        "method": "insufficient_samples", "significant": False}

            if _ensure_causalml() and method in ("dml", "s", "t"):
                return self._causalml_ate(X, treatment, y, method)
            return self._linear_ate(X, treatment, y)
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-02] estimate_ate failed: %s", e)
            return {"ate": 0.0, "lower_bound": 0.0, "upper_bound": 0.0,
                    "method": "error", "significant": False}

    def _causalml_ate(self, X, treatment, y, method) -> dict:
        """使用 causalml 估计 ATE"""
        try:
            if method == "dml":
                from causalml.inference.meta import LRSRegressor
                lr = LRSRegressor()
                te, lb, ub = lr.estimate_ate(X, treatment, y)
            elif method == "s":
                from causalml.inference.meta import BaseSRegressor
                from sklearn.linear_model import LinearRegression
                s = BaseSRegressor(learner=LinearRegression())
                te, lb, ub = s.estimate_ate(X, treatment, y)
            else:  # t
                from causalml.inference.meta import BaseTRegressor
                from sklearn.linear_model import LinearRegression
                t = BaseTRegressor(learner=LinearRegression())
                te, lb, ub = t.estimate_ate(X, treatment, y)

            ate = float(np.mean(te)) if hasattr(te, "__len__") else float(te)
            lb = float(np.mean(lb)) if hasattr(lb, "__len__") else float(lb)
            ub = float(np.mean(ub)) if hasattr(ub, "__len__") else float(ub)
            return {
                "ate": ate,
                "lower_bound": lb,
                "upper_bound": ub,
                "method": f"causalml_{method}",
                "significant": not (lb <= 0 <= ub),
            }
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-02] causalml ATE failed, falling back to linear: %s", e)
            return self._linear_ate(X, treatment, y)

    def _linear_ate(self, X, treatment, y) -> dict:
        """线性回归降级估计 ATE: y ~ treatment + X"""
        try:
            from sklearn.linear_model import LinearRegression

            # 构造设计矩阵: [treatment, X]
            T = treatment.reshape(-1, 1)
            X_design = np.hstack([T, X])
            reg = LinearRegression()
            reg.fit(X_design, y)
            ate = float(reg.coef_[0])  # treatment 的系数

            # 用 bootstrap 估计置信区间
            n = len(y)
            boot_ates = []
            rng = np.random.RandomState(42)
            for _ in range(200):
                idx = rng.choice(n, n, replace=True)
                reg_b = LinearRegression()
                reg_b.fit(X_design[idx], y[idx])
                boot_ates.append(float(reg_b.coef_[0]))
            lb = float(np.percentile(boot_ates, 2.5))
            ub = float(np.percentile(boot_ates, 97.5))

            return {
                "ate": ate,
                "lower_bound": lb,
                "upper_bound": ub,
                "method": "linear_regression",
                "significant": not (lb <= 0 <= ub),
            }
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-02] linear ATE failed: %s", e)
            return {"ate": 0.0, "lower_bound": 0.0, "upper_bound": 0.0,
                    "method": "error", "significant": False}

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
    # 状态查询
    # ------------------------------------------------------------------
    def backend_status(self) -> dict:
        """报告后端依赖状态"""
        return {
            "causalml": _ensure_causalml(),
            "networkx": _ensure_networkx(),
            "min_samples": self.min_samples,
        }
