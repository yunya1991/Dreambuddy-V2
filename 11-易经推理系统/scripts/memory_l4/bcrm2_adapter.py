"""
BCRM 2.0 适配器 — 封装辩证ML引擎，提供与 BCRM 1.0 兼容的接口。

支持：
- 自动训练（基于历史K线数据）
- 实时推理（输出与 BCRM 1.0 兼容的格式）
- 模型缓存（避免每次启动重新训练）
"""

import os
import time
import pickle
import hashlib
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any
import logging

logger = logging.getLogger(__name__)


class BCRM2Adapter:
    """
    BCRM 2.0 适配器，封装 DialecticalMLEngine。
    
    提供与 BCRM 1.0 兼容的 infer() 接口，输出格式包含：
    - next_state.direction: UP/DOWN/FLAT
    - next_state.confidence: 0-1
    - is_fail_closed(): bool
    - hexagram: 卦象信息
    """

    def __init__(self, symbol: str, timeframe: str = "1H",
                 model_cache_dir: str = None,
                 train_bars: int = 2000,
                 tp_atr: float = 3.0,
                 sl_atr: float = 1.5,
                 max_hold_bars: int = 60):
        """
        初始化 BCRM 2.0 适配器。
        
        Args:
            symbol: 交易对符号 (如 BTC)
            timeframe: 时间周期 (如 1H)
            model_cache_dir: 模型缓存目录
            train_bars: 训练用K线数量
            tp_atr: 止盈ATR倍数
            sl_atr: 止损ATR倍数
            max_hold_bars: 最大持仓K线数
        """
        self.symbol = symbol
        self.timeframe = timeframe
        self.train_bars = train_bars
        self.tp_atr = tp_atr
        self.sl_atr = sl_atr
        self.max_hold_bars = max_hold_bars
        
        if model_cache_dir is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            model_cache_dir = os.path.join(base_dir, "data", "bcrm2_models")
        self.model_cache_dir = model_cache_dir
        os.makedirs(self.model_cache_dir, exist_ok=True)
        
        self.engine = None
        self.feature_names = []
        self.feature_names_by_gua = {}
        self._df_cache = None
        self._last_train_time = 0
        self._train_interval = 86400  # 24小时重训一次
    
    def _get_cache_key(self, df: pd.DataFrame) -> str:
        """生成数据缓存键"""
        data_str = f"{self.symbol}_{self.timeframe}_{len(df)}_{df.index[0]}_{df.index[-1]}"
        return hashlib.md5(data_str.encode()).hexdigest()[:16]
    
    def _get_model_path(self, cache_key: str) -> str:
        return os.path.join(self.model_cache_dir, f"{self.symbol}_{self.timeframe}_{cache_key}")
    
    def _load_cached_model(self, cache_key: str) -> bool:
        """尝试加载缓存的模型"""
        model_path = self._get_model_path(cache_key)
        meta_path = model_path + "_meta.pkl"
        
        if not os.path.exists(meta_path):
            return False
        
        try:
            with open(meta_path, 'rb') as f:
                meta = pickle.load(f)
            
            from scripts.memory_l4.bcrm2.dialectical_ml_engine import DialecticalMLEngine
            engine = DialecticalMLEngine(
                feature_names=meta['feature_names'],
                feature_names_by_gua=meta['feature_names_by_gua'],
            )
            engine.load(model_path)
            
            self.engine = engine
            self.feature_names = meta['feature_names']
            self.feature_names_by_gua = meta['feature_names_by_gua']
            logger.info(f"[BCRM2] 加载缓存模型: {model_path}")
            return True
        except Exception as e:
            logger.warning(f"[BCRM2] 加载缓存模型失败: {e}")
            return False
    
    def _save_model_cache(self, cache_key: str, engine, 
                          feature_names: list, feature_names_by_gua: dict):
        """保存模型缓存"""
        model_path = self._get_model_path(cache_key)
        meta_path = model_path + "_meta.pkl"
        
        try:
            engine.save(model_path)
            with open(meta_path, 'wb') as f:
                pickle.dump({
                    'feature_names': feature_names,
                    'feature_names_by_gua': feature_names_by_gua,
                    'train_time': time.time(),
                    'symbol': self.symbol,
                    'timeframe': self.timeframe,
                }, f)
            logger.info(f"[BCRM2] 模型已缓存: {model_path}")
        except Exception as e:
            logger.warning(f"[BCRM2] 保存模型缓存失败: {e}")
    
    def train(self, df: pd.DataFrame, force_retrain: bool = False) -> bool:
        """
        训练 BCRM 2.0 模型。
        
        Args:
            df: K线数据 DataFrame (包含 open/high/low/close/volume)
            force_retrain: 强制重新训练
            
        Returns:
            是否训练成功
        """
        if len(df) < 200:
            logger.warning(f"[BCRM2] 数据不足，无法训练: {len(df)} bars")
            return False
        
        # 数据量不够时尝试获取更多
        if len(df) < 500:
            logger.info(f"[BCRM2] K线数据不足({len(df)})，尝试获取更多...")
            try:
                from scripts.memory_l4.bcrm2.data_fetcher import get_klines
                df_more = get_klines(self.symbol, self.timeframe, max_bars=2000)
                if len(df_more) > len(df):
                    df = df_more
                    logger.info(f"[BCRM2] 获取到更多数据: {len(df)} bars")
            except Exception as e:
                logger.warning(f"[BCRM2] 获取更多数据失败: {e}")
        
        if len(df) < 200:
            logger.warning(f"[BCRM2] 数据仍不足，无法训练: {len(df)} bars")
            return False
        
        cache_key = self._get_cache_key(df)
        
        # 尝试加载缓存
        if not force_retrain and self._load_cached_model(cache_key):
            self._df_cache = df.copy()
            self._last_train_time = time.time()
            return True
        
        try:
            from scripts.memory_l4.bcrm2.bagua_feature_engine import BaguaFeatureEngine
            from scripts.memory_l4.bcrm2.dialectical_ml_engine import DialecticalMLEngine
            from scripts.memory_l4.bcrm2.classic_experience_features import ClassicExperienceFeatures
            from scripts.memory_l4.bcrm2.fibonacci_features import FibonacciFeatures
            from scripts.memory_l4.bcrm2.pivot_point_features import PivotPointFeatures
            from scripts.memory_l4.bcrm2.rsi_sentiment_features import RSISentimentFeatures
            from scripts.memory_l4.bcrm2.wdh_features import WDHFeatures
            
            # 数据清洗: 填充NaN，确保特征计算鲁棒
            df = df.copy()
            df = df.ffill().bfill()
            for col in ['open', 'high', 'low', 'close', 'volume']:
                if col in df.columns:
                    df[col] = df[col].replace([np.inf, -np.inf], np.nan).ffill().bfill()
            
            # 计算特征
            logger.info(f"[BCRM2] 计算特征 ({self.symbol} {self.timeframe})...")
            
            feature_engine = BaguaFeatureEngine()
            features = feature_engine.compute(df)
            feature_names = list(features.columns)
            feature_names_by_gua = dict(feature_engine.feature_names_by_gua)
            
            # 经典交易经验特征
            classic_feats = ClassicExperienceFeatures().compute(df)
            features = pd.concat([features, classic_feats], axis=1)
            feature_names = list(features.columns)
            feature_names_by_gua["classic_exp"] = list(classic_feats.columns)
            
            # 斐波那契特征
            fib_feats = FibonacciFeatures().compute(df)
            features = pd.concat([features, fib_feats], axis=1)
            feature_names = list(features.columns)
            feature_names_by_gua["fibonacci"] = list(fib_feats.columns)
            
            # 枢纽点特征
            pivot_feats = PivotPointFeatures().compute(df)
            features = pd.concat([features, pivot_feats], axis=1)
            feature_names = list(features.columns)
            feature_names_by_gua["pivot_point"] = list(pivot_feats.columns)
            
            # RSI情绪特征
            rsi_feats = RSISentimentFeatures().compute(df)
            features = pd.concat([features, rsi_feats], axis=1)
            feature_names = list(features.columns)
            feature_names_by_gua["rsi_sentiment"] = list(rsi_feats.columns)
            
            # WDH三屏特征
            wdh_feats = WDHFeatures().compute(df)
            features = pd.concat([features, wdh_feats], axis=1)
            feature_names = list(features.columns)
            feature_names_by_gua["wdh"] = list(wdh_feats.columns)
            
            # 生成标签（未来N根K线的方向）
            logger.info(f"[BCRM2] 生成标签...")
            closes = df['close'].values
            highs = df['high'].values
            lows = df['low'].values
            
            # 计算ATR
            tr = np.maximum(
                highs[1:] - lows[1:],
                np.maximum(
                    np.abs(highs[1:] - closes[:-1]),
                    np.abs(lows[1:] - closes[:-1])
                )
            )
            atr = np.zeros(len(df))
            atr[14] = np.mean(tr[:14])
            for i in range(15, len(df)):
                atr[i] = (atr[i-1] * 13 + tr[i-1]) / 14
            
            # 生成方向标签：基于止盈止损的触发
            labels = np.zeros(len(df))  # -1=DOWN, 0=FLAT, 1=UP
            valid_mask = np.zeros(len(df), dtype=bool)
            
            for i in range(len(df) - self.max_hold_bars):
                if atr[i] == 0:
                    continue
                tp_long = closes[i] + atr[i] * self.tp_atr
                sl_long = closes[i] - atr[i] * self.sl_atr
                tp_short = closes[i] - atr[i] * self.tp_atr
                sl_short = closes[i] + atr[i] * self.sl_atr
                
                hit_tp_long = False
                hit_sl_long = False
                hit_tp_short = False
                hit_sl_short = False
                
                for j in range(i + 1, min(i + 1 + self.max_hold_bars, len(df))):
                    if not hit_tp_long and highs[j] >= tp_long:
                        hit_tp_long = True
                    if not hit_sl_long and lows[j] <= sl_long:
                        hit_sl_long = True
                    if not hit_tp_short and lows[j] <= tp_short:
                        hit_tp_short = True
                    if not hit_sl_short and highs[j] >= sl_short:
                        hit_sl_short = True
                    
                    if (hit_tp_long or hit_sl_long) and (hit_tp_short or hit_sl_short):
                        break
                
                # 多空都触发：看谁先触发（简化：都不标记）
                if hit_tp_long and not hit_sl_long:
                    labels[i] = 1
                    valid_mask[i] = True
                elif hit_tp_short and not hit_sl_short:
                    labels[i] = -1
                    valid_mask[i] = True
                elif not hit_tp_long and not hit_sl_long and not hit_tp_short and not hit_sl_short:
                    # 都没触发，按最终收益方向
                    final_return = (closes[i + self.max_hold_bars] - closes[i]) / closes[i]
                    if final_return > 0.005:
                        labels[i] = 1
                    elif final_return < -0.005:
                        labels[i] = -1
                    valid_mask[i] = True
            
            # 准备训练数据
            valid_idx = np.where(valid_mask)[0]
            if len(valid_idx) < 100:
                logger.warning(f"[BCRM2] 有效样本不足: {len(valid_idx)}")
                return False
            
            X = features.values[valid_idx]
            y = labels[valid_idx]
            
            # 去除NaN
            nan_mask = ~np.isnan(X).any(axis=1)
            X = X[nan_mask]
            y = y[nan_mask]
            
            if len(X) < 100:
                logger.warning(f"[BCRM2] 去除NaN后样本不足: {len(X)}")
                return False
            
            logger.info(f"[BCRM2] 训练样本: {len(X)} (UP={sum(y==1)} FLAT={sum(y==0)} DOWN={sum(y==-1)})")
            
            # 训练模型
            engine = DialecticalMLEngine(
                feature_names=feature_names,
                feature_names_by_gua=feature_names_by_gua,
            )
            
            logger.info(f"[BCRM2] 训练L1主方向模型...")
            engine.train_l1(X, y)
            
            # Meta-Labeling
            logger.info(f"[BCRM2] 训练L2 Meta-Labeling模型...")
            try:
                engine.train_l2(X, y)
            except Exception as e:
                logger.warning(f"[BCRM2] L2训练失败，跳过: {e}")
            
            self.engine = engine
            self.feature_names = feature_names
            self.feature_names_by_gua = feature_names_by_gua
            self._df_cache = df.copy()
            self._last_train_time = time.time()
            
            # 保存缓存
            self._save_model_cache(cache_key, engine, feature_names, feature_names_by_gua)
            
            logger.info(f"[BCRM2] 训练完成 ({self.symbol} {self.timeframe})")
            return True
            
        except Exception as e:
            logger.error(f"[BCRM2] 训练失败: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def infer(self, df: pd.DataFrame, idx: int = -1) -> Dict[str, Any]:
        """
        执行推理，返回与 BCRM 1.0 兼容的格式。
        
        Args:
            df: K线数据 DataFrame
            idx: 推理位置（默认最后一根）
            
        Returns:
            兼容 BCRM 1.0 输出格式的字典
        """
        if self.engine is None:
            # 自动训练
            if not self.train(df):
                return self._fail_closed_result("模型未训练")
        
        try:
            from scripts.memory_l4.bcrm2.bagua_feature_engine import BaguaFeatureEngine
            from scripts.memory_l4.bcrm2.classic_experience_features import ClassicExperienceFeatures
            from scripts.memory_l4.bcrm2.fibonacci_features import FibonacciFeatures
            from scripts.memory_l4.bcrm2.pivot_point_features import PivotPointFeatures
            from scripts.memory_l4.bcrm2.rsi_sentiment_features import RSISentimentFeatures
            from scripts.memory_l4.bcrm2.wdh_features import WDHFeatures
            
            # 数据清洗: 填充NaN，确保特征计算鲁棒
            df = df.copy()
            df = df.ffill().bfill()
            for col in ['open', 'high', 'low', 'close', 'volume']:
                if col in df.columns:
                    df[col] = df[col].replace([np.inf, -np.inf], np.nan).ffill().bfill()
            
            # 计算特征（只用需要的部分）
            feature_engine = BaguaFeatureEngine()
            features = feature_engine.compute(df)
            
            classic_feats = ClassicExperienceFeatures().compute(df)
            features = pd.concat([features, classic_feats], axis=1)
            
            fib_feats = FibonacciFeatures().compute(df)
            features = pd.concat([features, fib_feats], axis=1)
            
            pivot_feats = PivotPointFeatures().compute(df)
            features = pd.concat([features, pivot_feats], axis=1)
            
            rsi_feats = RSISentimentFeatures().compute(df)
            features = pd.concat([features, rsi_feats], axis=1)
            
            wdh_feats = WDHFeatures().compute(df)
            features = pd.concat([features, wdh_feats], axis=1)
            
            # 确保特征顺序一致
            X_row = features[self.feature_names].values[idx]
            
            # 处理NaN
            if np.isnan(X_row).any():
                X_row = np.nan_to_num(X_row, nan=0.0)
            
            # 推理
            result = self.engine.predict_single(X_row, with_gua=True)
            
            # 转换为 BCRM 1.0 兼容格式
            direction_text = result['direction_text']
            confidence = result['final_confidence']
            hexagram_info = result.get('hexagram', {})
            
            hex_name = hexagram_info.get('hexagram_name', '未知卦')
            hex_name_cn = hexagram_info.get('hexagram_name_cn', hex_name)
            
            # fail_closed 判定：FLAT 或置信度太低
            fail_closed = (direction_text == 'FLAT') or (confidence < 0.3)
            
            return {
                'ok': True,
                'next_state': {
                    'direction': direction_text,
                    'confidence': confidence,
                    'derivation': f"BCRM2.0 L1={result['l1_confidence']:.2f} L2={result.get('l2_confidence', 'N/A')}",
                },
                'hexagram': {
                    'hexagram_name': hex_name,
                    'hexagram_name_cn': hex_name_cn,
                    'changed_hexagram_cn': None,
                },
                'is_fail_closed': lambda: fail_closed,
                'strategy_branches': [],
                'liangyi_state': None,
                'scale_params': None,
                'fail_closed_reason': '' if not fail_closed else (
                    'FLAT方向' if direction_text == 'FLAT' else '置信度不足'
                ),
            }
            
        except Exception as e:
            logger.error(f"[BCRM2] 推理失败: {e}")
            import traceback
            traceback.print_exc()
            return self._fail_closed_result(f"推理失败: {e}")
    
    def _fail_closed_result(self, reason: str) -> Dict[str, Any]:
        """生成 fail_closed 结果"""
        return {
            'ok': False,
            'next_state': {
                'direction': 'FLAT',
                'confidence': 0.0,
                'derivation': reason,
            },
            'hexagram': {
                'hexagram_name': '未济',
                'hexagram_name_cn': '火水未济',
                'changed_hexagram_cn': None,
            },
            'is_fail_closed': lambda: True,
            'strategy_branches': [],
            'liangyi_state': None,
            'scale_params': None,
            'fail_closed_reason': reason,
        }
    
    def maybe_retrain(self, df: pd.DataFrame) -> bool:
        """检查是否需要重训模型"""
        if time.time() - self._last_train_time < self._train_interval:
            return False
        return self.train(df, force_retrain=True)
