"""V4+波浪趋势策略 — 独立模块

完全独立于三屏趋势系统的 V4+波浪策略模块。

核心组件：
- halving_top_exit_strategy: V4减半周期逃顶策略（定方向）
- ewave_recognizer: 艾略特波浪识别器
- ewave_strategy_adapter: 波浪策略适配器（互斥融合）
- v4_wave_engine: 主引擎（统一入口）

物理引擎从 12-三屏趋势系统 导入（保持原位置）。
"""

from .halving_top_exit_strategy import HalvingTopExitStrategy, BTC_HALVING_DATES
from .ewave_recognizer import ElliottWaveRecognizer, WavePoint, WaveStructure, WAVE_SIGNALS
from .ewave_strategy_adapter import EWaveStrategyAdapter, WaveConfig
from .v4_wave_engine import compute_v4_wave_signal, V4WaveEngine

__all__ = [
    "HalvingTopExitStrategy",
    "BTC_HALVING_DATES",
    "ElliottWaveRecognizer",
    "WavePoint",
    "WaveStructure",
    "WAVE_SIGNALS",
    "EWaveStrategyAdapter",
    "WaveConfig",
    "compute_v4_wave_signal",
    "V4WaveEngine",
]
