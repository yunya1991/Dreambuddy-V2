"""ML模型层

三种模型：
1. LightGBM（默认）— 微软开源，速度快，适合表格数据，量化领域最常用
2. XGBoost — 精度高，可对比LightGBM
3. Logistic Regression — 线性基准，解释性强

参考: 微软 Qlib 的 GBDT model, LightGBM/XGBoost 最佳实践
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
import numpy as np
import pandas as pd


class MLModel(ABC):
    """ML模型基类"""

    def __init__(self, params: Optional[Dict] = None):
        self.params = params or {}
        self.model = None
        self.is_trained = False
        self.feature_names: List[str] = []

    @abstractmethod
    def fit(self, X: pd.DataFrame, y: pd.Series,
            X_val: Optional[pd.DataFrame] = None,
            y_val: Optional[pd.Series] = None) -> "MLModel":
        """训练模型"""
        pass

    @abstractmethod
    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """预测概率（上涨概率）"""
        pass

    def predict(self, X: pd.DataFrame, threshold: float = 0.5) -> np.ndarray:
        """预测类别"""
        proba = self.predict_proba(X)
        return (proba > threshold).astype(int)

    def feature_importance(self) -> pd.Series:
        """特征重要性"""
        if self.model is None or not self.feature_names:
            return pd.Series()
        if hasattr(self.model, 'feature_importances_'):
            return pd.Series(
                self.model.feature_importances_,
                index=self.feature_names
            ).sort_values(ascending=False)
        return pd.Series()

    def save(self, path: str):
        """保存模型"""
        import pickle
        with open(path, 'wb') as f:
            pickle.dump({
                'model': self.model,
                'params': self.params,
                'feature_names': self.feature_names,
                'is_trained': self.is_trained,
            }, f)

    @classmethod
    def load(cls, path: str) -> "MLModel":
        """加载模型"""
        import pickle
        with open(path, 'rb') as f:
            data = pickle.load(f)
        instance = cls(params=data['params'])
        instance.model = data['model']
        instance.feature_names = data['feature_names']
        instance.is_trained = data['is_trained']
        return instance


class LightGBMModel(MLModel):
    """LightGBM 分类模型

    微软开源的梯度提升框架，速度快、内存低、精度高，
    是量化多因子模型的标配。
    """

    def __init__(self, params: Optional[Dict] = None):
        default_params = {
            'objective': 'binary',
            'metric': 'binary_logloss',
            'boosting_type': 'gbdt',
            'num_leaves': 31,
            'learning_rate': 0.05,
            'feature_fraction': 0.8,
            'bagging_fraction': 0.8,
            'bagging_freq': 5,
            'min_data_in_leaf': 20,
            'max_depth': -1,
            'lambda_l1': 0.0,
            'lambda_l2': 0.0,
            'verbose': -1,
            'n_estimators': 200,
            'early_stopping_rounds': 30,
            'random_state': 42,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)

    def fit(self, X, y, X_val=None, y_val=None):
        import lightgbm as lgb

        self.feature_names = list(X.columns)

        train_data = lgb.Dataset(X, label=y)
        valid_sets = [train_data]
        valid_names = ['train']

        if X_val is not None and y_val is not None:
            val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)
            valid_sets.append(val_data)
            valid_names.append('valid')

        n_estimators = self.params.pop('n_estimators', 200)
        early_stopping = self.params.pop('early_stopping_rounds', None)
        verbose = self.params.get('verbose', -1)

        callbacks = []
        if early_stopping:
            callbacks.append(lgb.early_stopping(early_stopping))

        self.model = lgb.train(
            self.params,
            train_data,
            num_boost_round=n_estimators,
            valid_sets=valid_sets,
            valid_names=valid_names,
            callbacks=callbacks,
        )

        self.is_trained = True
        self.params['n_estimators'] = n_estimators
        self.params['early_stopping_rounds'] = early_stopping
        self.params['verbose'] = verbose
        return self

    def predict_proba(self, X):
        if self.model is None:
            raise ValueError("模型未训练")
        return self.model.predict(X)


class XGBoostModel(MLModel):
    """XGBoost 分类模型

    精度高，正则化强，适合样本量中等的情况。
    """

    def __init__(self, params: Optional[Dict] = None):
        default_params = {
            'objective': 'binary:logistic',
            'eval_metric': 'logloss',
            'booster': 'gbtree',
            'max_depth': 6,
            'learning_rate': 0.05,
            'n_estimators': 200,
            'subsample': 0.8,
            'colsample_bytree': 0.8,
            'min_child_weight': 1,
            'gamma': 0,
            'reg_alpha': 0,
            'reg_lambda': 1,
            'random_state': 42,
            'early_stopping_rounds': 30,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)

    def fit(self, X, y, X_val=None, y_val=None):
        import xgboost as xgb

        self.feature_names = list(X.columns)

        n_estimators = self.params.pop('n_estimators', 200)
        early_stopping = self.params.pop('early_stopping_rounds', None)

        eval_set = [(X, y)]
        if X_val is not None and y_val is not None:
            eval_set.append((X_val, y_val))

        self.model = xgb.XGBClassifier(
            **self.params,
            n_estimators=n_estimators,
            early_stopping_rounds=early_stopping,
            verbosity=0,
        )
        self.model.fit(X, y, eval_set=eval_set, verbose=False)

        self.is_trained = True
        self.params['n_estimators'] = n_estimators
        self.params['early_stopping_rounds'] = early_stopping
        return self

    def predict_proba(self, X):
        if self.model is None:
            raise ValueError("模型未训练")
        return self.model.predict_proba(X)[:, 1]


class LogisticModel(MLModel):
    """Logistic Regression 线性基准模型

    解释性强，作为ML模型的基准线。
    """

    def __init__(self, params: Optional[Dict] = None):
        default_params = {
            'C': 1.0,
            'max_iter': 1000,
            'solver': 'lbfgs',
            'random_state': 42,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)

    def fit(self, X, y, X_val=None, y_val=None):
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler

        self.feature_names = list(X.columns)

        self.scaler = StandardScaler()
        X_scaled = self.scaler.fit_transform(X)

        self.model = LogisticRegression(**self.params)
        self.model.fit(X_scaled, y)

        self.is_trained = True
        return self

    def predict_proba(self, X):
        if self.model is None:
            raise ValueError("模型未训练")
        X_scaled = self.scaler.transform(X)
        return self.model.predict_proba(X_scaled)[:, 1]

    def feature_importance(self) -> pd.Series:
        if self.model is None or not self.feature_names:
            return pd.Series()
        return pd.Series(
            np.abs(self.model.coef_[0]),
            index=self.feature_names
        ).sort_values(ascending=False)

    def save(self, path: str):
        import pickle
        with open(path, 'wb') as f:
            pickle.dump({
                'model': self.model,
                'scaler': getattr(self, 'scaler', None),
                'params': self.params,
                'feature_names': self.feature_names,
                'is_trained': self.is_trained,
            }, f)

    @classmethod
    def load(cls, path: str) -> "LogisticModel":
        import pickle
        with open(path, 'rb') as f:
            data = pickle.load(f)
        instance = cls(params=data['params'])
        instance.model = data['model']
        instance.scaler = data.get('scaler')
        instance.feature_names = data['feature_names']
        instance.is_trained = data['is_trained']
        return instance


def create_model(model_type: str = 'lightgbm', params: Optional[Dict] = None) -> MLModel:
    """工厂函数：创建模型实例

    参数:
        model_type: 'lightgbm' | 'xgboost' | 'logistic'
        params: 模型参数
    """
    models = {
        'lightgbm': LightGBMModel,
        'xgboost': XGBoostModel,
        'logistic': LogisticModel,
    }
    if model_type not in models:
        raise ValueError(f"未知模型类型: {model_type}, 可选: {list(models.keys())}")
    return models[model_type](params)
