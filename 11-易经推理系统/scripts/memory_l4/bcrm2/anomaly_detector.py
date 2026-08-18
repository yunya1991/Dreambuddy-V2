"""
异常检测引擎 — 混合架构 (Phase 2.1)

三层架构:
  Layer 1: Isolation Forest 快速检测 (CPU友好)
  Layer 2: LightGBM 模式分类 (复杂异常)
  Layer 3: 预留深度学习接口 (PatchTST等)

BCRM理论映射:
  - 矛盾转化: 正常市态 → 异常市态的质变检测
  - 否定之否定: 异常→正常→再异常的循环
  - 量变积累: 连续小异常 → 大异常爆发
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import pickle
import json
import warnings

from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
import lightgbm as lgb


@dataclass
class AnomalySignal:
    """异常信号"""
    timestamp: str
    symbol: str
    anomaly_type: str  # price / volume / volatility / liquidity / pattern
    severity: str  # low / medium / high / critical
    confidence: float
    description: str
    features: Dict[str, float] = field(default_factory=dict)
    score: float = 0.0


class IsolationForestLayer:
    """隔离森林层 — 快速检测单点异常"""

    def __init__(self, contamination: float = 0.05, n_estimators: int = 100):
        self.model = IsolationForest(
            contamination=contamination,
            n_estimators=n_estimators,
            random_state=42,
            n_jobs=-1,
        )
        self.scaler = StandardScaler()
        self.is_fitted = False
        self.feature_names = [
            'returns', 'volume_change', 'volatility_change',
            'range_ratio', 'body_ratio', 'gap_ratio',
            'rsi_change', 'macd_change', 'bb_position',
        ]

    def _extract_features(self, df: pd.DataFrame) -> np.ndarray:
        """提取异常检测特征"""
        features = pd.DataFrame(index=df.index)

        # 收益率
        features['returns'] = df['close'].pct_change()

        # 成交量变化
        features['volume_change'] = df['volume'].pct_change()

        # 波动率变化
        returns = df['close'].pct_change()
        features['volatility_change'] = returns.rolling(20).std().diff()

        # 振幅比 (high-low)/close
        features['range_ratio'] = (df['high'] - df['low']) / df['close']

        # 实体比 |close-open|/high-low
        body = (df['close'] - df['open']).abs()
        range_val = df['high'] - df['low']
        features['body_ratio'] = body / range_val.replace(0, np.nan)

        # 跳空比
        features['gap_ratio'] = (df['open'] - df['close'].shift(1)) / df['close'].shift(1)

        # RSI变化
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        features['rsi_change'] = rsi.diff()

        # MACD变化
        ema12 = df['close'].ewm(span=12).mean()
        ema26 = df['close'].ewm(span=26).mean()
        macd = ema12 - ema26
        features['macd_change'] = macd.diff()

        # 布林带位置
        bb_mid = df['close'].rolling(20).mean()
        bb_std = df['close'].rolling(20).std()
        features['bb_position'] = (df['close'] - bb_mid) / bb_std.replace(0, np.nan)

        features = features.fillna(0)
        features = features.replace([np.inf, -np.inf], 0)

        return features.values

    def fit(self, df: pd.DataFrame):
        """训练隔离森林"""
        X = self._extract_features(df)
        self.scaler.fit(X)
        X_scaled = self.scaler.transform(X)
        self.model.fit(X_scaled)
        self.is_fitted = True

    def predict(self, df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
        """预测异常

        Returns:
            (labels, scores): labels=-1表示异常, scores越小越异常
        """
        if not self.is_fitted:
            # 未训练时，用数据自身拟合
            self.fit(df)

        X = self._extract_features(df)
        X_scaled = self.scaler.transform(X)
        labels = self.model.predict(X_scaled)
        scores = self.model.decision_function(X_scaled)
        return labels, scores

    def detect(self, df: pd.DataFrame, symbol: str = '') -> List[AnomalySignal]:
        """检测异常并返回信号列表"""
        labels, scores = self.predict(df)

        signals = []
        for i in range(len(df)):
            if labels[i] == -1:  # 异常点
                # 根据分数判断严重程度
                score = scores[i]
                if score < -0.3:
                    severity = 'critical'
                elif score < -0.15:
                    severity = 'high'
                elif score < -0.05:
                    severity = 'medium'
                else:
                    severity = 'low'

                # 判断异常类型
                features = self._extract_features(df.iloc[i:i+1])[0]
                anomaly_type = self._classify_anomaly(features)

                signals.append(AnomalySignal(
                    timestamp=str(df.index[i]),
                    symbol=symbol,
                    anomaly_type=anomaly_type,
                    severity=severity,
                    confidence=min(1.0, abs(score) * 2),
                    description=f"{anomaly_type}异常 detected (score={score:.3f})",
                    features=dict(zip(self.feature_names, features)),
                    score=score,
                ))

        return signals

    def _classify_anomaly(self, features: np.ndarray) -> str:
        """根据特征判断异常类型"""
        feature_dict = dict(zip(self.feature_names, features))

        # 价格异常判断
        if abs(feature_dict.get('returns', 0)) > 0.05:
            return 'price'
        if abs(feature_dict.get('gap_ratio', 0)) > 0.03:
            return 'price'

        # 成交量异常
        if abs(feature_dict.get('volume_change', 0)) > 2.0:
            return 'volume'

        # 波动率异常
        if abs(feature_dict.get('volatility_change', 0)) > 0.02:
            return 'volatility'

        # 其他
        return 'pattern'


class LightGBMClassifierLayer:
    """LightGBM分类器层 — 检测复杂异常模式"""

    def __init__(self, model_path: Optional[str] = None):
        self.model = None
        self.scaler = StandardScaler()
        self.is_fitted = False
        self.anomaly_types = [
            'normal', 'flash_crash', 'pump', 'dump',
            'low_liquidity', 'high_volatility_spike',
        ]

        if model_path and Path(model_path).exists():
            self.load_model(model_path)

    def _extract_features(self, df: pd.DataFrame, window: int = 20) -> np.ndarray:
        """提取窗口特征用于分类"""
        features_list = []

        for i in range(window, len(df)):
            window_df = df.iloc[i-window:i]

            feat = {}
            # 价格统计
            returns = window_df['close'].pct_change().dropna()
            feat['ret_mean'] = returns.mean()
            feat['ret_std'] = returns.std()
            feat['ret_max'] = returns.max()
            feat['ret_min'] = returns.min()
            feat['ret_skew'] = returns.skew()
            feat['ret_kurt'] = returns.kurt()

            # 成交量统计
            vol_change = window_df['volume'].pct_change().dropna()
            feat['vol_mean'] = vol_change.mean()
            feat['vol_std'] = vol_change.std()
            feat['vol_max'] = vol_change.max()

            # 波动率
            feat['volatility'] = returns.std() * np.sqrt(24)  # 日波动率

            # 趋势强度
            feat['trend'] = (window_df['close'].iloc[-1] - window_df['close'].iloc[0]) / window_df['close'].iloc[0]

            # 振幅
            feat['range'] = (window_df['high'].max() - window_df['low'].min()) / window_df['close'].mean()

            # 实体统计
            body = (window_df['close'] - window_df['open']).abs()
            feat['body_mean'] = body.mean() / window_df['close'].mean()

            # 连续涨跌
            feat['consecutive_up'] = (returns > 0).rolling(3).sum().max()
            feat['consecutive_down'] = (returns < 0).rolling(3).sum().max()

            features_list.append(feat)

        features_df = pd.DataFrame(features_list)
        features_df = features_df.fillna(0)
        features_df = features_df.replace([np.inf, -np.inf], 0)

        return features_df.values

    def fit(self, df: pd.DataFrame, labels: Optional[np.ndarray] = None):
        """训练分类器

        Args:
            df: K线数据
            labels: 异常标签，如果为None则自动标注
        """
        X = self._extract_features(df)

        if labels is None:
            # 自动标注：基于规则生成训练标签
            labels = self._auto_label(df)
            labels = labels[-len(X):]  # 对齐长度

        # 确保只包含实际出现的类别
        unique_labels = sorted(set(labels))
        self.anomaly_types = [self.anomaly_types[i] for i in unique_labels]
        # 重新映射标签为连续整数
        label_map = {old: new for new, old in enumerate(unique_labels)}
        labels = np.array([label_map[l] for l in labels])

        self.scaler.fit(X)
        X_scaled = self.scaler.transform(X)

        self.model = lgb.LGBMClassifier(
            objective='multiclass',
            num_class=len(self.anomaly_types),
            n_estimators=100,
            learning_rate=0.1,
            max_depth=5,
            random_state=42,
            verbose=-1,
        )
        self.model.fit(X_scaled, labels)
        self.is_fitted = True

    def _auto_label(self, df: pd.DataFrame) -> np.ndarray:
        """基于规则自动标注异常类型"""
        labels = np.zeros(len(df), dtype=int)

        returns = df['close'].pct_change()
        vol_change = df['volume'].pct_change()

        for i in range(1, len(df)):
            ret = returns.iloc[i]
            vol = vol_change.iloc[i]

            # flash_crash: 大幅下跌+放量
            if ret < -0.05 and vol > 2.0:
                labels[i] = 1
            # pump: 大幅上涨+放量
            elif ret > 0.05 and vol > 2.0:
                labels[i] = 2
            # dump: 大幅下跌
            elif ret < -0.03:
                labels[i] = 3
            # low_liquidity: 缩量+小波动
            elif abs(ret) < 0.005 and vol < 0.3:
                labels[i] = 4
            # high_volatility_spike: 波动率突增
            elif abs(ret) > 0.04:
                labels[i] = 5

        return labels

    def predict(self, df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
        """预测异常类型

        Returns:
            (predictions, probabilities)
        """
        if not self.is_fitted:
            self.fit(df)

        X = self._extract_features(df)
        X_scaled = self.scaler.transform(X)
        predictions = self.model.predict(X_scaled)
        probabilities = self.model.predict_proba(X_scaled)
        return predictions, probabilities

    def detect(self, df: pd.DataFrame, symbol: str = '') -> List[AnomalySignal]:
        """检测异常模式"""
        predictions, probabilities = self.predict(df)

        # 获取对应时间索引
        window = 20
        timestamps = df.index[window:]

        signals = []
        for i in range(len(predictions)):
            pred = int(predictions[i])
            if pred == 0:  # normal
                continue

            prob = probabilities[i][pred]
            if prob < 0.6:  # 置信度阈值
                continue

            anomaly_type = self.anomaly_types[pred]

            # 严重程度
            if anomaly_type in ['flash_crash', 'pump']:
                severity = 'critical' if prob > 0.8 else 'high'
            elif anomaly_type in ['dump', 'high_volatility_spike']:
                severity = 'high' if prob > 0.8 else 'medium'
            else:
                severity = 'medium'

            signals.append(AnomalySignal(
                timestamp=str(timestamps[i]),
                symbol=symbol,
                anomaly_type=anomaly_type,
                severity=severity,
                confidence=prob,
                description=f"{anomaly_type} pattern detected (prob={prob:.2f})",
                score=prob,
            ))

        return signals

    def save_model(self, path: str):
        """保存模型"""
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'wb') as f:
            pickle.dump({
                'model': self.model,
                'scaler': self.scaler,
                'anomaly_types': self.anomaly_types,
            }, f)

    def load_model(self, path: str):
        """加载模型"""
        with open(path, 'rb') as f:
            data = pickle.load(f)
        self.model = data['model']
        self.scaler = data['scaler']
        self.anomaly_types = data['anomaly_types']
        self.is_fitted = True


class DeepLearningLayer:
    """深度学习层 — 预留接口 (PatchTST等)"""

    def __init__(self, model_path: Optional[str] = None):
        self.model = None
        self.model_path = model_path

    def is_available(self) -> bool:
        """检查深度学习模型是否可用"""
        return self.model is not None and self.model_path is not None

    def detect(self, df: pd.DataFrame, symbol: str = '') -> List[AnomalySignal]:
        """预留: 深度学习异常检测"""
        if not self.is_available():
            return []

        # TODO: 接入PatchTST或其他深度学习模型
        # 当前返回空列表，作为占位符
        return []

    def load_model(self, path: str):
        """预留: 加载深度学习模型"""
        self.model_path = path
        # TODO: 实现模型加载逻辑
        pass


class HybridAnomalyDetector:
    """混合异常检测器 — 三层架构"""

    def __init__(self,
                 if_contamination: float = 0.05,
                 lgb_model_path: Optional[str] = None,
                 dl_model_path: Optional[str] = None,
                 enable_if: bool = True,
                 enable_lgb: bool = True,
                 enable_dl: bool = False):
        """
        Args:
            if_contamination: Isolation Forest 异常比例假设
            lgb_model_path: LightGBM 模型路径
            dl_model_path: 深度学习模型路径
            enable_if: 启用隔离森林层
            enable_lgb: 启用LightGBM层
            enable_dl: 启用深度学习层 (预留)
        """
        self.layer1 = IsolationForestLayer(contamination=if_contamination) if enable_if else None
        self.layer2 = LightGBMClassifierLayer(model_path=lgb_model_path) if enable_lgb else None
        self.layer3 = DeepLearningLayer(model_path=dl_model_path) if enable_dl else None

        self.stats = {
            'total_checked': 0,
            'anomalies_found': 0,
            'by_type': {},
            'by_severity': {},
        }

    def detect(self, df: pd.DataFrame, symbol: str = '') -> List[AnomalySignal]:
        """三层检测，合并结果"""
        all_signals = []

        # Layer 1: Isolation Forest
        if self.layer1:
            signals = self.layer1.detect(df, symbol)
            all_signals.extend(signals)

        # Layer 2: LightGBM
        if self.layer2:
            signals = self.layer2.detect(df, symbol)
            all_signals.extend(signals)

        # Layer 3: Deep Learning (预留)
        if self.layer3 and self.layer3.is_available():
            signals = self.layer3.detect(df, symbol)
            all_signals.extend(signals)

        # 去重：同一时间+同类型只保留一个
        unique_signals = {}
        for sig in all_signals:
            key = (sig.timestamp, sig.anomaly_type)
            if key not in unique_signals or sig.confidence > unique_signals[key].confidence:
                unique_signals[key] = sig

        result = list(unique_signals.values())
        result.sort(key=lambda x: x.confidence, reverse=True)

        # 更新统计
        self.stats['total_checked'] += len(df)
        self.stats['anomalies_found'] += len(result)
        for sig in result:
            self.stats['by_type'][sig.anomaly_type] = self.stats['by_type'].get(sig.anomaly_type, 0) + 1
            self.stats['by_severity'][sig.severity] = self.stats['by_severity'].get(sig.severity, 0) + 1

        return result

    def get_stats(self) -> Dict:
        """获取检测统计"""
        return self.stats.copy()

    def get_summary(self, df: pd.DataFrame, symbol: str = '') -> Dict:
        """获取异常检测摘要"""
        signals = self.detect(df, symbol)

        return {
            'symbol': symbol,
            'total_bars': len(df),
            'anomaly_count': len(signals),
            'anomaly_rate': len(signals) / len(df) if len(df) > 0 else 0,
            'by_severity': {
                'critical': sum(1 for s in signals if s.severity == 'critical'),
                'high': sum(1 for s in signals if s.severity == 'high'),
                'medium': sum(1 for s in signals if s.severity == 'medium'),
                'low': sum(1 for s in signals if s.severity == 'low'),
            },
            'by_type': {
                t: sum(1 for s in signals if s.anomaly_type == t)
                for t in set(s.anomaly_type for s in signals)
            },
            'latest_anomaly': {
                'time': signals[0].timestamp,
                'type': signals[0].anomaly_type,
                'severity': signals[0].severity,
            } if signals else None,
        }

    def save_models(self, dir_path: str):
        """保存所有模型"""
        Path(dir_path).mkdir(parents=True, exist_ok=True)

        if self.layer2 and self.layer2.is_fitted:
            self.layer2.save_model(f"{dir_path}/lgb_anomaly.pkl")

    def load_models(self, dir_path: str):
        """加载所有模型"""
        lgb_path = f"{dir_path}/lgb_anomaly.pkl"
        if Path(lgb_path).exists() and self.layer2:
            self.layer2.load_model(lgb_path)


def create_anomaly_report(signals: List[AnomalySignal], symbol: str = '') -> str:
    """生成异常检测报告"""
    lines = [
        f"{'='*70}",
        f"  异常检测报告: {symbol}",
        f"{'='*70}",
        f"  发现异常: {len(signals)} 个",
        f"",
    ]

    if not signals:
        lines.append("  ✅ 未发现异常")
    else:
        for i, sig in enumerate(signals[:10], 1):  # 只显示前10个
            emoji = {'critical': '🔴', 'high': '🟠', 'medium': '🟡', 'low': '🟢'}.get(sig.severity, '⚪')
            lines.append(f"  {emoji} [{sig.severity.upper()}] {sig.timestamp}")
            lines.append(f"     类型: {sig.anomaly_type} | 置信度: {sig.confidence:.2f}")
            lines.append(f"     描述: {sig.description}")
            lines.append(f"")

    lines.append(f"{'='*70}")
    return '\n'.join(lines)
