"""三屏趋势系统 — 核心算法包"""

try:
    from .config import (
        CANDIDATE_COINS,
        SCREEN1_INDICATORS,
        SCREEN2_INDICATORS,
        WEEKLY_WEIGHT,
        DAILY_WEIGHT,
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
except ImportError:
    from config import (
        CANDIDATE_COINS,
        SCREEN1_INDICATORS,
        SCREEN2_INDICATORS,
        WEEKLY_WEIGHT,
        DAILY_WEIGHT,
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

__all__ = [
    "CANDIDATE_COINS",
    "SCREEN1_INDICATORS",
    "SCREEN2_INDICATORS",
    "WEEKLY_WEIGHT",
    "DAILY_WEIGHT",
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
]
