"""三维分类 SL/TP 参数配置表

维度：(asset_class, market_cap_tier, market_regime) → SL/TP 参数

参数说明：
  sl_floor        SL 下限（百分比，如 0.04 = 4%）
  tp_floor        TP 下限（百分比，如 0.12 = 12%）
  atr_mult_range  ATR 倍数范围 (min, max)
  rr_ratio_target 盈亏比目标（TP/SL）
  tp_decay_floor  TP 衰减下限（不低于 tp_floor）
  tp_decay_hours  TP 衰减时间参数（grace_hours, full_hours）

设计原则：
  - 大市值波动率低 → 紧 SL/TP；小市值波动率高 → 宽 SL/TP
  - 美股波动率接近美股 → 更紧的 SL/TP
  - 牛市 → 宽 TP 紧 SL（让利润奔跑）
  - 熊市 → 收紧止损（sl_mult=0.85）+ 降仓（position_mult=0.5），RR不恶化
  - 震荡 → 均衡

约束：sl_floor ≥ 0.03, tp_floor ≥ 0.12, tp_floor / sl_floor ≥ 2.0
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Tuple

from .asset_classifier import (
    ASSET_CRYPTO_LARGE, ASSET_CRYPTO_MAJOR, ASSET_CRYPTO_MID,
    ASSET_CRYPTO_MEME, ASSET_CRYPTO_SMALL, ASSET_PRECIOUS_METAL,
    ASSET_US_STOCK, MCAP_LARGE, MCAP_MID, MCAP_SMALL, MCAP_TRADFI,
)
from .market_regime_gateway import REGIME_BEAR, REGIME_BULL, REGIME_CHOP


@dataclass
class SLTPParams:
    """单组 SL/TP 参数"""
    sl_floor: float = 0.04
    tp_floor: float = 0.12
    atr_mult_range: Tuple[float, float] = (4.0, 6.0)
    rr_ratio_target: float = 3.0
    tp_decay_floor: float = 0.12
    tp_decay_hours: Tuple[int, int] = (12, 72)  # (grace_hours, full_hours)
    position_mult: float = 1.0  # 市场形态仓位乘数（熊市=0.5）

    def validate(self) -> bool:
        """校验参数是否满足硬约束"""
        if self.sl_floor < 0.03:
            return False
        if self.tp_floor < 0.12:
            return False
        if self.tp_floor / self.sl_floor < 2.0:
            return False
        if self.tp_decay_floor < self.tp_floor:
            return False
        return True


# ============================================================================
# 基础参数表（按资产类别 × 市值等级，不含市场形态调整）
# ============================================================================
_BASE_PARAMS: Dict[Tuple[str, str], SLTPParams] = {
    # 美股代币（ATR约0.8-1.2%，SL=3%对应2.5-3.75x ATR）
    (ASSET_US_STOCK, MCAP_TRADFI): SLTPParams(
        sl_floor=0.03, tp_floor=0.12, atr_mult_range=(2.5, 4.0),
        rr_ratio_target=4.0, tp_decay_floor=0.12, tp_decay_hours=(8, 48),
    ),
    # 贵金属（ATR约0.8-1.2%，SL=3%对应2.5-3.75x ATR）
    (ASSET_PRECIOUS_METAL, MCAP_TRADFI): SLTPParams(
        sl_floor=0.03, tp_floor=0.12, atr_mult_range=(2.5, 4.0),
        rr_ratio_target=4.0, tp_decay_floor=0.12, tp_decay_hours=(12, 72),
    ),
    # BTC/ETH（大市值，趋势明确，ATR约2-3%，SL=5%对应2-2.5x ATR）
    (ASSET_CRYPTO_MAJOR, MCAP_LARGE): SLTPParams(
        sl_floor=0.05, tp_floor=0.12, atr_mult_range=(3.5, 5.0),
        rr_ratio_target=2.4, tp_decay_floor=0.12, tp_decay_hours=(12, 72),
    ),
    # 大市值加密
    (ASSET_CRYPTO_LARGE, MCAP_LARGE): SLTPParams(
        sl_floor=0.05, tp_floor=0.15, atr_mult_range=(4.0, 5.5),
        rr_ratio_target=3.0, tp_decay_floor=0.15, tp_decay_hours=(12, 72),
    ),
    # 中市值加密
    (ASSET_CRYPTO_MID, MCAP_MID): SLTPParams(
        sl_floor=0.06, tp_floor=0.18, atr_mult_range=(4.5, 6.0),
        rr_ratio_target=3.0, tp_decay_floor=0.18, tp_decay_hours=(12, 72),
    ),
    # 小市值加密
    (ASSET_CRYPTO_SMALL, MCAP_SMALL): SLTPParams(
        sl_floor=0.08, tp_floor=0.24, atr_mult_range=(5.0, 6.0),
        rr_ratio_target=3.0, tp_decay_floor=0.24, tp_decay_hours=(24, 96),
    ),
    # Meme 币（高波动）
    (ASSET_CRYPTO_MEME, MCAP_SMALL): SLTPParams(
        sl_floor=0.10, tp_floor=0.30, atr_mult_range=(5.0, 6.0),
        rr_ratio_target=3.0, tp_decay_floor=0.30, tp_decay_hours=(24, 96),
    ),
}

# 兜底参数（未知资产类别/市值等级）
_DEFAULT_PARAMS = SLTPParams(
    sl_floor=0.03, tp_floor=0.12, atr_mult_range=(4.0, 6.0),
    rr_ratio_target=3.0, tp_decay_floor=0.12, tp_decay_hours=(12, 72),
)


# ============================================================================
# 市场形态调整系数
# ============================================================================
_REGIME_ADJUST = {
    REGIME_BULL: {"sl_mult": 0.8, "tp_mult": 1.2},   # 牛市：紧 SL 宽 TP
    REGIME_CHOP: {"sl_mult": 1.0, "tp_mult": 1.0},   # 震荡：不变
    REGIME_BEAR: {"sl_mult": 0.85, "tp_mult": 1.0, "position_mult": 0.5},   # 熊市：收紧止损+降仓，RR不恶化
}


def get_sltp_params(
    asset_class: str,
    market_cap_tier: str,
    market_regime: str = REGIME_CHOP,
) -> SLTPParams:
    """获取三维分类 SL/TP 参数。

    Args:
        asset_class: 资产类别
        market_cap_tier: 市值等级
        market_regime: 市场形态（默认震荡）

    Returns:
        SLTPParams（已应用市场形态调整）
    """
    base = _BASE_PARAMS.get((asset_class, market_cap_tier), _DEFAULT_PARAMS)

    # 应用市场形态调整
    adjust = _REGIME_ADJUST.get(market_regime, _REGIME_ADJUST[REGIME_CHOP])
    sl_floor = max(0.03, base.sl_floor * adjust["sl_mult"])
    tp_floor = max(0.12, base.tp_floor * adjust["tp_mult"])

    # 确保盈亏比 ≥ 2:1
    if tp_floor / sl_floor < 2.0:
        tp_floor = sl_floor * 2.0

    return SLTPParams(
        sl_floor=round(sl_floor, 4),
        tp_floor=round(tp_floor, 4),
        atr_mult_range=base.atr_mult_range,
        rr_ratio_target=base.rr_ratio_target,
        tp_decay_floor=round(max(tp_floor, base.tp_decay_floor * adjust["tp_mult"]), 4),
        tp_decay_hours=base.tp_decay_hours,
        position_mult=adjust.get("position_mult", 1.0),
    )


def validate_all_params() -> Dict[str, bool]:
    """校验所有参数组合是否满足硬约束。返回 {组合: 是否合规}"""
    result = {}
    for (ac, mc), base in _BASE_PARAMS.items():
        for regime in (REGIME_BULL, REGIME_CHOP, REGIME_BEAR):
            params = get_sltp_params(ac, mc, regime)
            key = f"{ac}/{mc}/{regime}"
            result[key] = params.validate()
    return result


if __name__ == "__main__":
    # 打印所有参数组合并校验
    print("=== 三维分类 SL/TP 参数表 ===\n")
    all_valid = True
    for (ac, mc) in _BASE_PARAMS:
        for regime in (REGIME_BULL, REGIME_CHOP, REGIME_BEAR):
            p = get_sltp_params(ac, mc, regime)
            valid = p.validate()
            all_valid = all_valid and valid
            print(
                f"{ac:18s}/{mc:8s}/{regime:5s} | "
                f"SL={p.sl_floor*100:5.1f}% TP={p.tp_floor*100:5.1f}% "
                f"RR={p.tp_floor/p.sl_floor:.1f}:1 "
                f"ATR={p.atr_mult_range[0]:.1f}-{p.atr_mult_range[1]:.1f}x "
                f"{'✓' if valid else '✗'}"
            )
    print(f"\n{'所有参数合规' if all_valid else '存在不合规参数！'}")
