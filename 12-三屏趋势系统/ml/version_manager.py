"""模型版本管理器

认识-实践闭环的核心组件：
1. 模型版本化：每个模型有版本号、创建时间、训练数据范围
2. 性能追踪：记录每个版本在验证集上的表现
3. 基线模型：标记一个稳定版本作为参考基线
4. 自动升级：新版本表现优于当前最佳时自动升级
5. 回滚机制：表现不佳时可快速回滚到上一版本或基线版本
6. 性能退化检测：监控新数据上的表现，触发自动回退

参考: 软件版本管理思想, MLOps最佳实践, 蓝绿部署思想
"""

from typing import Dict, List, Optional, Any, Tuple
import os
import json
import time
import shutil
import pickle
import numpy as np
import pandas as pd
from .models import MLModel, create_model


class ModelVersionManager:
    """模型版本管理器

    目录结构:
        models/
        ├── versions/
        │   ├── v1/
        │   │   ├── model.pkl
        │   │   ├── meta.json
        │   │   └── feature_engineer_config.json
        │   ├── v2/
        │   └── ...
        ├── current/
        │   ├── model.pkl
        │   └── meta.json
        ├── baseline/          # 基线模型（稳定参考版本）
        │   ├── model.pkl
        │   └── meta.json
        ├── perf_logs/         # 性能日志（用于退化检测）
        │   └── perf_history.json
        └── registry.json
    """

    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self.versions_dir = os.path.join(base_dir, 'versions')
        self.current_dir = os.path.join(base_dir, 'current')
        self.baseline_dir = os.path.join(base_dir, 'baseline')
        self.perf_logs_dir = os.path.join(base_dir, 'perf_logs')

        os.makedirs(self.versions_dir, exist_ok=True)
        os.makedirs(self.current_dir, exist_ok=True)
        os.makedirs(self.baseline_dir, exist_ok=True)
        os.makedirs(self.perf_logs_dir, exist_ok=True)

        self.registry_path = os.path.join(base_dir, 'registry.json')
        self.perf_history_path = os.path.join(self.perf_logs_dir, 'perf_history.json')

        self._load_registry()
        self._load_perf_history()

    def _load_registry(self):
        if os.path.exists(self.registry_path):
            with open(self.registry_path, 'r') as f:
                self.registry = json.load(f)
        else:
            self.registry = {
                'versions': [],
                'current_version': None,
                'baseline_version': None,
                'next_version': 1,
            }

    def _save_registry(self):
        with open(self.registry_path, 'w') as f:
            json.dump(self.registry, f, indent=2, ensure_ascii=False)

    def _load_perf_history(self):
        if os.path.exists(self.perf_history_path):
            with open(self.perf_history_path, 'r') as f:
                self.perf_history = json.load(f)
        else:
            self.perf_history = {'records': []}

    def _save_perf_history(self):
        with open(self.perf_history_path, 'w') as f:
            json.dump(self.perf_history, f, indent=2, ensure_ascii=False)

    def save_version(
        self,
        model: MLModel,
        performance: Dict[str, float],
        train_date_range: Tuple[str, str],
        feature_engineer_config: Optional[Dict] = None,
        metadata: Optional[Dict] = None,
    ) -> str:
        """保存一个新版本模型

        参数:
            model: 训练好的模型
            performance: 性能指标 dict (如 {'roc_auc': 0.65, 'accuracy': 0.58})
            train_date_range: (start_date, end_date) 训练数据范围
            feature_engineer_config: 特征工程配置
            metadata: 额外元数据

        返回:
            version_id (如 'v3')
        """
        version_num = self.registry['next_version']
        version_id = f'v{version_num}'
        version_dir = os.path.join(self.versions_dir, version_id)
        os.makedirs(version_dir, exist_ok=True)

        # 保存模型
        model_path = os.path.join(version_dir, 'model.pkl')
        model.save(model_path)

        # 保存元数据
        meta = {
            'version': version_id,
            'created_at': time.strftime('%Y-%m-%d %H:%M:%S'),
            'model_type': getattr(model, 'name', type(model).__name__),
            'model_params': getattr(model, 'params', {}),
            'performance': performance,
            'train_date_range': [str(d) for d in train_date_range],
            'feature_names': model.feature_names,
            'num_features': len(model.feature_names),
            'feature_engineer_config': feature_engineer_config or {},
            'metadata': metadata or {},
        }

        with open(os.path.join(version_dir, 'meta.json'), 'w') as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)

        # 更新注册表
        self.registry['versions'].append({
            'version': version_id,
            'created_at': meta['created_at'],
            'performance': performance,
            'num_features': len(model.feature_names),
        })
        self.registry['next_version'] = version_num + 1
        self._save_registry()

        print(f"[版本管理] 保存新版本 {version_id}: "
              f"AUC={performance.get('roc_auc', 0):.4f}, "
              f"特征数={len(model.feature_names)}")
        return version_id

    def load_version(self, version_id: str) -> MLModel:
        """加载指定版本的模型"""
        version_dir = os.path.join(self.versions_dir, version_id)
        model_path = os.path.join(version_dir, 'model.pkl')
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"模型版本不存在: {version_id}")
        return _load_model_from_path(model_path)

    def get_version_meta(self, version_id: str) -> Optional[Dict]:
        """获取版本元数据"""
        version_dir = os.path.join(self.versions_dir, version_id)
        meta_path = os.path.join(version_dir, 'meta.json')
        if not os.path.exists(meta_path):
            return None
        with open(meta_path, 'r') as f:
            return json.load(f)

    def promote(self, version_id: str, metric: str = 'roc_auc') -> bool:
        """将某个版本升级为当前版本

        只有性能优于当前版本时才升级
        """
        version_info = self._get_version_info(version_id)
        if version_info is None:
            return False

        current = self.registry.get('current_version')
        if current:
            current_info = self._get_version_info(current)
            if current_info and version_info['performance'].get(metric, 0) <= current_info['performance'].get(metric, 0):
                print(f"[版本管理] {version_id} 性能未优于当前版本 {current}，不升级")
                return False

        # 升级
        version_dir = os.path.join(self.versions_dir, version_id)
        for fname in ['model.pkl', 'meta.json']:
            src = os.path.join(version_dir, fname)
            dst = os.path.join(self.current_dir, fname)
            if os.path.exists(src):
                shutil.copy2(src, dst)

        self.registry['current_version'] = version_id
        self._save_registry()
        print(f"[版本管理] 升级 {version_id} 为当前版本")
        return True

    def set_baseline(self, version_id: str) -> bool:
        """将某个版本设为基线版本（稳定参考）

        基线模型是回退的最终保障，通常经过充分验证。
        """
        version_dir = os.path.join(self.versions_dir, version_id)
        if not os.path.exists(version_dir):
            print(f"[版本管理] 版本 {version_id} 不存在，无法设为基线")
            return False

        for fname in ['model.pkl', 'meta.json']:
            src = os.path.join(version_dir, fname)
            dst = os.path.join(self.baseline_dir, fname)
            if os.path.exists(src):
                shutil.copy2(src, dst)

        self.registry['baseline_version'] = version_id
        self._save_registry()
        print(f"[版本管理] 设置 {version_id} 为基线版本")
        return True

    def load_current(self) -> Optional[MLModel]:
        """加载当前生产版本模型"""
        model_path = os.path.join(self.current_dir, 'model.pkl')
        if not os.path.exists(model_path):
            return None
        return _load_model_from_path(model_path)

    def load_baseline(self) -> Optional[MLModel]:
        """加载基线版本模型"""
        model_path = os.path.join(self.baseline_dir, 'model.pkl')
        if not os.path.exists(model_path):
            return None
        return _load_model_from_path(model_path)

    def rollback(self, to_baseline: bool = False) -> Optional[str]:
        """回退到上一版本或基线版本

        参数:
            to_baseline: True则回退到基线，False则回退到上一版本

        返回:
            回退后的版本号，失败返回None
        """
        current = self.registry.get('current_version')
        if not current:
            print("[版本管理] 当前无版本，无法回退")
            return None

        target_version = None
        if to_baseline:
            target_version = self.registry.get('baseline_version')
            if not target_version:
                print("[版本管理] 无基线版本，无法回退")
                return None
        else:
            # 回退到上一版本（registry中前一个版本）
            versions = self.registry['versions']
            current_idx = -1
            for i, v in enumerate(versions):
                if v['version'] == current:
                    current_idx = i
                    break
            if current_idx <= 0:
                print("[版本管理] 已是第一个版本，无法回退")
                return None
            target_version = versions[current_idx - 1]['version']

        # 执行回退
        target_dir = os.path.join(self.versions_dir, target_version)
        for fname in ['model.pkl', 'meta.json']:
            src = os.path.join(target_dir, fname)
            dst = os.path.join(self.current_dir, fname)
            if os.path.exists(src):
                shutil.copy2(src, dst)

        self.registry['current_version'] = target_version
        self._save_registry()
        print(f"[版本管理] 回退: {current} → {target_version}")
        return target_version

    def check_degradation(
        self,
        new_performance: Dict[str, float],
        metric: str = 'roc_auc',
        threshold: float = 0.05,
        compare_to: str = 'current',
    ) -> Tuple[bool, float]:
        """检测性能退化

        参数:
            new_performance: 新数据上的性能指标
            metric: 比较的指标
            threshold: 退化阈值（绝对差）
            compare_to: 比较对象 - 'current' 当前版本, 'baseline' 基线版本

        返回:
            (是否退化, 退化幅度) - 退化幅度 = 参考值 - 新值（正数表示退化）
        """
        if compare_to == 'baseline':
            ref_version = self.registry.get('baseline_version')
        else:
            ref_version = self.registry.get('current_version')

        if not ref_version:
            return False, 0.0

        ref_info = self._get_version_info(ref_version)
        if not ref_info:
            return False, 0.0

        ref_score = ref_info['performance'].get(metric, 0)
        new_score = new_performance.get(metric, 0)
        degradation = ref_score - new_score

        is_degraded = degradation > threshold
        return is_degraded, degradation

    def log_performance(
        self,
        version_id: str,
        period: str,
        performance: Dict[str, float],
        date_range: Tuple[str, str],
    ):
        """记录模型在某个时间段的性能（用于持续监控）

        参数:
            version_id: 版本号
            period: 时间段标识 (如 '2025-Q3', '2025-06')
            performance: 性能指标
            date_range: (start_date, end_date)
        """
        record = {
            'version': version_id,
            'period': period,
            'date_range': [str(d) for d in date_range],
            'performance': performance,
            'logged_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        }
        self.perf_history['records'].append(record)
        self._save_perf_history()

    def get_best_version(self, metric: str = 'roc_auc') -> Optional[str]:
        """获取性能最好的版本"""
        best_ver = None
        best_score = -float('inf')
        for v in self.registry['versions']:
            score = v.get('performance', {}).get(metric, 0)
            if score > best_score:
                best_score = score
                best_ver = v['version']
        return best_ver

    def list_versions(self, limit: int = 10) -> List[Dict]:
        """列出最近N个版本"""
        versions = self.registry['versions'][-limit:]
        return list(reversed(versions))

    def print_status(self):
        """打印版本管理状态"""
        print("\n" + "=" * 60)
        print("  模型版本管理状态")
        print("=" * 60)
        print(f"  当前版本:    {self.registry.get('current_version', '无')}")
        print(f"  基线版本:    {self.registry.get('baseline_version', '无')}")
        print(f"  总版本数:    {len(self.registry['versions'])}")
        print(f"\n  版本列表 (最近10个):")
        for v in self.list_versions(10):
            perf = v.get('performance', {})
            auc = perf.get('roc_auc', 0)
            acc = perf.get('accuracy', 0)
            marker = ""
            if v['version'] == self.registry.get('current_version'):
                marker = " [当前]"
            if v['version'] == self.registry.get('baseline_version'):
                marker += " [基线]"
            print(f"    {v['version']:<6} AUC={auc:.4f}  Acc={acc:.4f}  "
                  f"{v['created_at']}{marker}")
        print("=" * 60 + "\n")

    def _get_version_info(self, version_id: str) -> Optional[Dict]:
        for v in self.registry['versions']:
            if v['version'] == version_id:
                return v
        return None


def _load_model_from_path(path: str) -> MLModel:
    """从路径加载模型（自动检测类型）"""
    with open(path, 'rb') as f:
        data = pickle.load(f)

    model_type = 'lightgbm'
    params = data.get('params', {})
    if params:
        if 'num_leaves' in params or 'objective' in params:
            model_type = 'lightgbm'
        elif 'booster' in params:
            model_type = 'xgboost'
        elif 'C' in params:
            model_type = 'logistic'

    # 用对应类的 load 方法正确加载（包含内部模型对象）
    if model_type == 'lightgbm':
        from .models import LightGBMModel
        return LightGBMModel.load(path)
    elif model_type == 'xgboost':
        from .models import XGBoostModel
        return XGBoostModel.load(path)
    elif model_type == 'logistic':
        from .models import LogisticModel
        return LogisticModel.load(path)
    else:
        model = create_model(model_type, params)
        if 'feature_names' in data:
            model.feature_names = data['feature_names']
        return model
