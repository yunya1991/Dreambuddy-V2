# -*- coding: utf-8 -*-
"""P0-D3D: 证据包（EvidenceBundle）。证据必须可追溯、可重放。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

SOURCE_TYPES = frozenset({"data", "code", "log", "experiment", "artifact"})
_REPLAY_REQUIRED = frozenset({"data", "code", "log"})


@dataclass(frozen=True)
class EvidenceItem:
    ref_id: str
    source_type: str
    uri: str
    content_hash: str
    collected_at: float = 0.0
    replay_cmd: str = ""
    excerpt: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_type", str(self.source_type or "").lower())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ref_id": self.ref_id,
            "source_type": self.source_type,
            "uri": self.uri,
            "content_hash": self.content_hash,
            "collected_at": self.collected_at,
            "replay_cmd": self.replay_cmd,
            "excerpt": self.excerpt,
        }


@dataclass(frozen=True)
class EvidenceBundle:
    bundle_id: str
    trace_id: str
    items: Tuple[EvidenceItem, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", tuple(self.items or ()))

    def validate(self) -> List[str]:
        errors: List[str] = []
        if not self.items:
            errors.append("evidence_required")
        for item in self.items:
            if not isinstance(item, EvidenceItem):
                errors.append("invalid_evidence")
                continue
            if item.source_type not in SOURCE_TYPES:
                errors.append(f"invalid_source_type:{item.ref_id}")
            if not item.uri:
                errors.append(f"uri_required:{item.ref_id}")
            if not item.content_hash:
                errors.append("content_hash_required")
            if item.source_type in _REPLAY_REQUIRED and not item.replay_cmd:
                errors.append("replay_cmd_required")
        return errors

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "trace_id": self.trace_id,
            "items": [i.to_dict() for i in self.items],
        }
