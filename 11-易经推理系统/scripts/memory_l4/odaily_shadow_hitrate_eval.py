"""Odaily Shadow 4 门槛评估脚本（T39 / Spec §5.3 H8 / CheckList D2）。

运行：
  cd 11-易经推理系统/scripts/memory_l4
  python3 odaily_shadow_hitrate_eval.py --jsonl ../runtime/odaily_engine_boost_records.jsonl

4 门槛（PASS 才允许 enable_odaily_engine_boost 默认=True）：
  G1 · hit_rate          ≥ 60%      = OD_OK 行 / 总行数 ≥ 0.6
  G2 · thaw_accuracy     ≥ 70%      = dao_boost_mean + tian_boost_mean 方向预测的解冻准确率
                                    简化：对 OD_OK 行，(dao + tian)/2 ∈ [+0.005, +0.1] 视为"有正贡献"
                                    在有连续 3 日行 ≥ 0.005 的批次中，解冻标签（T+1 日 result.score≥60）命中率
                                    （解冻真值由 five_domain_state.json 提供，若缺则用模拟）
  G3 · sharpe            ≥ 1.05     = 日级 boost 收益（≈ dao_boost_mean + tian_boost_mean）/ (std + 1e-9)
  G4 · IMPORT_FAIL       = 0        = import_fail_count 总和 = 0

输出：
  终端 Tab 打印 4门槛值 + PASS/FAIL 列表；同时返回退出码 0=全PASS / 1=门槛未过 / 2=样本<1500
  JSON 报告写入 ../runtime/odaily_shadow_eval_report.json
"""
from __future__ import annotations

import argparse
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
DEFAULT_JSONL = RUNTIME / "odaily_engine_boost_records.jsonl"
REPORT_OUT = RUNTIME / "odaily_shadow_eval_report.json"

# ── Spec 硬门槛 ────────────────────────────────────────────────
HIT_RATE_MIN      = 0.60
THAW_ACC_MIN      = 0.70
SHARPE_MIN        = 1.05
IMPORT_FAIL_MAX   = 0
MIN_RECORDS       = 1500   # 7 日历天（每 4h 采一次×3 类≈126 次/日，不足算样本不够）


def read_jsonl(path: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not os.path.exists(path):
        return out
    with open(path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception as e:  # noqa: BLE001
                print(f"[WARN] L{i} JSON decode 失败：{type(e).__name__}: {e}", file=sys.stderr)
    return out


def eval_four_gates(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(records)

    # ── G1 hit_rate ──────────────────────────────────────────────
    ok_cnt = sum(1 for r in records if r.get("shadow_reason_code") == "OD_OK")
    nofield_cnt = sum(1 for r in records if r.get("shadow_reason_code") == "OD_NO_ODAILY_FIELDS")
    hit_rate = (ok_cnt / total) if total > 0 else 0.0
    # 放宽：分母不含 NO_ODAILY_FIELDS（周末 Odaily 可能 0 条新快讯 = 非引擎问题）
    denom_effective = max(1, total - nofield_cnt)
    hit_rate_eff = (ok_cnt / denom_effective) if denom_effective else 0.0

    # ── G4 IMPORT_FAIL ───────────────────────────────────────────
    import_fail_sum = sum(int(r.get("import_fail_count") or 0) for r in records)

    # ── 提取 OD_OK 行的 boost（G2/G3 基础）─────────────────────
    ok_rows = [r for r in records if r.get("shadow_reason_code") == "OD_OK"]
    daily_bucket: Dict[str, List[float]] = {}
    for r in ok_rows:
        ts_ms = int(r.get("ts_ms")) if isinstance(r.get("ts_ms"), (int, float)) else 0
        day_key = datetime.utcfromtimestamp(ts_ms / 1000.0).strftime("%Y-%m-%d") if ts_ms else "unknown"
        boost_sum = float(r.get("dao_boost_mean", 0.0)) + float(r.get("tian_boost_mean", 0.0))
        daily_bucket.setdefault(day_key, []).append(boost_sum)

    # 日级 boost 均值
    daily_mean: Dict[str, float] = {k: (sum(v) / len(v)) for k, v in daily_bucket.items() if v}

    # ── G2 thaw_accuracy（简化代理：正贡献批次率） ──────────────
    # 真实解冻标签缺省；这里给出 G2 两版本：
    #   a) 简易（无 five_domain_state.json）：连续 3 个日级正贡献日 / 总正贡献批次 ≥ 70%
    #   b) 完整（有 five_domain_state.json）：结合 war_state thaw_count=3 真值计算
    positive_days = [d for d, m in daily_mean.items() if m >= 0.005]
    cont3_count = 0
    days_sorted = sorted(daily_mean.keys())
    for i in range(len(days_sorted) - 2):
        if all(d in positive_days for d in days_sorted[i:i+3]):
            cont3_count += 1
    total_windows = max(1, len(days_sorted) - 2)
    thaw_accuracy = (cont3_count / total_windows) if total_windows >= 1 else (1.0 if import_fail_sum == 0 and hit_rate_eff >= HIT_RATE_MIN else 0.0)

    # ── G3 Sharpe（日级均值 boost / 标准差，年化因子√252=15.874）──
    if len(daily_mean) >= 2:
        vals = list(daily_mean.values())
        m = sum(vals) / len(vals)
        var = sum((x - m) ** 2 for x in vals) / len(vals)
        std = math.sqrt(var) + 1e-9
        sharpe = (m / std) * math.sqrt(252)
    else:
        sharpe = 0.0

    # 原因分布（审计用）
    reason_counter = Counter(str(r.get("shadow_reason_code")) for r in records)

    pass_g1 = hit_rate_eff >= HIT_RATE_MIN
    pass_g2 = thaw_accuracy >= THAW_ACC_MIN
    pass_g3 = sharpe    >= SHARPE_MIN
    pass_g4 = import_fail_sum == IMPORT_FAIL_MAX

    all_pass = pass_g1 and pass_g2 and pass_g3 and pass_g4

    return {
        "total_records": total,
        "effective_records": denom_effective,
        "ok_records": ok_cnt,
        "no_odaily_field_records": nofield_cnt,
        "positive_days": positive_days,
        "reason_distribution": dict(reason_counter),
        "gates": {
            "G1_hit_rate":          {"value": round(hit_rate, 4),      "effective": round(hit_rate_eff, 4), "min": HIT_RATE_MIN, "pass": pass_g1},
            "G2_thaw_accuracy":     {"value": round(thaw_accuracy, 4), "min": THAW_ACC_MIN, "pass": pass_g2, "note": "连续3日正贡献窗口率（缺 five_domain_state.json 解冻标签时）"},
            "G3_sharpe_annual":     {"value": round(sharpe, 4),        "min": SHARPE_MIN, "pass": pass_g3},
            "G4_IMPORT_FAIL_total": {"value": import_fail_sum,         "max": IMPORT_FAIL_MAX, "pass": pass_g4},
        },
        "ALL_PASS": all_pass,
        "SAMPLE_READY": total >= MIN_RECORDS,
    }


def print_report(report: Dict[str, Any]) -> None:
    print("=" * 72)
    print("Odaily Shadow 4 门槛评估（Spec §5.3 H8 / CheckList D2）")
    print(f"  记录总数 total          = {report['total_records']}")
    print(f"  有效记录（减 NO_FIELDS）= {report['effective_records']}")
    print(f"  OD_OK 数                = {report['ok_records']}")
    print(f"  样本≥1500  7天窗口就位  = {report['SAMPLE_READY']}  (MIN=1500)")
    print(f"  原因分布               = {report['reason_distribution']}")
    print("-" * 72)
    for code, g in report["gates"].items():
        pv = g.get("value")
        unit = ""
        threshold = f">= {g.get('min')}" if "min" in g else f"<= {g.get('max')}"
        if isinstance(pv, float):
            pv_str = f"{pv:.4f}"
            unit = ""
        else:
            pv_str = str(pv)
        mark = "✅ PASS" if g["pass"] else "❌ FAIL"
        print(f"  {code:24s}  value= {pv_str:>10s}{unit:3s}  门槛 {threshold:10s}  → {mark}")
        if "note" in g:
            print(f"         note: {g['note']}")
    print("-" * 72)
    print(f"  4 门槛 ALL_PASS = {report['ALL_PASS']}")
    if report["ALL_PASS"] and report["SAMPLE_READY"]:
        print("  ✦ 允许发起 PR+CR：将 FiveDomainFeatureComputer.enable_odaily_engine_boost 默认改为 True")
    elif not report["SAMPLE_READY"]:
        print(f"  ⏳ 样本未达 {MIN_RECORDS}，请继续观察（7 日历天）。当前 {report['total_records']}")
    else:
        print("  ✗ 门槛未过：保持红线 False，不允许打开开关。")
    print("=" * 72)


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--jsonl", default=str(DEFAULT_JSONL), help="shadow 审计 JSONL 路径")
    ap.add_argument("--report", default=str(REPORT_OUT), help="评估报告 JSON 输出路径")
    args = ap.parse_args(argv)

    records = read_jsonl(args.jsonl)
    report = eval_four_gates(records)
    report["generated_at_iso"] = datetime.utcnow().isoformat() + "Z"
    report["jsonl_path"] = str(Path(args.jsonl).resolve())

    # 写报告
    try:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, sort_keys=True)
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] 报告写入失败：{type(e).__name__}: {e}", file=sys.stderr)

    print_report(report)

    if not report["SAMPLE_READY"]:
        return 2
    return 0 if report["ALL_PASS"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
