"""D2-A 基线预测器：B0 文档 kNN / B1 关键词检索（SPEC v0.4 §4.1 基线表）。

基线只使用 holdout 快照（kept 节点），不得读取被扣留模块内容，也不使用
指向被扣留模块的图边（那是 ground truth）。
输出统一为预测边集合 {(src, dst, kind)}，与 ground truth 同口径比较。
"""

from __future__ import annotations

import math
import re
from collections import Counter

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]+")
CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
STOP = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "import",
    "def",
    "class",
    "return",
    "self",
    "none",
    "true",
    "false",
    "this",
    "that",
    "are",
    "not",
    "you",
    "can",
}


def tokenize(text: str) -> list[str]:
    """英文标识符 token + 中文二元组（路径/文档以中文为主，纯 ASCII 正则会得到空查询）。"""
    text = text.lower()
    tokens = [t for t in TOKEN_RE.findall(text) if t not in STOP]
    for run in CJK_RE.findall(text):
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
    return tokens


def _doc_text(root, path: str, cache: dict) -> str:
    if path in cache:
        return cache[path]
    try:
        text = (root / path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    cache[path] = text
    return text


def _coverage(probe: Counter, doc: Counter) -> float:
    """查询 token 在文档中的覆盖率——短查询（模块名）下比余弦更稳定。"""
    keys = set(probe)
    if not keys:
        return 0.0
    return len(keys & set(doc)) / len(keys)


def _candidate_sources(snapshot: dict) -> list[str]:
    """候选预测源：kept 的 python 文件节点。"""
    return sorted(n["id"] for n in snapshot.get("kept_nodes", []) if n["type"] == "python_file")


def predict_b0_doc_knn(
    root, snapshot: dict, top_k: int = 20, min_sim: float = 0.1
) -> set[tuple[str, str, str]]:
    """B0：按模块名 token 覆盖率检索最相近的 top-k 源文件，预测它们依赖 holdout 模块。

    预测类型记 import（模块级依赖）。
    """
    module = snapshot["module"]
    cache: dict = {}
    probe = Counter(tokenize(module.replace("-", " ").replace("_", " ")))
    scored = []
    for src in _candidate_sources(snapshot):
        sim = _coverage(probe, Counter(tokenize(_doc_text(root, src, cache))))
        if sim >= min_sim:
            scored.append((sim, src))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return {(src, module, "import") for _, src in scored[:top_k]}


def _bm25_scores(
    docs: dict[str, list[str]], query: list[str], k1: float = 1.5, b: float = 0.75
) -> dict[str, float]:
    if not docs:
        return {}
    n = len(docs)
    avgdl = sum(len(d) for d in docs.values()) / n or 1.0
    df = Counter()
    for d in docs.values():
        for term in set(d):
            df[term] += 1
    scores: dict[str, float] = {}
    for name, doc in docs.items():
        tf = Counter(doc)
        dl = len(doc) or 1
        s = 0.0
        for q in set(query):
            if q not in tf:
                continue
            idf = math.log(1 + (n - df[q] + 0.5) / (df[q] + 0.5))
            s += idf * (tf[q] * (k1 + 1)) / (tf[q] + k1 * (1 - b + b * dl / avgdl))
        if s > 0:
            scores[name] = s
    return scores


def predict_b1_bm25(root, snapshot: dict, top_k: int = 20) -> set[tuple[str, str, str]]:
    """B1：BM25 关键词命中——仅用 holdout 模块名 token 查询检索其余源码。

    不使用指向 holdout 的图边（那是 ground truth）。
    """
    module = snapshot["module"]
    cache: dict = {}
    docs = {src: tokenize(_doc_text(root, src, cache)) for src in _candidate_sources(snapshot)}
    query = tokenize(module.replace("-", " ").replace("_", " "))
    scores = _bm25_scores(docs, query)
    ranked = sorted(scores.items(), key=lambda x: (-x[1], x[0]))[:top_k]
    return {(src, module, "import") for src, _ in ranked}


def normalize_predictions(preds) -> set[tuple[str, str, str]]:
    """统一按 (src, dst_module, kind) 口径——目标端归一为模块。"""
    from .holdout import module_of  # 局部导入避免循环

    return {(e[0], module_of(e[1]), e[2]) for e in preds}


def ground_truth_set(manifest: dict) -> set[tuple[str, str, str]]:
    from .holdout import module_of

    return {
        (e["src"], module_of(e["dst"]), e["kind"]) for e in manifest.get("ground_truth_edges", [])
    }
