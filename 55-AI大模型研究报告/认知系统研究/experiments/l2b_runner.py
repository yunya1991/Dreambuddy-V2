"""L2b：加入"弱证据回退"后的结果。

规则（先验设定，不按测试集调参）：
  弱证据 = top1 得分 < 1.5  或  top1 与 top2 的差距 < 0.5
  弱证据时回退为"存内容"，读时直接命中；否则按 grep 复原。
同时给出阈值敏感性曲线，避免只用一组阈值下结论。
"""

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


def run(top_min, margin_min):
    rows = []
    for q in R.build_questions():
        truth_file = q["truth_evidence"][0].rsplit(":", 1)[0]
        symbols = rmd.extract_symbols(q["question"])
        g = {"verdict": "NONE", "symbols": symbols, "assertion": "code_structure"}
        dec = rmd.decode({"text": q["question"], "question": q["question"]}, g)
        ev = dec.get("evidence", [])
        top1 = ev[0]["score"] if ev else 0.0
        top2 = ev[1]["score"] if len(ev) > 1 else 0.0
        weak = (top1 < top_min) or (top1 - top2 < margin_min)
        files = [e["file"] for e in ev]
        ok = True if weak else (truth_file in files)
        rows.append(
            {
                "id": q["id"],
                "question": q["question"],
                "truth_file": truth_file,
                "files": files[:3],
                "top1": top1,
                "margin": round(top1 - top2, 3),
                "weak": weak,
                "ok": ok,
                "tokens": tok(q["truth"]) if weak else tok(" ".join(symbols)),
            }
        )
    return rows


base = run(1.5, 0.5)
n = len(base)
acc = sum(1 for r in base if r["ok"])
fb = sum(1 for r in base if r["weak"])
tks = sum(r["tokens"] for r in base) / n
print(f"L2b 正确 {acc}/{n} ({acc/n:.0%})  回退 {fb}/{n} ({fb/n:.0%})  平均存储 {tks:.1f} tokens")
print("回退项:", [r["id"] for r in base if r["weak"]])
print("仍失败:", [(r["id"], r["top1"], r["margin"], r["files"][:1]) for r in base if not r["ok"]])

# 敏感性曲线
print("\n阈值敏感性（top1_min, margin_min）→ 正确率 / 回退率 / 存储")
for t in (1.0, 1.5, 2.0):
    for m in (0.0, 0.5, 1.0):
        rows = run(t, m)
        a = sum(1 for r in rows if r["ok"]) / n
        f = sum(1 for r in rows if r["weak"]) / n
        s = sum(r["tokens"] for r in rows) / n
        print(f"  ({t},{m})  {a:.0%}  {f:.0%}  {s:.1f}")

with open(f"{P}/L2b-runs.jsonl", "w") as f:
    for r in base:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
