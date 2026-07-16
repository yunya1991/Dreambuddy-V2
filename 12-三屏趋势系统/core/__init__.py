"""三屏趋势系统 — 核心算法包"""

try:
    from .config import (
        CANDIDATE_COINS,
        SCREEN1_INDICATORS,
        SCREEN2_INDICATORS,
        WEEKLY_WEIGHT,
        DAILY_WEIGHT,
        MARGIN_MODE,
        MAX_LEVERAGE,
        MAX_POSITION_PCT,
        MAX_ADDON_POSITION_PCT,
        BTC_DIVERGENCE_ADDON_PCT,
        BASE_TAKE_PROFIT_PCT,
        BASE_STOP_LOSS_PCT,
        RISK_REWARD_THRESHOLD,
        TREND_STRENGTH_ADDON_THRESHOLD,
        MAX_ADDON_COUNT,
        BTC_WIND_VANE_DAILY_MA,
        BTC_WIND_VANE_WEEKLY_MA,
        BTC_WIND_VANE_BREAK_DAYS,
        BTC_WIND_VANE_ENABLED,
    )
    from .indicators import (
        calc_indicator_dynamics,
        calc_indicator_signal,
        calc_trend_direction_static,
        calc_classic_indicator_confidence,
    )
    from .trend_consistency import (
        calc_trend_direction_dynamic,
        calc_trend_consistency,
    )
    from .dynamic_weights import (
        calc_indicator_performance,
        calc_dynamic_weights,
        calc_bayesian_confidence,
    )
    from .fusion import (
        fuse_technical_fundamental,
    )
    from .risk_reward import (
        calc_elder_ray,
        calc_30d_volatility,
        get_vol_adjusted_params,
        calc_risk_reward_ratio,
        evaluate_addon_opportunity,
        calc_position_sizing,
    )
except ImportError:
    from config import (
        CANDIDATE_COINS,
        SCREEN1_INDICATORS,
        SCREEN2_INDICATORS,
        WEEKLY_WEIGHT,
        DAILY_WEIGHT,
        MARGIN_MODE,
        MAX_LEVERAGE,
        MAX_POSITION_PCT,
        MAX_ADDON_POSITION_PCT,
        BTC_DIVERGENCE_ADDON_PCT,
        BASE_TAKE_PROFIT_PCT,
        BASE_STOP_LOSS_PCT,
        RISK_REWARD_THRESHOLD,
        TREND_STRENGTH_ADDON_THRESHOLD,
        MAX_ADDON_COUNT,
        BTC_WIND_VANE_DAILY_MA,
        BTC_WIND_VANE_WEEKLY_MA,
        BTC_WIND_VANE_BREAK_DAYS,
        BTC_WIND_VANE_ENABLED,
    )
    from indicators import (
        calc_indicator_dynamics,
        calc_indicator_signal,
        calc_trend_direction_static,
        calc_classic_indicator_confidence,
    )
    from trend_consistency import (
        calc_trend_direction_dynamic,
        calc_trend_consistency,
    )
    from dynamic_weights import (
        calc_indicator_performance,
        calc_dynamic_weights,
        calc_bayesian_confidence,
    )
    from fusion import (
        fuse_technical_fundamental,
    )
    from risk_reward import (
        calc_elder_ray,
        calc_30d_volatility,
        get_vol_adjusted_params,
        calc_risk_reward_ratio,
        evaluate_addon_opportunity,
        calc_position_sizing,
    )

__all__ = [
    "CANDIDATE_COINS",
    "SCREEN1_INDICATORS",
    "SCREEN2_INDICATORS",
    "WEEKLY_WEIGHT",
    "DAILY_WEIGHT",
    "MARGIN_MODE",
    "MAX_LEVERAGE",
    "MAX_POSITION_PCT",
    "MAX_ADDON_POSITION_PCT",
    "BTC_DIVERGENCE_ADDON_PCT",
    "BASE_TAKE_PROFIT_PCT",
    "BASE_STOP_LOSS_PCT",
    "RISK_REWARD_THRESHOLD",
    "TREND_STRENGTH_ADDON_THRESHOLD",
    "MAX_ADDON_COUNT",
    "BTC_WIND_VANE_DAILY_MA",
    "BTC_WIND_VANE_WEEKLY_MA",
    "BTC_WIND_VANE_BREAK_DAYS",
    "BTC_WIND_VANE_ENABLED",
    "calc_indicator_dynamics",
    "calc_indicator_signal",
    "calc_trend_direction_static",
    "calc_classic_indicator_confidence",
    "calc_trend_direction_dynamic",
    "calc_trend_consistency",
    "calc_indicator_performance",
    "calc_dynamic_weights",
    "calc_bayesian_confidence",
    "fuse_technical_fundamental",
    "calc_elder_ray",
    "calc_30d_volatility",
    "get_vol_adjusted_params",
    "calc_risk_reward_ratio",
    "evaluate_addon_opportunity",
    "calc_position_sizing",
]
