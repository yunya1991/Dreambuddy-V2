"""L2e 准备：把非弱证据的 top-3 候选一起交给 LLM，让它选一个或都不选。"""

import importlib
import json
import sys

P = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/55-AI大模型研究报告/认知系统研究/experiments"
sys.path.insert(0, P)
R = importlib.import_module("l2_runner")
rmd = R.rmd
INV = {v: k for k, v in rmd.REL.items()}

rows = []
for q in R.build_questions():
    symbols = rmd.extract_symbols(q["question"])
    g = {"verdict": "NONE", "symbols": symbols, "assertion": "code_structure"}
    ev = rmd.decode({"text": q["question"], "question": q["question"]}, g).get("evidence", [])
    if not ev:
        continue
    top1 = ev[0]["score"]
    margin = top1 - (ev[1]["score"] if len(ev) > 1 else 0)
    if top1 < 1.0 or margin < 0.5:
        continue
    cands = []
    for e in ev[:3]:
        ls = open(INV[e["file"]], encoding="utf-8", errors="ignore").read().splitlines()
        lo, hi = max(1, e["line"] - 1), min(len(ls), e["line"] + 1)
        cands.append(
            {
                "file": e["file"],
                "line": e["line"],
                "snippet": "\n".join(f"{i}|{ls[i-1]}" for i in range(lo, hi + 1)),
            }
        )
    rows.append({"id": q["id"], "question": q["question"], "candidates": cands})

with open(f"{P}/L2e-judge-input.jsonl", "w") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("待选", len(rows))
