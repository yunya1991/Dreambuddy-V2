"""
特征选择模块 — 去芜存菁，提升模型质量

双层筛选策略:
  第一层: 重要性筛选 — 剔除LightGBM重要性极低的特征
  第二层: 相关性去冗余 — 高相关特征组中只保留最重要的那个

理论映射 (BCRM去芜存菁):
  去芜 → 剔除弱特征/噪声特征 (减少干扰)
  存菁 → 保留强特征/核心特征 (聚焦主要矛盾)
  去芜存菁的过程 = 否定之否定 — 先建立全面特征(肯定)，再剔除冗余(否定)，最后得到精炼集(否定之否定)
"""

import numpy as np
import pandas as pd
from typing import List, Dict, Tuple, Optional
import warnings


class FeatureSelector:
    """
    特征选择器 — 双层筛选：重要性过滤 + 相关性去冗余
    """

    def __init__(
        self,
        importance_threshold: float = 0.01,
        corr_threshold: float = 0.85,
        min_features: int = 50,
    ):
        """
        Args:
            importance_threshold: 重要性阈值 (占最高重要性的比例)，低于此值的特征被剔除
            corr_threshold: 相关性阈值，高于此值的特征组只保留一个
            min_features: 最少保留特征数 (防止过滤过猛)
        """
        self.importance_threshold = importance_threshold
        self.corr_threshold = corr_threshold
        self.min_features = min_features

        self.selected_features: List[str] = []
        self.feature_importances_: Dict[str, float] = {}
        self.dropped_by_importance: List[str] = []
        self.dropped_by_corr: List[str] = []

    def fit(
        self,
        X: pd.DataFrame,
        y: np.ndarray,
        model=None,
        min_valid_ratio: float = 0.5,
    ) -> List[str]:
        """
        执行特征选择

        Args:
            X: 特征DataFrame
            y: 标签
            model: 已训练的LightGBM模型 (如果有)，没有则训练一个简单的
            min_valid_ratio: 有效值比例阈值（0~1），低于此值的特征先被过滤

        Returns:
            选中的特征名列表
        """
        # 第0层: 有效值比例预筛（过滤macro稀疏特征等）
        n_rows = len(X)
        min_valid = int(n_rows * min_valid_ratio)
        valid_counts = X.notna().sum()
        sparse_cols = valid_counts[valid_counts < min_valid].index.tolist()
        if sparse_cols:
            X = X.drop(columns=sparse_cols)
        feature_names = list(X.columns)

        # 1. 获取特征重要性
        if model is not None:
            importances = model.feature_importances_
        else:
            importances = self._train_and_get_importance(X.values, y, len(feature_names))

        self.feature_importances_ = dict(zip(feature_names, importances))

        # 2. 第一层: 重要性筛选
        selected = self._filter_by_importance(feature_names, importances)
        self.dropped_by_importance = [f for f in feature_names if f not in selected]

        # 3. 第二层: 相关性去冗余
        selected = self._filter_by_correlation(X, selected, importances)
        self.dropped_by_corr = [
            f for f in self.feature_importances_.keys()
            if f not in selected and f not in self.dropped_by_importance
        ]

        # 4. 确保最少特征数
        if len(selected) < self.min_features:
            all_sorted = sorted(
                self.feature_importances_.items(),
                key=lambda x: x[1], reverse=True
            )
            selected = [f for f, _ in all_sorted[:self.min_features]]

        self.selected_features = selected
        return selected

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        """应用特征选择"""
        return X[self.selected_features].copy()

    def fit_transform(self, X: pd.DataFrame, y: np.ndarray, model=None) -> pd.DataFrame:
        self.fit(X, y, model)
        return self.transform(X)

    def _train_and_get_importance(
        self, X: np.ndarray, y: np.ndarray, n_features: int
    ) -> np.ndarray:
        """训练一个简单的LightGBM模型获取重要性"""
        try:
            import lightgbm as lgb
            params = {
                "objective": "multiclass",
                "num_class": 3,
                "max_depth": 5,
                "learning_rate": 0.05,
                "n_estimators": 100,
                "subsample": 0.8,
                "colsample_bytree": 0.7,
                "random_state": 42,
                "verbose": -1,
            }
            # 映射标签到0/1/2
            y_mapped = y + 1
            model = lgb.LGBMClassifier(**params)
            model.fit(X, y_mapped)
            return model.feature_importances_
        except Exception as e:
            warnings.warn(f"训练模型失败，使用全特征: {e}")
            return np.ones(n_features)

    def _filter_by_importance(
        self, feature_names: List[str], importances: np.ndarray
    ) -> List[str]:
        """按重要性筛选"""
        max_imp = max(importances.max(), 1e-8)
        threshold = max_imp * self.importance_threshold

        selected = [
            name for name, imp in zip(feature_names, importances)
            if imp >= threshold
        ]
        return selected

    def _filter_by_correlation(
        self,
        X: pd.DataFrame,
        feature_names: List[str],
        importances: np.ndarray,
    ) -> List[str]:
        """
        按相关性去冗余

        算法:
          1. 按重要性从高到低排序特征
          2. 依次遍历，若当前特征与任何已选特征的相关性>阈值，则剔除
          3. 否则保留
        """
        if len(feature_names) <= 1:
            return feature_names

        # 计算相关矩阵
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            corr_matrix = X[feature_names].corr().abs().values

        # 按重要性排序的索引
        imp_dict = dict(zip(feature_names, [
            self.feature_importances_.get(f, 0) for f in feature_names
        ]))
        sorted_indices = np.argsort([-imp_dict[f] for f in feature_names])

        selected_idx = []
        dropped_idx = []

        for idx in sorted_indices:
            if len(selected_idx) == 0:
                selected_idx.append(idx)
                continue

            # 计算与所有已选特征的最大相关
            max_corr = max(corr_matrix[idx, s] for s in selected_idx)
            if max_corr > self.corr_threshold:
                dropped_idx.append(idx)
            else:
                selected_idx.append(idx)

        selected = [feature_names[i] for i in selected_idx]
        return selected

    @property
    def summary(self) -> Dict:
        """特征选择摘要"""
        total = len(self.feature_importances_)
        selected = len(self.selected_features)
        return {
            "total_features": total,
            "selected_features": selected,
            "dropped_by_importance": len(self.dropped_by_importance),
            "dropped_by_corr": len(self.dropped_by_corr),
            "reduction_ratio": 1 - selected / total if total > 0 else 0,
            "importance_threshold": self.importance_threshold,
            "corr_threshold": self.corr_threshold,
        }

    def print_summary(self):
        """打印摘要"""
        s = self.summary
        print("=" * 60)
        print("  特征选择摘要")
        print("=" * 60)
        print(f"  总特征数:      {s['total_features']}")
        print(f"  选中特征数:    {s['selected_features']}")
        print(f"  剔除(重要性):  {s['dropped_by_importance']}")
        print(f"  剔除(相关性):  {s['dropped_by_corr']}")
        print(f"  压缩比例:      {s['reduction_ratio']*100:.1f}%")
        print(f"  重要性阈值:    {s['importance_threshold']}")
        print(f"  相关性阈值:    {s['corr_threshold']}")
        print("=" * 60)

        if self.dropped_by_importance:
            print(f"\n  因重要性低被剔除 ({len(self.dropped_by_importance)}个):")
            for f in self.dropped_by_importance[:20]:
                imp = self.feature_importances_.get(f, 0)
                print(f"    {f:<40} imp={imp:.1f}")
            if len(self.dropped_by_importance) > 20:
                print(f"    ... 还有 {len(self.dropped_by_importance)-20} 个")

        if self.dropped_by_corr:
            print(f"\n  因高相关被剔除 ({len(self.dropped_by_corr)}个):")
            for f in self.dropped_by_corr[:20]:
                imp = self.feature_importances_.get(f, 0)
                print(f"    {f:<40} imp={imp:.1f}")
            if len(self.dropped_by_corr) > 20:
                print(f"    ... 还有 {len(self.dropped_by_corr)-20} 个")

        print()
