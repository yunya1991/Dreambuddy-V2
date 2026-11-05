"""batch_schema.py — E2 统一「生成批 → verify」schema（SPEC v0.5 §4 E2 P1 M2）。

仓内两个做梦器空间不同：
  - 33-REA `DreamingLoop.dream()` → 分析编排配置（analyzer_sequence/budget/parallelism）
  - 4-MEMORY `run_dreaming_cycle()` → 记忆卫生（重复合并）
本模块定义**同一批信封**（envelope）承载二者产出，逐项标注 `space`，
使 M2 判据（新颖且 verify 成功 / 总生成数）在任一空间都可计算。

统一项字段：variant_id / struct_vector / vector_hash / novelty / gate / verify / space / transform。
判据悬置（无结构向量 = 非策略结构空间）时 novelty.is_human_written=None，绝不伪造为 False。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "1.0"

ENVELOPE_KEYS = (
    "schema_version",
    "batch_id",
    "generated_at",
    "generator",
    "space",
    "items",
    "stats",
)

_SUSPENDED_NOVELTY = {
    "is_human_written": None,
    "min_distance": None,
    "nearest_config_id": None,
    "reason": "space_has_no_struct_vector_判据悬置",
    "vector_hash": None,
}

_NOT_VERIFIED = {"success": None, "evaluated_by": None, "reason": "not_evaluated"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_batch_id(generator: str, space: str, n: int) -> str:
    seed = f"{generator}|{space}|{n}|{_now()}"
    return f"BATCH-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{hashlib.sha256(seed.encode()).hexdigest()[:8]}"


def _normalize_item(item: Dict[str, Any], space: str) -> Dict[str, Any]:
    return {
        "variant_id": str(item.get("variant_id", "")),
        "struct_vector": item.get("struct_vector"),
        "vector_hash": item.get("vector_hash"),
        "novelty": dict(item.get("novelty") or _SUSPENDED_NOVELTY),
        "gate": dict(item.get("gate") or {"admitted": False, "reasons": ["not_gated"]}),
        "verify": dict(item.get("verify") or _NOT_VERIFIED),
        "space": space,
        "transform": item.get("transform"),
    }


def compute_stats(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """M2 = (verify 成功 且 编辑距离>=k，即 is_human_written is False) / 总生成数。"""
    n = len(items)
    n_novel = sum(1 for i in items if i["novelty"].get("is_human_written") is False)
    n_verified = sum(1 for i in items if i["verify"].get("evaluated_by"))
    n_verified_success = sum(1 for i in items if i["verify"].get("success") is True)
    n_novel_verified = sum(
        1
        for i in items
        if i["novelty"].get("is_human_written") is False and i["verify"].get("success") is True
    )
    n_gate_admitted = sum(1 for i in items if i["gate"].get("admitted") is True)
    return {
        "n_generated": n,
        "n_novel": n_novel,
        "n_verified": n_verified,
        "n_verified_success": n_verified_success,
        "n_gate_admitted": n_gate_admitted,
        "n_novel_verified": n_novel_verified,
        "m2_ratio": (n_novel_verified / n) if n else 0.0,
    }


def build_batch(
    generator: str,
    space: str,
    items: List[Dict[str, Any]],
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """构造统一批次信封。meta 合并进 stats 之外的顶层字段（如 feedback/evaluator）。"""
    normalized = [_normalize_item(i, space) for i in items]
    batch: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "batch_id": _make_batch_id(generator, space, len(normalized)),
        "generated_at": _now(),
        "generator": generator,
        "space": space,
        "items": normalized,
        "stats": compute_stats(normalized),
    }
    if meta:
        batch["meta"] = dict(meta)
    return batch


def adapter_rea_dreaming(rea_result: Dict[str, Any]) -> Dict[str, Any]:
    """33-REA `DreamingLoop.dream()` 输出 → 统一批次。编排空间无结构向量 → 判据悬置。"""
    items: List[Dict[str, Any]] = []
    candidates = rea_result.get("candidates") or []
    for idx, cand in enumerate(candidates):
        strategy = cand.get("strategy") or {}
        items.append(
            {
                "variant_id": f"REA-{idx}",
                "struct_vector": None,
                "vector_hash": None,
                "novelty": dict(_SUSPENDED_NOVELTY),
                "gate": {"admitted": False, "reasons": ["gate_not_applicable_rea_space"]},
                "verify": dict(_NOT_VERIFIED),
                "transform": strategy.get("transform", "current"),
            }
        )
    return build_batch(
        generator="rea_dreaming",
        space="rea_orchestration_config",
        items=items,
        meta={
            "best_v": rea_result.get("best_v"),
            "current_v": rea_result.get("current_v"),
            "improved": rea_result.get("improved"),
        },
    )


def adapter_memory_dreaming(mem_result: Dict[str, Any]) -> Dict[str, Any]:
    """4-MEMORY `run_dreaming_cycle()` 输出 → 统一批次。记忆卫生空间无结构向量。"""
    items: List[Dict[str, Any]] = []
    for idx, _cand in enumerate(mem_result.get("merge_candidates") or []):
        items.append(
            {
                "variant_id": f"MEM-{idx}",
                "struct_vector": None,
                "vector_hash": None,
                "novelty": dict(_SUSPENDED_NOVELTY),
                "gate": {"admitted": False, "reasons": ["gate_not_applicable_memory_space"]},
                "verify": dict(_NOT_VERIFIED),
            }
        )
    return build_batch(
        generator="memory_dreaming",
        space="memory_hygiene",
        items=items,
        meta={"dedupe_ratio": mem_result.get("dedupe_ratio")},
    )


def write_batch(batch: Dict[str, Any], path) -> bool:
    """落盘批次（JSON）。FAIL-OPEN。"""
    try:
        from pathlib import Path

        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception:  # noqa: BLE001 — FAIL-OPEN
        return False
