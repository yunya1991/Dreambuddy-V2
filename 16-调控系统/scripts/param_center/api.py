"""P0 T3: 参数中心对外只读 API

SPEC §3.1 接口契约：
    get_sltp_params(symbol, market_regime, use_cache) -> SLTPParams

子系统通过此 API 查询参数中心，零延迟附单 OKX。
"""
from __future__ import annotations

from memory_l4.bcrm2.sl_tp_config import SLTPParams

from .repository import get_repository


def get_sltp_params(
    symbol: str,
    market_regime: str = "chop",
    use_cache: bool = True,
) -> SLTPParams:
    """子系统查询参数中心，获取 SL/TP 参数。

    Args:
        symbol: 交易对（如 "BTC", "PEPE"）
        market_regime: 当前市场形态（bull/chop/bear），默认 chop
        use_cache: 是否使用本地缓存（5min TTL，默认 True）

    Returns:
        SLTPParams: sl_floor, tp_floor, atr_mult_range, rr_ratio_target,
                    tp_decay_floor, tp_decay_hours

    FAIL-OPEN:
        - 参数中心不可用 → 返回 _DEFAULT_PARAMS (SL=4%, TP=12%)
        - 资产未分类 → 走 _DEFAULT_PARAMS（由 classify_asset 兜底）
        - regime 未知 → 按 chop 处理
    """
    repo = get_repository()
    return repo.get(symbol, market_regime=market_regime, use_cache=use_cache)
