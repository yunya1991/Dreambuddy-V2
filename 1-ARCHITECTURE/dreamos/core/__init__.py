"""
Dreambuddy OS — Core 四大核心层

SACG 架构:
    S层 Sense      — 感知/意图识别
    A层 Arrange    — 图编排
    C层 Compute    — 执行
    G层 GraphStore — 图存储

数据流:
    输入 → [S层] → IntentResult
                   ↓
              [A层] → Graph (执行图)
                       ↓
                  [C层] → 执行 → State 更新
                               ↓
                          [G层] → 持久化/压缩/回放
"""

# 各层入口（P1-P4 阶段填充真实实现）
from . import sense, arrange, compute, graph_store, capability

__all__ = ["sense", "arrange", "compute", "graph_store", "capability"]
