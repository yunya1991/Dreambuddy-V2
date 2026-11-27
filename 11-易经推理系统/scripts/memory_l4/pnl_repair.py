"""P0.5 零 pnl 记账修复（SPEC-20261127-winrate-diagnosis-optimization §17.3）。

症状：trades 表 11 笔 pnl_pct=0，但 entry_price/exit_price 已有真实变动
（最大 XAU -4.31%），bdsm 分钟级强平也全记 0。
原因：多条平仓路径把 pos_info["upl_ratio"] 直接当 pnl_pct，而该值在
OKX 回退/影子成交等路径上可能为 0。

策略：写库前用「开仓价 + 平仓价 + 方向」重算。仅在「记录值恰为 0 且价格确实变动」
时才修正；真实打平（价格未变）保持 0，已有非零值不被覆盖。纯函数便于测试。
"""

from __future__ import annotations


def repair_close_pnl(
    *,
    entry_price: float,
    exit_price: float,
    direction: str,
    pnl: float,
    pnl_pct: float,
    position_usdt: float = 0.0,
    eps: float = 1e-12,
) -> tuple[float, float, bool]:
    """返回 (pnl, pnl_pct, repaired)。任何缺价/已有非零值都原样返回。"""
    if entry_price <= 0 or exit_price <= 0:
        return pnl, pnl_pct, False
    sign = -1.0 if str(direction).lower() in {"short", "-1", "sell"} else 1.0
    expected = sign * (exit_price - entry_price) / entry_price
    if abs(expected) <= eps:  # 价格未变 → 真实打平，不修
        return pnl, pnl_pct, False
    if abs(pnl_pct) > eps:  # 已有非零记录 → 信任原值，不覆盖
        return pnl, pnl_pct, False
    new_pnl = pnl
    if abs(pnl) <= eps and position_usdt > 0:
        new_pnl = position_usdt * expected
    return new_pnl, expected, True
