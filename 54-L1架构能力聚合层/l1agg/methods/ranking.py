# -*- coding: utf-8 -*-
"""方法基座与动态排名（SPEC-54-L1交易层 §4.0 / §5.0；LT-G11 / LT-G12）。

分工：
  - **基座（baseline）**：5 个方法 ID（I35–I39）+ 6 条机制，永久占位，不参与排名竞争；
  - **动态排名（ranking）**：其余方法按 `abs(IC) × 稳定性` 竞争非基座槽位，每槽位 TopK；
  - **增量保护（blend_axis）**：排名方法的修饰幅度 ≤20% 且不得反转基座轴符号。

本模块为纯函数：不取数、不写库、不做统计。`reliability` / `stability` / `sample_n`
一律由调用方（能力层）给出，避免在方法层重复计算口径。

门禁：
  - LT-G11：`baseline ∩ ranked = ∅`；基座方法 ID 全部已实现；6 条机制缺一即报错。
  - LT-G12：`sign(axis_after) == sign(axis_baseline)` 且相对偏差 ≤ `max_rel`。
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import yaml

from .registry import MethodSpec, RegistryError, all_specs

_MODULE_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)
BASELINE_CONFIG = os.path.join(_MODULE_ROOT, "config", "baseline_methods.yaml")
RANK_CONFIG = os.path.join(_MODULE_ROOT, "config", "method_rank.yaml")

# 基座契约（改动必须同步 SPEC §4.0 与 spec_version）
REQUIRED_BASELINE_METHODS: Tuple[str, ...] = ("I35", "I36", "I37", "I38", "I39")
REQUIRED_MECHANISMS: Tuple[str, ...] = (
    "midas",
    "taylor_gap",
    "fci",
    "vintage",
    "uncertainty",
    "equal_weight_control",
)
DEFAULT_MAX_REL = 0.20


class BaselineConfigError(RegistryError):
    """基座配置不完整 / 非法。"""


@dataclass(frozen=True)
class BaselineConfig:
    """基座固化的运行时视图。"""

    version: str
    method_ids: Tuple[str, ...]
    mechanisms: Tuple[str, ...]
    axes: Mapping[str, str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "method_ids": list(self.method_ids),
            "mechanisms": list(self.mechanisms),
            "axes": dict(self.axes),
        }


@dataclass(frozen=True)
class RankConfig:
    """动态排名参数。"""

    version: str
    window: int = 250
    purge: int = 10
    embargo: int = 10
    topk: int = 2
    min_obs: int = 250
    stability_weight: float = 1.0
    tie_break: str = "method_id"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "window": self.window,
            "purge": self.purge,
            "embargo": self.embargo,
            "topk": self.topk,
            "min_obs": self.min_obs,
            "stability_weight": self.stability_weight,
            "tie_break": self.tie_break,
        }


def _read_yaml(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        raise BaselineConfigError(f"配置文件不存在: {path}")
    with open(path, "r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if not isinstance(raw, Mapping):
        raise BaselineConfigError(f"配置根必须是 mapping: {path}")
    return dict(raw)


def load_baseline(path: Optional[str] = None) -> BaselineConfig:
    """读取并校验基座配置（fail-closed，绝不静默降级）。"""
    raw = _read_yaml(path or BASELINE_CONFIG)
    methods = raw.get("methods") or []
    mechanisms = raw.get("mechanisms") or []
    if not isinstance(methods, Sequence) or not isinstance(mechanisms, Sequence):
        raise BaselineConfigError("methods/mechanisms 必须是列表")

    enabled_ids: List[str] = []
    axes: Dict[str, str] = {}
    for item in methods:
        if not isinstance(item, Mapping):
            raise BaselineConfigError("methods 条目必须是 mapping")
        method_id = str(item.get("id") or "").strip()
        if not method_id:
            raise BaselineConfigError("methods[].id 不能为空")
        if not bool(item.get("enabled", True)):
            raise BaselineConfigError(f"基座方法禁止停用: {method_id}")
        spec = _REGISTRY_GET(method_id)
        if spec is None:
            raise BaselineConfigError(f"基座方法未在方法库登记: {method_id}")
        if not spec.implemented:
            raise BaselineConfigError(f"基座方法尚未实现: {method_id}")
        enabled_ids.append(method_id)
        axes[method_id] = str(item.get("axis") or "")

    missing = [m for m in REQUIRED_BASELINE_METHODS if m not in enabled_ids]
    extra = [m for m in enabled_ids if m not in REQUIRED_BASELINE_METHODS]
    if missing or extra:
        raise BaselineConfigError(
            f"基座方法集必须恰为 {list(REQUIRED_BASELINE_METHODS)}；缺 {missing} / 多 {extra}"
        )

    enabled_keys: List[str] = []
    for item in mechanisms:
        if not isinstance(item, Mapping):
            raise BaselineConfigError("mechanisms 条目必须是 mapping")
        key = str(item.get("key") or "").strip()
        if not key:
            raise BaselineConfigError("mechanisms[].key 不能为空")
        if not bool(item.get("enabled", True)):
            raise BaselineConfigError(f"基座机制禁止停用: {key}")
        enabled_keys.append(key)

    missing_keys = [k for k in REQUIRED_MECHANISMS if k not in enabled_keys]
    extra_keys = [k for k in enabled_keys if k not in REQUIRED_MECHANISMS]
    if missing_keys or extra_keys:
        raise BaselineConfigError(
            f"基座机制必须恰为 {list(REQUIRED_MECHANISMS)}；缺 {missing_keys} / 多 {extra_keys}"
        )

    version = str(raw.get("version") or "").strip()
    if not version:
        raise BaselineConfigError("baseline.version 不能为空")
    return BaselineConfig(
        version=version,
        method_ids=tuple(enabled_ids),
        mechanisms=tuple(enabled_keys),
        axes=axes,
    )


def _REGISTRY_GET(method_id: str) -> Optional[MethodSpec]:
    from .registry import REGISTRY

    return REGISTRY.get(method_id)


def load_rank_config(path: Optional[str] = None) -> RankConfig:
    """读取排名参数；非法值 fail-closed。"""
    raw = _read_yaml(path or RANK_CONFIG)
    try:
        config = RankConfig(
            version=str(raw.get("version") or "mr-unversioned"),
            window=int(raw.get("window", 250)),
            purge=int(raw.get("purge", 10)),
            embargo=int(raw.get("embargo", 10)),
            topk=int(raw.get("topk", 2)),
            min_obs=int(raw.get("min_obs", 250)),
            stability_weight=float(raw.get("stability_weight", 1.0)),
            tie_break=str(raw.get("tie_break", "method_id")),
        )
    except (TypeError, ValueError) as exc:
        raise BaselineConfigError(f"method_rank 参数非法: {exc}") from exc
    if config.topk < 1:
        raise BaselineConfigError("topk 必须 ≥1")
    if config.window < config.purge + config.embargo:
        raise BaselineConfigError("window 必须 ≥ purge + embargo")
    if config.tie_break != "method_id":
        raise BaselineConfigError("tie_break 当前只支持 method_id（确定性要求）")
    return config


def assert_disjoint(ranked_ids: Sequence[str], baseline_ids: Sequence[str]) -> None:
    """LT-G11：排名结果不得侵占基座槽位。"""
    overlap = sorted(set(ranked_ids) & set(baseline_ids))
    if overlap:
        raise BaselineConfigError(f"排名结果与基座相交: {overlap}")


def _canonical(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _hash(payload: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def rank(
    reliability: Mapping[str, float],
    *,
    as_of: str,
    sample_n: Optional[Mapping[str, int]] = None,
    stability: Optional[Mapping[str, float]] = None,
    config: Optional[RankConfig] = None,
    baseline: Optional[BaselineConfig] = None,
    specs: Optional[Sequence[MethodSpec]] = None,
) -> Dict[str, Any]:
    """非基座方法的动态排名（确定性，可回放）。

    - 可算性：`implemented` 且（给了 `sample_n` 时）`sample_n ≥ spec.min_n`；
    - 打分：`score = |reliability| × stability`（stability 缺省 1.0）；
    - 排序：`(-score, method_id)`，取 `topk`；
    - 基座方法恒被排除，即使其 reliability 最高。
    """
    cfg = config or load_rank_config()
    base = baseline or load_baseline()
    pool = list(specs) if specs is not None else all_specs()

    ranked: List[Dict[str, Any]] = []
    excluded_baseline: List[str] = []
    excluded_unimplemented: List[str] = []
    excluded_insufficient: List[str] = []
    excluded_no_signal: List[str] = []

    for spec in pool:
        method_id = spec.method_id
        if method_id in base.method_ids:
            excluded_baseline.append(method_id)
            continue
        if not spec.implemented:
            excluded_unimplemented.append(method_id)
            continue
        if sample_n is not None and int(sample_n.get(method_id, 0)) < int(spec.min_n):
            excluded_insufficient.append(method_id)
            continue
        try:
            value = abs(float(reliability.get(method_id, 0.0)))
        except (TypeError, ValueError):
            value = 0.0
        if value <= 0.0:
            excluded_no_signal.append(method_id)
            continue
        stab = 1.0
        if stability is not None:
            try:
                stab = float(stability.get(method_id, 1.0))
            except (TypeError, ValueError):
                stab = 1.0
            if stab < 0.0:
                stab = 0.0
        ranked.append(
            {
                "method_id": method_id,
                "score": round(value * stab * cfg.stability_weight, 10),
            }
        )

    ranked.sort(key=lambda item: (-item["score"], item["method_id"]))
    top = ranked[: cfg.topk]
    assert_disjoint([item["method_id"] for item in top], base.method_ids)

    payload = {
        "as_of": as_of,
        "baseline_version": base.version,
        "rank_version": cfg.version,
        "topk": cfg.topk,
        "entries": [[item["method_id"], item["score"]] for item in top],
    }
    return {
        "as_of": as_of,
        "baseline_version": base.version,
        "rank_version": cfg.version,
        "topk": cfg.topk,
        "ranked": top,
        "candidates": ranked,
        "excluded_baseline": sorted(excluded_baseline),
        "excluded_unimplemented": sorted(excluded_unimplemented),
        "excluded_insufficient": sorted(excluded_insufficient),
        "excluded_no_signal": sorted(excluded_no_signal),
        "method_rank_hash": _hash(payload),
    }


def blend_axis(
    baseline_values: Sequence[float],
    ranked_values: Sequence[float],
    *,
    max_rel: float = DEFAULT_MAX_REL,
    eps: float = 1e-12,
) -> Dict[str, Any]:
    """LT-G12 增量保护：排名方法只能修饰基座轴值。

    规则（逐轴）：
      - 长度不一致 → 报错；
      - 基座值为 0 → 保持 0（排名方法不得"新增轴"）；
      - 符号相反 → 回退基座值；
      - 相对偏差 > `max_rel` → 回退基座值；
      - 其余取排名值。
    """
    if len(baseline_values) != len(ranked_values):
        raise BaselineConfigError(
            f"轴数不一致: baseline={len(baseline_values)} ranked={len(ranked_values)}"
        )
    values: List[float] = []
    clipped: List[int] = []
    for index, (base_raw, rank_raw) in enumerate(zip(baseline_values, ranked_values, strict=False)):
        base = float(base_raw)
        try:
            rank_value = float(rank_raw)
        except (TypeError, ValueError):
            values.append(round(base, 10))
            clipped.append(index)
            continue
        if base == 0.0:
            values.append(round(base, 10))
            clipped.append(index)
            continue
        if (base > 0) != (rank_value > 0):
            values.append(round(base, 10))
            clipped.append(index)
            continue
        if abs(rank_value - base) / max(abs(base), eps) > max_rel:
            values.append(round(base, 10))
            clipped.append(index)
            continue
        values.append(round(rank_value, 10))
    return {"values": values, "clipped": clipped, "clipped_any": bool(clipped)}
