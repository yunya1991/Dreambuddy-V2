"""L2d 第一步：把"非弱证据"的 top-1 候选整理成盲评输入，交给 LLM 判断"这一行能否回答该问题"。"""

import importlib
import json
import sys

P = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/55-AI大模型研究报告/认知系统研究/experiments"
sys.path.insert(0, P)
R = importlib.import_module("l2_runner")
rmd = R.rmd

INV = {v: k for k, v in rmd.REL.items()}
rows, skipped = [], []
for q in R.build_questions():
    symbols = rmd.extract_symbols(q["question"])
    g = {"verdict": "NONE", "symbols": symbols, "assertion": "code_structure"}
    ev = rmd.decode({"text": q["question"], "question": q["question"]}, g).get("evidence", [])
    if not ev:
        skipped.append(q["id"])
        continue
    top1 = ev[0]
    weak = top1["score"] < 1.0 or (top1["score"] - (ev[1]["score"] if len(ev) > 1 else 0)) < 0.5
    if weak:
        skipped.append(q["id"])
        continue
    ls = open(INV[top1["file"]], encoding="utf-8", errors="ignore").read().splitlines()
    lo, hi = max(1, top1["line"] - 2), min(len(ls), top1["line"] + 2)
    snippet = "\n".join(f"{i}|{ls[i-1]}" for i in range(lo, hi + 1))
    rows.append(
        {
            "id": q["id"],
            "question": q["question"],
            "file": top1["file"],
            "line": top1["line"],
            "snippet": snippet,
        }
    )

with open(f"{P}/L2d-judge-input.jsonl", "w") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("待判", len(rows), "弱证据跳过", len(skipped))
