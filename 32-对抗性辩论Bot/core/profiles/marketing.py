"""profiles/marketing.py — 营销内容 profile（保持原 32 Bot 行为）。"""

from __future__ import annotations

from core.profiles.base import DebateProfile
from core.prompts import (
    BEAR_SYSTEM_PROMPT,
    BULL_SYSTEM_PROMPT,
    JUDGE_SYSTEM_PROMPT,
)

MARKETING_PROFILE = DebateProfile(
    name="marketing",
    bull_system_prompt=BULL_SYSTEM_PROMPT,
    bear_system_prompt=BEAR_SYSTEM_PROMPT,
    judge_system_prompt=JUDGE_SYSTEM_PROMPT,
    marketing=True,
    technical=False,
    signal=False,
    evidence_required=False,
)
