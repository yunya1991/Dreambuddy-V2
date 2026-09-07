#!/usr/bin/env python3
"""fd7engines_hitrate_eval.py — Fundamental 7引擎 Shadow 7门槛评估 CLI
（Spec §6.3 Fundamental Shadow 7门槛 / CheckList D3）

Usage:
  python3 fd7engines_hitrate_eval.py <jsonl_path>

7 门槛（样本≥1500 且 7/7 PASS 才允许改红线）：
  G1 · hit_rate_effective   ≥ 60%  = count(_hit==1) / total
  G2 · thaw_accuracy        ≥ 70%  = count(_thaw==1) / count(_thaw exists)；无记录→中性PASS
  G3 · sharpe_annual        ≥ 1.05 = sqrt(252) × mean(_pnl) / max(std(_pnl), 1e-9)；空/全0→中性PASS
  G4 · IMPORT_FAIL_total    = 0    = sum(import_fail_count)
  G5 · S_ACCURACY           ≥ 75%  = count(_s_acc==1) / total
  G6 · A_CONSISTENCY        ≥ 60%  = count(_a_cons==1) / total
  G7 · SCHEMA_PASS_RATE     ≥ 95%  = count(_sch_pass==1) / total

Exit codes:
  0 · 全通过（样本≥1500 且 G1~G7 全 PASS）—— 允许 PR+CR 改红线
  1 · 样本≥1500 但至少 1 门 FAIL —— 保持红线 False
  2 · 样本不足（<1500）或文件/IO 错误 —— 观察中
"""
from __future__ import annotations

import json
import math
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
RUNTIME = REPO / "scripts" / "runtime"
MIN_RECORDS = 1500  # 7 日历天观察窗口（每 300s 一次 × 1 进程 ≈ 2016 次/周，1500 为保守下限）

# ── 7 门槛常量（Spec §6.3 硬编码）────────────────────────────────
HIT_RATE_MIN    = 0.60   # G1
THAW_ACC_MIN    = 0.70   # G2
SHARPE_MIN      = 1.05   # G3
IMPORT_FAIL_MAX = 0      # G4
S_ACC_MIN       = 0.75   # G5
A_CONS_MIN      = 0.60   # G6
SCHEMA_PASS_MIN = 0.95   # G7


# ── 1. JSONL 加载（错行跳过，文件不存在 stderr+空列表） ─────
def load_records(path: str) -> List[Dict[str, Any]]:
    """加载 JSONL 文件。文件不存在打印到 stderr 返回空列表；JSON 错行跳过。"""
    out: List[Dict[str, Any]] = []
    if not os.path.exists(path):
        print(f"[ERROR] JSONL 文件不存在：{path}", file=sys.stderr)
        return out
    try:
        with open(path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception as e:  # noqa: BLE001 — JSON 错行必须 fail-open
                    print(f"[WARN] L{i} JSON decode 失败跳过：{type(e).__name__}: {e}", file=sys.stderr)
    except (PermissionError, OSError) as e:
        print(f"[ERROR] 读取 JSONL 失败：{type(e).__name__}: {e}", file=sys.stderr)
        return []
    return out


# ── 2. 单门槛计算函数 ──────────────────────────────────────────
def _safe_is_one(val: Any) -> bool:
    """判断辅助键是否为「正样本1」：int 1、float 1.0、字符串 '1' 都算，其他（None/NaN/0/False）不算。"""
    if val is None:
        return False
    # bool 是 int 子类，True==1；但显式 bool True 也要算 1，False 算 0
    if isinstance(val, bool):
        return val is True
    if isinstance(val, (int, float)):
        # 排除 NaN
        try:
            if math.isnan(val):  # type: ignore[arg-type]
                return False
        except (TypeError, ValueError):
            pass
        return abs(float(val) - 1.0) < 1e-9
    if isinstance(val, str):
        return val.strip() == "1"
    return False


def _key_exists_not_none(r: Dict[str, Any], key: str) -> bool:
    """键存在且值不为 None / 非 NaN。"""
    if key not in r:
        return False
    v = r[key]
    if v is None:
        return False
    if isinstance(v, float) and math.isnan(v):
        return False
    return True


def g1_hit_rate(recs: List[Dict[str, Any]]) -> Tuple[float, bool]:
    """G1 · 预测方向命中率 _hit ≥ 60%。无 _hit 字段 → 中性 PASS。"""
    total = len(recs)
    if total == 0:
        return 0.0, True  # 空样本中性
    has_field = sum(1 for r in recs if _key_exists_not_none(r, "_hit"))
    if has_field == 0:
        return 0.0, True  # 无字段中性 PASS
    good = sum(1 for r in recs if _safe_is_one(r.get("_hit")))
    rate = good / total  # 分母 = total（与 Spec 一致）
    return rate, rate >= HIT_RATE_MIN


def g2_thaw_accuracy(recs: List[Dict[str, Any]]) -> Tuple[float, bool]:
    """G2 · 解冻命中率 _thaw ≥ 70%。无 _thaw 记录 → 中性 PASS。"""
    has_thaw = [r for r in recs if _key_exists_not_none(r, "_thaw")]
    if not has_thaw:
        return 0.0, True  # 无 _thaw → 中性 PASS
    good = sum(1 for r in has_thaw if _safe_is_one(r.get("_thaw")))
    rate = good / len(has_thaw)
    return rate, rate >= THAW_ACC_MIN


def g3_sharpe_annual(recs: List[Dict[str, Any]]) -> Tuple[float, bool]:
    """G3 · _pnl 年化 Sharpe ≥ 1.05。空或全 0 → 中性 PASS。"""
    pnls: List[float] = []
    for r in recs:
        if not _key_exists_not_none(r, "_pnl"):
            continue
        v = r["_pnl"]
        try:
            fv = float(v)
            if math.isnan(fv) or math.isinf(fv):
                continue
            pnls.append(fv)
        except (TypeError, ValueError):
            continue
    if not pnls:
        return 0.0, True  # 空 → 中性 PASS
    n = len(pnls)
    mean = sum(pnls) / n
    # 全 0（或几乎 0）
    if abs(mean) < 1e-12 and all(abs(x) < 1e-12 for x in pnls):
        return 0.0, True  # 全 0 → 中性 PASS
    # 总体 std（除以 n，与 pandas 默认一致）
    var = sum((x - mean) ** 2 for x in pnls) / n
    std = math.sqrt(var) if var > 0 else 0.0
    denom = max(std, 1e-9)
    sharpe_daily = mean / denom
    sharpe_annual = sharpe_daily * math.sqrt(252.0)
    return sharpe_annual, sharpe_annual >= SHARPE_MIN


def g4_import_fail(recs: List[Dict[str, Any]]) -> Tuple[int, bool]:
    """G4 · import_fail_count 求和 == 0。字段不存在 → 当 0 计。"""
    total = 0
    for r in recs:
        v = r.get("import_fail_count", 0)
        try:
            total += int(v) if v is not None and not (isinstance(v, float) and math.isnan(v)) else 0
        except (TypeError, ValueError):
            pass
    return total, total == IMPORT_FAIL_MAX


def g5_s_accuracy(recs: List[Dict[str, Any]]) -> Tuple[float, bool]:
    """G5 · S 级引擎准确率 _s_acc ≥ 75%。无字段 → 中性 PASS。"""
    total = len(recs)
    if total == 0:
        return 0.0, True
    has_field = sum(1 for r in recs if _key_exists_not_none(r, "_s_acc"))
    if has_field == 0:
        return 0.0, True
    good = sum(1 for r in recs if _safe_is_one(r.get("_s_acc")))
    rate = good / total
    return rate, rate >= S_ACC_MIN


def g6_a_consistency(recs: List[Dict[str, Any]]) -> Tuple[float, bool]:
    """G6 · A 级引擎一致性 _a_cons ≥ 60%。无字段 → 中性 PASS。"""
    total = len(recs)
    if total == 0:
        return 0.0, True
    has_field = sum(1 for r in recs if _key_exists_not_none(r, "_a_cons"))
    if has_field == 0:
        return 0.0, True
    good = sum(1 for r in recs if _safe_is_one(r.get("_a_cons")))
    rate = good / total
    return rate, rate >= A_CONS_MIN


def g7_schema_pass(recs: List[Dict[str, Any]]) -> Tuple[float, bool]:
    """G7 · news_contract schema 通过率 _sch_pass ≥ 95%。无字段 → 中性 PASS。"""
    total = len(recs)
    if total == 0:
        return 0.0, True
    has_field = sum(1 for r in recs if _key_exists_not_none(r, "_sch_pass"))
    if has_field == 0:
        return 0.0, True
    good = sum(1 for r in recs if _safe_is_one(r.get("_sch_pass")))
    rate = good / total
    return rate, rate >= SCHEMA_PASS_MIN


# ── 3. 主评估流程 ──────────────────────────────────────────────
def eval_seven_gates(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(records)
    reason_counter = Counter(str(r.get("shadow_reason_code", "N/A")) for r in records)

    g1_val, g1_pass = g1_hit_rate(records)
    g2_val, g2_pass = g2_thaw_accuracy(records)
    g3_val, g3_pass = g3_sharpe_annual(records)
    g4_val, g4_pass = g4_import_fail(records)
    g5_val, g5_pass = g5_s_accuracy(records)
    g6_val, g6_pass = g6_a_consistency(records)
    g7_val, g7_pass = g7_schema_pass(records)

    gates = {
        "G1_hit_rate_effective": {"value": round(g1_val, 4), "min": HIT_RATE_MIN,    "pass": g1_pass, "unit": ""},
        "G2_thaw_accuracy":      {"value": round(g2_val, 4), "min": THAW_ACC_MIN,    "pass": g2_pass, "unit": "", "note": "分母=含_thaw记录数；无_thaw→中性PASS"},
        "G3_sharpe_annual":      {"value": round(g3_val, 4), "min": SHARPE_MIN,      "pass": g3_pass, "unit": "", "note": "sqrt(252)×mean/std；空/全0→中性PASS"},
        "G4_IMPORT_FAIL_total":  {"value": g4_val,           "max": IMPORT_FAIL_MAX, "pass": g4_pass, "unit": ""},
        "G5_S_ACCURACY":         {"value": round(g5_val, 4), "min": S_ACC_MIN,       "pass": g5_pass, "unit": ""},
        "G6_A_CONSISTENCY":      {"value": round(g6_val, 4), "min": A_CONS_MIN,      "pass": g6_pass, "unit": ""},
        "G7_SCHEMA_PASS_RATE":   {"value": round(g7_val, 4), "min": SCHEMA_PASS_MIN, "pass": g7_pass, "unit": ""},
    }
    all_pass = all(g["pass"] for g in gates.values())

    return {
        "total_records": total,
        "MIN_RECORDS": MIN_RECORDS,
        "SAMPLE_READY": total >= MIN_RECORDS,
        "reason_distribution": dict(reason_counter),
        "gates": gates,
        "ALL_PASS": all_pass,
    }


# ── 4. stdout 打印报表 ────────────────────────────────────────
def print_report(report: Dict[str, Any]) -> None:
    print("=" * 76)
    print("Fundamental 7引擎 Shadow 7门槛评估（Spec §6.3 / CheckList D3）")
    print(f"  记录总数 total          = {report['total_records']}")
    print(f"  样本≥1500  7天窗口就位  = {report['SAMPLE_READY']}   (MIN={MIN_RECORDS})")
    print(f"  reason_code 分布        = {report['reason_distribution']}")
    print("-" * 76)
    for code, g in report["gates"].items():
        pv = g.get("value")
        threshold = f">= {g.get('min')}" if "min" in g else f"<= {g.get('max')}"
        if isinstance(pv, float):
            pv_str = f"{pv:.4f}"
        else:
            pv_str = str(pv)
        mark = "✅ PASS" if g["pass"] else "❌ FAIL"
        print(f"  {code:26s}  value= {pv_str:>10s}  门槛 {threshold:10s}  → {mark}")
        if "note" in g:
            print(f"         note: {g['note']}")
    print("-" * 76)
    print(f"  7 门槛 ALL_PASS = {report['ALL_PASS']}")
    if report["ALL_PASS"] and report["SAMPLE_READY"]:
        print("  ✦ 允许发起 PR+CR：将 enable_fundamental_7engines_production_injection 默认改为 True")
    elif not report["SAMPLE_READY"]:
        print(f"  ⏳ 样本未达 {MIN_RECORDS}，请继续观察（≥7 日历天）。当前 {report['total_records']}")
    else:
        print("  ✗ 门槛未过：保持红线 False，不允许打开正式注入开关。")
    print("=" * 76)


# ── 5. 入口：argv[1]=jsonl_path（TC-9/10 要求位置参数，不使用 argparse）
def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print(f"[USAGE] {argv[0]} <jsonl_path>", file=sys.stderr)
        return 2  # 用法错 → 视为「观察中/条件不满足」
    jsonl_path = argv[1]
    records = load_records(jsonl_path)
    report = eval_seven_gates(records)
    report["generated_at_iso"] = datetime.utcnow().isoformat() + "Z"
    report["jsonl_path"] = str(Path(jsonl_path).resolve()) if os.path.exists(jsonl_path) else jsonl_path

    # 写报告 JSON（运行时目录；失败忽略不影响退出码）
    try:
        RUNTIME.mkdir(parents=True, exist_ok=True)
        report_out = RUNTIME / "fundamental_7engines_eval_report.json"
        with open(report_out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, sort_keys=True)
    except Exception:  # noqa: BLE001 — 报表写失败永不影响退出码
        pass

    print_report(report)

    # 退出码判定（三态铁律）
    if not report["SAMPLE_READY"]:
        return 2
    return 0 if report["ALL_PASS"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
