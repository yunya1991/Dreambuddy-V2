#!/usr/bin/env python3
"""
Screen 1 注释文件新鲜度门禁 v1.0
==================================
检查五维 SKILL 注释文件是否存在且在有效期内。

代码级门禁职责:
  1. 检测每个维度 annotation 的 "updated" 字段
  2. 判断 FRESH / STALE / MISSING 状态
  3. 提取 clock_stage / skill_regime 供代码直接消费
  4. 检查 E(宏观)→F(跨市场) 依赖关系是否满足
  5. 输出 gate_level: FULL / PARTIAL / BASELINE
  6. 生成 TeamA 需要运行的 SKILL 建议列表

gate_level 含义:
  FULL     — 所有核心维度新鲜，A系列输出最高置信度
  PARTIAL  — 部分维度新鲜（≥3/5），A系列输出降级置信度
  BASELINE — 大多数维度缺失，退回代码基线（tech + code_regime）

独立运行: python annotation_freshness_gate.py
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple


# ── 配置 ────────────────────────────────────────────────────────────────────

def _default_base() -> str:
    """注释文件目录（相对于本文件所在目录）."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "Dreambuddy-V2", "6-TRADING")


# 维度元数据: key → (显示名, 文件名, 最大有效天数, SKILL触发词, BTC-only)
DIMENSION_META: Dict[str, Dict] = {
    "cycle":        {
        "name":      "减半/库存周期 (B)",
        "file":      "screen1_cycle_annotation.json",
        "max_days":  14,    # 确定性阶段变化慢，有效期更长
        "skill":     "/screen1-halving-cycle",
        "btc_only":  True,
    },
    "miner":        {
        "name":      "矿工经济 (C)",
        "file":      "screen1_miner_annotation.json",
        "max_days":  7,
        "skill":     "/screen1-miner-economics",
        "btc_only":  True,
    },
    "onchain":      {
        "name":      "链上估值 (D)",
        "file":      "screen1_onchain_annotation.json",
        "max_days":  7,
        "skill":     "/screen1-onchain-valuation",
        "btc_only":  True,
    },
    "macro":        {
        "name":      "宏观金融 (E)",
        "file":      "screen1_macro_annotation.json",
        "max_days":  7,
        "skill":     "/screen1-macro-finance",
        "btc_only":  False,  # ETH/SOL 也可读取宏观
    },
    "cross_market": {
        "name":      "跨市场周期 (F)",
        "file":      "screen1_cross_market_annotation.json",
        "max_days":  7,
        "skill":     "/screen1-cross-market",
        "btc_only":  True,
    },
    "cross_asset":  {
        "name":      "A系列跨资产配置",
        "file":      "screen1_cross_asset_annotation.json",
        "max_days":  7,
        "skill":     "/screen1-cross-asset",
        "btc_only":  True,
    },
}

# F 依赖 E（cross_market 依赖 macro）
DEPENDENCY_CHAIN: Dict[str, List[str]] = {
    "cross_market": ["macro"],
}

# 核心维度（用于 gate_level 判断，不含 cross_asset 这个最终输出）
CORE_DIMS = ["cycle", "miner", "onchain", "macro", "cross_market"]

STATUS_FRESH   = "FRESH"
STATUS_STALE   = "STALE"
STATUS_MISSING = "MISSING"

VALID_REGIMES = frozenset(
    ["STRONG_BULL", "WEAK_BULL", "CONSOLIDATION", "WEAK_BEAR", "STRONG_BEAR"]
)


# ── 内部工具 ─────────────────────────────────────────────────────────────────

def _annotation_path(dim_key: str, base: str) -> str:
    return os.path.join(base, DIMENSION_META[dim_key]["file"])


def _read_annotation(dim_key: str, base: str) -> Optional[Dict]:
    path = _annotation_path(dim_key, base)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        return None


def _calc_age(updated_str: str, today: datetime) -> Optional[int]:
    """返回距今天数，解析失败返回 None."""
    if not updated_str:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return (today - datetime.strptime(updated_str, fmt)).days
        except ValueError:
            continue
    return None


def _dim_status(dim_key: str, base: str, today: datetime) -> Dict:
    """检查单个维度注释状态."""
    data = _read_annotation(dim_key, base)
    if data is None:
        return {"status": STATUS_MISSING, "age_days": None, "updated": None, "data": None}

    updated_str = data.get("updated", "")
    age = _calc_age(updated_str, today)
    max_days = DIMENSION_META[dim_key]["max_days"]

    if age is None:
        status = STATUS_STALE
    elif age <= max_days:
        status = STATUS_FRESH
    else:
        status = STATUS_STALE

    return {"status": status, "age_days": age, "updated": updated_str, "data": data}


# ── 主函数 ────────────────────────────────────────────────────────────────────

def check_annotation_freshness(
    base: Optional[str] = None,
    today: Optional[datetime] = None,
    is_btc: bool = True,
) -> Dict:
    """
    检查所有维度注释文件的新鲜度。

    参数:
      base   — 注释文件目录（默认自动推断）
      today  — 基准日期（默认今天，便于测试传入模拟日期）
      is_btc — 是否为 BTC 标的（False 时跳过 BTC-only 维度）

    返回:
    {
        "gate_pass":             bool,    # True = 所有核心维度 FRESH
        "gate_level":            str,     # FULL / PARTIAL / BASELINE
        "gate_checked_at":       str,
        "dimensions":            dict,    # 每维度状态详情
        "stale_dims":            list,
        "missing_dims":          list,
        "dependency_violations": list,    # E→F 违规说明
        "clock_stage":           str|None,# 来自 F annotation
        "skill_regime":          str|None,# 来自 cross_asset annotation
        "n_fresh":               int,
        "n_total":               int,
        "gate_confidence_mult":  float,  # 置信度系数 (1.0 / 0.8 / 0.5)
        "recommendations":       list,   # TeamA 需运行的 SKILL 列表
    }
    """
    if base is None:
        base = _default_base()
    if today is None:
        today = datetime.now()

    results: Dict[str, Dict] = {}
    stale: List[str]   = []
    missing: List[str] = []
    dep_violations: List[str] = []

    # 决定要检查的维度
    dims = list(DIMENSION_META.keys())

    for dim in dims:
        meta = DIMENSION_META[dim]
        if meta["btc_only"] and not is_btc:
            results[dim] = {
                "status": "SKIPPED", "age_days": None,
                "updated": None, "data": None,
            }
            continue
        info = _dim_status(dim, base, today)
        results[dim] = info
        if info["status"] == STATUS_STALE:
            if dim in CORE_DIMS:
                stale.append(dim)
        elif info["status"] == STATUS_MISSING:
            if dim in CORE_DIMS:
                missing.append(dim)

    # ── 依赖关系检查: F 依赖 E ──────────────────────────────────────────────
    for dim, deps in DEPENDENCY_CHAIN.items():
        dim_info = results.get(dim, {})
        if dim_info.get("status") not in (STATUS_FRESH,):
            continue  # F 自己不新鲜，无需检查依赖
        for dep in deps:
            dep_info = results.get(dep, {})
            dep_status = dep_info.get("status", STATUS_MISSING)
            if dep_status in (STATUS_STALE, STATUS_MISSING):
                dep_name  = DIMENSION_META.get(dep,  {}).get("name", dep)
                dim_name  = DIMENSION_META.get(dim,  {}).get("name", dim)
                dep_age   = dep_info.get("age_days")
                dim_age   = dim_info.get("age_days", 0)
                word      = "缺失" if dep_status == STATUS_MISSING else f"过期({dep_age}天)"
                dep_violations.append(
                    f"{dim_name} annotation 存在(更新{dim_age}天前), "
                    f"但依赖的 {dep_name} {word} — "
                    f"F 中的 M2/DXY 字段可能基于过时数据"
                )

    # ── 提取关键下游字段 ────────────────────────────────────────────────────
    clock_stage  = None
    skill_regime = None

    cm_info = results.get("cross_market", {})
    if cm_info.get("status") == STATUS_FRESH and cm_info.get("data"):
        clock_stage = cm_info["data"].get("clock_stage")

    ca_info = results.get("cross_asset", {})
    if ca_info.get("status") == STATUS_FRESH and ca_info.get("data"):
        raw = ca_info["data"].get("skill_regime", "")
        if raw in VALID_REGIMES:
            skill_regime = raw

    # ── gate_level 判断 ─────────────────────────────────────────────────────
    # 只统计核心维度（非 cross_asset）
    active_core = [d for d in CORE_DIMS
                   if results.get(d, {}).get("status") != "SKIPPED"]
    n_total = len(active_core)
    n_fresh = sum(1 for d in active_core
                  if results.get(d, {}).get("status") == STATUS_FRESH)

    if n_fresh == n_total and not dep_violations:
        gate_level = "FULL"
        gate_confidence_mult = 1.0
    elif n_fresh >= 3:
        gate_level = "PARTIAL"
        gate_confidence_mult = 0.8
    else:
        gate_level = "BASELINE"
        gate_confidence_mult = 0.5

    gate_pass = (gate_level == "FULL")

    # ── 生成 TeamA 建议 ──────────────────────────────────────────────────────
    # 按依赖顺序排序（E 排在 F 前）
    ordered_to_run: List[str] = []
    for dim in ["cycle", "miner", "onchain", "macro", "cross_market"]:
        if dim in missing or dim in stale:
            ordered_to_run.append(dim)

    recommendations: List[str] = []
    for dim in ordered_to_run:
        meta  = DIMENSION_META[dim]
        label = "缺失" if dim in missing else "过期"
        recommendations.append(
            f"运行 {meta['skill']:35s}  [{meta['name']}  {label}]"
        )

    if dep_violations:
        recommendations.append(
            "⚡ 注意: 请先运行 /screen1-macro-finance 再运行 /screen1-cross-market"
        )

    # ── 调度计划（可选，Hermes 消费）────────────────────────────────────────
    dispatch_plan: List[Dict] = []
    try:
        from model_dispatcher import dispatch as _dispatch, get_task_info as _get_task_info

        # 仅为需要运行的维度 + 完整合成链生成调度项
        _dim_to_task = {
            "cycle":        "dim_annotation_cycle",
            "miner":        "dim_annotation_miner",
            "onchain":      "dim_annotation_onchain",
            "macro":        "dim_annotation_macro",
            "cross_market": "dim_annotation_cross_market",
        }
        _step = 1
        for dim in ordered_to_run:
            tt    = _dim_to_task[dim]
            model = _dispatch(tt)
            info  = _get_task_info(tt)
            dispatch_plan.append({
                "step":        _step,
                "task_type":   tt,
                "model":       model,
                "skill":       info["skill"],
                "depends_on":  info["depends_on"],
                "dim":         dim,
                "reason":      "缺失" if dim in missing else "过期",
            })
            _step += 1

        # 如果有维度需要更新，补充合成链
        if ordered_to_run:
            for tt in ["synthesis_a1", "synthesis_a2", "synthesis_a3", "synthesis_cross_asset"]:
                model = _dispatch(tt)
                info  = _get_task_info(tt)
                dispatch_plan.append({
                    "step":       _step,
                    "task_type":  tt,
                    "model":      model,
                    "skill":      info["skill"],
                    "depends_on": info["depends_on"],
                    "dim":        None,
                    "reason":     "合成链重跑",
                })
                _step += 1
    except ImportError:
        pass  # model_dispatcher 不存在时优雅降级

    return {
        "gate_pass":             gate_pass,
        "gate_level":            gate_level,
        "gate_checked_at":       today.strftime("%Y-%m-%d %H:%M"),
        "dimensions":            results,
        "stale_dims":            stale,
        "missing_dims":          missing,
        "dependency_violations": dep_violations,
        "clock_stage":           clock_stage,
        "skill_regime":          skill_regime,
        "n_fresh":               n_fresh,
        "n_total":               n_total,
        "gate_confidence_mult":  gate_confidence_mult,
        "recommendations":       recommendations,
        "dispatch_plan":         dispatch_plan,
    }


def get_annotation_field(
    dim_key: str,
    field: str,
    default=None,
    base: Optional[str] = None,
) -> object:
    """从指定维度注释中安全读取单个字段（无论新鲜度）."""
    if base is None:
        base = _default_base()
    data = _read_annotation(dim_key, base)
    if data is None:
        return default
    return data.get(field, default)


# ── 格式化报告 ────────────────────────────────────────────────────────────────

def format_gate_report(g: Dict) -> str:
    """生成人类可读的门禁检查报告."""
    icons = {STATUS_FRESH: "✅", STATUS_STALE: "⚠️",
             STATUS_MISSING: "❌", "SKIPPED": "—"}
    level_icon = {"FULL": "✅ FULL", "PARTIAL": "⚠️ PARTIAL",
                  "BASELINE": "❌ BASELINE"}

    lines = [
        "=" * 64,
        f"  Screen 1 注释门禁检查  [{g['gate_checked_at']}]",
        f"  门禁级别: {level_icon.get(g['gate_level'], g['gate_level'])}"
        f"  ({g['n_fresh']}/{g['n_total']} 核心维度新鲜)"
        f"  置信系数: ×{g['gate_confidence_mult']:.1f}",
        "─" * 64,
    ]

    for dim, info in g["dimensions"].items():
        if dim not in DIMENSION_META:
            continue
        meta   = DIMENSION_META[dim]
        st     = info.get("status", "UNKNOWN")
        icon   = icons.get(st, "?")
        age    = f"{info['age_days']}天前" if info.get("age_days") is not None else "—"
        upd    = info.get("updated") or "—"
        lines.append(
            f"  {icon} {meta['name']:22s}  {st:8s}"
            f"  更新: {upd:12s}  ({age})"
        )

    if g["dependency_violations"]:
        lines.append("─" * 64)
        lines.append("  依赖关系警告:")
        for v in g["dependency_violations"]:
            lines.append(f"  ⚡ {v}")

    lines.append("─" * 64)
    if g.get("clock_stage"):
        lines.append(f"  象限定位 (F维度):    {g['clock_stage']}")
    else:
        lines.append("  象限定位 (F维度):    — (F annotation 不可用，使用代码默认)")
    if g.get("skill_regime"):
        lines.append(f"  SKILL研判 (A3):      {g['skill_regime']}")
    else:
        lines.append("  SKILL研判 (A3):      — (cross_asset annotation 不可用，使用 code_regime)")

    if g["recommendations"]:
        lines.append("─" * 64)
        lines.append("  TeamA 待运行 SKILL:")
        for r in g["recommendations"]:
            lines.append(f"    → {r}")

    lines.append("=" * 64)
    return "\n".join(lines)


# ── 独立运行 ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys, io
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    print()
    result = check_annotation_freshness()
    print(format_gate_report(result))

    # 简单 smoke test
    assert result["gate_level"] in ("FULL", "PARTIAL", "BASELINE"), \
        f"gate_level 非法: {result['gate_level']}"
    assert 0.0 <= result["gate_confidence_mult"] <= 1.0, \
        "gate_confidence_mult 超出范围"
    assert result["n_fresh"] <= result["n_total"], \
        "n_fresh > n_total 不合理"
    print("\n[SMOKE TEST] annotation_freshness_gate: OK")
