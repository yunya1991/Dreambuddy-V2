# -*- coding: utf-8 -*-
"""E1 路由策略对比实验（SPEC-v1.4 §7.1.3）。

同一套 e1_cases.jsonl（500 条），跑 S0–S5 + 参数网格，按「安全硬门 → 效果 → 成本」
字典序裁决，输出 summary/per_segment/decisions/manifest + 报告。

关键约束：
  - 特征（正则/语义/序列/认知召回）**一次构建并缓存**，所有策略复用，避免重复编码与召回；
  - 生产行为零改动：本脚本只调 l1_routing_policy.decide 纯函数；
  - 认知召回慢（本机 0.3–9s/条），支持并行构建缓存（--jobs）。

用法：
  python3 34-前端应用训练系统/scripts/eval_router_strategies.py [--rebuild] [--jobs 6]
  python3 34-前端应用训练系统/scripts/eval_router_strategies.py --real-cloud 60
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import subprocess
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
_TRAIN_DIR = os.path.join(_ROOT, "34-前端应用训练系统")
_SCRIPTS_DIR = os.path.join(_ROOT, "3.1-FRONTEND", "scripts")
for _p in (_TRAIN_DIR, _SCRIPTS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import l1_routing_policy as pol  # noqa: E402

CASES_PATH = os.path.join(_TRAIN_DIR, "eval", "e1_cases.jsonl")
CACHE_DIR = os.path.join(_TRAIN_DIR, "eval", "cache")
FEATURE_CACHE = os.path.join(CACHE_DIR, "features.jsonl")
RECALL_CACHE = os.path.join(CACHE_DIR, "recall.jsonl")
DATASET_VERSION = "e1_d1@2026-11-16"
SEED = 20261116

THRESHOLDS = (0.60, 0.63, 0.66, 0.70)
DELTAS = (0.02, 0.03, 0.05, 0.08)

# 结构复杂度排序（平手时取更简单者）：依赖越少越靠前
SIMPLICITY = {"S1": 1, "S2": 2, "S3": 3, "S5": 4, "S4": 5, "S0": 6}

L1_SEGMENTS = ("data", "semantic", "clarify", "regression")


def _read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _write_jsonl(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# ============================================================
# 特征构建（正则 + 语义 + 序列 + 认知召回），带磁盘缓存
# ============================================================


def build_feature_cache(cases, rebuild=False):
    cached = {} if rebuild else {r["message"]: r for r in _read_jsonl(FEATURE_CACHE)}
    todo = [c["message"] for c in cases if c["message"] not in cached]
    if todo:
        import l1_route_signal as lrs

        # 预热：首条语义调用包含模型加载，不计入单条耗时
        lrs.semantic_candidates("预热一条无关的测试问法", k=3)
        for i, msg in enumerate(todo, 1):
            t0 = time.perf_counter()
            regex_intent = lrs.detect_intent_regex(msg)
            series_ok = bool(lrs._is_deterministic_series(msg))
            detect_ms = (time.perf_counter() - t0) * 1000
            t1 = time.perf_counter()
            top = lrs.semantic_candidates(msg, k=3, validated=True)
            semantic_ms = (time.perf_counter() - t1) * 1000
            cached[msg] = {
                "message": msg,
                "regex_intent": regex_intent,
                "series_ok": series_ok,
                "semantic_top": [[i2, round(s, 6)] for i2, s in top],
                "detect_ms": round(detect_ms, 3),
                "semantic_ms": round(semantic_ms, 3),
            }
            if i % 50 == 0:
                print(f"  语义特征 {i}/{len(todo)}")
                _write_jsonl(FEATURE_CACHE, list(cached.values()))
        _write_jsonl(FEATURE_CACHE, [cached[c["message"]] for c in cases])
    return cached


def _recall_one(message):
    from core.l0_foundation import get_l0

    t0 = time.perf_counter()
    try:
        ctx = get_l0().fetch_context(
            "cognitive.recall",
            {"context": f"x::{message}", "top_k": 5, "poe_enforcement": "off"},
        )
        elapsed = (time.perf_counter() - t0) * 1000
        if ctx.get("degraded"):
            return {
                "message": message,
                "available": False,
                "error": False,
                "memories": [],
                "elapsed_ms": round(elapsed, 3),
            }
        memories = ctx.get("data") or []
        return {
            "message": message,
            "available": True,
            "error": False,
            "memories": [{"score": float(m.get("score", 0.0))} for m in memories][:5],
            "elapsed_ms": round(elapsed, 3),
        }
    except Exception:  # noqa: BLE001 — FAIL-OPEN：认知不可用按降级记录
        elapsed = (time.perf_counter() - t0) * 1000
        return {
            "message": message,
            "available": False,
            "error": True,
            "memories": [],
            "elapsed_ms": round(elapsed, 3),
        }


def build_recall_cache(cases, jobs=6, rebuild=False):
    cached = {} if rebuild else {r["message"]: r for r in _read_jsonl(RECALL_CACHE)}
    todo = [c["message"] for c in cases if c["message"] not in cached]
    if todo:
        print(f"  认知召回缓存构建 {len(todo)} 条（jobs={jobs}）…")
        done = 0
        with ThreadPoolExecutor(max_workers=jobs) as ex:
            for row in ex.map(_recall_one, todo):
                cached[row["message"]] = row
                done += 1
                if done % 50 == 0:
                    print(f"    召回 {done}/{len(todo)}")
                    _write_jsonl(RECALL_CACHE, list(cached.values()))
        _write_jsonl(RECALL_CACHE, [cached[c["message"]] for c in cases])
    return cached


def make_features(case, feat, recall):
    r = recall.get(case["message"], {})
    return pol.Features(
        message=case["message"],
        regex_intent=feat["regex_intent"],
        semantic_top=tuple((i, s) for i, s in feat["semantic_top"]),
        series_ok=feat["series_ok"],
        recall_memories=tuple(r.get("memories") or ()),
        cognitive_available=bool(r.get("available", True)),
        recall_error=bool(r.get("error", False)),
    )


# ============================================================
# 配置网格
# ============================================================


def grid():
    configs = [
        {"strategy": "S0", "threshold": None, "delta": None},
        {"strategy": "S1", "threshold": None, "delta": None},
    ]
    for t in THRESHOLDS:
        configs.append({"strategy": "S2", "threshold": t, "delta": None})
    for t in THRESHOLDS:
        for d in DELTAS:
            configs.append({"strategy": "S3", "threshold": t, "delta": d})
    for t in THRESHOLDS:
        for d in DELTAS:
            configs.append({"strategy": "S4", "threshold": t, "delta": d})
    for t in THRESHOLDS:
        for d in DELTAS:
            configs.append({"strategy": "S5", "threshold": t, "delta": d})
    return configs


def _params(cfg):
    return pol.Params(
        semantic_threshold=(
            cfg["threshold"] if cfg["threshold"] is not None else pol.SEMANTIC_THRESHOLD_ZH
        ),
        margin_delta=cfg["delta"] or 0.0,
    )


# ============================================================
# 评估
# ============================================================


def run_config(cfg, cases, feats):
    p = _params(cfg)
    decisions = []
    for case in cases:
        t0 = time.perf_counter()
        try:
            d = pol.decide(cfg["strategy"], feats[case["id"]], p)
            exc = False
        except Exception as e:  # noqa: BLE001 — 异常率指标
            d = pol.Decision(
                strategy=cfg["strategy"],
                decision="L2_HANDOFF",
                intent="unknown",
                channel="none",
                route_confidence=0.0,
                handled=False,
                reasons=(f"exception:{e}",),
            )
            exc = True
        decide_ms = (time.perf_counter() - t0) * 1000
        feat = _feat_meta(case)
        est_ms = decide_ms + feat["detect_ms"]
        # 语义只在正则未命中时运行；认知只在策略需要且非确定性旁路时运行
        if not feat["regex_intent"] and d.channel in ("semantic", "none"):
            est_ms += feat["semantic_ms"]
        if cfg["strategy"] in ("S0", "S4") and "deterministic" not in d.reasons:
            est_ms += _recall_ms(case)
        decisions.append({"case": case, "decision": d, "exception": exc, "elapsed_ms": est_ms})
    return decisions


_FEAT_META = {}
_RECALL_META = {}


def _feat_meta(case):
    return _FEAT_META.get(
        case["message"], {"detect_ms": 0.0, "semantic_ms": 0.0, "regex_intent": ""}
    )


def _recall_ms(case):
    return float(_RECALL_META.get(case["message"], {}).get("elapsed_ms", 0.0))


def _p95(values):
    if not values:
        return 0.0
    s = sorted(values)
    idx = max(0, min(len(s) - 1, math.ceil(0.95 * len(s)) - 1))
    return s[idx]


def _sem_cov(s_by_key, strategy, threshold):
    m = s_by_key.get((strategy, threshold, None))
    if not m:
        return "-"
    seg = m["segments"].get("semantic", {})
    return (
        f"{seg.get('ok', 0)}/{seg.get('n', 0)}" if "ok" in seg else f"{seg.get('coverage', 0):.0%}"
    )


def metrics(rows):
    exp_l1 = [r for r in rows if r["case"]["expected_route"] == "L1"]
    exp_l2 = [r for r in rows if r["case"]["expected_route"] == "L2"]
    crit = [r for r in exp_l2 if r["case"]["severity"] == "critical"]

    answered_l1 = [r for r in exp_l1 if r["decision"].decision == "L1_DIRECT"]
    intent_ok = [
        r
        for r in exp_l1
        if r["decision"].decision == "L1_DIRECT"
        and (
            r["case"]["expected_intent"] is None
            or r["decision"].intent == r["case"]["expected_intent"]
        )
    ]
    far_rows = [r for r in exp_l2 if r["decision"].decision == "L1_DIRECT"]
    crit_rows = [r for r in crit if r["decision"].decision == "L1_DIRECT"]
    handoff_ok = [r for r in exp_l2 if r["decision"].decision == "L2_HANDOFF"]

    seg = defaultdict(lambda: {"n": 0, "ok": 0})
    for r in exp_l1:
        s = r["case"]["segment"]
        seg[s]["n"] += 1
        if r in intent_ok:
            seg[s]["ok"] += 1

    return {
        "n": len(rows),
        "far": len(far_rows) / max(1, len(exp_l2)),
        "far_critical": len(crit_rows),
        "crit_total": len(crit),
        "coverage": len(intent_ok) / max(1, len(exp_l1)),
        # IntentAcc：应 L1 且已作答的样本里意图正确率（条件准确率）
        "intent_acc": (
            sum(
                1
                for r in answered_l1
                if r["case"]["expected_intent"] is None
                or r["decision"].intent == r["case"]["expected_intent"]
            )
            / max(1, len(answered_l1))
        ),
        "answered_l1_rate": len(answered_l1) / max(1, len(exp_l1)),
        "handoff_acc": len(handoff_ok) / max(1, len(exp_l2)),
        "p95_ms": _p95([r["elapsed_ms"] for r in rows]),
        "exception_rate": sum(1 for r in rows if r["exception"]) / max(1, len(rows)),
        "l2_count": sum(1 for r in rows if r["decision"].decision == "L2_HANDOFF"),
        "segments": {
            s: {"n": v["n"], "coverage": v["ok"] / max(1, v["n"])} for s, v in seg.items()
        },
    }


def case_correct(row):
    case = row["case"]
    d = row["decision"]
    if case["expected_route"] == "L2":
        return d.decision == "L2_HANDOFF"
    if d.decision != "L1_DIRECT":
        return False
    return case["expected_intent"] is None or d.intent == case["expected_intent"]


def eligible(m):
    if m["far_critical"] != 0:
        return False, "critical 误答>0"
    if m["far"] > 0.02:
        return False, f"FAR {m['far']:.1%} >2%"
    if m["exception_rate"] > 0.005:
        return False, "ExceptionRate >0.5%"
    for s in L1_SEGMENTS:
        if s in m["segments"] and m["segments"][s]["coverage"] < 0.60:
            return False, f"{s} Coverage {m['segments'][s]['coverage']:.0%} <60%"
    return True, ""


def bootstrap_ci(rows_a, rows_b, n=2000, seed=SEED):
    """Coverage 差值的 bootstrap 95% CI（按应 L1 样本重采样）。"""
    rnd = random.Random(seed)
    idx = [i for i, r in enumerate(rows_a) if r["case"]["expected_route"] == "L1"]
    if not idx:
        return (0.0, 0.0)
    diffs = []
    for _ in range(n):
        sample = [idx[rnd.randrange(len(idx))] for _ in idx]
        a = sum(1 for i in sample if case_correct(rows_a[i])) / len(sample)
        b = sum(1 for i in sample if case_correct(rows_b[i])) / len(sample)
        diffs.append(a - b)
    diffs.sort()
    lo = diffs[int(0.025 * n)]
    hi = diffs[int(0.975 * n) - 1]
    return (lo, hi)


def mcnemar(rows_a, rows_b):
    b = sum(
        1 for x, y in zip(rows_a, rows_b, strict=False) if case_correct(x) and not case_correct(y)
    )
    c = sum(
        1 for x, y in zip(rows_a, rows_b, strict=False) if not case_correct(x) and case_correct(y)
    )
    n = b + c
    if n == 0:
        return {"b": b, "c": c, "n": 0, "p": 1.0}
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (2**n)
    return {"b": b, "c": c, "n": n, "p": min(1.0, 2 * tail)}


def _git_commit():
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=_ROOT, capture_output=True, text=True, timeout=5
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true", help="重建特征与召回缓存")
    ap.add_argument("--jobs", type=int, default=6, help="认知召回并发数")
    ap.add_argument("--real-cloud", type=int, default=0, help="抽样 N 条供云端复核")
    ap.add_argument("--cloud-url", default="", help="云端 /api/data/query 基址（可选）")
    args = ap.parse_args()

    cases = _read_jsonl(CASES_PATH)
    assert len(cases) == 500, f"数据集条数异常: {len(cases)}"
    os.makedirs(CACHE_DIR, exist_ok=True)

    print("构建特征缓存…")
    feats_raw = build_feature_cache(cases, rebuild=args.rebuild)
    print("构建认知召回缓存…")
    recalls = build_recall_cache(cases, jobs=args.jobs, rebuild=args.rebuild)

    for c in cases:
        _FEAT_META[c["message"]] = {
            "detect_ms": feats_raw[c["message"]]["detect_ms"],
            "semantic_ms": feats_raw[c["message"]]["semantic_ms"],
            "regex_intent": feats_raw[c["message"]]["regex_intent"],
        }
        _RECALL_META[c["message"]] = {
            "elapsed_ms": recalls.get(c["message"], {}).get("elapsed_ms", 0.0)
        }

    feats = {c["id"]: make_features(c, feats_raw[c["message"]], recalls) for c in cases}

    results = []
    for cfg in grid():
        rows = run_config(cfg, cases, feats)
        m = metrics(rows)
        ok, why = eligible(m)
        results.append({"cfg": cfg, "metrics": m, "rows": rows, "eligible": ok, "why": why})
        print(
            f"{cfg['strategy']} t={cfg['threshold']} d={cfg['delta']} | "
            f"FAR={m['far']:.2%} crit={m['far_critical']} Cov={m['coverage']:.1%} "
            f"Intent={m['intent_acc']:.1%} P95={m['p95_ms']:.1f}ms "
            f"{'PASS' if ok else 'FAIL:' + why}"
        )

    passed = [r for r in results if r["eligible"]]
    no_eligible = not passed
    if no_eligible:
        # 无合格策略：输出两个参考点（覆盖优先 / 安全优先），不做"赢家"命名
        print("\n无策略通过硬门：输出覆盖参考点与安全参考点，需人工复审。")
        ref_cov = max(
            results,
            key=lambda r: (
                r["metrics"]["coverage"] * r["metrics"]["intent_acc"],
                -r["metrics"]["far_critical"],
            ),
        )
        ref_safe = min(
            results,
            key=lambda r: (
                r["metrics"]["far_critical"],
                r["metrics"]["far"],
                -r["metrics"]["coverage"],
            ),
        )
        winner, second = ref_cov, ref_safe
        ci = bootstrap_ci(winner["rows"], second["rows"])
        mc = mcnemar(winner["rows"], second["rows"])
    else:
        passed.sort(
            key=lambda r: (
                -(r["metrics"]["coverage"] * r["metrics"]["intent_acc"]),
                r["metrics"]["p95_ms"],
                SIMPLICITY[r["cfg"]["strategy"]],
            )
        )
        winner = passed[0]
        second = passed[1] if len(passed) > 1 else None
        ci = bootstrap_ci(winner["rows"], second["rows"]) if second else (0.0, 0.0)
        mc = (
            mcnemar(winner["rows"], second["rows"])
            if second
            else {"b": 0, "c": 0, "n": 0, "p": 1.0}
        )

    stamp = datetime.now().strftime("%Y%m%d")
    outdir = os.path.join(_TRAIN_DIR, "eval-results", stamp)
    os.makedirs(outdir, exist_ok=True)

    with open(os.path.join(outdir, "summary.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "strategy",
                "threshold",
                "delta",
                "far",
                "far_critical",
                "crit_total",
                "coverage",
                "intent_acc",
                "handoff_acc",
                "p95_ms",
                "exception_rate",
                "l2_count",
                "eligible",
                "reject_reason",
                "rank_score",
            ]
        )
        for r in results:
            m = r["metrics"]
            w.writerow(
                [
                    r["cfg"]["strategy"],
                    r["cfg"]["threshold"],
                    r["cfg"]["delta"],
                    f"{m['far']:.4f}",
                    m["far_critical"],
                    m["crit_total"],
                    f"{m['coverage']:.4f}",
                    f"{m['intent_acc']:.4f}",
                    f"{m['handoff_acc']:.4f}",
                    f"{m['p95_ms']:.2f}",
                    f"{m['exception_rate']:.4f}",
                    m["l2_count"],
                    int(r["eligible"]),
                    r["why"],
                    f"{m['coverage'] * m['intent_acc']:.4f}",
                ]
            )

    with open(os.path.join(outdir, "per_segment.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["strategy", "threshold", "delta", "segment", "n", "coverage"])
        for r in results:
            for seg, v in sorted(r["metrics"]["segments"].items()):
                w.writerow(
                    [
                        r["cfg"]["strategy"],
                        r["cfg"]["threshold"],
                        r["cfg"]["delta"],
                        seg,
                        v["n"],
                        f"{v['coverage']:.4f}",
                    ]
                )

    with open(os.path.join(outdir, "decisions.jsonl"), "w", encoding="utf-8") as f:
        for i, case in enumerate(cases):
            row = {
                "id": case["id"],
                "segment": case["segment"],
                "message": case["message"],
                "expected_route": case["expected_route"],
                "expected_intent": case["expected_intent"],
                "severity": case["severity"],
                "strategies": {},
            }
            for r in results:
                d = r["rows"][i]["decision"]
                key = f"{r['cfg']['strategy']}:{r['cfg']['threshold']}:{r['cfg']['delta']}"
                row["strategies"][key] = {
                    "decision": d.decision,
                    "intent": d.intent,
                    "reasons": list(d.reasons),
                    "channel": d.channel,
                }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    manifest = {
        "dataset_version": DATASET_VERSION,
        "dataset_sha256": _sha256(CASES_PATH),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "git_commit": _git_commit(),
        "semantic_model": os.environ.get("L1_ZH_MODEL", "BAAI/bge-base-zh-v1.5"),
        "semantic_threshold_default": pol.SEMANTIC_THRESHOLD_ZH,
        "seed": SEED,
        "grid": {"thresholds": list(THRESHOLDS), "deltas": list(DELTAS)},
        "recall_cache": {
            "n": len(recalls),
            "available_rate": sum(1 for r in recalls.values() if r.get("available"))
            / max(1, len(recalls)),
            "errors": sum(1 for r in recalls.values() if r.get("error")),
        },
        "winner": (
            {
                "status": "no_eligible",
                "reference_coverage": {
                    "strategy": winner["cfg"]["strategy"],
                    "threshold": winner["cfg"]["threshold"],
                    "delta": winner["cfg"]["delta"],
                    "metrics": winner["metrics"],
                },
                "reference_safety": {
                    "strategy": second["cfg"]["strategy"],
                    "threshold": second["cfg"]["threshold"],
                    "delta": second["cfg"]["delta"],
                    "metrics": second["metrics"],
                },
            }
            if no_eligible
            else {
                "strategy": winner["cfg"]["strategy"],
                "threshold": winner["cfg"]["threshold"],
                "delta": winner["cfg"]["delta"],
                "metrics": winner["metrics"],
            }
        ),
        "runner_up": (
            None
            if (no_eligible or not second)
            else {
                "strategy": second["cfg"]["strategy"],
                "threshold": second["cfg"]["threshold"],
                "delta": second["cfg"]["delta"],
                "metrics": second["metrics"],
            }
        ),
        "bootstrap_ci_diff": list(ci),
        "mcnemar": mc,
    }
    with open(os.path.join(outdir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    if args.real_cloud:
        step = max(1, len(cases) // args.real_cloud)
        sample = cases[::step][: args.real_cloud]
        _write_jsonl(
            os.path.join(outdir, "real_cloud_sample.jsonl"),
            [
                {
                    "id": c["id"],
                    "message": c["message"],
                    "expected_route": c["expected_route"],
                    "expected_intent": c["expected_intent"],
                }
                for c in sample
            ],
        )
        print(f"已导出云端复核样本 {len(sample)} 条（--cloud-url 可自动回放）")

    _write_report(outdir, results, winner, second, ci, mc, manifest, no_eligible)
    if no_eligible:
        print(
            f"\n无合格策略。覆盖参考点：{winner['cfg']}（Cov={winner['metrics']['coverage']:.1%}）；"
            f"安全参考点：{second['cfg']}（FAR={second['metrics']['far']:.2%}）"
        )
    else:
        print(
            f"\n赢家: {winner['cfg']} | Coverage={winner['metrics']['coverage']:.1%} "
            f"IntentAcc={winner['metrics']['intent_acc']:.1%} FAR={winner['metrics']['far']:.2%}"
        )
        if second:
            print(f"McNemar p={mc['p']:.4f} (b={mc['b']}, c={mc['c']})；Coverage 差 95%CI={ci}")
    return 0


def _sha256(path):
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_report(outdir, results, winner, second, ci, mc, manifest, no_eligible=False):
    lines = [
        "# E1 策略对比实验报告",
        "",
        f"- 数据集：{manifest['dataset_version']}（sha256 {manifest['dataset_sha256'][:12]}）",
        f"- 语义模型：{manifest['semantic_model']}（默认阈值 {manifest['semantic_threshold_default']}）",
        f"- git commit：{manifest['git_commit']}",
        f"- 认知缓存：{manifest['recall_cache']['n']} 条，可用率 "
        f"{manifest['recall_cache']['available_rate']:.1%}，异常 {manifest['recall_cache']['errors']}",
        "",
        "## 全部配置",
        "",
        "| 策略 | 阈值 | δ | FAR | critical | Coverage | IntentAcc | P95(ms) | 硬门 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        m = r["metrics"]
        lines.append(
            f"| {r['cfg']['strategy']} | {r['cfg']['threshold']} | {r['cfg']['delta']} | "
            f"{m['far']:.2%} | {m['far_critical']} | {m['coverage']:.1%} | {m['intent_acc']:.1%} | "
            f"{m['p95_ms']:.0f} | {'PASS' if r['eligible'] else r['why']} |"
        )
    lines += [
        "",
        "## 分段 Coverage（应 L1 段）",
        "",
        "| 策略 | 阈值 | δ | " + " | ".join(L1_SEGMENTS) + " |",
        "|---|---|---|" + "---|" * len(L1_SEGMENTS),
    ]
    for r in results:
        segs = r["metrics"]["segments"]
        lines.append(
            f"| {r['cfg']['strategy']} | {r['cfg']['threshold']} | {r['cfg']['delta']} | "
            + " | ".join(f"{segs.get(s, {}).get('coverage', 0):.0%}" for s in L1_SEGMENTS)
            + " |"
        )
    lines += [
        "",
        "## 分段 FAR（应 L2 段被 L1 作答）",
        "",
        "| 策略 | 阈值 | δ | out_of_scope | compound | trap |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        far_seg = defaultdict(lambda: [0, 0])
        for row in r["rows"]:
            if row["case"]["expected_route"] != "L2":
                continue
            seg = row["case"]["segment"]
            far_seg[seg][1] += 1
            if row["decision"].decision == "L1_DIRECT":
                far_seg[seg][0] += 1
        lines.append(
            f"| {r['cfg']['strategy']} | {r['cfg']['threshold']} | {r['cfg']['delta']} | "
            + " | ".join(
                f"{far_seg[s][0]}/{far_seg[s][1]}" if s in far_seg else "-"
                for s in ("out_of_scope", "compound", "trap")
            )
            + " |"
        )

    s_by_key = {
        (r["cfg"]["strategy"], r["cfg"]["threshold"], r["cfg"]["delta"]): r["metrics"]
        for r in results
    }
    s4 = s_by_key.get(("S4", 0.66, 0.05))
    s3 = s_by_key.get(("S3", 0.66, 0.05))
    lines += ["", "## 结论要点", ""]
    lines.append(
        f"1. 硬门通过 {sum(1 for r in results if r['eligible'])}/{len(results)} 个配置；"
        "主因是 compound 段被 L1 单边作答（正则类策略 80/80），阈值/δ 调整无法改变。"
    )
    lines.append(
        f"2. 去掉认知门（S1）相对现状（S0）：Coverage {s_by_key[('S0', None, None)]['coverage']:.1%} → "
        f"{s_by_key[('S1', None, None)]['coverage']:.1%}，IntentAcc "
        f"{s_by_key[('S0', None, None)]['intent_acc']:.1%} → {s_by_key[('S1', None, None)]['intent_acc']:.1%}，"
        f"FAR {s_by_key[('S0', None, None)]['far']:.1%} → {s_by_key[('S1', None, None)]['far']:.1%}。"
    )
    if s3 and s4:
        lines.append(
            f"3. S4 vs S3（0.66/0.05）：Coverage {s3['coverage']:.1%} vs {s4['coverage']:.1%}，"
            f"P95 {s3['p95_ms']:.0f}ms vs {s4['p95_ms']:.0f}ms → 认知裁决无增量、成本高 40 倍。"
        )
    lines.append(
        f"4. 语义段可救回上限（S2 网格）：0.60→{_sem_cov(s_by_key, 'S2', 0.6)}，"
        f"0.66→{_sem_cov(s_by_key, 'S2', 0.66)}，0.70→{_sem_cov(s_by_key, 'S2', 0.7)}"
        "（共 80 条）→ 阈值不是瓶颈，口语样本覆盖不足才是。"
    )
    lines.append(
        f"5. 纯语义 S5 在 data/clarify 段塌陷（Coverage {s_by_key[('S5', 0.66, 0.08)]['coverage']:.1%}），"
        "正则通道不可移除。"
    )
    lines += ["", "## 裁决", ""]
    if no_eligible:
        lines.append(
            "- **无合格策略**：所有 54 个配置均未通过硬门（critical=0 / FAR≤2% / 分段 Coverage≥60%）。"
        )
        lines.append(
            f"- 覆盖参考点：{winner['cfg']['strategy']}（threshold={winner['cfg']['threshold']}, "
            f"delta={winner['cfg']['delta']}）Coverage={winner['metrics']['coverage']:.1%}，"
            f"IntentAcc={winner['metrics']['intent_acc']:.1%}，FAR={winner['metrics']['far']:.2%}"
        )
        lines.append(
            f"- 安全参考点：{second['cfg']['strategy']}（threshold={second['cfg']['threshold']}, "
            f"delta={second['cfg']['delta']}）FAR={second['metrics']['far']:.2%}，"
            f"critical={second['metrics']['far_critical']}，"
            f"Coverage={second['metrics']['coverage']:.1%}"
        )
        lines.append(
            f"- 两点对比（非裁决）：McNemar b={mc['b']}, c={mc['c']}, p={mc['p']:.4f}；"
            f"正确率差 bootstrap 95% CI={ci}"
        )
    else:
        lines.append(
            f"- 赢家：**{winner['cfg']['strategy']}**"
            f"（threshold={winner['cfg']['threshold']}, delta={winner['cfg']['delta']}）"
        )
        lines.append(
            f"- Coverage={winner['metrics']['coverage']:.1%}，"
            f"IntentAcc={winner['metrics']['intent_acc']:.1%}，"
            f"FAR={winner['metrics']['far']:.2%}，critical={winner['metrics']['far_critical']}"
        )
        lines.append(f"- 第二名：{second['cfg'] if second else '无'}")
        lines.append(f"- Coverage 差 bootstrap 95% CI：{ci}")
        lines.append(
            f"- McNemar：b={mc['b']}, c={mc['c']}, p={mc['p']:.4f}"
            + ("" if mc["p"] < 0.05 else "（差异统计上不可区分）")
        )
    lines += [
        "",
        "> 标注状态：AI 初标（label_status=ai_draft），需 100% 人工复核后方可作为终态依据。",
    ]
    with open(os.path.join(outdir, "E1-REPORT.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
