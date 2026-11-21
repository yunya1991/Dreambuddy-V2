"""L2：四种记忆条件的解码对照（20 题 E1 + 40 题由 L1 派生）。

条件：
  content       直接把真值文本当记忆（最强内容基线）
  pointer_rea   只存符号指针，读时调用 REA trace 复原
  pointer_grep  只存符号指针，读时 grep 排序复原
  rmd           走门槛；code_fact 判 NONE 后按 pointer_grep 复原
正确性：真值文件是否出现在该条件给出的前 3 个证据文件里。
成本：注入 token、时延、REA 输出字节。
"""

import importlib
import json
import re
import sys
import time

P = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/55-AI大模型研究报告/认知系统研究/experiments"
sys.path.insert(0, P)
sys.path.insert(0, "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/33-REA逆向解析工程")
rmd = importlib.import_module("rmd_mvp")

try:
    import tiktoken

    enc = tiktoken.get_encoding("cl100k_base")

    def tok(s):
        return len(enc.encode(s))

except Exception:  # noqa: BLE001

    def tok(s):
        return int(len(s) / 1.6)


STRIP = [
    (r"符号 `([^`]+)` 定义在 `[^`]+` 模块中。", "符号 `{0}` 定义在哪个模块？"),
    (r"属性 `([^`]+)` 在 `[^`]+` 中被赋值。", "属性 `{0}` 在哪个模块被赋值？"),
    (r"`([^`]+)` 被 `[^`]+` 导入。", "`{0}` 由哪个模块导入？"),
    (r"环境变量 `([^`]+)` 在 `[^`]+` 中被读取。", "环境变量 `{0}` 在哪个模块被读取？"),
]


def build_questions():
    qs = []
    for line in open(f"{P}/E1-tasks.jsonl"):
        r = json.loads(line)
        qs.append(
            {
                "id": r["id"],
                "question": r["question"],
                "truth": r["truth"],
                "truth_evidence": r["truth_evidence"],
                "source": "E1",
            }
        )
    derived = []
    for line in open(f"{P}/L1-300.jsonl"):
        r = json.loads(line)
        if r.get("label") != "derivable":
            continue
        for pat, tpl in STRIP:
            m = re.fullmatch(pat, r["text"])
            if m:
                derived.append(
                    {
                        "id": r["id"],
                        "question": tpl.format(m.group(1)),
                        "truth": r["text"],
                        "truth_evidence": r["truth_evidence"],
                        "source": "L1",
                    }
                )
                break

    # 平衡取 40：定义 20、赋值 10、导入 10
    def take(pred, n):
        out = [d for d in derived if pred(d["question"])][:n]
        return out

    picked = (
        take(lambda q: "定义在哪个模块" in q, 20)
        + take(lambda q: "被赋值" in q, 10)
        + take(lambda q: "导入" in q, 10)
    )
    return qs + picked


def rea_files(feature):
    """REA 返回的是点分函数名，需要映射回文件；映射本身不算 REA 的功劳。"""
    import dsh_nodes

    t0 = time.time()
    res = dsh_nodes.S33_rea_trace({"target": rmd.TARGET, "feature": feature, "hops": 2})
    payload = json.dumps(res, ensure_ascii=False)
    cc = (res.get("result") or {}).get("call_chain") or {}
    names = list(cc.get("seeds") or []) + list(cc.get("all_functions") or [])
    ranked, seen = [], set()
    for n in names:
        leaf = n.rsplit(".", 1)[-1]
        for rel, _line in rmd.INDEX["defs"].get(leaf, []):
            if rel not in seen:
                seen.add(rel)
                ranked.append(rel)
        dotted = n.rsplit(".", 1)[0].replace(".", "/")
        for rel in (f"{dotted}.py", f"{dotted}/__init__.py"):
            if rel not in seen and rel in rmd.REL.values():
                seen.add(rel)
                ranked.append(rel)
    return ranked, len(payload.encode()), round((time.time() - t0) * 1000, 1)


def main():
    qs = build_questions()
    rows = []
    for q in qs:
        truth_file = q["truth_evidence"][0].rsplit(":", 1)[0]
        symbols = rmd.extract_symbols(q["question"])
        cand = {"text": q["question"], "question": q["question"]}

        # content：记忆里直接有答案
        content_tokens = tok(q["truth"])

        # pointer_grep
        t0 = time.time()
        g = {"verdict": "NONE", "symbols": symbols, "assertion": "code_structure"}
        dec = rmd.decode(cand, g)
        grep_files = [e["file"] for e in dec.get("evidence", [])]
        grep_ms = round((time.time() - t0) * 1000, 1)

        # pointer_rea：指针里存的是符号，不是整句问题
        rf, rbytes, rms = rea_files(" ".join(symbols) or q["question"])

        # rmd：门槛作用在"候选记忆"（真值文本）上，而不是作用在问题上
        gate = rmd.gate({"text": q["truth"], "question": q["truth"]})
        if gate["verdict"] == "NONE":
            rmd_ok = truth_file in grep_files
            rmd_tokens = tok(" ".join(symbols))
            rmd_over = False
        else:
            # 判为 CONTENT 表示把事实本身存下来，读时直接命中；但可推导事实被存即过度存储
            rmd_ok = True
            rmd_tokens = content_tokens
            rmd_over = True

        rows.append(
            {
                "id": q["id"],
                "source": q["source"],
                "question": q["question"],
                "truth_file": truth_file,
                "content": {"ok": True, "tokens": content_tokens},
                "pointer_grep": {
                    "ok": truth_file in grep_files,
                    "files": grep_files[:3],
                    "ms": grep_ms,
                    "tokens": tok(" ".join(symbols)),
                },
                "pointer_rea": {
                    "ok": truth_file in rf[:3],
                    "files": rf[:3],
                    "ms": rms,
                    "bytes": rbytes,
                    "tokens": tok(" ".join(symbols)),
                },
                "rmd": {
                    "gate": gate["verdict"],
                    "ok": rmd_ok,
                    "ms": grep_ms,
                    "tokens": rmd_tokens,
                    "over_store": rmd_over,
                },
            }
        )

    with open(f"{P}/L2-runs.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    n = len(rows)
    for cond in ("content", "pointer_grep", "pointer_rea", "rmd"):
        ok = sum(1 for r in rows if r[cond]["ok"])
        ms = sum(r[cond].get("ms", 0) for r in rows) / n
        tk = sum(r[cond]["tokens"] for r in rows) / n
        print(
            f"{cond:14s} 正确 {ok}/{n} ({ok/n:.0%})  平均时延 {ms:.0f} ms  平均注入 {tk:.0f} tokens"
        )
    print("REA 平均输出字节:", int(sum(r["pointer_rea"]["bytes"] for r in rows) / n))
    print("RMD 误存（可推导却存内容）:", sum(1 for r in rows if r["rmd"]["over_store"]), "/", n)
    bad = [r["id"] for r in rows if not r["pointer_grep"]["ok"]]
    print("grep 未命中:", bad)
    badr = [r["id"] for r in rows if not r["pointer_rea"]["ok"]]
    print("REA 未命中:", badr)


if __name__ == "__main__":
    main()
