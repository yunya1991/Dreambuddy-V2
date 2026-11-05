"""replay_decisions.py — polling_trader 决策回放器（SPEC-EMERGENCE-EVOLUTION v0.5 E0b 前置）。

设计约束：
  - shadow 性质：只读既有日志/数据库，零实盘触发，不 import polling_trader；
  - FAIL-OPEN：任何数据源缺失/损坏静默跳过，不阻断；
  - 合并 E4a 埋点：认知召回相关事件落盘 events/memory_readout/，readout_rate 可算。

数据源（2026-11-05 实测）：
  - 主源 A：data/polling_trader/trader_YYYYMMDD.jsonl（文本日志 ts/level/msg，决策事件需正则提取）
  - 主源 B：data/polling_trader/s4_eval_log.jsonl（cycle 级结构化快照：positions/top1_coin/triggered/reason）
  - 辅源 C：scripts/data/bcrm_trades.db（trades 表，成交明细 join）

输出：
  - 48-涌现架构/experiments/replay/replay_YYYYMMDD.jsonl（决策级回放记录）
  - 48-涌现架构/experiments/replay/memory_readout.jsonl（recall 事件，E4a 埋点）
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parents[3]
_TRADER_DIR = _REPO_ROOT / "11-易经推理系统" / "data" / "polling_trader"
_TRADES_DB = _REPO_ROOT / "11-易经推理系统" / "scripts" / "data" / "bcrm_trades.db"
_OUT_DIR = _REPO_ROOT / "48-涌现架构" / "experiments" / "replay"

# 决策事件提取模式（msg 文本 → 结构化）
_DECISION_PATTERNS = [
    ("open_attempt", re.compile(r"\[(?P<coin>[A-Z0-9]+)\].*开仓")),
    ("close_executed", re.compile(r"\[(?P<coin>[A-Z0-9]+)\].*平仓")),
    ("signal_switch", re.compile(r"换仓信号: (?P<coin>[A-Z0-9]+)")),
    ("cooldown_block", re.compile(r"(?P<coin>[A-Z0-9]+) evolution 冷静期拦截")),
    ("confidence_penalty", re.compile(r"\[(?P<coin>[A-Z0-9]+)\] P0卦象一致性惩罚")),
]
_RECALL_PATTERN = re.compile(r"认知召回|cognitive_recall|_inject_cognitive_recall")


def _parse_ts(ts: str) -> Optional[datetime]:
    try:
        return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return None


def extract_decision_events(log_path: Path) -> List[Dict[str, Any]]:
    """从文本交易日志提取结构化决策事件。FAIL-OPEN：损坏行跳过。"""
    events: List[Dict[str, Any]] = []
    try:
        with log_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = str(rec.get("msg", ""))
                _parse_ts(rec.get("ts", ""))
                matched = False
                for kind, pat in _DECISION_PATTERNS:
                    m = pat.search(msg)
                    if m:
                        events.append(
                            {
                                "ts": rec.get("ts"),
                                "kind": kind,
                                "coin": m.groupdict().get("coin", ""),
                                "level": rec.get("level", "INFO"),
                                "msg_head": msg[:160],
                            }
                        )
                        matched = True
                        break
                if not matched and _RECALL_PATTERN.search(msg):
                    events.append(
                        {
                            "ts": rec.get("ts"),
                            "kind": "cognitive_recall",
                            "coin": "",
                            "level": rec.get("level", "INFO"),
                            "msg_head": msg[:160],
                        }
                    )
    except Exception:  # noqa: BLE001 — FAIL-OPEN
        pass
    return events


def load_cycle_snapshots(s4_path: Path) -> List[Dict[str, Any]]:
    """加载 s4_eval_log cycle 级快照（结构化，直接可用）。"""
    snaps: List[Dict[str, Any]] = []
    try:
        with s4_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    snaps.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception:  # noqa: BLE001
        pass
    return snaps


def load_trades(db_path: Path = _TRADES_DB) -> List[Dict[str, Any]]:
    """加载成交明细（辅源，join 用）。FAIL-OPEN：库缺失返回空。"""
    trades: List[Dict[str, Any]] = []
    if not db_path.exists():
        return trades
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        for row in conn.execute(
            "SELECT symbol, direction, entry_time, exit_time, entry_price, "
            "exit_price, pnl_pct, hold_bars, exit_reason, confidence FROM trades"
        ):
            trades.append(dict(row))
        conn.close()
    except Exception:  # noqa: BLE001
        pass
    return trades


def replay(day: str, *, out_dir: Path = _OUT_DIR) -> Dict[str, Any]:
    """重放指定日期（YYYYMMDD）的决策链，输出结构化回放记录。

    返回统计 {decision_events, recall_events, cycles, trades}。
    """
    log_path = _TRADER_DIR / f"trader_{day}.jsonl"
    s4_path = _TRADER_DIR / "s4_eval_log.jsonl"
    out_dir.mkdir(parents=True, exist_ok=True)

    events = extract_decision_events(log_path)
    recall_events = [e for e in events if e["kind"] == "cognitive_recall"]
    decision_events = [e for e in events if e["kind"] != "cognitive_recall"]

    # E4a 埋点：recall 事件落盘（readout_rate 数据源）
    if recall_events:
        with (out_dir / "memory_readout.jsonl").open("a", encoding="utf-8") as fh:
            for e in recall_events:
                fh.write(json.dumps({"day": day, **e}, ensure_ascii=False) + "\n")

    # cycle 快照按日过滤
    cycles = [
        s
        for s in load_cycle_snapshots(s4_path)
        if str(s.get("ts", "")).startswith("-".join([day[:4], day[4:6], day[6:]]))
    ]

    record = {
        "day": day,
        "generated_at": datetime.now().isoformat(),
        "stats": {
            "decision_events": len(decision_events),
            "recall_events": len(recall_events),
            "cycles": len(cycles),
            "trades": len(load_trades()),
        },
        "decision_events": decision_events,
        "cycle_snapshots": cycles,
    }
    out_path = out_dir / f"replay_{day}.jsonl"
    with out_path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record["stats"]


def main() -> int:
    import sys

    day = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y%m%d")
    stats = replay(day)
    print(f"replay {day}: {stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
