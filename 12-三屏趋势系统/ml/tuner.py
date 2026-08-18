"""模型调优器

结合 Optuna 超参搜索 + Walk-Forward 交叉验证，
找到在滚动验证下最优的超参数组合。

参考: 微软 Qlib 的滚动验证, Optuna 贝叶斯优化
"""

from typing import Dict, List, Optional, Any, Callable
import numpy as np
import pandas as pd
from .models import MLModel, create_model


class ModelTuner:
    """模型调优器

    支持两种调优方式：
    1. Walk-Forward 交叉验证（推荐，更接近实盘）
    2. 简单训练/验证集分割
    """

    def __init__(
        self,
        model_type: str = 'lightgbm',
        n_trials: int = 50,
        direction: str = 'maximize',
        metric: str = 'accuracy',
        train_window: int = 180,
        test_window: int = 30,
        step_size: int = 30,
        random_state: int = 42,
    ):
        """
        参数:
            model_type: 模型类型
            n_trials: Optuna试验次数
            direction: 'maximize' or 'minimize'
            metric: 优化指标 'accuracy' | 'sharpe' | 'roc_auc' | 'f1'
            train_window: Walk-Forward训练窗口大小
            test_window: Walk-Forward测试窗口大小
            step_size: 每次滚动步长
        """
        self.model_type = model_type
        self.n_trials = n_trials
        self.direction = direction
        self.metric = metric
        self.train_window = train_window
        self.test_window = test_window
        self.step_size = step_size
        self.random_state = random_state
        self.best_params: Dict = {}
        self.best_score: float = 0.0

    def _get_param_space(self, trial) -> Dict:
        """根据模型类型获取参数搜索空间"""
        if self.model_type == 'lightgbm':
            return {
                'num_leaves': trial.suggest_int('num_leaves', 15, 100),
                'learning_rate': trial.suggest_float('learning_rate', 0.01, 0.3, log=True),
                'feature_fraction': trial.suggest_float('feature_fraction', 0.5, 1.0),
                'bagging_fraction': trial.suggest_float('bagging_fraction', 0.5, 1.0),
                'min_data_in_leaf': trial.suggest_int('min_data_in_leaf', 5, 100),
                'max_depth': trial.suggest_int('max_depth', 3, 12),
                'lambda_l1': trial.suggest_float('lambda_l1', 1e-8, 10.0, log=True),
                'lambda_l2': trial.suggest_float('lambda_l2', 1e-8, 10.0, log=True),
                'n_estimators': 200,
                'early_stopping_rounds': 30,
                'verbose': -1,
            }
        elif self.model_type == 'xgboost':
            return {
                'max_depth': trial.suggest_int('max_depth', 3, 12),
                'learning_rate': trial.suggest_float('learning_rate', 0.01, 0.3, log=True),
                'subsample': trial.suggest_float('subsample', 0.5, 1.0),
                'colsample_bytree': trial.suggest_float('colsample_bytree', 0.5, 1.0),
                'min_child_weight': trial.suggest_int('min_child_weight', 1, 20),
                'gamma': trial.suggest_float('gamma', 1e-8, 1.0, log=True),
                'reg_alpha': trial.suggest_float('reg_alpha', 1e-8, 10.0, log=True),
                'reg_lambda': trial.suggest_float('reg_lambda', 1e-8, 10.0, log=True),
                'n_estimators': 200,
                'early_stopping_rounds': 30,
            }
        elif self.model_type == 'logistic':
            return {
                'C': trial.suggest_float('C', 1e-4, 1e4, log=True),
                'max_iter': 1000,
            }
        return {}

    def _compute_metric(self, y_true: np.ndarray, y_pred_proba: np.ndarray) -> float:
        """计算评估指标"""
        from sklearn.metrics import accuracy_score, roc_auc_score, f1_score

        if self.metric == 'accuracy':
            y_pred = (y_pred_proba > 0.5).astype(int)
            return accuracy_score(y_true, y_pred)
        elif self.metric == 'roc_auc':
            try:
                return roc_auc_score(y_true, y_pred_proba)
            except Exception:
                return 0.5
        elif self.metric == 'f1':
            y_pred = (y_pred_proba > 0.5).astype(int)
            return f1_score(y_true, y_pred, zero_division=0)
        else:
            return accuracy_score(y_true, (y_pred_proba > 0.5).astype(int))

    def _walk_forward_score(self, X: pd.DataFrame, y: pd.Series, params: Dict) -> float:
        """Walk-Forward 交叉验证得分"""
        n = len(X)
        if n <= self.train_window + self.test_window:
            return 0.5

        scores = []
        start = 0

        while start + self.train_window + self.test_window <= n:
            train_end = start + self.train_window
            test_end = min(train_end + self.test_window, n)

            X_train, y_train = X.iloc[start:train_end], y.iloc[start:train_end]
            X_test, y_test = X.iloc[train_end:test_end], y.iloc[train_end:test_end]

            if len(np.unique(y_train)) < 2 or len(np.unique(y_test)) < 2:
                start += self.step_size
                continue

            # 小样本时禁用early stopping，避免训练不足
            params_copy = dict(params)
            if len(X_train) < 200 or len(X_test) < 30:
                params_copy.pop('early_stopping_rounds', None)
                params_copy['verbose'] = -1

            model = create_model(self.model_type, params_copy)
            try:
                # 不传入验证集，避免early stopping过早停止
                model.fit(X_train, y_train)
                preds = model.predict_proba(X_test)
                score = self._compute_metric(y_test.values, preds)
                scores.append(score)
            except Exception:
                pass

            start += self.step_size

        if not scores:
            return 0.5

        return np.mean(scores)

    def tune(self, X: pd.DataFrame, y: pd.Series) -> Dict:
        """运行超参优化

        返回:
            {'best_params': Dict, 'best_score': float, 'study': optuna.study}
        """
        import optuna

        optuna.logging.set_verbosity(optuna.logging.WARNING)

        def objective(trial):
            params = self._get_param_space(trial)
            return self._walk_forward_score(X, y, params)

        study = optuna.create_study(direction=self.direction)
        study.optimize(objective, n_trials=self.n_trials)

        self.best_params = study.best_params
        self.best_score = study.best_value

        return {
            'best_params': study.best_params,
            'best_score': study.best_value,
            'n_trials': self.n_trials,
            'study': study,
        }

    def train_best(self, X_train: pd.DataFrame, y_train: pd.Series,
                   X_val: Optional[pd.DataFrame] = None,
                   y_val: Optional[pd.Series] = None) -> MLModel:
        """用最优参数训练最终模型"""
        model = create_model(self.model_type, self.best_params)
        model.fit(X_train, y_train, X_val, y_val)
        return model
