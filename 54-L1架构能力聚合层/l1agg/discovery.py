# -*- coding: utf-8 -*-
"""Discovery 搜索空间加载与校验（SPEC-54 §15.2 / B3 预注册）。

单一事实源：`config/discovery_space.yaml`。本模块只做「读 + 校验 + 预算估算」，
不取数、不算统计量、不写报告、不产出 findings——发现流水线另立项。

校验只拦「违反预注册冻结项」的改动（seed / 变换集 / 方法库登记 / 序列可解析 /
预算上限 / FDR 强制 / 70-30 分段 / 去重阈值），不评价搜索质量。
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, Iterable, List, Optional

import yaml

from . import asset_pool
from .methods import REGISTRY

SPACE_FILE = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "discovery_space.yaml")
)

# ---------------- 预注册冻结项（§15.2 / §15.5） ----------------
FIXED_TRANSFORMS = ("raw", "diff", "pct", "zscore60", "ts_rank60", "quintile5")
FIXED_METHODS = (
    "M01",
    "M02",
    "M11",
    "M12",
    "B01",
    "B02",
    "B03",
    "B04",
    "B05",
    "B11",
    "B12",
    "B13",
    "B14",
    "B15",
    "R01",
    "R02",
    "R03",
    "R04",
    "SC52",
    "SC62",
)
FIXED_HORIZONS = (1, 5, 20)
SEED = 42
MAX_SERIES = 40
MAX_PAIRS = 300
MAX_UNITS = 5000
MAX_MINUTES = 10
MAX_FINDINGS = 50
FDR_ALPHA = 0.05
DEDUPE_CORR = 0.95
SCREEN_RATIO = 0.7
MIN_HOLDOUT_AGREEMENT = 0.6


class DiscoverySpaceError(ValueError):
    """搜索空间结构非法或违反预注册冻结项。"""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DiscoverySpaceError(message)


def _unique(values: Iterable[Any], label: str) -> List[Any]:
    out = list(values)
    _require(len(set(out)) == len(out), f"{label} 存在重复项")
    return out


def _asset_storage_keys() -> set:
    """资产池 anchors[].storage.sub_category（核心 + 扩展）。"""
    pool = asset_pool.load()
    return {anchor.storage_key[0] for anchor in pool.all_anchors()}


def pair_count(n_series: int) -> int:
    return n_series * (n_series - 1) // 2


def estimate_units(space: Dict[str, Any]) -> Dict[str, int]:
    """单元估算：单序列单元 + 双序列单元（每对按两个方向各算一次）。"""
    n_series = len(space["series"])
    grid = len(space["transforms"]) * len(space["methods"]) * len(space["horizons"])
    single = n_series * grid if space["single"] else 0
    pairs = pair_count(n_series)
    pair_units = pairs * 2 * grid if space["pair"] else 0
    return {
        "series": n_series,
        "pairs": pairs,
        "single_units": single,
        "pair_units": pair_units,
        "total_units": single + pair_units,
    }


def validate_space(space: Dict[str, Any]) -> None:
    """校验预注册冻结项；任一不满足即抛 DiscoverySpaceError。"""
    _require(int(space["version"]) >= 1, "version 必须是 >=1 的整数")
    _require(space["seed"] == SEED, f"seed 冻结为 {SEED}，禁止改动")

    transforms = _unique(space["transforms"], "transforms")
    _require(
        set(transforms) == set(FIXED_TRANSFORMS),
        f"transforms 必须恰好是 {list(FIXED_TRANSFORMS)}",
    )

    methods = _unique(space["methods"], "methods")
    _require(bool(methods), "methods 不能为空")
    unknown = [m for m in methods if m not in REGISTRY]
    _require(not unknown, f"methods 未在方法库登记：{unknown}")
    outside = [m for m in methods if m not in FIXED_METHODS]
    _require(not outside, f"methods 超出预注册子集：{outside}")

    _require(tuple(space["horizons"]) == FIXED_HORIZONS, f"horizons 冻结为 {list(FIXED_HORIZONS)}")

    series = _unique(space["series"], "series")
    _require(bool(series), "series 不能为空")
    _require(len(series) <= MAX_SERIES, f"序列池上限 {MAX_SERIES} 条，当前 {len(series)}")

    known = _asset_storage_keys()
    unresolved = [s for s in space["assets"] if s not in known]
    _require(not unresolved, f"资产池序列无法解析到 anchors.storage.sub_category：{unresolved}")

    pairs = pair_count(len(series))
    _require(not space["pair"] or pairs <= MAX_PAIRS, f"双序列上限 {MAX_PAIRS} 对，当前 {pairs}")
    _require(space["single"] or space["pair"], "single/pair 至少启用一种（三序列及以上禁）")

    budget = space["budget"]
    _require(int(budget["max_units"]) <= MAX_UNITS, f"单元预算上限 {MAX_UNITS}")
    _require(int(budget["max_minutes"]) <= MAX_MINUTES, f"单次运行上限 {MAX_MINUTES} 分钟")
    _require(int(budget["max_findings"]) <= MAX_FINDINGS, f"发现数量上限 {MAX_FINDINGS}")

    fdr = space["fdr"]
    _require(bool(fdr["enabled"]) is True, "BH-FDR 强制开启，禁止关闭")
    _require(float(fdr["alpha"]) == FDR_ALPHA, f"FDR alpha 冻结为 {FDR_ALPHA}")

    _require(
        float(space["dedupe"]["corr_threshold"]) == DEDUPE_CORR, f"去重阈值冻结为 {DEDUPE_CORR}"
    )

    split = space["split"]
    _require(float(split["screen_ratio"]) == SCREEN_RATIO, f"筛选段固定为 {SCREEN_RATIO}")
    _require(
        float(split["holdout_ratio"]) == round(1.0 - SCREEN_RATIO, 6),
        "holdout 段固定为 30%",
    )
    _require(
        float(split["min_holdout_agreement"]) >= MIN_HOLDOUT_AGREEMENT,
        f"holdout 符号一致率下限 {MIN_HOLDOUT_AGREEMENT}",
    )


def load_space(path: Optional[str] = None) -> Dict[str, Any]:
    """读取 + 规范化 + 校验搜索空间，并给出可复现的 `space_hash`。"""
    with open(path or SPACE_FILE, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    assets = [str(v) for v in ((raw.get("series") or {}).get("assets") or [])]
    macro = [str(v) for v in ((raw.get("series") or {}).get("macro") or [])]
    combos = raw.get("combos") or {}
    budget = raw.get("budget") or {}
    fdr = raw.get("fdr") or {}
    dedupe = raw.get("dedupe") or {}
    split = raw.get("split") or {}
    targets = raw.get("targets") or {}

    space: Dict[str, Any] = {
        "version": int(raw["version"]),
        "updated": str(raw.get("updated") or ""),
        "seed": int(raw["seed"]),
        "assets": assets,
        "macro": macro,
        "series": assets + macro,
        "single": bool(combos.get("single", True)),
        "pair": bool(combos.get("pair", True)),
        "transforms": [str(v) for v in raw["transforms"]],
        "methods": [str(v) for v in raw["methods"]],
        "horizons": [int(v) for v in targets["horizons"]],
        "budget": {
            "max_units": int(budget["max_units"]),
            "max_minutes": int(budget["max_minutes"]),
            "max_findings": int(budget["max_findings"]),
        },
        "fdr": {"enabled": bool(fdr["enabled"]), "alpha": float(fdr["alpha"])},
        "dedupe": {"corr_threshold": float(dedupe["corr_threshold"])},
        "split": {
            "screen_ratio": float(split["screen_ratio"]),
            "holdout_ratio": float(split["holdout_ratio"]),
            "min_holdout_agreement": float(split["min_holdout_agreement"]),
        },
    }
    validate_space(space)

    estimates = estimate_units(space)
    estimates["within_budget"] = estimates["total_units"] <= space["budget"]["max_units"]
    space["estimates"] = estimates
    space["space_hash"] = hashlib.sha256(_canonical(space).encode("utf-8")).hexdigest()
    return space
