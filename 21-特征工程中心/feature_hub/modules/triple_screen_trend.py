"""TripleScreen Trend 模块 — 包装 12-三屏 TrendFeatureEngineer

通过 SklearnStyleAdapter 适配，注册到 FeatureHub 后跨策略复用。

⚠️ 注意：12-三屏 TrendFeatureEngineer 依赖 10-经典指标系统的 talib shim
  （返回 pd.Series），不是系统原生 TA-Lib（返回 ndarray）。
  必须在导入 TrendFeatureEngineer 前把 10号目录**插到 sys.path[0]**，
  否则 `talib.abstract.EMA(...).pct_change()` 会抛 AttributeError。
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Optional

import pandas as pd

from feature_hub.adapters.sklearn_style_adapter import SklearnStyleAdapter


def _ensure_10_shim_path() -> None:
    """显式确保 12-三屏趋势系统 和 10-经典指标系统/talib shim 覆盖原生 talib。"""
    _root = Path(__file__).resolve().parents[3]
    _10 = str(_root / "10-经典指标系统")
    _12 = str(_root / "12-三屏趋势系统")
    # 优先：已经插过就移动到最前；没插就插最前
    for p in (_10, _12):
        if p in sys.path:
            sys.path.remove(p)
        sys.path.insert(0, p)
    # 如果 talib / talib.abstract 已经被系统版导入（缓存了），强制重新加载
    # 让后续 `from talib import abstract` 走 10号 shim。
    for mod_name in list(sys.modules.keys()):
        if mod_name == "talib" or mod_name.startswith("talib."):
            del sys.modules[mod_name]


def compute(
    df: pd.DataFrame,
    ref_df: Optional[pd.DataFrame] = None,
    macro_df: Optional[pd.DataFrame] = None,
    symbol: str = "",
) -> pd.DataFrame:
    """TripleScreen Trend 特征计算"""
    _ensure_10_shim_path()
    TrendFE = importlib.import_module("ml.feature_engineer").TrendFeatureEngineer
    adapter = SklearnStyleAdapter(TrendFE, views=None)
    return adapter.compute(df, ref_df=ref_df, macro_df=macro_df, symbol=symbol)
