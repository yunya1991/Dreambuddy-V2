"""variant_generator.py — E2 做梦器升级：策略结构变体生成器（SPEC v0.5 §4 E2）。

与既有做梦器的关系（只读引用，不改 33/4-MEMORY 代码）：
  - 33-REA `core/reflection/dreaming.py`：V(π,T) 寻优，但只在**人工写的编排空间**内
    做序列重排/预算/并行度变换（参数级微调）
  - 4-MEMORY `dreaming_engine.py`：记忆卫生（去重合并），与本判据无关
本模块补的是二者都缺的**策略结构变体**：开关位掩码 / 阈值分箱 / 标的集的结构化扰动，
经 schema 校验 + 新颖度判读 + 正负反馈配平后产出批次。

「人未写过」口径（§1 E2）：结构向量不在 human_config_hashes.json 且
与最近人工配置编辑距离 >= k(=2)，复用 48/registry/struct_vector.py 的向量与距离定义。

正负反馈配平（§4 E2 硬约束）：变异（正反馈）必须与记忆衰减/置信降级（负反馈）显式配平
——keep_ratio<1 时按新颖度确定性丢弃，双向计数落批次。

FAIL-OPEN：IO/解析异常降级为空结果，不抛错。
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_REGISTRY = str(_REPO_ROOT / "48-涌现架构" / "registry")
if _REGISTRY not in sys.path:
    sys.path.insert(0, _REGISTRY)

import struct_vector as sv  # noqa: E402

TRANSFORMS = (
    "switch_flip",
    "bdsm_flip",
    "env_flip",
    "phase_flip",
    "threshold_shift",
    "coin_change",
)

_BITMASKS = {
    "switch_flip": ("switches_bitmask", len(sv.SWITCH_ORDER)),
    "bdsm_flip": ("bdsm_flags", len(sv.BDSM_ORDER)),
    "env_flip": ("env_flags", len(sv.ENV_ORDER)),
    "phase_flip": ("phase_flags", len(sv.PHASE_ORDER)),
}

# schema 校验护栏（本地最小实现：仓内无 STRATEGY_CONFIG_SCHEMA 代码实现，
# 这里只校验结构性不变量，不做优化目标定义）
_THRESHOLD_BOUNDS = [
    (1, 19),  # confidence 按 0.05 分箱，0.05..0.95
    (1, 10),  # max_positions
    (5, 50),  # position_pct × 100
    (1, 60),  # interval 秒 / 60
]
_MIN_COINS = 3
_MAX_COINS = 30


def coins_hash(coins: List[str]) -> str:
    return hashlib.sha256(",".join(sorted(coins)).encode()).hexdigest()[:16]


def vector_hash(v: Dict[str, Any]) -> str:
    return sv.vector_hash(v)


def edit_distance(a: Dict[str, Any], b: Dict[str, Any]) -> int:
    return sv.edit_distance(a, b)


def validate_variant(v: Dict[str, Any]) -> List[str]:
    """结构性 schema 校验，返回错误列表（空=通过）。"""
    errors: List[str] = []
    for field, nbits in _BITMASKS.values():
        bits = v.get(field)
        if not isinstance(bits, str) or len(bits) != nbits or set(bits) - {"0", "1"}:
            errors.append(f"{field} 非法位串: {bits!r}（期望 {nbits} 位 0/1）")
    bins = v.get("threshold_bins")
    if not isinstance(bins, list) or len(bins) != len(_THRESHOLD_BOUNDS):
        errors.append(f"threshold_bins 长度非法: {bins!r}")
    else:
        for i, (lo, hi) in enumerate(_THRESHOLD_BOUNDS):
            try:
                val = int(bins[i])
            except (TypeError, ValueError):
                errors.append(f"threshold_bins[{i}] 非整数: {bins[i]!r}")
                continue
            if not lo <= val <= hi:
                errors.append(f"threshold_bins[{i}]={val} 越界 [{lo},{hi}]")
    coins = v.get("coins")
    if not isinstance(coins, list) or not (_MIN_COINS <= len(coins) <= _MAX_COINS):
        errors.append(f"coins 数量非法: {len(coins) if isinstance(coins, list) else coins!r}")
    elif v.get("coins_hash") != coins_hash([str(c) for c in coins]):
        errors.append("coins_hash 与 coins 不一致")
    return errors


def assess_novelty(
    v: Dict[str, Any],
    registry_path: Optional[Path] = None,
    k: int = sv.K_MIN_DISTANCE,
) -> Dict[str, Any]:
    """「人未写过」判读。registry 缺失 → 判据悬置（is_human_written=None）。"""
    kw = {"k": k}
    if registry_path is not None:
        kw["registry_path"] = Path(registry_path)
    return sv.is_human_written(v, **kw)


def _flip_bits(bits: str, positions: List[int]) -> str:
    chars = list(bits)
    for pos in positions:
        chars[pos] = "0" if chars[pos] == "1" else "1"
    return "".join(chars)


def _mutate(base: Dict[str, Any], transform: str, rng: np.random.Generator) -> Dict[str, Any]:
    """按指定变换类型生成一个候选结构向量（深度拷贝 base 后扰动）。"""
    cand = {
        "switches_bitmask": base["switches_bitmask"],
        "bdsm_flags": base["bdsm_flags"],
        "env_flags": base["env_flags"],
        "phase_flags": base["phase_flags"],
        "threshold_bins": list(base["threshold_bins"]),
        "coins": list(base["coins"]),
        "coins_hash": base["coins_hash"],
    }
    if transform in _BITMASKS:
        field, nbits = _BITMASKS[transform]
        n_flip = int(rng.integers(1, 3))  # 1~2 位
        positions = sorted(rng.choice(nbits, size=min(n_flip, nbits), replace=False).tolist())
        cand[field] = _flip_bits(cand[field], positions)
    elif transform == "threshold_shift":
        idx = int(rng.integers(0, len(_THRESHOLD_BOUNDS)))
        delta = int(rng.choice([-2, -1, 1, 2]))
        lo, hi = _THRESHOLD_BOUNDS[idx]
        cand["threshold_bins"][idx] = max(lo, min(hi, int(cand["threshold_bins"][idx]) + delta))
    elif transform == "coin_change":
        universe = sorted(set(base["coins"]))
        mode = "add" if int(rng.integers(0, 2)) == 0 else "remove"
        if mode == "add":
            pool = [c for c in universe if c not in cand["coins"]]
            if not pool:
                return cand
            cand["coins"].append(pool[int(rng.integers(0, len(pool)))])
        else:
            if len(cand["coins"]) <= _MIN_COINS:
                return cand
            cand["coins"].remove(cand["coins"][int(rng.integers(0, len(cand["coins"])))])
        cand["coins_hash"] = coins_hash(cand["coins"])
    return cand


def generate_variants(
    base: Dict[str, Any],
    n: int = 32,
    seed: int = 42,
    registry_path: Optional[Path] = None,
    min_novelty: int = 1,
    keep_ratio: float = 1.0,
    max_attempts_factor: int = 20,
) -> Dict[str, Any]:
    """生成 n 个结构变体（可含正负反馈配平丢弃）。

    Args:
        base: 人工基线结构向量（含 coins 列表）
        n: 目标生成数
        registry_path: 人工配置基线路径（缺省用 48/registry 内置）
        min_novelty: 相对 base 的最小编辑距离（默认 1，即必须真的改动）
        keep_ratio: 正负反馈配平保留比例（<1 时按新颖度丢弃尾部）

    Returns:
        {"variants": [...], "feedback": {...}, "generated": n_target}
    """
    rng = np.random.default_rng(seed)
    seen = {vector_hash(base)}
    variants: List[Dict[str, Any]] = []
    attempts = 0
    max_attempts = max(1, int(n * max_attempts_factor))
    while len(variants) < n and attempts < max_attempts:
        attempts += 1
        transform = TRANSFORMS[int(rng.integers(0, len(TRANSFORMS)))]
        cand = _mutate(base, transform, rng)
        if validate_variant(cand):
            continue
        dist = edit_distance(cand, base)
        if dist < max(1, int(min_novelty)):
            continue
        vh = vector_hash(cand)
        if vh in seen:
            continue
        seen.add(vh)
        novelty = assess_novelty(cand, registry_path=registry_path)
        variants.append(
            {
                "variant_id": f"V-{vh}",
                "struct_vector": cand,
                "vector_hash": vh,
                "transform": transform,
                "edit_distance_to_base": dist,
                "novelty": novelty,
            }
        )

    # 正负反馈配平：变异（正反馈）与记忆衰减/置信降级（负反馈）显式配平
    dropped: List[Dict[str, Any]] = []
    if keep_ratio < 1.0 and variants:
        keep = max(0, int(round(len(variants) * float(keep_ratio))))
        ranked = sorted(
            variants,
            key=lambda v: (
                -(v["novelty"].get("min_distance") or 0),
                -v["edit_distance_to_base"],
                v["variant_id"],
            ),
        )
        kept_ids = {v["variant_id"] for v in ranked[:keep]}
        dropped = [v for v in variants if v["variant_id"] not in kept_ids]
        variants = [v for v in variants if v["variant_id"] in kept_ids]

    return {
        "variants": variants,
        "generated_target": n,
        "attempts": attempts,
        "feedback": {
            "keep_ratio": float(keep_ratio),
            "n_kept": len(variants),
            "n_dropped": len(dropped),
            "dropped_min_distances": [v["novelty"].get("min_distance") for v in dropped],
        },
    }


def load_base_vector(
    registry_path: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    """取人工基线结构向量（第一条 human_config）。FAIL-OPEN → None。"""
    path = Path(registry_path) if registry_path else sv.REGISTRY_PATH
    try:
        reg = json.loads(path.read_text(encoding="utf-8"))
        cfg = reg["human_configs"][0]
        v = dict(cfg["struct_vector"])
        v["coins"] = list(v.get("coins") or [])
        if "coins_hash" not in v:
            v["coins_hash"] = coins_hash(v["coins"])
        return v
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        logger.warning("加载人工基线失败（降级）: %s", exc)
        return None
