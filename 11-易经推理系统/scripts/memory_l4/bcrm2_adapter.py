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
                 max_hold_bars: int = 60,
                 macro_config: dict = None):
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
            macro_config: 宏观特征开关配置 (如 {"macro_feat_fgi_zscore": True, ...})
                          None 表示不传 config (全部启用默认行为)
        """
        self.symbol = symbol
        self.timeframe = timeframe
        self.train_bars = train_bars
        self.tp_atr = tp_atr
        self.sl_atr = sl_atr
        self.max_hold_bars = max_hold_bars
        self.macro_config = macro_config or {}
        
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
        """生成数据缓存键（含 macro_config 哈希，配置变更自动重训）"""
        data_str = f"{self.symbol}_{self.timeframe}_{len(df)}_{df.index[0]}_{df.index[-1]}"
        if self.macro_config:
            import json as _json
            cfg_str = _json.dumps(self.macro_config, sort_keys=True)
            data_str += f"_macro_{hashlib.md5(cfg_str.encode()).hexdigest()[:8]}"
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

    def _fetch_ref_df(self, df: pd.DataFrame) -> Optional[pd.DataFrame]:
        """获取 BTC 参考数据用于跨资产特征和 L2 MetaLabeling"""
        if self.symbol.upper() in ("BTC", "BTC-USDT-SWAP"):
            return None  # BTC 自身不需要 ref_df

        try:
            from scripts.memory_l4.bcrm2.data_fetcher import get_klines
            # 获取与 df 时间范围对齐的 BTC K线
            ref_df = get_klines("BTC", self.timeframe, max_bars=max(len(df) + 200, 5000))
            if ref_df is not None and len(ref_df) > 200:
                # ══════════════════════════════════════════════════════
                # Bug修复: 统一时区，避免 datetime64[ns] vs datetime64[ns, UTC] 冲突
                # ══════════════════════════════════════════════════════
                # 如果 df.index 有时区，确保 ref_df.index 也有同样的时区；反之亦然
                df_tz = df.index.tz
                ref_tz = ref_df.index.tz
                if df_tz is not None and ref_tz is None:
                    # df有时区，ref没有 → 给ref加UTC再转换到df的时区（或直接localize到UTC再tz_convert）
                    ref_df = ref_df.tz_localize("UTC")
                    if str(df_tz) != "UTC":
                        ref_df = ref_df.tz_convert(df_tz)
                elif df_tz is None and ref_tz is not None:
                    # df无时区，ref有时区 → 去除ref的时区
                    ref_df = ref_df.tz_localize(None)
                elif df_tz is not None and ref_tz is not None and str(df_tz) != str(ref_tz):
                    # 两者有时区但不同 → 统一到df的时区
                    ref_df = ref_df.tz_convert(df_tz)
                # 对齐索引到 df
                ref_df = ref_df.reindex(df.index, method='ffill')
                return ref_df
        except Exception as e:
            logger.warning(f"[BCRM2] 获取 BTC ref_df 失败: {e}")
        return None

    def _fetch_macro_df(self, df: pd.DataFrame) -> Optional[pd.DataFrame]:
        """获取宏观数据用于宏观特征模块（P1）"""
        try:
            from scripts.memory_l4.bcrm2.macro_data_fetcher import MacroDataFetcher
            fetcher = MacroDataFetcher()
            macro_df = fetcher.fetch_all(self.symbol, df.index, live=True, verbose=False)
            if macro_df is not None and not macro_df.empty:
                return macro_df
        except Exception as e:
            logger.warning(f"[BCRM2] 获取宏观数据失败: {e}")
        return None

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
        
        # 确保数据可写（pandas 新版本 .values 可能返回只读视图）
        df = df.copy()
        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col in df.columns:
                df[col] = df[col].values.copy()
        
        cache_key = self._get_cache_key(df)
        
        # 尝试加载缓存
        if not force_retrain and self._load_cached_model(cache_key):
            self._df_cache = df.copy()
            self._last_train_time = time.time()
            return True
        
        try:
            from scripts.memory_l4.bcrm2.feature_registry import FeatureRegistry
            from scripts.memory_l4.bcrm2.dialectical_ml_engine import DialecticalMLEngine
            # 触发所有模块注册
            import scripts.memory_l4.bcrm2.bagua_feature_engine  # noqa: F401
            import scripts.memory_l4.bcrm2.classic_experience_features  # noqa: F401
            import scripts.memory_l4.bcrm2.fibonacci_features  # noqa: F401
            import scripts.memory_l4.bcrm2.pivot_point_features  # noqa: F401
            import scripts.memory_l4.bcrm2.rsi_sentiment_features  # noqa: F401
            import scripts.memory_l4.bcrm2.wdh_features  # noqa: F401
            import scripts.memory_l4.bcrm2.cycle_features  # noqa: F401
            import scripts.memory_l4.bcrm2.market_cap  # noqa: F401
            import scripts.memory_l4.bcrm2.cross_asset_features  # noqa: F401
            import scripts.memory_l4.bcrm2.merrill_clock_features  # noqa: F401
            import scripts.memory_l4.bcrm2.macro_features  # noqa: F401

            # 数据清洗: 填充NaN，确保特征计算鲁棒
            df = df.copy()
            df = df.ffill().bfill()
            for col in ['open', 'high', 'low', 'close', 'volume']:
                if col in df.columns:
                    df[col] = df[col].replace([np.inf, -np.inf], np.nan).ffill().bfill()
                    df[col] = df[col].values.copy()

            # 计算特征
            logger.info(f"[BCRM2] 计算特征 ({self.symbol} {self.timeframe})...")

            # 获取 BTC 参考数据
            ref_df = self._fetch_ref_df(df)

            # 获取宏观数据（P1）
            macro_df = self._fetch_macro_df(df)

            features, feature_names_by_gua = FeatureRegistry.compute_all(
                df=df,
                ref_df=ref_df,
                macro_df=macro_df,
                symbol=self.symbol,
                config=self.macro_config,
                verbose=True,
            )
            feature_names = list(features.columns)

            # 保存 cycle_feats 给 L2 用
            cycle_cols = []
            for key in ["cycle_halving", "cycle_ath", "cycle_inventory", "cycle_long_term"]:
                cycle_cols.extend(feature_names_by_gua.get(key, []))
            cycle_feats = features[cycle_cols] if cycle_cols else None
            
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
            
            # 生成方向标签：二分类 (UP=1, DOWN=0)
            labels = np.zeros(len(df))  # 0=DOWN, 1=UP
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
                hit_time_long = None
                hit_time_short = None
                
                for j in range(i + 1, min(i + 1 + self.max_hold_bars, len(df))):
                    if not hit_tp_long and highs[j] >= tp_long:
                        hit_tp_long = True
                        hit_time_long = j - i
                    if not hit_sl_long and lows[j] <= sl_long:
                        hit_sl_long = True
                    if not hit_tp_short and lows[j] <= tp_short:
                        hit_tp_short = True
                        hit_time_short = j - i
                    if not hit_sl_short and highs[j] >= sl_short:
                        hit_sl_short = True
                
                # 优先标记明确的止盈止损信号
                if hit_tp_long and not hit_sl_long:
                    labels[i] = 1
                    valid_mask[i] = True
                elif hit_tp_short and not hit_sl_short:
                    labels[i] = 0
                    valid_mask[i] = True
                elif hit_tp_long and hit_tp_short:
                    # 双方都触止盈，看谁先触发
                    if hit_time_long and hit_time_short:
                        labels[i] = 1 if hit_time_long < hit_time_short else 0
                        valid_mask[i] = True
                elif not hit_tp_long and not hit_sl_long and not hit_tp_short and not hit_sl_short:
                    # 都没触发，按最终收益方向
                    final_return = (closes[i + self.max_hold_bars] - closes[i]) / closes[i]
                    if abs(final_return) > 0.002:  # 降低阈值，增加样本
                        labels[i] = 1 if final_return > 0 else 0
                        valid_mask[i] = True
            
            # 准备训练数据
            valid_idx = np.where(valid_mask)[0]
            if len(valid_idx) < 100:
                logger.warning(f"[BCRM2] 有效样本不足: {len(valid_idx)}")
                # v3.0：返回 "insufficient_data" 而非 False，让调用方区分数据不足 vs 训练异常
                return "insufficient_data"
            
            X = features.values[valid_idx]
            y = labels[valid_idx]
            
            # 同步筛选df到有效样本
            df_valid = df.iloc[valid_idx].copy()
            
            # 去除NaN
            nan_mask = ~np.isnan(X).any(axis=1)
            X = X[nan_mask]
            y = y[nan_mask]
            df_valid = df_valid.iloc[nan_mask].copy()
            
            if len(X) < 100:
                logger.warning(f"[BCRM2] 去除NaN后样本不足: {len(X)}")
                return "insufficient_data"
            
            logger.info(f"[BCRM2] 训练样本: {len(X)} (UP={sum(y==1)} DOWN={sum(y==0)})")
            
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
                engine.train_l2(
                    X, y,
                    df=df_valid,
                    ref_df=ref_df.iloc[valid_idx][nan_mask] if ref_df is not None else None,
                    cycle_phase=cycle_feats.iloc[valid_idx][nan_mask] if cycle_feats is not None else None,
                )
            except Exception as e:
                logger.warning(f"[BCRM2] L2训练失败，跳过: {e}")
            
            self.engine = engine
            self.feature_names = feature_names
            self.feature_names_by_gua = feature_names_by_gua
            self._df_cache = df.copy()
            self._last_train_time = time.time()

            # ── Phase C (Spec §4.3.3): 多 horizon 并行训练 ──────────────
            # 每个 horizon h 独立训练 LGBM 模型，用于 predict_multi_horizon。
            # 失败不影响主模型（主方向交易仍用 L1/L2）。
            try:
                from scripts.memory_l4.bcrm2.triple_barrier_labeler import triple_barrier_labels

                HORIZONS_DEFAULT = [1, 2, 3, 6, 10, 20, 30]
                mh_labels_dfs = triple_barrier_labels(
                    df,
                    tp_factor=float(self.tp_atr),
                    sl_factor=float(self.sl_atr),
                    max_bars=max(HORIZONS_DEFAULT),
                    use_atr=True,
                    atr_period=14,
                    atr_multiplier_tp=float(self.tp_atr),
                    atr_multiplier_sl=float(self.sl_atr),
                    multi_horizons=HORIZONS_DEFAULT,
                )
                # 对齐 valid_idx + nan_mask 到特征集 X 有效样本（与 L1 完全一致）
                X_all = features.values.copy()
                X_nan_mask = ~np.isnan(X_all).any(axis=1)

                labels_by_h = {}
                horizons_ready = []
                for h in HORIZONS_DEFAULT:
                    mh_df = mh_labels_dfs.get(h)
                    if mh_df is None:
                        continue
                    y_h_full = mh_df["label"].values.copy()
                    # 对齐到 valid_idx
                    y_valid = y_h_full[valid_idx] if len(y_h_full) >= len(df) else y_h_full
                    # 对齐 nan_mask
                    y_clean = y_valid[nan_mask]
                    if len(y_clean) == len(X[nan_mask]):
                        labels_by_h[h] = y_clean
                        horizons_ready.append(h)

                if horizons_ready:
                    mh_report = engine.fit_multi_horizon(
                        X[nan_mask], labels_by_h, horizons_ready
                    )
                    horizons_trained = [h for h, r in mh_report.items()
                                        if float(r.get("train_accuracy", 0)) > 0]
                    logger.info(
                        f"[BCRM2] 多horizon训练完成 ({self.symbol})："
                        f"{len(horizons_trained)}/{len(horizons_ready)} 个训练成功"
                    )
                else:
                    logger.info(
                        f"[BCRM2] 多horizon训练跳过：无可用标签 ({self.symbol})"
                    )
            except Exception as _mh_e:
                logger.warning(
                    f"[BCRM2] 多horizon训练失败(不影响主模型)：{_mh_e} ({self.symbol})"
                )

            # 保存缓存（包含多horizon模型）
            self._save_model_cache(cache_key, engine, feature_names, feature_names_by_gua)

            logger.info(f"[BCRM2] 训练完成 ({self.symbol} {self.timeframe})")
            return True
            
        except Exception as e:
            logger.error(f"[BCRM2] 训练失败: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def infer(self, df: pd.DataFrame, idx: int = -1, auto_train: bool = True) -> Dict[str, Any]:
        """
        执行推理，返回与 BCRM 1.0 兼容的格式。
        
        Args:
            df: K线数据 DataFrame
            idx: 推理位置（默认最后一根）
            auto_train: 模型未就绪时是否自动触发训练
            
        Returns:
            兼容 BCRM 1.0 输出格式的字典
        """
        if self.engine is None:
            # 先尝试加载缓存模型
            cache_key = self._get_cache_key(df)
            if self._load_cached_model(cache_key):
                pass  # 加载成功
            elif auto_train:
                if not self.train(df):
                    return self._fail_closed_result("模型未训练")
            else:
                return self._fail_closed_result("模型未就绪")
        
        try:
            from scripts.memory_l4.bcrm2.feature_registry import FeatureRegistry
            # 触发所有模块注册
            import scripts.memory_l4.bcrm2.bagua_feature_engine  # noqa: F401
            import scripts.memory_l4.bcrm2.classic_experience_features  # noqa: F401
            import scripts.memory_l4.bcrm2.fibonacci_features  # noqa: F401
            import scripts.memory_l4.bcrm2.pivot_point_features  # noqa: F401
            import scripts.memory_l4.bcrm2.rsi_sentiment_features  # noqa: F401
            import scripts.memory_l4.bcrm2.wdh_features  # noqa: F401
            import scripts.memory_l4.bcrm2.cycle_features  # noqa: F401
            import scripts.memory_l4.bcrm2.market_cap  # noqa: F401
            import scripts.memory_l4.bcrm2.cross_asset_features  # noqa: F401
            import scripts.memory_l4.bcrm2.merrill_clock_features  # noqa: F401
            import scripts.memory_l4.bcrm2.macro_features  # noqa: F401

            # 数据清洗: 填充NaN，确保特征计算鲁棒
            df = df.copy()
            df = df.ffill().bfill()
            for col in ['open', 'high', 'low', 'close', 'volume']:
                if col in df.columns:
                    df[col] = df[col].replace([np.inf, -np.inf], np.nan).ffill().bfill()
                    df[col] = df[col].values.copy()

            # 计算特征
            ref_df = self._fetch_ref_df(df)
            macro_df = self._fetch_macro_df(df)
            features, feature_names_by_gua = FeatureRegistry.compute_all(
                df=df,
                ref_df=ref_df,
                macro_df=macro_df,
                symbol=self.symbol,
                config=self.macro_config,
            )
            
            # 确保特征顺序一致
            # 处理训练时存在但推理时缺失的特征
            for fn in self.feature_names:
                if fn not in features.columns:
                    features[fn] = 0.0
            X_row = features[self.feature_names].values[idx]
            
            # 处理NaN
            if np.isnan(X_row).any():
                X_row = np.nan_to_num(X_row, nan=0.0)
            
            # 推理
            result = self.engine.predict_single(X_row, with_gua=True, df=df)
            
            # 转换为 BCRM 1.0 兼容格式
            direction_text = result['direction_text']
            confidence = result['final_confidence']
            hexagram_info = result.get('hexagram', {})
            
            hex_name = hexagram_info.get('hexagram_name', '未知卦')
            hex_name_cn = hexagram_info.get('hexagram_name_cn', hex_name)
            
            # fail_closed 判定：置信度太低
            # 二分类无FLAT，仅根据置信度判断
            fail_closed = confidence < 0.3
            
            # KG 知识图谱增强（2026-07-21 修复：接入知识图谱推理校准置信度）
            kg_confidence_adjustment = 0.0
            kg_strategy_notes = []
            if not fail_closed:
                try:
                    from scripts.memory_l4.kg_query import KGQueryEngine
                    kg_engine = KGQueryEngine()
                    regime = hexagram_info.get('liangyi_state', {}).get('macro_phase', '')
                    recommendations = kg_engine.recommend_strategy(
                        inst_id=f"{self.symbol}-USDT-SWAP",
                        regime=regime,
                        hexagram=hex_name_cn,
                    )
                    if recommendations:
                        top_rec = recommendations[0]
                        # 如果历史推荐与当前方向一致，提升置信度；反之降低
                        kg_win_rate = top_rec.get('win_rate', 0.5)
                        if kg_win_rate > 0.6:
                            kg_confidence_adjustment = 0.03
                            kg_strategy_notes.append(f"KG历史胜率{kg_win_rate:.1%}支持当前方向")
                        elif kg_win_rate < 0.4:
                            kg_confidence_adjustment = -0.03
                            kg_strategy_notes.append(f"KG历史胜率{kg_win_rate:.1%}警告当前方向")
                        logger.info(f"[BCRM2] KG增强: {kg_strategy_notes}")
                except Exception as e:
                    logger.warning(f"[BCRM2] KG增强失败: {e}")
            
            # 应用 KG 校准
            confidence = min(1.0, max(0.0, confidence + kg_confidence_adjustment))

            # A0 矛盾分析增强（纯代码驱动，不依赖大模型）
            a0_result = None
            a0_adjustment = 0.0
            a0_warnings = []
            if not fail_closed:
                try:
                    from scripts.memory_l4.a0_contradiction_engine import A0ContradictionEngine

                    a0_engine = A0ContradictionEngine()
                    a0_result = a0_engine.analyze(
                        df, inst_id=f"{self.symbol}-USDT-SWAP",
                    )

                    # 方向一致性校准
                    bcrm_direction = 1 if direction_text == "UP" else -1
                    if a0_result.direction_bias * bcrm_direction > 0:
                        # A0 与 BCRM 方向一致 → 增强置信度
                        a0_adjustment = abs(a0_result.confidence_adjustment)
                    else:
                        # A0 与 BCRM 方向不一致 → 削弱置信度
                        a0_adjustment = -abs(a0_result.confidence_adjustment)

                    # 创伤信号 → 大幅降低置信度
                    if a0_result.trauma_signal:
                        a0_adjustment -= 0.15
                        a0_warnings.append("创伤信号：连续3次同方向错误，强制降级")

                    # 极端张力 → 额外风险预警
                    if a0_result.overall_tension > 0.7:
                        a0_warnings.append(a0_result.risk_warning)

                    if a0_warnings:
                        logger.warning(f"[BCRM2] A0预警: {a0_warnings}")
                    logger.info(
                        f"[BCRM2] A0矛盾分析: 综合张力={a0_result.overall_tension:.2f} "
                        f"方向偏置={a0_result.direction_bias:+.2f} "
                        f"调整={a0_adjustment:+.4f} "
                        f"主矛盾={a0_result.primary_contradiction.name if a0_result.primary_contradiction else 'N/A'}"
                    )
                except Exception as e:
                    logger.warning(f"[BCRM2] A0矛盾分析失败: {e}")

            # 应用 A0 校准
            confidence = min(1.0, max(0.0, confidence + a0_adjustment))

            # 如果 A0 创伤信号导致置信度过低，标记 fail_closed
            if a0_result and a0_result.trauma_signal and confidence < 0.4:
                fail_closed = True

            # 五角校验：BCRM2(ML) × 力学引擎(物理) × A0(矛盾) × Ising(相变) × TDA(拓扑)
            triangle_result = None
            triangle_adjustment = 0.0
            triangle_warnings = []
            # P3预警联动参数默认值（fail_closed 时使用默认值，避免 NameError）
            position_factor = 1.0
            sl_tighten_factor = 1.0
            early_exit_signal = False
            leverage_factor = 1.0
            tp_adjustment = 1.0
            risk_score = 0.0
            risk_level = "NORMAL"
            if not fail_closed:
                try:
                    from scripts.memory_l4.triangle_verifier import TriangleVerifier

                    verifier = TriangleVerifier()
                    market_snapshot = {
                        "volatility": float(df["close"].pct_change().tail(20).std()) if len(df) >= 20 else 0.03,
                    }
                    triangle_result = verifier.verify(
                        bcrm2_direction=direction_text,
                        bcrm2_confidence=confidence,
                        a0_result_dict=a0_result.to_dict() if a0_result else None,
                        market_snapshot=market_snapshot,
                        df=df,
                    )

                    triangle_adjustment = triangle_result.confidence_adjustment
                    triangle_warnings = triangle_result.risk_warnings

                    # 强反转预警 → 削弱置信度
                    if triangle_result.reversal_alert:
                        a0_warnings.append(f"三角反转预警: 强度={triangle_result.reversal_strength:.2f}")

                    # v4 风险评分风控：仓位/杠杆/止盈/止损/风险评分
                    position_factor = triangle_result.position_factor if triangle_result else 1.0
                    sl_tighten_factor = triangle_result.sl_tighten_factor if triangle_result else 1.0
                    early_exit_signal = triangle_result.early_exit_signal if triangle_result else False
                    leverage_factor = triangle_result.leverage_factor if triangle_result else 1.0
                    tp_adjustment = triangle_result.tp_adjustment if triangle_result else 1.0
                    risk_score = triangle_result.risk_score if triangle_result else 0.0
                    risk_level = triangle_result.risk_level if triangle_result else "NORMAL"

                    # 三源严重分歧 → fail_closed
                    if triangle_result.should_fail_closed:
                        fail_closed = True

                    logger.info(
                        f"[BCRM2] 三角校验: {triangle_result.verdict} "
                        f"一致性={triangle_result.agreement_score:.0%} "
                        f"调整={triangle_adjustment:+.4f}"
                    )
                except Exception as e:
                    logger.warning(f"[BCRM2] 三角校验失败: {e}")

            # 应用三角校验调整
            confidence = min(1.0, max(0.0, confidence + triangle_adjustment))

            return {
                'ok': True,
                'next_state': {
                    'direction': direction_text,
                    'confidence': confidence,
                    'derivation': f"BCRM2.0 L1={result['l1_confidence']:.2f} L2={result.get('l2_confidence', 'N/A')} A0_adj={a0_adjustment:+.3f} TRI_adj={triangle_adjustment:+.3f}",
                },
                'hexagram': hexagram_info if hexagram_info else {
                    'hexagram_name': hex_name,
                    'hexagram_name_cn': hex_name_cn,
                    'changed_hexagram_cn': None,
                },
                'is_fail_closed': lambda: fail_closed,
                'strategy_branches': [],
                'liangyi_state': None,
                'scale_params': None,
                'a0_analysis': a0_result.to_dict() if a0_result else None,
                'a0_warnings': a0_warnings,
                'triangle_verification': triangle_result.to_dict() if triangle_result else None,
                'fail_closed_reason': '' if not fail_closed else (
                    'FLAT方向' if direction_text == 'FLAT' else
                    ('三源严重分歧' if triangle_result and triangle_result.should_fail_closed else
                     ('A0创伤信号降级' if a0_result and a0_result.trauma_signal else '置信度不足'))
                ),
                # v4 风险评分风控参数
                'position_factor': position_factor,
                'sl_tighten_factor': sl_tighten_factor,
                'early_exit_signal': early_exit_signal,
                'leverage_factor': leverage_factor,
                'tp_adjustment': tp_adjustment,
                'risk_score': risk_score,
                'risk_level': risk_level,
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
            # P3预警联动参数（fail_closed 时使用默认值）
            'position_factor': 1.0,
            'sl_tighten_factor': 1.0,
            'early_exit_signal': False,
        }
    
    def maybe_retrain(self, df: pd.DataFrame) -> bool:
        """检查是否需要重训模型"""
        if time.time() - self._last_train_time < self._train_interval:
            return False
        return self.train(df, force_retrain=True)

    def predict_multi_horizon(
        self,
        df: pd.DataFrame,
        horizons: List[int] = None,
        idx: int = -1,
    ) -> Dict[str, Any]:
        """Phase C (Spec §4.3.1): 多 horizon 预测接口。

        复用 infer() 的特征计算管线，但调用 engine.predict_multi_horizon()
        返回每个 horizon 的 P_up/P_down 概率对 + 合成曲线指标。

        Args:
            df: K线数据 DataFrame
            horizons: horizon 列表，默认 [1,2,3,6,10,20,30]
            idx: 推理位置（默认最后一根）

        Returns:
            {
                "ok": bool,
                "direction": "UP"|"DOWN",
                "final_confidence": float,
                "multi_horizon": {h: {"P_up": float, "P_down": float}},
                "synthesis": {S_curve, L_curve, HORIZON_K_STAR, ...},
                "is_fail_closed": callable,
            }
        """
        if horizons is None:
            horizons = [1, 2, 3, 6, 10, 20, 30]

        # 确保引擎已加载
        if self.engine is None:
            cache_key = self._get_cache_key(df)
            if not self._load_cached_model(cache_key):
                if not self.train(df):
                    return {
                        "ok": False,
                        "direction": "FLAT",
                        "final_confidence": 0.0,
                        "multi_horizon": {},
                        "synthesis": {},
                        "is_fail_closed": lambda: True,
                        "fail_closed_reason": "模型未训练",
                    }

        try:
            from scripts.memory_l4.bcrm2.feature_registry import FeatureRegistry
            import scripts.memory_l4.bcrm2.bagua_feature_engine  # noqa: F401
            import scripts.memory_l4.bcrm2.classic_experience_features  # noqa: F401
            import scripts.memory_l4.bcrm2.fibonacci_features  # noqa: F401
            import scripts.memory_l4.bcrm2.pivot_point_features  # noqa: F401
            import scripts.memory_l4.bcrm2.rsi_sentiment_features  # noqa: F401
            import scripts.memory_l4.bcrm2.wdh_features  # noqa: F401
            import scripts.memory_l4.bcrm2.cycle_features  # noqa: F401
            import scripts.memory_l4.bcrm2.market_cap  # noqa: F401
            import scripts.memory_l4.bcrm2.cross_asset_features  # noqa: F401
            import scripts.memory_l4.bcrm2.merrill_clock_features  # noqa: F401
            import scripts.memory_l4.bcrm2.macro_features  # noqa: F401

            df = df.copy()
            df = df.ffill().bfill()
            for col in ['open', 'high', 'low', 'close', 'volume']:
                if col in df.columns:
                    df[col] = df[col].replace([np.inf, -np.inf], np.nan).ffill().bfill()
                    df[col] = df[col].values.copy()

            ref_df = self._fetch_ref_df(df)
            macro_df = self._fetch_macro_df(df)
            features, _ = FeatureRegistry.compute_all(
                df=df, ref_df=ref_df, macro_df=macro_df,
                symbol=self.symbol, config=self.macro_config,
            )

            for fn in self.feature_names:
                if fn not in features.columns:
                    features[fn] = 0.0
            X_row = features[self.feature_names].values[idx]
            if np.isnan(X_row).any():
                X_row = np.nan_to_num(X_row, nan=0.0)

            # 多 horizon 预测
            mh_result = self.engine.predict_multi_horizon(
                X_row.reshape(1, -1), horizons
            )

            # 合成曲线
            from scripts.memory_l4.trading_utils import RiskManager
            pos_sign = 1 if mh_result["direction"] == "UP" else -1
            synthesis = RiskManager.synthesize_horizon_curves(
                mh_result["multi_horizon"], pos_sign=pos_sign
            )

            return {
                "ok": True,
                "direction": mh_result["direction"],
                "final_confidence": mh_result["final_confidence"],
                "multi_horizon": mh_result["multi_horizon"],
                "synthesis": synthesis,
                "is_fail_closed": lambda: False,
            }

        except Exception as e:
            logger.error(f"[BCRM2] predict_multi_horizon 失败: {e}")
            return {
                "ok": False,
                "direction": "FLAT",
                "final_confidence": 0.0,
                "multi_horizon": {},
                "synthesis": {},
                "is_fail_closed": lambda: True,
                "fail_closed_reason": str(e),
            }
