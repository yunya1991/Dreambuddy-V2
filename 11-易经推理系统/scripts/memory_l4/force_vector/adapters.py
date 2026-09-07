"""力向量适配层 —— 复用 9-基本面 引擎输出。

将 compute_resistance_3d() / SignalEngine 的输出转换为 ForceVector 核心字段。

关键适配点：
  1. compute_resistance_3d() 返回的 direction 是字符串("up"/"down"/"neutral")，
     而 direction_score 是 float [-1,1]。ForceVector.direction 需要 float，
     因此用 direction_score 映射。
  2. SignalEngine._bayesian_confidence() 需 predictions>=10 才生效；
     _adaptive_weight() 需 predictions>=5 才生效。适配层 FAIL-OPEN 调用。
"""
from __future__ import annotations

import os as _os
import sys as _sys

# ============================================================
# 注入「9-基本面分析」到 sys.path（engines.* 导入前置）
#   定位方式：本文件(force_vector/adapters.py) 上溯 4 层到项目根(dreambuddy-v2)，
#   再拼「9-基本面分析」子目录。Fail-Open：目录不存在或已在 path → 静默跳过。
# ============================================================
try:  # noqa: E402
    _HERE = _os.path.dirname(_os.path.abspath(__file__))          # force_vector
    _SCRIPTS = _os.path.dirname(_HERE)                            # scripts
    _YIJING = _os.path.dirname(_SCRIPTS)                         # 11-易经推理系统
    _ROOT = _os.path.dirname(_YIJING)                             # dreambuddy-v2
    _9_FUND_PATH = _os.path.join(_ROOT, "9-基本面分析")
    if _os.path.isdir(_9_FUND_PATH) and _9_FUND_PATH not in _sys.path:
        _sys.path.insert(0, _9_FUND_PATH)
except Exception:
    pass


class LeastResistanceAdapter:
    """将 compute_resistance_3d() 输出转换为 ForceVector 核心字段。

    direction 取 direction_score(float [-1,1])，而非字符串 'up'/'down'/'neutral'。
    """

    def to_force_vector_fields(self, dimension: str, r3d: dict,
                               raw_confidence: float = 0.5) -> dict:
        """将 compute_resistance_3d() 输出转换为 ForceVector 核心字段。

        Args:
            dimension: 维度名 "dao"/"tian"/"di"/"jiang"/"fa"
            r3d: compute_resistance_3d() 返回的 dict
            raw_confidence: r3d 无 confidence 字段时的回退值

        Returns:
            dict: dimension/direction/magnitude/confidence/velocity/acceleration
        """
        # direction = direction_score（float，不是字符串）
        try:
            direction = float(r3d.get("direction_score", 0.0))
        except (TypeError, ValueError):
            direction = 0.0
        # magnitude = |direction_score|
        magnitude = abs(direction)
        # velocity / acceleration 透传
        try:
            velocity = float(r3d.get("velocity", 0.0))
        except (TypeError, ValueError):
            velocity = 0.0
        try:
            acceleration = float(r3d.get("acceleration", 0.0))
        except (TypeError, ValueError):
            acceleration = 0.0
        # confidence：优先 r3d，缺失时回退 raw_confidence
        try:
            confidence = float(r3d.get("confidence", raw_confidence))
        except (TypeError, ValueError):
            confidence = float(raw_confidence)
        return {
            "dimension": dimension,
            "direction": direction,
            "magnitude": magnitude,
            "confidence": confidence,
            "velocity": velocity,
            "acceleration": acceleration,
        }


class SignalEngineAdapter:
    """SignalEngine 薄封装 —— FAIL-OPEN 调用 _bayesian_confidence / _adaptive_weight。

    正常情况下委托给 SignalEngine 实例；signal_engine 不可用或方法异常时
    返回中性默认值（bayesian_confidence 回退 raw_confidence，adaptive_weight 回退 1.0）。
    """

    def bayesian_confidence(self, signal_engine, module_name: str,
                            raw_confidence: float) -> float:
        """调用 signal_engine._bayesian_confidence()，异常时返回 raw_confidence。

        SignalEngine 内部需 predictions>=10 才做贝叶斯修正，否则原样返回 raw_confidence。
        """
        try:
            return float(signal_engine._bayesian_confidence(module_name, raw_confidence))
        except Exception:
            return float(raw_confidence)

    def adaptive_weight(self, signal_engine, module_name: str) -> float:
        """调用 signal_engine._adaptive_weight()，异常时返回 1.0。

        SignalEngine 内部需 predictions>=5 才做自适应调整，否则返回 base 权重。
        """
        try:
            return float(signal_engine._adaptive_weight(module_name))
        except Exception:
            return 1.0
