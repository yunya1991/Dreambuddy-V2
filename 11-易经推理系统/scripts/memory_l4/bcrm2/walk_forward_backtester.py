"""
Walk-Forward 回测框架 — 实践检验真理的算法落地

理论映射 (实践论 → Walk-Forward):
  实践 → 回测/模拟盘/实盘 (用历史或真实市场检验)
  认识 → 模型训练 (从数据中提炼规律)
  实践-认识循环 → Walk-Forward 滚动验证 (不断用新实践修正认识)
  真理标准 → 样本外表现 (不是训练集表现，而是未见过的数据)

核心原则:
  避免数据泄露 → 严格时间分割，训练集永远在测试集之前
  避免过拟合 → Walk-Forward多折验证，不是单次分割
  可重复性 → 固定随机种子，相同数据得到相同结果
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, field
from tqdm import tqdm

from .bagua_feature_engine import BaguaFeatureEngine
from .triple_barrier_labeler import DialecticalLabeler
from .dialectical_ml_engine import DialecticalMLEngine
from .cross_asset_features import compute_cross_asset_features
from .classic_experience_features import ClassicExperienceFeatures
from .fibonacci_features import FibonacciFeatures
from .pivot_point_features import PivotPointFeatures
from .rsi_sentiment_features import RSISentimentFeatures
from .wdh_features import WDHFeatures
from .cycle_features import CycleFeatures
from .market_cap import MarketCapClassifier, apply_mcap_feature_config
from .merrill_clock_features import MerrillClockFeatures
from .feature_selector import FeatureSelector


# ============================================================
# 回测结果数据结构
# ============================================================

@dataclass
class Trade:
    """单笔交易记录"""
    entry_bar: int
    exit_bar: int
    direction: int  # 1=long, -1=short
    entry_price: float
    exit_price: float
    pnl_pct: float
    hold_bars: int
    exit_reason: str  # tp/sl/time/close
    confidence: float
    hexagram_name: str = ""
    upper_gua: str = ""
    lower_gua: str = ""
    position_factor: float = 1.0


@dataclass
class FoldResult:
    """单个fold的结果"""
    fold_id: int
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    n_train: int
    n_test: int
    trades: List[Trade] = field(default_factory=list)
    predictions: List[Dict] = field(default_factory=list)

    @property
    def n_trades(self) -> int:
        return len(self.trades)

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        return sum(1 for t in self.trades if t.pnl_pct > 0) / len(self.trades)

    @property
    def total_return(self) -> float:
        if not self.trades:
            return 0.0
        return sum(t.pnl_pct for t in self.trades)

    @property
    def avg_return(self) -> float:
        if not self.trades:
            return 0.0
        return self.total_return / len(self.trades)

    @property
    def max_drawdown(self) -> float:
        if not self.trades:
            return 0.0
        cumulative = np.cumsum([t.pnl_pct for t in self.trades])
        peak = np.maximum.accumulate(cumulative)
        drawdown = peak - cumulative
        return float(np.max(drawdown))

    @property
    def profit_factor(self) -> float:
        if not self.trades:
            return 0.0
        wins = sum(t.pnl_pct for t in self.trades if t.pnl_pct > 0)
        losses = abs(sum(t.pnl_pct for t in self.trades if t.pnl_pct < 0))
        return wins / losses if losses > 0 else float('inf')


@dataclass
class BacktestResult:
    """完整回测结果"""
    symbol: str
    n_folds: int
    folds: List[FoldResult] = field(default_factory=list)
    all_trades: List[Trade] = field(default_factory=list)

    # 汇总指标
    total_trades: int = 0
    overall_win_rate: float = 0.0
    total_return: float = 0.0
    avg_return_per_trade: float = 0.0
    max_drawdown: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    avg_hold_bars: float = 0.0

    # 按方向统计
    long_stats: Dict = field(default_factory=dict)
    short_stats: Dict = field(default_factory=dict)

    # 卦象统计
    hexagram_stats: Dict[str, Dict] = field(default_factory=dict)
    # 上卦分布 (八卦维度活跃度)
    upper_gua_stats: Dict[str, int] = field(default_factory=dict)
    # 下卦分布
    lower_gua_stats: Dict[str, int] = field(default_factory=dict)


# ============================================================
# Walk-Forward 回测引擎
# ============================================================

class WalkForwardBacktester:
    """
    Walk-Forward 滚动回测引擎

    理论基础: 实践-认识-再实践-再认识，循环往复以至无穷
    每个fold都是一次"实践→认识→再实践"的完整循环

    工作流程:
      1. 用train训练集训练模型 (认识)
      2. 在test测试集上交易 (实践)
      3. 滚动到下一个时间窗口 (再实践→再认识)
    """

    def __init__(
        self,
        symbol: str = "BTC",
        n_folds: int = 5,
        train_ratio: float = 0.7,
        min_train_bars: int = 500,
        min_test_bars: int = 100,
        conf_threshold: float = 0.40,
        tp_atr: float = 3.0,
        sl_atr: float = 2.0,
        max_hold_bars: int = 60,
        atr_period: int = 14,
        fee_rate: float = 0.0004,  # 0.04% 手续费
        slippage_rate: float = 0.0002,  # 0.02% 滑点
        feature_selection: bool = False,
        fs_imp_threshold: float = 0.01,
        fs_corr_threshold: float = 0.85,
        use_regime_switching: bool = False,  # 是否启用市态切换
        use_meta_labeling: bool = False,  # 是否启用L2 Meta-Labeling
    ):
        self.symbol = symbol
        self.n_folds = n_folds
        self.train_ratio = train_ratio
        self.min_train_bars = min_train_bars
        self.min_test_bars = min_test_bars
        self.conf_threshold = conf_threshold
        self.tp_atr = tp_atr
        self.sl_atr = sl_atr
        self.max_hold_bars = max_hold_bars
        self.atr_period = atr_period
        self.fee_rate = fee_rate
        self.slippage_rate = slippage_rate
        self.feature_selection = feature_selection
        self.fs_imp_threshold = fs_imp_threshold
        self.fs_corr_threshold = fs_corr_threshold
        self.use_regime_switching = use_regime_switching
        self.use_meta_labeling = use_meta_labeling

        # 组件
        self.feature_engine = BaguaFeatureEngine()
        self.classic_features = ClassicExperienceFeatures()
        self.fib_features = FibonacciFeatures()
        self.pivot_features = PivotPointFeatures()
        self.rsi_features = RSISentimentFeatures()
        self.wdh_features = WDHFeatures()
        self.cycle_features = CycleFeatures(symbol=symbol)
        self.mcap_classifier = MarketCapClassifier()
        self.merrill_features = MerrillClockFeatures(symbol=symbol)
        self.labeler = DialecticalLabeler(
            tp_atr=tp_atr,
            sl_atr=sl_atr,
            max_bars=max_hold_bars,
            atr_period=atr_period,
        )

    def run(
        self,
        df: pd.DataFrame,
        ref_df: Optional[pd.DataFrame] = None,
        verbose: bool = True,
        enable_pivot: bool = True,
        enable_rsi: bool = True,
        enable_wdh: bool = True,
        wdh_weekly_only: bool = False,
        enable_cycle: bool = False,
        cycle_halving: bool = True,
        cycle_ath: bool = True,
        cycle_inventory: bool = True,
        cycle_long_term: bool = True,
        enable_mcap: bool = False,
        auto_mcap_config: bool = True,
        enable_merrill: bool = False,
        merrill_inflation: bool = True,
        merrill_growth: bool = True,
        merrill_capital_flow: bool = True,
        merrill_phase: bool = True,
        merrill_cross: bool = True,
    ) -> BacktestResult:
        """
        执行完整的walk-forward回测

        Args:
            df: OHLCV数据
            ref_df: 参考资产OHLCV (如BTC数据，用于跨资产特征)
            verbose: 是否显示进度条
            enable_pivot: 是否启用枢纽点特征
            enable_rsi: 是否启用RSI情绪特征
            enable_wdh: 是否启用周/日/时三屏+量变积累特征
            wdh_weekly_only: WDH只保留周线层 (消融实验)
            enable_cycle: 是否启用库存周期特征 (基钦周期+减半+牛熊线)
            cycle_halving: 周期特征-减半周期子模块
            cycle_ath: 周期特征-历史高低点子模块
            cycle_inventory: 周期特征-库存四阶段子模块
            cycle_long_term: 周期特征-长期趋势MA子模块
            enable_mcap: 是否启用市值特征 (等级+波动率归一化)
            auto_mcap_config: 自动按市值等级配置特征开关 (大/中/小市值各有不同)
            enable_merrill: 是否启用美林时钟周期特征 (通胀+增长+资金流转+四阶段)
            merrill_inflation: 美林时钟-通胀代理子模块
            merrill_growth: 美林时钟-增长代理子模块
            merrill_capital_flow: 美林时钟-资金流转子模块
            merrill_phase: 美林时钟-四阶段分类子模块
            merrill_cross: 美林时钟-交叉周期子模块

        Returns:
            BacktestResult 汇总结果
        """
        result = BacktestResult(symbol=self.symbol, n_folds=self.n_folds)

        # 初始化可选特征DataFrame
        cycle_feats = None

        # 按市值等级自动配置特征 (如果开启auto_mcap)
        if auto_mcap_config:
            cfg = self.mcap_classifier.get_config(self.symbol, df)
            enable_pivot = cfg.enable_pivot
            enable_rsi = cfg.enable_rsi
            enable_wdh = cfg.enable_wdh
            wdh_weekly_only = cfg.wdh_weekly_only
            enable_cycle = cfg.enable_cycle
            cycle_halving = cfg.cycle_halving
            cycle_ath = cfg.cycle_ath
            cycle_inventory = cfg.cycle_inventory
            cycle_long_term = cfg.cycle_long_term
            enable_mcap = cfg.enable_mcap_feature
            # 按市值配置L2 Meta-Labeling (覆盖全局设置)
            self.use_meta_labeling = cfg.enable_meta_labeling
            # 美林时钟配置
            enable_merrill = cfg.enable_merrill
            merrill_inflation = cfg.merrill_inflation
            merrill_growth = cfg.merrill_growth
            merrill_capital_flow = cfg.merrill_capital_flow
            merrill_phase = cfg.merrill_phase
            merrill_cross = cfg.merrill_cross

        # 1. 计算全部特征
        if verbose:
            print(f"[{self.symbol}] 计算八卦特征...")
        features = self.feature_engine.compute(df)
        feature_names = list(features.columns)
        feature_names_by_gua = dict(self.feature_engine.feature_names_by_gua)

        # 1b. 经典交易经验特征 (经验常量)
        if verbose:
            print(f"[{self.symbol}] 计算经典交易经验特征 (牛熊线+Elder-ray+三屏)...")
        classic_feats = self.classic_features.compute(df)
        features = pd.concat([features, classic_feats], axis=1)
        feature_names = list(features.columns)
        feature_names_by_gua["classic_exp"] = list(classic_feats.columns)
        if verbose:
            print(f"  经典经验特征: {len(classic_feats.columns)}个")

        # 1c. 斐波那契特征 (数学确定性比例)
        if verbose:
            print(f"[{self.symbol}] 计算斐波那契特征 (回撤+扩展+波动率归一化+时间周期)...")
        fib_feats = self.fib_features.compute(df)
        features = pd.concat([features, fib_feats], axis=1)
        feature_names = list(features.columns)
        feature_names_by_gua["fibonacci"] = list(fib_feats.columns)
        if verbose:
            print(f"  斐波那契特征: {len(fib_feats.columns)}个")

        # 1d. 枢纽点特征 (数学确定性的支撑/阻力位)
        if enable_pivot:
            if verbose:
                print(f"[{self.symbol}] 计算枢纽点特征 (Standard+Fibonacci+Camarilla)...")
            pp_feats = self.pivot_features.compute(df)
            features = pd.concat([features, pp_feats], axis=1)
            feature_names = list(features.columns)
            feature_names_by_gua["pivot_point"] = list(pp_feats.columns)
            if verbose:
                print(f"  枢纽点特征: {len(pp_feats.columns)}个")

        # 1e. RSI情绪压力特征 (自适应超买超卖+买卖压力)
        if enable_rsi:
            if verbose:
                print(f"[{self.symbol}] 计算RSI情绪压力特征 (自适应阈值+背离+买卖压力)...")
            rsi_feats = self.rsi_features.compute(df)
            features = pd.concat([features, rsi_feats], axis=1)
            feature_names = list(features.columns)
            feature_names_by_gua["rsi_sentiment"] = list(rsi_feats.columns)
            if verbose:
                print(f"  RSI情绪特征: {len(rsi_feats.columns)}个")

        # 1f. 周/日/时三屏 + 量变积累特征 (量变引起质变理论)
        if enable_wdh:
            if verbose:
                if wdh_weekly_only:
                    print(f"[{self.symbol}] 计算周线量变积累特征 (仅周线层)...")
                else:
                    print(f"[{self.symbol}] 计算周/日/时三屏+量变积累特征 (量变→质变)...")
            wdh_feats = self.wdh_features.compute(df, weekly_only=wdh_weekly_only)
            features = pd.concat([features, wdh_feats], axis=1)
            feature_names = list(features.columns)
            # 按子类注册 (便于卦象映射器跳过非八卦维度)
            feature_names_by_gua["wdh_weekly_accum"] = [
                c for c in wdh_feats.columns if c.startswith("wa_")
            ]
            if not wdh_weekly_only:
                feature_names_by_gua["wdh_daily_confirm"] = [
                    c for c in wdh_feats.columns if c.startswith("dc_")
                ]
                feature_names_by_gua["wdh_hourly_timing"] = [
                    c for c in wdh_feats.columns if c.startswith("ht_")
                ]
                feature_names_by_gua["wdh_qual_trigger"] = [
                    c for c in wdh_feats.columns if c.startswith("qt_")
                ]
            if verbose:
                label = "周线量变积累" if wdh_weekly_only else "周/日/时+量变质变"
                print(f"  {label}特征: {len(wdh_feats.columns)}个")

        # 1g. 库存周期特征 (4年基钦周期 + 减半周期 + 长期趋势)
        if enable_cycle:
            if verbose:
                print(f"[{self.symbol}] 计算库存周期特征 (基钦周期+减半+牛熊线)...")
            cycle_feats = self.cycle_features.compute(
                df,
                enable_halving=cycle_halving,
                enable_ath=cycle_ath,
                enable_inventory=cycle_inventory,
                enable_long_term=cycle_long_term,
            )
            features = pd.concat([features, cycle_feats], axis=1)
            feature_names = list(features.columns)
            feature_names_by_gua["cycle_halving"] = [
                c for c in cycle_feats.columns if c.startswith("hc_")
            ]
            feature_names_by_gua["cycle_ath"] = [
                c for c in cycle_feats.columns if c.startswith("ath_")
            ]
            feature_names_by_gua["cycle_inventory"] = [
                c for c in cycle_feats.columns if c.startswith("ic_")
            ]
            feature_names_by_gua["cycle_long_term"] = [
                c for c in cycle_feats.columns if c.startswith("lt_")
            ]
            if verbose:
                print(f"  库存周期特征: {len(cycle_feats.columns)}个")

        # 1h. 市值特征 (将市值等级作为特征输入)
        if enable_mcap:
            if verbose:
                print(f"[{self.symbol}] 计算市值特征 (等级+波动率归一化)...")
            mcap_feats = self.mcap_classifier.get_mcap_features(self.symbol, df)
            features = pd.concat([features, mcap_feats], axis=1)
            feature_names = list(features.columns)
            feature_names_by_gua["market_cap"] = list(mcap_feats.columns)
            if verbose:
                print(f"  市值特征: {len(mcap_feats.columns)}个")

        # 1h2. 美林时钟周期特征 (跨资产资金流转)
        if enable_merrill:
            if verbose:
                print(f"[{self.symbol}] 计算美林时钟特征 (BTC.D×库存周期+共振+跨资产动量+流动性)...")
            from .merrill_clock_features import MerrillClockFeatures
            cycle_phase_data = cycle_feats if enable_cycle else None
            merrill_feats = self.merrill_features.compute(
                df,
                ref_df=ref_df,
                enable_btcd=merrill_capital_flow,
                enable_inventory=merrill_growth,
                enable_resonance=merrill_inflation,
                enable_cross_asset_momentum=True,
                enable_liquidity=True,
                enable_phase=merrill_phase,
                enable_cross=merrill_cross,
                cycle_phase=cycle_phase_data,
            )
            features = pd.concat([features, merrill_feats], axis=1)
            feature_names = list(features.columns)
            feature_names_by_gua["merrill_clock"] = list(merrill_feats.columns)
            if verbose:
                print(f"  美林时钟特征: {len(merrill_feats.columns)}个")

        # 1i. 跨资产特征 (如果有参考资产)
        if ref_df is not None and len(ref_df) > 200:
            if verbose:
                print(f"[{self.symbol}] 计算跨资产特征 (ref=BTC)...")
            ca_feats = compute_cross_asset_features(df, ref_df)
            features = pd.concat([features, ca_feats], axis=1)
            feature_names = list(features.columns)
            feature_names_by_gua["cross_asset"] = list(ca_feats.columns)
            if verbose:
                print(f"  跨资产特征: {len(ca_feats.columns)}个")

        if verbose:
            print(f"  特征总数: {len(feature_names)}")

        if verbose:
            for gua, cnt in {**{g: len(f) for g, f in feature_names_by_gua.items()}}.items():
                print(f"    {gua}: {cnt}个特征")

        # 2. 计算三重障碍标签
        if verbose:
            print(f"[{self.symbol}] 计算三重障碍标签...")
        labels = self.labeler.label(df)
        if verbose:
            stats = self.labeler.label_stats(labels)
            print(f"  标签分布: {stats['label_distribution']}")
            print(f"  障碍分布: {stats['barrier_distribution']}")

        # 3. 划分folds
        n_total = len(df)
        folds = self._split_folds(n_total)
        result.n_folds = len(folds)

        if verbose:
            print(f"[{self.symbol}] 共{len(folds)}个fold")
            for i, (ts, te, trs, tre) in enumerate(folds, 1):
                print(f"  Fold {i}: train[{ts}:{te}]={te-ts}根, test[{trs}:{tre}]={tre-trs}根")

        # 4. 逐fold回测
        iterator = tqdm(enumerate(folds, 1), total=len(folds),
                        desc=f"Walk-Forward [{self.symbol}]") if verbose else enumerate(folds, 1)

        for fold_id, (train_start, train_end, test_start, test_end) in iterator:
            fold_result = self._run_single_fold(
                fold_id, df, features, labels,
                train_start, train_end, test_start, test_end,
                feature_names, feature_names_by_gua,
                verbose=verbose,
                ref_df=ref_df,
                cycle_feats=cycle_feats,
            )
            result.folds.append(fold_result)
            result.all_trades.extend(fold_result.trades)

        # 5. 计算汇总指标
        self._compute_summary(result, df)

        return result

    def _split_folds(self, n_total: int) -> List[Tuple[int, int, int, int]]:
        """划分walk-forward folds

        Returns:
            List of (train_start, train_end, test_start, test_end)
        """
        folds = []
        # 采用anchoring walk-forward (锚定扩展训练集)
        # 第一个fold: 前70%训练, 后30%/N测试
        test_size = int(n_total * (1 - self.train_ratio) / self.n_folds)
        train_end = int(n_total * self.train_ratio)

        if train_end < self.min_train_bars:
            train_end = self.min_train_bars
        if test_size < self.min_test_bars:
            test_size = self.min_test_bars

        test_start = train_end
        for i in range(self.n_folds):
            ts = 0
            te = train_end + i * test_size  # 训练集扩展
            trs = train_end + i * test_size
            tre = min(trs + test_size, n_total)

            if tre - trs < self.min_test_bars:
                break
            if te - ts < self.min_train_bars:
                continue

            folds.append((ts, te, trs, tre))

        return folds

    def _run_single_fold(
        self,
        fold_id: int,
        df: pd.DataFrame,
        features: pd.DataFrame,
        labels: pd.DataFrame,
        train_start: int,
        train_end: int,
        test_start: int,
        test_end: int,
        feature_names: List[str],
        feature_names_by_gua: Dict[str, List[str]],
        verbose: bool = False,
        ref_df: Optional[pd.DataFrame] = None,
        cycle_feats: Optional[pd.DataFrame] = None,
    ) -> FoldResult:
        """运行单个fold"""
        fold_result = FoldResult(
            fold_id=fold_id,
            train_start=train_start,
            train_end=train_end,
            test_start=test_start,
            test_end=test_end,
            n_train=train_end - train_start,
            n_test=test_end - test_start,
        )

        # 准备训练数据 (用DataFrame以支持特征选择)
        X_train_df = features.iloc[train_start:train_end].copy()
        y_train = labels.iloc[train_start:train_end]["label"].values

        # 过滤掉NaN
        valid_mask = ~X_train_df.isna().any(axis=1).values
        X_train_df = X_train_df[valid_mask]
        y_train = y_train[valid_mask]

        if len(X_train_df) < 100:
            return fold_result

        # 特征选择 (只用训练集，避免未来函数)
        current_feat_names = list(X_train_df.columns)
        current_feat_by_gua = feature_names_by_gua

        if self.feature_selection:
            selector = FeatureSelector(
                importance_threshold=self.fs_imp_threshold,
                corr_threshold=self.fs_corr_threshold,
            )
            selector.fit(X_train_df, y_train)
            selected = selector.selected_features
            X_train_df = X_train_df[selected]
            current_feat_names = selected
            # 更新feature_names_by_gua (只保留选中的特征)
            current_feat_by_gua = {}
            for gua, feats in feature_names_by_gua.items():
                kept = [f for f in feats if f in selected]
                if kept:
                    current_feat_by_gua[gua] = kept

        X_train = X_train_df.values

        # 训练模型
        engine = DialecticalMLEngine(current_feat_names, current_feat_by_gua)
        engine.train_l1(X_train, y_train)

        # L2 Meta-Labeling训练 (反题: 对L1方向做"是否盈利"二次判断)
        if self.use_meta_labeling:
            if verbose:
                print(f"  [{self.symbol}] 训练L2 Meta-Labeling模型 (V2互补特征)...")
            # V2版本: 需要传入ref_df和cycle_phase用于跨资产验证和周期特征
            l2_result = engine.train_l2(
                X_train, y_train, 
                df=df.iloc[train_start:train_end],
                ref_df=ref_df.iloc[train_start:train_end] if ref_df is not None else None,
                cycle_phase=cycle_feats.iloc[train_start:train_end] if cycle_feats is not None else None,
            )
            if verbose and l2_result.get("ok", True):
                print(f"  L2训练完成: long_acc={l2_result.get('long_train_accuracy', 'N/A'):.3f}, "
                      f"short_acc={l2_result.get('short_train_accuracy', 'N/A'):.3f}")

        # 准备测试数据
        X_test_df = features.iloc[test_start:test_end][current_feat_names].copy()
        X_test = X_test_df.fillna(0).values

        # 预测 (V2版本: 需要传入ref_df和cycle_phase)
        preds = engine.predict(
            X_test, with_gua=True, 
            df=df.iloc[test_start:test_end],
            ref_df=ref_df.iloc[test_start:test_end] if ref_df is not None else None,
            cycle_phase=cycle_feats.iloc[test_start:test_end] if cycle_feats is not None else None,
        )

        # 市场模式分类 (如果启用)
        regime_names = None
        if self.use_regime_switching:
            from .market_regime import MarketRegimeClassifier
            regime_cls = MarketRegimeClassifier(
                feature_names_by_gua=current_feat_by_gua,
                lookback_bars=20,
            )
            regime_cls.fit(X_train, current_feat_names)
            regime_names = regime_cls.predict_regime_names(X_test, current_feat_names)

        # 模拟交易
        trades = self._simulate_trades(df, preds, test_start, test_end, regime_names)

        fold_result.trades = trades
        fold_result.predictions = preds

        return fold_result

    def _simulate_trades(
        self,
        df: pd.DataFrame,
        predictions: List[Dict],
        test_start: int,
        test_end: int,
        regime_names: Optional[List[str]] = None,
    ) -> List[Trade]:
        """
        模拟交易: 当action=OPEN时入场，触碰tp/sl或到期平仓

        简化模拟:
          - 每根K线收盘检查信号，下一根K线开盘入场
          - 入场后，每根K线检查是否触障
          - 触障则在障碍价平仓
          - 到期则在最后一根K线收盘平仓
          - 如果启用市态切换，根据市态调整置信度阈值和止盈止损
        """
        from .market_regime import DEFAULT_REGIME_PARAMS
        trades = []
        position = None  # 当前持仓

        close = df["close"].values
        high = df["high"].values
        low = df["low"].values
        open_prices = df["open"].values

        for i, pred in enumerate(predictions):
            bar_idx = test_start + i

            # 如果有持仓，检查是否出场
            if position is not None:
                entry_price = position["entry_price"]
                direction = position["direction"]
                tp_price = position["tp_price"]
                sl_price = position["sl_price"]
                hold_bars = i - position["entry_offset"]
                max_hold = position.get("max_hold_bars", self.max_hold_bars)

                # 检查止盈止损
                if direction == 1:  # 多单
                    if high[bar_idx] >= tp_price:
                        exit_price = tp_price
                        exit_reason = "tp"
                    elif low[bar_idx] <= sl_price:
                        exit_price = sl_price
                        exit_reason = "sl"
                    elif hold_bars >= max_hold:
                        exit_price = close[bar_idx]
                        exit_reason = "time"
                    else:
                        exit_price = None
                        exit_reason = None
                else:  # 空单
                    if low[bar_idx] <= tp_price:
                        exit_price = tp_price
                        exit_reason = "tp"
                    elif high[bar_idx] >= sl_price:
                        exit_price = sl_price
                        exit_reason = "sl"
                    elif hold_bars >= self.max_hold_bars:
                        exit_price = close[bar_idx]
                        exit_reason = "time"
                    else:
                        exit_price = None
                        exit_reason = None

                if exit_price is not None:
                    # 计算手续费 + 滑点
                    fee = entry_price * self.fee_rate + exit_price * self.fee_rate
                    slippage = abs(exit_price - entry_price) * self.slippage_rate
                    pnl_pct = ((exit_price - entry_price) * direction - fee - slippage) / entry_price

                    # 仓位系数只记录，不直接影响PnL
                    # 通过调整置信度阈值实现市态自适应开仓
                    pf = position.get("position_factor", 1.0)

                    trade = Trade(
                        entry_bar=position["entry_bar"],
                        exit_bar=bar_idx,
                        direction=direction,
                        entry_price=entry_price,
                        exit_price=exit_price,
                        pnl_pct=pnl_pct * 100,  # 百分比
                        hold_bars=hold_bars,
                        exit_reason=exit_reason,
                        confidence=position["confidence"],
                        hexagram_name=position.get("hexagram_name", ""),
                        upper_gua=position.get("upper_gua", ""),
                        lower_gua=position.get("lower_gua", ""),
                        position_factor=pf,
                    )
                    trades.append(trade)
                    position = None

            # 如果无持仓，检查是否开仓
            if position is None and pred["action"] == "OPEN" and pred["direction"] != 0:
                if bar_idx + 1 >= len(df):
                    break

                direction = pred["direction"]
                confidence = pred["final_confidence"]

                # 市态切换: 根据市态调整参数
                effective_conf_thresh = self.conf_threshold
                effective_tp_atr = self.tp_atr
                effective_sl_atr = self.sl_atr
                effective_max_hold = self.max_hold_bars
                allow_trade = True
                regime_name = "DEFAULT"

                # 仓位系数 (默认1.0)
                # position_factor > 1: 高信心市态(FOMO/强趋势), 更容易开仓
                # position_factor < 1: 低信心市态(横盘/反转), 更难开仓
                position_factor = 1.0

                if regime_names is not None and i < len(regime_names):
                    regime_name = regime_names[i]
                    rp = DEFAULT_REGIME_PARAMS.get(regime_name)
                    if rp is not None:
                        # 方向过滤
                        if direction == 1 and not rp.allow_long:
                            allow_trade = False
                        if direction == -1 and not rp.allow_short:
                            allow_trade = False

                        # 置信度阈值 (基础值)
                        if direction == 1:
                            effective_conf_thresh = rp.long_conf_threshold
                        else:
                            effective_conf_thresh = rp.short_conf_threshold

                        # 止盈止损
                        effective_tp_atr = rp.tp_atr
                        effective_sl_atr = rp.sl_atr
                        effective_max_hold = rp.max_hold_bars

                        # 仓位系数 (市态自适应)
                        position_factor = rp.position_factor

                        # 用仓位系数调整置信度阈值:
                        # position_factor > 1: 降低阈值, 更容易开仓
                        # position_factor < 1: 提高阈值, 更难开仓
                        # 阈值调整幅度 = 0.20 * (1 - position_factor)
                        # 例如: FOMO(position_factor=1.5) → 阈值降低0.10
                        #       横盘(position_factor=0.5) → 阈值提高0.10
                        conf_adjust = 0.20 * (1 - position_factor)
                        effective_conf_thresh += conf_adjust
                        effective_conf_thresh = max(0.20, min(0.70, effective_conf_thresh))

                # 置信度过滤 (用市态调整后的阈值)
                if confidence < effective_conf_thresh:
                    continue

                if not allow_trade:
                    continue

                entry_price = open_prices[bar_idx + 1]  # 下一根K线开盘入场

                # 用ATR计算止盈止损
                # 简化: 用入场价的固定百分比
                atr_mult_tp = effective_tp_atr
                atr_mult_sl = effective_sl_atr
                # 用最近的ATR近似
                atr_est = entry_price * 0.015  # 假设1.5% ATR
                tp_dist = atr_est * atr_mult_tp
                sl_dist = atr_est * atr_mult_sl

                if direction == 1:
                    tp_price = entry_price + tp_dist
                    sl_price = entry_price - sl_dist
                else:
                    tp_price = entry_price - tp_dist
                    sl_price = entry_price + sl_dist

                hex_name = pred.get("hexagram", {}).get("hexagram_name", "")
                upper_name = pred.get("hexagram", {}).get("upper_gua", {}).get("name", "")
                lower_name = pred.get("hexagram", {}).get("lower_gua", {}).get("name", "")

                position = {
                    "entry_bar": bar_idx,
                    "entry_offset": i,
                    "entry_price": entry_price,
                    "direction": direction,
                    "tp_price": tp_price,
                    "sl_price": sl_price,
                    "confidence": confidence,
                    "hexagram_name": hex_name,
                    "upper_gua": upper_name,
                    "lower_gua": lower_name,
                    "regime_name": regime_name,
                    "max_hold_bars": effective_max_hold,
                    "position_factor": position_factor,
                }

        # 如果最后还有持仓，强制平仓
        if position is not None:
            bar_idx = test_end - 1
            exit_price = close[bar_idx]
            direction = position["direction"]
            hold_bars = (test_end - 1) - position["entry_bar"]
            fee = position["entry_price"] * self.fee_rate + exit_price * self.fee_rate
            slippage = abs(exit_price - position["entry_price"]) * self.slippage_rate
            pnl_pct = ((exit_price - position["entry_price"]) * direction - fee - slippage) / position["entry_price"]

            # 仓位系数只记录
            pf = position.get("position_factor", 1.0)

            trade = Trade(
                entry_bar=position["entry_bar"],
                exit_bar=bar_idx,
                direction=direction,
                entry_price=position["entry_price"],
                exit_price=exit_price,
                pnl_pct=pnl_pct * 100,
                position_factor=pf,
                hold_bars=hold_bars,
                exit_reason="end",
                confidence=position["confidence"],
                hexagram_name=position.get("hexagram_name", ""),
                upper_gua=position.get("upper_gua", ""),
                lower_gua=position.get("lower_gua", ""),
            )
            trades.append(trade)

        return trades

    def _compute_summary(self, result: BacktestResult, df: pd.DataFrame):
        """计算汇总指标"""
        trades = result.all_trades
        result.total_trades = len(trades)

        if not trades:
            return

        # 基础指标
        pnls = [t.pnl_pct for t in trades]
        result.overall_win_rate = sum(1 for p in pnls if p > 0) / len(pnls)
        result.total_return = sum(pnls)
        result.avg_return_per_trade = result.total_return / len(pnls)

        # 最大回撤 (假设每次投入相同仓位)
        cumulative = np.cumsum(pnls)
        peak = np.maximum.accumulate(cumulative)
        drawdown = peak - cumulative
        result.max_drawdown = float(np.max(drawdown))

        # 盈亏比
        wins = sum(p for p in pnls if p > 0)
        losses = abs(sum(p for p in pnls if p < 0))
        result.profit_factor = wins / losses if losses > 0 else float('inf')

        # 夏普比率 (假设无风险利率=0)
        if len(pnls) > 1 and np.std(pnls) > 0:
            result.sharpe_ratio = np.mean(pnls) / np.std(pnls) * np.sqrt(252)  # 年化近似
        else:
            result.sharpe_ratio = 0.0

        # 平均持仓时间
        result.avg_hold_bars = np.mean([t.hold_bars for t in trades])

        # 按方向统计
        long_trades = [t for t in trades if t.direction == 1]
        short_trades = [t for t in trades if t.direction == -1]

        result.long_stats = self._stats_for_trades(long_trades)
        result.short_stats = self._stats_for_trades(short_trades)

        # 卦象统计 (Top 10)
        gua_counts = {}
        gua_pnl = {}
        upper_counts = {}
        lower_counts = {}
        for t in trades:
            name = t.hexagram_name or "unknown"
            gua_counts[name] = gua_counts.get(name, 0) + 1
            gua_pnl[name] = gua_pnl.get(name, 0) + t.pnl_pct
            if t.upper_gua:
                upper_counts[t.upper_gua] = upper_counts.get(t.upper_gua, 0) + 1
            if t.lower_gua:
                lower_counts[t.lower_gua] = lower_counts.get(t.lower_gua, 0) + 1

        top_guas = sorted(gua_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        for gua, cnt in top_guas:
            result.hexagram_stats[gua] = {
                "count": cnt,
                "total_pnl": round(gua_pnl[gua], 2),
                "avg_pnl": round(gua_pnl[gua] / cnt, 2),
                "win_rate": round(sum(1 for t in trades if t.hexagram_name == gua and t.pnl_pct > 0) / cnt * 100, 1),
            }

        # 上卦/下卦分布
        result.upper_gua_stats = dict(sorted(upper_counts.items(), key=lambda x: x[1], reverse=True))
        result.lower_gua_stats = dict(sorted(lower_counts.items(), key=lambda x: x[1], reverse=True))

    def _stats_for_trades(self, trades: List[Trade]) -> Dict:
        """为一组交易计算统计"""
        if not trades:
            return {"count": 0, "win_rate": 0, "total_pnl": 0, "avg_pnl": 0}
        pnls = [t.pnl_pct for t in trades]
        return {
            "count": len(trades),
            "win_rate": round(sum(1 for p in pnls if p > 0) / len(pnls) * 100, 1),
            "total_pnl": round(sum(pnls), 2),
            "avg_pnl": round(sum(pnls) / len(pnls), 2),
        }


# ============================================================
# 报告生成
# ============================================================

def generate_report(result: BacktestResult, output_path: Optional[str] = None) -> str:
    """生成可读的回测报告"""
    lines = []
    lines.append("=" * 70)
    lines.append(f"  BCRM 2.0 Phase 0 回测报告 — {result.symbol}")
    lines.append("=" * 70)
    lines.append("")

    # 汇总指标
    lines.append("【汇总指标】")
    lines.append(f"  总交易次数:     {result.total_trades}")
    lines.append(f"  胜率:           {result.overall_win_rate * 100:.1f}%")
    lines.append(f"  总收益率:       {result.total_return:.2f}%")
    lines.append(f"  单笔平均收益:   {result.avg_return_per_trade:.3f}%")
    lines.append(f"  最大回撤:       {result.max_drawdown:.2f}%")
    lines.append(f"  盈亏比:         {result.profit_factor:.2f}")
    lines.append(f"  夏普比率:       {result.sharpe_ratio:.2f}")
    lines.append(f"  平均持仓bar数:  {result.avg_hold_bars:.1f}")
    lines.append("")

    # 分fold结果
    lines.append("【分Fold结果】")
    lines.append(f"  {'Fold':<6} {'交易数':<8} {'胜率':<8} {'总收益':<10} {'最大回撤':<10} {'盈亏比':<8}")
    lines.append(f"  {'-'*6} {'-'*8} {'-'*8} {'-'*10} {'-'*10} {'-'*8}")
    for f in result.folds:
        lines.append(f"  {f.fold_id:<6} {f.n_trades:<8} {f.win_rate*100:<7.1f}% "
                    f"{f.total_return:<9.2f}% {f.max_drawdown:<9.2f}% {f.profit_factor:<7.2f}")
    lines.append("")

    # 多空统计
    lines.append("【多空统计】")
    lines.append(f"  多单: {result.long_stats.get('count', 0)}笔, "
                f"胜率{result.long_stats.get('win_rate', 0)}%, "
                f"总收益{result.long_stats.get('total_pnl', 0)}%")
    lines.append(f"  空单: {result.short_stats.get('count', 0)}笔, "
                f"胜率{result.short_stats.get('win_rate', 0)}%, "
                f"总收益{result.short_stats.get('total_pnl', 0)}%")
    lines.append("")

    # 卦象统计
    if result.hexagram_stats:
        lines.append("【卦象统计 Top 10】")
        lines.append(f"  {'卦象':<15} {'次数':<6} {'胜率':<8} {'总收益':<10} {'平均':<8}")
        lines.append(f"  {'-'*15} {'-'*6} {'-'*8} {'-'*10} {'-'*8}")
        for gua, stats in result.hexagram_stats.items():
            lines.append(f"  {gua:<15} {stats['count']:<6} {stats['win_rate']:<7.1f}% "
                        f"{stats['total_pnl']:<9.2f}% {stats['avg_pnl']:<7.2f}%")
        lines.append("")

    # 八卦维度分布
    if result.upper_gua_stats:
        lines.append("【上卦分布 (主导力量)】")
        for gua, cnt in result.upper_gua_stats.items():
            pct = cnt / result.total_trades * 100
            bar = "█" * int(pct / 5)
            lines.append(f"  {gua:<4}: {cnt:<4} ({pct:<5.1f}%) {bar}")
        lines.append("")

    if result.lower_gua_stats:
        lines.append("【下卦分布 (基础力量)】")
        for gua, cnt in result.lower_gua_stats.items():
            pct = cnt / result.total_trades * 100
            bar = "█" * int(pct / 5)
            lines.append(f"  {gua:<4}: {cnt:<4} ({pct:<5.1f}%) {bar}")
        lines.append("")

    report = "\n".join(lines)

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report)

    return report
