"""W3a RED 测试 — 洗盘判定 4 维加密独有特征 + Wyckoff climax 阶段判定.

Spec: docs/superpowers/specs/2026-09-21-washout-detector-design.md §9.3 测试 13-20
W3a 切分: 仅特征提取 (F9-F12 + Wyckoff climax), 数据源通过 macro_data dict 接入,
         缺失时返回中性默认值 (FAIL-OPEN, 与 W2 F4 OI 处理一致).
W3b 后续: 18-数据获取中心 3 采集器 + 奖章架构 Bronze/Silver/Gold 清洗链路 (12 测试).

F9 oi_price_quadrant      — OI×Price 四象限 (0=OI↑Price↑, 1=OI↑Price↓, 2=OI↓Price↑, 3=OI↓Price↓)
F10 funding_rate_zscore   — 30d 滚动 zscore (持续负=洗盘, 突然转正=真弱势反转)
F11 cvd_price_divergence  — CVD 与价格相关性 (负=trapped trader 洗盘, 正=同步下行真弱势)
F12 ofi_std_20d           — 20d OFI 滚动标准差 (低方差+高 vol=可疑洗盘, 高方差=真弱势)
F13 wyckoff_climax_stage  — Wyckoff climax 阶段 (0=未触发, 1=Panic, 2=Sustained, 3=Exhaustion)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _THIS_DIR.parent.parent  # 11-易经推理系统/
sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.memory_l4.bcrm2.washout_features import (  # noqa: E402
    WashoutFeatureExtractor,
)


# ============================================================
# 辅助：构造 OHLCV DataFrame
# ============================================================
def _make_df(closes, highs=None, lows=None, volumes=None):
    """构造 OHLCV DataFrame, 默认 high/low 用 close±0.5% 估计."""
    n = len(closes)
    if highs is None:
        highs = [c * 1.005 for c in closes]
    if lows is None:
        lows = [c * 0.995 for c in closes]
    if volumes is None:
        volumes = [1000.0] * n
    idx = pd.date_range("2026-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame(
        {"open": closes, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=idx,
    )


# ============================================================
# F9: oi_price_quadrant — OI×Price 四象限
# ============================================================
class TestF9OiPriceQuadrant:
    """F9: OI×Price 四象限 (0=OI↑Price↑, 1=OI↑Price↓, 2=OI↓Price↑, 3=OI↓Price↓)."""

    def test_extract_oi_price_quadrant_oi_up_price_down(self):
        """OI↑+Price↓ → 象限 1 (空头建仓, 洗盘特征, 看多反向)."""
        closes = [50.0, 50.0, 45.0]  # 价格↓
        oi = [100.0, 100.0, 120.0]   # OI↑
        df = _make_df(closes)
        macro = {"oi_series": oi}
        ext = WashoutFeatureExtractor()
        # 直接调用新方法 (W3a RED 阶段未实现, 应抛 AttributeError 或返回 -1.0)
        q = ext.extract_oi_price_quadrant(df, macro)
        assert q == 1.0, f"OI↑+Price↓ 应为象限 1, got {q}"

    def test_extract_oi_price_quadrant_oi_down_price_down(self):
        """OI↓+Price↓ → 象限 3 (多头投降, 真弱势特征, 本地底部反转前兆)."""
        closes = [50.0, 50.0, 45.0]  # 价格↓
        oi = [120.0, 120.0, 100.0]   # OI↓
        df = _make_df(closes)
        macro = {"oi_series": oi}
        ext = WashoutFeatureExtractor()
        q = ext.extract_oi_price_quadrant(df, macro)
        assert q == 3.0, f"OI↓+Price↓ 应为象限 3, got {q}"

    def test_extract_oi_price_quadrant_oi_up_price_up(self):
        """OI↑+Price↑ → 象限 0 (多头增仓, 健康上涨趋势)."""
        closes = [50.0, 50.0, 55.0]  # 价格↑
        oi = [100.0, 100.0, 120.0]   # OI↑
        df = _make_df(closes)
        macro = {"oi_series": oi}
        ext = WashoutFeatureExtractor()
        q = ext.extract_oi_price_quadrant(df, macro)
        assert q == 0.0, f"OI↑+Price↑ 应为象限 0, got {q}"

    def test_extract_oi_price_quadrant_fail_open_missing_oi(self):
        """OI 数据缺失 → 中性默认值 -1.0 (FAIL-OPEN)."""
        closes = [50.0, 50.0, 45.0]
        df = _make_df(closes)
        macro = {}  # 无 oi_series
        ext = WashoutFeatureExtractor()
        q = ext.extract_oi_price_quadrant(df, macro)
        assert q == -1.0, f"OI 缺失应 FAIL-OPEN 返回 -1.0, got {q}"


# ============================================================
# F10: funding_rate_zscore — 30d 滚动 zscore
# ============================================================
class TestF10FundingRateZscore:
    """F10: Funding rate 30d zscore (持续负=洗盘, 突然转正=真弱势反转)."""

    def test_extract_funding_rate_zscore_extreme_positive(self):
        """funding 持续负后突然转正 → zscore > 2 (真弱势反转信号)."""
        # 30 个 funding rate: 前 29 个持续 -0.001, 最后 1 个 +0.005 (转正)
        fr_series = [-0.001] * 29 + [0.005]
        df = _make_df([50.0] * 31)
        macro = {"funding_rate_series": fr_series}
        ext = WashoutFeatureExtractor()
        z = ext.extract_funding_rate_zscore(df, macro)
        # 突然转正 → zscore 应 > 2 (extreme positive)
        assert z > 2.0, f"突然转正 zscore 应 > 2.0, got {z}"

    def test_extract_funding_rate_zscore_persistent_negative(self):
        """funding 持续负 (空头偏向, 洗多头) → zscore 在 [-1, 0] 区间."""
        # 30 个 funding rate 全部 -0.001 (持续负, std=0 → FAIL-OPEN 返回 0.0)
        fr_series = [-0.001] * 30
        df = _make_df([50.0] * 31)
        macro = {"funding_rate_series": fr_series}
        ext = WashoutFeatureExtractor()
        z = ext.extract_funding_rate_zscore(df, macro)
        # std=0 时 FAIL-OPEN: 持续负但无偏离 → 返回 0.0 (中性, 表示无偏离)
        assert z == 0.0, f"持续负 std=0 应 FAIL-OPEN 返回 0.0, got {z}"

    def test_extract_funding_rate_zscore_neutral_when_missing(self):
        """funding 数据缺失 → 中性默认值 0.0 (FAIL-OPEN)."""
        df = _make_df([50.0] * 31)
        macro = {}  # 无 funding_rate / funding_rate_series / funding_rate_zscore
        ext = WashoutFeatureExtractor()
        z = ext.extract_funding_rate_zscore(df, macro)
        assert z == 0.0, f"funding 缺失应返回 0.0, got {z}"

    def test_extract_funding_rate_zscore_uses_precomputed(self):
        """若 macro_data 已有 funding_rate_zscore 字段 (已计算好的), 直接复用."""
        df = _make_df([50.0] * 31)
        macro = {"funding_rate_zscore": 2.5}  # 已计算好的 zscore
        ext = WashoutFeatureExtractor()
        z = ext.extract_funding_rate_zscore(df, macro)
        assert z == 2.5, f"应复用 precomputed zscore=2.5, got {z}"


# ============================================================
# F11: cvd_price_divergence — CVD 与价格相关性
# ============================================================
class TestF11CvdPriceDivergence:
    """F11: CVD 与价格相关性 (负=trapped trader 洗盘, 正=同步下行真弱势)."""

    def test_extract_cvd_price_divergence_trapped_trader(self):
        """CVD 下行但价格守住/微涨 → 负相关 (trapped trader fakeout, 洗盘特征).

        spec §2.2: CVD 下行但价格守住 (trapped seller fakeout) → 洗盘信号.
        实现: corr(cvd_level, price_level) — CVD 线性下行 + 价格微涨 → 强负相关.
        """
        n = 30
        # 价格小幅上涨 (守住+微涨), CVD 持续下行 → 强负相关
        closes = [50.0 + i * 0.05 for i in range(n)]
        cvd = [100.0 - i * 0.5 for i in range(n)]  # CVD 持续下行
        df = _make_df(closes)
        macro = {"cvd_series": cvd}
        ext = WashoutFeatureExtractor()
        d = ext.extract_cvd_price_divergence(df, macro)
        # CVD 下行 + 价格微涨 → 负相关
        assert d < 0.0, f"CVD 下行+价格微涨 应为负相关, got {d}"

    def test_extract_cvd_price_divergence_sync_down(self):
        """CVD 与价格同步下行 → 正相关 (真弱势特征)."""
        # 价格和 CVD 都持续下行
        n = 30
        closes = [50.0 - i * 0.1 for i in range(n)]  # 价格下行
        cvd = [100.0 - i * 0.5 for i in range(n)]  # CVD 同步下行
        df = _make_df(closes)
        macro = {"cvd_series": cvd}
        ext = WashoutFeatureExtractor()
        d = ext.extract_cvd_price_divergence(df, macro)
        # 同步下行 → 正相关
        assert d > 0.0, f"CVD 与价格同步下行 应为正相关, got {d}"

    def test_extract_cvd_price_divergence_fail_open_missing_cvd(self):
        """CVD 数据缺失 → 中性默认值 0.0 (FAIL-OPEN)."""
        df = _make_df([50.0] * 30)
        macro = {}  # 无 cvd_series
        ext = WashoutFeatureExtractor()
        d = ext.extract_cvd_price_divergence(df, macro)
        assert d == 0.0, f"CVD 缺失应返回 0.0, got {d}"


# ============================================================
# F12: ofi_std_20d — 20d OFI 滚动标准差
# ============================================================
class TestF12OfiStd20d:
    """F12: 20d OFI 滚动标准差 (低方差+高 vol=可疑洗盘, 高方差=真弱势)."""

    def test_extract_ofi_std_20d_low_variance_suspicious(self):
        """低 OFI 方差 (可疑洗盘, 庄家对倒)."""
        # 20 个 OFI 值全部接近 0.01 (低方差)
        ofi = [0.01] * 20
        df = _make_df([50.0] * 21)
        macro = {"ofi_series": ofi}
        ext = WashoutFeatureExtractor()
        s = ext.extract_ofi_std_20d(df, macro)
        # std=0 (全相同) → 低方差可疑
        assert s == 0.0, f"全相同 std=0 应为低方差, got {s}"

    def test_extract_ofi_std_20d_high_variance_genuine_selling(self):
        """高 OFI 方差 + 持续卖压 (真弱势特征)."""
        # 20 个 OFI 值波动剧烈 (高方差)
        ofi = [0.1, -0.1, 0.2, -0.2, 0.15, -0.15, 0.25, -0.25,
               0.1, -0.1, 0.2, -0.2, 0.15, -0.15, 0.25, -0.25,
               0.1, -0.1, 0.2, -0.2]
        df = _make_df([50.0] * 21)
        macro = {"ofi_series": ofi}
        ext = WashoutFeatureExtractor()
        s = ext.extract_ofi_std_20d(df, macro)
        # 高方差 → std > 0.1
        assert s > 0.1, f"高方差 std 应 > 0.1, got {s}"

    def test_extract_ofi_std_20d_fail_open_missing_ofi(self):
        """OFI 数据缺失 → 中性默认值 0.0 (FAIL-OPEN)."""
        df = _make_df([50.0] * 21)
        macro = {}  # 无 ofi_series
        ext = WashoutFeatureExtractor()
        s = ext.extract_ofi_std_20d(df, macro)
        assert s == 0.0, f"OFI 缺失应返回 0.0, got {s}"


# ============================================================
# F13: wyckoff_climax_stage — Wyckoff Selling Climax 3 阶段
# ============================================================
class TestF13WyckoffClimaxStage:
    """F13: Wyckoff climax 阶段 (0=未触发, 1=Panic, 2=Sustained, 3=Exhaustion).

    spec §2.3 阈值 (1h bar 近似):
      Stage 1 Panic: 累计跌幅 ∈ [0.01, 0.03], close<open 占比 > 0.66
      Stage 2 Sustained: vol/vol_ma20 ∈ [2.0, 3.0], 累计跌幅 ∈ [0.03, 0.05]
      Stage 3 Exhaustion: 量能衰减 > 0.3, 下跌速度放缓 > 0.3
      触发: volume ≥ 2 × 20d 均量 且 价格跌破 20d 低点
    """

    def test_extract_wyckoff_climax_stage_1_panic(self):
        """Stage 1 Panic: 累计跌幅 1-3%, close<open 占比 > 0.66."""
        # 构造 30d 数据: 前 27 bar 平稳, 后 3 bar 跌 1.6% (Stage 1 Panic)
        # close[-1]=49.0 需跌破前 20d low (low[-21:-1] min)
        closes = [50.0] * 27 + [49.8, 49.6, 49.0]  # 累计跌 (49.8-49.0)/49.8 = 0.016 (1.6%)
        opens = [50.0] + closes[:-1]
        highs = [max(o, c) * 1.001 for o, c in zip(opens, closes)]
        lows = [min(o, c) * 0.999 for o, c in zip(opens, closes)]
        vols = [1000.0] * 27 + [3000.0, 3000.0, 3000.0]  # 后 3 bar 放量 3x
        df = pd.DataFrame(
            {"open": opens, "high": highs, "low": lows, "close": closes, "volume": vols},
            index=pd.date_range("2026-01-01", periods=30, freq="1h", tz="UTC"),
        )
        macro = {}
        ext = WashoutFeatureExtractor()
        stage = ext.extract_wyckoff_climax_stage(df, macro)
        # Stage 1: 跌 1.6% + 放量 + 价格跌破前 20d low → 应触发 Stage 1
        assert stage >= 1.0, f"Stage 1 Panic 应触发 stage>=1.0, got {stage}"

    def test_extract_wyckoff_climax_stage_2_sustained(self):
        """Stage 2 Sustained: vol/vol_ma20 ∈ [2.0, 3.0], 跌幅 3-5%."""
        # 构造 30d 数据: 前 26 bar 平稳, 后 4 bar 跌 3.125% (Stage 2 Sustained)
        # close[-1]=46.5 需跌破前 20d low
        closes = [50.0] * 26 + [49.0, 48.0, 47.5, 46.5]  # 累计跌 (48.0-46.5)/48.0 = 0.03125 (3.125%)
        opens = [50.0] + closes[:-1]
        highs = [max(o, c) * 1.001 for o, c in zip(opens, closes)]
        lows = [min(o, c) * 0.999 for o, c in zip(opens, closes)]
        vols = [1000.0] * 26 + [2500.0, 2500.0, 2500.0, 2500.0]  # 放量 2.5x
        df = pd.DataFrame(
            {"open": opens, "high": highs, "low": lows, "close": closes, "volume": vols},
            index=pd.date_range("2026-01-01", periods=30, freq="1h", tz="UTC"),
        )
        macro = {}
        ext = WashoutFeatureExtractor()
        stage = ext.extract_wyckoff_climax_stage(df, macro)
        # Stage 2: 跌 3.125% + 放量 2.5x → 应触发 stage >= 2.0
        assert stage >= 2.0, f"Stage 2 Sustained 应触发 stage>=2.0, got {stage}"

    def test_extract_wyckoff_climax_stage_3_exhaustion(self):
        """Stage 3 Exhaustion: 量能衰减 > 0.3, 下跌速度放缓 > 0.3."""
        # 构造 30d 数据: 前期放量跌, 后 3 bar 量能递减 + 速度放缓
        # close[-1]=44.99 需跌破前 20d low (low[28]=min(45.1,45.05)*0.999=45.00495)
        closes = [50.0] * 20 + [49.0, 48.0, 47.0, 46.5, 46.0, 45.5, 45.2, 45.1, 45.05, 44.99]
        opens = [50.0] + closes[:-1]
        highs = [max(o, c) * 1.001 for o, c in zip(opens, closes)]
        lows = [min(o, c) * 0.999 for o, c in zip(opens, closes)]
        # 前 7 bar 放量跌 (Stage 1+2), 后 3 bar 量能递减 + 速度放缓
        vols = [1000.0] * 20 + [3000.0, 3000.0, 2500.0, 2000.0, 1800.0, 1500.0, 1200.0,
                                800.0, 600.0, 400.0]
        df = pd.DataFrame(
            {"open": opens, "high": highs, "low": lows, "close": closes, "volume": vols},
            index=pd.date_range("2026-01-01", periods=30, freq="1h", tz="UTC"),
        )
        macro = {}
        ext = WashoutFeatureExtractor()
        stage = ext.extract_wyckoff_climax_stage(df, macro)
        # Stage 3: 量能衰减 + 速度放缓 → stage == 3.0
        assert stage == 3.0, f"Stage 3 Exhaustion 应触发 stage=3.0, got {stage}"

    def test_extract_wyckoff_climax_no_trigger_low_volume(self):
        """volume < 2x 20d 均量 → 不触发 climax (stage=0.0)."""
        # 平稳数据, 无放量, 无明显下跌
        n = 30
        closes = [50.0 + 0.01 * i for i in range(n)]  # 缓慢上涨
        opens = [50.0] + closes[:-1]
        highs = [c * 1.001 for c in closes]
        lows = [c * 0.999 for c in closes]
        vols = [1000.0] * n  # 无放量
        df = pd.DataFrame(
            {"open": opens, "high": highs, "low": lows, "close": closes, "volume": vols},
            index=pd.date_range("2026-01-01", periods=n, freq="1h", tz="UTC"),
        )
        macro = {}
        ext = WashoutFeatureExtractor()
        stage = ext.extract_wyckoff_climax_stage(df, macro)
        assert stage == 0.0, f"低量无触发应 stage=0.0, got {stage}"


# ============================================================
# 子开关门控 (W2 风格)
# ============================================================
class TestW3SubswitchGating:
    """W3 子开关门控: enable_oi_price_quadrant/enable_funding_rate/enable_cvd/enable_ofi/enable_wyckoff_climax."""

    def test_extract_all_w3_features_respect_subswitches(self):
        """关闭所有 W3 子开关 → extract_all 不输出 F9-F13."""
        closes = [50.0] * 30
        df = _make_df(closes)
        macro = {
            "oi_series": [100.0] * 30,
            "funding_rate_series": [-0.001] * 30,
            "cvd_series": [100.0] * 30,
            "ofi_series": [0.01] * 30,
        }
        # 关闭所有 W3 子开关
        config = {
            "enable_volume_dim": True, "enable_support_dim": True,
            "enable_amplitude_dim": True, "enable_oi_dim": True,
            "enable_position_dim": True, "enable_rebound_dim": True,
            "enable_news_dim": True, "enable_market_dim": True,
            "enable_oi_price_quadrant": False,
            "enable_funding_rate": False,
            "enable_cvd": False,
            "enable_ofi": False,
            "enable_wyckoff_climax": False,
        }
        ext = WashoutFeatureExtractor(config=config)
        out = ext.extract_all(df, macro)
        # W3 维度不应出现在输出中
        w3_keys = {"oi_price_quadrant", "funding_rate_zscore",
                   "cvd_price_divergence", "ofi_std_20d", "wyckoff_climax_stage"}
        for k in w3_keys:
            assert k not in out, f"子开关关闭后不应输出 {k}, got keys={set(out.keys())}"

    def test_extract_all_w3_features_enabled_output_present(self):
        """开启所有 W3 子开关 → extract_all 输出 F9-F13."""
        closes = [50.0] * 30
        df = _make_df(closes)
        macro = {
            "oi_series": [100.0] * 30,
            "funding_rate_series": [-0.001] * 30,
            "cvd_series": [100.0] * 30,
            "ofi_series": [0.01] * 30,
        }
        ext = WashoutFeatureExtractor()  # 默认全开
        out = ext.extract_all(df, macro)
        w3_keys = {"oi_price_quadrant", "funding_rate_zscore",
                   "cvd_price_divergence", "ofi_std_20d", "wyckoff_climax_stage"}
        out_keys = set(out.keys())
        for k in w3_keys:
            assert k in out_keys, f"子开关开启后应输出 {k}, got keys={out_keys}"

    def test_extract_all_w3_features_fail_open_on_none_macro(self):
        """macro_data=None → extract_all 不抛错, 返回空 dict (与 W2 FAIL-OPEN 一致).

        W2 设计: extract_all 在 macro_data=None 时直接返回空 dict, 不抛错.
        单个 W3 方法的 FAIL-OPEN 由各自测试覆盖 (test_*_fail_open_missing_*).
        """
        closes = [50.0] * 30
        df = _make_df(closes)
        ext = WashoutFeatureExtractor()
        out = ext.extract_all(df, None)  # macro=None
        # W2 行为: macro=None → 返回空 dict, 不抛错
        assert out == {}, f"macro=None 应返回空 dict (W2 FAIL-OPEN), got keys={set(out.keys())}"
