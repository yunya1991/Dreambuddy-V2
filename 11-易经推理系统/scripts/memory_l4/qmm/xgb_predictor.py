"""
XGBoost 小模型预测器 — 替换 QMM backtest 的规则预测器。

从 L4 cases 中提取特征（liangyi_state + scale_params + 市场指标），
训练 XGBoost 分类器预测方向(UP/DOWN/FLAT)。

特征工程：
- 力学特征：四象权重(weight_time/space/surface/core) + 体量参数(mass/decay)
- 两仪特征：macro_phase(编码) + micro_phase(编码) + resonance/conflict
- 市场特征：price_position + trend_strength + volatility + volume_ratio
- 四维评分：sd/tech/cf/sent
- 象限特征：quadrant_x + quadrant_y
"""
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# 延迟导入 xgboost
_xgb = None


def _get_xgb():
    global _xgb
    if _xgb is None:
        import xgboost
        _xgb = xgboost
    return _xgb


# 特征名列表
FEATURE_NAMES = [
    # 四象权重
    "weight_time", "weight_space", "weight_surface", "weight_core",
    # 体量参数
    "market_mass_base", "velocity_decay",
    "confidence_threshold", "reversal_threshold",
    # 两仪状态
    "macro_phase_enc", "micro_phase_enc",
    "is_resonance", "is_conflict", "resonance_factor",
    "liangyi_strength",
    # 市场指标
    "price_position", "trend_strength", "volatility",
    "volume_ratio", "scale",
    # 四维评分
    "sd_score", "tech_score", "cf_score", "sent_score",
    # 象限
    "quadrant_x", "quadrant_y",
    # 衍生
    "score_consistency", "score_mean",
    "weight_dominant",  # 最大权重维度 (0=time,1=space,2=surface,3=core)
]

# 分类标签映射
# Bug Y4 修复: 使用二元标签（盈利=1/亏损=0）替代三分类（DOWN=0/FLAT=1/UP=2）
# 原三分类导致 XGBClassifier 期望 [0,1] 但收到 [0,2]，训练报错
LABEL_MAP = {"DOWN": 0, "FLAT": 0, "UP": 1}   # 合并 FLAT 到 DOWN（保守）
LABEL_INVERSE = {0: "DOWN_OR_FLAT", 1: "UP"}

# Phase 编码
MACRO_PHASE_ENC = {"recession": 0, "recovery": 1, "overheat": 2, "stagflation": 3}
MICRO_PHASE_ENC = {"sprout": 0, "growth": 1, "mature": 2, "decline": 3}


def extract_features_from_case(case: Dict[str, Any]) -> Optional[np.ndarray]:
    """从单个 L4 case 提取特征向量。"""
    try:
        sp = case.get("scale_params", {})
        ly = case.get("liangyi_state", {})
        q = case.get("quadrant", {})
        env = case.get("environment_snapshot", {})

        # 四象权重
        w_t = sp.get("weight_time", 0.2)
        w_s = sp.get("weight_space", 0.15)
        w_sf = sp.get("weight_surface", 0.3)
        w_c = sp.get("weight_core", 0.35)

        # 两仪
        macro = ly.get("macro_phase", "recovery")
        micro = ly.get("micro_phase", "sprout")
        is_res = 1.0 if ly.get("is_resonance") else 0.0
        is_conf = 1.0 if ly.get("is_conflict") else 0.0
        res_factor = float(ly.get("resonance_factor", 0))

        # liangyi_strength 可能在不同位置
        ly_strength = float(ly.get("liangyi_strength", 0))
        if ly_strength == 0:
            # 从 liangyi_state 的文字描述里推断
            macro_season = ly.get("macro_season", "")
            micro_season = ly.get("micro_season", "")
            ly_strength = 0.5  # 默认

        # 市场指标
        pp = float(env.get("price_position", ly.get("price_position", 0.5)))
        ts_val = float(env.get("trend_strength", ly.get("trend_strength", 0.5)))
        vol = float(env.get("volatility", 0.5))
        vol_ratio = float(env.get("volume_ratio", 1.0))
        scale = float(sp.get("scale", 0.5))

        # 四维评分
        sd = float(env.get("supply_demand_score", 0.5))
        tech = float(env.get("technical_score", 0.5))
        cf = float(env.get("capital_flow_score", 0.5))
        sent = float(env.get("sentiment_score", 0.5))

        # 象限
        qx = float(q.get("x", 0))
        qy = float(q.get("y", 0))

        # 衍生
        scores = [sd, tech, cf, sent]
        s_mean = sum(scores) / len(scores)
        s_var = sum((s - s_mean) ** 2 for s in scores) / len(scores)
        s_consistency = 1.0 - min(s_var, 1.0)

        weights = [w_t, w_s, w_sf, w_c]
        w_dominant = float(weights.index(max(weights)))

        features = np.array([
            w_t, w_s, w_sf, w_c,
            float(sp.get("market_mass_base", 1.0)),
            float(sp.get("velocity_decay", 0.85)),
            float(sp.get("confidence_threshold", 0.375)),
            float(sp.get("reversal_threshold", 0.175)),
            float(MACRO_PHASE_ENC.get(macro, 1)),
            float(MICRO_PHASE_ENC.get(micro, 0)),
            is_res, is_conf, res_factor,
            ly_strength,
            pp, ts_val, vol, vol_ratio, scale,
            sd, tech, cf, sent,
            qx, qy,
            s_consistency, s_mean,
            w_dominant,
        ], dtype=np.float32)

        return features
    except Exception:
        return None


def extract_label_from_case(case: Dict[str, Any]) -> Optional[int]:
    """从 case 提取标签（方向）。"""
    # 优先用 pnl_pct 推断方向
    pnl = None
    do = case.get("decision_outcome", {})
    ao = case.get("actual_outcome", {})
    pnl = do.get("pnl_pct")
    if pnl is None:
        pnl = ao.get("pnl_pct")

    if pnl is not None:
        if pnl > 0.01:
            return LABEL_MAP["UP"]
        elif pnl < -0.01:
            return LABEL_MAP["DOWN"]
        else:
            return LABEL_MAP["FLAT"]

    # 回退：用 direction + is_correct
    direction = case.get("direction", "")
    is_correct = do.get("is_correct", ao.get("is_correct"))
    if direction and is_correct is not None:
        if is_correct:
            return LABEL_MAP.get(direction.upper(), LABEL_MAP["FLAT"])
        else:
            inv = {"UP": "DOWN", "DOWN": "UP", "LONG": "DOWN", "SHORT": "UP"}
            return LABEL_MAP.get(inv.get(direction.upper(), "FLAT"), LABEL_MAP["FLAT"])

    return None


class QMMPredictor:
    """XGBoost 方向预测器。"""

    def __init__(self, model_path: Optional[str] = None):
        self.model = None
        self.model_path = model_path
        self.feature_names = FEATURE_NAMES
        self.n_features = len(FEATURE_NAMES)

        if model_path and os.path.exists(model_path):
            self.load(model_path)

    def train(
        self,
        cases: List[Dict[str, Any]],
        n_folds: int = 3,
        params: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """训练模型。

        Returns:
            训练统计（交叉验证准确率等）
        """
        xgb = _get_xgb()

        X_list, y_list = [], []
        for c in cases:
            feat = extract_features_from_case(c)
            label = extract_label_from_case(c)
            if feat is not None and label is not None and feat.shape[0] == self.n_features:
                X_list.append(feat)
                y_list.append(label)

        if len(X_list) < 20:
            return {"ok": False, "reason": f"insufficient data: {len(X_list)}"}

        X = np.array(X_list)
        y = np.array(y_list)

        # 默认参数（偏保守，减少过拟合）
        default_params = {
            "objective": "binary:logistic",   # Bug Y4 修复: 改为二元分类
            # "num_class": 3,                 # 已移除，二元不需要
            "max_depth": 3,
            "learning_rate": 0.05,
            "n_estimators": 80,
            "subsample": 0.7,
            "colsample_bytree": 0.7,
            "reg_alpha": 1.0,
            "reg_lambda": 5.0,
            "min_child_weight": 5,
            "random_state": 42,
            "verbosity": 0,
        }
        if params:
            default_params.update(params)

        # 交叉验证
        from sklearn.model_selection import cross_val_score
        clf = xgb.XGBClassifier(**default_params)
        cv_scores = cross_val_score(clf, X, y, cv=min(n_folds, len(set(y))),
                                    scoring="accuracy")

        # 全量训练
        clf.fit(X, y)
        self.model = clf

        # 训练集准确率
        train_pred = clf.predict(X)
        train_acc = (train_pred == y).mean()

        stats = {
            "ok": True,
            "n_samples": len(X),
            "n_features": self.n_features,
            "label_dist": {LABEL_INVERSE[k]: int(v) for k, v in zip(*np.unique(y, return_counts=True))},
            "cv_scores": [round(s, 4) for s in cv_scores],
            "cv_mean": round(float(cv_scores.mean()), 4),
            "cv_std": round(float(cv_scores.std()), 4),
            "train_accuracy": round(float(train_acc), 4),
            "train_test_gap": round(float(train_acc - cv_scores.mean()), 4),
        }

        # 特征重要性
        try:
            importances = clf.feature_importances_
            top_indices = np.argsort(importances)[::-1][:10]
            stats["top_features"] = [
                {"name": FEATURE_NAMES[i], "importance": round(float(importances[i]), 4)}
                for i in top_indices
            ]
        except Exception:
            pass

        return stats

    def predict(self, case: Dict[str, Any]) -> Tuple[str, float]:
        """预测方向 + 置信度。

        Returns:
            (direction, confidence)
        """
        if self.model is None:
            return "FLAT", 0.3

        feat = extract_features_from_case(case)
        if feat is None or feat.shape[0] != self.n_features:
            return "FLAT", 0.3

        X = feat.reshape(1, -1)
        pred_class = self.model.predict(X)[0]
        proba = self.model.predict_proba(X)[0]
        confidence = float(proba[pred_class])

        direction = LABEL_INVERSE.get(int(pred_class), "FLAT")
        uncertainty = 1.0 - confidence

        return direction, uncertainty

    def predict_batch(self, cases: List[Dict[str, Any]]) -> List[Tuple[str, float]]:
        """批量预测。"""
        return [self.predict(c) for c in cases]

    def save(self, path: str) -> bool:
        """保存模型。"""
        if self.model is None:
            return False
        try:
            self.model.save_model(path)
            # 保存元数据
            meta_path = path + ".meta.json"
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump({
                    "n_features": self.n_features,
                    "feature_names": self.feature_names,
                    "label_map": LABEL_MAP,
                }, f, indent=2)
            return True
        except Exception:
            return False

    def load(self, path: str) -> bool:
        """加载模型。"""
        try:
            xgb = _get_xgb()
            clf = xgb.XGBClassifier()
            clf.load_model(path)
            self.model = clf
            return True
        except Exception:
            return False
