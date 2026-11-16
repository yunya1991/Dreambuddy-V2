# -*- coding: utf-8 -*-
"""构建意图的多样例向量索引（SPEC v1.6 §3.6 / P0.5）。

背景：原 `vector.json` 每意图仅 1 个质心向量，口语变体被平均掉
（OOD top1 33.3% vs 多样例 kNN 63.3%）。本脚本把每个意图的
`examples_zh.jsonl` 全部编码为多样例向量，供 IntentVectorStore 取最大相似度。

用法：python3 41-文件索引系统/scripts/build_intent_example_vectors.py
"""

from __future__ import annotations

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT41 = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT41 not in sys.path:
    sys.path.insert(0, _ROOT41)

from core.embedder_bridge import embed_batch  # noqa: E402

UNITS = os.path.join(_ROOT41, "intent_units")
_DATASET = os.path.join(
    _ROOT41, "..", "34-前端应用训练系统", "training", "l1_intent", "datasets", "in_dist.jsonl"
)


def _load_dataset_positives() -> dict[str, list[str]]:
    """合并训练侧 in_dist 正例（agent_verified/golden），扩充每意图样例覆盖。"""
    out: dict[str, list[str]] = {}
    path = os.path.abspath(_DATASET)
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            intent = r.get("expected_intent") or ""
            status = r.get("label_status") or ""
            if intent and status != "ai_draft" and r.get("message"):
                out.setdefault(intent, []).append(r["message"])
    return out


def main() -> int:
    extra = _load_dataset_positives()
    summary = {}
    for name in sorted(os.listdir(UNITS)):
        d = os.path.join(UNITS, name)
        path = os.path.join(d, "examples_zh.jsonl")
        if not os.path.isdir(d) or not os.path.exists(path):
            continue
        msgs, seen = [], set()
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    m = json.loads(line).get("message", "")
                    if m and m not in seen:
                        seen.add(m)
                        msgs.append(m)
        for m in extra.get(name, []):
            if m not in seen:
                seen.add(m)
                msgs.append(m)
        if not msgs:
            continue
        vecs = embed_batch(msgs, lang="zh")
        out = os.path.join(d, "example_vectors.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump(
                {"zh": vecs, "messages": msgs, "model": "bge-base-zh-768"}, f, ensure_ascii=False
            )
        summary[name] = len(vecs)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print(f"合计 {sum(summary.values())} 条样例向量")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
