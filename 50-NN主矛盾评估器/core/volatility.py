# 50 决策侧 SL/TP 波动率口径：Wilder ATR(%) → 价格间距（百分比）。
#
# 为什么放在 50：22 执行器 `_resolve_sl_tp` 的优先级是
#   decision.sl_pct/tp_pct > 注册表 symbols > asset_class > default，
# 因此 50 只要在决策顶层声明 sl_pct/tp_pct 即可按自身波动率覆盖固定间距，
# 22 无需改动（22 仍是唯一真实下单方）。
#
# 硬边界（22 `live_order_bridge._place_live_order`）：0 < sl_pct < 10、0 < tp_pct < 20；
# 本模块上限 SL 8 / TP 16，留安全余量，避免高波动时被 22 直接拒单。
from __future__ import annotations

from typing import Any, Iterable

ATR_PERIOD = 14
# SL = 2×ATR%：约覆盖 1.5 个持有周期的正常噪音，避免被日内扫损
SL_ATR_MULT = 2.0
# 盈亏比 1:2（与 22 注册表 asset_class 配置的 sl:tp 比例一致）
TP_SL_RATIO = 2.0
SL_CAP_PCT = 8.0
TP_CAP_PCT = 16.0

# 类别 SL 下限（%）：与 22 `config/live_symbols.json` 的 sl_tp.asset_class 对齐；
# ATR 缺失/低波动时退回该值，保证决策始终携带合法 SL/TP
_CLASS_SL_FLOOR_PCT = {
    "crypto": 3.0,
    "precious_metal": 2.5,
    "industrial_metal": 3.0,
    "energy": 3.0,
    "rates_credit": 2.0,
    "us_index": 2.0,
    "apac_index": 2.0,
    "us_etf": 2.5,
    "us_stock": 3.0,
}
_DEFAULT_SL_FLOOR_PCT = 2.5


def sl_floor_pct(asset_class: str) -> float:
    """类别 SL 下限（百分比）；未知类别回落 2.5%。"""
    return _CLASS_SL_FLOOR_PCT.get(str(asset_class or "").strip().lower(), _DEFAULT_SL_FLOOR_PCT)


def wilder_atr_pct(candles: Iterable[dict[str, Any]], period: int = ATR_PERIOD) -> float:
    """Wilder ATR / 最新收盘，返回百分比（2.0 表示 2%）。

    candles 按时间正序（旧→新），每项需含 h/l/c；样本不足 period+1 根返回 0.0。
    异常数值一律按 0.0 处理，调用方据此退回类别下限。
    """
    rows = [r for r in candles if isinstance(r, dict)]
    if len(rows) < period + 1:
        return 0.0
    try:
        highs = [float(r["h"]) for r in rows]
        lows = [float(r["l"]) for r in rows]
        closes = [float(r["c"]) for r in rows]
    except (KeyError, TypeError, ValueError):
        return 0.0
    trs: list[float] = []
    for i in range(1, len(rows)):
        trs.append(
            max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
        )
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    last = closes[-1]
    if last <= 0 or atr <= 0:
        return 0.0
    return atr / last * 100.0


def resolve_sl_tp_pct(asset_class: str, atr_pct: float) -> dict[str, Any]:
    """按类别下限 + ATR 计算决策用 SL/TP 间距（百分比）。

    - sl_pct = clamp(2×ATR%, 类别下限, 8)
    - tp_pct = clamp(max(2×类别下限, 2×sl_pct), 6~, 16)
    - atr_pct <= 0（取数失败/样本不足）时退回类别下限，source=atr_missing
    """
    floor = sl_floor_pct(asset_class)
    try:
        atr = max(0.0, float(atr_pct or 0.0))
    except (TypeError, ValueError):
        atr = 0.0
    # 防御异常值：单根 ATR% 超过 30% 视为脏数据，退回类别下限
    if atr > 30.0:
        atr = 0.0
    if atr > 0:
        sl = max(floor, SL_ATR_MULT * atr)
        source = "atr"
    else:
        sl = floor
        source = "atr_missing"
    sl = round(min(sl, SL_CAP_PCT), 2)
    tp = round(min(max(TP_SL_RATIO * floor, TP_SL_RATIO * sl), TP_CAP_PCT), 2)
    return {
        "sl_pct": sl,
        "tp_pct": tp,
        "atr_pct": round(atr, 4),
        "source": source,
        "sl_floor_pct": floor,
    }
