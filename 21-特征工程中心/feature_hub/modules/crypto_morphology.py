"""CryptoMorphology — BTC形态学4模块 Native 注册

将易经原4模块（morphology_core + ma200_cycle + multi_timeframe + rolling_regime_stats）
封装为 FeatureHub Native 模块，通过 FR.compute_all 委托调用。

输出列数 ≈ 44（11+10+6+17），满足 btc_morph_v6 集合 shape ≥ 40 要求。
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# 易经 bcrm2 路径
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_BCRM2_ROOT = _PROJECT_ROOT / "11-易经推理系统" / "scripts" / "memory_l4"
if str(_BCRM2_ROOT) not in sys.path:
    sys.path.insert(0, str(_BCRM2_ROOT))

# 启用集合对应的4模块
_MODULES = ["morphology_core", "ma200_cycle", "multi_timeframe", "rolling_regime_stats"]

_FR_LOADED = False


def _ensure_fr_modules():
    """导入注册文件，确保4模块已在 FR 中注册"""
    global _FR_LOADED
    if _FR_LOADED:
        return
    import importlib
    for mod in (
        "bcrm2.classic_experience_features",
        "bcrm2.ma200_cycle_features",
        "bcrm2.multi_timeframe_features",
        "bcrm2.rolling_regime_stats",
    ):
        try:
            importlib.import_module(mod)
        except Exception as exc:
            logger.warning("[FeatureHub] FR module import failed: %s — %s", mod, exc)
    _FR_LOADED = True


def compute(
    df: pd.DataFrame,
    ref_df: Optional[pd.DataFrame] = None,
    macro_df: Optional[pd.DataFrame] = None,
    symbol: str = "BTC",
) -> pd.DataFrame:
    """计算 BTC 形态学4模块特征"""
    _ensure_fr_modules()
    from feature_hub.hub.feature_registry import FeatureRegistry

    feats, _ = FeatureRegistry.compute_all(
        df=df, ref_df=ref_df, macro_df=macro_df,
        symbol=symbol, enabled=_MODULES,
    )
    return feats
