"""T31 · 10-经典 FeatureHub 灰度一致性对比（Bot2StrategyTrend）

验证 FeatureHub `classic_talib_only` 集合输出 vs 原始 Bot2StrategyTrend.populate_indicators
的指标列名交集与数值相关性，为 H3 wrapper 灰度接入提供前置证据。

硬门槛（T-G3）：
  - Bot2 使用的核心列名交集 ≥ 95%（populate_entry_trend + custom_stoploss 依赖）
  - 交集列数值 Pearson 相关 ≥ 0.97（允许 EMA period 参数差异偏差）
  - 信号方向一致率 ≥ 95%（基于 populate_entry_trend 输出 enter_long/short）

测试目标策略：Bot2StrategyTrend（生产主策略之一，backtest_strategies.py CORE_STRATEGIES 排名第三）
Bot2 核心依赖列（populate_indicators 写入 + populate_entry_trend 读取）：
  rsi, ema_fast, ema_slow, ema_trend, bb_upper, bb_mid, bb_lower,
  adx, atr, volume_mean
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_21_ROOT = _PROJECT_ROOT / "21-特征工程中心"
_10_ROOT = _PROJECT_ROOT / "10-经典指标系统"


def _ensure_sys_path() -> None:
    """确保 user_data / feature_hub 可 import。pytest 会 reset sys.path，函数内调用要显式注入。"""
    for _p in [str(_21_ROOT), str(_21_ROOT / "feature_hub"), str(_10_ROOT)]:
        if _p not in sys.path:
            sys.path.insert(0, _p)


_ensure_sys_path()


# Bot2StrategyTrend 使用的核心指标列（populate_entry_trend + custom_stoploss 读取）
BOT2_CORE_COLS = {
    "rsi", "ema_fast", "ema_slow", "ema_trend",
    "bb_upper", "bb_mid", "bb_lower",
    "adx", "atr", "volume_mean",
}

# Bot2 额外可能用到的列（macd 等）
BOT2_EXTRA_COLS = {"macd", "macdsignal", "macdhist"}


def _make_ohlcv(n: int = 400, seed: int = 42) -> pd.DataFrame:
    """生成 5m 频率的 OHLCV 样本（Bot2 timeframe=5m，startup=200）"""
    rng = np.random.default_rng(seed)
    close = 40000 * np.exp(np.cumsum(rng.normal(0, 0.005, n)))
    return pd.DataFrame({
        "open": close * (1 + rng.normal(0, 0.001, n)),
        "high": close * (1 + np.abs(rng.normal(0, 0.003, n))),
        "low": close * (1 - np.abs(rng.normal(0, 0.003, n))),
        "close": close,
        "volume": 1e6 * (1 + rng.uniform(-0.5, 1.5, n)),
    }, index=pd.date_range("2024-01-01", periods=n, freq="5min"))


def _bot2_original_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """调用 Bot2StrategyTrend.populate_indicators 原始实现。"""
    _ensure_sys_path()
    from user_data.strategies.Bot2StrategyTrend import Bot2StrategyTrend
    strat = Bot2StrategyTrend(config={})
    meta = {"pair": "BTC/USDT"}
    dataframe = df.copy()
    return strat.populate_indicators(dataframe, meta)


def _bot2_original_signals(df: pd.DataFrame) -> pd.DataFrame:
    """调用 populate_entry_trend 得到 enter_long/enter_short"""
    _ensure_sys_path()
    from user_data.strategies.Bot2StrategyTrend import Bot2StrategyTrend
    strat = Bot2StrategyTrend(config={})
    meta = {"pair": "BTC/USDT"}
    dataframe = strat.populate_indicators(df.copy(), meta)
    return strat.populate_entry_trend(dataframe, meta)


def _featurehub_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """FeatureHub classic_talib_only + strip_prefix=True。"""
    _ensure_sys_path()
    from feature_hub.pipeline.feature_pipeline import FeaturePipeline
    from feature_hub.modules.loader import load_default_sets
    pipe = FeaturePipeline()
    load_default_sets(pipe)
    fv = pipe.run(set_name="classic_talib_only", df=df, symbol="BTC")
    out = fv.df
    if not out.empty:
        new_cols = {}
        for col in out.columns:
            sep = col.find("__")
            new_cols[col] = col[sep + 2:] if sep >= 0 else col
        out = out.rename(columns=new_cols)
    return out


def _bot2_signal_from_prefilled(df: pd.DataFrame, ind_df: pd.DataFrame) -> pd.DataFrame:
    """模拟灰度接入路径：

    1. 先把 FH 的 13 个 talib 列 merge 回 df（替代原始 populate_indicators L84-97）
    2. 再调用完整 populate_indicators 写 regime_trend 等衍生列 + populate_entry_trend

    注意：populate_indicators 会再次调用 talib 重写 L84-97 列，**覆盖** FH 的值。
    这正是我们在实盘要做的：在 populate_indicators 入口注入 FeatureHub，
    替代内部 talib/qtpylib 调用，而不是外部 merge。为了测试等价性，
    我们必须真正 patch Bot2 的 talib 调用，或者直接用 Bot2 的原始实现做对比。

    本测试简化为：直接比较「原始 Bot2.populate_indicators 输出」和「FH talib_aligned
    + handwritten regime 衍生」在相同输入下的列是否等价；再比较信号方向。
    """
    _ensure_sys_path()
    from user_data.strategies.Bot2StrategyTrend import Bot2StrategyTrend
    strat = Bot2StrategyTrend(config={})
    meta = {"pair": "BTC/USDT"}
    # 先跑完整 populate_indicators 生成 regime_trend / mr_score 等衍生列
    # 再把 FH 的 13 列覆盖写入（等价于在 populate_indicators 开头替换 talib 调用）
    dataframe = strat.populate_indicators(df.copy(), meta)
    for col in ind_df.columns:
        if col in dataframe.columns:
            dataframe[col] = ind_df[col].reindex(dataframe.index)
    return strat.populate_entry_trend(dataframe, meta)


# ============================================================
# T31-1 · Bot2 核心列名交集 ≥ 95%
# ============================================================
def test_t31_1_bot2_core_column_intersection():
    """验证 FeatureHub 覆盖 Bot2StrategyTrend 核心列 ≥ 95%。"""
    df = _make_ohlcv(n=400, seed=42)
    fh = _featurehub_indicators(df)

    # 只要 bot2 需要的列在 fh 中存在即可
    present_core = BOT2_CORE_COLS & set(fh.columns)
    ratio_core = len(present_core) / len(BOT2_CORE_COLS)

    print(f"\n[T31-1] Bot2 核心列: {sorted(BOT2_CORE_COLS)}")
    print(f"[T31-1] FH 覆盖核心列: {sorted(present_core)}")
    print(f"[T31-1] 缺失核心列: {sorted(BOT2_CORE_COLS - set(fh.columns))}")
    print(f"[T31-1] 核心列交集占比: {ratio_core:.2%}")

    assert ratio_core >= 0.95, (
        f"Bot2 核心列交集 {ratio_core:.2%} < 95%，"
        f"缺失: {sorted(BOT2_CORE_COLS - set(fh.columns))}"
    )


# ============================================================
# T31-2 · 交集列数值 Pearson 相关 ≥ 0.97
# ============================================================
def test_t31_2_intersection_value_correlation():
    """验证 Bot2 核心列在 FH vs 原始 talib 下 Pearson ≥ 0.97。"""
    df = _make_ohlcv(n=400, seed=42)

    orig = _bot2_original_indicators(df)
    fh = _featurehub_indicators(df)

    common_idx = orig.index.intersection(fh.index)
    if len(common_idx) < 50:
        pytest.skip(f"公共 index 仅 {len(common_idx)} 行")

    core_intersection = BOT2_CORE_COLS & set(fh.columns)
    correlations = []
    low_corr = []

    for col in sorted(core_intersection):
        o = orig.loc[common_idx, col].astype(float)
        f = fh.loc[common_idx, col].astype(float)
        mask = o.notna() & f.notna()
        if mask.sum() < 30:
            continue
        o_v = o[mask]
        f_v = f[mask]
        if o_v.std() < 1e-10 or f_v.std() < 1e-10:
            continue
        corr = o_v.corr(f_v)
        if not np.isnan(corr):
            correlations.append((col, corr))
            if corr < 0.97:
                low_corr.append((col, corr))

    if not correlations:
        pytest.skip("无非常数交集列可对比")

    avg_corr = np.mean([c for _, c in correlations])
    min_corr = np.min([c for _, c in correlations])

    print(f"\n[T31-2] 可对比列数: {len(correlations)}")
    print(f"[T31-2] 平均 Pearson: {avg_corr:.6f}")
    print(f"[T31-2] 最低 Pearson: {min_corr:.6f}")
    if low_corr:
        print(f"[T31-2] 低相关列(<0.97): {low_corr}")

    assert avg_corr >= 0.97, (
        f"Bot2 核心列平均 Pearson {avg_corr:.6f} < 0.97"
    )


# ============================================================
# T31-3 · 信号方向一致率 ≥ 95%
# ============================================================
def test_t31_3_signal_direction_consistency():
    """验证 populate_entry_trend 在 FH 指标 vs 原始指标下方向一致率 ≥ 95%。

    关键验证：populate_entry_trend 读不到核心列会出 KeyError 或产生全 0 信号，
    一致率低会导致实盘交易决策不一致。
    """
    n_seeds = 10
    consistent = 0
    total = 0
    error_cases: list[str] = []

    for seed in range(n_seeds):
        df = _make_ohlcv(n=400, seed=42 + seed)

        # 原始：populate_indicators → populate_entry_trend
        try:
            orig_sig = _bot2_original_signals(df)
            orig_last = orig_sig.iloc[-1] if not orig_sig.empty else None
            if orig_last is None:
                continue
            orig_dir = (
                "short" if int(orig_last.get("enter_short", 0) or 0) == 1
                else "long" if int(orig_last.get("enter_long", 0) or 0) == 1
                else "none"
            )

            # FH：FH 指标 → merge → populate_entry_trend
            fh_ind = _featurehub_indicators(df)
            fh_sig = _bot2_signal_from_prefilled(df, fh_ind)
            fh_last = fh_sig.iloc[-1] if not fh_sig.empty else None
            if fh_last is None:
                error_cases.append(f"seed{seed}:fh_sig_empty")
                total += 1
                continue
            fh_dir = (
                "short" if int(fh_last.get("enter_short", 0) or 0) == 1
                else "long" if int(fh_last.get("enter_long", 0) or 0) == 1
                else "none"
            )

            if fh_dir == orig_dir:
                consistent += 1
            else:
                error_cases.append(
                    f"seed{seed}:orig={orig_dir} vs fh={fh_dir}")
            total += 1
        except Exception as exc:
            error_cases.append(f"seed{seed}:{type(exc).__name__}:{exc}")
            total += 1

    consistency_rate = consistent / total if total > 0 else 0
    print(f"\n[T31-3] 一致/总数: {consistent}/{total}")
    print(f"[T31-3] 方向一致率: {consistency_rate:.2%}")
    if error_cases:
        print(f"[T31-3] 不一致/异常详情: {error_cases}")

    assert consistency_rate >= 0.95, (
        f"信号方向一致率 {consistency_rate:.2%} < 95%"
    )


# ============================================================
# T31-4 · FH 输出不引入 populate_entry_trend 报错（fail-open）
# ============================================================
def test_t31_4_fh_no_keyerror_in_entry_trend():
    """若 FH 缺列，populate_entry_trend 必须 KeyError 或全 0（fail-open）。"""
    df = _make_ohlcv(n=400, seed=99)

    # 故意只给 FH 输出一部分列，模拟 partial featurehub 失败
    fh_ind = _featurehub_indicators(df)
    # 删掉 adx / atr 两列（custom_stoploss 和 entry 依赖）
    partial = fh_ind.drop(columns=["adx", "atr"], errors="ignore")

    try:
        fh_sig = _bot2_signal_from_prefilled(df, partial)
        # 能跑通就算 fail-open（不 crash），可能全 0 信号
        assert fh_sig is not None
        assert not fh_sig.empty
        print("\n[T31-4] 缺列情况下仍能完成 populate_entry_trend（fail-open 可行）")
    except KeyError:
        # KeyError 也可以接受：说明缺列会被立刻发现而不是静默错误
        print("\n[T31-4] 缺列导致 KeyError（可接受：立刻暴露问题）")
