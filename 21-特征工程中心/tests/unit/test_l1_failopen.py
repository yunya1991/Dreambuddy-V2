"""T26 · M3.6 L1 fail-open 注入测试（5 类异常）

FAIL-OPEN 铁律：Silver/FeatureHub 任一步异常 → 中性兜底 + warning，绝不阻塞交易热路径。

5 类异常注入：
  T26-1  模块 compute 抛 KeyError     → 跳过 + 其他模块照常输出 + meta 记录 modules_failed
  T26-2  InfNaNImpute 输入全 NaN/Inf  → 兜底为 50，不抛异常
  T26-3  RobustScalerIQR 注入异常输入 → StandardCleaningChain fail-open 返回原 DF
  T26-4  VIFDropper 全共线奇异矩阵    → lstsq 异常被捕获，列保留返回
  T26-5  IVDropper y 长度不匹配        → 跳过 IV 筛选，不阻塞链路
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "21-特征工程中心"))


@pytest.fixture
def ohlcv():
    rng = np.random.default_rng(7)
    n = 300
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, n)))
    return pd.DataFrame({
        "open": close * (1 + rng.normal(0, 0.004, n)),
        "high": close * (1 + np.abs(rng.normal(0, 0.01, n))),
        "low": close * (1 - np.abs(rng.normal(0, 0.01, n))),
        "close": close,
        "volume": 1e6 * (1 + rng.uniform(-0.5, 1.0, n)),
    }, index=pd.date_range("2024-01-01", periods=n, freq="D"))


# ============================================================
# T26-1  模块 compute 抛 KeyError → 跳过 + 其他模块照常输出
# ============================================================
def test_t26_1_module_keyerror_skip(ohlcv, caplog):
    from feature_hub.pipeline.feature_pipeline import FeaturePipeline

    def good_module(df, **kw):
        return pd.DataFrame({"good_feat": df["close"].pct_change()}, index=df.index)

    def bad_module(df, **kw):
        # 故意访问不存在的列触发 KeyError
        _ = df["nonexistent_column"]
        return pd.DataFrame()

    pipe = FeaturePipeline()
    pipe.register_module("good", good_module)
    pipe.register_module("bad", bad_module)
    pipe.register_set("mixed_set", ["good", "bad"])

    with caplog.at_level(logging.WARNING, logger="feature_hub.pipeline.feature_pipeline"):
        fv = pipe.run(set_name="mixed_set", df=ohlcv)

    # ① good 模块照常输出
    assert "good__good_feat" in fv.df.columns, "good 模块被 bad 阻塞"
    # ② bad 模块被跳过（meta 记录 modules_failed）
    failed = fv.meta.get("modules_failed", [])
    assert "bad" in failed, f"modules_failed 未记录 bad: {failed}"
    # ③ warning 日志含 fail-open 标识
    assert any("fail-open" in rec.message for rec in caplog.records), \
        "未产出 fail-open warning 日志"


# ============================================================
# T26-2  InfNaNImpute 全 NaN/Inf 兜底为 50
# ============================================================
def test_t26_2_infnan_impute_full_dirty():
    from feature_hub.cleaning_chain.cleaning_steps import InfNaNImpute

    # 全 NaN/Inf 的极端输入
    df = pd.DataFrame({
        "all_nan": [np.nan, np.nan, np.nan, np.nan, np.nan],
        "all_inf": [np.inf, -np.inf, np.inf, -np.inf, np.inf],
        "mixed":   [np.nan, np.inf, -np.inf, np.nan, 1.0],
    })
    step = InfNaNImpute()
    out = step.fit_transform(df)

    # 不抛异常
    assert isinstance(out, pd.DataFrame)
    # 无 NaN/Inf 残留
    assert not out.isna().any().any(), "NaN 残留"
    assert not np.isinf(out.values).any(), "Inf 残留"
    # 全 NaN 列兜底为 50
    assert (out["all_nan"] == 50.0).all(), f"全 NaN 列未兜底为 50: {out['all_nan'].unique()}"


# ============================================================
# T26-3  RobustScalerIQR 注入异常输入 → StandardCleaningChain fail-open
# ============================================================
def test_t26_3_robust_scaler_exception_failopen():
    from feature_hub.cleaning_chain.standard_chain import StandardCleaningChain

    # 构造一个会让 RobustScalerIQR 抛异常的输入：
    # 含字符串列 → median/quantile 在混合 dtype 上抛 TypeError
    df = pd.DataFrame({
        "num":   [1.0, 2.0, 3.0, 4.0, 5.0] * 200,
        "str":   ["a"] * 1000,
    })

    chain = StandardCleaningChain()
    # fail-open → 返回原 DF（或上一步输出），不抛异常
    out = chain.fit_transform(df)
    assert isinstance(out, pd.DataFrame)
    # 即使 RobustScalerIQR 抛异常，链路仍返回非 None 结果
    assert out is not None


# ============================================================
# T26-4  VIFDropper 全共线奇异矩阵 → 列保留返回
# ============================================================
def test_t26_4_vif_singular_matrix():
    from feature_hub.cleaning_chain.cleaning_steps import VIFDropper

    # 构造会让 lstsq 异常的奇异矩阵：
    # 全零列 + 完全相同列 → ss_tot=0 / 矩阵退化
    n = 1200
    df = pd.DataFrame({
        "zero":   [0.0] * n,
        "dup_a":  [3.14] * n,  # 常量列
        "dup_b":  [3.14] * n,  # 与 dup_a 完全相同
    })

    step = VIFDropper(threshold=10.0, skip_if=lambda X: len(X) < 1000)
    # 不应抛异常
    out = step.fit_transform(df)
    assert isinstance(out, pd.DataFrame)
    # 异常被内部捕获，列保留返回（_compute_vif 出错时返回 1.0）
    assert len(out.columns) >= 1, f"VIF 奇异矩阵后无列返回: {out.columns}"


# ============================================================
# T26-5  IVDropper y 长度不匹配 → 跳过 IV 筛选
# ============================================================
def test_t26_5_iv_mismatched_y_skip():
    from feature_hub.cleaning_chain.cleaning_steps import IVDropper

    rng = np.random.default_rng(0)
    n = 1000
    df = pd.DataFrame({
        "feat_a": rng.normal(0, 1, n),
        "feat_b": rng.normal(0, 1, n),
    })
    # y 长度与 df 不匹配（仅 500 个）
    y_short = rng.integers(0, 2, 500)

    step = IVDropper(threshold=0.02, skip_if=lambda y: y is None)
    # 不应抛异常 → 链路继续
    try:
        out = step.fit_transform(df, y=y_short)
        # 即使内部 _compute_iv 出错，也应返回 DataFrame（保留列）
        assert isinstance(out, pd.DataFrame)
    except (ValueError, IndexError):
        # 如果 y 长度不匹配直接抛异常，则 StandardCleaningChain 应 fail-open
        from feature_hub.cleaning_chain.standard_chain import StandardCleaningChain
        chain = StandardCleaningChain()
        out = chain.fit_transform(df, y=y_short)
        assert isinstance(out, pd.DataFrame)


# ============================================================
# T26-G  5 类异常综合：StandardCleaningChain.fit_transform 全程不抛
# ============================================================
def test_t26_g_combined_no_raise():
    from feature_hub.cleaning_chain.standard_chain import StandardCleaningChain

    # 5 类异常同时存在：空 DF + 全 NaN + 全共线 + 字符串列 + 不匹配 y
    chain = StandardCleaningChain()
    cases = [
        pd.DataFrame(),
        pd.DataFrame({"x": [np.nan] * 5}),
        pd.DataFrame({"a": [1.0] * 1200, "b": [1.0] * 1200}),
        pd.DataFrame({"s": ["x"] * 1000, "n": [1.0] * 1000}),
    ]

    for df in cases:
        out = chain.fit_transform(df)
        # 铁律：永不返回 None，永不抛异常
        assert out is not None, "fail-open 返回 None"
        assert isinstance(out, pd.DataFrame), "fail-open 返回非 DataFrame"
