"""T32 — 易经 BTC / BCRM2 bagua+cycle 一致性测试。

目标：
  1. 对同一合成 OHLCV，FeatureHub(yijing_bagua_cycle) 的列名、数值与
     FeatureRegistry.compute_all(bagua+cycle) 一致（单值场景）；
  2. H3 wrapper return_tuple=True 时返回的 feature_names_by_gua（八卦字典）
     与 compute_all 结果完全一致（字典等价）；
  3. 关断（EN_FEATUREHUB_YIJING_BTC=false）走 original_fe_fn，与直连
     FeatureRegistry.compute_all 完全一致 — 零回归。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# ============================================================
# 1. 触发 BCRM2 侧 FeatureRegistry.register（bagua / cycle 等）
# ============================================================
import scripts.memory_l4.bcrm2.bagua_feature_engine  # noqa: F401,E402
import scripts.memory_l4.bcrm2.cycle_features  # noqa: F401,E402

from feature_hub.hub.feature_registry import FeatureRegistry  # noqa: E402


# ============================================================
# 2. 合成 OHLCV
# ============================================================
def _synth_ohlcv(n: int = 500, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    t = np.linspace(25_000, 70_000, n) * (1 + rng.normal(0, 0.003, n))
    idx = pd.date_range("2023-01-01", periods=n, freq="4h")
    df = pd.DataFrame({
        "open":  t * (1 + rng.normal(0, 0.002, n)),
        "high":  t * (1 + np.abs(rng.normal(0, 0.006, n))),
        "low":   t * (1 - np.abs(rng.normal(0, 0.006, n))),
        "close": t,
        "volume": 1e8 * (1 + rng.uniform(-0.3, 1.2, n)),
    }, index=idx)
    return df


def _original_compute_all(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """「原始 FE」直接走 FeatureRegistry.compute_all — 与 bcrm2_adapter 完全一致。"""
    return FeatureRegistry.compute_all(df=df, enabled=["bagua", "cycle"])


# ============================================================
# 3. 辅助：列交集比例 / Pearson 相关 / gua_map 等价
# ============================================================
def _common_rate(orig_cols: list[str], fh_cols: list[str]) -> float:
    o, f = set(orig_cols), set(fh_cols)
    if not o:
        return 1.0 if not f else 0.0
    return len(o & f) / len(o)


def _mean_pearson(orig: pd.DataFrame, fh: pd.DataFrame, cols: list[str]) -> float:
    rs = []
    for c in cols:
        a = pd.to_numeric(orig[c], errors="coerce").values
        b = pd.to_numeric(fh[c], errors="coerce").values
        if len(a) < 2 or len(b) < 2:
            continue
        mask = np.isfinite(a) & np.isfinite(b)
        if mask.sum() < 3:
            continue
        if np.std(a[mask]) < 1e-14 or np.std(b[mask]) < 1e-14:
            continue
        r = np.corrcoef(a[mask], b[mask])[0, 1]
        if np.isfinite(r):
            rs.append(r)
    return float(np.mean(rs)) if rs else 0.0


def _gua_map_equal(g1: dict, g2: dict) -> bool:
    """八卦/子组分组字典等价（不要求 key 顺序；要求 key 集合相同、排序后列名列表相同）。"""
    if set(g1.keys()) != set(g2.keys()):
        return False
    for k in g1.keys():
        if sorted(g1[k]) != sorted(g2[k]):
            return False
    return True


# ============================================================
# 4. 测试用例
# ============================================================
class TestT32YijingBaguaCycleConsistency:
    def test_fh_columns_and_values_match_fr(self):
        df = _synth_ohlcv(600, seed=7)
        orig_feats, orig_gua = _original_compute_all(df)

        # FH Native 模块 yijing_cycle
        from feature_hub.modules.yijing_cycle import compute as yijing_compute
        fh_feats, fh_gua = yijing_compute(df, enabled=["bagua", "cycle"])

        assert _common_rate(list(orig_feats.columns), list(fh_feats.columns)) >= 0.95, (
            f"列交集不足: orig={len(orig_feats.columns)} fh={len(fh_feats.columns)}"
        )
        common = sorted(set(orig_feats.columns) & set(fh_feats.columns))
        assert len(common) > 150, f"公共列太少: {len(common)}"
        r = _mean_pearson(orig_feats, fh_feats, common)
        assert r >= 0.97, f"公共列 Pearson 均值过低: {r:.4f}"
        assert _gua_map_equal(orig_gua, fh_gua), "bagua+cycle gua_map 结构不一致"

    def test_pipeline_yijing_bagua_cycle_exports_extra_ctx(self):
        """FeaturePipeline.run → meta['extra_ctx'] 有 yijing_cycle 且可解包为 feature_names_by_gua。"""
        from feature_hub.pipeline.feature_pipeline import FeaturePipeline
        from feature_hub.modules.loader import load_default_sets

        pipe = FeaturePipeline()
        load_default_sets(pipe)
        df = _synth_ohlcv(500, seed=11)
        fv = pipe.run("yijing_bagua_cycle", df=df, symbol="BTC")
        assert "yijing_cycle" in fv.meta.get("modules_run", []), fv.meta
        assert "extra_ctx" in fv.meta, f"meta 缺 extra_ctx: {list(fv.meta.keys())}"
        ctx = fv.meta["extra_ctx"].get("yijing_cycle", {})
        # 至少 8 卦 + cycle 4 子组 = 12 个 key
        assert len(ctx) >= 12, f"extra_ctx 内容过少: {list(ctx.keys())}"
        # 确认有 8 卦名
        for g in ("qian", "kun", "zhen", "xun", "kan", "li", "gen", "dui"):
            assert g in ctx, f"缺八卦 key: {g}"
        for c in ("cycle_halving", "cycle_ath", "cycle_inventory", "cycle_long_term"):
            assert c in ctx, f"缺 cycle 子组 key: {c}"

    def test_h3_wrapper_return_tuple_matches_fr(self):
        """EN_FEATUREHUB_YIJING_BTC=true → H3 元组返回值与 FR 一致。"""
        from feature_hub.h3_wrapper import wrap_featurehub

        os.environ["EN_FEATUREHUB_YIJING_BTC"] = "true"
        try:
            df = _synth_ohlcv(500, seed=13)
            orig_feats, orig_gua = _original_compute_all(df)

            fh_feats, fh_gua = wrap_featurehub(
                strategy_name="yijing_btc",
                ohlcv_df=df,
                symbol="BTC",
                set_name="yijing_bagua_cycle",
                original_fe_fn=lambda: _original_compute_all(df),
                strip_prefix=True,
                return_tuple=True,
            )
        finally:
            del os.environ["EN_FEATUREHUB_YIJING_BTC"]

        assert isinstance(fh_feats, pd.DataFrame)
        assert isinstance(fh_gua, dict)
        # strip_prefix 去掉 yijing_cycle__ 后列名与 FR 对齐
        assert _common_rate(list(orig_feats.columns), list(fh_feats.columns)) >= 0.95, (
            f"H3 列交集不足 orig={list(orig_feats.columns)[:5]} fh={list(fh_feats.columns)[:5]}"
        )
        common = sorted(set(orig_feats.columns) & set(fh_feats.columns))
        r = _mean_pearson(orig_feats, fh_feats, common)
        assert r >= 0.97, f"H3 Pearson 均值过低: {r:.4f}"
        assert _gua_map_equal(orig_gua, fh_gua), "H3 gua_map 与 FR 不等价"

    def test_h3_wrapper_fallback_off_takes_original_branch(self):
        """关断 EN_FEATUREHUB_YIJING_BTC → 走 original_fe_fn，无任何 FH 特征列前缀。"""
        from feature_hub.h3_wrapper import wrap_featurehub

        os.environ.pop("EN_FEATUREHUB_YIJING_BTC", None)
        df = _synth_ohlcv(400, seed=23)
        orig_feats, orig_gua = _original_compute_all(df)

        out = wrap_featurehub(
            strategy_name="yijing_btc",
            ohlcv_df=df,
            symbol="BTC",
            set_name="yijing_bagua_cycle",
            original_fe_fn=lambda: _original_compute_all(df),
            strip_prefix=True,
            return_tuple=True,
        )
        assert isinstance(out, tuple) and len(out) == 2
        fh_feats, fh_gua = out
        # 关断情况下应该就是 original 的结果（列 100% 相同、无模块前缀）
        pd.testing.assert_frame_equal(fh_feats, orig_feats, check_names=False)
        assert _gua_map_equal(fh_gua, orig_gua)
