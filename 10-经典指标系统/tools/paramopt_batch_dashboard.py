import argparse
import datetime as dt
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _now_ms() -> int:
    return int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)


def _fmt_ms(ts_ms: Optional[int]) -> str:
    if ts_ms is None or int(ts_ms) <= 0:
        return "-"
    return dt.datetime.fromtimestamp(int(ts_ms) / 1000.0, tz=dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _fmt_dur(ms: Optional[int]) -> str:
    if ms is None:
        return "-"
    s = max(0, int(round(float(ms) / 1000.0)))
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    if h > 0:
        return f"{h}h{m:02d}m{sec:02d}s"
    if m > 0:
        return f"{m}m{sec:02d}s"
    return f"{sec}s"


def _family_of_strategy(sid: str) -> str:
    x = str(sid or "").strip().lower()
    if any(k in x for k in ["carry", "funding"]):
        return "carry"
    if "breakout" in x:
        return "breakout"
    if any(k in x for k in ["range", "mean", "revert"]):
        return "mean_reversion"
    return "trend"


def _pick_latest_log(user_data_dir: Path) -> Optional[Path]:
    cands = sorted([p for p in user_data_dir.glob("batch_paramopt_*.jsonl") if p.is_file()], key=lambda p: p.stat().st_mtime, reverse=True)
    return (cands[0] if cands else None)


def _safe_read_jsonl(path: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not path.exists():
        return out
    with path.open("r", encoding="utf-8") as f:
        for ln in f:
            s = str(ln or "").strip()
            if not s:
                continue
            try:
                obj = json.loads(s)
            except Exception:
                continue
            if isinstance(obj, dict):
                out.append(obj)
    return out


def _scan(log_path: Path) -> Dict[str, Any]:
    rows = _safe_read_jsonl(log_path)
    run_id = ""
    trace_root = ""
    total = 0
    batch_start_ts: Optional[int] = None
    batch_end_ts: Optional[int] = None
    by_sid: Dict[str, Dict[str, Any]] = {}

    for r in rows:
        ev = str(r.get("event") or "").strip()
        ts = int(r.get("ts") or 0)
        if ev == "batch_start":
            run_id = str(r.get("run_id") or run_id)
            trace_root = str(r.get("trace_root") or trace_root)
            try:
                total = int(r.get("n") or total)
            except Exception:
                total = total
            batch_start_ts = ts if ts > 0 else batch_start_ts
            continue
        if ev == "batch_end":
            batch_end_ts = ts if ts > 0 else batch_end_ts
            continue
        sid = str(r.get("strategy_id") or "").strip()
        if not sid:
            continue
        if sid not in by_sid:
            by_sid[sid] = {
                "strategy_id": sid,
                "family": _family_of_strategy(sid),
                "start_ts": None,
                "end_ts": None,
                "duration_ms": None,
                "status": "pending",
                "http": None,
                "trace_id": str(r.get("trace_id") or ""),
                "error_brief": None,
            }
        st = by_sid[sid]
        if ev == "strategy_start":
            st["status"] = "running"
            st["trace_id"] = str(r.get("trace_id") or st.get("trace_id") or "")
            st["start_ts"] = ts if ts > 0 else st.get("start_ts")
        elif ev == "strategy_done":
            st["status"] = ("success" if bool(r.get("ok")) else "fail")
            st["http"] = r.get("http")
            st["end_ts"] = ts if ts > 0 else st.get("end_ts")
        elif ev in ("strategy_http_error", "strategy_error"):
            st["status"] = "fail"
            st["http"] = r.get("code")
            st["end_ts"] = ts if ts > 0 else st.get("end_ts")
            body = str(r.get("body") or r.get("error") or "")
            st["error_brief"] = body[:180]

    now_ms = _now_ms()
    for st in by_sid.values():
        s0 = st.get("start_ts")
        e0 = st.get("end_ts")
        if isinstance(s0, int) and s0 > 0:
            if isinstance(e0, int) and e0 >= s0:
                st["duration_ms"] = int(e0 - s0)
            elif str(st.get("status")) == "running":
                st["duration_ms"] = int(now_ms - s0)

    done = [x for x in by_sid.values() if str(x.get("status")) in ("success", "fail")]
    running = [x for x in by_sid.values() if str(x.get("status")) == "running"]
    succ = [x for x in done if str(x.get("status")) == "success"]
    fail = [x for x in done if str(x.get("status")) == "fail"]
    started = int(len(by_sid))
    if total <= 0:
        total = started
    pending = max(0, int(total - len(done) - len(running)))

    fams = ["trend", "mean_reversion", "breakout", "carry"]
    fam_agg: Dict[str, Dict[str, Any]] = {}
    for f in fams:
        fam_agg[f] = {"family": f, "total_seen": 0, "success": 0, "fail": 0, "running": 0, "avg_duration_sec_done": None}
    for st in by_sid.values():
        f = str(st.get("family") or "trend")
        if f not in fam_agg:
            fam_agg[f] = {"family": f, "total_seen": 0, "success": 0, "fail": 0, "running": 0, "avg_duration_sec_done": None}
        fam_agg[f]["total_seen"] = int(fam_agg[f]["total_seen"]) + 1
        s = str(st.get("status") or "")
        if s == "success":
            fam_agg[f]["success"] = int(fam_agg[f]["success"]) + 1
        elif s == "fail":
            fam_agg[f]["fail"] = int(fam_agg[f]["fail"]) + 1
        elif s == "running":
            fam_agg[f]["running"] = int(fam_agg[f]["running"]) + 1

    for f, row in fam_agg.items():
        durs = [int(st.get("duration_ms")) for st in by_sid.values() if str(st.get("family")) == f and str(st.get("status")) in ("success", "fail") and isinstance(st.get("duration_ms"), int)]
        if durs:
            row["avg_duration_sec_done"] = round(float(sum(durs)) / float(len(durs)) / 1000.0, 2)

    slowest_done = sorted([x for x in done if isinstance(x.get("duration_ms"), int)], key=lambda x: int(x.get("duration_ms") or 0), reverse=True)[:5]
    latest_fail = sorted([x for x in fail if isinstance(x.get("end_ts"), int)], key=lambda x: int(x.get("end_ts") or 0), reverse=True)[:5]

    return {
        "ok": True,
        "run_id": run_id or log_path.stem,
        "trace_root": trace_root,
        "log_path": str(log_path),
        "batch_start_ts": batch_start_ts,
        "batch_end_ts": batch_end_ts,
        "batch_elapsed_ms": (None if not batch_start_ts else (int((batch_end_ts or now_ms) - batch_start_ts))),
        "summary": {
            "total": int(total),
            "started": int(started),
            "completed": int(len(done)),
            "success": int(len(succ)),
            "fail": int(len(fail)),
            "running": int(len(running)),
            "pending": int(pending),
            "progress_pct": round((float(len(done)) / float(total) * 100.0), 2) if total > 0 else 0.0,
        },
        "family_aggregation": [fam_agg[k] for k in sorted(fam_agg.keys())],
        "slowest_done_top5": slowest_done,
        "latest_fail_top5": latest_fail,
        "strategies": sorted(list(by_sid.values()), key=lambda x: str(x.get("strategy_id") or "")),
        "ts": now_ms,
    }


def _print_report(rep: Dict[str, Any]) -> None:
    s = rep.get("summary") if isinstance(rep.get("summary"), dict) else {}
    print("=== 批任务实时看板摘要 ===")
    print(f"run_id: {rep.get('run_id')}")
    print(f"log: {rep.get('log_path')}")
    print(f"start: {_fmt_ms(rep.get('batch_start_ts'))} | elapsed: {_fmt_dur(rep.get('batch_elapsed_ms'))}")
    print(
        "进度: {completed}/{total} ({pct}%) | success={success} fail={fail} running={running} pending={pending}".format(
            completed=int(s.get("completed") or 0),
            total=int(s.get("total") or 0),
            pct=float(s.get("progress_pct") or 0.0),
            success=int(s.get("success") or 0),
            fail=int(s.get("fail") or 0),
            running=int(s.get("running") or 0),
            pending=int(s.get("pending") or 0),
        )
    )
    print("")
    print("=== 按策略族聚合 ===")
    for row in rep.get("family_aggregation") or []:
        if not isinstance(row, dict):
            continue
        print(
            "{family:>14} | seen={seen:>2} success={succ:>2} fail={fail:>2} running={run:>2} avg_done={avg}".format(
                family=str(row.get("family") or ""),
                seen=int(row.get("total_seen") or 0),
                succ=int(row.get("success") or 0),
                fail=int(row.get("fail") or 0),
                run=int(row.get("running") or 0),
                avg=("-" if row.get("avg_duration_sec_done") is None else f"{row.get('avg_duration_sec_done')}s"),
            )
        )
    print("")
    print("=== 每策略状态 ===")
    for st in rep.get("strategies") or []:
        if not isinstance(st, dict):
            continue
        print(
            "{sid:<38} | {family:<14} | {status:<7} | dur={dur:<9} | http={http}".format(
                sid=str(st.get("strategy_id") or "")[:38],
                family=str(st.get("family") or ""),
                status=str(st.get("status") or ""),
                dur=_fmt_dur(st.get("duration_ms")),
                http=("-" if st.get("http") is None else str(st.get("http"))),
            )
        )
    if rep.get("latest_fail_top5"):
        print("")
        print("=== 最近失败 Top5 ===")
        for st in rep.get("latest_fail_top5") or []:
            if not isinstance(st, dict):
                continue
            print(f"{st.get('strategy_id')} | {st.get('family')} | {st.get('status')} | {str(st.get('error_brief') or '')}")


def _run_once(log_path: Path, as_json: bool) -> int:
    rep = _scan(log_path)
    if as_json:
        print(json.dumps(rep, ensure_ascii=False))
    else:
        _print_report(rep)
    return 0


def main() -> None:
    p = argparse.ArgumentParser(prog="paramopt_batch_dashboard", add_help=True)
    p.add_argument("--project-dir", default=str(Path(__file__).resolve().parents[1]))
    p.add_argument("--log-path", default="")
    p.add_argument("--json", action="store_true")
    p.add_argument("--watch", action="store_true")
    p.add_argument("--interval-sec", type=float, default=10.0)
    args = p.parse_args()

    project_dir = Path(str(args.project_dir)).resolve()
    log_path = Path(str(args.log_path)).resolve() if str(args.log_path).strip() else None
    if log_path is None:
        user_data = (project_dir / "user_data").resolve()
        log_path = _pick_latest_log(user_data)
    if log_path is None or (not log_path.exists()):
        print(json.dumps({"ok": False, "error": "batch_log_not_found"}, ensure_ascii=False))
        raise SystemExit(1)

    if not bool(args.watch):
        raise SystemExit(_run_once(log_path, bool(args.json)))

    try:
        while True:
            rep = _scan(log_path)
            if bool(args.json):
                print(json.dumps(rep, ensure_ascii=False))
            else:
                print("\x1bc", end="")
                _print_report(rep)
            time.sleep(max(1.0, float(args.interval_sec)))
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()
