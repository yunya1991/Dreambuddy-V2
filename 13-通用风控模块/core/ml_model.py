"""
ML 风控模型集成框架
===================
支持加载和推理多种模型类型（xgb / sklearn / committee），
为 L1 评估提供 p_tail / p_move 概率。

模型加载模式与 ml_trade_service.py 的 _gtw_path_model_predict 对齐：
    meta JSON → 模型加载 → 特征对齐 → 预测 → 概率输出
"""

import os
import json
import pickle
from typing import Dict, Any, Optional, List, Union
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ModelPrediction:
    """模型预测结果"""
    p_tail: Optional[float] = None
    p_move: Optional[float] = None
    confidence: float = 0.0
    model_name: str = ""
    model_version: str = ""
    raw_output: Any = None
    details: Dict[str, Any] = field(default_factory=dict)


class MLRiskModel:
    """ML 风控模型适配器

    支持:
        - sklearn pickle 模型 (lr / rf / xgb sklearn)
        - xgb Booster 模型
        - committee 多模型加权

    使用方式:
        model = MLRiskModel.load_from_meta("path/to/meta.json")
        pred = model.predict(features_dict)
        print(pred.p_tail, pred.p_move)
    """

    def __init__(
        self,
        model: Any = None,
        model_type: str = "sklearn_pickle",
        feature_names: Optional[List[str]] = None,
        name: str = "",
        version: str = "",
    ):
        self.model = model
        self.model_type = model_type
        self.feature_names = feature_names or []
        self.name = name
        self.version = version
        self._loaded = model is not None

    @classmethod
    def load_from_meta(cls, meta_path: str) -> "MLRiskModel":
        """从 meta JSON 文件加载模型

        meta JSON 格式（与 committee_meta.json 对齐）:
        {
            "model_type": "xgb" | "sklearn_pickle",
            "model_path": "/path/to/model.pkl",
            "feature_names": ["feat1", "feat2", ...],
            "latest_version": 1
        }
        """
        try:
            with open(meta_path) as f:
                meta = json.load(f)
        except Exception as e:
            return cls(name="error", version="0")

        model_type = meta.get("model_type", "sklearn_pickle")
        model_path = meta.get("model_path", "")
        feature_names = meta.get("feature_names", [])
        version = str(meta.get("latest_version", "1"))
        name = Path(meta_path).stem

        if not model_path or not os.path.exists(model_path):
            return cls(name=name, version=version, feature_names=feature_names)

        model = None
        try:
            if model_type == "xgb":
                import xgboost as xgb
                booster = xgb.Booster()
                booster.load_model(model_path)
                model = booster
            else:
                with open(model_path, "rb") as pf:
                    model = pickle.load(pf)
        except Exception:
            pass

        return cls(
            model=model,
            model_type=model_type,
            feature_names=feature_names,
            name=name,
            version=version,
        )

    @property
    def is_loaded(self) -> bool:
        return self._loaded and self.model is not None

    def predict(self, features: Dict[str, float]) -> ModelPrediction:
        """执行预测

        Args:
            features: 特征字典 {feature_name: value}

        Returns:
            ModelPrediction 预测结果
        """
        result = ModelPrediction(model_name=self.name, model_version=self.version)

        if not self.is_loaded:
            return result

        try:
            if self.model_type == "xgb":
                return self._predict_xgb(features, result)
            else:
                return self._predict_sklearn(features, result)
        except Exception as e:
            result.details["error"] = str(e)
            return result

    def _predict_xgb(self, features: Dict[str, float], result: ModelPrediction) -> ModelPrediction:
        """XGBoost Booster 预测"""
        import xgboost as xgb

        ordered = []
        for fn in self.feature_names:
            ordered.append(float(features.get(fn, 0.0)))

        dm = xgb.DMatrix([ordered], feature_names=self.feature_names)
        raw = self.model.predict(dm)
        proba = float(raw[0])

        result.p_tail = max(0.0, min(1.0, proba))
        result.confidence = max(0.0, min(1.0, abs(proba - 0.5) * 2.0))
        result.raw_output = proba
        result.details["method"] = "xgb_booster"
        return result

    def _predict_sklearn(self, features: Dict[str, float], result: ModelPrediction) -> ModelPrediction:
        """sklearn 模型预测"""
        ordered = []
        for fn in self.feature_names:
            ordered.append(float(features.get(fn, 0.0)))

        model = self.model

        if hasattr(model, "predict_proba"):
            proba = model.predict_proba([ordered])
            if proba.shape[1] >= 2:
                p = float(proba[0][1])
            else:
                p = float(proba[0][0])
        elif hasattr(model, "predict"):
            p = float(model.predict([ordered])[0])
        else:
            return result

        p = max(0.0, min(1.0, p))
        result.p_tail = p
        result.confidence = max(0.0, min(1.0, abs(p - 0.5) * 2.0))
        result.raw_output = p
        result.details["method"] = "sklearn"
        return result


class CommitteeModel:
    """Committee 多模型加权集成

    加载多个子模型，加权平均后输出 p_tail / p_move。

    使用方式:
        committee = CommitteeModel()
        committee.add_member(MLRiskModel.load_from_meta("tail_meta.json"), weight=0.6)
        committee.add_member(MLRiskModel.load_from_meta("move_meta.json"), weight=0.4)
        pred = committee.predict(features)
    """

    def __init__(self, name: str = "committee"):
        self.name = name
        self.members: List[tuple] = []  # [(MLRiskModel, weight), ...]

    def add_member(self, model: MLRiskModel, weight: float = 1.0):
        """添加子模型"""
        self.members.append((model, weight))

    @property
    def is_loaded(self) -> bool:
        return any(m.is_loaded for m, _ in self.members)

    def predict(self, features: Dict[str, float]) -> ModelPrediction:
        """Committee 加权预测"""
        result = ModelPrediction(model_name=self.name)

        if not self.members:
            return result

        total_weight = 0.0
        weighted_p_tail = 0.0
        weighted_p_move = 0.0
        has_tail = False
        has_move = False
        member_results = []

        for model, weight in self.members:
            if not model.is_loaded:
                member_results.append({"name": model.name, "loaded": False})
                continue

            pred = model.predict(features)
            member_results.append({
                "name": model.name,
                "loaded": True,
                "p_tail": pred.p_tail,
                "p_move": pred.p_move,
                "weight": weight,
            })

            if pred.p_tail is not None:
                weighted_p_tail += pred.p_tail * weight
                total_weight += weight
                has_tail = True

            if pred.p_move is not None:
                weighted_p_move += pred.p_move * weight
                has_move = True

        if has_tail and total_weight > 0:
            result.p_tail = max(0.0, min(1.0, weighted_p_tail / total_weight))
            result.confidence = max(0.0, min(1.0, abs(result.p_tail - 0.5) * 2.0))

        if has_move and total_weight > 0:
            result.p_move = max(0.0, min(1.0, weighted_p_move / total_weight))

        result.details["members"] = member_results
        result.details["method"] = "committee_weighted"
        return result


class MLModelRegistry:
    """ML 模型注册表 — 管理多个风控模型

    使用方式:
        registry = MLModelRegistry()
        registry.load_model("tail", "path/to/tail_meta.json")
        registry.load_committee("committee", [
            ("path/to/tail_meta.json", 0.6),
            ("path/to/move_meta.json", 0.4),
        ])

        model = registry.get_model("tail")
        pred = model.predict(features)
    """

    def __init__(self):
        self._models: Dict[str, Union[MLRiskModel, CommitteeModel]] = {}

    def load_model(self, name: str, meta_path: str) -> bool:
        """加载单个模型"""
        model = MLRiskModel.load_from_meta(meta_path)
        self._models[name] = model
        return model.is_loaded

    def load_committee(self, name: str, members: List[tuple]) -> bool:
        """加载 Committee 模型

        Args:
            name: 注册名称
            members: [(meta_path, weight), ...]
        """
        committee = CommitteeModel(name=name)
        for meta_path, weight in members:
            model = MLRiskModel.load_from_meta(meta_path)
            committee.add_member(model, weight)
        self._models[name] = committee
        return committee.is_loaded

    def register_model(self, name: str, model: Union[MLRiskModel, CommitteeModel]):
        """直接注册已加载的模型"""
        self._models[name] = model

    def get_model(self, name: str) -> Optional[Union[MLRiskModel, CommitteeModel]]:
        """获取模型"""
        return self._models.get(name)

    def predict(self, name: str, features: Dict[str, float]) -> ModelPrediction:
        """使用指定模型预测"""
        model = self._models.get(name)
        if model is None:
            return ModelPrediction(model_name=name)
        return model.predict(features)

    def list_models(self) -> Dict[str, Dict[str, Any]]:
        """列出所有模型"""
        result = {}
        for name, model in self._models.items():
            result[name] = {
                "type": type(model).__name__,
                "loaded": model.is_loaded,
                "name": model.name,
            }
            if isinstance(model, CommitteeModel):
                result[name]["members"] = len(model.members)
        return result
