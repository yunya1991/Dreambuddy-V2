"""L2d 第二步：合并 LLM 校验结果，计算最终准确率/回退率/存储。"""

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


judged = {
    json.loads(line)["id"]: json.loads(line)
    for line in open(f"{P}/L2d-judge-output.jsonl")
    if line.strip()
}

rows = []
for q in R.build_questions():
    truth = q["truth_evidence"][0].rsplit(":", 1)[0]
    symbols = rmd.extract_symbols(q["question"])
    g = {"verdict": "NONE", "symbols": symbols, "assertion": "code_structure"}
    ev = rmd.decode({"text": q["question"], "question": q["question"]}, g).get("evidence", [])
    files = [e["file"] for e in ev]
    top1 = ev[0]["score"] if ev else 0
    margin = top1 - (ev[1]["score"] if len(ev) > 1 else 0)
    weak = (not ev) or top1 < 1.0 or margin < 0.5
    verdict = judged.get(q["id"], {}).get("verdict", "n/a")
    # 弱证据 → 回退；非弱但 LLM 判 no → 也回退
    fb = weak or verdict == "no"
    ok = True if fb else (truth in files)
    rows.append(
        {
            "id": q["id"],
            "weak": weak,
            "verdict": verdict,
            "fb": fb,
            "ok": ok,
            "truth_in": truth in files,
            "top1": top1,
            "tokens": tok(q["truth"]) if fb else tok(" ".join(symbols)),
        }
    )

n = len(rows)
acc = sum(r["ok"] for r in rows)
fb = sum(r["fb"] for r in rows)
tks = sum(r["tokens"] for r in rows) / n
print(f"L2d 正确 {acc}/{n} ({acc/n:.0%})  回退 {fb}/{n} ({fb/n:.0%})  平均存储 {tks:.1f} tokens")
wrong = [r["id"] for r in rows if not r["ok"]]
print("仍失败:", wrong)
# LLM 判 no 的项里，有多少本来是对的（误杀）
killed = [r["id"] for r in rows if r["verdict"] == "no" and r["truth_in"]]
print("LLM 误杀（本来正确却判 no）:", killed)
saved = [r["id"] for r in rows if r["verdict"] == "no" and not r["truth_in"]]
print("LLM 拦下（本来错误）:", saved)

with open(f"{P}/L2d-runs.jsonl", "w") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
