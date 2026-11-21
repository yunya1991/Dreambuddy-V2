"""L3b：读频敏感性——同一事实被读 N 次时，各形态的"单位成功任务成本"。

成本口径（token）：
  写入 = 存储一次（content 23 / pointer 3 / rmd 11.8 / rmd_llm 15.2，均取 L2 实测均值）
  读取 = 指针 3 + 注入片段 s（content 直接注入自身 23；指针/重建注入 grep 命中片段）
  rmd_llm 额外 = 350 × 0.632（E4 实测 LLM 校验成本 × 非弱证据比例）
成功率取 L3 任务级实测：content 1.00 / pointer 0.66 / rmd 0.93 / rmd_llm 1.00
"""

import json

P = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/55-AI大模型研究报告/认知系统研究/experiments"

WRITE = {"content": 23.0, "pointer": 3.0, "rmd": 11.8, "rmd_llm": 15.2}
SUCC = {"content": 1.00, "pointer": 0.66, "rmd": 0.93, "rmd_llm": 1.00}
LLM = 350 * 0.632


def read_cost(cond, s):
    if cond == "content":
        return 23.0
    if cond == "pointer":
        return 3.0 + s
    if cond == "rmd":
        return 3.0 + s
    return 3.0 + s + LLM


def cost(cond, n, s):
    return (WRITE[cond] + n * read_cost(cond, s)) / SUCC[cond]


rows = []
for s in (15, 25, 40):
    for n in (1, 5, 20, 100):
        vals = {c: cost(c, n, s) for c in WRITE}
        best = min(vals, key=vals.get)
        rows.append(
            {
                "snippet_tokens": s,
                "reads": n,
                **{k: round(v, 1) for k, v in vals.items()},
                "best": best,
            }
        )

print(f"{'片段':>4} {'读次数':>5} | " + " | ".join(f"{c:>11}" for c in WRITE) + " | 最优")
for r in rows:
    print(
        f"{r['snippet_tokens']:>4} {r['reads']:>5} | "
        + " | ".join(f"{r[c]:>11.1f}" for c in WRITE)
        + f" | {r['best']}"
    )

# 盈亏平衡：content 与 rmd 相等时的读次数
print("\n盈亏平衡（content vs rmd）：")
for s in (10, 15, 20, 25, 30, 40):
    wc, wr = WRITE["content"], WRITE["rmd"]
    rc, rr = read_cost("content", s), read_cost("rmd", s)
    num, den = wr - SUCC["rmd"] * wc, SUCC["rmd"] * rc - rr
    if den == 0:
        print(f"  片段 {s:>2} tok → 两者斜率相同，看写入成本")
        continue
    n = num / den
    if n <= 0:
        print(f"  片段 {s:>2} tok → rmd 在所有读次数下都更省")
    elif n < 1:
        print(f"  片段 {s:>2} tok → content 在所有读次数下都更省")
    else:
        print(f"  片段 {s:>2} tok → N* = {n:.1f}（读 ≤{int(n)} 次 rmd 更省，超过则 content 更省）")

with open(f"{P}/L3b-read-frequency.json", "w") as f:
    json.dump(rows, f, ensure_ascii=False, indent=2)
