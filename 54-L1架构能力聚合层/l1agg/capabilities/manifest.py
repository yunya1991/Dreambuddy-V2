# -*- coding: utf-8 -*-
"""能力注册表加载与校验（`capability_manifest.yaml` 为唯一事实源）。

SPEC-54 §3.3 / §11.4：
  - 能力 ID `D-*` 只在 TECHNICAL_DESIGN 登记，本文件只做「能力 → 意图/scope/方法」绑定；
  - 校验失败直接抛 `ManifestError`（禁止能力引用未实现方法、禁止重复 id/意图漂移）；
  - 本模块无副作用、不读库，供 L1 执行器与测试共用。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

import yaml

from ..methods import REGISTRY
from ..methods import get as get_method

MANIFEST_FILE = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "capability_manifest.yaml")
)
_REQUIRED = ("id", "intent", "mode", "data_scope", "executor", "methods", "min_n")
_MODES = ("deterministic", "gated")


class ManifestError(ValueError):
    """能力注册表契约错误。"""


@dataclass(frozen=True)
class Capability:
    id: str
    intent: str
    mode: str
    data_scope: Tuple[str, ...]
    executor: str
    methods: Tuple[str, ...]
    min_n: int
    min_span_days: int = 0
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "intent": self.intent,
            "mode": self.mode,
            "data_scope": list(self.data_scope),
            "executor": self.executor,
            "methods": list(self.methods),
            "min_n": self.min_n,
            "min_span_days": self.min_span_days,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class Manifest:
    version: int
    updated: str
    capabilities: Tuple[Capability, ...] = field(default_factory=tuple)

    def get(self, capability_id: str) -> Capability:
        for cap in self.capabilities:
            if cap.id == capability_id:
                return cap
        raise ManifestError(f"unknown capability: {capability_id}")

    def by_intent(self, intent: str) -> List[Capability]:
        return [cap for cap in self.capabilities if cap.intent == intent]

    def intents(self) -> List[str]:
        seen: List[str] = []
        for cap in self.capabilities:
            if cap.intent not in seen:
                seen.append(cap.intent)
        return seen


def load(path: Optional[str] = None) -> Manifest:
    target = path or MANIFEST_FILE
    with open(target, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    caps = tuple(_capability(item) for item in raw.get("capabilities") or ())
    manifest = Manifest(
        version=int(raw.get("version", 0)), updated=str(raw.get("updated", "")), capabilities=caps
    )
    validate(manifest)
    return manifest


def _capability(item: Any) -> Capability:
    if not isinstance(item, dict):
        raise ManifestError(f"capability 必须是 mapping: {item!r}")
    missing = [key for key in _REQUIRED if key not in item]
    if missing:
        raise ManifestError(f"capability {item.get('id')!r} 缺少字段: {missing}")
    methods = tuple(str(m) for m in item["methods"])
    return Capability(
        id=str(item["id"]),
        intent=str(item["intent"]),
        mode=str(item["mode"]),
        data_scope=tuple(str(s) for s in item["data_scope"]),
        executor=str(item["executor"]),
        methods=methods,
        min_n=int(item["min_n"]),
        min_span_days=int(item.get("min_span_days", 0)),
        notes=str(item.get("notes", "")),
    )


def validate(manifest: Manifest) -> None:
    """结构 + 方法引用校验；任一违规抛 ManifestError。"""
    if manifest.version < 1:
        raise ManifestError("version 必须 >= 1")
    ids, intents = set(), {}
    for cap in manifest.capabilities:
        if not cap.id.startswith("D-"):
            raise ManifestError(f"能力 ID 必须以 D- 开头: {cap.id}")
        if cap.id in ids:
            raise ManifestError(f"重复能力 ID: {cap.id}")
        ids.add(cap.id)
        if cap.mode not in _MODES:
            raise ManifestError(f"{cap.id}: mode 必须是 {_MODES}")
        if not cap.data_scope:
            raise ManifestError(f"{cap.id}: data_scope 不可为空")
        if cap.min_n < 0:
            raise ManifestError(f"{cap.id}: min_n 不可为负")
        if not cap.methods:
            raise ManifestError(f"{cap.id}: 必须绑定至少一个方法")
        for method_id in cap.methods:
            spec = REGISTRY.get(method_id) or get_method(method_id)
            if spec is None or not spec.implemented:
                raise ManifestError(f"{cap.id}: 方法 {method_id} 未实现，禁止绑定")
            if spec.min_n > cap.min_n:
                raise ManifestError(
                    f"{cap.id}: 能力 min_n={cap.min_n} 小于方法 {method_id} 的 min_n={spec.min_n}"
                )
        intents.setdefault(cap.intent, []).append(cap.id)
    for intent, cap_ids in intents.items():
        modes = {manifest.get(cid).mode for cid in cap_ids}
        if len(modes) > 1:
            raise ManifestError(f"意图 {intent} 下 mode 不一致: {sorted(modes)}")


def validate_execution(
    manifest: Manifest,
    executed: Mapping[str, Iterable[str]],
    *,
    require_complete: bool = True,
) -> Dict[str, Any]:
    """校验跨场景累计的真实方法调用，并返回绑定覆盖率。

    条件分支不要求单次调用覆盖全部方法；调用方应把各分支实际成功执行的方法
    按能力聚合后传入。未绑定调用永远拒绝，`require_complete=True` 时还拒绝
    只在 manifest 声明、从未真实执行的方法。
    """
    capability_ids = {cap.id for cap in manifest.capabilities}
    unknown = sorted(set(executed) - capability_ids)
    if unknown:
        raise ManifestError(f"执行覆盖包含未登记能力: {unknown}")

    rows: Dict[str, Any] = {}
    incomplete: List[str] = []
    declared_total = 0
    executed_total = 0
    for cap in manifest.capabilities:
        declared = set(cap.methods)
        actual = set(executed.get(cap.id, ()))
        unbound = sorted(actual - declared)
        if unbound:
            raise ManifestError(f"{cap.id}: 执行了未绑定方法: {unbound}")
        covered = actual & declared
        missing = sorted(declared - actual)
        if missing:
            incomplete.append(f"{cap.id}={missing}")
        declared_total += len(declared)
        executed_total += len(covered)
        rows[cap.id] = {
            "declared": sorted(declared),
            "executed": sorted(covered),
            "missing": missing,
            "coverage": len(covered) / len(declared) if declared else 1.0,
        }

    if require_complete and incomplete:
        raise ManifestError("manifest 方法执行覆盖不足: " + "; ".join(incomplete))
    return {
        "summary": {
            "declared": declared_total,
            "executed": executed_total,
            "missing": declared_total - executed_total,
            "coverage": executed_total / declared_total if declared_total else 1.0,
        },
        "capabilities": rows,
    }


_CACHE: Optional[Manifest] = None


def manifest() -> Manifest:
    global _CACHE
    if _CACHE is None:
        _CACHE = load()
    return _CACHE


def get_capability(capability_id: str) -> Capability:
    return manifest().get(capability_id)
