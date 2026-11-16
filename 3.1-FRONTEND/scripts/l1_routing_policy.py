# -*- coding: utf-8 -*-
"""L1 路由策略纯决策模块（SPEC-v1.4 §7.1 E1 策略对比实验）。

定位：把「意图检测通道 + 准入闸门」从 route_query 中抽成**纯函数**，
同一份特征（Features）可被多个策略（S0–S5）复用，便于同一测试集对比。

约束：
  - 不改变生产行为：route_query 仍走原链路，默认等价 S0（由测试锁定）；
  - 不引入第二套阈值：语义阈值/认知门限全部来自 route_confidence / intent_matcher；
  - 纯函数：decide() 只依赖 (strategy, features, params)，不做 IO、不写状态。

策略定义（SPEC §7.1.1，附实测口径修正）：
  S0 现状      检测=正则→语义(≥阈值)  门控=认知召回(0.65，确定性/产物/序列旁路)
  S1 契约门控  检测=仅正则            门控=能力契约(G1/G2)
  S2 语义补位  检测=正则→语义(≥阈值)  门控=契约，无 margin
  S3 歧义拦截  同 S2 + margin ≥ δ     门控=契约
  S4 认知裁决  同 S3 + 低置信/歧义时用认知裁决（coverage≥0.65 可采纳）
  S5 纯语义    检测=仅语义(≥阈值+δ)   门控=契约
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from l1_route_signal import (  # noqa: E402
    DETERMINISTIC_INTENTS,
    EXECUTOR_AVAILABILITY_INTENTS,
    EXECUTORS,
    R_DETERMINISTIC_REGISTRY,
    R_EXECUTOR_AVAILABILITY,
    SEMANTIC_MIN_LEN,
    detect_intent_regex,
    semantic_candidates,
)

_TRAINING_SYS_DIR = os.path.abspath(os.path.join(_SCRIPTS_DIR, "..", "..", "34-前端应用训练系统"))
if _TRAINING_SYS_DIR not in sys.path:
    sys.path.insert(0, _TRAINING_SYS_DIR)

from core.route_confidence import (  # noqa: E402
    L1_DIRECT,
    L2_HANDOFF,
    THRESHOLD_HIGH,
    evaluate_route,
)


def _semantic_threshold() -> float:
    """语义阈值单一事实源：读 41 intent_matcher 已标定常量（intent_matcher 为相对导入包，
    由 l1_route_signal 以 `_l1_semantic_core` 包名加载，故从 sys.modules 取）。"""
    mod = sys.modules.get("_l1_semantic_core.intent_matcher")
    if mod is not None:
        return float(getattr(mod, "SEMANTIC_THRESHOLD_ZH", 0.66))
    return 0.66  # 语义通道加载失败时的兜底值，与 intent_matcher.SEMANTIC_THRESHOLD_ZH 一致


SEMANTIC_THRESHOLD_ZH = _semantic_threshold()

STRATEGIES: Tuple[str, ...] = ("S0", "S1", "S2", "S3", "S4", "S5")

R_INTENT_UNKNOWN = "intent_unknown"
R_NO_EXECUTOR = "l1_no_executor"
R_LOW_CONFIDENCE = "l1_low_confidence"
R_AMBIGUOUS = "l1_ambiguous_intent"
R_SEMANTIC_MATCH = "semantic_intent_match"
R_RECALL_DIRECT = "cognitive_recall_direct"
R_ARBITRATION_ADOPT = "cognition_arbitration_adopt"
R_CONTRACT_DIRECT = "executor_contract_ok"


@dataclass(frozen=True)
class Features:
    """单条问题的路由特征（检测结果 + 认知召回证据），由调用方一次性构建。"""

    message: str
    regex_intent: str = ""
    semantic_top: Tuple[Tuple[str, float], ...] = ()
    series_ok: bool = False
    # 认知召回原始记忆（沿 route_query 用法，交 evaluate_route 统一算 coverage）
    recall_memories: Tuple[Dict[str, Any], ...] = ()
    cognitive_available: bool = True
    recall_error: bool = False

    def semantic_margin(self) -> float:
        if not self.semantic_top:
            return 0.0
        top1 = self.semantic_top[0][1]
        top2 = self.semantic_top[1][1] if len(self.semantic_top) > 1 else 0.0
        return top1 - top2


@dataclass(frozen=True)
class Params:
    semantic_threshold: float = SEMANTIC_THRESHOLD_ZH
    margin_delta: float = 0.0
    arbitration_threshold: float = THRESHOLD_HIGH
    min_semantic_len: int = SEMANTIC_MIN_LEN


@dataclass(frozen=True)
class Decision:
    strategy: str
    decision: str
    intent: str
    channel: str
    route_confidence: float
    handled: bool
    reasons: Tuple[str, ...] = ()
    features: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy,
            "decision": self.decision,
            "intent": self.intent,
            "channel": self.channel,
            "route_confidence": self.route_confidence,
            "handled": self.handled,
            "reasons": list(self.reasons),
            "features": dict(self.features),
        }


# 策略开关：regex 检测 / 语义检测 / margin 拦截 / 认知裁决
_STRATEGY_CONFIG: Dict[str, Dict[str, bool]] = {
    "S0": {
        "regex": True,
        "semantic": True,
        "margin": False,
        "cognitive": True,
        "arbitration": False,
    },
    "S1": {
        "regex": True,
        "semantic": False,
        "margin": False,
        "cognitive": False,
        "arbitration": False,
    },
    "S2": {
        "regex": True,
        "semantic": True,
        "margin": False,
        "cognitive": False,
        "arbitration": False,
    },
    "S3": {
        "regex": True,
        "semantic": True,
        "margin": True,
        "cognitive": False,
        "arbitration": False,
    },
    "S4": {
        "regex": True,
        "semantic": True,
        "margin": True,
        "cognitive": False,
        "arbitration": True,
    },
    "S5": {
        "regex": False,
        "semantic": True,
        "margin": True,
        "cognitive": False,
        "arbitration": False,
    },
}


def _feat_view(f: Features) -> Dict[str, Any]:
    return {
        "semantic_top1": round(f.semantic_top[0][1], 4) if f.semantic_top else None,
        "semantic_margin": round(f.semantic_margin(), 4),
    }


def _decision(
    strategy: str,
    decision: str,
    intent: str,
    channel: str,
    reasons: Sequence[str],
    f: Features,
    confidence: float | None = None,
) -> Decision:
    route_confidence = (
        confidence if confidence is not None else (1.0 if decision == L1_DIRECT else 0.0)
    )
    return Decision(
        strategy=strategy,
        decision=decision,
        intent=intent or "unknown",
        channel=channel,
        route_confidence=route_confidence,
        handled=decision == L1_DIRECT,
        reasons=tuple(reasons),
        features=_feat_view(f),
    )


def _cognitive_signal(f: Features):
    """复用 route_query 的认知门控（同一函数、同一阈值），返回 RouteConfidenceResult。"""
    if f.recall_error:
        return evaluate_route([], cognitive_available=False)
    return evaluate_route(list(f.recall_memories), cognitive_available=f.cognitive_available)


def _decide_s0(f: Features, p: Params) -> Decision:
    """S0 = 线上现状：正则→语义兜底；确定性/产物/序列旁路；其余走认知召回门控。"""
    intent = f.regex_intent
    if not intent and f.semantic_top and f.semantic_top[0][1] >= p.semantic_threshold:
        intent = f.semantic_top[0][0]
    channel = "regex" if f.regex_intent else ("semantic" if intent else "none")

    if not intent:
        return _decision("S0", L2_HANDOFF, "", channel, [R_INTENT_UNKNOWN], f)
    if intent not in EXECUTORS:
        return _decision("S0", L2_HANDOFF, intent, channel, [R_NO_EXECUTOR], f)
    if f.regex_intent and intent in DETERMINISTIC_INTENTS:
        return _decision("S0", L1_DIRECT, intent, "deterministic", [R_DETERMINISTIC_REGISTRY], f)
    if f.regex_intent and intent in EXECUTOR_AVAILABILITY_INTENTS:
        return _decision("S0", L1_DIRECT, intent, "deterministic", [R_EXECUTOR_AVAILABILITY], f)
    if intent == "metric_series" and f.series_ok:
        return _decision("S0", L1_DIRECT, intent, "deterministic", [R_DETERMINISTIC_REGISTRY], f)

    signal = _cognitive_signal(f)
    if signal.decision == L1_DIRECT:
        return _decision(
            "S0",
            L1_DIRECT,
            intent,
            channel,
            tuple(signal.reasons) + (R_RECALL_DIRECT,),
            f,
            confidence=signal.route_confidence,
        )
    return _decision("S0", L2_HANDOFF, intent, channel, tuple(signal.reasons), f)


def _select_intent(
    cfg: Dict[str, bool], f: Features, p: Params
) -> Tuple[str, str, Tuple[str, ...]]:
    """返回 (intent, channel, reasons)；intent 为空表示应在检测阶段就交 L2。"""
    if cfg["regex"] and f.regex_intent:
        return f.regex_intent, "regex", ()

    if not cfg["semantic"] or not f.semantic_top:
        return "", "none", (R_INTENT_UNKNOWN,)

    top1_intent, top1_score = f.semantic_top[0]
    if top1_score < p.semantic_threshold:
        return "", "semantic", (R_LOW_CONFIDENCE,)
    if cfg["margin"] and f.semantic_margin() < p.margin_delta:
        return "", "semantic", (R_AMBIGUOUS,)
    return top1_intent, "semantic", ()


def decide(strategy: str, f: Features, params: Optional[Params] = None) -> Decision:
    """纯决策入口：给定策略与特征，返回与 route_signal 同构的判决。"""
    if strategy not in _STRATEGY_CONFIG:
        raise ValueError(f"unknown strategy: {strategy}")
    p = params or Params()
    if strategy == "S0":
        return _decide_s0(f, p)

    cfg = _STRATEGY_CONFIG[strategy]
    intent, channel, reasons = _select_intent(cfg, f, p)

    if not intent and cfg["arbitration"]:
        # S4：低置信/歧义 → 认知裁决；认知覆盖度达门限则采纳语义 top1
        signal = _cognitive_signal(f)
        if (
            f.semantic_top
            and signal.route_confidence >= p.arbitration_threshold
            and f.semantic_top[0][1] >= p.semantic_threshold * 0.9  # 仅在"接近阈值"时采纳
        ):
            intent = f.semantic_top[0][0]
            channel = "semantic"
            reasons = (R_ARBITRATION_ADOPT,)

    if not intent:
        return _decision(strategy, L2_HANDOFF, "", channel, reasons, f)

    # G1：能力闸（无执行器 → L2）；contract 策略不查认知
    if intent not in EXECUTORS:
        return _decision(strategy, L2_HANDOFF, intent, channel, [R_NO_EXECUTOR], f)

    # G2：语义来源的 metric_series 必须命中确定性序列；正则来源天然满足
    if channel == "semantic" and intent == "metric_series" and not f.series_ok:
        return _decision(strategy, L2_HANDOFF, intent, channel, [R_LOW_CONFIDENCE], f)

    if channel == "semantic" and R_ARBITRATION_ADOPT not in reasons:
        reasons = (R_SEMANTIC_MATCH,) + tuple(reasons)
    elif intent in DETERMINISTIC_INTENTS:
        reasons = (R_DETERMINISTIC_REGISTRY,)
    elif intent in EXECUTOR_AVAILABILITY_INTENTS:
        reasons = (R_EXECUTOR_AVAILABILITY,)
    elif not reasons:
        reasons = (R_CONTRACT_DIRECT,)

    return _decision(strategy, L1_DIRECT, intent, channel, reasons, f)


def build_features(
    message: str,
    *,
    semantic_k: int = 3,
    recall_memories: Optional[List[Dict[str, Any]]] = None,
    cognitive_available: bool = True,
    recall_error: bool = False,
) -> Features:
    """从真实检测通道 + 认知召回结果构建特征（供 E1 harness 调用）。"""
    from l1_route_signal import _is_deterministic_series  # noqa: PLC0415 — 延迟导入

    return Features(
        message=message,
        regex_intent=detect_intent_regex(message),
        semantic_top=tuple(semantic_candidates(message, k=semantic_k, validated=True)),
        series_ok=bool(_is_deterministic_series(message)),
        recall_memories=tuple(recall_memories or ()),
        cognitive_available=cognitive_available,
        recall_error=recall_error,
    )
