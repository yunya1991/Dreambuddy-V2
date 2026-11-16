# -*- coding: utf-8 -*-
"""E2 实验：复合问法检测 + L1 模型建议器（SPEC-v1.4 §7.2 草案）。

两个子实验，共用 E1 的 500 条数据集与语义特征缓存：
  E2-A 复合检测：4 个检测器（规则多命中 / 语义双峰 / 连接词多实体 / 组合），
       指标：compound 段召回 vs 单意图段误杀；再把最佳检测器作为前置闸接到 S1，
       看整体 FAR / Coverage 是否达到硬门。
  E2-B 建议器：语义 top3 → 相关意图 + 示例问法，指标：top1/top3 命中、空候选率、
       延迟、"延伸推荐"（排除主意图后 top2–3 命中）。

只读缓存、不联网、不改生产行为。

用法：python3 34-前端应用训练系统/scripts/eval_compound_suggest.py
"""

from __future__ import annotations

import json
import os
import re
import statistics
import sys
from collections import defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
_TRAIN_DIR = os.path.join(_ROOT, "34-前端应用训练系统")
_SCRIPTS_DIR = os.path.join(_ROOT, "3.1-FRONTEND", "scripts")
for _p in (_TRAIN_DIR, _SCRIPTS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import l1_route_signal as lrs  # noqa: E402

CASES = os.path.join(_TRAIN_DIR, "eval", "e1_cases.jsonl")
FEATURES = os.path.join(_TRAIN_DIR, "eval", "cache", "features.jsonl")
HITS_CACHE = os.path.join(_TRAIN_DIR, "eval", "cache", "regex_hits.jsonl")
OUT_DIR = os.path.join(_TRAIN_DIR, "eval-results", "20261116")
UNITS = os.path.join(_ROOT, "41-文件索引系统", "intent_units")

CONNECTIVE = re.compile(r"[与和及、]|同时|还有|以及|一起|顺便|另外|再")
COMPARE = re.compile(r"对比|比较|谁更|谁强|哪个强|差距|vs|VS")
ANCHOR = re.compile(
    r"BTC|ETH|SOL|比特币|以太坊|索拉纳|二饼|大饼|姨太|黄金|原油|美股|港股|A股|纳指|标普"
    r"|CPI|PPI|GDP|非农|失业率|通胀|恐惧贪婪|恐慌贪婪|资金费率|多空比|稳定币|ETF|美元|国债|M2|M1"
)


def _read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_hits(cases):
    if os.path.exists(HITS_CACHE):
        return {r["message"]: r["hits"] for r in _read_jsonl(HITS_CACHE)}
    hits = {c["message"]: lrs.regex_intent_hits(c["message"]) for c in cases}
    with open(HITS_CACHE, "w", encoding="utf-8") as f:
        for msg, h in hits.items():
            f.write(json.dumps({"message": msg, "hits": h}, ensure_ascii=False) + "\n")
    return hits


def detect_d0(hits, msg):
    strong = [h for h in hits if h not in ("data_query",)]
    return len(set(strong)) >= 2


def detect_d1(sem_top, theta):
    if len(sem_top) < 2:
        return False
    (i1, s1), (i2, s2) = sem_top[0], sem_top[1]
    return i1 != i2 and s2 >= theta and s1 < 0.999


def detect_d2(hits, msg):
    if not CONNECTIVE.search(msg) or COMPARE.search(msg):
        return False
    return len(set(ANCHOR.findall(msg))) >= 2


def detect_d3(hits, msg, sem_top, theta):
    return detect_d0(hits, msg) or detect_d1(sem_top, theta) or detect_d2(hits, msg)


SPLIT = re.compile(r"[，,；;、]|以及|还有|同时|顺便|另外|并且|然后|和|与|及")


def detect_d4(msg):
    """子句切分 + 逐子句意图：≥2 个不同意图即复合（纯规则，零模型）。

    子句长度 <4 视为碎片（如单独的 "BTC"），不计入——避免把
    「BTC和ETH涨跌幅对比」这类单意图对比句误判为复合。
    """
    parts = [p.strip() for p in SPLIT.split(msg) if len(p.strip()) >= 4]
    if len(parts) < 2:
        return False
    intents = {lrs.detect_intent_regex(p) for p in parts}
    intents.discard("")
    return len(intents) >= 2


def detect_d5(msg, hits):
    """D5 = D4（子句异构意图）∪ D2（连接词+多实体）∪ 多指标并列（≥2 个注册表指标）。"""
    if detect_d4(msg) or detect_d2(hits, msg):
        return True
    try:
        return lrs.count_series_hits(msg) >= 2
    except Exception:  # noqa: BLE001 — FAIL-OPEN
        return False


def eval_detector(name, fn, cases, feats, hits):
    tp = fp = fn_ = tn = 0
    flagged_single = []
    for c in cases:
        f = feats[c["message"]]
        sem = [(i, s) for i, s in f["semantic_top"]]
        pred = fn(hits[c["message"]], c["message"], sem)
        if c["segment"] == "compound":
            tp += pred
            fn_ += not pred
        elif c["expected_route"] == "L1":
            fp += pred
            tn += not pred
            if pred:
                flagged_single.append(c["message"])
        else:
            # 其他应 L2 段（out_of_scope / trap）不参与复合误杀统计
            continue
    recall = tp / max(1, tp + fn_)
    fpr = fp / max(1, fp + tn)
    return {
        "name": name,
        "recall": recall,
        "fpr": fpr,
        "tp": tp,
        "fn": fn_,
        "fp": fp,
        "tn": tn,
        "flagged_single": flagged_single[:8],
    }


def apply_gate_s1(cases, feats, hits, gate):
    """S1 + 复合闸：命中复合 → L2；否则按 S1（正则命中且有执行器 → L1）。"""
    l1_ok = l1_total = 0
    far = l2_total = 0
    for c in cases:
        sem = [(i, s) for i, s in feats[c["message"]]["semantic_top"]]
        is_compound = gate(hits[c["message"]], c["message"], sem)
        regex_intent = feats[c["message"]]["regex_intent"]
        answered = (not is_compound) and bool(regex_intent) and regex_intent in lrs.EXECUTORS
        if c["expected_route"] == "L1":
            l1_total += 1
            if answered and (c["expected_intent"] is None or regex_intent == c["expected_intent"]):
                l1_ok += 1
        else:
            l2_total += 1
            if answered:
                far += 1
    return {"coverage": l1_ok / max(1, l1_total), "far": far / max(1, l2_total)}


def examples_map(case_messages):
    """每个意图取一条示例问法（排除测试集消息）。"""
    out = {}
    for name in os.listdir(UNITS):
        p = os.path.join(UNITS, name, "examples_zh.jsonl")
        if not os.path.exists(p):
            continue
        for r in _read_jsonl(p):
            msg = r.get("message", "")
            if msg and msg not in case_messages:
                out.setdefault(name, msg)
                break
    return out


def main():
    cases = _read_jsonl(CASES)
    feats = {r["message"]: r for r in _read_jsonl(FEATURES)}
    hits = load_hits(cases)

    # ---------- E2-A 复合检测 ----------
    theta_grid = (0.45, 0.50, 0.55, 0.60, 0.66)
    results = []
    results.append(
        eval_detector("D0 规则多命中", lambda h, m, s: detect_d0(h, m), cases, feats, hits)
    )
    results.append(
        eval_detector("D2 连接词+多实体", lambda h, m, s: detect_d2(h, m), cases, feats, hits)
    )
    results.append(
        eval_detector("D4 子句切分+意图", lambda h, m, s: detect_d4(m), cases, feats, hits)
    )
    results.append(
        eval_detector("D5 组合规则", lambda h, m, s: detect_d5(m, h), cases, feats, hits)
    )
    for th in theta_grid:
        results.append(
            eval_detector(
                f"D1 语义双峰 θ={th}", lambda h, m, s, t=th: detect_d1(s, t), cases, feats, hits
            )
        )
    for th in theta_grid:
        results.append(
            eval_detector(
                f"D3 组合 θ={th}", lambda h, m, s, t=th: detect_d3(h, m, s, t), cases, feats, hits
            )
        )

    print("== E2-A 复合检测 ==")
    for r in results:
        print(
            f"{r['name']:18} recall={r['recall']:.1%} FPR={r['fpr']:.1%} "
            f"(tp={r['tp']} fn={r['fn']} fp={r['fp']} tn={r['tn']})"
        )

    best = max(results, key=lambda r: (r["recall"] - 2 * r["fpr"], -r["fpr"]))
    best_name = best["name"]
    th = float(best_name.split("=")[1]) if "=" in best_name else 0.0

    def gate(h, m, s, name=best_name, t=th):
        if name.startswith("D0"):
            return detect_d0(h, m)
        if name.startswith("D5"):
            return detect_d5(m, h)
        if name.startswith("D4"):
            return detect_d4(m)
        if name.startswith("D2"):
            return detect_d2(h, m)
        if name.startswith("D1"):
            return detect_d1(s, t)
        return detect_d3(h, m, s, t)

    s1_raw = apply_gate_s1(cases, feats, hits, lambda h, m, s: False)
    s1_best = apply_gate_s1(cases, feats, hits, gate)
    print(f"\n最佳检测器：{best['name']}")
    print(f"S1 无闸   Coverage={s1_raw['coverage']:.1%} FAR={s1_raw['far']:.1%}")
    print(f"S1+复合闸 Coverage={s1_best['coverage']:.1%} FAR={s1_best['far']:.1%}")

    # ---------- E2-B 建议器 ----------
    seg = defaultdict(lambda: {"n": 0, "empty": 0, "top1": 0, "top3": 0, "ext": 0})
    lat = []
    for c in cases:
        if not c["expected_intent"]:
            continue
        f = feats[c["message"]]
        top = [(i, s) for i, s in f["semantic_top"]]
        lat.append(f["semantic_ms"])
        g = seg[c["segment"]]
        g["n"] += 1
        if not top:
            g["empty"] += 1
            continue
        if top[0][0] == c["expected_intent"]:
            g["top1"] += 1
        if c["expected_intent"] in [i for i, _ in top]:
            g["top3"] += 1
        if c["expected_intent"] in [i for i, _ in top[1:]]:
            g["ext"] += 1

    print("\n== E2-B 建议器 ==")
    print(f"{'分段':12} {'n':>4} {'空候选':>6} {'top1':>7} {'top3':>7} {'延伸(top2-3)':>12}")
    tot = defaultdict(int)
    for s, v in sorted(seg.items()):
        print(
            f"{s:12} {v['n']:4} {v['empty']:6} {v['top1']/v['n']:6.1%} "
            f"{v['top3']/v['n']:6.1%} {v['ext']/v['n']:11.1%}"
        )
        for k in ("n", "empty", "top1", "top3", "ext"):
            tot[k] += v[k]
    print(
        f"{'合计':10} {tot['n']:4} {tot['empty']:6} {tot['top1']/tot['n']:6.1%} "
        f"{tot['top3']/tot['n']:6.1%} {tot['ext']/tot['n']:11.1%}"
    )
    lat_sorted = sorted(lat)
    p50 = statistics.median(lat_sorted) if lat_sorted else 0
    p95 = lat_sorted[max(0, int(0.95 * len(lat_sorted)) - 1)] if lat_sorted else 0
    print(f"语义耗时 P50={p50:.1f}ms P95={p95:.1f}ms")

    # ---------- 报告 ----------
    lines = [
        "# E2 实验报告：复合问法检测 + L1 模型建议器",
        "",
        "> 数据集与 E1 相同（e1_cases.jsonl 500 条，AI 初标）；只读缓存，不改生产行为。",
        "",
        "## E2-A 复合检测器（compound 80 条 vs 单意图 240 条）",
        "",
        "| 检测器 | 召回 | 误杀(FPR) | tp | fn | fp | tn |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r['name']} | {r['recall']:.1%} | {r['fpr']:.1%} | {r['tp']} | "
            f"{r['fn']} | {r['fp']} | {r['tn']} |"
        )
    lines += [
        "",
        f"- 最佳检测器：**{best['name']}**（recall {best['recall']:.1%} / FPR {best['fpr']:.1%}）",
        f"- S1 无闸：Coverage {s1_raw['coverage']:.1%} / FAR {s1_raw['far']:.1%}",
        f"- S1 + 复合闸：Coverage {s1_best['coverage']:.1%} / FAR {s1_best['far']:.1%}",
        "",
        "## E2-B 建议器（语义 top3 → 意图 + 示例问法）",
        "",
        "| 分段 | n | 空候选 | top1 | top3 | 延伸(top2–3) |",
        "|---|---|---|---|---|---|",
    ]
    for s, v in sorted(seg.items()):
        lines.append(
            f"| {s} | {v['n']} | {v['empty']} | {v['top1']/v['n']:.1%} | "
            f"{v['top3']/v['n']:.1%} | {v['ext']/v['n']:.1%} |"
        )
    lines += [
        f"| 合计 | {tot['n']} | {tot['empty']} | {tot['top1']/tot['n']:.1%} | "
        f"{tot['top3']/tot['n']:.1%} | {tot['ext']/tot['n']:.1%} |",
        "",
        f"- 语义耗时 P50={p50:.1f}ms / P95={p95:.1f}ms（含 requiredPattern 校验）",
        "",
        "> 标注状态：AI 初标，需人工复核。",
    ]
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "E2-REPORT.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\n报告: {os.path.join(OUT_DIR, 'E2-REPORT.md')}")

    with open(os.path.join(OUT_DIR, "e2_summary.json"), "w", encoding="utf-8") as f:
        json.dump(
            {
                "detectors": [
                    {k: v for k, v in r.items() if k != "flagged_single"} for r in results
                ],
                "best": best["name"],
                "s1_raw": s1_raw,
                "s1_with_gate": s1_best,
                "suggest": {
                    "segments": {k: dict(v) for k, v in seg.items()},
                    "total": dict(tot),
                    "p50_ms": p50,
                    "p95_ms": p95,
                },
            },
            f,
            ensure_ascii=False,
            indent=2,
        )


if __name__ == "__main__":
    main()
