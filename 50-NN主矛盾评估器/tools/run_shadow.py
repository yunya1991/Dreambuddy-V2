#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""50 shadow 决策调度入口（shadow 接入 crontab）。

读取 42 总线最新快照 → 50 shadow 决策 → 落盘 runtime/shadow/。
shadow 模式只产出审计信号，不执行任何交易。

行为（fail-open）：
- 50_KILL_SWITCH=1：跳过决策，记录 skipped 后正常退出
- 总线无信号：记录 no_evidences 后正常退出
- 决策结果原子写 runtime/shadow/latest.json；摘要追加 shadow_history.jsonl（滚动上限 500）

用法：python3 tools/run_shadow.py [--bus-state PATH] [--out-dir PATH]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_50_ROOT = _REPO_ROOT / "50-NN主矛盾评估器"
_42_ROOT = _REPO_ROOT / "42-神经网络交易协调层"
if str(_50_ROOT) not in sys.path:
    sys.path.insert(0, str(_50_ROOT))

from adapters.bus_reader import load_evidences  # noqa: E402
from adapters.constraint_loader import load_constraints  # noqa: E402
from adapters.execution_writer import is_kill_switch_on  # noqa: E402
from core.shadow_decision import make_shadow_decision  # noqa: E402

SHADOW_HISTORY_CAP = 500
DEFAULT_BUS_STATE = _42_ROOT / "runtime" / "bus_state.json"
DEFAULT_OUT_DIR = _50_ROOT / "runtime" / "shadow"


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, 0o664)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _append_history(path: Path, record: dict[str, Any], cap: int = SHADOW_HISTORY_CAP) -> None:
    lines: list[str] = []
    if path.exists():
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    lines.append(json.dumps(record, ensure_ascii=False))
    _atomic_write_text(path, "\n".join(lines[-cap:]) + "\n")


def run(bus_state: Path, out_dir: Path) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    run_ts = now.isoformat().replace("+00:00", "Z")
    result: dict[str, Any] = {"run_ts": run_ts, "status": "ok", "reason": None}

    if is_kill_switch_on():
        result["status"] = "skipped"
        result["reason"] = "50_KILL_SWITCH=1（kill switch 开启，跳过 shadow 决策）"
        return result

    evidences = load_evidences(str(bus_state))
    result["evidence_count"] = len(evidences)
    if not evidences:
        result["status"] = "skipped"
        result["reason"] = "no_evidences（42 总线无信号，fail-open 跳过）"
        return result

    constraints = load_constraints()
    decision = make_shadow_decision(evidences, constraints, now=now)
    result["decision"] = decision
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="50 shadow 决策调度入口")
    parser.add_argument("--bus-state", default=str(DEFAULT_BUS_STATE), help="42 bus_state.json 路径")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="shadow 结果输出目录")
    args = parser.parse_args()

    result = run(Path(args.bus_state), Path(args.out_dir))

    out_dir = Path(args.out_dir)
    _atomic_write_json(out_dir / "latest.json", result)

    summary: dict[str, Any] = {
        "run_ts": result["run_ts"],
        "status": result["status"],
        "reason": result.get("reason"),
        "evidence_count": result.get("evidence_count"),
    }
    decision = result.get("decision")
    if isinstance(decision, dict):
        payload = decision.get("payload") if isinstance(decision.get("payload"), dict) else {}
        summary.update(
            {
                "signal_id": decision.get("signal_id"),
                "direction": decision.get("direction"),
                "confidence": decision.get("confidence"),
                "position_pct": payload.get("position_pct"),
            }
        )
    _append_history(out_dir / "shadow_history.jsonl", summary)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
