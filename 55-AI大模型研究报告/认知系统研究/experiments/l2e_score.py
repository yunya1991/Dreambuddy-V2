"""L2e 计分：LLM 从 top-3 中挑选；none 或弱证据则回退存内容。"""

import importlib
import json
import sys

P = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/55-AI大模型研究报告/认知系统研究/experiments"
sys.path.insert(0, P)
R = importlib.import_module("l2_runner")
rmd = R.rmd

try:
    import tiktoken

    enc = tiktoken.get_encoding("cl100k_base")

    def tok(s):
        return len(enc.encode(s))

except Exception:  # noqa: BLE001

    def tok(s):
        return int(len(s) / 1.6)


picks = {
    json.loads(line)["id"]: json.loads(line)
    for line in open(f"{P}/L2e-judge-output.jsonl")
    if line.strip()
}

rows = []
for q in R.build_questions():
    truth = q["truth_evidence"][0].rsplit(":", 1)[0]
    symbols = rmd.extract_symbols(q["question"])
    g = {"verdict": "NONE", "symbols": symbols, "assertion": "code_structure"}
    ev = rmd.decode({"text": q["question"], "question": q["question"]}, g).get("evidence", [])
    files = [e["file"] for e in ev[:3]]
    top1 = ev[0]["score"] if ev else 0
    margin = top1 - (ev[1]["score"] if len(ev) > 1 else 0)
    weak = (not ev) or top1 < 1.0 or margin < 0.5
    pick = picks.get(q["id"], {}).get("pick")
    fb = weak or pick in (None, "none")
    chosen = None if fb else files[int(pick) - 1]
    ok = True if fb else (chosen == truth)
    rows.append(
        {
            "id": q["id"],
            "weak": weak,
            "pick": pick,
            "chosen": chosen,
            "truth": truth,
            "ok": ok,
            "top3_hit": truth in files,
            "fb": fb,
            "tokens": tok(q["truth"]) if fb else tok(" ".join(symbols)),
        }
    )

n = len(rows)
acc = sum(r["ok"] for r in rows)
fb = sum(r["fb"] for r in rows)
tks = sum(r["tokens"] for r in rows) / n
print(f"L2e 正确 {acc}/{n} ({acc/n:.0%})  回退 {fb}/{n} ({fb/n:.0%})  平均存储 {tks:.1f} tokens")
print("选错:", [(r["id"], r["chosen"], r["truth"]) for r in rows if not r["ok"]])
print("none 但 top3 本来正确:", [r["id"] for r in rows if r["pick"] == "none" and r["top3_hit"]])
print("top-3 命中率:", sum(r["top3_hit"] for r in rows), "/", n)

with open(f"{P}/L2e-runs.jsonl", "w") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
