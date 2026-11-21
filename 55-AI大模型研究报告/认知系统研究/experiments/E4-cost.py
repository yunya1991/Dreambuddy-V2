"""E4：写入判定路径的单条成本实测（规则 / 探针 / LLM 输入 token）。"""

import importlib
import json
import statistics
import sys
import time

P = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/55-AI大模型研究报告/认知系统研究/experiments"
sys.path.insert(0, P)

t0 = time.time()
rmd = importlib.import_module("rmd_mvp")
boot_ms = (time.time() - t0) * 1000

rows = []
for fn in ("L1-300.jsonl", "A-60.jsonl", "H-70.jsonl", "M-15.jsonl"):
    rows += [json.loads(line) for line in open(f"{P}/{fn}") if line.strip()]

# 规则路径：分类 + 门槛（不含探针）
rule_ms, probe_ms, total = [], [], []
for r in rows:
    s = time.perf_counter()
    g = rmd.gate(r)
    total.append((time.perf_counter() - s) * 1000)

# 探针路径：只对 code_fact 候选计时
for r in rows:
    g = rmd.gate(r)
    if g.get("assertion") == "code_structure":
        s = time.perf_counter()
        rmd.decode(r, g)
        probe_ms.append((time.perf_counter() - s) * 1000)

RULE = """你是记忆写入判定器。把候选文本归入以下四类之一：
code_fact：断言源代码本身的属性（定义位置、导入、赋值、读取、依赖、继承、入参、所属模块），可由读代码回答。
runtime_state：断言运行/部署环境状态（实例、端口、版本、主机、目录、副本、配额、到期、灰度），仓库里没有答案。
decision：断言人的决定/约定/偏好/否决/教训（谁审批、谁负责、被禁止或放弃什么、按什么周期、保留多久、走什么流程）。
sensitive：涉及凭证或凭证位置（密码、密钥、token、私钥、口令、secret、API key）。
只输出 JSON：{"label":"...","confidence":0.0-1.0}。
候选："""

try:
    import tiktoken

    enc = tiktoken.get_encoding("cl100k_base")

    def tok(s):
        return len(enc.encode(s))

except Exception:  # noqa: BLE001

    def tok(s):
        return int(len(s) / 1.6)


prompt_tokens = [tok(RULE + r["text"]) for r in rows]


def pct(xs, q):
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(len(xs) * q))], 2)


out = {
    "items": len(rows),
    "boot_ms_once": round(boot_ms, 1),
    "rule_ms": {"p50": pct(total, 0.5), "p95": pct(total, 0.95), "max": round(max(total), 2)},
    "probe_ms": {
        "n": len(probe_ms),
        "p50": pct(probe_ms, 0.5),
        "p95": pct(probe_ms, 0.95),
        "max": round(max(probe_ms), 2),
    },
    "llm_prompt_tokens": {
        "p50": int(statistics.median(prompt_tokens)),
        "p95": pct(prompt_tokens, 0.95),
        "max": max(prompt_tokens),
        "total": sum(prompt_tokens),
    },
}
with open(f"{P}/E4-cost.json", "w") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print(json.dumps(out, ensure_ascii=False, indent=2))
