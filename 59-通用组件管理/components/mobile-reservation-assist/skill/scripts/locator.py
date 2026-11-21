"""本地小模型定位兜底：选择器失效时，按意图在无障碍节点树中重新定位可点击节点。

顺序：
1. 红线校验：意图或节点文本命中支付/提交类动作 → 直接拒绝；
2. 规则排序：精确 > 包含 > 字符重合率，可点击节点优先；
3. 本地小模型复核（可选，OpenAI 兼容端点）→ 只允许在给定节点下标内选择。

输出 `locator.v1`；模型不可用/超时/越界时静默回退规则结果，不影响主流程。
仅标准库（urllib），无第三方依赖。
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

SCHEMA = "locator.v1"
TOP_N = 5
MATCH_THRESHOLD = 0.3
CLICKABLE_BONUS = 0.0
NON_CLICKABLE_PENALTY = 0.15
CHAR_MATCH_CAP = 0.8
MAX_MODEL_NODES = 60

FORBIDDEN_INTENTS = ("支付", "提交订单", "确认支付", "去支付", "锁座", "占座", "代付", "支付密码")
FORBIDDEN_NODE_MARKERS = ("支付", "提交订单", "锁座", "占座", "代付")

_INDEX_RE = re.compile(r'"index"\s*:\s*(-?\d+)')


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _node_text(node: dict) -> str:
    return _norm("{}{}".format(node.get("text") or "", node.get("desc") or ""))


def _is_forbidden(text: str) -> bool:
    return any(marker in (text or "") for marker in FORBIDDEN_NODE_MARKERS)


def _score(intent: str, node: dict) -> float:
    haystack = _node_text(node)
    if not haystack:
        return 0.0
    if haystack == intent:
        score = 1.0
    elif intent and intent in haystack:
        score = 0.9
    else:
        chars = {ch for ch in intent if not ch.isspace()}
        if not chars:
            return 0.0
        score = min(CHAR_MATCH_CAP, len(chars & set(haystack)) / len(chars))
    if not node.get("clickable"):
        score -= NON_CLICKABLE_PENALTY
    return round(max(0.0, min(1.0, score)), 3)


def rank(intent: str, nodes: list[dict]) -> list[dict]:
    """规则排序：过滤支付类节点，返回按分数降序的候选（含原始下标）。"""
    normalized = _norm(intent)
    ranked = []
    for index, node in enumerate(nodes or []):
        if _is_forbidden(_node_text(node)):
            continue
        score = _score(normalized, node)
        if score <= 0:
            continue
        ranked.append(_candidate(index, node, score))
    ranked.sort(key=lambda item: item["score"], reverse=True)
    return ranked


def _candidate(index: int, node: dict, score: float) -> dict:
    return {
        "index": index,
        "text": _norm(node.get("text") or "")[:60],
        "desc": _norm(node.get("desc") or "")[:60],
        "cls": str(node.get("cls") or ""),
        "clickable": bool(node.get("clickable")),
        "bounds": node.get("bounds") or [],
        "score": score,
    }


def locate(intent: str, nodes: list[dict], use_model: bool = True, threshold: float = MATCH_THRESHOLD) -> dict:
    """在节点树中定位意图目标；返回 `locator.v1`。"""
    intent = _norm(intent)
    base = {"schema": SCHEMA, "intent": intent, "best": None, "candidates": [], "source": "rules"}
    if not intent:
        return dict(base, ok=False, reason="empty_intent")
    if _is_forbidden(intent):
        return dict(base, ok=False, source="guard", reason="forbidden_intent")
    if not nodes:
        return dict(base, ok=False, reason="no_nodes")

    candidates = rank(intent, nodes)
    top = candidates[:TOP_N]
    rules_best = top[0] if top and top[0]["score"] >= threshold else None

    picked = None
    if use_model:
        try:
            index = _model_pick(intent, nodes)
        except Exception:  # 模型只是兜底，任何异常都不能影响主流程
            index = None
        if index is not None and 0 <= index < len(nodes):
            node = nodes[index]
            if not _is_forbidden(_node_text(node)):
                picked = _candidate(index, node, max(1.0, top[0]["score"] if top else 0.0))

    if picked:
        return dict(base, ok=True, best=picked, candidates=top, source="model", reason="local_model")
    if rules_best:
        return dict(base, ok=True, best=rules_best, candidates=top, reason="rule_match")
    return dict(base, ok=False, candidates=top, reason="no_match")


def _load_model_env() -> dict:
    keys = ("MRA_LOCAL_MODEL_URL", "MRA_LOCAL_MODEL_NAME", "MRA_LOCAL_MODEL_KEY", "MRA_LOCAL_MODEL_TIMEOUT")
    return {key: os.environ[key] for key in keys if os.environ.get(key)}


def _model_pick(intent: str, nodes: list[dict]) -> int | None:
    """调用本地小模型在节点列表中选择下标；未配置或失败返回 None。"""
    env = _load_model_env()
    url = env.get("MRA_LOCAL_MODEL_URL")
    model = env.get("MRA_LOCAL_MODEL_NAME")
    if not (url and model):
        return None
    candidates = nodes[:MAX_MODEL_NODES]
    lines = []
    for index, node in enumerate(candidates):
        lines.append(
            "{}. [{}] {} {}".format(
                index,
                "可点" if node.get("clickable") else "文本",
                _node_text(node)[:40],
                "(" + str(node.get("cls") or "") + ")",
            )
        )
    prompt = (
        "你是手机界面定位器。根据目标意图，从下列无障碍节点中选择最匹配的一个。\n"
        "只输出 JSON：{\"index\": 数字}；没有合适节点输出 {\"index\": -1}。\n"
        "目标：{}\n节点：\n{}"
    ).format(intent, "\n".join(lines))
    content = _chat(url, model, env.get("MRA_LOCAL_MODEL_KEY", ""), prompt,
                   float(env.get("MRA_LOCAL_MODEL_TIMEOUT", "4")))
    match = _INDEX_RE.search(content or "")
    if not match:
        return None
    index = int(match.group(1))
    if 0 <= index < len(candidates):
        return index
    return None


def _chat(url: str, model: str, api_key: str, prompt: str, timeout: float) -> str:
    endpoint = url.rstrip("/")
    if not endpoint.endswith("/chat/completions"):
        endpoint += "/chat/completions"
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "stream": False,
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    req = urllib.request.Request(
        endpoint, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return ""
    try:
        return str(data["choices"][0]["message"]["content"] or "")
    except (KeyError, IndexError, TypeError):
        return ""
