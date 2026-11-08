"""profiles — 辩论业务 profile 注册表。

默认 `marketing` 保持原 32 Bot 行为；`technical` / `signal` 用于 C-Drive 与
技术红队。profile 只换角色设定/输出语义，不换通用辩论循环。
"""
from __future__ import annotations

from core.profiles.base import DebateProfile
from core.profiles.marketing import MARKETING_PROFILE
from core.profiles.signal import SIGNAL_PROFILE
from core.profiles.technical import TECHNICAL_PROFILE

PROFILES: dict[str, DebateProfile] = {
    profile.name: profile
    for profile in (MARKETING_PROFILE, TECHNICAL_PROFILE, SIGNAL_PROFILE)
}

PROFILE_NAMES = tuple(PROFILES)


def get_profile(value: str | DebateProfile | None) -> DebateProfile:
    """按名称/对象取 profile；None 默认 marketing。"""
    if isinstance(value, DebateProfile):
        return value
    name = (value or "marketing").strip().lower()
    try:
        return PROFILES[name]
    except KeyError as exc:
        raise ValueError(
            f"未知 debate profile: {name!r}（可选: {', '.join(PROFILE_NAMES)}）"
        ) from exc


__all__ = [
    "DebateProfile", "PROFILES", "PROFILE_NAMES", "get_profile",
    "MARKETING_PROFILE", "TECHNICAL_PROFILE", "SIGNAL_PROFILE",
]