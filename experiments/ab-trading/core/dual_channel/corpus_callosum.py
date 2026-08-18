#!/usr/bin/env python3
"""
胼胝体整合器 (Corpus Callosum Integrator)

P2-8 spec §4.2 核心逻辑：左右脑并行决策的整合层。
对齐认知科学"左右脑分工 + 胼胝体整合"理论（Sperry 裂脑研究）。

整合规则（spec §4.2）：
  1. 三者一致（左脑=右脑=A0）→ 高置信标准仓
  2. 左右一致但与 A0 相反 → 取 A0 方向 + 降置信
  3. 左右分歧 → 取 A0 方向 + 降置信 + 标记分歧

胼胝体 = A7 门禁的升级版：从单通道阈值门禁 → 双通道对比整合门禁。
"""
from dataclasses import dataclass, field
from typing import Optional, List
from enum import Enum


class AgreementLevel(Enum):
    """左右脑一致性等级"""
    FULL_CONSENSUS = "full_consensus"       # 三者一致
    LR_CONSENSUS = "lr_consensus"           # 左右一致但与A0不同
    LR_DIVERGENT = "lr_divergent"           # 左右分歧
    RIGHT_SKIP = "right_skip"               # 右脑未启用/无信号


@dataclass
class ChannelResult:
    """单通道决策结果"""
    direction: str        # "LONG" / "SHORT" / "HOLD"
    confidence: float     # [0, 1]
    source: str = ""      # "left_brain" / "right_brain" / "a0"
    reasoning: List[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class IntegrationResult:
    """胼胝体整合结果"""
    direction: str                # 整合后方向
    confidence: float             # 整合后置信度
    agreement_level: AgreementLevel
    gate_passed: bool             # 是否通过门禁
    gate_reason: str              # 门禁理由
    left_brain: Optional[ChannelResult] = None
    right_brain: Optional[ChannelResult] = None
    a0_direction: str = "HOLD"
    divergence_flag: bool = False  # 左右分歧标记
    confidence_adjustment: float = 0.0  # 置信度调整量

    def to_dict(self) -> dict:
        return {
            "direction": self.direction,
            "confidence": round(self.confidence, 4),
            "agreement_level": self.agreement_level.value,
            "gate_passed": self.gate_passed,
            "gate_reason": self.gate_reason,
            "left_direction": self.left_brain.direction if self.left_brain else None,
            "left_confidence": round(self.left_brain.confidence, 4) if self.left_brain else None,
            "right_direction": self.right_brain.direction if self.right_brain else None,
            "right_confidence": round(self.right_brain.confidence, 4) if self.right_brain else None,
            "a0_direction": self.a0_direction,
            "divergence_flag": self.divergence_flag,
            "confidence_adjustment": round(self.confidence_adjustment, 4),
        }


class CorpusCallosum:
    """
    胼胝体整合器

    参数：
      gate_threshold: 门禁阈值（默认 0.65，与 a4_gate.py 对齐）
      consensus_bonus: 三者一致时的置信度加成（默认 +0.10）
      divergence_penalty: 左右分歧时的置信度惩罚（默认 -0.15）
      lr_consensus_penalty: 左右一致但与A0不同时的惩罚（默认 -0.08）
    """

    def __init__(
        self,
        gate_threshold: float = 0.65,
        consensus_bonus: float = 0.10,
        divergence_penalty: float = 0.15,
        lr_consensus_penalty: float = 0.08,
    ):
        self.gate_threshold = gate_threshold
        self.consensus_bonus = consensus_bonus
        self.divergence_penalty = divergence_penalty
        self.lr_consensus_penalty = lr_consensus_penalty

    def integrate(
        self,
        left: ChannelResult,
        right: Optional[ChannelResult],
        a0_direction: str = "HOLD",
    ) -> IntegrationResult:
        """
        整合左右脑通道 + A0 方向，输出最终决策。

        Args:
            left: 左脑通道结果（A0→A1→A2→A3 链路最终输出）
            right: 右脑通道结果（易经/做梦部），None 表示未启用
            a0_direction: A0 矛盾分析的主导方向

        Returns:
            IntegrationResult
        """
        # 右脑未启用 → 退化为单通道（左脑直接过门禁）
        if right is None or right.direction == "HOLD":
            return self._integrate_single_channel(left, a0_direction)

        # ── 三种整合场景 ──────────────────────────────────────────

        # 场景1: 三者一致
        if (left.direction == right.direction == a0_direction
                and left.direction != "HOLD"):
            return self._integrate_full_consensus(left, right, a0_direction)

        # 场景2: 左右一致但与 A0 相反（或 A0=HOLD）
        if (left.direction == right.direction
                and left.direction != "HOLD"
                and left.direction != a0_direction):
            return self._integrate_lr_consensus(left, right, a0_direction)

        # 场景2b: 左右一致且 A0=HOLD（A0 无方向，跟随左右）
        if (left.direction == right.direction
                and left.direction != "HOLD"
                and a0_direction == "HOLD"):
            return self._integrate_lr_consensus(left, right, a0_direction)

        # 场景3: 左右分歧
        if left.direction != right.direction:
            return self._integrate_lr_divergent(left, right, a0_direction)

        # 兜底：左脑 HOLD + 右脑 HOLD
        return self._integrate_single_channel(left, a0_direction)

    # ── 内部整合方法 ──────────────────────────────────────────────

    def _integrate_full_consensus(
        self, left: ChannelResult, right: ChannelResult, a0_dir: str
    ) -> IntegrationResult:
        """场景1: 三者一致 → 高置信标准仓"""
        base_conf = max(left.confidence, right.confidence)
        adjusted = min(base_conf + self.consensus_bonus, 0.95)
        gate_passed = adjusted >= self.gate_threshold
        reason = (f"三者一致({left.direction}) → 置信度加成"
                  f"+{self.consensus_bonus:.2f} → {adjusted:.0%}")
        return IntegrationResult(
            direction=left.direction,
            confidence=adjusted,
            agreement_level=AgreementLevel.FULL_CONSENSUS,
            gate_passed=gate_passed,
            gate_reason=reason,
            left_brain=left,
            right_brain=right,
            a0_direction=a0_dir,
            confidence_adjustment=self.consensus_bonus,
        )

    def _integrate_lr_consensus(
        self, left: ChannelResult, right: ChannelResult, a0_dir: str
    ) -> IntegrationResult:
        """场景2: 左右一致但与 A0 相反 → 取 A0 方向 + 降置信"""
        # 取 A0 方向（如果 A0=HOLD 则跟随左右）
        if a0_dir == "HOLD":
            final_dir = left.direction
        else:
            final_dir = a0_dir

        base_conf = max(left.confidence, right.confidence)
        adjusted = max(base_conf - self.lr_consensus_penalty, 0.30)
        gate_passed = adjusted >= self.gate_threshold and final_dir != "HOLD"
        conflict_note = (f"左右一致({left.direction}) vs A0({a0_dir})"
                         if a0_dir != "HOLD" else
                         f"左右一致({left.direction}), A0=HOLD")
        reason = f"{conflict_note} → 取A0方向({final_dir}), 降置信-{self.lr_consensus_penalty:.2f}"
        return IntegrationResult(
            direction=final_dir,
            confidence=adjusted,
            agreement_level=AgreementLevel.LR_CONSENSUS,
            gate_passed=gate_passed,
            gate_reason=reason,
            left_brain=left,
            right_brain=right,
            a0_direction=a0_dir,
            confidence_adjustment=-self.lr_consensus_penalty,
        )

    def _integrate_lr_divergent(
        self, left: ChannelResult, right: ChannelResult, a0_dir: str
    ) -> IntegrationResult:
        """场景3: 左右分歧 → 取 A0 方向 + 降置信 + 标记分歧"""
        # A0 方向优先；A0=HOLD 时取左脑（分析型更可信）
        if a0_dir != "HOLD":
            final_dir = a0_dir
        elif left.direction != "HOLD":
            final_dir = left.direction
        else:
            final_dir = right.direction

        base_conf = max(left.confidence, right.confidence)
        adjusted = max(base_conf - self.divergence_penalty, 0.25)
        gate_passed = adjusted >= self.gate_threshold and final_dir != "HOLD"
        reason = (f"左右分歧(左={left.direction}/右={right.direction}) "
                  f"→ 取A0({final_dir}), 降置信-{self.divergence_penalty:.2f}, 标记分歧")
        return IntegrationResult(
            direction=final_dir,
            confidence=adjusted,
            agreement_level=AgreementLevel.LR_DIVERGENT,
            gate_passed=gate_passed,
            gate_reason=reason,
            left_brain=left,
            right_brain=right,
            a0_direction=a0_dir,
            divergence_flag=True,
            confidence_adjustment=-self.divergence_penalty,
        )

    def _integrate_single_channel(
        self, left: ChannelResult, a0_dir: str
    ) -> IntegrationResult:
        """右脑未启用 → 单通道（左脑直接过门禁，与原 A7 行为一致）"""
        gate_passed = left.confidence >= self.gate_threshold and left.direction != "HOLD"
        reason = (f"单通道(左脑) conf={left.confidence:.0%} "
                  f"{'✅' if gate_passed else '❌'} 门槛={self.gate_threshold:.0%}")
        return IntegrationResult(
            direction=left.direction,
            confidence=left.confidence,
            agreement_level=AgreementLevel.RIGHT_SKIP,
            gate_passed=gate_passed,
            gate_reason=reason,
            left_brain=left,
            right_brain=None,
            a0_direction=a0_dir,
        )
