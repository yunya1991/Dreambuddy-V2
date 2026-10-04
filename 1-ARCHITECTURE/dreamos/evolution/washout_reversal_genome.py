"""WashoutReversalGenome — 洗盘反转做多基因组 (编排层).

Spec: docs/superpowers/specs/2026-09-22-washout-reversal-genome-design.md §3.3

阶段1 新增 (纯新增, 零回归):
  - WashoutReversalSignal: 做多信号输出契约
  - WashoutReversalGenome: 编排 WashoutDetector + EndingDetector + 案例库

设计原则 (硬约束):
  - HC-G1: 信号走 evolution probe 仓路径, 不增加总风险敞口
  - HC-G2: WashoutDetector conf≥0.80 才进入结束信号判定
  - HC-G3: EndingDetector 异常 → FAIL-OPEN
  - HC-G5: enable=False 时降级, 链路字节等价
  - HC-G6: 信号需 ≥ PROBE_THRESHOLD=0.55
  - HC-G7: 平仓后必须 record_case
  - confidence = washout_verdict.confidence*0.6 + ending_signal.confidence*0.4
  - 禁用 LLM, 纯数值计算

用法:
    genome = WashoutReversalGenome(
        washout_detector=det,
        ending_detector=ending_det,
        case_library=lib,
        bayesian_updater=updater,
        enable=True,
    )
    signal = genome.detect_signal("BTC", df, macro_data)
    if signal.direction == "LONG":
        # 做多
    # 平仓后
    genome.record_case(closed_case)
"""
from __future__ import annotations

import logging
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional

import pandas as pd

from .washout_ending_detector import EndingSignal, WashoutEndingDetector
from .washout_reversal_case_library import WashoutReversalCaseLibrary
from .washout_bayesian_updater import BayesianUpdater
from .washout_case_library import WashoutCase
from .exploration_policy import ExplorationPolicy

__all__ = ["WashoutReversalGenome", "WashoutReversalSignal"]

logger = logging.getLogger(__name__)

# 硬约束参数
_WASHOUT_CONFIDENCE_THRESHOLD = 0.80  # HC-G2: conf≥0.80 才进入结束信号判定
_PROBE_THRESHOLD = 0.55  # HC-G6: 信号需 ≥0.55
_CONFIDENCE_WASHOUT_WEIGHT = 0.6  # confidence = wv*0.6 + es*0.4
_CONFIDENCE_ENDING_WEIGHT = 0.4


@dataclass(frozen=True)
class WashoutReversalSignal:
    """洗盘反转做多信号输出契约.

    Attributes:
        direction: "LONG" 或 "NONE"
        confidence: [0.0, 1.0]
        washout_verdict: 洗盘判定结果 (WashoutVerdict)
        ending_signal: 结束信号 (EndingSignal)
        reason: 触发原因摘要
        timestamp: ISO 8601 UTC
    """
    direction: str
    confidence: float
    washout_verdict: object  # WashoutVerdict (延迟 import 避免循环)
    ending_signal: EndingSignal
    reason: str
    timestamp: str

    def __post_init__(self):
        c = float(self.confidence)
        if c < 0.0:
            c = 0.0
        elif c > 1.0:
            c = 1.0
        object.__setattr__(self, "confidence", c)
        # direction 标准化
        d = str(self.direction).upper()
        object.__setattr__(self, "direction", d)


class WashoutReversalGenome:
    """洗盘反转做多基因组 (编排层).

    编排流程:
        1. WashoutDetector.run(coin, df, macro) → verdict
        2. verdict.label=WASHOUT + conf≥0.80 → EndingDetector.check(df, macro)
        3. ending_signal.activated=True → 输出做多信号
        4. confidence = wv.confidence*0.6 + es.confidence*0.4

    FAIL-OPEN:
        任何异常 → direction=NONE, 不抛错不阻塞.
    """

    def __init__(
        self,
        washout_detector: object,
        ending_detector: WashoutEndingDetector,
        case_library: WashoutReversalCaseLibrary,
        bayesian_updater: BayesianUpdater,
        enable: bool = False,
        sandbox_validate_fn: Optional[callable] = None,
        exploration_policy: Optional[ExplorationPolicy] = None,
    ):
        self.washout_detector = washout_detector
        self.ending_detector = ending_detector
        self.case_library = case_library
        self.bayesian_updater = bayesian_updater
        self.enable = bool(enable)
        self.sandbox_validate_fn = sandbox_validate_fn
        self.exploration_policy = exploration_policy if exploration_policy is not None else ExplorationPolicy()

    def detect_signal(
        self,
        coin: str,
        df: pd.DataFrame,
        macro_data: Dict,
    ) -> WashoutReversalSignal:
        """主入口: 检测洗盘反转做多信号.

        流程:
            1. WashoutDetector.run(coin, df, macro) → verdict
            2. verdict.label=WASHOUT + conf≥0.80 → EndingDetector.check(df, macro)
            3. ending_signal.activated=True → 输出做多信号

        Returns:
            WashoutReversalSignal(direction=LONG/NONE, confidence, ...)
        """
        ts = datetime.now(timezone.utc).isoformat()
        not_activated = EndingSignal.not_activated("genome_disabled")

        # 开关关断
        if not self.enable:
            return WashoutReversalSignal(
                direction="NONE",
                confidence=0.0,
                washout_verdict=None,
                ending_signal=not_activated,
                reason="genome_disabled",
                timestamp=ts,
            )

        try:
            # Step 1: WashoutDetector 判定
            verdict = self.washout_detector.run(coin, df, macro_data)

            # HC-G2: conf<0.80 → 不进入结束信号判定
            if verdict is None:
                return WashoutReversalSignal(
                    direction="NONE",
                    confidence=0.0,
                    washout_verdict=None,
                    ending_signal=not_activated,
                    reason="washout_verdict_none",
                    timestamp=ts,
                )

            # 获取 label 值 (兼容 Enum 和 str)
            label_val = (
                verdict.label.value if hasattr(verdict.label, "value")
                else str(verdict.label).lower()
            )

            if label_val != "washout":
                return WashoutReversalSignal(
                    direction="NONE",
                    confidence=0.0,
                    washout_verdict=verdict,
                    ending_signal=not_activated,
                    reason=f"washout_label={label_val}",
                    timestamp=ts,
                )

            if verdict.confidence < _WASHOUT_CONFIDENCE_THRESHOLD:
                return WashoutReversalSignal(
                    direction="NONE",
                    confidence=0.0,
                    washout_verdict=verdict,
                    ending_signal=not_activated,
                    reason=f"washout_conf_low={verdict.confidence:.3f}",
                    timestamp=ts,
                )

            # Step 2: EndingDetector 判定
            ending_signal = self.ending_detector.check(df, macro_data)

            if not ending_signal.activated:
                return WashoutReversalSignal(
                    direction="NONE",
                    confidence=0.0,
                    washout_verdict=verdict,
                    ending_signal=ending_signal,
                    reason=f"ending_not_activated:{ending_signal.reason}",
                    timestamp=ts,
                )

            # Step 3: 计算综合 confidence
            confidence = (
                verdict.confidence * _CONFIDENCE_WASHOUT_WEIGHT
                + ending_signal.confidence * _CONFIDENCE_ENDING_WEIGHT
            )
            confidence = max(0.0, min(1.0, confidence))

            # HC-G6: confidence < PROBE_THRESHOLD → 不输出信号
            # 阶段3: Epsilon-Greedy 探索策略
            # should_explore=True → 降低 probe_threshold 到 0.30 (随机探索)
            # should_explore=False → 走正常退火阈值 (利用)
            if self.exploration_policy.should_explore(len(self.case_library)):
                probe_threshold = self.exploration_policy.get_exploration_probe_threshold()
            else:
                probe_threshold = self.exploration_policy.get_probe_threshold(
                    len(self.case_library)
                )
            if confidence < probe_threshold:
                return WashoutReversalSignal(
                    direction="NONE",
                    confidence=confidence,
                    washout_verdict=verdict,
                    ending_signal=ending_signal,
                    reason=f"below_probe_threshold={confidence:.3f}_thresh={probe_threshold:.3f}",
                    timestamp=ts,
                )

            return WashoutReversalSignal(
                direction="LONG",
                confidence=confidence,
                washout_verdict=verdict,
                ending_signal=ending_signal,
                reason=(
                    f"washout_conf={verdict.confidence:.3f}"
                    f"+ending_conf={ending_signal.confidence:.3f}"
                    f"+combined={confidence:.3f}"
                ),
                timestamp=ts,
            )
        except Exception as e:
            tb = traceback.format_exc()
            logger.error(
                "WashoutReversalGenome.detect_signal FAIL-OPEN err=%s\n%s", e, tb
            )
            return WashoutReversalSignal(
                direction="NONE",
                confidence=0.0,
                washout_verdict=None,
                ending_signal=EndingSignal.not_activated(
                    f"exception:{type(e).__name__}"
                ),
                reason=f"exception:{type(e).__name__}",
                timestamp=ts,
            )

    # ============================================================
    # 案例入库 (自进化训练)
    # ============================================================
    def record_case(self, case: WashoutCase) -> None:
        """平仓后记录案例 (HC-G7).

        Args:
            case: WashoutCase 闭环案例
                  actual_label: reversal_long_success / reversal_long_fail
        """
        try:
            self.case_library.add(case)
        except Exception as e:
            logger.warning("WashoutReversalGenome.record_case FAIL-OPEN: %s", e)

    # ============================================================
    # 自进化: 复用 _sandbox_validate 沙箱验证
    # ============================================================
    def evolve(self, proposal: Optional[Dict] = None) -> Dict:
        """复用 EvolutionEngine._sandbox_validate 进行自进化验证.

        Args:
            proposal: 编排调整提案 (含 scenario_id/new_pattern/nodes/score)
                      None=使用默认提案

        Returns:
            {"accepted": bool, "score": float, "baseline_score": float, "reason": str}

        FAIL-OPEN:
            异常 → accepted=False, 不抛错.
        """
        try:
            if self.sandbox_validate_fn is None:
                return {
                    "accepted": False,
                    "score": 0.0,
                    "baseline_score": 0.0,
                    "reason": "no_sandbox_validate_fn",
                }

            if proposal is None:
                proposal = {
                    "scenario_id": "washout_reversal_default",
                    "new_pattern": "knn_bayesian",
                    "nodes": ["WashoutReversalGenome"],
                    "score": 0.5,
                }

            accepted = bool(self.sandbox_validate_fn(proposal))

            return {
                "accepted": accepted,
                "score": float(proposal.get("score", 0.0)),
                "baseline_score": float(proposal.get("baseline_score", 0.0)),
                "reason": "sandbox_passed" if accepted else "sandbox_rejected",
            }
        except Exception as e:
            logger.warning("WashoutReversalGenome.evolve FAIL-OPEN: %s", e)
            return {
                "accepted": False,
                "score": 0.0,
                "baseline_score": 0.0,
                "reason": f"exception:{type(e).__name__}",
            }
