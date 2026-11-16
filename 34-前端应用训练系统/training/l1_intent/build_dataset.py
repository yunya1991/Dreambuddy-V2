# -*- coding: utf-8 -*-
"""L1 意图数据集构建（SPEC v1.6 §2 / P0）。

四源合并 → 归一化去重 → 近重复归并 → 分层切分 → 泄漏断言 → 配额报告。

用法：
  python3 34-前端应用训练系统/training/l1_intent/build_dataset.py
  python3 34-前端应用训练系统/training/l1_intent/build_dataset.py --strict
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
_TRAIN_DIR = os.path.abspath(os.path.join(_HERE, "..", ".."))
_ROOT = os.path.abspath(os.path.join(_TRAIN_DIR, ".."))
_UNITS = os.path.join(_ROOT, "41-文件索引系统", "intent_units")
_DEFAULT_OUT = os.path.join(_HERE, "datasets")
_NEAR_DUP = 0.85
_PUNCT = re.compile(r"[\s，。、；：！？,.;:!?\"'“”‘’（）()\[\]【】<>《》]")
_IN_DIST_SEGMENTS = {"data", "clarify", "regression"}
_OOD_SEGMENTS = {"semantic", "compound", "trap", "out_of_scope"}


def _norm(s: str) -> str:
    return _PUNCT.sub("", (s or "").lower())


def _grams(s: str) -> set[str]:
    s = _norm(s)
    return {s[i : i + 3] for i in range(max(0, len(s) - 2))}


def _near_dup(a: str, b: str) -> bool:
    if len(_norm(a)) < 6 or len(_norm(b)) < 6:
        return False
    ga, gb = _grams(a), _grams(b)
    if not ga or not gb:
        return False
    return len(ga & gb) / len(ga | gb) >= _NEAR_DUP


def _read_jsonl(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        out = []
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out


def _item(
    msg: str,
    *,
    source: str,
    segment: str,
    expected: str = "",
    route: str = "",
    status: str = "",
    notes: str = "",
) -> dict:
    return {
        "id": "l1-" + hashlib.sha1(f"{source}|{_norm(msg)}|{notes}".encode()).hexdigest()[:10],
        "message": msg,
        "expected_intent": expected,
        "expected_route": route,
        "segment": segment,
        "split": "",
        "source": source,
        "label_status": status,
        "labeled_by": source,
        "labeled_at": "2026-11-17",
        "notes": notes,
    }


def _split_for(item: dict) -> str:
    seg = item["segment"]
    if seg == "shadow":
        return "unlabeled"
    if seg in _IN_DIST_SEGMENTS or item["source"] == "unit":
        return "in_dist"
    # OOD 段：确定性哈希 60/40 → ood_spoken / holdout
    h = int(hashlib.sha1(_norm(item["message"]).encode()).hexdigest()[:8], 16) % 100
    return "ood_spoken" if h < 60 else "holdout"


def load_sources(sources: set[str]) -> tuple[list[dict], dict]:
    items: list[dict] = []
    stats: dict[str, int] = {}

    if "e1" in sources:
        path = os.path.join(_TRAIN_DIR, "eval", "e1_cases_reviewed.jsonl")
        if not os.path.exists(path):
            path = os.path.join(_TRAIN_DIR, "eval", "e1_cases.jsonl")
        rows = _read_jsonl(path)
        for r in rows:
            items.append(
                _item(
                    r["message"],
                    source="e1",
                    segment=r.get("segment", ""),
                    expected=r.get("expected_intent", ""),
                    route=r.get("expected_route", ""),
                    status=r.get("label_status", "ai_draft"),
                    notes=r.get("notes", ""),
                )
            )
        stats["e1"] = len(rows)

    if "units" in sources:
        n = 0
        for name in sorted(os.listdir(_UNITS)) if os.path.isdir(_UNITS) else []:
            for fn, seg, route in (
                ("examples_zh.jsonl", "data", "L1"),
                ("negatives_zh.jsonl", "trap", "L2"),
            ):
                for r in _read_jsonl(os.path.join(_UNITS, name, fn)):
                    msg = r.get("message", "")
                    if not msg:
                        continue
                    items.append(
                        _item(
                            msg,
                            source="unit",
                            segment=seg,
                            expected=name if seg == "data" else "",
                            route=route,
                            status="golden",
                            notes=(f"negative_for:{name}" if seg == "trap" else r.get("note", "")),
                        )
                    )
                    n += 1
        stats["units"] = n

    if "shadow" in sources:
        path = os.path.join(_ROOT, "logs", "l1_suggest_shadow.jsonl")
        n = 0
        for r in _read_jsonl(path):
            msg = r.get("message", "")
            if not msg:
                continue
            items.append(_item(msg, source="shadow", segment="shadow", status="unlabeled"))
            n += 1
        stats["shadow"] = n

    if "gen_neg" in sources:
        neg_dir = os.path.join(_HERE, "datasets", "negative_candidates")
        n = 0
        if os.path.isdir(neg_dir):
            for fn in sorted(os.listdir(neg_dir)):
                if not fn.endswith(".jsonl"):
                    continue
                for r in _read_jsonl(os.path.join(neg_dir, fn)):
                    msg = r.get("message", "")
                    if not msg:
                        continue
                    items.append(
                        _item(
                            msg,
                            source="gen_neg",
                            segment="trap",
                            route="L2",
                            status=r.get("label_status", "agent_verified"),
                            notes=f"negative_for:{r.get('negative_for', '')}",
                        )
                    )
                    n += 1
        stats["gen_neg"] = n

    return items, stats


def dedupe(items: list[dict]) -> tuple[list[dict], list[dict]]:
    """只丢弃完全重复；近重复保留，由 split 聚类强制同组（SPEC §2.4）。"""
    seen: dict[str, dict] = {}
    kept: list[dict] = []
    dropped: list[dict] = []
    for it in items:
        # 跨意图硬负例：同一条消息对不同意图可各存一行，按 (message, negative_for) 去重
        key = _norm(it["message"]) + (f"|{it['notes']}" if it["source"] == "gen_neg" else "")
        if key in seen:
            dropped.append(
                {"id": it["id"], "reason": f"exact_dup:{seen[key]['id']}", "message": it["message"]}
            )
            continue
        seen[key] = it
        kept.append(it)
    return kept, dropped


def assign_splits(items: list[dict]) -> int:
    """确定性切分：近重复聚成一簇，整簇同 split；返回簇数。"""
    parent = list(range(len(items)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if _near_dup(items[i]["message"], items[j]["message"]):
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[rj] = ri

    clusters: dict[int, list[int]] = {}
    for i in range(len(items)):
        clusters.setdefault(find(i), []).append(i)

    for members in clusters.values():
        # 簇内以最小哈希决定 split，保证同簇永不跨集
        key = min(_norm(items[i]["message"]) for i in members)
        if items[members[0]]["segment"] == "shadow":
            split = "unlabeled"
        elif (
            items[members[0]]["segment"] in _IN_DIST_SEGMENTS
            or items[members[0]]["source"] == "unit"
        ):
            split = "in_dist"
        else:
            h = int(hashlib.sha1(key.encode()).hexdigest()[:8], 16) % 100
            split = "ood_spoken" if h < 60 else "holdout"
        for i in members:
            items[i]["split"] = split
    return len(clusters)


def _split_for(item: dict) -> str:  # 保留供单测使用
    seg = item["segment"]
    if seg == "shadow":
        return "unlabeled"
    if seg in _IN_DIST_SEGMENTS or item["source"] == "unit":
        return "in_dist"
    h = int(hashlib.sha1(_norm(item["message"]).encode()).hexdigest()[:8], 16) % 100
    return "ood_spoken" if h < 60 else "holdout"


def leak_check(items: list[dict]) -> list[dict]:
    unit_msgs = [i["message"] for i in items if i["source"] == "unit"]
    bad = []
    for it in items:
        if it["split"] not in ("ood_spoken", "holdout"):
            continue
        for um in unit_msgs:
            if _near_dup(it["message"], um):
                bad.append(
                    {"id": it["id"], "split": it["split"], "message": it["message"], "unit": um}
                )
                break
    return bad


def quotas(items: list[dict]) -> dict:
    pos: dict[str, int] = {}
    neg_by_intent: dict[str, int] = {}
    ood = 0
    neg = 0
    for it in items:
        if it["split"] in ("ood_spoken", "holdout"):
            ood += 1
        if it["segment"] == "trap":
            neg += 1
            marker = it.get("notes") or ""
            if marker.startswith("negative_for:"):
                k = marker.split(":", 1)[1]
                neg_by_intent[k] = neg_by_intent.get(k, 0) + 1
        if it["expected_intent"]:
            pos[it["expected_intent"]] = pos.get(it["expected_intent"], 0) + 1
    return {
        "per_intent_positive": dict(sorted(pos.items())),
        "intents_below_20": sorted(k for k, v in pos.items() if v < 20),
        "ood_total": ood,
        "ood_min_required": 300,
        "negative_total": neg,
        "negative_min_required": 21 * 50,
        "negative_by_intent": dict(sorted(neg_by_intent.items())),
        "intents_below_50_negative": sorted(k for k, v in neg_by_intent.items() if v < 50),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=_DEFAULT_OUT)
    ap.add_argument("--sources", default="e1,units,shadow,gen_neg")
    ap.add_argument("--strict", action="store_true", help="泄漏或配额不达标时返回非零")
    args = ap.parse_args()

    items, stats = load_sources({s.strip() for s in args.sources.split(",") if s.strip()})
    kept, dropped = dedupe(items)
    clusters = assign_splits(kept)

    leaks = leak_check(kept)
    q = quotas(kept)

    os.makedirs(args.out, exist_ok=True)

    def dump(name: str, rows: list[dict]) -> None:
        with open(os.path.join(args.out, name), "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    dump("all.jsonl", kept)
    for split in ("in_dist", "ood_spoken", "holdout", "unlabeled"):
        dump(f"{split}.jsonl", [i for i in kept if i["split"] == split])

    manifest = {
        "sources": stats,
        "raw_total": len(items),
        "kept": len(kept),
        "dropped_duplicates": len(dropped),
        "split_counts": {
            s: sum(1 for i in kept if i["split"] == s)
            for s in ("in_dist", "ood_spoken", "holdout", "unlabeled")
        },
        "leaks": leaks,
        "quotas": q,
        "near_dup_clusters": clusters,
        "near_dup_threshold": _NEAR_DUP,
    }
    with open(os.path.join(args.out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    lines = [
        "# L1 意图数据集构建报告",
        "",
        f"- 原始：{len(items)}  保留：{len(kept)}  去重丢弃：{len(dropped)}",
        f"- 切分：{manifest['split_counts']}",
        f"- 泄漏：{len(leaks)} 条",
        f"- OOD 合计：{q['ood_total']}（要求 ≥{q['ood_min_required']}）",
        f"- 负例合计：{q['negative_total']}（要求 ≥{q['negative_min_required']}）",
        f"- 正例不足 20 的意图：{q['intents_below_20'] or '无'}",
        "",
        "## 泄漏明细（最多 20 条）",
        "",
    ]
    for x in leaks[:20]:
        lines.append(f"- `{x['id']}` [{x['split']}] {x['message']} ↔ {x['unit']}")
    with open(os.path.join(args.out, "REPORT.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))

    if args.strict and (leaks or q["intents_below_20"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
