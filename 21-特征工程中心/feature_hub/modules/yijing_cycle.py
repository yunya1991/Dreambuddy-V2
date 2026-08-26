"""易经八卦 + 周期 + WDH 模块 — FeatureHub Native 模块。

设计目标：
1. 复现 FeatureRegistry.compute_all 在 bagua / cycle / wdh 三个模块上的输出；
2. compute(df, ...) 返回 (features_df, feature_names_by_gua) 元组，
   H3 wrapper 通过 return_tuple=True 解包为（特征列，八卦字典）；
3. fail-open：任一子模块 import / compute 失败时该子块跳过，不影响其余。

注：
- bagua 为 BCRM2 核心模块，uses_instance_gua_map=True，八卦卦名字典来自
  实例属性 feature_names_by_gua（8 卦：qian/kun/zhen/xun/kan/li/gen/dui）。
- cycle 使用 _cycle_sub_key_splitter，拆分 4 组（halving/ath/inventory/long_term）。
- wdh 使用 _wdh_sub_key_splitter，拆分 4 组（weekly_accum/daily_confirm/
  hourly_timing/qual_trigger）。
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# BCRM2 shim 路径（保证 FeatureRegistry 反导出、bcrm2.* 原生导入两条路径都有效）
_BCRM2_ROOTS: List[Path] = []
for _p in (
    Path(__file__).resolve().parents[3] / "11-易经推理系统",
    Path(__file__).resolve().parents[3] / "11-易经推理系统" / "scripts" / "memory_l4",
):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
    _BCRM2_ROOTS.append(_p)


# ============================================================
# 模块计算的封装 — 对 3 个子模块逐一 import + compute + 提取 gua_map
# ============================================================
def _trigger_module_imports() -> None:
    """触发 bcrm2 侧各特征模块的 FeatureRegistry.register 副作用。

    易经 BTC 训练/推理依赖 bagua + cycle，其余模块按需导入即可（不强制）。
    """
    try:
        import scripts.memory_l4.bcrm2.bagua_feature_engine  # noqa: F401
    except Exception as exc:  # pragma: no cover - fail-open
        logger.warning("[yijing_cycle] bagua import failed: %s", exc)
    try:
        import scripts.memory_l4.bcrm2.cycle_features  # noqa: F401
    except Exception as exc:  # pragma: no cover - fail-open
        logger.warning("[yijing_cycle] cycle import failed: %s", exc)
    try:
        import scripts.memory_l4.bcrm2.wdh_features  # noqa: F401
    except Exception as exc:  # pragma: no cover - fail-open
        logger.warning("[yijing_cycle] wdh import failed: %s", exc)


def _compute_via_fr(
    df: pd.DataFrame,
    ref_df: Optional[pd.DataFrame],
    macro_df: Optional[pd.DataFrame],
    symbol: str,
    enabled: List[str],
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[pd.DataFrame, Dict[str, List[str]]]:
    """走 FeatureRegistry.compute_all，保证跟 bcrm2_adapter 训练侧完全一致。

    这是最稳的实现：直接调用单一真相源，避免 bagua.compute() 之后
    ``instance.feature_names_by_gua`` 缺失、cycle config 不一致等问题。
    """
    from feature_hub.hub.feature_registry import FeatureRegistry

    features, gua_map = FeatureRegistry.compute_all(
        df=df,
        ref_df=ref_df,
        macro_df=macro_df,
        symbol=symbol,
        config=config or {},
        enabled=enabled,
    )
    return features, gua_map


def compute(
    df: pd.DataFrame,
    ref_df: Optional[pd.DataFrame] = None,
    macro_df: Optional[pd.DataFrame] = None,
    symbol: str = "BTC",
    config: Optional[Dict[str, Any]] = None,
    enabled: Optional[List[str]] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """FeatureHub 模块入口 — 返回 (features_df, feature_names_by_gua)。

    默认启用 ``["bagua", "cycle"]``（易经 BTC 训练常用最小集合）。
    如需 wdh 可通过 enabled=["bagua", "cycle", "wdh"] 或集合配置切换。
    """
    _trigger_module_imports()
    if enabled is None:
        enabled = ["bagua", "cycle"]
    try:
        features, gua_map = _compute_via_fr(
            df=df, ref_df=ref_df, macro_df=macro_df,
            symbol=symbol, enabled=enabled, config=config,
        )
    except Exception as exc:
        logger.warning("[yijing_cycle] compute_all failed (%s) — returning empty frame", exc)
        return pd.DataFrame(index=df.index), {}

    # 与 FR 原版一样做最终防御（bagua 实例内部已经 ffill().fillna(0) 一次，
    # 这里对 concat 后的大表再做一次，避免子模块间 NaN 位置不一致）
    if len(features.columns) == 0:
        return features, {}
    features = features.ffill().fillna(0)
    features = features.replace([np.inf, -np.inf], 0)
    return features, gua_map
