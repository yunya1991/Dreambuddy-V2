"""
DreamOS 入场策略能力层（Entry Strategy）
=========================================

完全对齐 exit_strategy 的 3 文件架构：
    - entry_module_adapter.py    6 个入场子能力统一封装（scenario_ema/a2_fusion/c2_momentum/s3_trend/yj_infer/martin_v15）
    - entry_module_backtester.py 36 场景 × 入场模块回测评估（出场统一 builtin ATR，避免出场差异污染入场打分）
    - entry_module_selector.py   三级降级 + LOW/CHOP/RANGE 场景强降级

持久化（与 exit_performance_memory.json 同目录）：
    dreamos/core/memory/entry_performance_memory.json
"""

from .entry_module_adapter import (
    UnifiedEntryDecision,
    BaseEntryAdapter,
    ScenarioEmaAdapter,
    A2FusionAdapter,
    C2MomentumAdapter,
    S3TrendAdapter,
    YJInferAdapter,
    MartinV15Adapter,
    get_all_entry_modules,
    create_entry_adapter,
)

from .entry_module_selector import EntryModuleSelector, EntryModuleChoice

from .entry_module_backtester import EntryModuleBacktester

__all__ = [
    # 统一结构
    "UnifiedEntryDecision", "BaseEntryAdapter", "EntryModuleChoice",
    # 适配器
    "ScenarioEmaAdapter", "A2FusionAdapter", "C2MomentumAdapter",
    "S3TrendAdapter", "YJInferAdapter", "MartinV15Adapter",
    "get_all_entry_modules", "create_entry_adapter",
    # 选择器 / 回测器
    "EntryModuleSelector", "EntryModuleBacktester",
]
