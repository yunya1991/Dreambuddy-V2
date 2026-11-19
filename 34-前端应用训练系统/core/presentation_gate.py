# -*- coding: utf-8 -*-
"""P0-D3D: FactGate（表达事实一致性门）与逐格式事实提取。

manifest 为主、抽取为辅；未映射事实/图表不一致/风险缺失一律 fail。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from core.fact_lock import (
    CanonicalFactBundle,
    FactConsistencyReport,
    FactUsageManifest,
)
from core.presentation_contract import PresentationArtifact

_NUMBER_RE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?%?")


def _parse_number(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip().replace(",", "")
    if text.endswith("%"):
        text = text[:-1]
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _tolerance(fact_value: float, transform: str) -> float:
    if transform == "rounded":
        return max(0.01, abs(fact_value) * 0.01)
    return max(1e-6, abs(fact_value) * 0.001)


def _fact_map(bundle: Any) -> Dict[str, Any]:
    if not isinstance(bundle, CanonicalFactBundle):
        return {}
    return {fact.fact_id: fact for fact in bundle.facts}


def evaluate_presentation(
    artifact: Any,
    manifest: Any,
    bundle: Any,
) -> FactConsistencyReport:
    """FAIL-CLOSED：非法输入直接 fail。"""
    if not isinstance(artifact, PresentationArtifact):
        return FactConsistencyReport("CR-invalid", verdict="fail")
    if not isinstance(manifest, FactUsageManifest):
        return FactConsistencyReport("CR-invalid", verdict="fail")
    if not isinstance(bundle, CanonicalFactBundle):
        return FactConsistencyReport("CR-invalid", verdict="fail")

    facts = _fact_map(bundle)
    matched = 0
    missing = 0
    changed = 0
    chart_mismatch = 0
    caveat_missing = 0
    contradictions: List[str] = []

    for usage in manifest.fact_usages:
        fact = facts.get(usage.fact_id)
        if fact is None:
            missing += 1
            continue
        if usage.transform in {"unit_converted", "derived"} and not usage.formula:
            changed += 1
            contradictions.append(f"formula_required:{usage.claim_id}")
            continue
        rendered = _parse_number(usage.rendered_value)
        expected = _parse_number(fact.value)
        if rendered is None or expected is None:
            changed += 1
            contradictions.append(f"unparseable:{usage.claim_id}")
            continue
        if abs(rendered - expected) > _tolerance(expected, usage.transform):
            changed += 1
            contradictions.append(f"value_changed:{usage.claim_id}")
        else:
            matched += 1

    for chart in manifest.chart_specs:
        if any(fid not in facts for fid in chart.source_fact_ids):
            chart_mismatch += 1

    caveat_texts = {caveat.text for caveat in manifest.caveats if caveat.text}
    for fact in bundle.facts:
        if fact.caveat and fact.caveat not in caveat_texts:
            caveat_missing += 1

    manifest_missing = not bool(artifact.fact_usage_manifest)
    unmapped = len(manifest.unmapped_claims)

    if (
        changed
        or missing
        or contradictions
        or unmapped
        or manifest_missing
        or chart_mismatch
        or caveat_missing
    ):
        verdict = "fail"
    elif manifest.validate():
        verdict = "degraded"
    else:
        verdict = "pass"

    return FactConsistencyReport(
        report_id="CR-1",
        matched=matched,
        missing=missing,
        extra=unmapped,
        changed=changed,
        contradictions=tuple(contradictions),
        unmapped_claims=unmapped,
        manifest_missing=manifest_missing,
        chart_mismatch=chart_mismatch,
        caveat_missing=caveat_missing,
        verdict=verdict,
    )


def _collect_text(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    if not isinstance(payload, dict):
        return ""
    parts: List[str] = []
    for key in ("paragraphs", "tables", "slides", "cells", "text", "chart_data"):
        value = payload.get(key)
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, dict):
            parts.extend(str(v) for v in value.values())
        elif isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    parts.extend(str(v) for v in item.values())
                elif isinstance(item, (list, tuple)):
                    parts.extend(str(v) for v in item)
    return " ".join(parts)


def extract_facts(format: str, payload: Any) -> List[str]:
    """Phase 1 fixture 适配器：从结构化 payload 提取数字；扫描 PDF 明确拒绝。"""
    fmt = str(format or "").lower()
    if fmt == "pdf" and isinstance(payload, dict) and payload.get("scanned"):
        raise ValueError("scanned_pdf_unsupported")
    if fmt not in {"docx", "pptx", "xlsx", "pdf", "html", "chart"}:
        return []
    text = _collect_text(payload)
    return _NUMBER_RE.findall(text)
