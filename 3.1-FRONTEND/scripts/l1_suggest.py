# -*- coding: utf-8 -*-
"""L1 建议器（实盘）：L2 交接时返回可点击的规范化问法。

设计约束（SPEC v1.4 §9.3）：
- 只在 `handled=false` 时调用，不进入 L1 直答路径；
- `query` 必须通过 `detect_intent_regex(query) == intent` 校验，
  点击后以该文本重发即可在 S1 下必然命中（无需服务端特判）；
- 预算 `L1_SUGGEST_BUDGET_MS`（默认 3000ms；云端 8099 CPU 推理单条 embed 实测
  600–900ms，与 l1-loop/训练守护进程争抢时超过 3s）；语义通道先试 1.5s，
  失败即回落本地 2-gram 兜底（毫秒级），保证建议不缺席；超时/异常绝不影响主链路。
"""

from __future__ import annotations

import json
import os
import re
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

_HERE = os.path.dirname(os.path.abspath(__file__))
_UNITS_DIR = os.path.abspath(os.path.join(_HERE, "..", "..", "41-文件索引系统", "intent_units"))
_DEFAULT_BUDGET_MS = 3000
_SEMANTIC_BUDGET_S = 1.5  # 语义通道单独设上限，剩余时间留给本地兜底
_LEXICAL_MIN_SCORE = 0.12
_K = 3

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="l1-suggest")
_examples_cache: dict[str, list[str]] = {}
_cache_lock = threading.Lock()


def enabled() -> bool:
    return (os.environ.get("L1_SUGGEST_ENABLED", "1") or "1").strip().lower() not in (
        "0",
        "false",
        "off",
    )


def _budget_s() -> float:
    try:
        return max(1, int(os.environ.get("L1_SUGGEST_BUDGET_MS", str(_DEFAULT_BUDGET_MS)))) / 1000.0
    except ValueError:
        return _DEFAULT_BUDGET_MS / 1000.0


def _load_examples(intent: str) -> list[str]:
    with _cache_lock:
        if intent in _examples_cache:
            return _examples_cache[intent]
    items: list[str] = []
    path = os.path.join(_UNITS_DIR, intent, "examples_zh.jsonl")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line).get("message", "")
                except json.JSONDecodeError:
                    continue
                if msg:
                    items.append(msg)
    with _cache_lock:
        _examples_cache[intent] = items
    return items


def _canonical_query(intent: str, message: str) -> str:
    """取该意图下「正则可确定命中」的示例问法（点击后必中 S1）。"""
    from l1_route_signal import detect_intent_regex  # noqa: PLC0415 — 避免循环依赖

    for q in _load_examples(intent):
        if q == message:
            continue
        try:
            if detect_intent_regex(q) == intent:
                return q
        except Exception:  # noqa: BLE001 — 单条示例异常跳过
            continue
    return ""


def _embed_server_ready() -> bool:
    """常驻向量服务可用性快速探测。

    bge-base 首次进程内加载约 20s（实测），绝不能压在 L2 交接路径上；
    因此只使用常驻服务（默认 127.0.0.1:8099），不可用则直接放弃建议。
    """
    server = (os.environ.get("L1_EMBED_SERVER", "http://127.0.0.1:8099") or "").strip()
    if not server:
        return False
    try:
        u = urlparse(server)
        with socket.create_connection((u.hostname or "127.0.0.1", u.port or 8099), timeout=0.02):
            return True
    except OSError:
        return False


def _bigrams(text: str) -> set[str]:
    s = re.sub(r"[\s\W_]+", "", text or "")
    if len(s) < 2:
        return {s} if s else set()
    return {s[i : i + 2] for i in range(len(s) - 1)}


def _lexical_candidates(message: str, k: int = _K) -> list[tuple[str, float]]:
    """无向量兜底：与各意图示例做字符 2-gram 相似度。

    云端 8099 推理与 l1-loop/训练守护进程争抢 CPU 时单条 embed 可达 3s，
    语义通道必然超时；此路径纯本地字符串计算（毫秒级），保证建议不缺席。
    """
    from l1_route_signal import EXECUTORS  # noqa: PLC0415

    q = _bigrams(message)
    if not q:
        return []
    scored: list[tuple[str, float]] = []
    for intent in EXECUTORS:
        best = 0.0
        for example in _load_examples(intent):
            e = _bigrams(example)
            if not e:
                continue
            score = len(q & e) / len(q | e)
            if score > best:
                best = score
        if best >= _LEXICAL_MIN_SCORE:
            scored.append((intent, round(best, 3)))
    scored.sort(key=lambda item: -item[1])
    return scored[:k]


def build_suggestions(message: str, k: int = _K) -> list[dict]:
    if not enabled() or not message:
        return []
    from l1_route_signal import EXECUTORS, semantic_candidates  # noqa: PLC0415

    top: list = []
    if _embed_server_ready():
        try:
            # admission=False：S1 下语义不参与路由准入，但建议器仍需要语义候选
            top = _executor.submit(semantic_candidates, message, k, admission=False).result(
                timeout=min(_budget_s(), _SEMANTIC_BUDGET_S)
            )
        except Exception:  # noqa: BLE001 — 超时/模型不可用走本地兜底
            top = []
    if not top:
        top = _lexical_candidates(message, k)
    out: list[dict] = []
    seen: set[str] = set()
    for item in top:
        intent, score = item[0], item[1]
        if not intent or intent in seen or intent not in EXECUTORS:
            continue
        query = _canonical_query(intent, message)
        if not query:
            continue
        seen.add(intent)
        out.append(
            {
                "intent": intent,
                "label": query,
                "query": query,
                "score": round(float(score), 3),
            }
        )
        if len(out) >= k:
            break
    return out
