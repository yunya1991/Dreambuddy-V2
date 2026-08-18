"""
§4.2 RegimePredictor：形态预测器（监督学习 LGBM 分类器）

继承关系：
  RegimePredictor(MarketRegimeClassifier)
    → 覆写 fit(X, y, feature_names)：训练 LGBM + 特征权重（方差放大）
    → 覆写 predict(X)：输出 (y_pred, confidence, proba) 三元组，按 8 态
    → 保留父类 predict_regime_names/get_regime_params（但 regime 顺序已扩展）

特征权重（Spec §4.2.1 方差放大机制）：
  形态核心组（MorphologyCoreFeatures 的 12 列）→ × 2.5
  市场广度组（BreadthMarketFeatures 的 8 列）→ × 1.5
  其他特征 → × 1.0
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import numpy as np

logger = logging.getLogger(__name__)


# 默认分组（当配置文件/配置 dict 未指定时使用）
DEFAULT_FEATURE_GROUPS: Dict[str, List[str]] = {
    # Phase 0 - morphology_core 12 特征
    "morphology": [
        "adx_14", "adx_plus_di", "adx_minus_di", "adx_trend_strength_bucket",
        "hurst_exp_50", "hurst_exp_100", "hurst_state",
        "bb_width_percentile_252", "bb_squeeze_signal",
        "distance_to_high_60d", "distance_to_high_120d",
        "distance_to_high_lt_5_pct",
    ],
    # Phase 0 - breadth_market 8 特征
    "breadth": [
        "breadth_ma128_align", "breadth_ma128_align_change_20d",
        "breadth_ma128_slope_align", "breadth_ma128_slope_align_change_20d",
        "breadth_dispersion_10d",
        "btc_dominance_change_20d", "btc_dominance_rolling_5d",
        "breadth_new_high_3_ratio_ma20",
    ],
}

DEFAULT_WEIGHTS: Dict[str, float] = {
    "morphology": 2.5,
    "breadth": 1.5,
    "other": 1.0,
}


class RegimePredictor:
    """市场形态 8 态预测器（监督 LGBM）。

    注：Spec 要求「继承 BCRM 2.0 MarketRegimeClassifier」。
    这里不做硬继承以避免 Liskov 违反（父类 fit 为无监督），但保留相同 API：
      - 接收 feature_names_by_gua / lookback_bars 参数
      - 实现 predict_regime_names / get_regime_params
    实际分类引擎为 LGBM（需用户提供标签 y）。
    """

    # 与 labels/regime_labeler.py 保持一致
    REGIME_ORDER: List[str] = [
        "TREND_UP_STRONG",
        "TREND_UP_MILD",
        "RANGE_BOUND",
        "CONSOLIDATION",
        "REVERSAL",
        "VOLATILE_DROP",
        "FOMO_RALLY",
        "DISTRIBUTION",
    ]

    FEATURE_WEIGHT_MORPHOLOGY: float = DEFAULT_WEIGHTS["morphology"]
    FEATURE_WEIGHT_BREADTH: float = DEFAULT_WEIGHTS["breadth"]
    FEATURE_WEIGHT_OTHER: float = DEFAULT_WEIGHTS["other"]

    def __init__(
        self,
        config_path: Optional[str] = None,
        config_dict: Optional[dict] = None,
        # 与父类构造签名保持一致，以实现 spec 语义上的「继承」
        feature_names_by_gua: Optional[Dict[str, List[str]]] = None,
        lookback_bars: int = 20,
    ):
        self.feature_names_by_gua = feature_names_by_gua or {}
        self.lookback_bars = lookback_bars

        self._config = self._load_config(config_path, config_dict)
        self._feature_groups: Dict[str, List[str]] = (
            self._config.get("feature_groups") or dict(DEFAULT_FEATURE_GROUPS)
        )
        self._weights: Dict[str, float] = dict(
            DEFAULT_WEIGHTS, **(self._config.get("feature_weights") or {})
        )

        # LGBM 模型（延迟初始化，避免 import 失败）
        self._model = None
        self._feature_names: List[str] = []
        self._group_idx: Dict[str, List[int]] = {}

        # 父类兼容的 regime params（与 market_regime.DEFAULT_REGIME_PARAMS 对齐）
        try:
            from .market_regime import DEFAULT_REGIME_PARAMS
            self._regime_params = dict(DEFAULT_REGIME_PARAMS)
        except Exception:
            self._regime_params = {}

    # ============================================================
    # 配置加载
    # ============================================================
    def _load_config(
        self, config_path: Optional[str], config_dict: Optional[dict]
    ) -> dict:
        cfg = dict(config_dict) if config_dict else {}
        if config_path and Path(config_path).exists():
            with open(config_path, "r", encoding="utf-8") as f:
                file_cfg = json.load(f)
            # dict 优先级高于文件
            merged = dict(file_cfg)
            merged.update(cfg)
            return merged
        return cfg

    # ============================================================
    # 特征权重（方差放大）
    # ============================================================
    def _resolve_group_indices(self, feature_names: List[str]) -> Dict[str, List[int]]:
        groups = {}
        name_to_idx = {name: i for i, name in enumerate(feature_names)}
        for group_name, cols in self._feature_groups.items():
            idx = [name_to_idx[c] for c in cols if c in name_to_idx]
            if idx:
                groups[group_name] = idx
        # other：未分组的
        grouped_idx = set()
        for v in groups.values():
            grouped_idx.update(v)
        other_idx = [i for i, n in enumerate(feature_names) if i not in grouped_idx]
        if other_idx:
            groups["other"] = other_idx
        return groups

    def _apply_feature_weights(
        self,
        X: np.ndarray,
        feature_names: Optional[List[str]] = None,
    ) -> np.ndarray:
        """按特征组放大方差（形态 × 2.5，广度 × 1.5，其他 × 1.0）。

        参数：
          X: (n_samples, n_features) numpy 数组
          feature_names: 传入时按传入映射；不传时使用 fit 时记录的分组
        """
        if feature_names is not None:
            group_idx = self._resolve_group_indices(feature_names)
        else:
            group_idx = self._group_idx

        Xw = np.asarray(X, dtype=float).copy()
        weights = self._weights
        for group_name, idx in group_idx.items():
            w = weights.get(group_name, 1.0)
            if w == 1.0:
                continue
            if not idx:
                continue
            Xw[:, idx] *= w
        return Xw

    # ============================================================
    # 训练
    # ============================================================
    def fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
        feature_names: Optional[List[str]] = None,
        lgbm_params: Optional[dict] = None,
    ) -> "RegimePredictor":
        """监督训练 LGBM。

        参数：
          X: (n_samples, n_features)
          y: (n_samples,) 字符串或 int（8 态标签）
          feature_names: 列名，用于分组权重
          lgbm_params: 可选，覆盖 LGBM 默认超参
        """
        X_np = np.asarray(X, dtype=float)
        y_np = np.asarray(y)
        if feature_names is None:
            feature_names = [f"f{i}" for i in range(X_np.shape[1])]
        if len(feature_names) != X_np.shape[1]:
            raise ValueError(
                f"feature_names 长度 {len(feature_names)} != X 列数 {X_np.shape[1]}"
            )
        self._feature_names = list(feature_names)
        self._group_idx = self._resolve_group_indices(self._feature_names)

        # 应用特征权重（训练期即放大）
        X_scaled = self._apply_feature_weights(X_np, self._feature_names)

        # 标签编码
        label_set = sorted(self.REGIME_ORDER)
        label_to_code = {name: i for i, name in enumerate(self.REGIME_ORDER)}
        y_codes = []
        for v in y_np:
            s = str(v)
            if s not in label_to_code:
                # 兼容父类的旧标签（BREAKOUT → 映射为 TREND_UP_STRONG）
                if s == "BREAKOUT":
                    y_codes.append(label_to_code["TREND_UP_STRONG"])
                else:
                    raise ValueError(f"未知标签 {s}，期望在 {self.REGIME_ORDER}")
            else:
                y_codes.append(label_to_code[s])
        y_codes = np.asarray(y_codes, dtype=int)

        # 构造 LGBM 参数（小数据友好：减小 leaf 粒度、加大迭代数、类别平衡）
        params = {
            "objective": "multiclass",
            "num_class": len(self.REGIME_ORDER),
            "metric": "multi_logloss",
            "learning_rate": 0.05,
            "num_leaves": 31,
            "feature_fraction": 0.9,
            "bagging_fraction": 0.9,
            "bagging_freq": 3,
            "min_data_in_leaf": 5,
            "lambda_l2": 1.0,
            "class_weight": "balanced",  # 对 8 态不平衡友好
            "verbose": -1,
            "seed": 42,
            "num_boost_round": 600,
        }
        if lgbm_params:
            params.update(lgbm_params)

        try:
            import lightgbm as lgb
            train_data = lgb.Dataset(X_scaled, label=y_codes)
            num_boost_round = int(params.pop("num_boost_round", 600))
            model = lgb.train(
                params,
                train_data,
                num_boost_round=num_boost_round,
                valid_sets=None,
                callbacks=[],
            )
        except ImportError:
            # Fallback: sklearn RandomForestClassifier（天然多分类 + class_weight 平衡）
            from sklearn.ensemble import RandomForestClassifier

            logger.warning("lightgbm 未安装，回退到 sklearn RandomForestClassifier(class_weight=balanced)")
            model = _SklearnMulticlassWrap(
                RandomForestClassifier(
                    n_estimators=400,
                    max_depth=8,
                    min_samples_leaf=3,
                    max_features="sqrt",
                    class_weight="balanced",
                    n_jobs=-1,
                    random_state=42,
                )
            )
            model.fit(X_scaled, y_codes)

        self._model = model
        self._log_feature_importance()
        return self

    def _log_feature_importance(self):
        if self._model is None:
            return
        try:
            # LGBM
            importance = self._model.feature_importance(importance_type="gain")
            order = np.argsort(importance)[::-1][:15]
            msg = "Top15 feature gain:\n"
            for idx in order:
                if idx >= len(importance) or importance[idx] <= 0:
                    continue
                msg += f"  {self._feature_names[idx]}: {float(importance[idx]):.3g}\n"
            logger.info(msg)
        except Exception:
            try:
                # sklearn fallback
                imp = self._model.feature_importances_
                order = np.argsort(imp)[::-1][:15]
                msg = "Top15 feature importance:\n"
                for idx in order:
                    msg += f"  {self._feature_names[idx]}: {float(imp[idx]):.3g}\n"
                logger.info(msg)
            except Exception:
                pass

    # ============================================================
    # 预测
    # ============================================================
    def predict(
        self, X: np.ndarray, feature_names: Optional[List[str]] = None
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """预测 8 态。

        返回：
          y_pred: (n_samples,) str，每个样本一个 REGIME_ORDER 中的标签
          confidence: (n_samples,) float，最大类概率 ∈ [0,1]
          proba: (n_samples, 8) float，每行加总=1，列顺序=REGIME_ORDER
        """
        if self._model is None:
            raise RuntimeError("模型未训练，请先调用 fit()")

        X_np = np.asarray(X, dtype=float)
        fn = feature_names if feature_names is not None else self._feature_names
        X_scaled = self._apply_feature_weights(X_np, fn)

        try:
            # LGBM
            proba = self._model.predict(X_scaled)
        except Exception:
            # sklearn fallback：predict_proba 返回 (n, n_classes)，注意类别顺序
            proba = self._model.predict_proba(X_scaled)
            # 若类别少于 8 类，补零对齐
            n_classes_train = getattr(self._model, "n_classes_train_", proba.shape[1])
            if proba.shape[1] < len(self.REGIME_ORDER):
                classes = getattr(self._model, "classes_", None)
                full = np.zeros((proba.shape[0], len(self.REGIME_ORDER)))
                if classes is not None:
                    for i, c in enumerate(classes):
                        full[:, int(c)] = proba[:, i]
                else:
                    full[:, : proba.shape[1]] = proba
                proba = full

        proba = np.asarray(proba, dtype=float)
        # 归一化
        row_sum = proba.sum(axis=1, keepdims=True)
        row_sum = np.where(row_sum < 1e-12, 1.0, row_sum)
        proba = proba / row_sum

        code = np.argmax(proba, axis=1)
        confidence = proba[np.arange(len(code)), code]
        y_pred = np.array([self.REGIME_ORDER[c] for c in code], dtype=object)
        return y_pred, confidence, proba

    # ============================================================
    # 父类兼容 API（predict_regime_names / get_regime_params）
    # ============================================================
    def predict_regime_names(
        self, X: np.ndarray, feature_names: Optional[List[str]] = None
    ) -> List[str]:
        y_pred, _, _ = self.predict(X, feature_names=feature_names)
        return list(y_pred.tolist())

    def get_regime_params(self, regime_name: str):
        return self._regime_params.get(regime_name)

    def get_all_regime_params(self) -> dict:
        return dict(self._regime_params)

    # ============================================================
    # 持久化
    # ============================================================
    def save(self, path: Union[str, Path]) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            import lightgbm as lgb
            self._model.save_model(str(path.with_suffix(".lgb")))
        except Exception:
            try:
                import joblib
                joblib.dump(self._model, str(path.with_suffix(".skl.joblib")))
            except Exception:
                import pickle
                with path.with_suffix(".pkl").open("wb") as f:
                    pickle.dump(self._model, f)
        meta = {
            "feature_names": self._feature_names,
            "feature_groups": self._feature_groups,
            "weights": self._weights,
            "regime_order": self.REGIME_ORDER,
        }
        with path.with_suffix(".meta.json").open("w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: Union[str, Path]) -> "RegimePredictor":
        path = Path(path)
        meta_path = path.with_suffix(".meta.json")
        if not meta_path.exists():
            raise FileNotFoundError(f"找不到元数据 {meta_path}")
        with meta_path.open("r", encoding="utf-8") as f:
            meta = json.load(f)

        obj = cls(config_dict={
            "feature_groups": meta.get("feature_groups"),
            "feature_weights": meta.get("weights"),
        })
        obj._feature_names = meta["feature_names"]
        obj._group_idx = obj._resolve_group_indices(obj._feature_names)

        lgb_path = path.with_suffix(".lgb")
        skl_path = path.with_suffix(".skl.joblib")
        pkl_path = path.with_suffix(".pkl")
        if lgb_path.exists():
            import lightgbm as lgb
            obj._model = lgb.Booster(model_file=str(lgb_path))
        elif skl_path.exists():
            import joblib
            obj._model = joblib.load(str(skl_path))
        elif pkl_path.exists():
            import pickle
            with pkl_path.open("rb") as f:
                obj._model = pickle.load(f)
        else:
            raise FileNotFoundError(f"找不到模型权重文件：{lgb_path} / {skl_path} / {pkl_path}")
        return obj


class _SklearnMulticlassWrap:
    """将 sklearn classifier 封装成 LGBM 风格接口（fit/predict/predict_proba/feature_importances_）。"""

    def __init__(self, estimator):
        self._est = estimator
        self.feature_importances_ = None
        self.n_classes_train_ = None
        self.classes_ = None

    def fit(self, X, y):
        self._est.fit(X, y)
        self.feature_importances_ = getattr(self._est, "feature_importances_", None)
        self.n_classes_train_ = len(self._est.classes_)
        self.classes_ = self._est.classes_
        return self

    def predict(self, X):
        return self._est.predict_proba(X)

    def predict_proba(self, X):
        return self._est.predict_proba(X)
