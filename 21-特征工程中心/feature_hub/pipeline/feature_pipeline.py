"""FeaturePipeline — 按 ENABLED_SETS 编排 → 串清洗链 → FeatureVector

支持双入口模块：
  1. 本地注册模块（register_module）→ 直接调用 compute(df, **kw)
  2. FR 注册模块 → 通过 FeatureRegistry.compute_all 调用

L1 fail-open：某模块异常 → 跳过 + log.warning + 其他模块照常
L3 Fail-Fast：启用集合名不存在 → FeatureSetNotFound
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

from feature_hub.cleaning_chain.standard_chain import StandardCleaningChain
from feature_hub.contract import FeatureVector
from feature_hub.errors import FeatureSetNotFound

logger = logging.getLogger(__name__)


class FeaturePipeline:
    """特征编排管道"""

    def __init__(self) -> None:
        self._modules: Dict[str, Callable[..., pd.DataFrame]] = {}
        self._sets: Dict[str, List[str]] = {}
        self._cleaning_chain = StandardCleaningChain()

    def register_module(self, name: str, compute_fn: Callable[..., pd.DataFrame]) -> None:
        """注册本地模块"""
        self._modules[name] = compute_fn

    def register_set(self, set_name: str, modules: List[str]) -> None:
        """注册启用集合"""
        self._sets[set_name] = modules

    def run(
        self,
        set_name: str,
        df: pd.DataFrame,
        symbol: str = "",
        ref_df: Optional[pd.DataFrame] = None,
        macro_df: Optional[pd.DataFrame] = None,
        y: Optional[Any] = None,
    ) -> FeatureVector:
        """执行特征编排

        Args:
            set_name: 启用集合名
            df: OHLCV 数据
            symbol: 交易标的
            ref_df: 参考资产数据
            macro_df: 宏观数据
            y: 标签（可选，用于 IV 筛选）

        Returns:
            FeatureVector
        """
        # 1) 查找启用集合
        if set_name not in self._sets:
            # 也检查 FR 的 ENABLED_SETS
            try:
                from feature_hub.hub.feature_registry import ENABLED_SETS
                if set_name in ENABLED_SETS:
                    modules = ENABLED_SETS[set_name]
                    if modules is None:
                        modules = list(self._modules.keys())
                else:
                    raise FeatureSetNotFound(set_name)
            except ImportError:
                raise FeatureSetNotFound(set_name) from None
        else:
            modules = self._sets[set_name]

        if modules is None:
            modules = list(self._modules.keys())

        # 2) 逐模块计算
        features = pd.DataFrame(index=df.index)
        meta: Dict[str, Any] = {"set_name": set_name, "modules_run": []}
        # 模块级 extra_ctx 聚合：{mod_name: ctx_dict}，易经用 bagua.feature_names_by_gua + cycle 等
        extra_ctx_agg: Dict[str, Any] = {}

        for mod_name in modules:
            try:
                if mod_name in self._modules:
                    # 本地模块 — compute 支持 (df, **kw) 或返回 (df, ctx_dict) 元组
                    raw = self._modules[mod_name](
                        df, ref_df=ref_df, macro_df=macro_df, symbol=symbol,
                    )
                else:
                    # FR 注册模块：compute_all 返回 (df, gua_map) 元组
                    from feature_hub.hub.feature_registry import FeatureRegistry
                    raw = FeatureRegistry.compute_all(
                        df=df, ref_df=ref_df, macro_df=macro_df,
                        symbol=symbol, enabled=[mod_name],
                    )

                # 兼容：模块可返回 DataFrame 或 (DataFrame, extra_ctx_dict) 元组
                extra_ctx: Dict[str, Any] = {}
                if isinstance(raw, tuple):
                    if len(raw) == 0:
                        feats = None
                    elif len(raw) == 1:
                        feats = raw[0]
                    else:
                        feats, extra_ctx = raw[0], raw[1]
                else:
                    feats = raw

                if feats is not None and len(feats.columns) > 0:
                    # 加模块名前缀避免列名冲突
                    prefixed = feats.add_prefix(f"{mod_name}__")
                    features = pd.concat([features, prefixed], axis=1)
                    meta["modules_run"].append(mod_name)
                    if extra_ctx:
                        extra_ctx_agg[mod_name] = extra_ctx
            except Exception as exc:
                logger.warning(
                    "[FeatureHub] module '%s' failed: %s — skipping (fail-open)",
                    mod_name, exc,
                )
                meta.setdefault("modules_failed", []).append(mod_name)

        # 3) 清洗链
        cleaned = self._cleaning_chain.fit_transform(features, y=y)

        # 4) 返回 FeatureVector（extra_ctx 放进 meta 便于 H3 wrapper / 上层消费）
        meta["feature_count"] = len(cleaned.columns)
        if extra_ctx_agg:
            meta["extra_ctx"] = extra_ctx_agg
        return FeatureVector(df=cleaned, meta=meta)
