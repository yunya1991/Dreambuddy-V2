"""ML模型层

模型列表：
1. LightGBM（默认）— 微软开源，速度快，适合表格数据，量化领域最常用
2. XGBoost — 精度高，可对比LightGBM
3. Logistic Regression — 线性基准，解释性强
4. LSTM — 长短期记忆网络，时序预测，缓解过拟合（V6.0+）

参考: 微软 Qlib 的 GBDT model, LightGBM/XGBoost 最佳实践
PyTorch LSTM: 用于时序特征的序列建模，有效缓解过拟合
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


class LSTMModel(MLModel):
    """LSTM 时序分类模型（V6.0+）

    基于PyTorch的长短期记忆网络，用于时序特征的序列建模。
    优势：有效缓解过拟合（训练AUC从1.0降至~0.97），同时保持/提升测试AUC。

    Config1最佳参数（V6.0基线）：
        hidden_dim=32, num_layers=2, dropout=0.5
        weight_decay=0.01, epochs=15, seq_length=20
    """

    def __init__(self, params: Optional[Dict] = None):
        default_params = {
            'hidden_dim': 32,
            'num_layers': 2,
            'dropout': 0.5,
            'weight_decay': 0.01,
            'lr': 0.001,
            'batch_size': 32,
            'epochs': 15,
            'patience': 5,
            'seq_length': 20,
            'pos_weight': True,
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)

    def _build_model(self, input_dim: int):
        import torch
        import torch.nn as nn

        class LSTMNet(nn.Module):
            def __init__(self, input_dim, hidden_dim, num_layers, dropout):
                super(LSTMNet, self).__init__()
                self.input_dropout = nn.Dropout(dropout * 0.5)
                self.lstm = nn.LSTM(
                    input_dim, hidden_dim, num_layers,
                    batch_first=True,
                    dropout=dropout if num_layers > 1 else 0
                )
                self.fc = nn.Sequential(
                    nn.Linear(hidden_dim, 16),
                    nn.ReLU(),
                    nn.Dropout(dropout),
                    nn.Linear(16, 1),
                    nn.Sigmoid()
                )

            def forward(self, x):
                x = self.input_dropout(x)
                out, _ = self.lstm(x)
                out = out[:, -1, :]
                return self.fc(out).squeeze()

        return LSTMNet(
            input_dim,
            self.params['hidden_dim'],
            self.params['num_layers'],
            self.params['dropout']
        )

    def _create_sequences(self, X: np.ndarray, y: Optional[np.ndarray] = None):
        seq_len = self.params['seq_length']
        n = len(X)
        X_seqs = []
        y_seqs = []

        for i in range(seq_len, n):
            X_seqs.append(X[i - seq_len:i])
            if y is not None:
                y_seqs.append(y[i])

        X_seqs = np.array(X_seqs, dtype=np.float32)
        if y is not None:
            y_seqs = np.array(y_seqs, dtype=np.float32)
            return X_seqs, y_seqs
        return X_seqs

    def fit(self, X, y, X_val=None, y_val=None):
        import torch
        import torch.nn as nn
        import torch.optim as optim
        from torch.utils.data import DataLoader, TensorDataset

        self.feature_names = list(X.columns)
        input_dim = len(self.feature_names)

        if not hasattr(self, 'scaler'):
            from sklearn.preprocessing import StandardScaler
            self.scaler = StandardScaler()
            X_scaled = self.scaler.fit_transform(X)
        else:
            X_scaled = self.scaler.transform(X)

        X_train_seqs, y_train_seqs = self._create_sequences(X_scaled, y.values)

        X_val_seqs = None
        y_val_seqs = None
        if X_val is not None and y_val is not None:
            X_val_scaled = self.scaler.transform(X_val)
            X_val_seqs, y_val_seqs = self._create_sequences(X_val_scaled, y_val.values)

        self.model = self._build_model(input_dim)

        pos_weight_val = 1.0
        if self.params.get('pos_weight'):
            pos_count = max((y_train_seqs > 0.5).sum(), 1)
            neg_count = len(y_train_seqs) - pos_count
            pos_weight_val = neg_count / pos_count

        criterion = nn.BCELoss()
        optimizer = optim.Adam(
            self.model.parameters(),
            lr=self.params['lr'],
            weight_decay=self.params['weight_decay']
        )

        train_dataset = TensorDataset(
            torch.FloatTensor(X_train_seqs),
            torch.FloatTensor(y_train_seqs)
        )
        train_loader = DataLoader(
            train_dataset,
            batch_size=self.params['batch_size'],
            shuffle=True
        )

        best_val_loss = float('inf')
        patience_counter = 0
        best_state = None
        pos_weight_tensor = torch.tensor([pos_weight_val], dtype=torch.float32)

        for epoch in range(self.params['epochs']):
            self.model.train()
            for X_batch, y_batch in train_loader:
                optimizer.zero_grad()
                outputs = self.model(X_batch)
                weight = torch.where(
                    y_batch > 0.5,
                    pos_weight_tensor,
                    torch.ones_like(y_batch)
                )
                loss = nn.functional.binary_cross_entropy(outputs, y_batch, weight=weight)
                loss.backward()
                optimizer.step()

            if X_val_seqs is not None and y_val_seqs is not None:
                self.model.eval()
                with torch.no_grad():
                    val_outputs = self.model(torch.FloatTensor(X_val_seqs))
                    val_loss = nn.functional.binary_cross_entropy(
                        val_outputs, torch.FloatTensor(y_val_seqs)
                    ).item()
                if val_loss < best_val_loss:
                    best_val_loss = val_loss
                    patience_counter = 0
                    best_state = {k: v.clone() for k, v in self.model.state_dict().items()}
                else:
                    patience_counter += 1
                    if patience_counter >= self.params['patience']:
                        break
            else:
                best_state = {k: v.clone() for k, v in self.model.state_dict().items()}

        if best_state is not None:
            self.model.load_state_dict(best_state)

        self.is_trained = True
        return self

    def predict_proba(self, X):
        import torch
        if self.model is None:
            raise ValueError("模型未训练")

        X_scaled = self.scaler.transform(X)
        X_seqs = self._create_sequences(X_scaled)

        self.model.eval()
        with torch.no_grad():
            preds = self.model(torch.FloatTensor(X_seqs)).numpy()

        seq_len = self.params['seq_length']
        full_preds = np.zeros(len(X))
        full_preds[:seq_len] = 0.5
        full_preds[seq_len:] = preds
        return full_preds

    def feature_importance(self) -> pd.Series:
        return pd.Series(dtype=float)

    def save(self, path: str):
        import pickle
        import torch
        state_dict = self.model.state_dict() if self.model else None
        state_dict_cpu = {}
        if state_dict:
            for k, v in state_dict.items():
                state_dict_cpu[k] = v.cpu().clone()

        with open(path, 'wb') as f:
            pickle.dump({
                'model_type': 'lstm',
                'state_dict': state_dict_cpu,
                'scaler': getattr(self, 'scaler', None),
                'params': self.params,
                'feature_names': self.feature_names,
                'is_trained': self.is_trained,
            }, f)

    @classmethod
    def load(cls, path: str) -> "LSTMModel":
        import pickle
        with open(path, 'rb') as f:
            data = pickle.load(f)
        instance = cls(params=data['params'])
        instance.feature_names = data['feature_names']
        instance.is_trained = data['is_trained']
        instance.scaler = data.get('scaler')

        if data.get('state_dict') and instance.feature_names:
            input_dim = len(instance.feature_names)
            instance.model = instance._build_model(input_dim)
            instance.model.load_state_dict(data['state_dict'])

        return instance


def create_model(model_type: str = 'lightgbm', params: Optional[Dict] = None) -> MLModel:
    """工厂函数：创建模型实例

    参数:
        model_type: 'lightgbm' | 'xgboost' | 'logistic' | 'lstm'
        params: 模型参数
    """
    models = {
        'lightgbm': LightGBMModel,
        'xgboost': XGBoostModel,
        'logistic': LogisticModel,
        'lstm': LSTMModel,
    }
    if model_type not in models:
        raise ValueError(f"未知模型类型: {model_type}, 可选: {list(models.keys())}")
    return models[model_type](params)
