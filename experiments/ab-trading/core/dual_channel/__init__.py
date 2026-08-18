"""
双通道并行决策模块 (Dual-Channel Decision)

P2-8 spec 落地前置环境：左右脑并行 + 胼胝体整合 + AB 对比回测。

模块：
  - corpus_callosum:     胼胝体整合器（左右脑对比 + A7 升级）
  - dual_channel_runner: 双通道运行器（左脑 A0-A3 + 右脑 易经/做梦）
  - ab_comparison:       AB 对比框架（单通道 vs 双通道 → path_advantage）
"""
from .corpus_callosum import CorpusCallosum, IntegrationResult, ChannelResult
from .dual_channel_runner import DualChannelRunner, DualChannelDecision
from .ab_comparison import ABComparison, ABComparisonReport

__all__ = [
    "CorpusCallosum",
    "IntegrationResult",
    "ChannelResult",
    "DualChannelRunner",
    "DualChannelDecision",
    "ABComparison",
    "ABComparisonReport",
]
