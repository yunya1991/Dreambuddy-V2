"""
48-涌现架构 顶层 verdict 聚合仪表盘。

读取各实验产物与 metrics 快照，输出统一的实验 verdict 矩阵。
只读聚合，不修改任何源数据。

用法:
    python metrics/verdict_dashboard.py            # 输出 JSON 到 stdout
    python metrics/verdict_dashboard.py --table    # 输出可读表格
    python metrics/verdict_dashboard.py --save     # 写入 metrics/verdict_dashboard.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
EXPERIMENTS = ROOT / "experiments"
METRICS = ROOT / "metrics"


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open() as f:
        return json.load(f)


def _latest_d2a() -> dict:
    """D2-A: 取 mtime 最新的 run 目录下 evaluation.json。"""
    base = EXPERIMENTS / "d2a_holdout" / "results"
    if not base.exists():
        return {"experiment": "D2-A", "verdict": "not_run", "evidence": "no results dir"}
    runs = sorted(
        (d for d in base.iterdir() if d.is_dir()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for run in runs:
        ev = run / "evaluation.json"
        if ev.exists():
            data = _load_json(ev)
            decision = data.get("decision", {})
            verdict = decision.get("verdict", data.get("verdict", "unknown"))
            bootstrap = data.get("bootstrap", data.get("bootstrap_ci", {}))
            f1 = bootstrap.get("mean_delta")
            ci_low = bootstrap.get("ci_low")
            ci_high = bootstrap.get("ci_high")
            return {
                "experiment": "D2-A",
                "run_id": run.name,
                "verdict": verdict,
                "metric": "M-D2-EDGE-F1",
                "value": f1,
                "ci_low": ci_low,
                "ci_high": ci_high,
                "evidence": str(ev.relative_to(ROOT)),
            }
    return {"experiment": "D2-A", "verdict": "not_run", "evidence": "no evaluation.json"}


def _latest_d3a() -> dict:
    """D3-A: 取 mtime 最新的结果 json。"""
    base = EXPERIMENTS / "d3a_intent" / "results"
    if not base.exists():
        return {"experiment": "D3-A", "verdict": "not_run", "evidence": "no results dir"}
    files = sorted(
        base.glob("D3A-*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not files:
        return {"experiment": "D3-A", "verdict": "not_run", "evidence": "no result json"}
    data = _load_json(files[0])
    decision = data.get("decision", {})
    return {
        "experiment": "D3-A",
        "run_id": data.get("run_id", files[0].stem),
        "verdict": decision.get("verdict", "unknown"),
        "metric": "M-D3-TOP1",
        "value": data.get("system", {}).get("top1"),
        "delta": data.get("delta_top1"),
        "ci_low": data.get("bootstrap_ci", {}).get("ci_low"),
        "ci_high": data.get("bootstrap_ci", {}).get("ci_high"),
        "ece": data.get("system", {}).get("ece"),
        "reason": decision.get("reason"),
        "evidence": str(files[0].relative_to(ROOT)),
    }


def _e2_verdict() -> dict:
    """E2: 从 e2_batch_result.json 推导 verdict。"""
    path = EXPERIMENTS / "e2_hypothesis" / "e2_batch_result.json"
    data = _load_json(path)
    if not data:
        return {"experiment": "E2", "verdict": "not_run", "evidence": "no batch result"}
    stats = data.get("stats", {})
    verify_status = data.get("verify_status", "unknown")
    m2 = stats.get("m2_ratio")
    admitted = stats.get("n_gate_admitted", 0)
    if verify_status != "ok":
        verdict = "inconclusive"
        reason = f"verify_status={verify_status} (评估器缺失)"
    elif admitted > 0 and (m2 or 0) > 0:
        verdict = "candidate"
        reason = f"M2={m2}, admitted={admitted}"
    else:
        verdict = "falsified"
        reason = f"M2={m2}, admitted={admitted} (无自生成验证策略)"
    return {
        "experiment": "E2",
        "verdict": verdict,
        "metric": "M2-self-generated-ratio",
        "value": m2,
        "n_admitted": admitted,
        "n_novel": stats.get("n_novel"),
        "reason": reason,
        "evidence": str(path.relative_to(ROOT)),
    }


def _e3_verdict() -> dict:
    """E3: counterfactual_result.json verdict 字段。"""
    path = EXPERIMENTS / "e3_coupling" / "counterfactual_result.json"
    data = _load_json(path)
    if not data:
        return {"experiment": "E3", "verdict": "not_run", "evidence": "no result"}
    return {
        "experiment": "E3",
        "verdict": data.get("verdict", "unknown"),
        "metric": "M3-coupling-MAE",
        "mae_coupled": data.get("mae_coupled"),
        "mae_ablated": data.get("mae_ablated"),
        "p_value": data.get("p_value"),
        "improvement_pct": data.get("median_improvement_pct"),
        "evidence": str(path.relative_to(ROOT)),
    }


def _e5_verdict() -> dict:
    """E5: e5_holdout_shadow_rl_result.json verdict 字段。"""
    path = EXPERIMENTS / "e5_cbr_holdout" / "e5_holdout_shadow_rl_result.json"
    data = _load_json(path)
    if not data:
        return {"experiment": "E5", "verdict": "not_run", "evidence": "no result"}
    return {
        "experiment": "E5",
        "verdict": data.get("verdict", "unknown"),
        "metric": "M6-compositional-generalization",
        "acc_composition": data.get("acc_composition"),
        "acc_knn": data.get("acc_knn"),
        "p_value": data.get("p_value"),
        "homomorphism_error": data.get("homomorphism_error"),
        "evidence": str(path.relative_to(ROOT)),
    }


def _latest_metrics_entry() -> dict:
    path = METRICS / "emergence_metrics.jsonl"
    if not path.exists():
        return {}
    last = {}
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                last = json.loads(line)
    return last


def _d2b_verdict() -> dict:
    """D2-B: 取最新的 D2B-*.json overall_verdict。"""
    base = EXPERIMENTS / "d2b_engineering" / "results"
    if not base.exists():
        return {"experiment": "D2-B", "verdict": "not_run", "evidence": "no results dir"}
    files = sorted(
        base.glob("D2B-*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not files:
        return {"experiment": "D2-B", "verdict": "not_run", "evidence": "no result json"}
    data = _load_json(files[0])
    return {
        "experiment": "D2-B",
        "run_id": data.get("run_id", files[0].stem),
        "verdict": data.get("overall_verdict", "unknown"),
        "metric": "M-D2B-gap-resolution",
        "n_candidate": data.get("n_candidate"),
        "n_gaps": data.get("n_gaps"),
        "evidence": str(files[0].relative_to(ROOT)),
    }


def _d3b_verdict() -> dict:
    """D3-B: 取最新的 D3B-*.json result.verdict。"""
    base = EXPERIMENTS / "d3b_intent_combo" / "results"
    if not base.exists():
        return {"experiment": "D3-B", "verdict": "not_run", "evidence": "no results dir"}
    files = sorted(
        base.glob("D3B-*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not files:
        return {"experiment": "D3-B", "verdict": "not_run", "evidence": "no result json"}
    data = _load_json(files[0])
    res = data.get("result", {})
    return {
        "experiment": "D3-B",
        "run_id": data.get("run_id", files[0].stem),
        "verdict": res.get("verdict", "unknown"),
        "metric": "M-D3B-recall-step-reduction",
        "delta_recall_steps": res.get("mean_delta_recall_steps"),
        "ci_low": res.get("delta_ci_low"),
        "ci_high": res.get("delta_ci_high"),
        "hit_rate": res.get("mean_hit_rate"),
        "evidence": str(files[0].relative_to(ROOT)),
    }


def _xa_verdict() -> dict:
    """X-A: 取最新的 XA-*.json verdict。"""
    base = EXPERIMENTS / "xa_transfer" / "results"
    if not base.exists():
        return {"experiment": "X-A", "verdict": "not_run", "evidence": "no results dir"}
    files = sorted(
        base.glob("XA-*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not files:
        return {"experiment": "X-A", "verdict": "not_run", "evidence": "no result json"}
    data = _load_json(files[0])
    return {
        "experiment": "X-A",
        "run_id": data.get("run_id", files[0].stem),
        "verdict": data.get("verdict", "unknown"),
        "metric": "M-X-G123",
        "g123": data.get("g123"),
        "omega": data.get("omega_o_information"),
        "ci_low": data.get("g123_bootstrap", {}).get("ci_low"),
        "ci_high": data.get("g123_bootstrap", {}).get("ci_high"),
        "evidence": str(files[0].relative_to(ROOT)),
    }


def _e1_verdict(metrics: dict) -> dict:
    """E1: 来自 m1_broadcast_linkage。"""
    m1 = metrics.get("m1_broadcast_linkage", {})
    val = m1.get("value", {}) if isinstance(m1.get("value"), dict) else {}
    status = m1.get("status", "no_events")
    broadcasts = val.get("broadcasts", 0)
    actions = val.get("actions", 0)
    if status == "no_events" or broadcasts == 0:
        verdict = "insufficient_data"
    elif actions > 0 and status == "ok":
        verdict = "candidate_weak"
    else:
        verdict = "inconclusive"
    return {
        "experiment": "E1",
        "verdict": verdict,
        "metric": "M1-broadcast-linkage",
        "broadcasts": broadcasts,
        "actions": actions,
        "m1_rate": val.get("m1_rate"),
        "note": "需 7 天 shadow 跑数 + ≥1 次非预设联动候选",
        "evidence": "metrics/emergence_metrics.jsonl (latest)",
    }


def _e4_verdict(metrics: dict) -> dict:
    """E4: readout + cascade + self_correction 三指标联合。"""
    readout = metrics.get("e4_readout_rate", {})
    cascade = metrics.get("e4_cascade_sigma", {})
    selfcorr = metrics.get("e4_self_correction_rate", {})

    readout_ok = readout.get("status") == "ok" and readout.get("evidence_grade") != "pipeline_only"
    cascade_ok = cascade.get("status") == "ok"
    selfcorr_ok = (
        selfcorr.get("status") == "ok" and selfcorr.get("evidence_grade") != "pipeline_only"
    )

    if readout_ok and cascade_ok and selfcorr_ok:
        verdict = "candidate"
    elif cascade.get("status") == "insufficient_data":
        verdict = "insufficient_data"
    else:
        verdict = "inconclusive"

    return {
        "experiment": "E4",
        "verdict": verdict,
        "metric": "E4-self-correction (readout+cascade+reflection)",
        "readout_rate": readout.get("value"),
        "readout_grade": readout.get("evidence_grade"),
        "cascade_status": cascade.get("status"),
        "self_correction_rate": selfcorr.get("value"),
        "selfcorr_grade": selfcorr.get("evidence_grade"),
        "note": (
            "self-correction 已脱离 pipeline_only（active_reflection_id 精确 join，grade=real）；"
            "readout 待交易域 recall 数据积累；cascade 待 7 天 shadow 跑数"
        ),
        "evidence": "metrics/emergence_metrics.jsonl (latest)",
    }


def build_dashboard() -> dict:
    metrics = _latest_metrics_entry()
    entries = [
        _latest_d2a(),
        _d2b_verdict(),
        _latest_d3a(),
        _d3b_verdict(),
        _xa_verdict(),
        _e2_verdict(),
        _e3_verdict(),
        _e5_verdict(),
        _e1_verdict(metrics),
        _e4_verdict(metrics),
    ]
    # 统计
    by_verdict: dict[str, int] = {}
    for e in entries:
        by_verdict[e["verdict"]] = by_verdict.get(e["verdict"], 0) + 1
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "metrics_ts": metrics.get("ts"),
        "entries": entries,
        "summary": by_verdict,
    }


def _render_table(dash: dict) -> str:
    lines = []
    lines.append(f"# 48-涌现架构 Verdict 仪表盘  ({dash['generated_at'][:19]})")
    lines.append(f"metrics 快照: {dash.get('metrics_ts', 'N/A')}")
    lines.append("")
    lines.append(f"{'实验':<6} {'Verdict':<18} {'关键指标':<28} {'证据'}")
    lines.append("-" * 100)
    for e in dash["entries"]:
        exp = e["experiment"]
        verdict = e["verdict"]
        metric = e.get("metric", "")
        val = e.get("value")
        if val is not None:
            metric = f"{metric}={val}"
        elif "mae_coupled" in e:
            metric = f"coupled={e['mae_coupled']} vs ablated={e['mae_ablated']}"
        elif "acc_composition" in e:
            metric = f"composition={e['acc_composition']} vs knn={e['acc_knn']}"
        elif "broadcasts" in e:
            metric = f"broadcasts={e['broadcasts']} actions={e['actions']}"
        elif "readout_rate" in e:
            metric = f"readout={e['readout_rate']} cascade={e['cascade_status']}"
        elif "delta_recall_steps" in e:
            metric = f"delta_steps={e['delta_recall_steps']:.2f} hit={e.get('hit_rate', 0):.2f}"
        elif "n_candidate" in e:
            metric = f"{e['n_candidate']}/{e.get('n_gaps', '?')} gaps resolved"
        elif "g123" in e:
            metric = f"G123={e['g123']:.3f} Ω={e.get('omega', 0):.3f}"
        ev = e.get("evidence", "")
        lines.append(f"{exp:<6} {verdict:<18} {metric:<28} {ev}")
    lines.append("")
    lines.append("汇总: " + ", ".join(f"{k}={v}" for k, v in dash["summary"].items()))
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--table", action="store_true", help="输出可读表格")
    parser.add_argument("--save", action="store_true", help="写入 metrics/verdict_dashboard.json")
    args = parser.parse_args()

    dash = build_dashboard()
    if args.save:
        out = METRICS / "verdict_dashboard.json"
        out.write_text(json.dumps(dash, ensure_ascii=False, indent=2))
        print(f"saved -> {out}")
    if args.table:
        print(_render_table(dash))
    else:
        print(json.dumps(dash, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
