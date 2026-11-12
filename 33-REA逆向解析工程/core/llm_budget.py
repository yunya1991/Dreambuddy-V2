"""Token 预算与成本记账（SPEC-33-E T-E8）。

设计边界：
  - 内核不调用模型、不存 API key；这里只做预算校验与成本台账。
  - 单次生成上限：输入 8,000 / 输出 2,000 token；超限必须降级模板并标
    `degraded=true`（禁止静默超支）。
  - 台账为 JSONL 追加写，一行一次生成：{model, tokens_in, tokens_out, gate, degraded, ts}。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

MAX_TOKENS_IN = 8_000
MAX_TOKENS_OUT = 2_000
COST_LEDGER_ENV = "REA_LLM_COST_PATH"


def estimate_tokens(text: str) -> int:
    """确定性粗估：4 字符 ≈ 1 token（仅用于预算预检，不宣称精确）。"""
    return max(0, len(str(text)) // 4)


def check_budget(tokens_in: Any, tokens_out: Any) -> dict[str, Any]:
    """校验单次生成预算；超限返回降级建议。"""
    try:
        tin = max(0, int(tokens_in or 0))
    except (TypeError, ValueError):
        tin = 0
    try:
        tout = max(0, int(tokens_out or 0))
    except (TypeError, ValueError):
        tout = 0

    reasons: list[str] = []
    if tin > MAX_TOKENS_IN:
        reasons.append(f"输入 {tin} > 上限 {MAX_TOKENS_IN}")
    if tout > MAX_TOKENS_OUT:
        reasons.append(f"输出 {tout} > 上限 {MAX_TOKENS_OUT}")
    degraded = bool(reasons)
    return {
        "tokens_in": tin,
        "tokens_out": tout,
        "limits": {"tokens_in": MAX_TOKENS_IN, "tokens_out": MAX_TOKENS_OUT},
        "degraded": degraded,
        "action": "degrade_to_template" if degraded else "allow",
        "reason": "；".join(reasons) if degraded else "",
    }


def cost_ledger_path(override: str | Path | None = None) -> Path:
    if override:
        return Path(override)
    env = os.getenv(COST_LEDGER_ENV, "").strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[1] / "reflection_data" / "reports" / "llm_cost.jsonl"


def record_cost(entry: dict[str, Any], *, path: str | Path | None = None) -> dict[str, Any]:
    """追加一条成本记录；缺 model 时不写（调用方应先校验）。"""
    model = str(entry.get("model") or "").strip()
    if not model:
        return {
            "recorded": False,
            "path": str(cost_ledger_path(path)),
            "known_gaps": ["缺少 model"],
        }

    budget = check_budget(entry.get("tokens_in"), entry.get("tokens_out"))
    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "model": model,
        "tokens_in": budget["tokens_in"],
        "tokens_out": budget["tokens_out"],
        "gate": str(entry.get("gate") or "unknown"),
        "degraded": bool(budget["degraded"]),
        "reason": budget["reason"],
        "task": str(entry.get("task") or ""),
    }
    target = cost_ledger_path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        return {
            "recorded": False,
            "path": str(target),
            "known_gaps": [f"台账写入失败（FAIL-OPEN）: {type(exc).__name__}: {exc}"],
        }
    return {"recorded": True, "path": str(target), "record": record, "known_gaps": []}
