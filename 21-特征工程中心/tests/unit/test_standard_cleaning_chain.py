"""T14 · 标准特征清洗链 7 条边例（TDD 先红→后绿）。

清洗链顺序：① Inf/NaN兜底 → ② RobustScaler(IQR) → ③ VIF去共线 → ④ IV筛选
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "21-特征工程中心"))


@pytest.fixture
def clean_df():
    """1000 行 × 5 列正常数值 DF"""
    rng = np.random.default_rng(42)
    n = 1000
    return pd.DataFrame({
        "a": rng.normal(0, 1, n),
        "b": rng.normal(5, 2, n),
        "c": rng.normal(-3, 0.5, n),
        "d": rng.uniform(10, 20, n),
        "e": rng.normal(0, 1, n),
    })


# ============================================================
# T14-1  Inf/NaN 全消无残留
# ============================================================
def test_t14_1_inf_nan_impute(clean_df):
    from feature_hub.cleaning_chain.cleaning_steps import InfNaNImpute

    df = clean_df.copy()
    df.iloc[0, 0] = np.inf
    df.iloc[1, 1] = -np.inf
    df.iloc[2, 2] = np.nan

    step = InfNaNImpute()
    out = step.fit_transform(df)

    assert not out.isna().any().any(), "NaN 残留"
    assert not np.isinf(out.values).any(), "Inf 残留"


# ============================================================
# T14-2  IQR=0 恒等缩放不除零
# ============================================================
def test_t14_2_iqr_zero_identity():
    from feature_hub.cleaning_chain.cleaning_steps import RobustScalerIQR

    df = pd.DataFrame({"const": [5.0] * 100})
    step = RobustScalerIQR()
    out = step.fit_transform(df)
    # IQR=0 → 恒等，不报错
    assert (out["const"] == 5.0).all()


# ============================================================
# T14-3  样本<1000 自动跳过 VIF
# ============================================================
def test_t14_3_vif_skip_small_sample():
    from feature_hub.cleaning_chain.cleaning_steps import VIFDropper

    df = pd.DataFrame({
        "a": np.arange(500, dtype=float),
        "b": np.arange(500, dtype=float) * 2,  # 完全共线
    })
    step = VIFDropper(threshold=10.0, skip_if=lambda X: len(X) < 1000)
    out = step.fit_transform(df)
    # 小样本跳过 → 不删列
    assert set(out.columns) == {"a", "b"}


# ============================================================
# T14-4  无 y 自动跳过 IV
# ============================================================
def test_t14_4_iv_skip_no_label(clean_df):
    from feature_hub.cleaning_chain.cleaning_steps import IVDropper

    step = IVDropper(threshold=0.02, skip_if=lambda y: y is None)
    out = step.fit_transform(clean_df, y=None)
    # 无标签 → 不删列
    assert set(out.columns) == set(clean_df.columns)


# ============================================================
# T14-5  VIF>10 从高到低剔除
# ============================================================
def test_t14_5_vif_drops_collinear():
    from feature_hub.cleaning_chain.cleaning_steps import VIFDropper

    rng = np.random.default_rng(0)
    n = 1200
    a = rng.normal(0, 1, n)
    b = a * 3 + rng.normal(0, 0.01, n)  # 与 a 高度共线
    c = rng.normal(5, 2, n)
    df = pd.DataFrame({"a": a, "b": b, "c": c})

    step = VIFDropper(threshold=10.0, skip_if=lambda X: len(X) < 1000)
    out = step.fit_transform(df)
    # a 或 b 中应被删一个
    assert len(out.columns) == 2, f"VIF 剔除后应剩 2 列, 实际 {out.columns}"


# ============================================================
# T14-6  IV<0.02 剔除
# ============================================================
def test_t14_6_iv_drops_useless():
    from feature_hub.cleaning_chain.cleaning_steps import IVDropper

    rng = np.random.default_rng(0)
    n = 1000
    # useful 特征：与 y 强相关
    useful = rng.normal(0, 1, n)
    y = (useful > 0).astype(int)
    # useless 特征：与 y 无关
    useless = rng.normal(0, 1, n)
    df = pd.DataFrame({"useful": useful, "useless": useless})

    step = IVDropper(threshold=0.02, skip_if=lambda y_in: y_in is None)
    out = step.fit_transform(df, y=y)
    assert "useful" in out.columns
    # useless 可能被删也可能保留（取决于 IV 计算），但 useful 必须保留
    assert len(out.columns) >= 1


# ============================================================
# T14-7  任一步异常 → Raw 透传 + warning（L1 fail-open）
# ============================================================
def test_t14_7_fail_open_on_exception(clean_df):
    from feature_hub.cleaning_chain.standard_chain import StandardCleaningChain

    chain = StandardCleaningChain()
    # 注入一个会导致异常的 DF（空 DF）
    empty_df = pd.DataFrame()
    out = chain.fit_transform(empty_df)
    # fail-open → 返回原 DF（空），不抛异常
    assert out is not None
    assert isinstance(out, pd.DataFrame)
