"""上下文打包：只读检索 + token 预算裁剪。

契约见 references/pack.md：
- 命中来源：docs / skills 的标题、路径、触发词，以及 edges 的一跳关联；
- 只返回指针（路径 / 标题 / 估算 token），不读取也不复制正文；
- 累计估算 token 不超过预算，超预算的候选跳过并计入 skipped。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from . import signature, store

DEFAULT_BUDGET = 2000
MAX_KEYWORDS = 32
TITLE_WEIGHT = 2.0
PATH_WEIGHT = 1.0
TRIGGER_WEIGHT = 1.5
EDGE_WEIGHT = 0.5


def estimate_tokens(size_bytes: int) -> int:
    """按 UTF-8 中文 3 字节/字符、1.5 字符/token 粗估，仅用于预算裁剪。"""
    chars = max(int(size_bytes or 0) // 3, 0)
    return max(1, int(round(chars / 1.5))) if chars else 1


def _keywords(query: str) -> list:
    tokens = signature.tokenize(signature.clean(query))
    ordered = []
    for token in tokens:
        if token and token not in ordered:
            ordered.append(token)
    return ordered[:MAX_KEYWORDS]


def _score_row(title: str, path: str, keywords, extra_text: str = ""):
    """返回 (score, reasons)；标题权重最高，其次触发词与路径。"""
    title_field = (title or "").lower()
    path_field = (path or "").lower()
    extra_field = (extra_text or "").lower()
    score = 0.0
    title_hits, path_hits, extra_hits = [], [], []
    for keyword in keywords:
        if keyword in title_field:
            score += TITLE_WEIGHT
            title_hits.append(keyword)
        elif keyword in path_field:
            score += PATH_WEIGHT
            path_hits.append(keyword)
        elif keyword in extra_field:
            score += TRIGGER_WEIGHT
            extra_hits.append(keyword)
    reasons = []
    if title_hits:
        reasons.append("标题命中：{}".format("、".join(title_hits[:3])))
    if extra_hits:
        reasons.append("触发词命中：{}".format("、".join(extra_hits[:3])))
    if path_hits:
        reasons.append("路径命中：{}".format("、".join(path_hits[:3])))
    return score, reasons


def _skill_size(root: Path, rel_path: str) -> int:
    try:
        return (root / rel_path).stat().st_size
    except OSError:
        return 0


def _edge_boost(conn, hit_paths, scores: dict, reasons: dict) -> None:
    """一跳关联加分：被命中文件引用、或引用命中文件的候选。"""
    if not hit_paths:
        return
    placeholders = ",".join("?" for _ in hit_paths)
    rows = conn.execute(
        "SELECT src, dst FROM edges WHERE kind='references' "
        "AND (src IN ({0}) OR dst IN ({0}))".format(placeholders),
        tuple(hit_paths) * 2,
    ).fetchall()
    for row in rows:
        source, target = row["src"], row["dst"]
        if source in hit_paths and target in scores and target not in hit_paths:
            scores[target] += EDGE_WEIGHT
            reasons[target].append("被 {} 引用".format(source))
        elif target in hit_paths and source in scores and source not in hit_paths:
            scores[source] += EDGE_WEIGHT
            reasons[source].append("引用了 {}".format(target))


def pack(root, config: dict, conn, query: str, budget: int = DEFAULT_BUDGET) -> dict:
    """只读打包，返回按分数排序且在预算内的指针列表。"""
    root = Path(root).expanduser().resolve()
    query = (query or "").strip()
    if not query:
        raise store.CmError(store.EXIT_USAGE, "打包查询不能为空")
    try:
        budget = int(budget)
    except (TypeError, ValueError):
        raise store.CmError(store.EXIT_USAGE, "预算必须是整数") from None
    if budget <= 0:
        raise store.CmError(store.EXIT_USAGE, "预算必须大于 0")

    keywords = _keywords(query)
    if not keywords:
        raise store.CmError(store.EXIT_USAGE, "查询没有可用关键词")

    scores, reasons, meta = {}, {}, {}

    for row in conn.execute("SELECT path, title, doc_type, size FROM docs WHERE status = 'active'"):
        score, row_reasons = _score_row(row["title"], row["path"], keywords)
        if score <= 0:
            continue
        path = row["path"]
        scores[path] = score
        reasons[path] = list(row_reasons)
        meta[path] = {
            "path": path,
            "title": row["title"] or Path(path).stem,
            "kind": "doc",
            "doc_type": row["doc_type"] or "other",
            "estimated_tokens": estimate_tokens(int(row["size"] or 0)),
        }

    for row in conn.execute(
        "SELECT name, path, version, triggers_json FROM skills WHERE status != 'orphan'"
    ):
        triggers = ""
        try:
            triggers = " ".join(json.loads(row["triggers_json"] or "[]"))
        except (TypeError, ValueError):
            triggers = str(row["triggers_json"] or "")
        score, row_reasons = _score_row(row["name"], row["path"], keywords, triggers)
        if score <= 0:
            continue
        path = row["path"]
        scores[path] = score
        reasons[path] = list(row_reasons)
        meta[path] = {
            "path": path,
            "title": row["name"] or Path(path).parent.name,
            "kind": "skill",
            "version": row["version"] or "",
            "estimated_tokens": estimate_tokens(_skill_size(root, path)),
        }

    _edge_boost(conn, list(scores), scores, reasons)

    ordered = sorted(scores, key=lambda path: (-scores[path], meta[path]["estimated_tokens"], path))
    items, skipped, used = [], 0, 0
    for path in ordered:
        info = meta[path]
        cost = int(info["estimated_tokens"])
        if used + cost > budget:
            skipped += 1
            continue
        used += cost
        item = dict(info)
        item["score"] = round(scores[path], 2)
        item["reason"] = "；".join(dict.fromkeys(reasons[path])) or "关键词命中"
        items.append(item)

    notes = []
    if not items and not skipped:
        notes.append("无候选命中：请换关键词，或先执行 cm scan")
    if skipped:
        notes.append("{} 个候选因预算不足被跳过".format(skipped))

    return {
        "schema_version": "1.0",
        "command": "pack",
        "workspace": str(root),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "query": query,
        "keywords": keywords,
        "budget": budget,
        "estimated_tokens": used,
        "item_count": len(items),
        "items": items,
        "skipped": skipped,
        "truncated": bool(skipped),
        "read_only": True,
        "notes": notes,
    }
