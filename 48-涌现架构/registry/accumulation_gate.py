"""accumulation_gate.py — 积累类实验达标自动放行开关（E1 / E4b cascade）。
判据（与 SPEC v0.5 §4 对齐）：
  E1: shadow 事件积累 ≥7 个自然日 且 非预设联动动作 ≥1 次（M1 actions>0）
  E4b cascade: 点火事件 ≥ MIN_EVENTS(20)（脱离 insufficient_data）
达标后写放行 flag 文件（幂等，已存在不重写）；未达标静默返回继续积累。
FAIL-OPEN：任何异常不抛出，退出码恒为 0。
用法：python accumulation_gate.py [--json]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "48-涌现架构" / "bus"))
sys.path.insert(0, str(_REPO_ROOT / "48-涌现架构" / "metrics"))

from m1_linkage import compute_m1, DEFAULT_EVENTS_DIR  # noqa: E402
from e4b_cascade import compute_cascade  # noqa: E402

logger = logging.getLogger("accumulation_gate")
GATES_DIR = _REPO_ROOT / "48-涌现架构" / "events" / "gates"
E1_FLAG = GATES_DIR / "E1_ACCUMULATION_RELEASED"
E4B_FLAG = GATES_DIR / "E4B_CASCADE_RELEASED"
E1_MIN_DAYS = 7


def _distinct_days(events_dir: Path) -> int:
    """统计 bus_*.jsonl 覆盖的不同自然日数。"""
    days = set()
    if events_dir.is_dir():
        for f in events_dir.glob("bus_*.jsonl"):
            stem = f.stem.replace("bus_", "")
            if len(stem) == 8 and stem.isdigit():
                days.add(stem)
    return len(days)


def check_e1() -> dict:
    m1 = compute_m1()
    days = _distinct_days(DEFAULT_EVENTS_DIR)
    actions = int(m1.get("actions", 0))
    days_ok = days >= E1_MIN_DAYS
    action_ok = actions >= 1
    released = E1_FLAG.exists()
    if days_ok and action_ok and not released:
        try:
            GATES_DIR.mkdir(parents=True, exist_ok=True)
            E1_FLAG.write_text(
                json.dumps(
                    {
                        "released_at": datetime.now(timezone.utc).isoformat(),
                        "distinct_days": days,
                        "m1_actions": actions,
                        "m1": m1,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            released = True
            logger.info("E1 积累达标，已写放行 flag: %s", E1_FLAG)
        except Exception as exc:  # noqa: BLE001
            logger.warning("E1 flag 写入失败（FAIL-OPEN）: %s", exc)
    return {
        "gate": "E1",
        "distinct_days": days,
        "min_days": E1_MIN_DAYS,
        "days_ok": days_ok,
        "m1_actions": actions,
        "action_ok": action_ok,
        "released": released,
        "criteria": "days>=7 AND actions>=1",
    }


def check_e4b() -> dict:
    res = compute_cascade()
    value = res.get("value") or {}
    n_events = int(value.get("n_events", 0))
    status = res.get("status", "no_data")
    events_ok = status == "ok" and n_events >= 20
    released = E4B_FLAG.exists()
    if events_ok and not released:
        try:
            GATES_DIR.mkdir(parents=True, exist_ok=True)
            E4B_FLAG.write_text(
                json.dumps(
                    {
                        "released_at": datetime.now(timezone.utc).isoformat(),
                        "n_events": n_events,
                        "cascade": value,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            released = True
            logger.info("E4b cascade 积累达标，已写放行 flag: %s", E4B_FLAG)
        except Exception as exc:  # noqa: BLE001
            logger.warning("E4b flag 写入失败（FAIL-OPEN）: %s", exc)
    return {
        "gate": "E4b_cascade",
        "n_events": n_events,
        "status": status,
        "events_ok": events_ok,
        "released": released,
        "criteria": "n_events>=20 (status=ok)",
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="积累类实验达标自动放行开关")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    args = parser.parse_args()
    try:
        result = {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "e1": check_e1(),
            "e4b_cascade": check_e4b(),
        }
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        result = {"checked_at": datetime.now(timezone.utc).isoformat(), "error": str(exc)}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        e1, e4b = result.get("e1", {}), result.get("e4b_cascade", {})
        logger.info(
            "E1: days=%s/%s actions=%s released=%s | E4b: n_events=%s status=%s released=%s",
            e1.get("distinct_days"), e1.get("min_days"), e1.get("m1_actions"), e1.get("released"),
            e4b.get("n_events"), e4b.get("status"), e4b.get("released"),
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
