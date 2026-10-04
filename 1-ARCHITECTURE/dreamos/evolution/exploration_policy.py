"""ExplorationPolicy — 探索-利用策略管理器.

基于案例库大小动态调整 probe 阈值, 打破冷启动死锁.

设计原则 (硬约束):
  - HC-2: 纯数学计算, 无 LLM 依赖
  - FAIL-OPEN: 异常输入 → 返回硬编码默认阈值 0.55, 不抛错
  - 模块化开关: ENABLE_EVOLUTION_EXPLORATION 默认 False, 关断时字节等价
  - reward = tanh(pnl_pct/0.02) 归一化 [-1,1] (本文件不涉及计算, 仅阈值)

阈值退火策略 (Spec 缺陷B 适度上调, 避免冷启动死锁):
  - 冷启动 (case_count < 10):   threshold = 0.50 (适度上调, 原 0.40)
  - 早期 (10 ≤ case_count < 30): threshold = 0.52 (原 0.45)
  - 成熟 (30 ≤ case_count < 100): threshold = 0.54 (原 0.50)
  - 稳定 (case_count ≥ 100):     threshold = 0.55 (硬约束值, 不变)
"""
from __future__ import annotations

import logging
import os

__all__ = ["ExplorationPolicy"]

logger = logging.getLogger(__name__)

# 硬约束默认阈值 (开关关断 / 异常 / 稳定期)
_DEFAULT_THRESHOLD = 0.55


class ExplorationPolicy:
    """探索-利用策略管理器, 基于案例库大小动态调整阈值.

    开关: ENABLE_EVOLUTION_EXPLORATION 环境变量
      - 未设置/空/非"1" → 关断, 返回硬编码 0.55 (字节等价)
      - "1" → 启用退火策略
    """

    def __init__(self):
        self._enabled = os.environ.get("ENABLE_EVOLUTION_EXPLORATION", "") == "1"

    def get_probe_threshold(self, case_count: int) -> float:
        """获取 probe 阈值, 基于案例库大小动态退火.

        Returns:
            冷启动(<10): 0.50 (适度上调, 原 0.40)
            早期(10-29): 0.52 (原 0.45)
            成熟(30-99): 0.54 (原 0.50)
            稳定(≥100):  0.55 (硬约束值, 不变)

        开关关断时返回 0.55 (字节等价).
        异常输入返回 0.55 (FAIL-OPEN).
        """
        if not self._enabled:
            return _DEFAULT_THRESHOLD

        try:
            n = int(case_count)  # type: ignore[arg-type]
            if n < 0:
                return _DEFAULT_THRESHOLD
        except (TypeError, ValueError):
            return _DEFAULT_THRESHOLD

        if n < 10:
            return 0.50
        elif n < 30:
            return 0.52
        elif n < 100:
            return 0.54
        else:
            return 0.55

    def is_cold_start(self, case_count: int) -> bool:
        """是否处于冷启动阶段 (case_count < 30).

        开关关断时返回 False (字节等价).
        """
        if not self._enabled:
            return False

        try:
            n = int(case_count)  # type: ignore[arg-type]
            if n < 0:
                return False
            return n < 30
        except (TypeError, ValueError):
            return False

    def get_exploration_mode(self, case_count: int) -> str:
        """获取探索模式名称.

        Returns:
            "cold_start" (case_count < 10)
            "early" (10 ≤ case_count < 30)
            "mature" (30 ≤ case_count < 100)
            "stable" (case_count ≥ 100)

        开关关断时返回 "stable" (字节等价).
        """
        if not self._enabled:
            return "stable"

        try:
            n = int(case_count)  # type: ignore[arg-type]
            if n < 0:
                return "stable"
        except (TypeError, ValueError):
            return "stable"

        if n < 10:
            return "cold_start"
        elif n < 30:
            return "early"
        elif n < 100:
            return "mature"
        else:
            return "stable"

    # ============================================================
    # 阶段2: 阈值退火 (washout/weakness 判定阈值动态调整)
    # ============================================================
    def get_washout_threshold(self, case_count: int) -> float:
        """获取 washout 判定阈值, 基于案例库大小动态退火.

        冷启动时阈值更低 (更宽松), 鼓励做出 WASHOUT 判定
        → 触发 probe 仓 → 积累案例 → 打破冷启动死锁.

        Returns:
            冷启动 (<10):  0.55
            早期 (10-29):  0.58
            成熟 (30-99):  0.62
            稳定 (≥100):   0.65 (硬约束值)

        开关关断时返回 0.65 (字节等价).
        异常输入返回 0.65 (FAIL-OPEN).
        """
        if not self._enabled:
            return 0.65

        try:
            n = int(case_count)  # type: ignore[arg-type]
            if n < 0:
                return 0.65
        except (TypeError, ValueError):
            return 0.65

        if n < 10:
            return 0.55
        elif n < 30:
            return 0.58
        elif n < 100:
            return 0.62
        else:
            return 0.65

    def get_weakness_threshold(self, case_count: int) -> float:
        """获取 weakness 判定阈值, 基于案例库大小动态退火.

        冷启动时阈值更高 (更宽松), 鼓励做出 WEAKNESS 判定.

        Returns:
            冷启动 (<10):  0.45
            早期 (10-29): 0.42
            成熟 (30-99): 0.38
            稳定 (≥100):   0.35 (硬约束值)

        开关关断时返回 0.35 (字节等价).
        异常输入返回 0.35 (FAIL-OPEN).
        """
        if not self._enabled:
            return 0.35

        try:
            n = int(case_count)  # type: ignore[arg-type]
            if n < 0:
                return 0.35
        except (TypeError, ValueError):
            return 0.35

        if n < 10:
            return 0.45
        elif n < 30:
            return 0.42
        elif n < 100:
            return 0.38
        else:
            return 0.35

    # ============================================================
    # 阶段3: Epsilon-Greedy 探索策略
    # ============================================================
    def get_epsilon(self, case_count: int) -> float:
        """获取 epsilon 探索概率, 基于案例库大小动态退火.

        Epsilon-Greedy: 以 epsilon 概率走随机探索路径, (1-epsilon) 走利用路径.

        Returns:
            冷启动 (<10):  0.30 (30% 概率探索, 主动积累案例)
            早期 (10-29): 0.20
            成熟 (30-99): 0.10
            稳定 (≥100):   0.05 (硬约束下限, 仍保留少量探索防过拟合)

        开关关断时返回 0.0 (字节等价, 永不探索).
        异常输入返回 0.0 (FAIL-OPEN).
        """
        if not self._enabled:
            return 0.0

        try:
            n = int(case_count)  # type: ignore[arg-type]
            if n < 0:
                return 0.0
        except (TypeError, ValueError):
            return 0.0

        if n < 10:
            return 0.30
        elif n < 30:
            return 0.20
        elif n < 100:
            return 0.10
        else:
            return 0.05

    def should_explore(self, case_count: int, rng_seed: int | None = None) -> bool:
        """是否走随机探索路径 (Epsilon-Greedy).

        以 epsilon 概率返回 True (探索), 否则返回 False (利用).
        rng_seed 可注入, 保证测试可复现.

        Args:
            case_count: 案例库大小
            rng_seed: 随机种子, None=系统随机

        Returns:
            True: 走随机探索路径 (降低 probe_threshold 到 0.30)
            False: 走正常利用路径

        开关关断时永远返回 False (字节等价).
        异常输入返回 False (FAIL-OPEN).
        """
        if not self._enabled:
            return False

        try:
            n = int(case_count)  # type: ignore[arg-type]
            if n < 0:
                return False
        except (TypeError, ValueError):
            return False

        epsilon = self.get_epsilon(n)
        if epsilon <= 0.0:
            return False

        # rng_seed 注入: 保证测试可复现
        import random
        if rng_seed is not None:
            rng = random.Random(rng_seed)
            return rng.random() < epsilon
        else:
            return random.random() < epsilon

    def get_exploration_probe_threshold(self) -> float:
        """探索时的 probe_threshold (降低门槛, 让更多信号通过).

        Returns:
            0.40 (固定值, 探索时降低门槛鼓励尝试; Spec 缺陷B 从 0.30 上调)

        注意: 此方法不依赖开关, 仅在 should_explore()=True 时调用.
        """
        return 0.40
