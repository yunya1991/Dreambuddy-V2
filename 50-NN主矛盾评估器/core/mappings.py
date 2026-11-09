"""50 自有的 source 映射表（禁止复用 23 的键，否则 11-* 源退化为 C3/0.05）。"""

from __future__ import annotations

VALID_DIMENSIONS = {"D1", "D2", "D3", "D4", "C6", "C7", "C8", "NEWS"}
VALID_HORIZONS = {"minutes", "hours", "days", "weeks"}
VALID_INTENTS = {"trend", "reversal", "event_shock"}

# N3（SPEC-M1 M4）：角色四分。
# macro_force 源产 D1/days 维度的 path，参与宏观力量裁决；
# constraint 源不产 path（仅用于未来的硬约束）；
# self_mirror 源不产 path（自环反馈，不重复投票）；
# external 源产微观路径。
MACRO_FORCE_SOURCES = {"40-cycle", "43-strategic", "40-divergence", "40-resonance"}
CONSTRAINT_SOURCES: set[str] = set()
SELF_MIRROR_SOURCES = {"29-event", "23-contradiction"}
EXTERNAL_SOURCES = {
    "11-bcrm",
    "11-bdsm",
    "11-washout",
    "11-event-arbitrage",
    "11-bcrm-tactical",
}

# 外部证据权重之和必须为 1.0（约束/自环不投票，权重 0）
SOURCE_WEIGHT_MAP = {
    "11-bcrm": 0.15,
    "11-bdsm": 0.20,
    "11-washout": 0.15,
    "11-event-arbitrage": 0.15,
    "11-bcrm-tactical": 0.35,
    "29-event": 0.0,
    # N3（SPEC-M1 M4）：macro_force 权重表已注册，R0 未完成前保持 0（G1 红线）。
    # 解禁后目标值：40-cycle=0.15 / 43-strategic=0.10 / 40-divergence=0.05 / 40-resonance=0.05，micro 等比缩放。
    "40-cycle": 0.0,
    "43-strategic": 0.0,
    "40-divergence": 0.0,
    "40-resonance": 0.0,
    "23-contradiction": 0.0,
}

SOURCE_DIM_MAP = {
    "11-bcrm": "D3",
    "11-bdsm": "C6",
    "11-washout": "D3",
    "11-event-arbitrage": "C7",
    "11-bcrm-tactical": "D3",
    "29-event": "C7",
    "40-cycle": "D1",
    "43-strategic": "D1",
    "40-divergence": "D1",
    "40-resonance": "D1",
    "23-contradiction": "C7",
}

SOURCE_TF_MAP = {
    "11-bcrm": "days",
    "11-bdsm": "days",
    "11-washout": "hours",
    "11-event-arbitrage": "hours",
    "11-bcrm-tactical": "hours",
    "29-event": "hours",
    "40-cycle": "days",
    "43-strategic": "days",
    "40-divergence": "days",
    "40-resonance": "days",
    "23-contradiction": "hours",
}

SOURCE_INTENT_MAP = {
    "11-washout": "reversal",
    "11-event-arbitrage": "event_shock",
    "29-event": "event_shock",
}

SOURCE_ALIASES = {
    "bcrm": "11-bcrm",
    "bdsm": "11-bdsm",
    "washout": "11-washout",
    "event-arbitrage": "11-event-arbitrage",
    "event_arbitrage": "11-event-arbitrage",
    "bcrm-tactical": "11-bcrm-tactical",
    "bcrm_tactical": "11-bcrm-tactical",
    "cycle": "40-cycle",
    "strategic": "43-strategic",
    # F1（SPEC-M1 M1）：42 双写过渡期的旧名容错，双写结束后旧名进审计告警
    "strategic_extension": "43-strategic",
    "43-strategic-extension": "43-strategic",
    "event": "29-event",
    "contradiction": "23-contradiction",
}

# F2（SPEC-M1 M3）：C3 非 VALID_DIMENSIONS 成员（硬 bug），统一默认到 C7（隐性/未分类）
DEFAULT_DIMENSION = "C7"
DEFAULT_WEIGHT = 0.05
DEFAULT_HORIZON = "hours"

# F3（SPEC-M1 M8）：源数据年龄 TTL（小时）；源年龄超 2×TTL → evidence 丢弃 + degraded=source_stale
SOURCE_TTL_HOURS = {
    "40-cycle": 168.0,
    "40-divergence": 168.0,
    "40-resonance": 168.0,
    "43-strategic": 72.0,
    "11-bcrm": 24.0,
    "11-bdsm": 24.0,
    "11-washout": 24.0,
    "11-event-arbitrage": 24.0,
    "11-bcrm-tactical": 24.0,
    "23-contradiction": 24.0,
    "29-event": 24.0,
}
DEFAULT_TTL_HOURS = 24.0


def normalize_source(source: object) -> str:
    value = str(source or "").strip().lower()
    return SOURCE_ALIASES.get(value, value)


def role_of(source: object) -> str:
    name = normalize_source(source)
    if name in MACRO_FORCE_SOURCES:
        return "macro_force"
    if name in CONSTRAINT_SOURCES:
        return "constraint"
    if name in SELF_MIRROR_SOURCES:
        return "self_mirror"
    if name in EXTERNAL_SOURCES:
        return "external"
    return "unknown"


def intent_of(source: object, hint: object) -> str:
    name = normalize_source(source)
    value = str(hint or "").strip().lower()
    if value in VALID_INTENTS:
        return value
    return SOURCE_INTENT_MAP.get(name, "trend")


def normalize_horizon(value: object) -> str:
    horizon = str(value or "").strip().lower()
    if horizon in VALID_HORIZONS:
        return horizon
    if horizon in ("minute", "m"):
        return "minutes"
    if horizon in ("hour", "h"):
        return "hours"
    if horizon in ("day", "d"):
        return "days"
    if horizon in ("week", "w"):
        return "weeks"
    return DEFAULT_HORIZON


# ══════════════════════════════════════════════════════════════════
# M4-5: trigger → weight_profile 三档（SPEC-M3 §2.1/§2.2）
# ══════════════════════════════════════════════════════════════════

VALID_TRIGGERS = {"macro_led", "micro_led"}

# 预注册权重 profile（宏观权重 / 微观权重）。
# G1 红线期间 macro_force 源权重仍为 0，profile 仅记录目标分档，解禁后按此分配。
WEIGHT_PROFILES: dict[str, dict[str, float]] = {
    "default": {"macro_weight": 0.30, "micro_weight": 0.70},
    "macro_led": {"macro_weight": 0.50, "micro_weight": 0.50},
    "micro_led": {"macro_weight": 0.40, "micro_weight": 0.60},
}

DEFAULT_PROFILE = "default"


def profile_for_trigger(trigger: object) -> dict[str, float]:
    """根据 trigger 返回权重 profile。未知/None → default。"""
    name = str(trigger or "").strip().lower()
    return WEIGHT_PROFILES.get(name, WEIGHT_PROFILES[DEFAULT_PROFILE])
