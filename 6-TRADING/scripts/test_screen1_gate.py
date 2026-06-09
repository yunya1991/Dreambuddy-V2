#!/usr/bin/env python3
"""
Screen 1 门禁压力测试 v1.0
===========================
多轮场景模拟，验证 annotation_freshness_gate 在各种注释状态下
能否正确保证工作流正常进行。

场景矩阵:
  S01  所有 annotation 新鲜              → FULL  gate_pass=True
  S02  全部 annotation 缺失              → BASELINE  gate_pass=False
  S03  3/5 新鲜（E/F 缺失）              → PARTIAL  gate_pass=False
  S04  4/5 新鲜（仅 B 过期）             → PARTIAL  gate_pass=False
  S05  4/5 新鲜（仅 F 过期）             → PARTIAL  有依赖警告检查
  S06  E 过期 + F 新鲜                   → FULL-minus 但有依赖警告
  S07  E 缺失 + F 新鲜                   → 依赖违规应被检出
  S08  skill_regime 有效（STRONG_BEAR）  → 门禁读取正确
  S09  skill_regime 非法值               → 应被忽略，退回 code
  S10  B 有效期 14 天（12天内应为 FRESH）→ 确认 B 有效期规则
  S11  F 依赖 E，E=7天前（刚好新鲜）     → 边界检查
  S12  clock_stage 从 F annotation 提取  → 值正确传递
  S13  所有象限 × Phase1 完整覆盖        → calc_cross_asset_allocation 无异常
  S14  非 BTC 标的调用                   → BTC-only 维度全部 SKIPPED

运行: python test_screen1_gate.py
"""

import json
import os
import sys
import io
import tempfile
import traceback
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# ── 导入被测模块 ──────────────────────────────────────────────────────────────
sys.path.insert(0, r"C:\tmp")

from annotation_freshness_gate import (
    check_annotation_freshness,
    format_gate_report,
    VALID_REGIMES,
    CORE_DIMS,
    DIMENSION_META,
    STATUS_FRESH,
    STATUS_STALE,
    STATUS_MISSING,
)
from cross_asset_allocator import calc_cross_asset_allocation, format_screen1_a_summary


# ── 测试基础设施 ──────────────────────────────────────────────────────────────

PASS_COUNT = 0
FAIL_COUNT = 0
ERRORS: List[str] = []


def _ok(name: str):
    global PASS_COUNT
    PASS_COUNT += 1
    print(f"  ✅ {name}")


def _fail(name: str, reason: str):
    global FAIL_COUNT
    FAIL_COUNT += 1
    msg = f"  ❌ {name}: {reason}"
    ERRORS.append(msg)
    print(msg)


def assert_eq(name: str, got, expected):
    if got == expected:
        _ok(name)
    else:
        _fail(name, f"expected={expected!r}  got={got!r}")


def assert_in(name: str, got, collection):
    if got in collection:
        _ok(name)
    else:
        _fail(name, f"{got!r} not in {collection!r}")


def assert_true(name: str, cond: bool, msg: str = ""):
    if cond:
        _ok(name)
    else:
        _fail(name, msg or "condition is False")


def assert_false(name: str, cond: bool, msg: str = ""):
    if not cond:
        _ok(name)
    else:
        _fail(name, msg or "condition is True (expected False)")


# ── 注释文件生成工具 ──────────────────────────────────────────────────────────

def _make_annotation(dim: str, days_ago: int, extra: Optional[Dict] = None) -> Dict:
    """生成指定维度的 mock annotation（days_ago 天前更新）."""
    today = datetime.now()
    updated = (today - timedelta(days=days_ago)).strftime("%Y-%m-%d")

    base: Dict = {"updated": updated, "final_signal": "NEUTRAL", "confidence": 0.70}

    if dim == "cross_market":
        base["clock_stage"]     = "STAGFLATION_LITE"
        base["final_signal"]    = "NEUTRAL"
        base["score"]           = 0
        base["data_completeness"] = "full"
    elif dim == "cycle":
        base["stage"]           = 6
        base["stage_name"]      = "去库存期"
        base["days_since_halving"] = 772
        base["baseline_score"]  = -15
        base["final_signal"]    = "BEAR"
    elif dim == "miner":
        base["current_price"]   = 73500
        base["final_signal"]    = "NEUTRAL"
        base["code_score"]      = -10
    elif dim == "onchain":
        base["mvrv_z"]          = 1.0
        base["nupl"]            = 0.23
        base["rhodl_ratio"]     = 4.5
        base["sth_mvrv"]        = 0.76
        base["final_signal"]    = "BULL"
    elif dim == "macro":
        base["m2_yoy_pct"]      = 12.0
        base["dxy_trend"]       = "FALLING"
        base["yield_10y_pct"]   = 4.3
        base["final_signal"]    = "NEUTRAL"
    elif dim == "cross_asset":
        base["clock_stage"]     = "STAGFLATION_LITE"
        base["btc_role"]        = "high_beta_short"
        base["skill_regime"]    = "STRONG_BEAR"

    if extra:
        base.update(extra)
    return base


def _write_annotations(tmpdir: str, specs: Dict[str, Optional[int]],
                        extras: Optional[Dict[str, Dict]] = None) -> None:
    """
    往 tmpdir 写入指定维度的 mock annotation 文件。
    specs: {dim_key: days_ago} — None 表示不写（缺失）
    extras: {dim_key: {extra fields}}
    """
    if extras is None:
        extras = {}
    for dim, days in specs.items():
        if days is None:
            continue  # 不写 = 文件缺失
        fname = DIMENSION_META[dim]["file"]
        path  = os.path.join(tmpdir, fname)
        data  = _make_annotation(dim, days, extras.get(dim))
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def _run_gate(tmpdir: str, today: Optional[datetime] = None,
              is_btc: bool = True) -> Dict:
    return check_annotation_freshness(base=tmpdir, today=today, is_btc=is_btc)


# ── 场景定义 ──────────────────────────────────────────────────────────────────

TODAY = datetime.now()


def scenario(name: str):
    print(f"\n{'─'*60}")
    print(f"  {name}")
    print(f"{'─'*60}")


# ─────────────────────────────────────────────────────────────────────────────
# S01: 所有 annotation 新鲜
# ─────────────────────────────────────────────────────────────────────────────
scenario("S01 — 所有 annotation 新鲜 → FULL")
with tempfile.TemporaryDirectory() as td:
    _write_annotations(td, {dim: 1 for dim in CORE_DIMS})
    g = _run_gate(td)
    assert_eq("gate_level", g["gate_level"], "FULL")
    assert_true("gate_pass", g["gate_pass"])
    assert_eq("n_fresh", g["n_fresh"], 5)
    assert_false("stale_dims empty", bool(g["stale_dims"]))
    assert_false("missing_dims empty", bool(g["missing_dims"]))
    assert_false("dep_violations empty", bool(g["dependency_violations"]))
    assert_eq("gate_confidence_mult", g["gate_confidence_mult"], 1.0)


# ─────────────────────────────────────────────────────────────────────────────
# S02: 全部 annotation 缺失
# ─────────────────────────────────────────────────────────────────────────────
scenario("S02 — 全部 annotation 缺失 → BASELINE")
with tempfile.TemporaryDirectory() as td:
    g = _run_gate(td)
    assert_eq("gate_level", g["gate_level"], "BASELINE")
    assert_false("gate_pass", g["gate_pass"])
    assert_eq("n_fresh", g["n_fresh"], 0)
    assert_eq("n_missing", len(g["missing_dims"]), 5)
    assert_eq("confidence_mult", g["gate_confidence_mult"], 0.5)
    assert_false("clock_stage none", bool(g["clock_stage"]))
    assert_false("skill_regime none", bool(g["skill_regime"]))
    # recommendations 应包含所有5个 SKILL
    assert_eq("recommendations count", len(g["recommendations"]), 5)


# ─────────────────────────────────────────────────────────────────────────────
# S03: 3/5 新鲜（E macro + F cross_market 缺失）
# ─────────────────────────────────────────────────────────────────────────────
scenario("S03 — 3/5 新鲜（E/F 缺失）→ PARTIAL")
with tempfile.TemporaryDirectory() as td:
    _write_annotations(td, {"cycle": 1, "miner": 1, "onchain": 1})
    g = _run_gate(td)
    assert_eq("gate_level", g["gate_level"], "PARTIAL")
    assert_false("gate_pass", g["gate_pass"])
    assert_eq("n_fresh", g["n_fresh"], 3)
    assert_in("macro in missing", "macro", g["missing_dims"])
    assert_in("cross_market in missing", "cross_market", g["missing_dims"])
    assert_eq("confidence_mult", g["gate_confidence_mult"], 0.8)
    assert_false("clock_stage none (F缺失)", bool(g["clock_stage"]))


# ─────────────────────────────────────────────────────────────────────────────
# S04: 4/5 新鲜（仅 B cycle 过期）
# ─────────────────────────────────────────────────────────────────────────────
scenario("S04 — 4/5 新鲜（仅 B 过期 15天 > max_days 14）→ PARTIAL")
with tempfile.TemporaryDirectory() as td:
    _write_annotations(td, {
        "cycle": 15,   # 超过 max_days=14 → STALE
        "miner": 1, "onchain": 1, "macro": 1, "cross_market": 1,
    })
    g = _run_gate(td)
    assert_eq("gate_level", g["gate_level"], "PARTIAL")
    assert_in("cycle stale", "cycle", g["stale_dims"])
    assert_eq("n_fresh", g["n_fresh"], 4)
    # SKILL recommendations 应包含 B
    recs = " ".join(g["recommendations"])
    assert_in("cycle skill in rec", "/screen1-halving-cycle", recs)


# ─────────────────────────────────────────────────────────────────────────────
# S05: B 有效期边界（12 天前更新，max_days=14）→ 应为 FRESH
# ─────────────────────────────────────────────────────────────────────────────
scenario("S05 — B cycle 12天前更新（max_days=14）→ FRESH（边界验证）")
with tempfile.TemporaryDirectory() as td:
    _write_annotations(td, {dim: 1 for dim in CORE_DIMS})
    # 覆盖 cycle 为 12 天前
    _write_annotations(td, {"cycle": 12})
    g = _run_gate(td)
    cycle_status = g["dimensions"]["cycle"]["status"]
    assert_eq("cycle FRESH at 12d (max=14)", cycle_status, STATUS_FRESH)
    assert_eq("gate_level FULL", g["gate_level"], "FULL")


# ─────────────────────────────────────────────────────────────────────────────
# S06: E 过期 + F 新鲜 → 依赖违规被检出
# ─────────────────────────────────────────────────────────────────────────────
scenario("S06 — E(macro) 过期 + F(cross_market) 新鲜 → 依赖违规")
with tempfile.TemporaryDirectory() as td:
    _write_annotations(td, {
        "cycle": 1, "miner": 1, "onchain": 1,
        "macro": 10,         # STALE（>7天）
        "cross_market": 1,   # FRESH → 但依赖 E 已过期
    })
    g = _run_gate(td)
    assert_true("dep_violations not empty", bool(g["dependency_violations"]))
    assert_in("macro in stale", "macro", g["stale_dims"])
    # cross_market 自身是 FRESH，但 E 过期 → 违规记录
    viol_text = " ".join(g["dependency_violations"])
    assert_in("violation mentions macro", "宏观金融", viol_text)
    # recommendations 应提示先运行 E 再运行 F
    recs = " ".join(g["recommendations"])
    assert_in("ordering tip in recs", "screen1-macro-finance", recs)


# ─────────────────────────────────────────────────────────────────────────────
# S07: E 缺失 + F 新鲜 → 依赖违规（更严重）
# ─────────────────────────────────────────────────────────────────────────────
scenario("S07 — E 缺失 + F 新鲜 → 依赖违规（缺失比过期更严重）")
with tempfile.TemporaryDirectory() as td:
    _write_annotations(td, {
        "cycle": 1, "miner": 1, "onchain": 1,
        # macro 不写 = 缺失
        "cross_market": 1,
    })
    g = _run_gate(td)
    assert_true("dep_violations not empty", bool(g["dependency_violations"]))
    viol_text = " ".join(g["dependency_violations"])
    assert_in("violation mentions missing", "缺失", viol_text)
    assert_in("macro in missing", "macro", g["missing_dims"])


# ─────────────────────────────────────────────────────────────────────────────
# S08: skill_regime 有效值 → 正确读取
# ─────────────────────────────────────────────────────────────────────────────
scenario("S08 — skill_regime=STRONG_BEAR 写入 cross_asset → 正确读取")
with tempfile.TemporaryDirectory() as td:
    _write_annotations(td, {dim: 1 for dim in CORE_DIMS})
    _write_annotations(td, {"cross_asset": 1},
                       extras={"cross_asset": {"skill_regime": "STRONG_BEAR"}})
    g = _run_gate(td)
    assert_eq("skill_regime", g["skill_regime"], "STRONG_BEAR")
    assert_eq("gate_level FULL", g["gate_level"], "FULL")


# ─────────────────────────────────────────────────────────────────────────────
# S09: skill_regime 非法值 → 被忽略，skill_regime=None
# ─────────────────────────────────────────────────────────────────────────────
scenario("S09 — skill_regime='INVALID_VALUE' → 被忽略")
with tempfile.TemporaryDirectory() as td:
    _write_annotations(td, {dim: 1 for dim in CORE_DIMS})
    _write_annotations(td, {"cross_asset": 1},
                       extras={"cross_asset": {"skill_regime": "INVALID_VALUE"}})
    g = _run_gate(td)
    assert_false("skill_regime is None/empty", bool(g["skill_regime"]),
                 f"got: {g['skill_regime']!r}")


# ─────────────────────────────────────────────────────────────────────────────
# S10: clock_stage 从 F annotation 提取
# ─────────────────────────────────────────────────────────────────────────────
scenario("S10 — clock_stage 从 F annotation 提取")
for expected_clock in ["RECOVERY", "OVERHEAT", "STAGFLATION", "STAGFLATION_LITE", "REFLATION"]:
    with tempfile.TemporaryDirectory() as td:
        _write_annotations(td, {dim: 1 for dim in CORE_DIMS},
                           extras={"cross_market": {"clock_stage": expected_clock}})
        g = _run_gate(td)
        assert_eq(f"clock_stage={expected_clock}", g["clock_stage"], expected_clock)


# ─────────────────────────────────────────────────────────────────────────────
# S11: 非 BTC 标的 → BTC-only 维度全部 SKIPPED
# ─────────────────────────────────────────────────────────────────────────────
scenario("S11 — is_btc=False → BTC-only 维度 SKIPPED")
with tempfile.TemporaryDirectory() as td:
    # 即使写入了文件，btc_only 维度也应该被跳过
    _write_annotations(td, {dim: 1 for dim in CORE_DIMS})
    g = _run_gate(td, is_btc=False)
    btc_only_dims = [d for d in DIMENSION_META if DIMENSION_META[d]["btc_only"]]
    for dim in btc_only_dims:
        dim_status = g["dimensions"].get(dim, {}).get("status")
        assert_eq(f"{dim} SKIPPED when not BTC", dim_status, "SKIPPED")
    # 宏观维度（btc_only=False）应正常检查
    macro_status = g["dimensions"].get("macro", {}).get("status")
    assert_eq("macro FRESH when not BTC", macro_status, STATUS_FRESH)


# ─────────────────────────────────────────────────────────────────────────────
# S12: E 刚好 7天前更新（边界，max_days=7）
# ─────────────────────────────────────────────────────────────────────────────
scenario("S12 — E macro 刚好 7 天前 → FRESH（边界 max_days=7）")
with tempfile.TemporaryDirectory() as td:
    _write_annotations(td, {dim: 7 for dim in CORE_DIMS})
    g = _run_gate(td)
    macro_status = g["dimensions"]["macro"]["status"]
    assert_eq("macro FRESH at exactly max_days=7", macro_status, STATUS_FRESH)

scenario("S12b — E macro 8 天前 → STALE（刚超边界）")
with tempfile.TemporaryDirectory() as td:
    _write_annotations(td, {dim: 1 for dim in CORE_DIMS})
    _write_annotations(td, {"macro": 8})
    g = _run_gate(td)
    macro_status = g["dimensions"]["macro"]["status"]
    assert_eq("macro STALE at 8d (max=7)", macro_status, STATUS_STALE)
    assert_in("macro in stale_dims", "macro", g["stale_dims"])


# ─────────────────────────────────────────────────────────────────────────────
# S13: 所有象限 × phase1=True/False → calc_cross_asset_allocation 无异常
# ─────────────────────────────────────────────────────────────────────────────
scenario("S13 — 所有象限 × Phase1/Phase2 组合 → cross_asset_allocator 无异常")
clocks = ["RECOVERY", "OVERHEAT", "STAGFLATION", "STAGFLATION_LITE", "REFLATION"]
regimes = ["STRONG_BULL", "WEAK_BULL", "CONSOLIDATION", "WEAK_BEAR", "STRONG_BEAR"]

for clock in clocks:
    for phase1 in [True, False]:
        try:
            r = calc_cross_asset_allocation(
                clock_stage=clock,
                regime=regimes[clocks.index(clock)],
                phase1_only=phase1,
            )
            assert r["ml_clock_phase"] == clock, f"clock mismatch: {r['ml_clock_phase']}"
            # 验证配置完整性
            alloc = r["allocation"]
            total = (sum(x["weight"] for x in alloc["long"]) +
                     sum(x["weight"] for x in alloc["short"]) +
                     alloc["cash"])
            assert abs(total - 1.0) < 1e-6, f"权重之和 {total:.4f} ≠ 1.0"
            _ok(f"{clock} Phase{'1' if phase1 else '2'}: weights sum=1.0, {len(alloc['long'])}L/{len(alloc['short'])}S")
        except Exception as e:
            _fail(f"{clock} Phase{'1' if phase1 else '2'}", str(e))


# ─────────────────────────────────────────────────────────────────────────────
# S14: calc_cross_asset_allocation 使用 None clock_stage → 默认 STAGFLATION_LITE
# ─────────────────────────────────────────────────────────────────────────────
scenario("S14 — clock_stage=None → 默认 STAGFLATION_LITE")
r = calc_cross_asset_allocation(clock_stage=None, regime="STRONG_BEAR", phase1_only=True)
assert_eq("clock defaults to STAGFLATION_LITE", r["ml_clock_phase"], "STAGFLATION_LITE")
assert_true("btc_role correct", r["btc_role"] == "high_beta_short")


# ─────────────────────────────────────────────────────────────────────────────
# S15: gate 报告可渲染（format_gate_report 不崩溃）
# ─────────────────────────────────────────────────────────────────────────────
scenario("S15 — format_gate_report 在各种状态下均可渲染")
for state_name, specs in [
    ("FULL",     {dim: 1 for dim in CORE_DIMS}),
    ("PARTIAL",  {"cycle": 1, "miner": 1, "onchain": 1}),
    ("BASELINE", {}),
    ("STALE_E",  {dim: 1 for dim in CORE_DIMS if dim != "macro"} | {"macro": 10}),
]:
    with tempfile.TemporaryDirectory() as td:
        _write_annotations(td, specs)
        g = _run_gate(td)
        try:
            report = format_gate_report(g)
            assert len(report) > 100, "报告内容异常短"
            _ok(f"format_gate_report({state_name}): {len(report)} chars")
        except Exception as e:
            _fail(f"format_gate_report({state_name})", str(e))


# ─────────────────────────────────────────────────────────────────────────────
# S16: 工作流完整集成模拟（门禁 → clock_stage → cross_asset_allocation）
# ─────────────────────────────────────────────────────────────────────────────
scenario("S16 — 完整工作流集成: 门禁输出直接驱动 cross_asset_allocation")

WORKFLOW_CASES = [
    # (说明, specs, extra_cross_market, expected_clock, expected_btc_role)
    ("FULL+Recovery",
     {**{dim: 1 for dim in CORE_DIMS}},
     {"clock_stage": "RECOVERY"},
     "RECOVERY", "high_beta_long"),

    ("FULL+Stagflation_Lite",
     {**{dim: 1 for dim in CORE_DIMS}},
     {"clock_stage": "STAGFLATION_LITE"},
     "STAGFLATION_LITE", "high_beta_short"),

    ("FULL+Reflation",
     {**{dim: 1 for dim in CORE_DIMS}},
     {"clock_stage": "REFLATION"},
     "REFLATION", "accumulation_lhs"),

    ("PARTIAL_no_F",
     {"cycle": 1, "miner": 1, "onchain": 1, "macro": 1},
     None,
     "STAGFLATION_LITE",   # F 缺失 → 使用代码默认值
     "high_beta_short"),

    ("BASELINE",
     {},
     None,
     "STAGFLATION_LITE",   # 全缺失 → 默认
     "high_beta_short"),
]

for case_name, specs, extra_cm, exp_clock, exp_role in WORKFLOW_CASES:
    with tempfile.TemporaryDirectory() as td:
        extras = {}
        if extra_cm:
            extras["cross_market"] = extra_cm
        _write_annotations(td, specs, extras=extras)
        g = _run_gate(td)

        # 模拟 run_screen1 中的 clock_stage 选择逻辑
        clock = g.get("clock_stage") or "STAGFLATION_LITE"
        try:
            r = calc_cross_asset_allocation(
                clock_stage=clock, regime="STRONG_BEAR", phase1_only=True
            )
            assert_eq(f"[{case_name}] clock_stage", r["ml_clock_phase"], exp_clock)
            assert_eq(f"[{case_name}] btc_role",    r["btc_role"],       exp_role)
            # 权重完整性
            alloc = r["allocation"]
            total = (sum(x["weight"] for x in alloc["long"]) +
                     sum(x["weight"] for x in alloc["short"]) +
                     alloc["cash"])
            assert_true(f"[{case_name}] weights sum ≈ 1.0",
                        abs(total - 1.0) < 1e-6,
                        f"total={total:.4f}")
        except Exception as e:
            _fail(f"[{case_name}] workflow exception", str(e))
            traceback.print_exc()


# ── 汇总 ──────────────────────────────────────────────────────────────────────
print(f"\n{'═'*60}")
print(f"  压力测试汇总")
print(f"{'═'*60}")
print(f"  通过: {PASS_COUNT}  失败: {FAIL_COUNT}  总计: {PASS_COUNT + FAIL_COUNT}")
if ERRORS:
    print(f"\n  失败明细:")
    for e in ERRORS:
        print(f"  {e}")
print(f"{'═'*60}")

if FAIL_COUNT == 0:
    print("\n  ✅ 所有场景通过，门禁工作流验证完成")
    sys.exit(0)
else:
    print(f"\n  ❌ {FAIL_COUNT} 个场景失败，需要修复")
    sys.exit(1)
