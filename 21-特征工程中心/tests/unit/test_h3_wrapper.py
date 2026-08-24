"""P4 H3 策略出口 wrapper 测试。

验证 wrap_featurehub() 在不同 EN_FEATUREHUB_* 环境变量下的行为：
  - 未设置 → 走原始 FE
  - =true → 走 FeatureHub
  - FeatureHub 异常 → 回退原始 FE
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


def _sample_ohlcv(n=100):
    """合成 OHLCV。"""
    import numpy as np
    rng = np.random.default_rng(42)
    t = np.linspace(100, 200, n)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame({
        "open": t, "high": t * 1.01, "low": t * 0.99,
        "close": t, "volume": 1e6,
    }, index=idx)


# ── T1 · EN_FEATUREHUB 未设置 → 走原始 FE ───────────
def test_env_not_set_uses_original(monkeypatch):
    monkeypatch.delenv("EN_FEATUREHUB_TEST", raising=False)
    from feature_hub.h3_wrapper import wrap_featurehub

    original_fn = MagicMock(return_value=pd.DataFrame({"orig_feat": [1.0]}))
    result = wrap_featurehub(
        strategy_name="test",
        ohlcv_df=_sample_ohlcv(),
        symbol="BTC",
        set_name="btc_morph_v6",
        original_fe_fn=original_fn,
    )

    original_fn.assert_called_once()
    assert "orig_feat" in result.columns


# ── T2 · EN_FEATUREHUB=false → 走原始 FE ────────────
def test_env_false_uses_original(monkeypatch):
    monkeypatch.setenv("EN_FEATUREHUB_TEST", "false")
    from feature_hub.h3_wrapper import wrap_featurehub

    original_fn = MagicMock(return_value=pd.DataFrame({"orig_feat": [1.0]}))
    result = wrap_featurehub(
        strategy_name="test",
        ohlcv_df=_sample_ohlcv(),
        symbol="BTC",
        set_name="btc_morph_v6",
        original_fe_fn=original_fn,
    )

    original_fn.assert_called_once()


# ── T3 · EN_FEATUREHUB=true → 走 FeatureHub ──────────
def test_env_true_uses_featurehub(monkeypatch):
    monkeypatch.setenv("EN_FEATUREHUB_TEST", "true")
    from feature_hub.h3_wrapper import wrap_featurehub

    # mock FeaturePipeline.run 返回 FeatureVector
    mock_fv = MagicMock()
    mock_fv.df = pd.DataFrame({"fh_feat": [1.0]})
    mock_fv.meta = {"modules_run": ["crypto_morphology"]}

    original_fn = MagicMock(return_value=pd.DataFrame({"orig_feat": [1.0]}))

    with patch("feature_hub.h3_wrapper._build_pipeline") as mock_bp:
        mock_pipe = MagicMock()
        mock_pipe.run.return_value = mock_fv
        mock_bp.return_value = mock_pipe

        result = wrap_featurehub(
            strategy_name="test",
            ohlcv_df=_sample_ohlcv(),
            symbol="BTC",
            set_name="btc_morph_v6",
            original_fe_fn=original_fn,
        )

    original_fn.assert_not_called()
    mock_pipe.run.assert_called_once()


# ── T4 · FeatureHub 异常 → 回退原始 FE ─────────────
def test_featurehub_exception_fallback(monkeypatch):
    monkeypatch.setenv("EN_FEATUREHUB_TEST", "true")
    from feature_hub.h3_wrapper import wrap_featurehub

    original_fn = MagicMock(return_value=pd.DataFrame({"orig_feat": [1.0]}))

    with patch("feature_hub.h3_wrapper._build_pipeline") as mock_bp:
        mock_pipe = MagicMock()
        mock_pipe.run.side_effect = RuntimeError("pipeline boom")
        mock_bp.return_value = mock_pipe

        result = wrap_featurehub(
            strategy_name="test",
            ohlcv_df=_sample_ohlcv(),
            symbol="BTC",
            set_name="btc_morph_v6",
            original_fe_fn=original_fn,
        )

    original_fn.assert_called_once()
    assert "orig_feat" in result.columns


# ── T5 · strategy_name 映射到正确的 env var ─────────
def test_strategy_name_env_mapping(monkeypatch):
    """EN_FEATUREHUB_BTC 对应 strategy_name='btc'。"""
    monkeypatch.setenv("EN_FEATUREHUB_BTC", "true")
    from feature_hub.h3_wrapper import wrap_featurehub

    mock_fv = MagicMock()
    mock_fv.df = pd.DataFrame({"fh_feat": [1.0]})
    mock_fv.meta = {"modules_run": ["test"]}

    original_fn = MagicMock(return_value=pd.DataFrame({"orig": [1.0]}))

    with patch("feature_hub.h3_wrapper._build_pipeline") as mock_bp:
        mock_pipe = MagicMock()
        mock_pipe.run.return_value = mock_fv
        mock_bp.return_value = mock_pipe

        wrap_featurehub(
            strategy_name="btc",
            ohlcv_df=_sample_ohlcv(),
            symbol="BTC",
            set_name="btc_morph_v6",
            original_fe_fn=original_fn,
        )

    original_fn.assert_not_called()


# ── T6 · 传入 macro_df 时不抛异常 ───────────────────
def test_with_macro_df(monkeypatch):
    monkeypatch.setenv("EN_FEATUREHUB_TEST", "true")
    from feature_hub.h3_wrapper import wrap_featurehub

    mock_fv = MagicMock()
    mock_fv.df = pd.DataFrame({"fh_feat": [1.0]})
    mock_fv.meta = {"modules_run": ["test"]}

    original_fn = MagicMock(return_value=pd.DataFrame({"orig": [1.0]}))
    macro_df = pd.DataFrame({"fear_greed": [45]}, index=[0])

    with patch("feature_hub.h3_wrapper._build_pipeline") as mock_bp:
        mock_pipe = MagicMock()
        mock_pipe.run.return_value = mock_fv
        mock_bp.return_value = mock_pipe

        result = wrap_featurehub(
            strategy_name="test",
            ohlcv_df=_sample_ohlcv(),
            symbol="BTC",
            set_name="btc_morph_v6",
            original_fe_fn=original_fn,
            macro_df=macro_df,
        )

    # 验证 macro_df 被传递给 pipeline.run
    call_kwargs = mock_pipe.run.call_args.kwargs
    assert call_kwargs.get("macro_df") is not None
