"""模块化开关 — L0/L1/L2/L3 各层独立开关。

文档要求：所有新功能必须可独立关闭，默认 OFF。

层级定义：
- L0 观测层（observer）：recall/verify 旁路记录
- L1 验证层（verifiers）：cycle_consistency / factuality / applicability
- L2 聚合层（weighted aggregation + weight learning）：多源加权 + BT 学习
- L3 预测层（quality predictor）：质量预测 + 抑制

默认全部 OFF（零行为变更），通过环境变量或显式调用开启。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict


@dataclass
class ModuleSwitches:
    """四层验证框架的模块化开关。"""
    # L0 观测层
    L0_observer: bool = False
    # L1 验证层
    L1_verifiers: bool = False
    # L2 聚合层（加权聚合 + 权重学习）
    L2_aggregation: bool = False
    # L3 预测层（质量预测 + 抑制）
    L3_prediction: bool = False

    @classmethod
    def from_env(cls) -> "ModuleSwitches":
        """从环境变量读取开关配置。

        环境变量名：COGNITIVE_L0 / COGNITIVE_L1 / COGNITIVE_L2 / COGNITIVE_L3
        值为 1/true/yes/on 表示开启。
        """
        def _enabled(name: str) -> bool:
            return os.environ.get(name, "").lower() in ("1", "true", "yes", "on")

        return cls(
            L0_observer=_enabled("COGNITIVE_L0"),
            L1_verifiers=_enabled("COGNITIVE_L1"),
            L2_aggregation=_enabled("COGNITIVE_L2"),
            L3_prediction=_enabled("COGNITIVE_L3"),
        )

    def all_off(self) -> bool:
        """所有层都关闭。"""
        return not any([
            self.L0_observer,
            self.L1_verifiers,
            self.L2_aggregation,
            self.L3_prediction,
        ])

    def to_dict(self) -> Dict[str, bool]:
        return {
            "L0_observer": self.L0_observer,
            "L1_verifiers": self.L1_verifiers,
            "L2_aggregation": self.L2_aggregation,
            "L3_prediction": self.L3_prediction,
        }

    def enable_all(self) -> None:
        """开启所有层。"""
        self.L0_observer = True
        self.L1_verifiers = True
        self.L2_aggregation = True
        self.L3_prediction = True

    def disable_all(self) -> None:
        """关闭所有层。"""
        self.L0_observer = False
        self.L1_verifiers = False
        self.L2_aggregation = False
        self.L3_prediction = False
