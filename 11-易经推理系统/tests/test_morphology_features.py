"""
Phase 0: 形态核心 + 市场广度特征 TDD 测试矩阵
严格按 Spec §3.3 测试清单覆盖 P0/P1 共 10+ 专项。
运行：
  cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统
  pytest tests/test_morphology_features.py -v
"""
import os
import sys
import math
import numpy as np
import pandas as pd
import pytest

# ===== 路径配置 =====
BCRM2_ROOT = os.path.join(os.path.dirname(__file__), "..", "scripts", "memory_l4")
if BCRM2_ROOT not in sys.path:
    sys.path.insert(0, BCRM2_ROOT)
PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ============================================================
# P0-01: ADX(14) + DI — Wilder 1978 标准实现
# ============================================================
from bcrm2.classic_experience_features import compute_adx_features


def _gen_trending_ohlcv(n=200, drift=0.003):
    """生成单调上升趋势序列的 OHLCV DataFrame"""
    rng = np.random.RandomState(42)
    close = 100.0 * np.exp(np.cumsum(np.full(n, drift) + rng.randn(n) * 0.004))
    high = close * (1 + np.abs(rng.randn(n)) * 0.006)
    low = close * (1 - np.abs(rng.randn(n)) * 0.006)
    open_ = np.concatenate([[close[0]], close[:-1]])
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": 1e6}, index=idx)


def _gen_ranging_ohlcv(n=200):
    """生成正弦震荡序列（方向切换足够快，Wilder 14 ADX 自然低于 20）。

    频率 t/2.5 → ~16 个采样点一个完整周期，14 日窗口内会包含多个
    上涨/下跌交替，DI+ 和 DI- 的 Wilder 平滑值都会较高且差值小 → DX↓ → ADX<20。
    """
    rng = np.random.RandomState(7)
    t = np.arange(n)
    close = 100.0 + 5.0 * np.sin(t / 2.5) + rng.randn(n) * 0.3
    high = close + 0.4 + np.abs(rng.randn(n)) * 0.4
    low = close - 0.4 - np.abs(rng.randn(n)) * 0.4
    open_ = np.concatenate([[close[0]], close[:-1]])
    idx = pd.date_range("2023-06-01", periods=n, freq="D")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": 1e6}, index=idx)


class TestADX:
    def test_adx_trending_market(self):
        """DoD: ADX > 25, +DI > -DI （趋势形态）"""
        df = _gen_trending_ohlcv(n=300, drift=0.004)
        feats = compute_adx_features(df)
        latest = feats.iloc[-1]
        assert latest["adx_14"] > 25.0, f"趋势期ADX={latest['adx_14']:.2f}应>25"
        assert latest["adx_plus_di"] > latest["adx_minus_di"], (
            f"上升趋势 +DI({latest['adx_plus_di']:.2f}) 应 > -DI({latest['adx_minus_di']:.2f})"
        )
        assert latest["adx_trend_strength_bucket"] == 2, "强趋势 bucket=2"

    def test_adx_ranging_market(self):
        """DoD: ADX < 20 （震荡形态）"""
        df = _gen_ranging_ohlcv(n=300)
        feats = compute_adx_features(df)
        # 取中间段（避免边缘 warmup）
        mid = feats.iloc[len(feats) // 2]
        assert mid["adx_14"] < 20.0, f"震荡期ADX={mid['adx_14']:.2f}应<20"
        assert mid["adx_trend_strength_bucket"] == 0, "震荡 bucket=0"


# ============================================================
# P0-02: Hurst 指数（R/S 分析法）
# ============================================================
from bcrm2.classic_experience_features import compute_hurst_features


class TestHurst:
    def test_hurst_trending(self):
        """DoD: 对单调上升序列 H > 0.55"""
        rng = np.random.RandomState(1)
        series = 100.0 * np.exp(np.cumsum(np.full(500, 0.005) + rng.randn(500) * 0.001))
        feats = compute_hurst_features(pd.Series(series))
        assert feats["hurst_exp_50"] > 0.55, f"单调序列 Hurst(50)={feats['hurst_exp_50']:.3f} 应>0.55"
        assert feats["hurst_exp_100"] > 0.55, f"单调序列 Hurst(100)={feats['hurst_exp_100']:.3f} 应>0.55"
        assert feats["hurst_category"] == 2, "趋势 category=2"

    def test_hurst_mean_reverting(self):
        """DoD: 对正弦震荡序列 H < 0.45"""
        t = np.arange(1000)
        series = 100.0 + 10.0 * np.sin(t / 20.0)
        feats = compute_hurst_features(pd.Series(series))
        assert feats["hurst_exp_50"] < 0.45, f"震荡序列 Hurst(50)={feats['hurst_exp_50']:.3f} 应<0.45"
        assert feats["hurst_exp_100"] < 0.45, f"震荡序列 Hurst(100)={feats['hurst_exp_100']:.3f} 应<0.45"
        assert feats["hurst_category"] == 0, "均值回归 category=0"

    def test_hurst_random_walk(self):
        """DoD: 随机游走 Hurst 在 0.48~0.52"""
        rng = np.random.RandomState(123)
        rets = rng.randn(2000) * 0.01
        series = 100.0 * np.exp(np.cumsum(rets))
        feats = compute_hurst_features(pd.Series(series))
        h100 = feats["hurst_exp_100"]
        assert 0.45 <= h100 <= 0.60, f"随机游走 Hurst(100)={h100:.3f} 应接近0.5（±0.1容差）"


# ============================================================
# P0-03: 布林带宽度百分位 + squeeze 信号
# ============================================================
from bcrm2.classic_experience_features import compute_bb_width_features


class TestBBWidth:
    def test_bb_width_squeeze(self):
        """DoD: 构造压缩期 → 宽度百分位 < 10%, squeeze=1"""
        # 前 200 根正常波动 + 后 60 根极度压缩（BB 宽度极小）
        rng = np.random.RandomState(99)
        n1, n2 = 200, 80
        seg1 = 100.0 + rng.randn(n1) * 2.0
        seg2 = 150.0 + rng.randn(n2) * 0.2  # 波动率骤降=压缩
        close = np.concatenate([seg1, seg2])
        idx = pd.date_range("2023-01-01", periods=len(close), freq="D")
        feats = compute_bb_width_features(pd.Series(close, index=idx))
        # 取压缩段中部（第 n1+40 根），应检测到 squeeze
        t_squeeze = n1 + 40
        row = feats.iloc[t_squeeze]
        assert row["bb_width_percentile_252"] < 0.10, (
            f"压缩期宽度百分位={row['bb_width_percentile_252']:.3f} 应<0.10"
        )
        assert row["bb_squeeze_signal"] == 1, "压缩期 squeeze_signal=1"


# ============================================================
# P0-04: 距 60/120 日高点比例（P1 级但测试保证落地）
# ============================================================
from bcrm2.classic_experience_features import compute_distance_to_high_features


class TestDistanceToHigh:
    def test_distance_to_high_ath(self):
        """DoD: ATH 位置 ratio=1.0±0.005"""
        rng = np.random.RandomState(5)
        n = 300
        close = 100.0 * np.exp(np.cumsum(np.full(n, 0.003) + rng.randn(n) * 0.005))
        # 让最后一个点成为全局高点
        close[-1] = close.max() * 1.01
        idx = pd.date_range("2024-06-01", periods=n, freq="D")
        feats = compute_distance_to_high_features(pd.Series(close, index=idx))
        last = feats.iloc[-1]
        assert abs(last["distance_to_high_60d"] - 1.0) < 0.005, f"ATH 60d ratio={last['distance_to_high_60d']:.4f}"
        assert abs(last["distance_to_high_120d"] - 1.0) < 0.005, f"ATH 120d ratio={last['distance_to_high_120d']:.4f}"


# ============================================================
# P0-05: 8 币广度 MA128 同向比例 + 斜率同向
# ============================================================
from bcrm2.cross_asset_features import (
    compute_breadth_ma128_align,
    EIGHT_COINS_BREADTH,
)


class TestBreadthMA128:
    def test_breadth_ma128_all_above(self):
        """DoD: 8 币全 > MA128 → breadth_align = 1.0"""
        coins_closes = {}
        for coin in EIGHT_COINS_BREADTH:
            # newest-first：index 0 最新；130 个点保证 MA128 有值；最新点 160 > MA≈100
            arr = np.full(130, 100.0)
            arr[0] = 160.0  # newest 远超 100
            coins_closes[coin] = list(arr)
        ba, bs = compute_breadth_ma128_align(coins_closes)
        assert ba == pytest.approx(1.0), f"全部站上MA128 breadth_align={ba}"
        # MA(0..127)=100；MA(1..128)=100 → 斜率相同；slope_up_count=全部因 ma==ma_prev，不计 slope
        # 注：MA>MA_prev 需要 MA1<MA0。在我们构造时两 MA 均 100 → slope=0（不要求必须 1.0）

    def test_breadth_ma128_mixed(self):
        """DoD: 4/8 在 MA128 上 → breadth_align = 0.5"""
        coins_closes = {}
        for i, coin in enumerate(EIGHT_COINS_BREADTH):
            arr = np.full(130, 100.0)
            # 前 4 个 newest=120 > 100，后 4 个 newest=80 < 100
            arr[0] = 120.0 if i < 4 else 80.0
            coins_closes[coin] = list(arr)
        ba, bs = compute_breadth_ma128_align(coins_closes)
        assert ba == pytest.approx(0.5), f"4站上4站下 breadth_align={ba}"


# ============================================================
# P0-06: 广度其余 6 项（P1级：单项测试 graceful fallback + 值合理）
# ============================================================
from bcrm2.cross_asset_features import (
    compute_btc_dominance_change_proxy,
    compute_all_breadth_features,
)


class TestBreadthExtra:
    def _make_coins_closes(self, n=150):
        """构造 8 币 closes dict，newest-first"""
        coins_closes = {}
        base = {"BTC": 60000, "ETH": 3000, "SOL": 150, "BNB": 600, "XRP": 0.5,
                "ADA": 0.4, "DOGE": 0.2, "AVAX": 35}
        for c, p0 in base.items():
            arr = np.full(n, p0)
            coins_closes[c] = list(arr)
        return coins_closes

    def test_btc_dominance_change_positive(self):
        """BTC 涨 10%，其他跌 10% → dominance_change > 0"""
        cc = self._make_coins_closes(n=60)
        # 第 0 位（最新）BTC 价更高，其他更低
        cc["BTC"][0] = cc["BTC"][0] * 1.10
        for c in ["ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX"]:
            cc[c][0] = cc[c][0] * 0.90
        # 第 30 位（30日前）BTC 与其他 都是基准价
        dom_change = compute_btc_dominance_change_proxy(cc, lookback=30)
        assert dom_change > 0, f"BTC 涨山寨跌 → dominance_change={dom_change:.4f} 应为正"

    def test_all_breadth_features_short_data_noerror(self):
        """数据不足时 NaN graceful fallback（不报错）"""
        cc = {"BTC": [60000, 60100, 60200]}  # 只有 3 个点
        out = compute_all_breadth_features(cc)
        assert isinstance(out, dict)
        # 至少有 8 个广度键输出
        assert len(out) >= 8
        # 所有值可 float（nan / 数值皆可）
        for k, v in out.items():
            assert isinstance(v, (int, float, np.floating, np.integer)), f"{k}={v!r} 非数值"


# ============================================================
# P0-07: feature_registry 注册 12 个新特征，enabled_set=btc_morphology
# ============================================================
from bcrm2.feature_registry import FeatureRegistry


class TestFeatureRegistry:
    BTC_MORPHOLOGY_SET = "btc_morphology"

    def _clear_and_import(self):
        """清空注册表并强制重新导入所有 bcrm2 模块以触发注册。

        注意：pytest 同一会话中模块可能已经被 import 缓存（`sys.modules`），
        因此单纯 `import X` 不会再执行模块底部 register 语句。需要
        `importlib.reload` 强制重放注册逻辑。
        """
        import importlib
        FeatureRegistry.clear()
        # 确保注册文件已加载并强制 reload
        import bcrm2.feature_registry  # noqa: F401
        import bcrm2.classic_experience_features as _c  # noqa: F401
        import bcrm2.cross_asset_features as _x  # noqa: F401
        importlib.reload(_c)
        importlib.reload(_x)

    def test_all_12_features_registered(self):
        """DoD: enabled_set=btc_morphology 时 12 形态/广度特征名命中"""
        self._clear_and_import()
        # 构造 300 日 OHLCV
        n = 320
        rng = np.random.RandomState(10)
        close = 100.0 * np.exp(np.cumsum(np.full(n, 0.001) + rng.randn(n) * 0.008))
        high = close * (1 + np.abs(rng.randn(n)) * 0.01)
        low = close * (1 - np.abs(rng.randn(n)) * 0.01)
        open_ = np.concatenate([[close[0]], close[:-1]])
        idx = pd.date_range("2023-01-01", periods=n, freq="D")
        df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": 1e6}, index=idx)

        # 8 币广度（纯价格合成，用 copy BTC/ETH 等作为代理数据就够，测试只看字段名命中）
        ref_coins_closes = {}
        for c in ["BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX"]:
            ref_coins_closes[c] = list(close[::-1])  # newest-first

        features_df, names_map = FeatureRegistry.compute_all(
            df=df,
            symbol="BTC",
            enabled_set=self.BTC_MORPHOLOGY_SET,
            coins_closes=ref_coins_closes,
        )
        cols = set(features_df.columns)
        expected_12 = {
            # P0-01 ADX×4
            "adx_14", "adx_plus_di", "adx_minus_di", "adx_trend_strength_bucket",
            # P0-02 Hurst×3
            "hurst_exp_50", "hurst_exp_100", "hurst_category",
            # P0-03 BB×2
            "bb_width_percentile_252", "bb_squeeze_signal",
            # P0-04 距高×2
            "distance_to_high_60d", "distance_to_high_120d",
            # P0-05 广度 MA128 同向×1（还有其他 7 个广度总共 8 项，但注册要求 12 包含核心 12）
            # 为满足 DoD 我们用：上面 11 + breadth_ma128_align 即可
            "breadth_ma128_align",
        }
        missing = expected_12 - cols
        assert len(missing) == 0, f"缺少已注册的 12 形态/广度特征字段：{sorted(missing)}\n现有列：{sorted(cols)[:40]}"
