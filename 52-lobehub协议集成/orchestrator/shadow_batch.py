"""Phase 4 shadow 批量跑（定时任务入口）。

用途：按日跑固定意图清单，持续累积 decisions trace，供 T1-T4 命中率与
heuristic/grounded 一致率（R7 A/B）统计。不执行任何 DreamOS 链路。

前置：side-A（3.1 前端）与 side-B（DreamOS API）均在线；任一离线则整体跳过，
不消耗 LLM 调用（定时任务在深夜跑，服务未启动时应静默退出）。

用法：
    python3 shadow_batch.py                 # 跑默认清单
    python3 shadow_batch.py --max 3         # 只跑前 3 条
    python3 shadow_batch.py --dry-run       # 只打印将跑的意图
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_INTENTS = HERE / "shadow_intents.txt"
DEFAULT_LOG = HERE / "logs" / "shadow_batch.jsonl"
ORCHESTRATOR = HERE / "brainstorm_orchestrator.py"

SIDE_A_URL = os.environ.get("SIDE_A_URL", "http://127.0.0.1:3001")
SIDE_B_URL = os.environ.get("SIDE_B_URL", "http://127.0.0.1:8000")


def _alive(url: str, timeout: float = 4.0) -> bool:
    """任意 HTTP 响应即视为存活（404/405 也算，只判断端口可连）。"""
    try:
        with urllib.request.urlopen(url, timeout=timeout):
            return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


def _load_intents(path: Path) -> list[str]:
    if not path.exists():
        return []
    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            lines.append(line)
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="shadow 批量跑（定时任务入口）")
    parser.add_argument("--intents-file", default=str(DEFAULT_INTENTS))
    parser.add_argument("--log-path", default=str(DEFAULT_LOG))
    parser.add_argument("--max", type=int, default=0, help="最多跑几条，0 表示全部")
    parser.add_argument("--n-per-side", type=int, default=2)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    intents = _load_intents(Path(args.intents_file))
    if args.max > 0:
        intents = intents[: args.max]
    log_path = Path(args.log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    if not intents:
        print(json.dumps({"ok": False, "error": "no_intents"}, ensure_ascii=False))
        return 0

    if args.dry_run:
        print(json.dumps({"ok": True, "dry_run": True, "intents": intents}, ensure_ascii=False))
        return 0

    # 服务未就绪 → 静默跳过，避免深夜定时任务刷错误、浪费额度
    if not (_alive(SIDE_A_URL) and _alive(SIDE_B_URL)):
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "ok": False,
            "skipped": "services_down",
            "side_a": _alive(SIDE_A_URL),
            "side_b": _alive(SIDE_B_URL),
        }
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(json.dumps(record, ensure_ascii=False))
        return 0

    ran = 0
    failed = 0
    for intent in intents:
        cmd = [
            sys.executable,
            str(ORCHESTRATOR),
            "--intent",
            intent,
            "--n-per-side",
            str(args.n_per_side),
            "--json-out",
        ]
        started = time.time()
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            raw = (proc.stdout or "").strip().splitlines()
            summary: dict = {}
            if raw:
                try:
                    summary = json.loads(raw[-1])
                except json.JSONDecodeError:
                    summary = {"ok": False, "error": "bad_json", "raw": raw[-1][:200]}
            else:
                summary = {
                    "ok": False,
                    "error": "empty_stdout",
                    "stderr": (proc.stderr or "")[-200:],
                }
            record = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "intent": intent,
                "elapsed_sec": round(time.time() - started, 1),
                **summary,
            }
            ran += 1
        except subprocess.TimeoutExpired:
            record = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "intent": intent,
                "ok": False,
                "error": "timeout",
            }
            failed += 1
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(
        json.dumps(
            {"ok": True, "ran": ran, "failed": failed, "log": str(log_path)}, ensure_ascii=False
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
