#!/usr/bin/env python3
"""D0→D4 求解级联编排器 + telemetry（SPEC §2.4 / §3.4）。

级联顺序**固定不可调**（命中即停）：
    D0 记忆库检索（向量 + 关键词，短期/近期经验）
    D1 记忆树关键词命中（知道在哪）
    D2 上下文邻近 / 树遍历（祖先 + 兄弟 + 子节点）
    D2.5 向量兜底（D1/D2 未命中时的语义近邻）
    D3 REA 逆向解析整个工程（现拆）
    D4 大模型调研（最后手段，成本最高）

硬约束：
1. **命中即停**，禁止并行跑全级联（浪费 token）。
2. D3/D4 成功后**必须**回写记忆树（`on_writeback` 回调），否则下次仍从 D0 空转到 D4。
3. 全级联未命中**必须**返回 `degraded_reason=cascade_exhausted`，并按 SPEC §3.5 落能力缺口工单
   （`gap_reporter` 回调），**禁止**静默返回"没有结果"。
4. 任一阶段抛异常 = 该阶段未命中（fail-open 继续下一级），但必须写进 telemetry。

本模块只做编排，不内联检索实现：各阶段由调用方注入 handler。
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STAGES: tuple[str, ...] = ("D0", "D1", "D2", "D2.5", "D3", "D4")
WRITEBACK_STAGES = ("D3", "D4")
_TELEMETRY_DEFAULT = Path(__file__).resolve().parent / "data" / "cascade_telemetry.jsonl"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def record_event(path: str | Path | None, event: dict) -> None:
    """追加一条 telemetry（FAIL-OPEN：写失败不影响级联）。"""
    target = Path(path) if path else _TELEMETRY_DEFAULT
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 - telemetry 永不阻断主流程
        pass


def summarize(path: str | Path | None = None) -> dict:
    """按阶段统计命中率与平均耗时，用于 G6/G8 口径。"""
    target = Path(path) if path else _TELEMETRY_DEFAULT
    if not target.exists():
        return {"ok": False, "degraded_reason": "telemetry_missing", "path": str(target)}
    per_stage: dict[str, dict] = {}
    runs: dict[str, dict] = {}
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        stage = ev.get("stage")
        if stage:
            item = per_stage.setdefault(stage, {"executed": 0, "hit": 0, "ms": 0.0})
            item["executed"] += 1
            item["hit"] += 1 if ev.get("hit") else 0
            item["ms"] += float(ev.get("latency_ms") or 0.0)
        run = runs.setdefault(ev.get("run_id", ""), {"solved_level": None, "degraded": False})
        if ev.get("final"):
            run["solved_level"] = ev.get("level")
            run["degraded"] = ev.get("ok") is False
    for item in per_stage.values():
        item["hit_rate"] = round(item["hit"] / item["executed"], 3) if item["executed"] else 0.0
        item["avg_ms"] = round(item["ms"] / item["executed"], 1) if item["executed"] else 0.0
        item["ms"] = round(item["ms"], 1)
    total_runs = len(runs)
    return {
        "ok": True,
        "runs": total_runs,
        "degraded_runs": sum(1 for r in runs.values() if r["degraded"]),
        "solved_by_level": {
            lvl: sum(1 for r in runs.values() if r["solved_level"] == lvl)
            for lvl in (*STAGES, None)
            if any(r["solved_level"] == lvl for r in runs.values())
        },
        "per_stage": per_stage,
    }


def _normalize(result: Any) -> tuple[bool, str, Any]:
    """把各阶段返回值归一为 (hit, degraded_reason, payload)。

    约定：`dict` 用 `hit` 优先、否则 `ok`；`bool` 直接当 hit；其余"非空即命中"。
    """
    if result is None:
        return False, "", None
    if isinstance(result, bool):
        return result, "", None
    if isinstance(result, dict):
        hit = result.get("hit")
        if hit is None:
            hit = result.get("ok")
        reason = str(result.get("degraded_reason") or "")
        if hit and reason:
            hit = False
        return bool(hit), reason, result
    if isinstance(result, (list, tuple, set, str)):
        return len(result) > 0, "", result
    return True, "", result


class CascadeOrchestrator:
    """固定顺序的求解级联；各阶段 handler 由调用方注入。"""

    def __init__(
        self,
        handlers: dict[str, Callable[[str], Any]],
        on_writeback: Callable[[str, str, Any], None] | None = None,
        gap_reporter: Callable[[str, list[str]], None] | None = None,
        telemetry_path: str | Path | None = None,
    ):
        unknown = set(handlers) - set(STAGES)
        if unknown:
            raise ValueError(f"unknown cascade stages: {sorted(unknown)}")
        self.handlers = dict(handlers)
        self.on_writeback = on_writeback
        self.gap_reporter = gap_reporter
        self.telemetry_path = telemetry_path

    def solve(self, query: str) -> dict:
        run_id = uuid.uuid4().hex[:12]
        tried: list[str] = []
        events: list[dict] = []
        for stage in STAGES:
            handler = self.handlers.get(stage)
            if handler is None:
                continue
            tried.append(stage)
            started = time.perf_counter()
            error = ""
            try:
                hit, reason, payload = _normalize(handler(query))
            except Exception as exc:  # noqa: BLE001 - 单阶段失败不中断级联
                hit, reason, payload, error = False, "stage_error", None, f"{stage}: {exc}"
            latency = round((time.perf_counter() - started) * 1000, 1)
            events.append(
                {
                    "ts": _now_iso(),
                    "run_id": run_id,
                    "query": query[:200],
                    "stage": stage,
                    "hit": hit,
                    "latency_ms": latency,
                    "degraded_reason": reason,
                    "error": error,
                }
            )
            if hit:
                if stage in WRITEBACK_STAGES and self.on_writeback is not None:
                    try:
                        self.on_writeback(stage, query, payload)
                    except Exception as exc:  # noqa: BLE001
                        events[-1]["writeback_error"] = str(exc)
                events[-1].update({"final": True, "ok": True, "level": stage})
                self._flush(events)
                return {
                    "ok": True,
                    "run_id": run_id,
                    "level": stage,
                    "answer": payload,
                    "stages_tried": tried,
                    "telemetry": events,
                }

        for ev in events:
            ev.setdefault("final", True)
        if events:
            events[-1].update({"ok": False, "level": None})
        self._flush(events)
        if self.gap_reporter is not None:
            try:
                self.gap_reporter(query, tried)
            except Exception:  # noqa: BLE001 - 缺口登记失败不影响返回
                pass
        return {
            "ok": False,
            "run_id": run_id,
            "level": None,
            "degraded_reason": "cascade_exhausted",
            "next": "capability_gap_workorder",
            "stages_tried": tried,
            "telemetry": events,
        }

    def _flush(self, events: list[dict]) -> None:
        for ev in events:
            record_event(self.telemetry_path, ev)


# ── 常用适配器（只做形状转换，不内联检索逻辑）──────────────────


def tree_query_adapter(tree) -> Callable[[str], dict]:
    """D1 适配器：记忆树关键词命中。"""

    def _run(query: str) -> dict:
        res = tree.query(query, top_k=3)
        return {
            "hit": bool(res.get("ok")),
            "degraded_reason": res.get("degraded_reason", ""),
            "result": res,
        }

    return _run


def tree_walk_adapter(tree) -> Callable[[str], dict]:
    """D2 适配器：先定位节点，再取其祖先/兄弟/子节点作为上下文。"""

    def _run(query: str) -> dict:
        res = tree.query(query, top_k=1)
        results = res.get("results") or []
        if not results:
            return {"hit": False, "degraded_reason": res.get("degraded_reason", "tree_no_hit")}
        node = tree.walk(results[0]["path"], depth=2)
        return {"hit": bool(node.get("node")), "result": node}

    return _run


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="求解级联 telemetry 汇总")
    parser.add_argument("--telemetry", default="", help="cascade_telemetry.jsonl 路径")
    parser.add_argument("action", nargs="?", default="summarize", choices=["summarize"])
    args = parser.parse_args()
    print(json.dumps(summarize(args.telemetry or None), ensure_ascii=False, indent=2))
