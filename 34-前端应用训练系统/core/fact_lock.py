# -*- coding: utf-8 -*-
"""P0-D3D: FactLock（事实锁）与 FactUsageManifest（E8 关闭项）。

Core Facts 由 DSH 冻结；表达层只能引用、排版、可视化。
"""

from __future__ import annotations

import hashlib
import json
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


def _canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)


def _sha256(payload: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CanonicalFact:
    fact_id: str
    name: str
    value: Any
    unit: str
    as_of: str
    source_ref: str
    content_hash: str = ""
    confidence: float = 0.0
    caveat: str = ""

    def payload(self) -> Dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "as_of": self.as_of,
            "source_ref": self.source_ref,
            "confidence": self.confidence,
            "caveat": self.caveat,
        }

    def to_dict(self) -> Dict[str, Any]:
        data = self.payload()
        data["content_hash"] = self.content_hash
        return data


@dataclass(frozen=True)
class CanonicalFactBundle:
    bundle_id: str
    facts: Tuple[CanonicalFact, ...]
    bundle_hash: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "facts": [f.to_dict() for f in self.facts],
            "bundle_hash": self.bundle_hash,
        }


def freeze_facts(facts: Any, bundle_id: str = "FB-1") -> CanonicalFactBundle:
    frozen: List[CanonicalFact] = []
    for fact in facts or ():
        if not isinstance(fact, CanonicalFact):
            continue
        digest = fact.content_hash or _sha256(fact.payload())
        frozen.append(CanonicalFact(**{**fact.__dict__, "content_hash": digest}))
    bundle_hash = _sha256([f.to_dict() for f in frozen])
    return CanonicalFactBundle(bundle_id=bundle_id, facts=tuple(frozen), bundle_hash=bundle_hash)


@dataclass(frozen=True)
class FactUsage:
    claim_id: str
    fact_id: str
    location: str
    rendered_value: str
    transform: str = "identity"
    formula: str = ""


@dataclass(frozen=True)
class ChartSpec:
    chart_id: str
    chart_type: str
    source_fact_ids: Tuple[str, ...] = ()
    unit: str = ""
    x: str = ""
    y: str = ""
    axis: Dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_fact_ids", _as_tuple(self.source_fact_ids))
        object.__setattr__(self, "axis", dict(self.axis or {}))


@dataclass(frozen=True)
class CaveatManifest:
    caveat_id: str
    location: str
    text: str
    source: str = ""


@dataclass(frozen=True)
class FactUsageManifest:
    artifact_id: str
    fact_usages: Tuple[FactUsage, ...] = ()
    unmapped_claims: Tuple[str, ...] = ()
    chart_specs: Tuple[ChartSpec, ...] = ()
    caveats: Tuple[CaveatManifest, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "fact_usages", tuple(self.fact_usages or ()))
        object.__setattr__(self, "unmapped_claims", _as_tuple(self.unmapped_claims))
        object.__setattr__(self, "chart_specs", tuple(self.chart_specs or ()))
        object.__setattr__(self, "caveats", tuple(self.caveats or ()))

    def validate(self) -> List[str]:
        errors: List[str] = []
        if not self.fact_usages:
            errors.append("fact_usage_required")
        if self.unmapped_claims:
            errors.append("unmapped_claims")
        for usage in self.fact_usages:
            if not isinstance(usage, FactUsage):
                errors.append("invalid_fact_usage")
                continue
            if not usage.fact_id:
                errors.append(f"fact_id_required:{usage.claim_id}")
            if not usage.location:
                errors.append(f"location_required:{usage.claim_id}")
        for chart in self.chart_specs:
            if not isinstance(chart, ChartSpec):
                errors.append("invalid_chart_spec")
                continue
            if not chart.source_fact_ids:
                errors.append(f"chart_source_required:{chart.chart_id}")
        for caveat in self.caveats:
            if not isinstance(caveat, CaveatManifest):
                errors.append("invalid_caveat")
                continue
            if not caveat.text:
                errors.append(f"caveat_text_required:{caveat.caveat_id}")
        return errors

    def to_dict(self) -> Dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "fact_usages": [u.__dict__ for u in self.fact_usages],
            "unmapped_claims": list(self.unmapped_claims),
            "chart_specs": [
                {**c.__dict__, "source_fact_ids": list(c.source_fact_ids)} for c in self.chart_specs
            ],
            "caveats": [c.__dict__ for c in self.caveats],
        }


@dataclass(frozen=True)
class ChartSeries:
    name: str
    x: Tuple[Any, ...] = ()
    y: Tuple[float, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "x", tuple(self.x or ()))
        object.__setattr__(self, "y", tuple(float(v) for v in (self.y or ())))


@dataclass(frozen=True)
class ChartData:
    chart_id: str
    series: Tuple[ChartSeries, ...] = ()
    source_fact_ids: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "series", tuple(self.series or ()))
        object.__setattr__(self, "source_fact_ids", _as_tuple(self.source_fact_ids))

    def validate(self) -> List[str]:
        errors: List[str] = []
        if not self.chart_id:
            errors.append("chart_id_required")
        if not self.series:
            errors.append("series_required")
        if not self.source_fact_ids:
            errors.append("source_fact_ids_required")
        for series in self.series:
            if not isinstance(series, ChartSeries):
                errors.append("invalid_series")
                continue
            if len(series.x) != len(series.y):
                errors.append(f"series_length_mismatch:{series.name}")
        return errors


def validate_chart_data(chart_data: Any, specs: Any) -> List[str]:
    """校验 chart_data 与 ChartSpec 的 chart_id / source_fact_ids 一致。"""
    items = chart_data if isinstance(chart_data, (list, tuple)) else ()
    spec_map = {spec.chart_id: spec for spec in (specs or ()) if isinstance(spec, ChartSpec)}
    errors: List[str] = []
    for data in items:
        if not isinstance(data, ChartData):
            errors.append("invalid_chart_data")
            continue
        errors.extend(data.validate())
        spec = spec_map.get(data.chart_id)
        if spec is None:
            errors.append(f"chart_spec_missing:{data.chart_id}")
            continue
        if set(data.source_fact_ids) != set(spec.source_fact_ids):
            errors.append(f"chart_source_mismatch:{data.chart_id}")
    return errors


@dataclass(frozen=True)
class FactConsistencyReport:
    report_id: str
    matched: int = 0
    missing: int = 0
    extra: int = 0
    changed: int = 0
    contradictions: Tuple[str, ...] = ()
    unmapped_claims: int = 0
    manifest_missing: bool = False
    chart_mismatch: int = 0
    caveat_missing: int = 0
    verdict: str = "fail"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "matched": self.matched,
            "missing": self.missing,
            "extra": self.extra,
            "changed": self.changed,
            "contradictions": list(self.contradictions),
            "unmapped_claims": self.unmapped_claims,
            "manifest_missing": self.manifest_missing,
            "chart_mismatch": self.chart_mismatch,
            "caveat_missing": self.caveat_missing,
            "verdict": self.verdict,
        }
