# -*- coding: utf-8 -*-
"""training_event_join.py — 三端 TrainingEvent 统一 join（GAP-7 P1）。

职责：
  1. `join_execution`: 把 40 域 execution_trades.jsonl 按 标的+时间窗 关联回填到 TrainingEvent 的 execution/pnl 字段；
  2. `join_stats`: 输出 join 覆盖率统计（join_coverage / n_complete / n_incomplete）；
  3. `main`: CLI 入口，支持 --dry-run（只统计不写回）。

落盘：回填后的事件写回 `48-涌现架构/events/training_events/train_50_decisions.jsonl`（幂等：已有 execution 数据的事件跳过）。
纪律：FAIL-OPEN（IO/解析异常降级返回，不中断主链）；不写 40/23/50。
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2] if len(Path(__file__).resolve().parents) > 2 else Path(".")
EVENTS_PATH = _REPO_ROOT / "48-涌现架构" / "events" / "training_events" / "train_50_decisions.jsonl"
EXEC_PATH = _REPO_ROOT / "40-周期神经网络系统" / "execution_trades.jsonl"

# 时间窗：决策时间 ± 3 天内视为同一意图
WINDOW_DAYS = 3


def _parse_ts(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _norm_symbol(sym: Optional[str]) -> Optional[str]:
    """归一化标的：BTC/USDT / BTC-USDT-SWAP / BTCUSDT → BTC"""
    if not sym or sym == "MULTI":
        return None
    s = sym.upper().replace("/", "-").replace("_", "-")
    for sep in ("-USDT-SWAP", "-USDT", "USDT"):
        if s.endswith(sep):
            return s[: -len(sep)] if s != sep else s
    return s


def load_executions(path: Path = EXEC_PATH) -> List[Dict[str, Any]]:
    """加载 40 域执行数据，返回 [(symbol, dt, record)]"""
    out: List[Dict[str, Any]] = []
    if not path.exists():
        logger.warning("execution_trades 不存在: %s", path)
        return out
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            intent = rec.get("intent") or {}
            sym = _norm_symbol(intent.get("symbol"))
            dt = _parse_ts(rec.get("intent_date")) or _parse_ts(rec.get("ts"))
            if sym and dt:
                out.append({"symbol": sym, "dt": dt, "record": rec})
    except OSError as exc:
        logger.warning("读取 execution_trades 失败（降级）: %s", exc)
    return out


def _match_event(ev: Dict[str, Any], execs: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """按 标的+时间窗 匹配执行记录"""
    sym = _norm_symbol(ev.get("symbol"))
    ts = _parse_ts(ev.get("ts"))
    if not sym or not ts:
        return None
    window = timedelta(days=WINDOW_DAYS)
    best = None
    best_delta = None
    for e in execs:
        if e["symbol"] != sym:
            continue
        delta = abs((e["dt"] - ts).total_seconds())
        if delta <= window.total_seconds():
            if best_delta is None or delta < best_delta:
                best_delta = delta
                best = e["record"]
    return best


def _extract_execution(rec: Dict[str, Any]) -> Dict[str, Any]:
    """从 40 域记录提取 execution/pnl 字段"""
    intent = rec.get("intent") or {}
    return {
        "outcome": "order_placed" if rec.get("order_placed") else "intent_only",
        "order_id": None,
        "fill": rec.get("fill"),
        "exit": rec.get("exit"),
        "source": "40-execution_trades",
        "intent_symbol": intent.get("symbol"),
        "intent_direction": intent.get("direction"),
        "intent_date": rec.get("intent_date"),
    }


def _extract_pnl(rec: Dict[str, Any]) -> Dict[str, Any]:
    pnl = rec.get("pnl")
    return {"value": pnl} if pnl is not None else {}


def join_execution(
    events_path: Path = EVENTS_PATH,
    exec_path: Path = EXEC_PATH,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """执行 join 并回填，返回统计。幂等：已有 execution.outcome 的事件跳过。"""
    stats = {
        "n_events": 0,
        "n_already_complete": 0,
        "n_matched": 0,
        "n_unmatched": 0,
        "n_multi_symbol_skipped": 0,
        "error": 0,
    }
    if not events_path.exists():
        logger.warning("events 文件不存在: %s", events_path)
        return stats
    execs = load_executions(exec_path)
    stats["n_exec_records"] = len(execs)

    lines_out: List[str] = []
    try:
        raw = events_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        logger.warning("读取 events 失败（降级）: %s", exc)
        return stats

    for line in raw:
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            lines_out.append(line)
            stats["error"] += 1
            continue
        stats["n_events"] += 1
        execution = ev.get("execution") or {}
        if execution.get("outcome") or execution.get("order_id") or execution.get("fill"):
            stats["n_already_complete"] += 1
            lines_out.append(json.dumps(ev, ensure_ascii=False))
            continue
        if ev.get("symbol") == "MULTI":
            stats["n_multi_symbol_skipped"] += 1
            lines_out.append(json.dumps(ev, ensure_ascii=False))
            continue
        matched = _match_event(ev, execs)
        if matched:
            ev["execution"] = _extract_execution(matched)
            pnl = _extract_pnl(matched)
            if pnl:
                ev["pnl"] = pnl
            stats["n_matched"] += 1
        else:
            stats["n_unmatched"] += 1
        lines_out.append(json.dumps(ev, ensure_ascii=False))

    n = max(stats["n_events"], 1)
    stats["join_coverage"] = round(
        (stats["n_matched"] + stats["n_already_complete"]) / n, 4
    )

    if not dry_run and stats["n_matched"] > 0:
        try:
            events_path.write_text("\n".join(lines_out) + "\n", encoding="utf-8")
        except OSError as exc:
            logger.warning("写回 events 失败（降级）: %s", exc)
            stats["write_error"] = str(exc)
    return stats


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="三端 TrainingEvent 统一 join")
    parser.add_argument("--dry-run", action="store_true", help="只统计不写回")
    args = parser.parse_args(argv)
    stats = join_execution(dry_run=args.dry_run)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(main())
