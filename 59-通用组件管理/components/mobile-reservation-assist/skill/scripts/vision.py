"""视觉兜底：无障碍节点树不可用时，用 OCR 文本块（文本 + 坐标 + 置信度）定位目标。

定位仍是确定性规则（复用 locator 的打分与支付红线），只是输入从节点树换成 OCR 块：
- 过滤：空文本、低置信度（默认 <0.5）、非法坐标；
- 打分：规则分 × (0.5 + 0.5 × 置信度)；
- 输出 `vision.v1`，`best.bounds` 可直接点击。
"""

from __future__ import annotations

import re

import locator

SCHEMA = "vision.v1"
MIN_CONFIDENCE = 0.5
MATCH_THRESHOLD = 0.3
TOP_N = 5


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _valid_bounds(bounds) -> bool:
    if not isinstance(bounds, (list, tuple)) or len(bounds) != 4:
        return False
    try:
        left, top, right, bottom = (int(value) for value in bounds)
    except (TypeError, ValueError):
        return False
    return left >= 0 and top >= 0 and right > left and bottom > top


def locate(
    intent: str,
    blocks: list[dict],
    min_confidence: float | None = None,
    threshold: float = MATCH_THRESHOLD,
) -> dict:
    """在 OCR 块中定位意图目标；返回 `vision.v1`。"""
    intent = _norm(intent)
    base = {"schema": SCHEMA, "intent": intent, "ok": False, "source": "ocr",
            "best": None, "candidates": [], "reason": ""}
    if not intent:
        return dict(base, reason="empty_intent")
    if any(marker in intent for marker in locator.FORBIDDEN_INTENTS):
        return dict(base, source="guard", reason="forbidden_intent")

    floor = MIN_CONFIDENCE if min_confidence is None else float(min_confidence)
    nodes: list[dict] = []
    metas: list[dict] = []
    for block_index, block in enumerate(blocks or []):
        text = _norm(block.get("text"))
        bounds = block.get("bounds")
        try:
            confidence = float(block.get("confidence", 0))
        except (TypeError, ValueError):
            confidence = 0.0
        if not text or confidence < floor or not _valid_bounds(bounds):
            continue
        nodes.append(
            {"text": text, "desc": "", "clickable": True,
             "bounds": [int(value) for value in bounds]}
        )
        metas.append({"block_index": block_index, "confidence": round(confidence, 3)})

    if not nodes:
        return dict(base, reason="no_blocks")

    ranked = locator.rank(intent, nodes)
    for item in ranked:
        meta = metas[item["index"]]
        item["block_index"] = meta["block_index"]
        item["confidence"] = meta["confidence"]
        item["score"] = round(item["score"] * (0.5 + 0.5 * meta["confidence"]), 3)
    ranked.sort(key=lambda item: item["score"], reverse=True)

    top = ranked[:TOP_N]
    best = top[0] if top and top[0]["score"] >= threshold else None
    if best:
        return dict(base, ok=True, best=best, candidates=top, reason="ocr_match")
    return dict(base, candidates=top, reason="no_match")
