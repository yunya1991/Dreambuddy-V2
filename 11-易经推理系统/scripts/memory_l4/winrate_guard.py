#!/usr/bin/env python3
"""11 域定期回测 / 胜率告警守卫。

两种模式：
  --mode winrate     读取最近 N 天已平仓成交，统计胜率（默认，轻量、每日跑）
  --mode walkforward 运行 1H 5 折 walk-forward 评测，按各币样本数加权胜率（每周跑）

判定：
  n < min_trades           → INSUFFICIENT（不告警，只记录）
  win_rate < 0.50          → ALERT（飞书 warning + 日志）
  0.50 <= win_rate < 0.60  → BELOW_TARGET（飞书 info + 日志）
  win_rate >= 0.60         → OK（只落日志）

产出：
  data/eval/winrate_guard.json
  logs/winrate_guard.log（追加）
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_DB = PROJECT_ROOT / "scripts" / "data" / "bcrm_trades.db"
DEFAULT_JSON = PROJECT_ROOT / "data" / "eval" / "winrate_guard.json"
DEFAULT_LOG = PROJECT_ROOT / "logs" / "winrate_guard.log"


def _parse_ts(value: str):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def collect_db_trades(db_path: Path, days: int) -> list[dict]:
    if not db_path.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT symbol, direction, exit_time, pnl_pct, exit_reason FROM trades "
            "WHERE exit_time IS NOT NULL ORDER BY id DESC"
        ).fetchall()
    finally:
        con.close()
    out = []
    for symbol, direction, exit_time, pnl_pct, reason in rows:
        ts = _parse_ts(exit_time)
        if ts is None or ts < cutoff:
            continue
        try:
            pnl = float(pnl_pct)
        except Exception:
            continue
        out.append(
            {
                "symbol": symbol,
                "direction": direction,
                "exit_time": exit_time,
                "pnl": pnl,
                "reason": reason,
            }
        )
    return out


def summarize(trades: list[dict]) -> dict:
    n = len(trades)
    wins = sum(1 for t in trades if t["pnl"] > 0)
    wr = wins / n if n else 0.0
    return {
        "n": n,
        "wins": wins,
        "win_rate": round(wr, 4),
        "mean_pnl_raw": round(sum(t["pnl"] for t in trades) / n, 6) if n else 0.0,
        "from": trades[-1]["exit_time"] if n else None,
        "to": trades[0]["exit_time"] if n else None,
    }


def run_walkforward(coins: list[str], out_path: Path, max_bars: int, n_folds: int) -> dict:
    script = PROJECT_ROOT / "scripts" / "memory_l4" / "bcrm2" / "eval_1h_walkforward.py"
    cmd = [
        sys.executable,
        str(script),
        "--coins",
        *coins,
        "--max-bars",
        str(max_bars),
        "--n-folds",
        str(n_folds),
        "--out",
        str(out_path),
    ]
    proc = subprocess.run(
        cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=6 * 3600
    )
    if proc.returncode != 0:
        return {"error": f"eval exit={proc.returncode}", "stderr": proc.stderr[-800:]}
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    total_n = 0
    total_wins = 0.0
    per_coin = {}
    for coin, res in (payload.get("results") or {}).items():
        if "error" in res:
            per_coin[coin] = {"error": res["error"]}
            continue
        p = res.get("primary") or {}
        n = int(p.get("n") or 0)
        wr = float(p.get("win_rate") or 0.0)
        per_coin[coin] = {
            "n": n,
            "win_rate": wr,
            "verdict": (res.get("gates") or {}).get("verdict"),
        }
        total_n += n
        total_wins += n * wr
    wr = total_wins / total_n if total_n else 0.0
    return {
        "n": total_n,
        "wins": round(total_wins, 2),
        "win_rate": round(wr, 4),
        "per_coin": per_coin,
        "summary": payload.get("summary"),
        "config_hash": payload.get("config_hash"),
    }


def classify(metrics: dict, min_trades: int, warn_below: float, target: float) -> str:
    if metrics["n"] < min_trades:
        return "INSUFFICIENT"
    wr = metrics["win_rate"]
    if wr < warn_below:
        return "ALERT"
    if wr < target:
        return "BELOW_TARGET"
    return "OK"


def append_log(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def notify(status: str, metrics: dict, mode: str, target: float) -> None:
    if status == "OK" or status == "INSUFFICIENT":
        return
    try:
        from scripts.memory_l4.yijing_feishu_alert import send_alert
    except Exception as exc:  # 飞书模块不可用 → 仅日志
        print(f"[WARN] 飞书模块不可用: {exc}")
        return
    level = "warning" if status == "ALERT" else "info"
    title = "胜率低于 50% 告警" if status == "ALERT" else "胜率低于目标 60%"
    message = (
        f"{title}｜模式={mode} 样本N={metrics['n']} 胜率={metrics['win_rate']:.2%} "
        f"（告警线 50%，目标 {target:.0%}）"
    )
    try:
        send_alert(
            "trading",
            level,
            message,
            details={
                "mode": mode,
                "n": metrics["n"],
                "win_rate": metrics["win_rate"],
                "warn_below": 0.50,
                "target": target,
                "from": metrics.get("from"),
                "to": metrics.get("to"),
            },
        )
    except Exception as exc:  # FAIL-OPEN，不阻断定时任务
        print(f"[WARN] 飞书发送失败: {exc}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["winrate", "walkforward"], default="winrate")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--min-trades", type=int, default=20)
    ap.add_argument("--warn-below", type=float, default=0.50)
    ap.add_argument("--target", type=float, default=0.60)
    ap.add_argument("--coins", nargs="+", default=["BTC", "ETH", "SOL"])
    ap.add_argument("--max-bars", type=int, default=30000)
    ap.add_argument("--n-folds", type=int, default=5)
    ap.add_argument("--out", default=str(DEFAULT_JSON))
    ap.add_argument("--log", default=str(DEFAULT_LOG))
    ap.add_argument("--no-notify", action="store_true")
    args = ap.parse_args()

    if args.mode == "winrate":
        trades = collect_db_trades(Path(args.db), args.days)
        metrics = summarize(trades)
        metrics["window_days"] = args.days
        metrics["db"] = args.db
    else:
        wf_out = PROJECT_ROOT / "data" / "eval" / "walkforward_1h_latest.json"
        metrics = run_walkforward(args.coins, wf_out, args.max_bars, args.n_folds)
        metrics["window_days"] = None
        metrics["n_folds"] = args.n_folds

    status = classify(metrics, args.min_trades, args.warn_below, args.target)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": args.mode,
        "status": status,
        "metrics": metrics,
        "thresholds": {
            "warn_below": args.warn_below,
            "target": args.target,
            "min_trades": args.min_trades,
        },
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    append_log(Path(args.log), payload)
    print(
        f"[winrate_guard] mode={args.mode} status={status} n={metrics['n']} "
        f"wr={metrics['win_rate']:.2%} target={args.target:.0%} → {out}"
    )

    if not args.no_notify:
        notify(status, metrics, args.mode, args.target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
