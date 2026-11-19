# -*- coding: utf-8 -*-
"""P0-D3D: Presentation Assist 请求与成品契约。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

FORMATS = frozenset({"docx", "pdf", "pptx", "xlsx", "html", "chart"})
ARTIFACT_STATUSES = frozenset({"DRAFT", "VERIFIED"})


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
class PresentationRequest:
    request_id: str
    ticket_id: str
    format: str
    audience: str
    template: str
    language: str
    length: str
    required_sections: Tuple[str, ...] = ()
    allow_supplementary_research: bool = False
    fact_bundle_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "format", str(self.format or "").lower())
        object.__setattr__(self, "required_sections", _as_tuple(self.required_sections))

    def validate(self) -> List[str]:
        errors: List[str] = []
        if self.format not in FORMATS:
            errors.append("unsupported_format")
        if not self.request_id:
            errors.append("request_id_required")
        if not self.ticket_id:
            errors.append("ticket_id_required")
        if not self.fact_bundle_id:
            errors.append("fact_bundle_required")
        return errors

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "ticket_id": self.ticket_id,
            "format": self.format,
            "audience": self.audience,
            "template": self.template,
            "language": self.language,
            "length": self.length,
            "required_sections": list(self.required_sections),
            "allow_supplementary_research": self.allow_supplementary_research,
            "fact_bundle_id": self.fact_bundle_id,
        }


@dataclass(frozen=True)
class PresentationArtifact:
    artifact_id: str
    uri: str
    format: str
    renderer: str
    fact_bundle_hash: str
    fact_refs: Tuple[str, ...] = ()
    supplementary_refs: Tuple[str, ...] = ()
    fact_usage_manifest: str = ""
    status: str = "DRAFT"
    consistency_report: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "format", str(self.format or "").lower())
        object.__setattr__(self, "status", str(self.status or "DRAFT"))
        object.__setattr__(self, "fact_refs", _as_tuple(self.fact_refs))
        object.__setattr__(self, "supplementary_refs", _as_tuple(self.supplementary_refs))

    def validate(self) -> List[str]:
        errors: List[str] = []
        if not self.artifact_id:
            errors.append("artifact_id_required")
        if not self.uri:
            errors.append("uri_required")
        if self.format not in FORMATS:
            errors.append("unsupported_format")
        if not self.fact_bundle_hash:
            errors.append("fact_bundle_hash_required")
        if not self.fact_usage_manifest:
            errors.append("fact_usage_manifest_required")
        if self.status not in ARTIFACT_STATUSES:
            errors.append("invalid_status")
        return errors

    def to_dict(self) -> Dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "uri": self.uri,
            "format": self.format,
            "renderer": self.renderer,
            "fact_bundle_hash": self.fact_bundle_hash,
            "fact_refs": list(self.fact_refs),
            "supplementary_refs": list(self.supplementary_refs),
            "fact_usage_manifest": self.fact_usage_manifest,
            "status": self.status,
            "consistency_report": self.consistency_report,
        }
