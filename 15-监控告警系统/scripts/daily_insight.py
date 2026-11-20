#!/usr/bin/env python3
"""DreamBuddy 交易链路监控日报（23 + 40 核心链路）。

流程：
  1. 聚合当日 23 推理链、40 周期神经网络、22 执行链的监控数据
  2. 规则引擎先做确定性异常识别（ri 恒定 / d_star WAIT / 产物陈旧等）
  3. 调用大模型做归因分析与建议（失败时退化为规则报告）
  4. 输出 Markdown + JSON 报告，可选推送飞书

只读业务文件与 SQLite，不触发任何交易动作。

用法：
  python3 scripts/daily_insight.py --date 2026-11-17 --push
  python3 scripts/daily_insight.py --no-llm --json
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import statistics
import sys
import urllib.error
import urllib.request
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = BASE_DIR / "config/daily_insight.json"
DEFAULT_REPO = BASE_DIR.parent


# ────────────────────────────── 基础工具 ──────────────────────────────


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def iter_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not path.exists():
        return rows
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if isinstance(obj, dict):
                rows.append(obj)
    except OSError:
        return []
    return rows


def parse_ts(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def iso_utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")


def load_env_key(key: str, files: list[str], repo: Path) -> str:
    value = os.environ.get(key, "")
    if value:
        return value
    for rel in files:
        path = Path(rel)
        if not path.is_absolute():
            path = repo / rel
        try:
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() == key:
                    return v.strip().strip('"').strip("'")
        except OSError:
            continue
    return ""


def load_config(path: Path) -> dict:
    cfg = read_json(path)
    if not isinstance(cfg, dict):
        raise SystemExit(f"配置读取失败: {path}")
    return cfg


# ────────────────────────────── 时间窗口 ──────────────────────────────


def window_for(report_date: date, tz_name: str) -> dict:
    tz = ZoneInfo(tz_name)
    start = datetime.combine(report_date, datetime.min.time(), tzinfo=tz)
    end = start + timedelta(days=1)
    return {
        "date": report_date.isoformat(),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "start_ts": start.timestamp(),
        "end_ts": end.timestamp(),
        "timezone": tz_name,
        "mode": "calendar_day",
    }


def window_recent(hours: float, tz_name: str, now: datetime | None = None) -> dict:
    """滚动窗口：截至当前时刻的最近 N 小时（默认定时任务 09:00 覆盖过去 24h）。"""
    tz = ZoneInfo(tz_name)
    end = now.astimezone(tz) if now else datetime.now(tz)
    start = end - timedelta(hours=hours)
    return {
        "date": end.date().isoformat(),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "start_ts": start.timestamp(),
        "end_ts": end.timestamp(),
        "timezone": tz_name,
        "mode": f"rolling_{int(hours)}h",
    }


def in_window(ts: float, win: dict) -> bool:
    return bool(ts) and win["start_ts"] <= ts < win["end_ts"]


# ────────────────────────────── 统计函数 ──────────────────────────────


def num_stats(values: list[float]) -> dict:
    if not values:
        return {"count": 0}
    counter = Counter(round(float(v), 6) for v in values)
    mode, mode_n = counter.most_common(1)[0]
    return {
        "count": len(values),
        "distinct": len(counter),
        "mode": mode,
        "mode_ratio": round(mode_n / len(values), 4),
        "min": min(values),
        "max": max(values),
        "mean": round(statistics.fmean(values), 4),
    }


def ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _counts(counter: Counter, limit: int = 10) -> dict:
    return {str(k): v for k, v in counter.most_common(limit)}


# ────────────────────────────── 23 推理链 ──────────────────────────────


def _chain_files(repo: Path, report_date: date) -> list[Path]:
    runtime = repo / "23-四层闭环自进化交易架构/runtime"
    files = []
    for delta in (-1, 0, 1):
        day = (report_date + timedelta(days=delta)).strftime("%Y%m%d")
        path = runtime / f"chain_events-{day}.jsonl"
        if path.exists():
            files.append(path)
    return files


def collect_chain23(repo: Path, win: dict) -> dict:
    rows: list[dict] = []
    for path in _chain_files(repo, date.fromisoformat(win["date"])):
        rows.extend(r for r in iter_jsonl(path) if in_window(parse_ts(r.get("ts")), win))

    stage_counts = Counter(f"{r.get('stage')}|{r.get('status')}" for r in rows)
    _ts_all = [parse_ts(r.get("ts")) for r in rows if r.get("ts")]
    _last_ts = max(_ts_all) if _ts_all else 0.0
    by_stage: dict[str, list[dict]] = {}
    for rec in rows:
        by_stage.setdefault(str(rec.get("stage")), []).append(rec)

    # N9 诊断记录（ri/tier/l4/ESS/ripple）
    n9_data = [r.get("data") or {} for r in by_stage.get("N9", [])]
    n9_ri = [float(x["ri"]) for x in n9_data if isinstance(x.get("ri"), (int, float))]
    n9_tier = Counter(str(x.get("tier")) for x in n9_data if x.get("tier"))
    n9_l4 = [float(x["l4_v"]) for x in n9_data if isinstance(x.get("l4_v"), (int, float))]
    ess_recs = [x for x in n9_data if "ess_top_direction" in x]
    ess_empty = sum(1 for x in ess_recs if not x.get("ess_top_direction"))
    ripple_recs = [x for x in n9_data if "ripple_is_source" in x]
    ripple_true = sum(1 for x in ripple_recs if x.get("ripple_is_source"))
    reflect_recs = [x for x in n9_data if "reflection_eligible" in x]
    reflect_true = sum(1 for x in reflect_recs if x.get("reflection_eligible"))
    vol_ratio = [
        float(x["vol_ratio"]) for x in n9_data if isinstance(x.get("vol_ratio"), (int, float))
    ]

    n8_data = [r.get("data") or {} for r in by_stage.get("N8", [])]
    n8_skips = Counter(
        str(x.get("reason_category") or "unknown") for x in n8_data if x.get("reason_category")
    )
    n8_ri = [float(x["ri"]) for x in n8_data if isinstance(x.get("ri"), (int, float))]
    # d_star 全量分布（含 pass 样本），避免只看 skip 原因导致「恒 WAIT」误判
    n8_dstar = Counter(str(x.get("d_star") or "") for x in n8_data if x.get("d_star"))

    n10_data = [r.get("data") or {} for r in by_stage.get("N10", [])]
    n10_ri = [float(x["ri"]) for x in n10_data if isinstance(x.get("ri"), (int, float))]

    n2_data = [r.get("data") or {} for r in by_stage.get("N2", [])]
    flags = Counter()
    for x in n2_data:
        for flag in x.get("fallback_flags") or []:
            flags[str(flag)] += 1

    n5_data = [r.get("data") or {} for r in by_stage.get("N5", [])]
    dims = Counter()
    directions = Counter()
    strengths = []
    for x in n5_data:
        pc = x.get("primary_contradiction") or {}
        if isinstance(pc, dict) and pc:
            dims[str(pc.get("dimension") or "unknown")] += 1
            directions[str(pc.get("direction") or "unknown")] += 1
            if isinstance(pc.get("strength"), (int, float)):
                strengths.append(float(pc["strength"]))

    n6_data = [r.get("data") or {} for r in by_stage.get("N6", [])]
    degraded_modes = Counter()
    g_states = Counter()
    shifts = divergent = 0
    for x in n6_data:
        cv = x.get("cross_validation") or {}
        if not isinstance(cv, dict) or not cv:
            continue
        mode = cv.get("degraded_mode")
        if mode:
            degraded_modes[str(mode)] += 1
        g_states[str(cv.get("g_dim_status") or "unknown")] += 1
        shifts += int(bool(cv.get("shift_signal")))
        divergent += int(bool(cv.get("divergence_count")))

    n7_data = [r.get("data") or {} for r in by_stage.get("N7", [])]
    validated = sum(1 for x in n7_data if x.get("validated"))
    score_gaps = [
        float(x["score_gap"]) for x in n7_data if isinstance(x.get("score_gap"), (int, float))
    ]

    # 链路贯通率：有 N10 信号的 chain 是否继续到 N12/N14
    chain_stages: dict[str, set[str]] = {}
    for rec in rows:
        cid = str(rec.get("chain_id") or rec.get("trace_id") or rec.get("decision_id") or "")
        if cid:
            chain_stages.setdefault(cid, set()).add(str(rec.get("stage")))
    signal_chains = [st for st in chain_stages.values() if "N10" in st]
    complete_chains = sum(1 for st in signal_chains if {"N12", "N14"} <= st)
    exec_stages = {"N12", "N13", "N14", "E4", "E5", "E6"}
    execution_events = sum(1 for r in rows if str(r.get("stage")) in exec_stages)
    n10_chains = sum(
        1 for r in by_stage.get("N10", []) if r.get("chain_id") or r.get("decision_id")
    )

    # 决策审计（submit 级）
    audit = repo / "23-四层闭环自进化交易架构/runtime/execution_decisions.jsonl"
    decisions = [r for r in iter_jsonl(audit) if in_window(parse_ts(r.get("ts")), win)]
    dec_actions = Counter(str(r.get("action") or "?") for r in decisions)
    dec_notional = sum(float(r.get("notional_usdt") or 0.0) for r in decisions)
    dec_gateway = sum(1 for r in decisions if r.get("gateway_present"))

    return {
        "events": len(rows),
        "last_event_age_hours": (
            round(max(0.0, (win["end_ts"] - _last_ts) / 3600.0), 2) if _last_ts else None
        ),
        "stage_counts": _counts(stage_counts, limit=40),
        "n9": {
            "count": len(n9_data),
            "ri": num_stats(n9_ri),
            "tier": _counts(n9_tier),
            "l4_v": num_stats(n9_l4),
            "ess_top_direction_coverage": len(ess_recs),
            "ess_top_direction_empty_ratio": ratio(ess_empty, len(ess_recs)),
            "ripple_is_source_ratio": ratio(ripple_true, len(ripple_recs)),
            "reflection_eligible_ratio": ratio(reflect_true, len(reflect_recs)),
            "vol_ratio": num_stats(vol_ratio),
        },
        "n8": {
            "count": len(n8_data),
            "skip_total": sum(n8_skips.values()),
            "skip_reasons": _counts(n8_skips),
            "ri": num_stats(n8_ri),
            "d_star": _counts(n8_dstar),
            "d_star_wait_ratio": ratio(n8_dstar.get("WAIT", 0), sum(n8_dstar.values())),
        },
        "n10": {
            "count": len(n10_data),
            "actions": _counts(Counter(str(x.get("action") or "?") for x in n10_data)),
            "tiers": _counts(Counter(str(x.get("tier") or "?") for x in n10_data)),
            "ri": num_stats(n10_ri),
        },
        "n2": {
            "count": len(n2_data),
            "degraded_ratio": ratio(
                sum(1 for r in by_stage.get("N2", []) if r.get("status") == "degraded"),
                len(by_stage.get("N2", [])),
            ),
            "fallback_flags": _counts(flags),
            "quality_score": num_stats(
                [
                    float(x["quality_score"])
                    for x in n2_data
                    if isinstance(x.get("quality_score"), (int, float))
                ]
            ),
        },
        "n5": {
            "count": len(n5_data),
            "dimensions": _counts(dims),
            "directions": _counts(directions),
            "strength": num_stats(strengths),
        },
        "n6": {
            "count": len(n6_data),
            "degraded_modes": _counts(degraded_modes),
            "degraded_ratio": ratio(sum(degraded_modes.values()), len(n6_data)),
            "g_dim_status": _counts(g_states),
            "shift_ratio": ratio(shifts, len(n6_data)),
            "divergence_ratio": ratio(divergent, len(n6_data)),
        },
        "n7": {
            "count": len(n7_data),
            "validated_ratio": ratio(validated, len(n7_data)),
            "score_gap": num_stats(score_gaps),
        },
        "chain_completion": {
            "signal_chains": len(signal_chains),
            "complete_chains": complete_chains,
            "ratio": ratio(complete_chains, len(signal_chains)),
            "n10_chains": n10_chains,
            "execution_events": execution_events,
        },
        "decisions": {
            "count": len(decisions),
            "actions": _counts(dec_actions),
            "notional_usdt": round(dec_notional, 2),
            "gateway_present_ratio": ratio(dec_gateway, len(decisions)),
        },
    }


def collect_outbox(repo: Path, win: dict, stuck_after: float) -> dict:
    db = repo / "23-四层闭环自进化交易架构/runtime/execution_outbox.db"
    if not db.exists():
        return {"present": False}
    # submitted 是生产终态（mark_filled 未接线），因此同样不参与 stuck 统计；
    # archived 为人工归档的历史失败存量，同样是终态，不参与 stuck 判定
    terminal = {"filled", "failed", "cancelled", "canceled", "done", "submitted", "archived"}
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
        cur = conn.cursor()
        rows = cur.execute("SELECT state, created_at, updated_at FROM execution_outbox").fetchall()
        conn.close()
    except sqlite3.Error as exc:
        return {"present": True, "error": str(exc)}

    states = Counter(str(r[0]) for r in rows)
    in_win = [r for r in rows if in_window(parse_ts(r[1]), win)]
    win_states = Counter(str(r[0]) for r in in_win)
    now = datetime.now(timezone.utc).timestamp()
    stuck = sum(
        1 for r in rows if str(r[0]) not in terminal and r[2] and now - parse_ts(r[2]) > stuck_after
    )
    failed = states.get("failed", 0)
    # 窗口口径：只看本窗内已尝试（进入终态）的记录，避免历史存量污染当日判定
    window_attempts = sum(n for s, n in win_states.items() if s in terminal)
    window_failed = win_states.get("failed", 0)
    return {
        "present": True,
        "total": len(rows),
        "states": _counts(states),
        "window_total": len(in_win),
        "window_states": _counts(win_states),
        "failed_ratio": ratio(failed, len(rows)),
        "window_attempts": window_attempts,
        "window_failed": window_failed,
        "window_failed_ratio": ratio(window_failed, window_attempts),
        "stuck": stuck,
    }


def collect_execution22(repo: Path, win: dict, ledger_stale_hours: float) -> dict:
    result = {"ledger": {"present": False}, "sltp": {"present": False}}
    db = repo / "22-执行引擎中心/runtime/position_ledger.db"
    if db.exists():
        try:
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
            cur = conn.cursor()
            positions = cur.execute("SELECT COUNT(*) FROM positions WHERE qty > 1e-9").fetchone()[0]
            fills = cur.execute(
                "SELECT ts, action, qty, realized_pnl, source FROM fills"
            ).fetchall()
            cooldowns = cur.execute("SELECT close_ts, exit_reason FROM cooldowns").fetchall()
            conn.close()
            win_fills = [f for f in fills if in_window(parse_ts(f[0]), win)]
            last_ts = max((parse_ts(f[0]) for f in fills), default=0.0)
            age = max(0.0, datetime.now(timezone.utc).timestamp() - last_ts) if last_ts else None
            realized = sum(float(f[3]) for f in win_fills if isinstance(f[3], (int, float)))
            ghost = sum(
                1
                for c in cooldowns
                if in_window(parse_ts(c[0]), win)
                and str(c[1]) in ("ghost_stale", "ghost_exchange_flat")
            )
            result["ledger"] = {
                "present": True,
                "positions": positions,
                "fills": len(win_fills),
                "fill_actions": _counts(Counter(str(f[1]) for f in win_fills)),
                "reconcile_updates": sum(1 for f in win_fills if str(f[1]) == "reconcile_update"),
                "realized_pnl": round(realized, 4),
                "ghost_closed": ghost,
                "last_write_age_hours": round(age / 3600, 2) if age is not None else None,
                "stale": bool(age is not None and age > ledger_stale_hours * 3600),
            }
        except sqlite3.Error as exc:
            result["ledger"] = {"present": True, "error": str(exc)}

    audit = repo / "22-执行引擎中心/audit/sltp_reconcile.jsonl"
    if audit.exists():
        recs = [r for r in iter_jsonl(audit) if in_window(parse_ts(r.get("ts")), win)]
        summaries = [r for r in recs if r.get("kind") == "summary"]
        if summaries:
            patched = sum(int(r.get("patched") or 0) for r in summaries)
            failed = sum(int(r.get("failed") or 0) for r in summaries)
        else:
            details = [r for r in recs if "ok" in r]
            patched = sum(1 for r in details if r.get("ok"))
            failed = sum(1 for r in details if not r.get("ok"))
        result["sltp"] = {
            "present": True,
            "patched": patched,
            "failed": failed,
            "records": len(recs),
            "age_hours": round(
                max(0.0, datetime.now(timezone.utc).timestamp() - audit.stat().st_mtime) / 3600, 2
            ),
        }
    return result


# ────────────────────────────── 40 神经网络 ──────────────────────────────


def _age_seconds(path: Path, timestamp_field: str | None) -> float:
    age = datetime.now(timezone.utc).timestamp() - path.stat().st_mtime
    if timestamp_field:
        data = read_json(path, {})
        ts = parse_ts(data.get(timestamp_field)) if isinstance(data, dict) else 0.0
        if ts:
            age = datetime.now(timezone.utc).timestamp() - ts
    return max(0.0, age)


def collect_nn40(repo: Path, cfg: dict) -> dict:
    """40 周期神经网络（本期预留：仅保留采集接口，默认不纳入日报分析）。"""
    enabled = "40" in (cfg.get("enabled_chains") or [])
    if not enabled:
        return {
            "enabled": False,
            "reserved": True,
            "artifacts": [],
            "stale_count": 0,
            "missing_count": 0,
            "cycle": {},
            "strategy": {},
            "fund_flow_layers": {},
            "sector_layers": {},
        }
    artifacts = []
    for spec in cfg.get("nn40_artifacts", []):
        path = repo / spec["path"]
        if not path.exists():
            artifacts.append(
                {
                    "name": spec["name"],
                    "present": False,
                    "severity": spec.get("severity", "P2"),
                    "ttl_seconds": spec.get("ttl_seconds"),
                    "stale": True,
                    "age_hours": None,
                }
            )
            continue
        age = _age_seconds(path, spec.get("timestamp_field"))
        ttl = float(spec.get("ttl_seconds") or 0)
        artifacts.append(
            {
                "name": spec["name"],
                "present": True,
                "severity": spec.get("severity", "P2"),
                "ttl_seconds": ttl,
                "age_hours": round(age / 3600, 2),
                "stale": age > ttl if ttl else False,
            }
        )

    cycle_state = read_json(repo / "40-周期神经网络系统/cycle_state.json", {}) or {}
    strategy = read_json(repo / "40-周期神经网络系统/strategy_mapping.json", {}) or {}
    fund_flow = read_json(repo / "40-周期神经网络系统/fund_flow.json", {}) or {}
    transmission = read_json(repo / "40-周期神经网络系统/sector_transmission.json", {}) or {}
    real_cycle = cycle_state.get("real_cycle") or {}
    suggestion = strategy.get("strategy_suggestion") or {}
    strategy_inputs = strategy.get("inputs") or {}
    return {
        "enabled": True,
        "reserved": False,
        "artifacts": artifacts,
        "stale_count": sum(1 for a in artifacts if a["stale"]),
        "missing_count": sum(1 for a in artifacts if not a["present"]),
        "cycle": {
            "state": real_cycle.get("state"),
            "current_rate": real_cycle.get("current_rate"),
            "confidence": real_cycle.get("confidence"),
            "current_month": real_cycle.get("current_month"),
        },
        "strategy": {
            "quadrant": strategy_inputs.get("quadrant"),
            "quadrant_confidence": strategy_inputs.get("quadrant_confidence"),
            "stance": suggestion.get("stance"),
            "position_band_pct": suggestion.get("position_band_pct"),
        },
        "fund_flow_layers": {
            k: (v or {}).get("n") if isinstance(v, dict) else None
            for k, v in (fund_flow.get("intra_sector_flow") or {}).get("layers", {}).items()
        },
        "sector_layers": {
            k: len(v) if isinstance(v, list) else None
            for k, v in (transmission.get("layers") or {}).items()
        },
    }


# ────────────────────────────── 异常规则 ──────────────────────────────


def _finding(
    fid: str, severity: str, area: str, title: str, evidence: str, likely_cause: str, action: str
) -> dict:
    return {
        "id": fid,
        "severity": severity,
        "area": area,
        "title": title,
        "evidence": evidence,
        "likely_cause": likely_cause,
        "action": action,
    }


def detect_findings(metrics: dict, cfg: dict) -> list[dict]:
    th = cfg.get("thresholds", {})
    chain = metrics["chain_23"]
    n9 = chain["n9"]
    findings: list[dict] = []

    # ── 链路数据门禁：窗口内无事件 / 链路停跑 / 样本不足时，
    #    推理链降级类判定只反映陈旧快照，必须先报数据缺失并抑制下游误报。
    _events = int(chain.get("events") or 0)
    _stale_h = chain.get("last_event_age_hours")
    _min_n = float(th.get("ri_min_samples", 10))
    _stale_limit = float(th.get("chain_stale_hours", 2.0))
    chain_gate: dict | None = None
    if _events == 0:
        chain_gate = _finding(
            "23_CHAIN_NO_EVENT",
            "P1",
            "23",
            "23 链路窗口内无事件（数据缺失）",
            f"统计窗口内 chain_events=0，N9 覆盖 {n9.get('count', 0)}",
            "entry23 未运行或 chain_events 未落盘",
            "检查 entry23 systemd/launchd 状态与 runtime/chain_events-*.jsonl 最后写入时间",
        )
    elif isinstance(_stale_h, (int, float)) and _stale_h >= _stale_limit:
        chain_gate = _finding(
            "23_CHAIN_STALE",
            "P1",
            "23",
            f"23 链路窗口末已停跑（最后事件距今 {_stale_h}h）",
            f"窗口内 events={_events}、N9 覆盖 {n9.get('count', 0)}，最后事件距窗口结束 {_stale_h}h",
            "entry23 进程中断或事件写入停止，窗口内数据只覆盖停跑前片段",
            "检查 entry23 运行状态与日志；恢复后重跑日报，停跑前的推理链降级判定不可信",
        )
    elif int(n9.get("count") or 0) < _min_n:
        chain_gate = _finding(
            "23_CHAIN_SAMPLE_STARVED",
            "P1",
            "23",
            "23 链路窗口内样本不足（数据缺失）",
            f"窗口内 events={_events}，N9 仅 {n9.get('count', 0)} 条（阈值 {int(_min_n)}）",
            "链路长时间未运行或采集频率过低，样本不足以支撑推理链判定",
            "确认链路运行时长与事件采样；样本恢复后再评估 ri/d_star/N2",
        )
    chain_ok = chain_gate is None
    if chain_gate is not None:
        findings.append(chain_gate)

    # ── 23 推理链 ──
    ri = n9["ri"]
    if chain_ok and ri.get("count", 0) >= th.get("ri_min_samples", 10):
        if ri.get("distinct", 99) <= 1:
            findings.append(
                _finding(
                    "23_RI_CONSTANT",
                    "P1",
                    "23",
                    f"ri 恒定为 {ri.get('mode')}",
                    f"N9 共 {ri['count']} 条，ri 仅 {ri['distinct']} 个取值，mode_ratio={ri['mode_ratio']}",
                    "ESS 无方向输出导致 ripple 源缺失，ri 走 FAIL-OPEN 中性降级（F1）",
                    "检查 N9 ess_top_direction 是否仍为空；确认 F1 修复是否已部署到运行实例",
                )
            )
        elif ri.get("mode_ratio", 0) >= th.get("ri_constant_ratio", 0.8):
            findings.append(
                _finding(
                    "23_RI_CONCENTRATED",
                    "P1",
                    "23",
                    f"ri 高度集中于 {ri.get('mode')}",
                    f"N9 共 {ri['count']} 条，mode_ratio={ri['mode_ratio']}，distinct={ri['distinct']}",
                    "ripple 触发率过低或源检测退化",
                    "核查 ripple_is_source / vol_ratio 分布与 RI 阈值",
                )
            )

    if chain_ok and n9.get("ess_top_direction_coverage", 0) >= th.get("ri_min_samples", 10):
        empty = n9.get("ess_top_direction_empty_ratio", 0)
        if empty >= th.get("ess_topdir_empty_ratio", 0.9):
            findings.append(
                _finding(
                    "23_ESS_TOPDIR_EMPTY",
                    "P1",
                    "23",
                    "ESS top1 方向为空",
                    f"N9 诊断覆盖 {n9['ess_top_direction_coverage']} 条，空方向占比 {empty}",
                    "ESS top1 为纯离场组合（direction=both），Provider 未向下取有方向组合",
                    "确认 ES Direction Provider 已按 ESS 降序取首个 long/short 组合",
                )
            )

    tier = n9.get("tier") or {}
    probe_ratio = ratio(tier.get("probe", 0), sum(tier.values()))
    if (
        chain_ok
        and sum(tier.values()) >= th.get("ri_min_samples", 10)
        and probe_ratio >= th.get("probe_tier_ratio", 0.8)
    ):
        findings.append(
            _finding(
                "23_TIER_PROBE",
                "P1",
                "23",
                f"仓位 tier 恒为 probe（{probe_ratio}）",
                f"N9 tier 分布 {tier}",
                "ri 未突破 PROBE_THRESHOLD 或 d_star 恒 WAIT，仓位停留在观察档",
                "结合 ri/d_star 一起定位；确认 PROBE_THRESHOLD 口径（F7 待定）",
            )
        )

    n8 = chain["n8"]
    n8_ri = n8["ri"]
    if chain_ok and n8_ri.get("count", 0) >= th.get("ri_min_samples", 10):
        if n8_ri.get("distinct", 99) <= 1:
            findings.append(
                _finding(
                    "23_N8_RI_CONSTANT",
                    "P1",
                    "23",
                    f"N8 ri 恒定为 {n8_ri.get('mode')}",
                    f"N8 共 {n8_ri['count']} 条，ri 仅 {n8_ri['distinct']} 个取值，mode_ratio={n8_ri['mode_ratio']}",
                    "无 ripple 源时 ri 走中性降级 0.5，与 ESS 方向缺失同源",
                    "确认 ripple 源检测与 ESS 方向输出；对照 N9 ess_top_direction",
                )
            )
        elif n8_ri.get("mode_ratio", 0) >= th.get("ri_constant_ratio", 0.8):
            findings.append(
                _finding(
                    "23_N8_RI_CONCENTRATED",
                    "P1",
                    "23",
                    f"N8 ri 高度集中于 {n8_ri.get('mode')}",
                    f"N8 共 {n8_ri['count']} 条，mode_ratio={n8_ri['mode_ratio']}",
                    "ripple 触发率过低或源检测退化",
                    "核查 ripple_is_source / vol_ratio 分布",
                )
            )

    # d_star 口径：优先用 N8 全量 d_star 分布（含 pass 样本）；
    # 旧事件无 d_star 字段时回退 skip 原因占比，避免把「skip 全是 d_star_wait」误读为「d_star 恒 WAIT」。
    _dstar = n8.get("d_star") or {}
    _dstar_total = sum(_dstar.values())
    if chain_ok and _dstar_total >= th.get("ri_min_samples", 10):
        wait_all = ratio(_dstar.get("WAIT", 0), _dstar_total)
        if wait_all >= th.get("dstar_all_wait_ratio", 0.95):
            findings.append(
                _finding(
                    "23_DSTAR_WAIT",
                    "P1",
                    "23",
                    f"N8 全量 d_star=WAIT（{wait_all}）",
                    f"N8 共 {_dstar_total} 条，d_star 分布={_dstar}",
                    "calibrated 中性区持续拒绝（方向代价未低于 wait×(1-margin)），或 wait_mode 未按预期生效",
                    "核对 EVOLUTION_DSTAR_WAIT_MODE 与环境注入；用 N4 d_star_shadow 比较 legacy/calibrated",
                )
            )
    elif chain_ok and n8.get("skip_total", 0) >= th.get("ri_min_samples", 10):
        wait_ratio = ratio(n8["skip_reasons"].get("d_star_wait", 0), n8["skip_total"])
        if wait_ratio >= th.get("dstar_wait_ratio", 0.8):
            findings.append(
                _finding(
                    "23_DSTAR_WAIT",
                    "P1",
                    "23",
                    f"d_star 恒 WAIT（{wait_ratio}）",
                    f"N8 skip {n8['skip_total']} 次，d_star_wait 占 {wait_ratio}（无 d_star 分布字段，按 skip 口径）",
                    "wait 成本在平滑行情下恒低于开仓（F4 已修：calibrated 口径 + 30% 中性区，默认 legacy）",
                    "确认 EVOLUTION_DSTAR_WAIT_MODE=calibrated 已生效；若已生效仍全 WAIT，查 d_star_shadow 与 margin",
                )
            )

    if (
        chain_ok
        and n9.get("reflection_eligible_ratio") == 0.0
        and n9.get("ri", {}).get("count", 0) >= th.get("ri_min_samples", 10)
    ):
        findings.append(
            _finding(
                "23_REFLECTION_STARVED",
                "P1",
                "23",
                "reflection 无有效样本（ri 恒中性 0.5）",
                f"N9 {n9['ri']['count']} 条，reflection_eligible=0，ri mode={n9['ri'].get('mode')}",
                "22 账本平仓 realized_pnl 大量为 0（reconcile/幽灵仓清零也计入统计）→ win_rate 恒 0 → reflection_ri 恒 0.5",
                "核查 22 fills 平仓 PnL 回写；reflection 统计应排除 realized_pnl 缺失/0 的 reconcile 记录",
            )
        )

    n2 = chain["n2"]
    if (
        chain_ok
        and n2.get("count", 0) >= th.get("ri_min_samples", 10)
        and n2.get("degraded_ratio", 0) >= th.get("n2_degraded_ratio", 0.9)
    ):
        findings.append(
            _finding(
                "23_N2_DEGRADED",
                "P1",
                "23",
                f"N2 阻力向量持续降级（{n2['degraded_ratio']}）",
                f"N2 共 {n2['count']} 条，fallback_flags={n2.get('fallback_flags')}",
                "多路数据源缺失（CHF/FUNDING/OI/ORDERBOOK 等），走默认阻力值",
                "检查行情/资金费/持仓量数据链路，优先补最频繁的 fallback flag",
            )
        )

    if chain_ok and chain["n10"]["count"] == 0:
        findings.append(
            _finding(
                "23_SIGNAL_SILENCE",
                "P1",
                "23",
                "当日无 23 可执行信号",
                f"N1 事件 {chain['events']} 条，N10 信号 0 条",
                "d_star/ri/tier 全链路未放行",
                "核对 N8 skip 原因与上游 ri/tier 状态",
            )
        )

    cv = chain["n6"]
    if (
        chain_ok
        and cv.get("count", 0) >= th.get("ri_min_samples", 10)
        and cv.get("degraded_ratio", 0) >= th.get("cv_degraded_ratio", 0.5)
    ):
        findings.append(
            _finding(
                "23_CV_DEGRADED",
                "P2",
                "23",
                f"交叉验证降级率 {cv['degraded_ratio']}",
                f"degraded_modes={cv.get('degraded_modes')}",
                "价格序列/维度数据不足，交叉验证退化为单维注意力",
                "检查 18/19 价格序列供给与 N6 输入完整性",
            )
        )

    g_missing = ratio(cv.get("g_dim_status", {}).get("no_price_series", 0), cv.get("count", 0))
    if (
        chain_ok
        and cv.get("count", 0) >= th.get("ri_min_samples", 10)
        and g_missing >= th.get("g_dim_missing_ratio", 0.5)
    ):
        findings.append(
            _finding(
                "23_G_DIM_NO_SERIES",
                "P2",
                "23",
                f"G 维度无价格序列（{g_missing}）",
                f"g_dim_status={cv.get('g_dim_status')}",
                "N6 价格序列输入缺失，Granger 检验无法执行",
                "核查价格序列采样与 N6 输入字段",
            )
        )

    completion = chain["chain_completion"]
    if (
        completion.get("signal_chains", 0)
        and completion.get("execution_events", 0) > 0
        and completion.get("ratio", 1.0) < th.get("chain_completion_min", 0.95)
    ):
        findings.append(
            _finding(
                "23_CHAIN_ID_MISMATCH",
                "P2",
                "23",
                f"信号→执行链路无法按 chain_id 贯通（{completion['ratio']}）",
                f"N10 信号 chain={completion['signal_chains']}，join 成功={completion['complete_chains']}，"
                f"执行事件={completion['execution_events']}",
                "N10 与执行段 chain_id 命名不一致（如 BTC 与 BTC-USDT-SWAP），或执行段未回填关联键",
                "统一 N10 与 E 段的 chain_id/symbol 口径，便于逐单复盘",
            )
        )

    # ── 40 神经网络（预留链路：启用后才参与异常判定） ──
    nn = metrics["nn_40"]
    if nn.get("enabled", True):
        stale = [a for a in nn["artifacts"] if a.get("stale")]
        if stale:
            sev = "P1" if any(a.get("severity") == "P1" for a in stale) else "P2"
            oldest = max(stale, key=lambda a: a.get("age_hours") or 0)
            findings.append(
                _finding(
                    "40_ARTIFACT_STALE",
                    sev,
                    "40",
                    f"40 神经网络产物陈旧（{len(stale)}/{len(nn['artifacts'])}）",
                    f"最旧 {oldest['name']} 已 {oldest['age_hours']}h 未更新；stale={[a['name'] for a in stale]}",
                    "40 daily_pipeline 未按日运行或产物未落盘",
                    "检查 40 daily 定时任务与 logs/daily_pipeline_*.log，确认最近一次成功运行时间",
                )
            )

        missing = [a for a in nn["artifacts"] if not a.get("present")]
        if missing:
            findings.append(
                _finding(
                    "40_ARTIFACT_MISSING",
                    "P1",
                    "40",
                    f"40 产物缺失（{len(missing)}）",
                    f"missing={[a['name'] for a in missing]}",
                    "40 未产出或路径变更",
                    "核对 40 产物路径与 daily pipeline 输出",
                )
            )

    # ── 22 执行链 ──
    outbox = metrics["outbox"]
    if outbox.get("present"):
        if outbox.get("error"):
            findings.append(
                _finding(
                    "22_OUTBOX_ERROR",
                    "P1",
                    "22",
                    "发件箱读取失败",
                    outbox["error"],
                    "SQLite 只读访问异常",
                    "检查 execution_outbox.db 权限与完整性",
                )
            )
        else:
            if outbox.get("stuck", 0) > 0:
                findings.append(
                    _finding(
                        "22_OUTBOX_STUCK",
                        "P1",
                        "22",
                        f"发件箱积压 {outbox['stuck']} 条",
                        f"states={outbox.get('states')}",
                        "网关未消费或提交状态未回写",
                        "检查 execution_gateway 与 outbox 消费循环",
                    )
                )
            # 优先用窗口口径；老实现无该字段时回退累计口径
            win_ratio = outbox.get("window_failed_ratio", outbox.get("failed_ratio", 0))
            if win_ratio > th.get("outbox_failed_ratio", 0.2):
                findings.append(
                    _finding(
                        "22_OUTBOX_FAILED",
                        "P2",
                        "22",
                        f"发件箱窗口失败率 {win_ratio}",
                        (
                            f"window_failed={outbox.get('window_failed')}/"
                            f"{outbox.get('window_attempts')}，"
                            f"window_states={outbox.get('window_states')}，"
                            f"累计 failed_ratio={outbox.get('failed_ratio')}"
                        ),
                        "网关拒单或参数不合法",
                        "抽查 failed 记录 last_error 与 result_json",
                    )
                )

    ledger = metrics["exec_22"].get("ledger", {})
    if ledger.get("present"):
        if ledger.get("error"):
            findings.append(
                _finding(
                    "22_LEDGER_ERROR",
                    "P1",
                    "22",
                    "持仓账本读取失败",
                    ledger["error"],
                    "SQLite 只读访问异常",
                    "检查 position_ledger.db 权限与完整性",
                )
            )
        else:
            if ledger.get("stale"):
                findings.append(
                    _finding(
                        "22_LEDGER_STALE",
                        "P2",
                        "22",
                        f"账本 {ledger.get('last_write_age_hours')}h 无写入",
                        f"positions={ledger.get('positions')}，window_fills={ledger.get('fills')}",
                        "无成交且无对账更新（稳定持仓也可能触发）",
                        "结合 exit23 日志确认是否长期无成交",
                    )
                )
            if ledger.get("ghost_closed", 0) > 0:
                findings.append(
                    _finding(
                        "22_GHOST_CLOSED",
                        "P2",
                        "22",
                        f"幽灵仓清理 {ledger['ghost_closed']} 次",
                        f"fills={ledger.get('fill_actions')}",
                        "交易所与本地账本不一致",
                        "核对对账任务与交易所持仓",
                    )
                )

    sltp = metrics["exec_22"].get("sltp", {})
    if sltp.get("present") and sltp.get("failed", 0) > 0:
        findings.append(
            _finding(
                "22_SLTP_FAILED",
                "P1",
                "22",
                f"SL/TP 补挂失败 {sltp['failed']} 次",
                f"patched={sltp.get('patched')}，records={sltp.get('records')}",
                "交易所拒单或参数不合法",
                "抽查 sltp_reconcile.jsonl 失败明细与交易所返回码",
            )
        )

    return findings


# ────────────────────────────── 大模型分析 ──────────────────────────────

SYSTEM_PROMPT = (
    "你是 DreamBuddy 量化交易系统的监控分析师。你的读者是交易系统负责人。"
    "你必须基于给定数据做归因，不要臆造数据；不确定时明确写“数据不足”。"
    "只输出一个 JSON 对象，不要 Markdown 代码块，不要解释性文字。"
)


def build_prompt(report_date: str, metrics: dict, findings: list[dict]) -> str:
    payload = {
        "report_date": report_date,
        "core_chains": ["23-四层闭环自进化交易架构", "40-周期神经网络系统"],
        "metrics": metrics,
        "rule_findings": findings,
    }
    return f"""分析以下交易链路监控日数据，识别异常、给出归因和可执行建议。

## 已知语义（用于避免误判）
- ri 是反身性强度；无 ripple 源时 ri 走 FAIL-OPEN 中性降级 0.5。
- tier=probe 表示仅观察档，未达到开仓阈值。
- d_star=WAIT 是 spec 定义的门控；平滑行情下 wait 成本可能恒低于开仓（已知 F4 待裁决）。
- 本期只分析 23 核心交易推理链；40 周期神经网络链路为预留项，不纳入本期异常判定。
- 22 执行链只作为 23 信号落地证据参考。

## 数据
{json.dumps(payload, ensure_ascii=False)}

## 输出 JSON 结构
{{
  "health_score": 0-100 的整数,
  "verdict": "normal|attention|critical",
  "executive_summary": "3-5 句中文，先说结论",
  "anomalies": [
    {{
      "severity": "P0|P1|P2",
      "area": "23|40|22",
      "title": "简短标题",
      "evidence": "引用具体数值",
      "likely_cause": "归因",
      "suggested_action": "可执行动作",
      "owner": "trading-core|ml-platform|data-platform|platform-governance"
    }}
  ],
  "trend_observations": ["与常态/前一日对比的观察"],
  "recommendations": ["按优先级排序的建议"],
  "data_quality": {{"missing": ["缺失数据"], "caveats": ["口径提醒"]}}
}}"""


def _extract_json(text: str) -> dict:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        text = text.rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    obj = json.loads(text)
    if not isinstance(obj, dict):
        raise ValueError("LLM 返回不是 JSON 对象")
    return obj


def llm_analyze(
    report_date: str, metrics: dict, findings: list[dict], cfg: dict, repo: Path
) -> tuple[dict | None, dict]:
    llm_cfg = cfg.get("llm", {})
    meta = {
        "enabled": bool(llm_cfg.get("enabled")),
        "provider": llm_cfg.get("provider"),
        "model": llm_cfg.get("model"),
        "ok": False,
        "error": "",
    }
    if not llm_cfg.get("enabled"):
        meta["error"] = "disabled"
        return None, meta

    api_key = load_env_key(
        llm_cfg.get("env_key", "DEEPSEEK_API_KEY"), llm_cfg.get("env_files") or [], repo
    )
    if not api_key:
        meta["error"] = f"{llm_cfg.get('env_key')} 未配置"
        return None, meta

    prompt = build_prompt(report_date, metrics, findings)
    models = [llm_cfg.get("model"), llm_cfg.get("fallback_model")]
    last_error = ""
    for model in [m for m in models if m]:
        body = json.dumps(
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "temperature": float(llm_cfg.get("temperature", 0.2)),
                "max_tokens": int(llm_cfg.get("max_tokens", 4000)),
                "response_format": {"type": "json_object"},
            }
        ).encode()
        req = urllib.request.Request(
            f"{str(llm_cfg.get('base_url', 'https://api.deepseek.com')).rstrip('/')}/chat/completions",
            data=body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        )
        try:
            with urllib.request.urlopen(
                req, timeout=int(llm_cfg.get("timeout_seconds", 120))
            ) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            choice = (data.get("choices") or [{}])[0]
            content = choice.get("message", {}).get("content", "")
            meta["model"] = model
            meta["finish_reason"] = choice.get("finish_reason")
            meta["usage"] = data.get("usage", {})
            parsed = _extract_json(content)
            meta["ok"] = True
            return parsed, meta
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as exc:
            last_error = f"{model}: {exc}"
            meta["ok"] = False
    meta["error"] = last_error or "no model"
    return None, meta


# ────────────────────────────── 报告渲染 ──────────────────────────────


def _fmt(value) -> str:
    if isinstance(value, float):
        return f"{value:g}"
    return "-" if value is None else str(value)


def _severity_order(findings: list[dict]) -> list[dict]:
    rank = {"P0": 0, "P1": 1, "P2": 2}
    return sorted(findings, key=lambda f: (rank.get(f.get("severity"), 9), f.get("title", "")))


def render_markdown(
    report_date: str,
    win: dict,
    metrics: dict,
    findings: list[dict],
    llm: dict | None,
    llm_meta: dict,
) -> str:
    chain = metrics["chain_23"]
    nn = metrics["nn_40"]
    exec22 = metrics["exec_22"]
    lines = [
        f"# 交易链路监控日报 · {report_date}",
        "",
        f"- 统计窗口：{win['start']} ~ {win['end']}（{win['timezone']}）",
        "- 核心链路：23 四层闭环自进化交易架构（40 周期神经网络链路预留，本期不启用）",
        f"- 生成时间：{datetime.now(ZoneInfo(win['timezone'])).strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 大模型：{llm_meta.get('model') or '-'}（{'成功' if llm_meta.get('ok') else '未使用/失败：' + str(llm_meta.get('error') or '-')}）",
        "",
        "## 一、结论",
    ]
    if llm:
        lines += [
            "",
            f"**健康分**：{_fmt(llm.get('health_score'))} / 100　**判定**：{_fmt(llm.get('verdict'))}",
            "",
            str(llm.get("executive_summary") or ""),
        ]
    else:
        p1 = sum(1 for f in findings if f["severity"] == "P1")
        p2 = sum(1 for f in findings if f["severity"] == "P2")
        lines += ["", f"**规则判定**：P1 {p1} 项，P2 {p2} 项（大模型分析未生成）"]

    lines += ["", "## 二、异常清单", ""]
    if findings:
        lines += [
            "### 规则引擎检出",
            "",
            "| 级别 | 域 | 异常 | 证据 | 建议动作 |",
            "|---|---|---|---|---|",
        ]
        for f in _severity_order(findings):
            lines.append(
                f"| {f['severity']} | {f['area']} | {f['title']} | {f['evidence']} | {f['action']} |"
            )
    else:
        lines.append("规则引擎未检出异常。")

    if llm and llm.get("anomalies"):
        lines += [
            "",
            "### 大模型归因",
            "",
            "| 级别 | 域 | 异常 | 证据 | 归因 | 建议 |",
            "|---|---|---|---|---|---|",
        ]
        for a in _severity_order(llm["anomalies"]):
            lines.append(
                "| {sev} | {area} | {title} | {ev} | {cause} | {act} |".format(
                    sev=a.get("severity", "-"),
                    area=a.get("area", "-"),
                    title=a.get("title", "-"),
                    ev=a.get("evidence", "-"),
                    cause=a.get("likely_cause", "-"),
                    act=a.get("suggested_action", "-"),
                )
            )

    lines += [
        "",
        "## 三、23 推理链",
        "",
        f"- 事件总数：{chain['events']}；N10 信号：{chain['n10']['count']}；决策审计：{chain['decisions']['count']}",
        f"- 链路贯通：{chain['chain_completion']['complete_chains']}/{chain['chain_completion']['signal_chains']}"
        f"（ratio={chain['chain_completion']['ratio']}）",
        "",
        "### 阶段分布",
        "",
        "| 阶段 | 状态 | 次数 |",
        "|---|---|---|",
    ]
    for key, count in chain["stage_counts"].items():
        stage, status = key.split("|", 1) if "|" in key else (key, "")
        lines.append(f"| {stage} | {status} | {count} |")

    n9 = chain["n9"]
    lines += [
        "",
        "### N9 ri / tier 诊断",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| ri 样本 | {n9['ri'].get('count', 0)} |",
        f"| ri 取值数 | {n9['ri'].get('distinct', '-')} |",
        f"| ri 众数 | {_fmt(n9['ri'].get('mode'))}（占比 {_fmt(n9['ri'].get('mode_ratio'))}） |",
        f"| tier 分布 | {n9.get('tier')} |",
        f"| l4_v 众数 | {_fmt(n9['l4_v'].get('mode'))} |",
        f"| ESS 方向为空占比 | {_fmt(n9.get('ess_top_direction_empty_ratio'))}（覆盖 {n9.get('ess_top_direction_coverage')}） |",
        f"| ripple 源命中率 | {_fmt(n9.get('ripple_is_source_ratio'))} |",
        f"| reflection 可用率 | {_fmt(n9.get('reflection_eligible_ratio'))} |",
        f"| vol_ratio 众数 | {_fmt(n9['vol_ratio'].get('mode'))} |",
        "",
        "### N8 门控分布",
        "",
        f"- skip 合计：{chain['n8']['skip_total']}；原因：{chain['n8']['skip_reasons']}",
        f"- d_star 分布：{chain['n8'].get('d_star') or '-'}（WAIT 占比 {_fmt(chain['n8'].get('d_star_wait_ratio'))}）",
        f"- N8 ri 众数：{_fmt(chain['n8']['ri'].get('mode'))}（占比 {_fmt(chain['n8']['ri'].get('mode_ratio'))}）",
        "",
        "### N10 信号",
        "",
        f"- 数量：{chain['n10']['count']}；动作：{chain['n10']['actions']}；tier：{chain['n10']['tiers']}",
        f"- 信号 ri 众数：{_fmt(chain['n10']['ri'].get('mode'))}",
        "",
        "### 上游降级情况",
        "",
        f"- N2 降级率：{chain['n2']['degraded_ratio']}；fallback flags：{chain['n2']['fallback_flags']}",
        f"- N5 主要矛盾维度：{chain['n5']['dimensions']}；方向：{chain['n5']['directions']}",
        f"- N6 降级率：{chain['n6']['degraded_ratio']}；degraded_modes：{chain['n6']['degraded_modes']}；g_dim：{chain['n6']['g_dim_status']}",
        f"- N7 通过率：{chain['n7']['validated_ratio']}",
    ]

    lines += ["", "## 四、40 周期神经网络（预留）"]
    if nn.get("enabled"):
        lines += [
            "",
            f"- 周期状态：{nn['cycle']}",
            f"- 策略映射：{nn['strategy']}",
            f"- 资金流层样本：{nn['fund_flow_layers']}",
            "",
            "| 产物 | 新鲜度(h) | TTL(h) | 状态 |",
            "|---|---|---|---|",
        ]
        for item in nn["artifacts"]:
            ttl_h = round(item["ttl_seconds"] / 3600, 1) if item.get("ttl_seconds") else "-"
            state = "缺失" if not item.get("present") else ("陈旧" if item.get("stale") else "正常")
            lines.append(f"| {item['name']} | {_fmt(item.get('age_hours'))} | {ttl_h} | {state} |")
    else:
        lines += [
            "",
            "本期预留：采集接口与产物 TTL 配置已保留，将 `enabled_chains` 加入 `40` 即启用。",
        ]

    ledger = exec22.get("ledger", {})
    sltp = exec22.get("sltp", {})
    outbox = metrics["outbox"]
    lines += [
        "",
        "## 五、22 执行链",
        "",
        f"- 发件箱：{outbox}",
        f"- 账本：{ledger}",
        f"- SL/TP 补挂：{sltp}",
    ]

    if llm:
        if llm.get("trend_observations"):
            lines += ["", "## 六、趋势观察", ""] + [f"- {x}" for x in llm["trend_observations"]]
        if llm.get("recommendations"):
            lines += ["", "## 七、建议（按优先级）", ""] + [
                f"{i + 1}. {x}" for i, x in enumerate(llm["recommendations"])
            ]
        dq = llm.get("data_quality") or {}
        if dq.get("missing") or dq.get("caveats"):
            lines += ["", "## 八、数据完整性", ""]
            if dq.get("missing"):
                lines.append(f"- 缺失：{dq['missing']}")
            if dq.get("caveats"):
                lines.append(f"- 口径提醒：{dq['caveats']}")

    return "\n".join(lines) + "\n"


# ────────────────────────────── 推送 ──────────────────────────────


def build_card_text(
    report_date: str,
    metrics: dict,
    findings: list[dict],
    llm: dict | None,
    report_path: Path,
    max_chars: int,
) -> str:
    chain = metrics["chain_23"]
    nn = metrics["nn_40"]
    order = _severity_order(findings)
    top = order[:5]
    lines = [f"**23+40 核心链路日报 · {report_date}**"]
    if llm:
        lines.append(
            f"健康分 **{_fmt(llm.get('health_score'))}** / 100 · 判定 **{_fmt(llm.get('verdict'))}**"
        )
        summary = str(llm.get("executive_summary") or "").strip()
        if summary:
            lines.append(summary)
    else:
        lines.append("大模型分析未生成，以下为规则检出。")

    lines.append(
        f"23：事件 {chain['events']} · N10 信号 {chain['n10']['count']} · "
        f"ri 众数 {_fmt(chain['n9']['ri'].get('mode'))}（{_fmt(chain['n9']['ri'].get('mode_ratio'))}）"
    )
    if nn.get("enabled"):
        lines.append(
            f"40：产物陈旧 {nn['stale_count']}/{len(nn['artifacts'])} · 周期 {nn['cycle'].get('state') or '-'}"
        )
    else:
        lines.append("40：本期预留，未纳入分析")
    if top:
        lines.append("**重点异常**")
        for f in top:
            lines.append(f"- [{f['severity']}] {f['title']}：{f['evidence']}")
    if llm and llm.get("recommendations"):
        lines.append("**建议**")
        for i, rec in enumerate(llm["recommendations"][:3], 1):
            lines.append(f"{i}. {rec}")
    lines.append(f"报告：{report_path.name}")
    text = "\n".join(lines)
    return text[:max_chars]


def push_report(cfg: dict, text: str) -> tuple[bool, str]:
    push_cfg = cfg.get("push", {})
    if not push_cfg.get("enabled"):
        return False, "push disabled"
    url = push_cfg.get("receiver_url")
    level = push_cfg.get("level", "P3")
    if url:
        try:
            body = json.dumps({"level": level, "text": text}).encode()
            req = urllib.request.Request(
                url, data=body, headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    return True, f"receiver:{url}"
        except (urllib.error.URLError, OSError) as exc:
            receiver_error = str(exc)
        else:
            receiver_error = "receiver non-200"
    else:
        receiver_error = "no receiver_url"

    if push_cfg.get("fallback_direct"):
        try:
            sys.path.insert(0, str(BASE_DIR))
            import feishu_alert  # noqa: PLC0415

            feishu_alert.send_alert("system", "info", text, None, "15-监控日报")
            return True, "direct-feishu"
        except Exception as exc:  # noqa: BLE001 - 推送失败不能影响报告落盘
            return False, f"receiver={receiver_error}; direct={exc}"
    return False, f"receiver={receiver_error}"


# ────────────────────────────── 主流程 ──────────────────────────────


def collect_all(repo: Path, win: dict, cfg: dict) -> dict:
    th = cfg.get("thresholds", {})
    return {
        "window": {k: win[k] for k in ("date", "start", "end", "timezone")},
        "chain_23": collect_chain23(repo, win),
        "nn_40": collect_nn40(repo, cfg),
        "outbox": collect_outbox(repo, win, float(th.get("outbox_stuck_seconds", 300))),
        "exec_22": collect_execution22(repo, win, float(th.get("ledger_stale_hours", 24))),
    }


def push_decision(metrics: dict, requested: bool, allow_empty: bool) -> tuple[bool, str]:
    """空窗抑制：窗口内没有 23 链路事件时不推送。

    本机没有 entry23 时，日报只能读到陈旧的本地 runtime，零事件会直接判 critical，
    推进飞书就是纯噪声；报告照常落盘，需要人工推送时用 --push-empty 覆盖。
    """
    if not requested:
        return False, "not requested"
    if not allow_empty and int((metrics.get("chain_23") or {}).get("events") or 0) == 0:
        return False, "skipped: 窗口内无 23 链路事件（本机无 entry23 或未落盘）"
    return True, "ok"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DreamBuddy 交易链路监控日报")
    parser.add_argument(
        "--date", help="报告日期 YYYY-MM-DD（自然日窗口）；缺省为截至当前的滚动窗口"
    )
    parser.add_argument("--hours", type=float, default=24, help="滚动窗口小时数，默认 24")
    parser.add_argument(
        "--repo-root", default=os.environ.get("DREAMBUDDY_REPO_ROOT", str(DEFAULT_REPO))
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--out-dir", default=str(BASE_DIR / "logs/daily-insight"))
    parser.add_argument("--no-llm", action="store_true", help="只用规则引擎，不调用大模型")
    parser.add_argument("--push", action="store_true", help="推送飞书")
    parser.add_argument(
        "--push-empty", action="store_true", help="窗口内无 23 事件时仍推送（默认抑制）"
    )
    parser.add_argument("--json", action="store_true", help="stdout 输出 JSON 摘要")
    args = parser.parse_args(argv)

    repo = Path(args.repo_root).expanduser().resolve()
    cfg = load_config(Path(args.config))
    tz_name = cfg.get("window", {}).get("timezone", "Asia/Shanghai")
    if args.date:
        report_date = date.fromisoformat(args.date)
        win = window_for(report_date, tz_name)
    else:
        win = window_recent(args.hours, tz_name)
        report_date = date.fromisoformat(win["date"])

    metrics = collect_all(repo, win, cfg)
    findings = detect_findings(metrics, cfg)

    llm, llm_meta = (None, {"enabled": False, "ok": False, "error": "no-llm"})
    if not args.no_llm:
        llm, llm_meta = llm_analyze(report_date.isoformat(), metrics, findings, cfg, repo)

    markdown = render_markdown(report_date.isoformat(), win, metrics, findings, llm, llm_meta)
    out_dir = Path(args.out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"{report_date.isoformat()}.md"
    json_path = out_dir / f"{report_date.isoformat()}.json"
    md_path.write_text(markdown, encoding="utf-8")
    json_path.write_text(
        json.dumps(
            {
                "report_date": report_date.isoformat(),
                "window": win,
                "metrics": metrics,
                "findings": findings,
                "llm": llm,
                "llm_meta": llm_meta,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    push_ok, push_reason = push_decision(metrics, args.push, args.push_empty)
    pushed, push_detail = (False, push_reason)
    if push_ok:
        text = build_card_text(
            report_date.isoformat(),
            metrics,
            findings,
            llm,
            md_path,
            int(cfg.get("push", {}).get("max_chars", 3200)),
        )
        pushed, push_detail = push_report(cfg, text)

    summary = {
        "report_date": report_date.isoformat(),
        "report_md": str(md_path),
        "report_json": str(json_path),
        "health_score": (llm or {}).get("health_score"),
        "verdict": (llm or {}).get("verdict"),
        "llm": llm_meta,
        "findings": len(findings),
        "p1": sum(1 for f in findings if f["severity"] == "P1"),
        "p2": sum(1 for f in findings if f["severity"] == "P2"),
        "pushed": pushed,
        "push_detail": push_detail,
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"[daily-insight] {report_date} → {md_path}")
        print(
            f"[daily-insight] findings={summary['findings']} p1={summary['p1']} p2={summary['p2']} "
            f"llm={'ok' if llm_meta.get('ok') else 'skip'} push={pushed} ({push_detail})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
