"""L3：任务级端到端对照（30 任务 × 3 条件 × 3 种子）。

说明：本地无 LLM 端点，本实验是**任务级模拟**——任务被定义为"需要 2 条事实才能完成"，
成功 = 两条事实的文件都答对。它衡量的是记忆形态对任务完成率与成本的影响，
不等价于真实智能体闭环（那需要 LLM 在环，见报告 §5）。

条件：
  content   写入时把事实原文全部存下
  pointer   只存指针，读时用 grep 重建
  rmd       门槛 + 弱证据回退（L2b 口径）
数据复用 L2-runs.jsonl（grep）与 L2b-runs.jsonl（rmd），保证与 L2 同口径。
"""

import importlib
import json
import random
import statistics
import sys

P = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/55-AI大模型研究报告/认知系统研究/experiments"
sys.path.insert(0, P)
R = importlib.import_module("l2_runner")

try:
    import tiktoken

    enc = tiktoken.get_encoding("cl100k_base")

    def tok(s):
        return len(enc.encode(s))

except Exception:  # noqa: BLE001

    def tok(s):
        return int(len(s) / 1.6)


qs = {q["id"]: q for q in R.build_questions()}
grep = {
    json.loads(line)["id"]: json.loads(line) for line in open(f"{P}/L2-runs.jsonl") if line.strip()
}
rmd = {
    json.loads(line)["id"]: json.loads(line) for line in open(f"{P}/L2b-runs.jsonl") if line.strip()
}
d = {
    json.loads(line)["id"]: json.loads(line) for line in open(f"{P}/L2d-runs.jsonl") if line.strip()
}

ids = sorted(qs)
for i in ids:
    qs[i]["content_tokens"] = tok(qs[i]["truth"])

seeds = [11, 22, 33]
summary = {
    c: {"succ": [], "tokens": [], "ms": []} for c in ("content", "pointer", "rmd", "rmd_llm")
}

for seed in seeds:
    order = ids[:]
    random.Random(seed).shuffle(order)
    tasks = [order[i : i + 2] for i in range(0, 60, 2)]  # 30 个任务，每个 2 条事实
    for t in tasks:
        for cond in ("content", "pointer", "rmd", "rmd_llm"):
            if cond == "content":
                ok = True
                tk = sum(qs[i]["content_tokens"] for i in t)
                ms = 0
            elif cond == "pointer":
                ok = all(grep[i]["pointer_grep"]["ok"] for i in t)
                tk = sum(grep[i]["pointer_grep"]["tokens"] for i in t)
                ms = sum(grep[i]["pointer_grep"]["ms"] for i in t)
            elif cond == "rmd":
                ok = all(rmd[i]["ok"] for i in t)
                tk = sum(rmd[i]["tokens"] for i in t)
                ms = sum(grep[i]["pointer_grep"]["ms"] for i in t)
            else:
                ok = all(d[i]["ok"] for i in t)
                tk = sum(d[i]["tokens"] for i in t)
                ms = sum(grep[i]["pointer_grep"]["ms"] for i in t)
            summary[cond]["succ"].append(1 if ok else 0)
            summary[cond]["tokens"].append(tk)
            summary[cond]["ms"].append(ms)

print(f"{'条件':10s} {'任务成功率':>10s} {'平均存储/任务':>14s} {'平均读时延':>12s}")
rows = []
for cond, s in summary.items():
    acc = sum(s["succ"]) / len(s["succ"])
    tk = statistics.mean(s["tokens"])
    ms = statistics.mean(s["ms"])
    print(f"{cond:10s} {acc:9.0%} {tk:13.1f} {ms:10.0f} ms")
    rows.append(
        {
            "condition": cond,
            "tasks": len(s["succ"]),
            "success_rate": round(acc, 4),
            "tokens_per_task": round(tk, 1),
            "ms_per_task": round(ms, 1),
        }
    )

with open(f"{P}/L3-summary.json", "w") as f:
    json.dump({"seeds": seeds, "rows": rows}, f, ensure_ascii=False, indent=2)
