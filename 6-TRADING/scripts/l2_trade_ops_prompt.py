#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""l2_trade_ops_prompt.py — 6-TRADING 侧 l2.app.trade_ops 运行时薄封装（SPEC-57 §8 P6）

接入点：Screen 2 / Gate C / Process D 的 LLM 出口（deepseek_analyst.py）。
职责边界：
  - TRIGGER_PROMPTS.md 正文仍由 CronCreate 宿主消费，本模块**不复制**文档正文；
  - 这里只做注入（宪法 + 人格）、出口 meta 台账、出口宪法门禁三件事；
  - 全部 FAIL-OPEN：57 运行时不可用时按原 SYSTEM_BASE 继续，不阻断交易分析。

台账：6-TRADING/data/l2_prompt_runtime.jsonl（append-only，与业务输出解耦）。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

PROMPT_ID = "l2.app.trade_ops"
_HERE = Path(__file__).resolve().parent
_RUNTIME = _HERE.parents[1] / "57-Agent提示词工程" / "runtime"
LEDGER = _HERE.parent / "data" / "l2_prompt_runtime.jsonl"

if str(_RUNTIME) not in sys.path:
    sys.path.insert(0, str(_RUNTIME))

_IMPORT_ERROR = ""


def _bridge():
    try:
        import l2_prompt_bridge

        return l2_prompt_bridge
    except Exception as exc:  # noqa: BLE001 — 57 不可用不得阻断交易分析
        global _IMPORT_ERROR
        _IMPORT_ERROR = f"{type(exc).__name__}: {exc}"
        return None


def system_prompt(
    base: str, task: str, tools: Iterable[str] = ()
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """返回 (system_prompt, meta)。注入失败时原样返回 base、meta=None。"""
    bridge = _bridge()
    if bridge is None:
        return base, None
    rendered = bridge.render(
        PROMPT_ID,
        variables={"task": task},
        tools=tools,
        include_asset=False,
    )
    if not rendered.get("injected"):
        return base, rendered.get("meta")
    return f"{base}\n\n{rendered['constitution_block']}", rendered.get("meta")


def gate_output(task: str, payload: Any, *, evidence: Optional[str] = "none") -> Dict[str, Any]:
    bridge = _bridge()
    if bridge is None:
        return {"verdict": "unknown", "error": _IMPORT_ERROR, "ok": False}
    return bridge.gate(PROMPT_ID, payload, evidence=evidence, context={"task": task})


def finalize_output(task: str, payload: Any, *, evidence: Optional[str] = "none") -> Any:
    """出口门禁 + 台账；返回 payload 本体（不改业务字段）。"""
    meta: Optional[Dict[str, Any]] = None
    result: Dict[str, Any] = {"verdict": "unknown"}
    try:
        bridge = _bridge()
        if bridge is not None:
            meta = bridge.render(PROMPT_ID, tools=(), include_asset=False).get("meta")
        result = gate_output(task, payload, evidence=evidence)
    except Exception as exc:  # noqa: BLE001
        result = {"verdict": "unknown", "error": f"{type(exc).__name__}: {exc}", "ok": False}
    _record(task, meta, result)
    return payload


def _record(task: str, meta: Optional[Dict[str, Any]], result: Dict[str, Any]) -> None:
    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "prompt_id": PROMPT_ID,
        "task": task,
        "meta": meta,
        "gate": {
            "verdict": result.get("verdict"),
            "violations": [v.get("code") for v in result.get("violations") or []],
            "error": result.get("error"),
        },
    }
    try:
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with LEDGER.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:  # 台账失败只提示，不影响分析
        print(f"[l2] 台账写入失败（FAIL-OPEN）: {exc}", file=sys.stderr)
        return
    print(
        f"[l2] {PROMPT_ID}@{((meta or {}).get('prompt_version') or '?')} "
        f"task={task} gate={result.get('verdict')}",
        file=sys.stderr,
    )


def main() -> int:
    """CLI：verify / render / gate（排障与验收用）。"""
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["verify", "render", "gate"])
    ap.add_argument("--task", default="a1")
    ap.add_argument("--output", default="")
    args = ap.parse_args()

    bridge = _bridge()
    if bridge is None:
        print(json.dumps({"error": _IMPORT_ERROR}, ensure_ascii=False))
        return 1
    if args.cmd == "verify":
        print(json.dumps(bridge.verify(PROMPT_ID), ensure_ascii=False, indent=2))
    elif args.cmd == "render":
        print(json.dumps(system_prompt("", args.task), ensure_ascii=False, indent=2))
    else:
        payload = json.loads(Path(args.output).read_text(encoding="utf-8")) if args.output else {}
        print(json.dumps(gate_output(args.task, payload), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
