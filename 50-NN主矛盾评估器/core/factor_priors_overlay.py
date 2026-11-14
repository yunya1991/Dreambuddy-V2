# factor_priors_overlay.py — 50 侧 40 因子方向先验 overlay（G4 升级：审计挂载 → 参与决策计算）。
#
# 定位（SPEC 待评审）：把 40 域 factor_contradiction_priors.json 的因子方向先验，
# 在 synthesize_paths 之后、w4.adjudicate 之前，按"因子前缀→dimension"映射调制 path.confidence。
# w4.force_score 消费 weight×confidence，故调制 confidence 会真实影响 direction 与 total。
#
# 纪律：
#   - 纯函数：不读文件、不写状态（文件加载由调用方负责）。
#   - 方向归一：先验 bullish/bearish → path long/short；neutral path 不参与（无方向可对齐）。
#   - 系数预注册截断：coef ∈ [0, MAX_COEF]，禁止运行时自适应调权（防漂移/过拟合）。
#   - confidence 截断到 [0,1]；空先验 / coef=0 原样返回（等价基线）。
from __future__ import annotations

from dataclasses import replace
from typing import Any, Iterable

from core.path_synthesis import Path

# 系数预注册上限（confidence 最多 ±MAX_COEF 调制）；扫描区间由 harness 实测支撑 SPEC 定档。
MAX_COEF = 0.5

# 先验样本量下限（SPEC-M4 v0.2 Q4 裁决）：n_samples 低于此值时由调用方 no-op。
MIN_N_SAMPLES = 200

# 因子方向归一：先验 bullish/bearish → path long/short。
_DIRECTION_NORM = {
    "bullish": "long",
    "bearish": "short",
    "long": "long",
    "short": "short",
}

# 因子前缀 → 50 dimension 预注册映射（SPEC-M4 v0.2 裁决）。
#   macro.*    → D1        宏观力量（40-cycle/43-strategic/40-divergence/40-resonance）
#   technical.*→ D3        技术/战术（11-bcrm/11-washout/11-bcrm-tactical）
#   flow.*     → D3        资金流（Q1 裁决：暂并战术维，不新开 D2）
#   event.*    → C7        事件（Q2 裁决：首轮仅 C7，NEWS 单独评估）
#   sentiment.*→ NEWS      情绪/叙事（新闻语义维）
FACTOR_PREFIX_DIM_MAP: dict[str, frozenset[str]] = {
    "macro": frozenset({"D1"}),
    "technical": frozenset({"D3"}),
    "flow": frozenset({"D3"}),
    "event": frozenset({"C7"}),
    "sentiment": frozenset({"NEWS"}),
}


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def _factor_prefix(name: object) -> str:
    return str(name or "").split(".", 1)[0].strip().lower()


def _bucket_factors_by_dimension(
    factors: dict[str, Any],
) -> dict[str, list[tuple[str, float]]]:
    """把完整因子表按 dimension 分桶为 [(direction_norm, weight)]，供 path 命中查询。"""
    buckets: dict[str, list[tuple[str, float]]] = {}
    for name, cfg in (factors or {}).items():
        if not isinstance(cfg, dict):
            continue
        prefix = _factor_prefix(name)
        dims = FACTOR_PREFIX_DIM_MAP.get(prefix)
        if not dims:
            continue
        direction = _DIRECTION_NORM.get(str(cfg.get("dominant_direction") or "").strip().lower())
        if direction not in ("long", "short"):
            continue
        try:
            weight = float(cfg.get("total_weight") or 0.0)
        except (TypeError, ValueError):
            continue
        if weight <= 0:
            continue
        for dim in dims:
            buckets.setdefault(dim, []).append((direction, weight))
    return buckets


def dimension_net_strength(
    dimension: str,
    path_direction: str,
    buckets: dict[str, list[tuple[str, float]]],
) -> float:
    """该 dimension 先验对 path_direction 的净方向强度 ∈ [-1,1]。

    支持方向与 path 一致的因子权重为正、相反为负，除以总权重归一。
    无命中因子返回 0.0（等价无调制）。
    """
    matched = buckets.get(dimension)
    if not matched:
        return 0.0
    total = sum(w for _, w in matched)
    if total <= 0:
        return 0.0
    support = sum(w if d == path_direction else -w for d, w in matched)
    return support / total


def apply_factor_priors_overlay(
    paths: Iterable[Path],
    factors: dict[str, Any] | None,
    coef: float,
) -> list[Path]:
    """对 paths 应用 40 因子方向先验 overlay，返回调整后的新列表（不改原对象）。

    coef 截断到 [0, MAX_COEF]；空先验 / coef=0 / 无命中 / neutral path 原样返回。
    """
    items = [p for p in paths if isinstance(p, Path)]
    try:
        c = float(coef)
    except (TypeError, ValueError):
        c = 0.0
    c = max(0.0, min(MAX_COEF, c))
    if c == 0.0 or not factors:
        return list(items)

    buckets = _bucket_factors_by_dimension(factors)
    if not buckets:
        return list(items)

    adjusted: list[Path] = []
    for p in items:
        # neutral path 无方向可对齐，不参与方向性先验调制。
        if p.direction not in ("long", "short"):
            adjusted.append(p)
            continue
        strength = dimension_net_strength(p.dimension, p.direction, buckets)
        if strength == 0.0:
            adjusted.append(p)
            continue
        factor = 1.0 + c * strength
        adjusted.append(replace(p, confidence=round(_clamp01(p.confidence * factor), 8)))
    return adjusted
