"""L2c：在 decode 之后加两级校验。

1) 行内容校验：命中行必须是 def / class / 赋值语句，且与查询符号同名；
2) 转发跟随：命中行若是 import/re-export，则用定义索引跳到真正定义处（最多 1 跳）。

校验后若无有效证据，或最高分仍偏低，则回退为"存内容"。
"""

import importlib
import json
import re
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


INV = {v: k for k, v in rmd.REL.items()}
_CACHE = {}

DEF_RE = re.compile(r"^\s*(?:async\s+)?(?:def|class)\s+(\w+)")
ASSIGN_RE = re.compile(r"^\s*(\w+)\s*(?::[^=]+)?=(?!=)")
IMPORT_RE = re.compile(r"^\s*(?:from\s+[\w.]+\s+import\s+|import\s+[\w.]+)")


def lines_of(rel):
    if rel not in _CACHE:
        try:
            _CACHE[rel] = open(INV[rel], encoding="utf-8", errors="ignore").read().splitlines()
        except Exception:  # noqa: BLE001
            _CACHE[rel] = []
    return _CACHE[rel]


def verify(rel, line, symbols):
    """返回 (kind, name)；kind ∈ def / assign / import / other / missing"""
    ls = lines_of(rel)
    if not (1 <= line <= len(ls)):
        return "missing", None
    text = ls[line - 1]
    m = DEF_RE.match(text)
    if m:
        return "def", m.group(1)
    if IMPORT_RE.match(text):
        return "import", None
    m = ASSIGN_RE.match(text)
    if m:
        return "assign", m.group(1)
    return "other", None


def qtype_of(question):
    if "定义在哪个模块" in question:
        return "def"
    if "被赋值" in question:
        return "assign"
    if "导入" in question:
        return "import"
    return "usage"


def resolve(rel, line, symbols, qtype):
    """按问题类型校验；只有"定义类"问题才做 import 跟随。"""
    ls = lines_of(rel)
    if not (1 <= line <= len(ls)):
        return None
    text = ls[line - 1]
    for s in symbols:
        leaf = s.split(".")[-1]
        if qtype == "usage":
            # 使用类问题：该行出现符号即算有效，不做定义校验、不跟随
            if leaf in text and "/tests/" not in rel:
                return {"file": rel, "line": line, "how": "usage"}
            continue
        kind, name = verify(rel, line, [leaf])
        if qtype == "def" and kind in ("def", "assign") and name == leaf:
            return {"file": rel, "line": line, "how": kind}
        if qtype == "assign" and kind == "assign" and name == leaf:
            return {"file": rel, "line": line, "how": "assign"}
        if qtype == "import" and (kind == "import" or leaf in text):
            return {"file": rel, "line": line, "how": "import"}
        # 定义类问题遇到转发行：跟随一跳
        if qtype == "def" and kind in ("import", "other", "missing"):
            for r2, l2 in rmd.INDEX["defs"].get(leaf, []):
                if r2 == rel:
                    continue
                k2, n2 = verify(r2, l2, [leaf])
                if k2 in ("def", "assign") and n2 == leaf:
                    return {"file": r2, "line": l2, "how": "follow"}
    return None


def run():
    rows = []
    for q in R.build_questions():
        truth_file = q["truth_evidence"][0].rsplit(":", 1)[0]
        symbols = rmd.extract_symbols(q["question"])
        qtype = qtype_of(q["question"])
        g = {"verdict": "NONE", "symbols": symbols, "assertion": "code_structure"}
        dec = rmd.decode({"text": q["question"], "question": q["question"]}, g)
        raw = dec.get("evidence", [])
        good, dropped = [], []
        for e in raw:
            r2 = resolve(e["file"], e["line"], e["symbols"], qtype)
            if r2:
                r2["score"] = e["score"]
                if r2["file"] not in [x["file"] for x in good]:
                    good.append(r2)
            else:
                dropped.append(e["file"])
        weak = (not good) or (good[0]["score"] < 1.0)
        files = [x["file"] for x in good]
        ok = True if weak else (truth_file in files)
        rows.append(
            {
                "id": q["id"],
                "truth_file": truth_file,
                "files": files[:3],
                "weak": weak,
                "ok": ok,
                "dropped": dropped[:3],
                "how": [x["how"] for x in good[:3]],
                "tokens": tok(q["truth"]) if weak else tok(" ".join(symbols)),
            }
        )
    return rows


rows = run()
n = len(rows)
acc = sum(1 for r in rows if r["ok"])
fb = sum(1 for r in rows if r["weak"])
tks = sum(r["tokens"] for r in rows) / n
follow = sum(1 for r in rows if "follow" in r["how"])
print(
    f"L2c 正确 {acc}/{n} ({acc/n:.0%})  回退 {fb}/{n} ({fb/n:.0%})  平均存储 {tks:.1f} tokens  跟随修正 {follow} 题"
)
print("仍失败:", [(r["id"], r["files"][:1], r["truth_file"]) for r in rows if not r["ok"]])
print("被校验剔除:", [(r["id"], r["dropped"][:1]) for r in rows if r["dropped"]][:10])

with open(f"{P}/L2c-runs.jsonl", "w") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
