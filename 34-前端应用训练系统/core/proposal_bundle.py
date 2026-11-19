# -*- coding: utf-8 -*-
"""P0-D3D: Hermes 提案包（ProposalBundle）。只提案，不指挥 DSH。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple


def _as_tuple(value: Any) -> Tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    try:
        return tuple(str(v) for v in value)
    except TypeError:
        return ()


@dataclass(frozen=True)
class ProposalOption:
    option_id: str
    title: str
    assumptions: Tuple[str, ...] = ()
    risks: Tuple[str, ...] = ()
    expected_effect: str = ""
    evidence_refs: Tuple[str, ...] = ()
    dissent: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "assumptions", _as_tuple(self.assumptions))
        object.__setattr__(self, "risks", _as_tuple(self.risks))
        object.__setattr__(self, "evidence_refs", _as_tuple(self.evidence_refs))
        object.__setattr__(self, "dissent", _as_tuple(self.dissent))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "option_id": self.option_id,
            "title": self.title,
            "assumptions": list(self.assumptions),
            "risks": list(self.risks),
            "expected_effect": self.expected_effect,
            "evidence_refs": list(self.evidence_refs),
            "dissent": list(self.dissent),
        }


@dataclass(frozen=True)
class ProposalBundle:
    bundle_id: str
    ticket_id: str
    options: Tuple[ProposalOption, ...] = ()
    dissent: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "options", tuple(self.options or ()))
        object.__setattr__(self, "dissent", _as_tuple(self.dissent))

    def validate(self) -> List[str]:
        errors: List[str] = []
        if not self.options:
            errors.append("option_required")
        for option in self.options:
            if not isinstance(option, ProposalOption):
                errors.append("invalid_option")
                continue
            if not option.assumptions:
                errors.append(f"assumptions_required:{option.option_id}")
            if not option.risks:
                errors.append(f"risks_required:{option.option_id}")
            if not option.evidence_refs:
                errors.append(f"evidence_required:{option.option_id}")
        return errors

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "ticket_id": self.ticket_id,
            "options": [o.to_dict() for o in self.options],
            "dissent": list(self.dissent),
        }
