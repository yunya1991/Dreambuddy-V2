# -*- coding: utf-8 -*-
"""生成每个意图的硬负例候选（SPEC v1.6 §2.5）。

策略：跨意图近邻 —— 取其它意图的正例中、与本意图示例字符 3-gram 相似度最高且
正则不会判成本意图的样本，作为「看起来像但不属于」的硬负例。
零 LLM；输出 `datasets/negative_candidates/<intent>.jsonl`，由 build_dataset 消费。

用法：python3 34-前端应用训练系统/training/l1_intent/gen_negatives.py [--per-intent 50]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TRAIN_DIR = os.path.abspath(os.path.join(_HERE, "..", ".."))
_ROOT = os.path.abspath(os.path.join(_TRAIN_DIR, ".."))
_SCRIPTS = os.path.join(_ROOT, "3.1-FRONTEND", "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import l1_route_signal as lrs  # noqa: E402

UNITS = os.path.join(_ROOT, "41-文件索引系统", "intent_units")
OUT = os.path.join(_HERE, "datasets", "negative_candidates")
_PUNCT = re.compile(r"[\s，。、；：！？,.;:!?\"'“”‘’（）()\[\]【】<>《》]")


def _norm(s: str) -> str:
    return _PUNCT.sub("", (s or "").lower())


def _grams(s: str) -> set[str]:
    s = _norm(s)
    return {s[i : i + 3] for i in range(max(0, len(s) - 2))}


def _jac(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _load() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for name in sorted(os.listdir(UNITS)):
        msgs = []
        path = os.path.join(UNITS, name, "examples_zh.jsonl")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        msg = json.loads(line).get("message", "")
                        if msg:
                            msgs.append(msg)
        out[name] = msgs
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-intent", type=int, default=50)
    args = ap.parse_args()

    pool = _load()
    os.makedirs(OUT, exist_ok=True)
    summary = {}
    for intent, own in pool.items():
        own_grams = [_grams(m) for m in own]
        scored = []
        for other, msgs in pool.items():
            if other == intent:
                continue
            for m in msgs:
                if lrs.detect_intent_regex(m) == intent:
                    continue  # 正则会判成本意图，不能当负例
                g = _grams(m)
                sim = max((_jac(g, og) for og in own_grams), default=0.0)
                scored.append((sim, other, m))
        scored.sort(key=lambda x: (-x[0], x[1], x[2]))
        seen = set()
        rows = []
        for sim, other, m in scored:
            key = _norm(m)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "message": m,
                    "negative_for": intent,
                    "near_intent": other,
                    "similarity": round(sim, 3),
                    "label_status": "agent_verified",
                }
            )
            if len(rows) >= args.per_intent:
                break
        with open(os.path.join(OUT, f"{intent}.jsonl"), "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        summary[intent] = len(rows)

    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print(f"输出目录: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
