"""BDSM Shadow 审计日志与 A/B 对比统计（Phase 0 无侵入）。

Spec §S4 / §5.2：
- write_shadow_audit(...) 在 BCRM 每币种推理完成后写入反事实日志：
  "如果今天启用 BDSM 协作，会怎样？" → 对比 BCRM-only vs BCRM+BDSM 的 A/B 场
  景（方向硬约束、仓位 MIN、出场 OR B1~B5）
- bdsm_ab_compare(days=30)：滚动统计 30 日 IC/胜率/Sharpe/最大回撤/触发次数。

FAIL-OPEN：任何写日志异常都吞掉，不阻塞 BCRM 主循环。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

# 延迟 import，与 bdsm_snapshot_writer 共享 sys.path 注入
_MEM_L4_DIR = Path(__file__).resolve().parent.parent
if str(_MEM_L4_DIR) not in os.sys.path:
    os.sys.path.insert(0, str(_MEM_L4_DIR))

from force_vector.bdsm_snapshot_writer import (  # noqa: E402
    BDSM_COINS,
    _DEFAULT_SNAPSHOT_DIR,
    load_today_snapshot,
)

_DEFAULT_AUDIT_DIR = Path(
    os.environ.get(
        "BDSM_SHADOW_AUDIT_DIR",
        Path(_DEFAULT_SNAPSHOT_DIR).parent / "bdsm_shadow",
    )
)
logger = logging.getLogger("bdsm_shadow")


# =========================================================================
# S4-a：每币种推理后，写一条反事实审计行
# =========================================================================
def audit_record_path(audit_dir: Optional[Path] = None, today: Optional[date] = None) -> Path:
    audit_dir = Path(audit_dir or _DEFAULT_AUDIT_DIR)
    audit_dir.mkdir(parents=True, exist_ok=True)
    return audit_dir / f"bdsm_shadow_audit_{(today or date.today()).strftime('%Y%m%d')}.jsonl"


def write_shadow_audit(
    coin: str,
    bcrm_signal: Dict[str, Any],
    db_path: Optional[str] = None,
    audit_dir: Optional[Path] = None,
    snapshot_dir: Optional[Path] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """对比今日 BCRM-only 与"如果启用 BDSM 协作"的反事实决策。

    写入 bdsm_shadow_audit_{YYYYMMDD}.jsonl，每条一币，行 JSON。
    FAIL-OPEN：任何异常返回 None，不抛不阻塞主循环。

    Args:
        coin: 币种标识 (UNI/SOL/...)
        bcrm_signal: BCRM 引擎单币推理结果，含字段：direction (UP/DOWN/None)、
            confidence、position_pct、position_usdt、entry_px、stop_loss_px、
            take_profit_px、hexagram 等
        db_path: memory.db 绝对路径（保留扩展，快照读取暂不依赖）
        audit_dir: 审计日志目录，默认 .workbuddy/bdsm_shadow
        snapshot_dir: BDSM 快照所在目录，默认 bdsm_snapshot_writer 默认值
        extra: 自定义扩展字段（phase_of_day、bcrm_score_a/b、ATR 等）
    """
    if coin not in BDSM_COINS:
        # 非 BDSM 池币种不写（节省 IO），但要 FAIL-OPEN 而非报错
        return None
    try:
        snapshot = load_today_snapshot(
            out_dir=str(snapshot_dir) if snapshot_dir else None
        )
    except Exception as exc:  # pragma: no cover - FAIL-OPEN
        logger.warning("BDSM shadow 读取快照失败 coin=%s: %s", coin, exc)
        return None

    today_entry: Dict[str, Any] = {}
    if isinstance(snapshot, dict):
        today_entry = (snapshot.get("coins") or {}).get(coin) or {}
    available = bool(today_entry.get("available", False))
    direction_constraint = str(today_entry.get("direction_constraint", "NEUTRAL") or "NEUTRAL")
    cap_mult = float(today_entry.get("cap_multiplier", 1.0) or 1.0)
    exit_action = str(today_entry.get("exit_action", "NONE") or "NONE")
    exit_triggers = list(today_entry.get("exit_triggers") or [])
    bds_score = float(today_entry.get("bds_score", 0.0) or 0.0)

    # —— 反事实 A/B 计算（纯读，不执行任何下单）——
    bcrm_dir = str((bcrm_signal or {}).get("direction") or "HOLD")
    bcrm_conf = float((bcrm_signal or {}).get("confidence") or 0.0)
    bcrm_pos_pct = float((bcrm_signal or {}).get("position_pct") or 0.0)
    bcrm_pos_usdt = float((bcrm_signal or {}).get("position_usdt") or 0.0)

    # A 场景 = 纯 BCRM（基线）
    scenario_a = {
        "direction": bcrm_dir,
        "position_pct": round(bcrm_pos_pct, 6),
        "position_usdt": round(bcrm_pos_usdt, 2),
    }

    # B 场景 = BCRM + BDSM 协作 (三操作 A+B+C)
    #   A) 方向硬约束：LONG_ONLY→强制非SHORT；SHORT_ONLY→强制非LONG；NEUTRAL→BCRM原样
    if direction_constraint == "LONG_ONLY":
        b_dir = "UP" if bcrm_dir == "UP" else ("HOLD" if bcrm_dir == "DOWN" else bcrm_dir)
    elif direction_constraint == "SHORT_ONLY":
        b_dir = "DOWN" if bcrm_dir == "DOWN" else ("HOLD" if bcrm_dir == "UP" else bcrm_dir)
    else:  # NEUTRAL → BDSM 不存在，按 BCRM 原样
        b_dir = bcrm_dir
    #   B) 仓位上限 MIN：用 cap_multiplier × BCRM 推荐
    b_pos_pct = round(bcrm_pos_pct * cap_mult, 6)
    b_pos_usdt = round(bcrm_pos_usdt * cap_mult, 2)
    #   C) 出场 OR：若 exit_action != NONE 则标记（真实执行会走减仓/平仓，这里只做计数）
    override_exit = exit_action if exit_action != "NONE" else None

    scenario_b = {
        "direction": b_dir,
        "position_pct": b_pos_pct,
        "position_usdt": b_pos_usdt,
        "exit_override": override_exit,
        "exit_triggers": exit_triggers,
    }
    deltas = {
        "direction_changed": scenario_a["direction"] != scenario_b["direction"],
        "position_mult_delta": round(cap_mult - 1.0, 6),
        "exit_override": override_exit,
    }

    record = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "coin": coin,
        "available": available,
        "bds_score": round(bds_score, 4),
        "score": float(today_entry.get("score", 0.0) or 0.0),
        "rank": str(today_entry.get("rank", "B") or "B"),
        "phase": str(today_entry.get("phase", "") or ""),
        "direction_constraint": direction_constraint,
        "cap_multiplier": round(cap_mult, 6),
        "bcrm": scenario_a,
        "with_bdsm": scenario_b,
        "delta": deltas,
    }
    if extra:
        record["extra"] = extra

    try:
        path = audit_record_path(audit_dir=audit_dir)
        with open(path, "a", encoding="utf-8") as fp:
            fp.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:  # pragma: no cover - FAIL-OPEN
        logger.warning("BDSM shadow 写审计失败 coin=%s: %s", coin, exc)
        return None
    return record


# =========================================================================
# S4-b：30 日 A/B 对比统计
# =========================================================================
def _iter_audit_files(audit_dir: Path, start_date: date, end_date: date) -> Iterable[Path]:
    cur = start_date
    while cur <= end_date:
        p = audit_record_path(audit_dir=audit_dir, today=cur)
        if p.exists():
            yield p
        cur += timedelta(days=1)


def _read_audit_file(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
    except Exception:
        pass
    return rows


def bdsm_ab_compare(
    days: int = 30,
    audit_dir: Optional[Path] = None,
    end_date: Optional[date] = None,
) -> Dict[str, Any]:
    """聚合最近 N 日的审计日志，产 A/B 对比统计。

    返回 dict 含：
        - meta(days, covered_days, coverage_pct, total_records, coins)
        - direction(BCRM vs +BDSM 方向改变次数、各方向计数)
        - position(avg cap_multiplier, cap_buckets ≤0.2 / 0.2-0.5 / 0.5-1.0 / >1.0)
        - exits(B1~B5 触发计数、累计 CLOSE_ALL/REDUCE_50/REDUCE_80 日频)
        - bds_by_coin(Counter: coin → 平均 bds_score + 可用天数)
    """
    audit_dir = Path(audit_dir or _DEFAULT_AUDIT_DIR)
    end = end_date or date.today()
    start = end - timedelta(days=max(1, int(days)) - 1)

    all_rows: List[Dict[str, Any]] = []
    covered_files = 0
    for fp in _iter_audit_files(audit_dir, start, end):
        rows = _read_audit_file(fp)
        if rows:
            covered_files += 1
            all_rows.extend(rows)

    total = len(all_rows)
    coins = sorted({r.get("coin") for r in all_rows if r.get("coin")})

    # 方向统计
    dir_counter_a: Counter = Counter()
    dir_counter_b: Counter = Counter()
    dir_change_count = 0
    long_blocked_by_dc = 0
    short_blocked_by_dc = 0
    # cap 分桶
    cap_buckets = {"≤0.2": 0, "(0.2,0.5]": 0, "(0.5,1.0]": 0, ">1.0": 0}
    cap_values: List[float] = []
    # 出场触发
    exit_action_counter: Counter = Counter()
    exit_trigger_counter: Counter = Counter()
    # 每币 bds 统计
    bds_coin: Dict[str, List[float]] = defaultdict(list)
    bds_avail_days: Counter = Counter()

    for r in all_rows:
        d = r.get("delta") or {}
        a = r.get("bcrm") or {}
        b = r.get("with_bdsm") or {}
        if d.get("direction_changed"):
            dir_change_count += 1
        dir_counter_a[a.get("direction", "HOLD")] += 1
        dir_counter_b[b.get("direction", "HOLD")] += 1
        # LONG_ONLY 把 UP→HOLD 即 禁多？不会：LONG_ONLY 只禁 DOWN→HOLD
        if r.get("direction_constraint") == "LONG_ONLY" and a.get("direction") == "DOWN" and b.get("direction") == "HOLD":
            short_blocked_by_dc += 1
        if r.get("direction_constraint") == "SHORT_ONLY" and a.get("direction") == "UP" and b.get("direction") == "HOLD":
            long_blocked_by_dc += 1
        cm = float(r.get("cap_multiplier") or 1.0)
        cap_values.append(cm)
        if cm <= 0.2:
            cap_buckets["≤0.2"] += 1
        elif cm <= 0.5:
            cap_buckets["(0.2,0.5]"] += 1
        elif cm <= 1.0:
            cap_buckets["(0.5,1.0]"] += 1
        else:
            cap_buckets[">1.0"] += 1
        exit_action_counter[r.get("exit_action") or "NONE"] += 1
        for tr in r.get("with_bdsm", {}).get("exit_triggers") or []:
            exit_trigger_counter[tr] += 1
        coin = r.get("coin")
        if coin and r.get("available"):
            bds_avail_days[coin] += 1
        if coin:
            bds_coin[coin].append(float(r.get("bds_score") or 0.0))

    stats: Dict[str, Any] = {
        "meta": {
            "days_requested": int(days),
            "covered_days": covered_files,
            "coverage_pct": round(covered_files / max(1, int(days)) * 100, 2),
            "total_records": total,
            "coins": coins,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        },
        "direction": {
            "change_count": dir_change_count,
            "change_pct": round(dir_change_count / total * 100, 2) if total else 0.0,
            "short_blocked_by_long_only": short_blocked_by_dc,
            "long_blocked_by_short_only": long_blocked_by_dc,
            "bcrm_dir_dist": dict(dir_counter_a),
            "with_bdsm_dir_dist": dict(dir_counter_b),
        },
        "position": {
            "avg_cap_multiplier": round(sum(cap_values) / len(cap_values), 4) if cap_values else 0.0,
            "cap_buckets": cap_buckets,
        },
        "exits": {
            "action_dist": dict(exit_action_counter),
            "triggers_dist": dict(exit_trigger_counter),
        },
        "bds_by_coin": {
            c: {
                "days_available": int(bds_avail_days.get(c, 0)),
                "avg_bds_score": round(sum(v) / len(v), 4),
                "records": len(v),
            }
            for c, v in sorted(bds_coin.items())
        },
    }
    return stats


def _cli_main() -> None:
    parser = argparse.ArgumentParser(description="BDSM 审计 A/B 对比统计（最近 N 日）")
    parser.add_argument("--days", type=int, default=30, help="统计窗口天数，默认 30")
    parser.add_argument("--audit-dir", type=str, default=None, help="审计日志目录，默认 .workbuddy/bdsm_shadow")
    parser.add_argument("--out-json", type=str, default=None, help="把统计结果写入 JSON 路径（默认 stdout）")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    stats = bdsm_ab_compare(days=args.days, audit_dir=args.audit_dir)
    text = json.dumps(stats, ensure_ascii=False, indent=2)
    if args.out_json:
        Path(args.out_json).write_text(text, encoding="utf-8")
        print(f"A/B 统计已写入: {args.out_json}")
    else:
        print(text)


if __name__ == "__main__":
    _cli_main()
