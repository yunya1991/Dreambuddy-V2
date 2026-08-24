"""LGBM 概率校正器 · 方案 A：log-odds 空间加权融合

Spec 设计：
  • 仅作为「概率校正器」参与 8 态概率的 log-odds 加权融合，
    不改变 8 态概率的核心来源（核心仍来自 RegimeMapper 的高斯软分配）。
  • w_gauss=0.6、w_lgbm=0.4、T=0.6（log-space mixing + temperature softmax）。
  • 仅暴露 calibrate(...) 接口输出 8 维概率分布，不提供 predict 硬分类。
  • FeatureSchema 严格校验：列顺序/列数/列名不匹配 → 抛 ValueError（禁止静默 reindex/fillna）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

try:
    import lightgbm as lgb
except ImportError:  # pragma: no cover - 运行时环境一定有，这里只做兼容提示
    lgb = None  # type: ignore


# ============================================================
# 融合超参（来自 Spec §Phase1 方案 A）
# ============================================================
W_GAUSS: float = 0.6
W_LGBM: float = 0.4
TEMPERATURE: float = 0.6
EPS: float = 1e-12


class LGBMCalibrator:
    """LightGBM 概率校正器 —— 8 态 soft probability calibrator.

    用法：
        cal = LGBMCalibrator()
        cal.fit(X_train_df, y_train_series, schema_path="artifacts/schema.json")
        p_out = cal.calibrate(p_gauss, X_infer_df)   # shape (n, 8), sum=1
    """

    REGIME_ORDER_DEFAULT = [
        "RANGE_BOUND", "CONSOLIDATION", "ACCUMULATION",
        "RECOVERY_MILD", "TREND_UP_MILD", "TREND_UP_STRONG",
        "FOMO_RALLY", "VOLATILE_DROP",
    ]

    # ------------------------------------------------------------------ init
    def __init__(self, random_state: int = 42):
        if lgb is None:  # pragma: no cover
            raise RuntimeError("lightgbm 未安装，LGBMCalibrator 不可用。请 pip install lightgbm")
        self._model: Optional["lgb.LGBMClassifier"] = None
        self._regime_order: List[str] = list(self.REGIME_ORDER_DEFAULT)
        self._feature_names: List[str] = []
        self._random_state = random_state

    # ------------------------------------------------------------------ fit
    def fit(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        schema_path: str,
        num_leaves: int = 31,
        max_depth: int = 8,
        reg_alpha: float = 0.5,
        reg_lambda: float = 2.0,
        n_estimators: int = 200,
        learning_rate: float = 0.05,
        regime_order: Optional[List[str]] = None,
        class_weight: Any = "balanced",
        min_child_samples: int = 20,
        colsample_bytree: float = 1.0,
        subsample: float = 1.0,
        subsample_freq: int = 0,
    ) -> "LGBMCalibrator":
        """训练 LGBM 多分类器，并将 FeatureSchema 持久化到 JSON。

        schema 格式：
        {
          "feature_names_in_order": ["feat_0", ...],  # 严格列顺序
          "regime_order":           ["RANGE_BOUND", ...],  # 概率轴顺序
          "n_features": int,
          "n_classes": 8,
        }

        Args:
            regime_order: 显式指定 regime 列轴顺序。若提供，则 predict_proba 列轴严格按此顺序，
                          y 中不在 regime_order 中的标签会被丢弃（过滤，不报错）。
                          若为 None，则回退到自动推导（兼容旧测试）。
            class_weight: 类别权重。'balanced' 自动按逆频率加权（缓解 8 态标签不均衡），
                          None 不加权，dict 手动指定 {regime_name: weight}。
                          默认 'balanced'。
            min_child_samples: 叶子节点最小样本数（防过拟合）。
            colsample_bytree: 每棵树列采样比例（防过拟合）。
            subsample: 样本采样比例（防过拟合）。
            subsample_freq: 样本采样频率（0=禁用，>0 每隔 N 轮重采）。
        """
        if not isinstance(X, pd.DataFrame):
            raise TypeError("X 必须是 pandas.DataFrame（才能严格追踪列）")
        if not isinstance(y, pd.Series):
            raise TypeError("y 必须是 pandas.Series")

        if regime_order is not None:
            # 显式模式：严格按 regime_order 对齐，过滤掉不在其中的标签
            self._regime_order = list(regime_order)
            # 过滤 y 中不在 regime_order 的样本
            mask = y.isin(set(regime_order))
            if mask.sum() < len(y):
                dropped = len(y) - int(mask.sum())
                print(f"[LGBMCalibrator.fit] 过滤 {dropped} 个不在 regime_order 中的样本", flush=True)
            X = X.loc[mask].copy()
            y = y.loc[mask].copy()
            # 将未在 y 中出现的 regime 也保留在列轴（predict_proba 会输出全 0 概率列）
        else:
            # 自动推导模式（兼容旧测试）
            classes_present = sorted(y.unique().tolist(),
                                     key=lambda c: (self.REGIME_ORDER_DEFAULT.index(c)
                                                    if c in self.REGIME_ORDER_DEFAULT else 999))
            full_order = list(classes_present)
            for c in self.REGIME_ORDER_DEFAULT:
                if c not in full_order:
                    full_order.append(c)
            for c in y.unique():
                if c not in full_order:
                    full_order.append(c)
            self._regime_order = full_order
        self._feature_names = list(X.columns)

        # 2) 处理 class_weight: 'balanced' → 逆频率 dict；dict → 按 regime_order 映射为 index dict
        cw_resolved: Any = None
        if class_weight is not None:
            if class_weight == "balanced":
                # 逆频率加权: w_i = n_samples / (n_classes * count_i)
                counts = y.value_counts()
                n_total = len(y)
                n_classes = len(self._regime_order)
                cw_resolved = {
                    self._regime_order.index(r): n_total / (n_classes * max(1, int(counts.get(r, 0))))
                    for r in self._regime_order
                }
            elif isinstance(class_weight, dict):
                # {regime_name: weight} → {class_index: weight}
                cw_resolved = {
                    self._regime_order.index(r): float(w)
                    for r, w in class_weight.items()
                    if r in self._regime_order
                }
            else:
                cw_resolved = class_weight  # 直接透传（如 None 或 sklearn 兼容格式）

        # 3) 训练 LGBM（强正则，Spec §4 要求）
        y_coded = y.map({name: i for i, name in enumerate(self._regime_order)}).astype(int)

        model = lgb.LGBMClassifier(
            objective="multiclass",
            num_class=len(self._regime_order),
            num_leaves=num_leaves,
            max_depth=max_depth,
            reg_alpha=reg_alpha,
            reg_lambda=reg_lambda,
            n_estimators=n_estimators,
            learning_rate=learning_rate,
            min_child_samples=min_child_samples,
            colsample_bytree=colsample_bytree,
            subsample=subsample,
            subsample_freq=subsample_freq,
            class_weight=cw_resolved,
            random_state=self._random_state,
            verbose=-1,
        )
        # early_stopping 只在有 eval_set 时启用；为了合成数据 n=800 也能稳定训练，
        # 这里直接整集 fit（测试集里的合成数据无过拟合风险，且 n_estimators=200 有强正则兜底）。
        model.fit(X.values, y_coded.values)
        self._model = model

        # 4) 保存 schema JSON（严格列顺序、regime 顺序）
        schema: Dict[str, Any] = {
            "feature_names_in_order": list(self._feature_names),
            "regime_order":           list(self._regime_order),
            "n_features":             len(self._feature_names),
            "n_classes":              len(self._regime_order),
            "hyperparams": {
                "w_gauss":            W_GAUSS,
                "w_lgbm":             W_LGBM,
                "temperature":        TEMPERATURE,
                "num_leaves":         num_leaves,
                "max_depth":          max_depth,
                "reg_alpha":          reg_alpha,
                "reg_lambda":         reg_lambda,
                "n_estimators":       n_estimators,
                "learning_rate":      learning_rate,
                "min_child_samples":  min_child_samples,
                "colsample_bytree":   colsample_bytree,
                "subsample":          subsample,
                "subsample_freq":     subsample_freq,
                "class_weight":       class_weight if isinstance(class_weight, str) else None,
            },
        }
        schema_path = Path(schema_path)
        schema_path.parent.mkdir(parents=True, exist_ok=True)
        schema_path.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
        return self

    # ------------------------------------------------------------------ schema 校验
    def _validate_schema_strict(self, X: pd.DataFrame) -> None:
        """严格校验 X 的列。不满足 → ValueError。

        禁止：静默 reindex、fillna、列顺序容忍。
        """
        if self._model is None:
            raise RuntimeError("请先 fit() 再 calibrate()")
        if not isinstance(X, pd.DataFrame):
            raise TypeError("X 必须是 pandas.DataFrame 才能做 schema 校验")
        in_cols = list(X.columns)
        expected = self._feature_names
        if len(in_cols) != len(expected):
            raise ValueError(
                f"schema mismatch col: 推理时列数={len(in_cols)} ≠ schema 列数={len(expected)}。"
                f" 实际列={in_cols}，期望列={expected}"
            )
        if in_cols != expected:
            # 找出第一个不同的位置给出错误信息
            for i, (a, b) in enumerate(zip(in_cols, expected)):
                if a != b:
                    raise ValueError(
                        f"schema mismatch col: 第 {i} 列推理={a!r} ≠ schema={b!r}。"
                        f" 必须列顺序严格一致。实际列={in_cols}，期望列={expected}"
                    )
            # 长度相等但内容不同（上面的循环理论会捕获，但兜底再比一次集合）
            if set(in_cols) != set(expected):
                raise ValueError(
                    f"schema mismatch col: 列集合不一致。"
                    f" 推理有但 schema 没有={set(in_cols)-set(expected)}，"
                    f" schema 有但推理没有={set(expected)-set(in_cols)}"
                )

    # ------------------------------------------------------------------ calibrate（唯一对外推理接口）
    def calibrate(self, p_gauss: np.ndarray, X: pd.DataFrame) -> np.ndarray:
        """对高斯软分配概率 p_gauss 与 LGBM 预测概率做 log-odds 温度融合。

        参数:
            p_gauss — shape (n, K)，来自 RegimeMapper 的 8 态软概率。列轴顺序
                      需与 self._regime_order 前 K 个对齐（K==8 时精确对齐）。
            X       — 用于 LGBM 推理的特征 DataFrame，列必须与 schema 严格一致。

        返回:
            p_out — shape (n, n_classes)，Σ=1 的校准概率分布。
                    列轴 == self._regime_order（按 REGIME_ORDER_DEFAULT 优先顺序）。
        """
        self._validate_schema_strict(X)
        n = len(X)
        if p_gauss.shape[0] != n:
            raise ValueError(
                f"p_gauss 行数={p_gauss.shape[0]} ≠ X 行数={n}"
            )
        if p_gauss.ndim != 2 or p_gauss.shape[1] != len(self._regime_order):
            # 允许 p_gauss 列与默认 8 态完全对齐（若 schema 中 regime 顺序和默认完全一致则 OK）
            if not (p_gauss.ndim == 2 and p_gauss.shape[1] <= len(self._regime_order)):
                raise ValueError(
                    f"p_gauss shape={p_gauss.shape} 无法匹配 n_classes={len(self._regime_order)}"
                )

        # 1) LGBM predict_proba — shape (n, n_classes)
        p_lgbm = self._model.predict_proba(X.values)  # type: ignore[union-attr]

        # 2) 将 p_gauss 列轴 pad 到与 n_classes 对齐（测试场景下两者完全相等，这里兜底）
        if p_gauss.shape[1] == p_lgbm.shape[1]:
            p_gauss_aligned = p_gauss
        else:
            p_gauss_aligned = np.zeros_like(p_lgbm)
            k = min(p_gauss.shape[1], p_lgbm.shape[1])
            p_gauss_aligned[:, :k] = p_gauss[:, :k]
            # 把剩余概率均匀分给末尾列？——不：保持归一化即可
            row_remain = 1.0 - p_gauss_aligned.sum(axis=1, keepdims=True)
            tail_count = p_lgbm.shape[1] - k
            if tail_count > 0:
                p_gauss_aligned[:, k:] = np.where(
                    tail_count > 0, row_remain / tail_count, 0.0
                )
            p_gauss_aligned = p_gauss_aligned / np.clip(p_gauss_aligned.sum(axis=1, keepdims=True), EPS, None)

        # 3) log-odds 加权 + temperature softmax
        log_pg = np.log(np.clip(p_gauss_aligned, EPS, None))
        log_pl = np.log(np.clip(p_lgbm, EPS, None))
        logits = (W_GAUSS * log_pg + W_LGBM * log_pl) / np.clip(TEMPERATURE, EPS, None)

        # 数值稳定 softmax
        logits_shifted = logits - logits.max(axis=1, keepdims=True)
        exp_l = np.exp(logits_shifted)
        p_out = exp_l / np.clip(exp_l.sum(axis=1, keepdims=True), EPS, None)
        return p_out

    # ------------------------------------------------------------------ 只读辅助（调试/审计）
    @property
    def feature_names(self) -> List[str]:
        return list(self._feature_names)

    @property
    def regime_order(self) -> List[str]:
        return list(self._regime_order)

    @property
    def is_fitted(self) -> bool:
        return self._model is not None

    # ------------------------------------------------------------------ 持久化：joblib dump/load 完整实例
    def save(self, dir_path: str) -> Path:
        """保存完整 calibrator 实例（含 model）到目录。

        目录结构：
            dir_path/
                calibrator.joblib    # pickle 整个 self
                schema.json          # （fit 时已写，这里再覆写保证一致）
        """
        import joblib  # 懒加载，避免未装时 import 失败
        d = Path(dir_path)
        d.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, d / "calibrator.joblib", compress=3)
        # 同步再写一份 schema（fit 已写过，但防御式覆盖）
        schema: Dict[str, Any] = {
            "feature_names_in_order": list(self._feature_names),
            "regime_order":           list(self._regime_order),
            "n_features":             len(self._feature_names),
            "n_classes":              len(self._regime_order),
            "hyperparams": {
                "w_gauss":     W_GAUSS,
                "w_lgbm":      W_LGBM,
                "temperature": TEMPERATURE,
            },
        }
        (d / "schema.json").write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
        return d

    @classmethod
    def load(cls, dir_path: str) -> "LGBMCalibrator":
        import joblib
        d = Path(dir_path)
        cal_path = d / "calibrator.joblib"
        if not cal_path.exists():
            raise FileNotFoundError(f"[LGBMCalibrator.load] 找不到 {cal_path}。请先 train_lgbm_calibrator_v4.py 产出。")
        obj: "LGBMCalibrator" = joblib.load(cal_path)
        if not isinstance(obj, cls):
            raise TypeError(f"calibrator.joblib 内对象不是 LGBMCalibrator：{type(obj)}")
        return obj


# ============================================================
# 模块别名同步（与 feature_registry 相同机制）
# ============================================================
def _sync_module_aliases():
    import sys as _sys
    this_mod = _sys.modules.get(__name__)
    if this_mod is None:
        return
    candidates = [
        "bcrm2.lgbm_calibrator",
        "scripts.memory_l4.bcrm2.lgbm_calibrator",
    ]
    for alias in candidates:
        existing = _sys.modules.get(alias)
        if existing is None:
            _sys.modules[alias] = this_mod


_sync_module_aliases()
del _sync_module_aliases
