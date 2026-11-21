"""残差记忆器 MVP v0.2 —— 五值门槛 + 证据排序 + L1 批量评测。

相对 v0.1 的改动：
1. 证据排序：符号 IDF × 通用词降权 × 测试/__init__ 文件惩罚；
2. 写入自包含校验：候选文本必须带可检索锚点，否则不判 NONE；
3. REA 短路：grep 命中即返回，REA 只在"有符号但探针未命中"时调用；
4. 决策/偏好/否决/外部状态/教训 视为结构性残差（先于符号判定）。
"""

import ast
import json
import os
import re
import sys
import time

TARGET = os.environ.get("RMD_TARGET", "/tmp/e1b_clean/1-ARCHITECTURE/dreamos")
EXP = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/55-AI大模型研究报告/认知系统研究/experiments"
sys.path.insert(0, "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/33-REA逆向解析工程")

SENSITIVE = (
    "密码",
    "password",
    "secret",
    "api key",
    "api_key",
    "apikey",
    "credential",
    "凭证",
    "私钥",
    "token",
    "密钥",
    "口令",
)
RESIDUAL_MARKERS = (
    "偏好",
    "否决",
    "不允许",
    "禁止",
    "决定",
    "约定",
    "必须",
    "教训",
    "代价",
    "外部状态",
    "当前运行",
    "曾经尝试",
)
STRUCTURAL = (
    "定义",
    "声明",
    "导入",
    "赋值",
    "读取",
    "依赖",
    "继承",
    "实现在",
    "注册在",
    "被引用",
    "位于",
    "所在包",
    "提供了",
    "入参",
    "父类是",
    "异步函数",
    "返回类型",
    "字段包括",
    "所属模块",
    "实现了",
)
RUNTIME = (
    "部署在",
    "跑在",
    "挂在",
    "实例",
    "端口",
    "版本",
    "目录在",
    "落在",
    "地址",
    "副本",
    "到期",
    "仓库在",
    "备份在",
)
DECISION = (
    "复核",
    "白名单",
    "默认",
    "只",
    "不再",
    "沿用",
    "冻结",
    "押后",
    "暂不",
    "维持",
    "停掉",
    "放弃",
    "停止",
    "保留",
    "人工",
    "值班",
    "团队",
    "业务方",
    "架构组",
    "风控岗",
    "会签",
    "变更单",
    "降级",
    "暂停",
    "口径",
    "阈值",
    "上限",
    "收盘后",
    "开盘前",
    "上线前",
    "审计",
)
PROCEDURE_MARKERS = ("先", "再", "步骤", "流程", "清单", "核对")
STOP = {
    "self",
    "state",
    "return",
    "None",
    "True",
    "False",
    "str",
    "int",
    "dict",
    "list",
    "Any",
    "Optional",
}
GENERIC = {
    "results",
    "result",
    "data",
    "value",
    "values",
    "output",
    "report",
    "config",
    "client",
    "handler",
    "update",
    "execute",
    "run",
    "main",
    "init",
    "get",
    "set",
    "node",
    "nodes",
    "types",
    "store",
    "summary",
    "status",
    "error",
    "message",
    "content",
    "text",
    "item",
    "items",
    "params",
    "options",
    "args",
    "kwargs",
    "method",
    "func",
    "function",
    "class",
    "module",
}


def collect_files(target):
    out = []
    for root, dirs, files in os.walk(target):
        dirs[:] = [d for d in dirs if d not in {"__pycache__", ".git", "node_modules"}]
        for name in files:
            if name.endswith(".py"):
                out.append(os.path.join(root, name))
    return sorted(out)


FILES = collect_files(TARGET)
REL = {f: os.path.relpath(f, TARGET) for f in FILES}


def extract_symbols(text):
    spans = re.findall(r"`([^`]+)`", text)
    tokens = [t.strip().rstrip(".") for t in re.findall(r"[A-Za-z_][A-Za-z0-9_.]{2,}", text)]
    cands = [
        t
        for t in spans + tokens
        if t and t not in STOP and len(t) >= 3 and ("_" in t or "." in t or re.search(r"[A-Z]", t))
    ]
    seen, out = set(), []
    for t in cands:
        parts = [t] + ([t.split(".")[-1]] if "." in t else [])
        for p in parts:
            if p in seen or len(p) < 4 or p in STOP:
                continue
            seen.add(p)
            out.append(p)
    return out[:14]


def specificity(symbol):
    if symbol.lower() in GENERIC:
        return 0.2
    if len(symbol) >= 12:
        return 1.2
    if "_" in symbol or re.search(r"[A-Z]", symbol):
        return 1.0
    return 0.5


def is_self_contained(symbols):
    return any(
        s.lower() not in GENERIC and (len(s) >= 8 or "_" in s or re.search(r"[A-Z]", s))
        for s in symbols
    )


def classify_assertion(text):
    """v0.3 断言类型判定：只有"代码结构事实"才允许进入探针。

    默认拒绝：无法归入代码结构句式的断言，一律按残差处理。
    """
    for word in STRUCTURAL:
        if word in text:
            for word2 in RUNTIME:
                if word2 in text:
                    return "runtime_state", word2
            for word3 in DECISION:
                if word3 in text:
                    return "decision", word3
            return "code_structure", word
    for word in RUNTIME:
        if word in text:
            return "runtime_state", word
    for word in DECISION:
        if word in text:
            return "decision", word
    return "unknown", ""


def probe_grep(symbols):
    hits = {s: [] for s in symbols}
    patterns = {
        s: re.compile(r"(?<![A-Za-z0-9_])" + re.escape(s) + r"(?![A-Za-z0-9_])") for s in symbols
    }
    for f in FILES:
        try:
            lines = open(f, encoding="utf-8").read().splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(lines, 1):
            for s, pat in patterns.items():
                if len(hits[s]) < 60 and pat.search(line):
                    hits[s].append((REL[f], i, line.strip()[:160]))
    return hits


def build_index():
    defs, envs, assigns, imports = {}, [], [], []
    for f in FILES:
        try:
            tree = ast.parse(open(f, encoding="utf-8").read(), filename=f)
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                defs.setdefault(node.name, []).append((REL[f], node.lineno))
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "getenv"
            ):
                envs.append((REL[f], node.lineno))
            if isinstance(node, ast.Attribute) and node.attr == "environ":
                envs.append((REL[f], node.lineno))
            if isinstance(node, ast.Assign):
                for tgt in node.targets:
                    if (
                        isinstance(tgt, ast.Attribute)
                        and isinstance(tgt.value, ast.Name)
                        and tgt.value.id == "self"
                    ):
                        assigns.append((REL[f], node.lineno, tgt.attr))
            if isinstance(node, ast.ImportFrom) and node.module:
                for a in node.names:
                    imports.append((REL[f], node.lineno, a.name, node.module))
    return {"defs": defs, "envs": envs, "assigns": assigns, "imports": imports}


INDEX = build_index()


def gate(candidate):
    text = candidate["text"]
    plain = re.sub(r"`[^`]*`", "", text)
    low = plain.lower()
    if any(k in low for k in SENSITIVE):
        return {"verdict": "REJECT", "reason": "命中敏感词", "symbols": []}
    symbols = extract_symbols(text)
    self_ok = is_self_contained(symbols)
    atype, hit = classify_assertion(text)
    if any(m in text for m in RESIDUAL_MARKERS):
        return {
            "verdict": "CONTENT",
            "reason": "命中结构性残差标记",
            "symbols": symbols,
            "self_contained": self_ok,
            "assertion": "residual_marker",
        }
    if atype != "code_structure":
        return {
            "verdict": "CONTENT",
            "reason": f"断言类型={atype}（{hit or '无结构谓语'}）",
            "symbols": symbols,
            "self_contained": self_ok,
            "assertion": atype,
        }
    if not self_ok:
        if all(m in text for m in ("先", "再")) or any(m in text for m in ("步骤", "清单")):
            return {
                "verdict": "PROCEDURE",
                "reason": "无自包含锚点，含步骤语义",
                "symbols": symbols,
                "self_contained": False,
                "assertion": "procedure",
            }
        return {
            "verdict": "CONTENT",
            "reason": "候选文本不自包含，无法验证可恢复性",
            "symbols": symbols,
            "self_contained": False,
            "assertion": "not_self_contained",
        }

    hits = probe_grep(symbols)
    covered = [s for s in symbols if hits[s]]
    if covered:
        files = sorted({h[0] for lst in hits.values() for h in lst})
        return {
            "verdict": "NONE",
            "reason": f"grep 命中 {len(covered)}/{len(symbols)} 个符号",
            "symbols": symbols,
            "self_contained": True,
            "assertion": "code_structure",
            "covered": covered,
            "files": files[:5],
            "pointer": {"probe": "grep", "pattern": covered[0], "anchor_files": files[:3]},
        }
    ast_hits = {
        s: INDEX["defs"].get(s.split(".")[-1], [])
        for s in symbols
        if INDEX["defs"].get(s.split(".")[-1])
    }
    if ast_hits:
        return {
            "verdict": "NONE",
            "reason": "AST 定义命中",
            "symbols": symbols,
            "self_contained": True,
            "assertion": "code_structure",
            "ast_defs": ast_hits,
        }
    return {
        "verdict": "CONTENT",
        "reason": "探针均未命中",
        "symbols": symbols,
        "self_contained": True,
        "assertion": "code_structure",
    }


def decode(candidate, g):
    if g["verdict"] != "NONE":
        return {"mode": "recall", "evidence": [], "content": candidate["text"]}
    query_symbols = list(
        dict.fromkeys((g.get("symbols") or []) + extract_symbols(candidate.get("question", "")))
    )
    hits = probe_grep(query_symbols)
    symbol_files = {s: {h[0] for h in lst} for s, lst in hits.items() if lst}
    scores = {}
    for s, files in symbol_files.items():
        weight = (1.0 / max(1, len(files))) * specificity(s)
        for rel in files:
            scores[rel] = scores.get(rel, 0.0) + weight
    for rel in list(scores):
        if "/tests/" in rel or rel.endswith("__init__.py") or "/test_" in rel:
            scores[rel] *= 0.1
    # 定义优先：查询符号的定义文件加分，压过 re-export 的 __init__
    for s in query_symbols:
        for rel, _line in INDEX["defs"].get(s.split(".")[-1], []):
            scores[rel] = scores.get(rel, 0.0) + 1.5
    # 锚点模块命中：候选文本里点名的模块，其文件加分
    mod_tokens = [s for s in query_symbols if "." in s]
    for rel in list(scores):
        dotted = rel[:-3].replace("/", ".").replace(".__init__", "")
        if any(
            dotted == m or dotted.endswith("." + m) or m.endswith("." + dotted) for m in mod_tokens
        ):
            scores[rel] += 1.5
    top = sorted(scores.items(), key=lambda x: -x[1])[:3]
    evidence = []
    for rel, score in top:
        line_hits = {}
        for s, lst in hits.items():
            for hit in lst:
                if hit[0] == rel:
                    line_hits.setdefault(hit[1], {"symbols": set(), "source": hit[2]})
                    line_hits[hit[1]]["symbols"].add(s)
        if not line_hits:
            continue
        best = max(line_hits.items(), key=lambda kv: len(kv[1]["symbols"]))
        evidence.append(
            {
                "file": rel,
                "line": best[0],
                "source": best[1]["source"],
                "symbols": sorted(best[1]["symbols"]),
                "score": round(score, 3),
            }
        )
    return {"mode": "reconstruct", "evidence": evidence[:5]}


def anchor(candidate, dec):
    expected = {e.rsplit(":", 1)[0] for e in candidate.get("truth_evidence") or []}
    files = [e["file"] for e in dec.get("evidence", [])]
    top1 = bool(files) and files[0] in expected
    top3 = bool(expected & set(files))
    line_ok = None
    if candidate.get("truth_evidence") and dec.get("evidence"):
        parts = candidate["truth_evidence"][0].rsplit(":", 1)
        if len(parts) == 2 and parts[1].isdigit():
            line_ok = (
                any(e["file"] == parts[0] and e["line"] == int(parts[1]) for e in dec["evidence"])
                or top1
            )
        else:
            line_ok = top1
    return top1, top3, line_ok


def probe_rea(feature):
    try:
        import dsh_nodes

        started = time.time()
        res = dsh_nodes.S33_rea_trace({"target": TARGET, "feature": feature, "hops": 2})
        cc = (res.get("result") or {}).get("call_chain") or {}
        return {
            "seeds": cc.get("seeds") or [],
            "bytes": len(json.dumps(cc, ensure_ascii=False).encode()),
            "ms": round((time.time() - started) * 1000, 1),
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "seeds": [], "bytes": 0, "ms": 0}


def run(tasks, out_name):
    rows = []
    for t in tasks:
        started = time.time()
        g = gate(t)
        dec = decode(t, g)
        top1, top3, line_ok = anchor(t, dec) if t.get("truth_evidence") else (None, None, None)
        rea = {"seeds": [], "bytes": 0, "ms": 0}
        rea_called = False
        if (
            g["verdict"] == "CONTENT"
            and g.get("symbols")
            and g.get("assertion") == "code_structure"
        ):
            rea = probe_rea(t.get("question") or t["text"])
            rea_called = True
        rows.append(
            {
                "id": t["id"],
                "label": t.get("label"),
                "category": t.get("category"),
                "gate": g["verdict"],
                "gate_reason": g["reason"],
                "self_contained": g.get("self_contained"),
                "symbols": len(g.get("symbols") or []),
                "top1": top1,
                "top3": top3,
                "line_ok": line_ok,
                "rea_called": rea_called,
                "rea_seeds": len(rea.get("seeds") or []),
                "rea_bytes": rea.get("bytes", 0),
                "latency_ms": round((time.time() - started) * 1000, 1),
                "evidence_top": dec.get("evidence", [])[:2],
            }
        )
    with open(f"{EXP}/{out_name}", "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return rows


def summarize(rows):
    by = {}
    for label in {r["label"] for r in rows if r["label"]}:
        sub = [r for r in rows if r["label"] == label]
        by[label] = len(sub)
        if label == "derivable":
            stored = [r for r in sub if r["gate"] != "NONE"]
            print(
                f"derivable {len(sub)}: 误存={len(stored)}  top1={sum(1 for r in sub if r['top1'])}  "
                f"top3={sum(1 for r in sub if r['top3'])}  line={sum(1 for r in sub if r['line_ok'])}"
            )
        elif label == "non_derivable":
            missed = [r for r in sub if r["gate"] == "NONE"]
            print(
                f"non_derivable {len(sub)}: 漏存(判NONE)={len(missed)}  CONTENT={sum(1 for r in sub if r['gate']=='CONTENT')}"
            )
        else:
            print(f"{label} {len(sub)}: REJECT={sum(1 for r in sub if r['gate']=='REJECT')}")
    rea_calls = sum(1 for r in rows if r["rea_called"])
    print(
        f"REA 调用 {rea_calls}/{len(rows)}，字节 {sum(r['rea_bytes'] for r in rows)}，"
        f"中位时延 {sorted(r['latency_ms'] for r in rows)[len(rows)//2]} ms"
    )


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else f"{EXP}/E1-tasks.jsonl"
    tasks = [json.loads(line) for line in open(path) if line.strip()]
    for t in tasks:
        t.setdefault("label", "derivable")
        t.setdefault("question", t.get("text") or t.get("question"))
    rows = run(tasks, sys.argv[2] if len(sys.argv) > 2 else "E2b-runs.jsonl")
    summarize(rows)


if __name__ == "__main__":
    main()
