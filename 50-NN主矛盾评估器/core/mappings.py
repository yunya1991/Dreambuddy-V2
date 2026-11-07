"""50 自有的 source 映射表（禁止复用 23 的键，否则 11-* 源退化为 C3/0.05）。"""

from __future__ import annotations

VALID_DIMENSIONS = {"D1", "D2", "D3", "D4", "C6", "C7", "C8", "NEWS"}
VALID_HORIZONS = {"minutes", "hours", "days", "weeks"}
VALID_INTENTS = {"trend", "reversal", "event_shock"}

CONSTRAINT_SOURCES = {"40-cycle", "43-strategic"}
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
    "40-cycle": 0.0,
    "43-strategic": 0.0,
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
    "23-contradiction": "C3",
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
    "event": "29-event",
    "contradiction": "23-contradiction",
}

DEFAULT_DIMENSION = "C3"
DEFAULT_WEIGHT = 0.05
DEFAULT_HORIZON = "hours"


def normalize_source(source: object) -> str:
    value = str(source or "").strip().lower()
    return SOURCE_ALIASES.get(value, value)


def role_of(source: object) -> str:
    name = normalize_source(source)
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
