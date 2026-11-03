#!/usr/bin/env python3
"""shadow_gate.py — 数据充分性门禁 + 自动推进开关（S0.5 → S1_READY → S3_READY）

SPEC-L0-L1-DOMAIN-DISCOVERY-v0.1 §4.6.6 撤销条件 / §4.6.7 分阶段：
S1/S2/S3 暂缓，但"满足数据要求后自动推进"需要一个可审计的门禁，而不是靠人记。

设计：
  1) `evaluate_readiness()`：流式读 trajectory store，按 (域 × 信号) 统计连续流，
     检查 F5 数据充分性三阈值（连续流数 / 每流观测数 / 覆盖天数）+ 断档上限。
  2) `maybe_promote()`：仅当开关打开时推进状态机，**只升不降**：
       S0.5 --(数据就绪)--> S1_READY --(消融 F1+F2 通过)--> S3_READY
     - S1_READY：touch `S1_ENABLED`，AgentMailShadow 开始附加签名特征（仍影子侧）
     - S3_READY：只记状态，不自动改图（图接线必须人工审查，H2 冻结主体权重）
  3) 开关（默认关）：env `AGENT_MAIL_AUTO_PROMOTE=1` > flag `.workbuddy/agent_mail/AUTO_PROMOTE`

FAIL-OPEN：任何异常返回 {"error": ...}，绝不影响驱动/壳主链路。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MAIL_DIR = _REPO_ROOT / ".workbuddy" / "agent_mail"
DEFAULT_STORE_PATH = _MAIL_DIR / "trajectories.jsonl"
DEFAULT_STATE_PATH = _MAIL_DIR / "PROMOTION_STATE.json"
AUTO_PROMOTE_FLAG = _MAIL_DIR / "AUTO_PROMOTE"
S1_FLAG = _MAIL_DIR / "S1_ENABLED"
DEFAULT_ABLATION_PATH = _MAIL_DIR / "ablation_result.json"

# F5 数据充分性阈值（SPEC §4.6.6 / §4.6.7 重启条件）
MIN_STREAMS = 10
MIN_OBS_PER_STREAM = 200
MIN_COVERAGE_DAYS = 180.0  # 6 个月
MAX_GAP_HOURS = 72.0

# 一条"流" = (域, 信号) 的时间序列；壳信封稳定携带这 4 个字段
SIGNALS = ("poe_score", "latency_ms", "messages_sent", "cross_domain_refs")

STAGE_INITIAL = "S0.5"
STAGE_S1 = "S1_READY"
STAGE_S3 = "S3_READY"
_STAGE_ORDER = {STAGE_INITIAL: 0, STAGE_S1: 1, STAGE_S3: 2}


def auto_promote_enabled() -> bool:
    """开关优先级：显式 env > flag 文件 > 默认关。"""
    env = os.environ.get("AGENT_MAIL_AUTO_PROMOTE")
    if env is not None:
        return env.strip() == "1"
    try:
        return AUTO_PROMOTE_FLAG.exists()
    except Exception:  # noqa: BLE001
        return False


def _signal_value(entry: Dict[str, Any], signal: str) -> Optional[float]:
    if signal == "poe_score":
        raw: Any = entry.get("poe_score")
    elif signal == "latency_ms":
        raw = (entry.get("cost") or {}).get("latency_ms")
    elif signal == "messages_sent":
        raw = (entry.get("cost") or {}).get("messages_sent")
    else:
        raw = entry.get("cross_domain_refs")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value


def evaluate_readiness(store_path: Optional[str] = None) -> Dict[str, Any]:
    """流式评估轨迹库是否达到 S1 数据门槛。只读、无副作用、内存 O(域×信号)。"""
    path = Path(store_path) if store_path else DEFAULT_STORE_PATH
    report: Dict[str, Any] = {
        "store": str(path),
        "entries": 0,
        "domains": [],
        "coverage_days": 0.0,
        "streams": [],
        "continuous_streams": 0,
        "max_gap_hours": 0.0,
        "ready": False,
        "failed": [],
        "thresholds": {
            "min_streams": MIN_STREAMS,
            "min_obs_per_stream": MIN_OBS_PER_STREAM,
            "min_coverage_days": MIN_COVERAGE_DAYS,
            "max_gap_hours": MAX_GAP_HOURS,
        },
    }
    if not path.exists():
        report["failed"].append("store_missing")
        return report

    # (domain, signal) → {count, last_ts, max_gap}
    streams: Dict[tuple, Dict[str, float]] = {}
    first_ts: Optional[float] = None
    last_ts: Optional[float] = None
    domain_last: Dict[str, float] = {}
    domain_gap: Dict[str, float] = {}

    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = float(entry.get("ts", 0.0) or 0.0)
                domain = str(entry.get("agent_domain", "") or "")
                if not domain or ts <= 0:
                    continue
                report["entries"] += 1
                first_ts = ts if first_ts is None else min(first_ts, ts)
                last_ts = ts if last_ts is None else max(last_ts, ts)
                prev = domain_last.get(domain)
                if prev is not None:
                    gap_hours = (ts - prev) / 3600.0
                    domain_gap[domain] = max(domain_gap.get(domain, 0.0), gap_hours)
                domain_last[domain] = ts
                for signal in SIGNALS:
                    if _signal_value(entry, signal) is None:
                        continue
                    key = (domain, signal)
                    row = streams.setdefault(key, {"count": 0.0})
                    row["count"] += 1
    except Exception as e:  # noqa: BLE001 — FAIL-OPEN
        report["error"] = f"{type(e).__name__}: {e}"
        return report

    if first_ts is None or last_ts is None:
        report["failed"].append("no_entries")
        return report

    coverage_days = max(0.0, (last_ts - first_ts) / 86400.0)
    report["coverage_days"] = round(coverage_days, 3)
    report["domains"] = sorted(domain_last)
    report["max_gap_hours"] = round(max(domain_gap.values()) if domain_gap else 0.0, 3)

    stream_rows: List[Dict[str, Any]] = []
    for (domain, signal), row in sorted(streams.items()):
        gap = float(domain_gap.get(domain, 0.0))
        continuous = row["count"] >= MIN_OBS_PER_STREAM and gap <= MAX_GAP_HOURS
        stream_rows.append(
            {
                "domain": domain,
                "signal": signal,
                "obs": int(row["count"]),
                "domain_max_gap_hours": round(gap, 3),
                "continuous": continuous,
            }
        )
    report["streams"] = stream_rows
    report["continuous_streams"] = sum(1 for r in stream_rows if r["continuous"])

    if report["continuous_streams"] < MIN_STREAMS:
        report["failed"].append(
            f"continuous_streams<{MIN_STREAMS} ({report['continuous_streams']})"
        )
    if coverage_days < MIN_COVERAGE_DAYS:
        report["failed"].append(f"coverage_days<{MIN_COVERAGE_DAYS} ({round(coverage_days, 3)})")
    short = [r for r in stream_rows if r["obs"] < MIN_OBS_PER_STREAM]
    if short:
        report["failed"].append(f"streams_with_obs<{MIN_OBS_PER_STREAM} ({len(short)})")
    if report["max_gap_hours"] > MAX_GAP_HOURS:
        report["failed"].append(f"max_gap_hours>{MAX_GAP_HOURS} ({report['max_gap_hours']})")
    report["ready"] = not report["failed"]
    return report


def _atomic_write(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def read_state(state_path: Optional[str] = None) -> Dict[str, Any]:
    path = Path(state_path) if state_path else DEFAULT_STATE_PATH
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:  # noqa: BLE001
        pass
    return {"stage": STAGE_INITIAL, "since": "", "history": []}


def maybe_promote(
    store_path: Optional[str] = None,
    ablation_path: Optional[str] = None,
    state_path: Optional[str] = None,
    enabled: Optional[bool] = None,
) -> Dict[str, Any]:
    """按开关与证据推进状态机。默认关：立即返回 skipped，不做任何 IO 重活。"""
    switched = auto_promote_enabled() if enabled is None else bool(enabled)
    result: Dict[str, Any] = {
        "enabled": switched,
        "promoted": False,
        "stage_before": "",
        "stage_after": "",
        "actions": [],
    }
    if not switched:
        result["skipped"] = "auto_promote_disabled"
        return result

    try:
        state = read_state(state_path)
        stage = str(state.get("stage", STAGE_INITIAL))
        result["stage_before"] = stage
        result["stage_after"] = stage

        # --- S0.5 → S1_READY：数据充分性 ---
        if _STAGE_ORDER.get(stage, 0) < _STAGE_ORDER[STAGE_S1]:
            readiness = evaluate_readiness(store_path)
            result["readiness"] = {
                "ready": readiness["ready"],
                "failed": readiness["failed"],
                "continuous_streams": readiness["continuous_streams"],
                "coverage_days": readiness["coverage_days"],
                "max_gap_hours": readiness["max_gap_hours"],
                "entries": readiness["entries"],
            }
            if not readiness["ready"]:
                result["skipped"] = "data_not_ready"
                result["stage_after"] = stage
                return result
            stage = STAGE_S1
            result["actions"].append("S1_ENABLED")

        # --- S1_READY → S3_READY：只看消融证据，不自动改图 ---
        if stage == STAGE_S1:
            report_path = Path(ablation_path) if ablation_path else DEFAULT_ABLATION_PATH
            evidence: Dict[str, Any] = {}
            try:
                if report_path.exists():
                    evidence = json.loads(report_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                evidence = {}
            passes = bool(evidence.get("f1_pass")) and bool(evidence.get("f2_pass"))
            result["ablation"] = {"path": str(report_path), "passes": passes}
            if passes:
                stage = STAGE_S3
                result["actions"].append("S3_READY")
            else:
                result["skipped"] = "ablation_not_passed"

        if result["actions"]:
            result["promoted"] = True

        if result["promoted"]:
            now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            if "S1_ENABLED" in result["actions"]:
                try:
                    S1_FLAG.parent.mkdir(parents=True, exist_ok=True)
                    S1_FLAG.touch()
                except Exception:  # noqa: BLE001
                    pass
            history = list(state.get("history") or [])[-20:]
            history.append({"from": result["stage_before"], "to": stage, "at": now})
            _atomic_write(
                Path(state_path) if state_path else DEFAULT_STATE_PATH,
                {
                    "stage": stage,
                    "since": now,
                    "history": history,
                    "evidence": {
                        "readiness": result.get("readiness"),
                        "ablation": result.get("ablation"),
                    },
                },
            )
        result["stage_after"] = stage
        return result
    except Exception as e:  # noqa: BLE001 — FAIL-OPEN
        result["error"] = f"{type(e).__name__}: {e}"
        return result


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="轨迹数据门禁 / 自动推进")
    ap.add_argument("--store", default="", help="trajectory store 路径")
    ap.add_argument("--state", default="", help="状态文件路径")
    ap.add_argument("--ablation", default="", help="消融结果 JSON 路径")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--evaluate", action="store_true", help="只评估数据充分性（只读）")
    group.add_argument("--promote", action="store_true", help="按开关推进一步（写入状态）")
    ns = ap.parse_args()

    if ns.evaluate:
        print(json.dumps(evaluate_readiness(ns.store or None), ensure_ascii=False))
        return
    print(
        json.dumps(
            maybe_promote(
                store_path=ns.store or None,
                ablation_path=ns.ablation or None,
                state_path=ns.state or None,
                enabled=True,
            ),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
