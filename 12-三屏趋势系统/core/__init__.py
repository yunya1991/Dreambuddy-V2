"""三屏趋势系统 — 核心算法包"""

try:
    from .composite_predictor import (
        CompositePredictor,
        create_composite_predictor,
        predict_from_dataframes,
    )
    from .config import (
        BASE_STOP_LOSS_PCT,
        BASE_TAKE_PROFIT_PCT,
        BTC_DIVERGENCE_ADDON_PCT,
        BTC_WIND_VANE_BREAK_DAYS,
        BTC_WIND_VANE_DAILY_MA,
        BTC_WIND_VANE_ENABLED,
        BTC_WIND_VANE_WEEKLY_MA,
        CANDIDATE_COINS,
        DAILY_WEIGHT,
        MARGIN_MODE,
        MAX_ADDON_COUNT,
        MAX_ADDON_POSITION_PCT,
        MAX_LEVERAGE,
        MAX_POSITION_PCT,
        RISK_REWARD_THRESHOLD,
        SCREEN1_INDICATORS,
        SCREEN2_INDICATORS,
        TREND_STRENGTH_ADDON_THRESHOLD,
        WEEKLY_WEIGHT,
    )
    from .dynamic_weights import (
        calc_bayesian_confidence,
        calc_dynamic_weights,
        calc_indicator_performance,
    )
    from .fusion import (
        fuse_technical_fundamental,
    )
    from .indicators import (
        calc_classic_indicator_confidence,
        calc_indicator_dynamics,
        calc_indicator_signal,
        calc_trend_direction_static,
    )
    from .least_resistance import (
        calc_fundamental_resistance,
        calc_momentum_resistance,
        calc_price_resistance,
        calc_trend_resistance,
        calc_volume_resistance,
        compute_least_resistance,
    )
    from .risk_reward import (
        calc_30d_volatility,
        calc_elder_ray,
        calc_position_sizing,
        calc_risk_reward_ratio,
        evaluate_addon_opportunity,
        get_vol_adjusted_params,
    )
    from .trend_consistency import (
        calc_trend_consistency,
        calc_trend_direction_dynamic,
    )
except ImportError:
    from composite_predictor import (
        CompositePredictor,
        create_composite_predictor,
        predict_from_dataframes,
    )
    from config import (
        BASE_STOP_LOSS_PCT,
        BASE_TAKE_PROFIT_PCT,
        BTC_DIVERGENCE_ADDON_PCT,
        BTC_WIND_VANE_BREAK_DAYS,
        BTC_WIND_VANE_DAILY_MA,
        BTC_WIND_VANE_ENABLED,
        BTC_WIND_VANE_WEEKLY_MA,
        CANDIDATE_COINS,
        DAILY_WEIGHT,
        MARGIN_MODE,
        MAX_ADDON_COUNT,
        MAX_ADDON_POSITION_PCT,
        MAX_LEVERAGE,
        MAX_POSITION_PCT,
        RISK_REWARD_THRESHOLD,
        SCREEN1_INDICATORS,
        SCREEN2_INDICATORS,
        TREND_STRENGTH_ADDON_THRESHOLD,
        WEEKLY_WEIGHT,
    )
    from dynamic_weights import (
        calc_bayesian_confidence,
        calc_dynamic_weights,
        calc_indicator_performance,
    )
    from fusion import (
        fuse_technical_fundamental,
    )
    from indicators import (
        calc_classic_indicator_confidence,
        calc_indicator_dynamics,
        calc_indicator_signal,
        calc_trend_direction_static,
    )
    from least_resistance import (
        calc_fundamental_resistance,
        calc_momentum_resistance,
        calc_price_resistance,
        calc_trend_resistance,
        calc_volume_resistance,
        compute_least_resistance,
    )
    from risk_reward import (
        calc_30d_volatility,
        calc_elder_ray,
        calc_position_sizing,
        calc_risk_reward_ratio,
        evaluate_addon_opportunity,
        get_vol_adjusted_params,
    )
    from trend_consistency import (
        calc_trend_consistency,
        calc_trend_direction_dynamic,
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
    "CompositePredictor",
    "create_composite_predictor",
    "predict_from_dataframes",
    "compute_least_resistance",
    "calc_price_resistance",
    "calc_volume_resistance",
    "calc_momentum_resistance",
    "calc_trend_resistance",
    "calc_fundamental_resistance",
]
