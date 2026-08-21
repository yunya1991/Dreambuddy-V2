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
    # MA200 牛熊分界 + 价格驱动周期特征 10 列（v2：移除 halving 日期）
    "ma200_cycle": [
        "ma200_distance_pct", "ma200_above", "ma200_slope_20d",
        "cycle_distance_from_365d_high", "cycle_distance_from_365d_low",
        "cycle_position_in_range", "cycle_time_since_peak",
        "cycle_momentum_180d", "cycle_vol_regime_90d", "cycle_trend_365d",
    ],
    # 多时间框架特征 6 列
    "multi_timeframe": [
        "ma_alignment_score", "ma_cross_50_200_signal",
        "log_ret_30d", "log_ret_90d",
        "vol_60d_percentile_252d", "volume_ma20_ratio",
    ],
}

DEFAULT_WEIGHTS: Dict[str, float] = {
    "morphology": 2.5,
    "breadth": 1.5,
    "ma200_cycle": 2.0,        # MA200+周期：经典经验，高权重
    "multi_timeframe": 1.8,    # 多时间框架：跨周期结构，较高权重
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
        # Phase 4: S6 开关（BOCPD + HMM 集成，默认关闭）
        enable_bocpd_hmm: bool = False,
        ensemble_alpha: float = 0.7,
        # Phase 5: S7 开关（外部数据源，默认关闭）
        enable_external_data: bool = False,
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

        # Phase 4: S6 开关 + HMM 模型 + 集成参数
        self.enable_bocpd_hmm = enable_bocpd_hmm
        self.ensemble_alpha = ensemble_alpha  # α=0.7（LGBM 主导）
        self.hmm_model = None  # HMMRegime 实例，由外部 set 或 predict_with_ensemble 内部加载

        # Phase 5: S7 开关（外部数据源，默认关闭）
        self.enable_external_data = enable_external_data
        self._external_data: Optional[dict] = None  # 外部数据缓存

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

        # ============================================================
        # 训练引擎选择（OPT-4 升级）：
        # 首选 LightGBM（强正则 + 早停），配合 sample_weight 平衡类别。
        # LightGBM 优势：
        #   1. 非线性判别力强于 LogisticRegression，能捕捉特征交互
        #   2. 通过 num_leaves/min_data_in_leaf/lambda_l1/l2 强正则防过拟合
        #   3. 原生支持 sample_weight，类别平衡更自然
        #   4. feature_importance 可解释
        # 回退：LightGBM 不可用时，使用 sklearn LogisticRegression。
        # ============================================================
        if lgbm_params is None:
            lgbm_params = {}

        # 类别平衡 sample_weight（class_weight='balanced' 公式）
        counts = np.bincount(y_codes, minlength=len(self.REGIME_ORDER)).astype(float)
        counts = np.where(counts == 0, 1.0, counts)
        weights_per_class = len(y_codes) / (len(self.REGIME_ORDER) * counts)
        sample_w = weights_per_class[y_codes]

        used_lgbm = False
        try:
            import lightgbm as lgb

            # LightGBM 强正则参数（防止训练 0.9 / 测试 0.0 的过拟合）
            params = {
                "objective": "multiclass",
                "num_class": len(self.REGIME_ORDER),
                "metric": "multi_logloss",
                "learning_rate": 0.03,
                "num_leaves": 15,               # 限制叶节点数防过拟合
                "feature_fraction": 0.85,        # 特征采样
                "bagging_fraction": 0.85,        # 样本采样
                "bagging_freq": 5,
                "min_data_in_leaf": 20,           # 叶节点最小样本数
                "lambda_l1": 1.0,                 # L1 正则
                "lambda_l2": 5.0,                 # L2 正则
                "max_depth": 6,                   # 限制树深
                "min_gain_to_split": 0.01,       # 最小分裂增益
                "verbose": -1,
                "seed": 42,
                "num_boost_round": 400,
            }
            params.update(lgbm_params)
            num_boost_round = int(params.pop("num_boost_round", 400))

            # 早停：20% 数据做验证，50 轮无提升则停止
            from sklearn.model_selection import train_test_split
            if len(X_scaled) > 100:
                X_tr, X_val, y_tr, y_val, w_tr, w_val = train_test_split(
                    X_scaled, y_codes, sample_w, test_size=0.2,
                    random_state=42, stratify=y_codes if len(np.unique(y_codes)) > 1 else None
                )
                train_data = lgb.Dataset(X_tr, label=y_tr, weight=w_tr)
                valid_data = lgb.Dataset(X_val, label=y_val, weight=w_val, reference=train_data)
                model = lgb.train(
                    params,
                    train_data,
                    num_boost_round=num_boost_round,
                    valid_sets=[valid_data],
                    valid_names=["valid"],
                    callbacks=[
                        lgb.early_stopping(stopping_rounds=30, verbose=False),
                        lgb.log_evaluation(period=0),
                    ],
                )
                # 用全量数据重训到早停轮数
                best_round = model.best_iteration or num_boost_round
                train_data_full = lgb.Dataset(X_scaled, label=y_codes, weight=sample_w)
                model = lgb.train(
                    params,
                    train_data_full,
                    num_boost_round=int(best_round),
                    valid_sets=None,
                    callbacks=[lgb.log_evaluation(period=0)],
                )
            else:
                train_data = lgb.Dataset(X_scaled, label=y_codes, weight=sample_w)
                model = lgb.train(
                    params,
                    train_data,
                    num_boost_round=num_boost_round,
                    valid_sets=None,
                    callbacks=[],
                )
            used_lgbm = True
        except ImportError:
            # 回退：sklearn LogisticRegression
            from sklearn.linear_model import LogisticRegression

            lr_params = dict(
                multi_class="ovr",
                class_weight="balanced",
                C=1.0,
                max_iter=3000,
                solver="liblinear",
                random_state=42,
            )
            if "lr_C" in lgbm_params:
                lr_params["C"] = float(lgbm_params.pop("lr_C"))
            model = _SklearnMulticlassWrap(LogisticRegression(**lr_params))
            model.fit(X_scaled, y_codes)

        self._used_lgbm = used_lgbm
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
    # Phase 4: LGBM + HMM 集成
    # ============================================================
    def predict_with_ensemble(
        self,
        X_lgbm: np.ndarray,
        X_hmm: np.ndarray,
        feature_names: Optional[List[str]] = None,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """LGBM + HMM 集成预测

        Spec §7.3:
            final_prob = α × P_LGBM + (1-α) × P_HMM
            α = 0.7（LGBM 主导，可通过 WalkForward 调参）

        Args:
            X_lgbm: (n_samples, n_features) LGBM 特征矩阵
            X_hmm: (n_samples, n_features_hmm) HMM 特征矩阵（可与 X_lgbm 相同）
            feature_names: 可选列名（传给 LGBM 权重映射）

        Returns:
            y_pred: (n_samples,) str — 每个样本一个 REGIME_ORDER 标签
            confidence: (n_samples,) float — 最大类概率 ∈ [0,1]
            proba: (n_samples, 8) float — 每行加总=1
        """
        if not self.enable_bocpd_hmm or self.hmm_model is None:
            # S6 关闭 / HMM 未训练 → 降级为纯 LGBM
            return self.predict(X_lgbm, feature_names=feature_names)

        # 1. LGBM 概率
        _, _, p_lgbm = self.predict(X_lgbm, feature_names=feature_names)
        # p_lgbm: (n, 8) 归一化

        # 1.1 LGBM 温度 sharpening：LogisticRegression 输出概率常过于分散
        #     （max≈0.3-0.4），在 8 分类下无法有效主导 argmax。
        #     对 log 概率 ×T（T=3）使分布更尖锐，提升高置信样本的 max prob。
        #     这是集成前的概率校准步骤，不改变 argmax（sharpening 是单调变换）。
        T_sharp = 3.0
        log_lgbm = np.log(np.clip(p_lgbm, 1e-12, 1.0))
        p_lgbm = np.exp(log_lgbm * T_sharp)
        row_sum = p_lgbm.sum(axis=1, keepdims=True)
        row_sum = np.where(row_sum < 1e-12, 1.0, row_sum)
        p_lgbm = p_lgbm / row_sum

        # 2. HMM 概率
        p_hmm = self.hmm_model.predict_proba(X_hmm)
        # p_hmm: (n, 8) 归一化
        # 对齐列数
        if p_hmm.shape[1] != len(self.REGIME_ORDER):
            full = np.zeros((p_hmm.shape[0], len(self.REGIME_ORDER)))
            n = min(p_hmm.shape[1], len(self.REGIME_ORDER))
            full[:, :n] = p_hmm[:, :n]
            p_hmm = full
        # 归一化
        row_sum = p_hmm.sum(axis=1, keepdims=True)
        row_sum = np.where(row_sum < 1e-12, 1.0, row_sum)
        p_hmm = p_hmm / row_sum

        # 2.1 HMM 温度平滑：无监督训练输出概率常接近 one-hot（max≈0.98+），
        #     混合 50% 均匀分布软化到 max≈0.56，避免 HMM 硬概率主导 argmax。
        #     HMM 在此仅作为时序先验修正，不应覆盖 LGBM 的特征判别。
        eps_smooth = 0.5
        p_hmm = (1.0 - eps_smooth) * p_hmm + eps_smooth / len(self.REGIME_ORDER)

        # 3. 集成: final_prob = α × P_LGBM + (1-α) × P_HMM
        alpha = self.ensemble_alpha
        final_prob = alpha * p_lgbm + (1.0 - alpha) * p_hmm

        # 4. 归一化 + argmax
        row_sum = final_prob.sum(axis=1, keepdims=True)
        row_sum = np.where(row_sum < 1e-12, 1.0, row_sum)
        final_prob = final_prob / row_sum

        code = np.argmax(final_prob, axis=1)
        confidence = final_prob[np.arange(len(code)), code]
        y_pred = np.array([self.REGIME_ORDER[c] for c in code], dtype=object)
        return y_pred, confidence, final_prob

    # ============================================================
    # Phase 5: 外部数据源（S7 开关）
    # ============================================================
    def set_external_data(self, data: dict) -> "RegimePredictor":
        """注入外部数据源数据

        Spec §8 — S7 打开时，外部数据（USDT 市值、BTC.D、VIX、F&G）
        通过此方法注入，用于：
          1. 替代代理特征（如 stablecoin_inflow_proxy → 真实 USDT 市值变化）
          2. 作为附加特征参与预测

        Args:
            data: 外部数据 dict，典型字段：
                  - usdt_market_cap: USDT 总市值（USD）
                  - btc_dominance: BTC 市占率（%）
                  - vix: VIX 恐慌指数
                  - fear_greed_index: 恐慌贪婪指数（0-100）

        Returns:
            self
        """
        self._external_data = dict(data)
        logger.info(f"S7 外部数据已注入: {list(self._external_data.keys())}")
        return self

    def get_external_data(self) -> Optional[dict]:
        """获取已注入的外部数据"""
        return self._external_data

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
