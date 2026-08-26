"""H3 策略出口 wrapper — 策略入口 ≤3 行接入 FeatureHub。

设计（Spec§6.1 H3）：
  · EN_FEATUREHUB_<STRATEGY> = true → 走 FeatureHub（GoldReader + FeaturePipeline）
  · FeatureHub 异常 → 自动回退原始 FE（fail-open）
  · 未设置 / false → 走原始 FE

使用方式（各策略入口，单值 DF 场景）：
    features = wrap_featurehub(
        strategy_name="btc",
        ohlcv_df=df,
        symbol="BTC",
        set_name="btc_morph_v6",
        original_fe_fn=lambda: OriginalFE().create_features(df),
    )

元组返回场景（易经 BTC：需要 features + feature_names_by_gua / gua_map）：
    features, gua_map = wrap_featurehub(
        strategy_name="yijing_btc",
        ohlcv_df=df,
        symbol="BTC",
        set_name="yijing_cycle",
        original_fe_fn=lambda: compute_all_original(df),  # 返回 (DataFrame, dict)
        return_tuple=True,
    )
"""
from __future__ import annotations

import logging
import os
from typing import Any, Callable, Dict, Optional, Tuple, Union

import pandas as pd

logger = logging.getLogger(__name__)


def _is_featurehub_enabled(strategy_name: str) -> bool:
    """检查 EN_FEATUREHUB_<STRATEGY> 环境变量。"""
    env_key = f"EN_FEATUREHUB_{strategy_name.upper()}"
    return os.environ.get(env_key, "false").lower() in {"1", "true", "on", "yes"}


def _build_pipeline():
    """构建 FeaturePipeline + 注册模块 + 集合。"""
    from feature_hub.pipeline.feature_pipeline import FeaturePipeline
    from feature_hub.modules.loader import load_default_sets

    pipe = FeaturePipeline()
    load_default_sets(pipe)
    return pipe


def _unwrap_extra_ctx(meta: Dict[str, Any]) -> Dict[str, Any]:
    """把 FeaturePipeline.meta['extra_ctx'] 拉平为策略易消费的形式。

    形式约定：
      meta['extra_ctx'] = {'bagua': {gua→[cols]}, 'cycle': {sub→[cols]}}
      → 输出：{'bagua': {...}, 'cycle': {...}, 'feature_names_by_gua': 合并版}
    合并版 = 所有 ctx dict 的 items 合并（易经策略依赖它，避免 key 重名覆盖：后入者覆盖，
            这与 FeatureRegistry.compute_all 行为一致）。
    """
    ctx_agg = meta.get("extra_ctx") or {}
    merged: Dict[str, Any] = {}
    for _mod_name, sub_ctx in ctx_agg.items():
        if isinstance(sub_ctx, dict):
            merged.update(sub_ctx)
    flat: Dict[str, Any] = {}
    flat.update(ctx_agg)
    flat["feature_names_by_gua"] = merged
    return flat


def wrap_featurehub(
    strategy_name: str,
    ohlcv_df: pd.DataFrame,
    symbol: str,
    set_name: str,
    original_fe_fn: Callable[[], Union[pd.DataFrame, Tuple[pd.DataFrame, Any]]],
    macro_df: Optional[pd.DataFrame] = None,
    ref_df: Optional[pd.DataFrame] = None,
    strip_prefix: bool = False,
    return_tuple: bool = False,
) -> Union[pd.DataFrame, Tuple[pd.DataFrame, Any]]:
    """H3 策略出口 wrapper。

    Args:
        strategy_name: 策略名（如 "btc", "alt_trend", "equity_classic", "yijing_btc"）
        ohlcv_df: OHLCV 数据
        symbol: 交易标的
        set_name: FeatureHub 启用集合名
        original_fe_fn: 原始 FE 函数（无参数，可返回 DataFrame 或 (DataFrame, extra_ctx) 元组）
        macro_df: 可选宏观数据
        ref_df: 可选参考资产数据
        strip_prefix: 是否去掉 FeaturePipeline 加的 ``<module>__`` 前缀。
            灰度接入策略时需与原始 FE 列名对齐，设 True；跨域融合场景
            保持前缀避免列名冲突，设 False（默认）。
        return_tuple: True 时返回 ``(DataFrame, extra_ctx)``；False（默认）只返回 DataFrame。
            当策略依赖 gua_map / feature_names_by_gua 这类非列上下文时，必须开启。

    Returns:
        DataFrame，或 ``(DataFrame, extra_ctx)`` 元组（由 return_tuple 决定）。
    """
    if not _is_featurehub_enabled(strategy_name):
        return original_fe_fn()

    try:
        pipe = _build_pipeline()
        fv = pipe.run(
            set_name=set_name,
            df=ohlcv_df,
            symbol=symbol,
            macro_df=macro_df,
            ref_df=ref_df,
        )
        df_out = fv.df
        if strip_prefix and not df_out.empty:
            # 去掉 "<module>__" 前缀，恢复原始 FE 列名
            # 若多模块有同名列，后者覆盖前者（按 concat 顺序）
            new_cols = {}
            for col in df_out.columns:
                sep_idx = col.find("__")
                new_name = col[sep_idx + 2:] if sep_idx >= 0 else col
                new_cols[col] = new_name
            df_out = df_out.rename(columns=new_cols)
        logger.info(
            "[H3] %s → FeatureHub ok: %d features from %s (strip_prefix=%s, tuple=%s)",
            strategy_name,
            len(df_out.columns),
            fv.meta.get("modules_run", []),
            strip_prefix,
            return_tuple,
        )
        extra_ctx = _unwrap_extra_ctx(fv.meta)
        if return_tuple:
            return df_out, extra_ctx.get("feature_names_by_gua", {})
        return df_out
    except Exception as exc:
        logger.warning(
            "[H3] %s → FeatureHub failed: %s — falling back to original FE",
            strategy_name, exc,
        )
        return original_fe_fn()

