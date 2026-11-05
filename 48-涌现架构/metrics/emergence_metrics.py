"""emergence_metrics.py — E4a 涌现度量骨架（SPEC-EMERGENCE-EVOLUTION v0.5 §4 E4a）。

每日落盘 48-涌现架构/metrics/emergence_metrics.jsonl（追加式历史快照）：
  - e2_self_generated_ratio：做梦器生成且 verify 成功且满足编辑距离>=k 的产物比率
    （当前做梦器未升级为结构变体生成器，比率恒 0——如实记录，E2 落地后自动开始非零）
  - e5_capability_scale_curve：能力-规模曲线数据点（记忆数/案例数/成交数/轨迹数）
  - complexity_trajectory：策略复杂度轨迹（人工配置结构向量的开关位数/阈值分箱跨度）

FAIL-OPEN：任何数据源缺失记 null，不阻断。

M7（E6 需求闭环率，2026-11-05 落地）：gap_resolved_rate / time_to_capability / 状态分布，
数据源 48-涌现架构/registry/capability_gaps.jsonl。
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "48-涌现架构" / "registry"))
_METRICS_DIR = _REPO_ROOT / "48-涌现架构" / "metrics"
_TRAJECTORIES = _REPO_ROOT / ".workbuddy" / "agent_mail" / "trajectories.jsonl"
_ARCHIVE_DIR = _REPO_ROOT / ".workbuddy" / "agent_mail" / "archive"
_CASE_STORE = _REPO_ROOT / "34-前端应用训练系统" / "l1_case_store.jsonl"
_TRADES_DB = _REPO_ROOT / "11-易经推理系统" / "scripts" / "data" / "bcrm_trades.db"
_HUMAN_HASHES = _REPO_ROOT / "48-涌现架构" / "registry" / "human_config_hashes.json"


def _count_lines(path: Path) -> Optional[int]:
    try:
        n = 0
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    n += 1
        return n
    except Exception:  # noqa: BLE001 — FAIL-OPEN
        return None


def _count_gz(path: Path) -> Optional[int]:
    import gzip

    try:
        n = 0
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    n += 1
        return n
    except Exception:  # noqa: BLE001
        return None


def _trajectory_count() -> Optional[int]:
    """主文件 + 归档合并计数（与轮转策略兼容）。"""
    total = 0
    main = _count_lines(_TRAJECTORIES)
    if main is not None:
        total += main
    if _ARCHIVE_DIR.is_dir():
        for p in sorted(_ARCHIVE_DIR.iterdir()):
            if not p.name.startswith("trajectories-"):
                continue
            n = _count_gz(p) if p.suffix == ".gz" else _count_lines(p)
            if n is not None:
                total += n
    return total


def _trades_count() -> Optional[int]:
    try:
        conn = sqlite3.connect(str(_TRADES_DB))
        n = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        conn.close()
        return int(n)
    except Exception:  # noqa: BLE001
        return None


_E2_RESULT = _REPO_ROOT / "48-涌现架构" / "experiments" / "e2_hypothesis" / "e2_batch_result.json"


def _e2_ratio() -> Dict[str, Any]:
    """E2 自生成比率（M2）：读 e2_hypothesis 批次结果。未跑过 → 如实 not_run。

    M2 = (verify 成功 且 编辑距离>=k) / 总生成数。评估器缺位时 M2 恒 0，
    status=evaluator_missing（不伪造）。
    """
    try:
        if not _E2_RESULT.exists():
            return {
                "value": 0.0,
                "status": "generator_not_run",
                "note": "E2 结构变体生成批尚未运行",
            }
        d = json.loads(_E2_RESULT.read_text(encoding="utf-8"))
        stats = d.get("stats") or {}
        return {
            "value": stats.get("m2_ratio", 0.0),
            "status": d.get("verify_status", "ok"),
            "note": {
                "n_generated": stats.get("n_generated"),
                "n_novel": stats.get("n_novel"),
                "n_gate_admitted": stats.get("n_gate_admitted"),
                "n_novel_verified": stats.get("n_novel_verified"),
                "evaluated_at": d.get("generated_at"),
            },
        }
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        return {"value": None, "status": "unavailable", "note": str(exc)}


def _complexity_trajectory() -> Dict[str, Any]:
    """策略复杂度：人工配置结构向量的开关位数与阈值分箱跨度。"""
    try:
        d = json.loads(_HUMAN_HASHES.read_text(encoding="utf-8"))
        cfgs = d.get("human_configs", [])
        if not cfgs:
            return {"value": None, "status": "no_configs"}
        sv = cfgs[0].get("struct_vector", {})
        switches = sv.get("switches_bitmask", "")
        bins = sv.get("threshold_bins", [])
        return {
            "value": {
                "switch_bits_on": switches.count("1"),
                "switch_bits_total": len(switches),
                "threshold_span": (max(bins) - min(bins)) if bins else None,
            },
            "status": "ok",
        }
    except Exception:  # noqa: BLE001
        return {"value": None, "status": "unavailable"}


def _m7_demand_loop() -> Dict[str, Any]:
    """M7 需求闭环率：resolved 占比 / 平均 time_to_capability（小时）/ 状态分布。"""
    try:
        import capability_gaps as cg

        gaps: List[Dict[str, Any]] = cg.load_gaps()
        if not gaps:
            return {"value": None, "status": "no_gaps_yet"}
        by_status: Dict[str, int] = {}
        ttc_hours: List[float] = []
        for g in gaps:
            s = g.get("status", "open")
            by_status[s] = by_status.get(s, 0) + 1
            if s == "resolved":
                try:
                    created = datetime.fromisoformat(
                        (g.get("created_at") or "").replace("Z", "+00:00")
                    )
                    resolved = datetime.fromisoformat(
                        (g.get("resolved_at") or "").replace("Z", "+00:00")
                    )
                    ttc_hours.append((resolved - created).total_seconds() / 3600)
                except ValueError:
                    continue
        closed = sum(by_status.get(s, 0) for s in ("resolved", "expired", "rejected"))
        return {
            "value": {
                "total": len(gaps),
                "by_status": by_status,
                "gap_resolved_rate": by_status.get("resolved", 0) / closed if closed else None,
                "avg_time_to_capability_hours": (
                    sum(ttc_hours) / len(ttc_hours) if ttc_hours else None
                ),
            },
            "status": "ok",
        }
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        return {"value": None, "status": "unavailable", "note": str(exc)}


def _m1_linkage() -> Dict[str, Any]:
    """M1 广播联动率（E1）：非目标域消费并产生动作的比例。"""
    try:
        _bus_dir = str(_REPO_ROOT / "48-涌现架构" / "bus")
        if _bus_dir not in sys.path:
            sys.path.insert(0, _bus_dir)
        import m1_linkage

        result = m1_linkage.compute_m1()
        return {"value": result, "status": result.get("status", "ok")}
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        return {"value": None, "status": "unavailable", "note": str(exc)}


_E3_RESULT = (
    _REPO_ROOT / "48-涌现架构" / "experiments" / "e3_coupling" / "counterfactual_result.json"
)


def _m3_counterfactual() -> Dict[str, Any]:
    """M3 反事实耦合（E3）：读 e3_coupling 评估结果。未跑过 → 如实 not_run。"""
    try:
        if not _E3_RESULT.exists():
            return {"value": None, "status": "not_run"}
        d = json.loads(_E3_RESULT.read_text(encoding="utf-8"))
        return {
            "value": {
                "verdict": d.get("verdict"),
                "n_pairs": d.get("n_pairs"),
                "mae_coupled": d.get("mae_coupled"),
                "mae_ablated": d.get("mae_ablated"),
                "median_improvement_pct": d.get("median_improvement_pct"),
                "p_value": d.get("p_value"),
                "direction_positive": d.get("direction_positive"),
                "evaluated_at": d.get("ts"),
            },
            "status": "ok",
        }
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        return {"value": None, "status": "unavailable", "note": str(exc)}


_E5_RESULT = (
    _REPO_ROOT / "48-涌现架构" / "experiments" / "e5_cbr_holdout" / "e5_holdout_result.json"
)


def _m6_compositional_generalization() -> Dict[str, Any]:
    """M6 组合泛化（E1 金标准）：读 e5_cbr_holdout 评估结果。未跑过 → 如实 not_run。"""
    try:
        if not _E5_RESULT.exists():
            return {"value": None, "status": "not_run"}
        d = json.loads(_E5_RESULT.read_text(encoding="utf-8"))
        return {
            "value": {
                "verdict": d.get("verdict"),
                "n_cases": d.get("n_cases"),
                "n_eval": d.get("n_eval"),
                "acc_composition": d.get("acc_composition"),
                "acc_knn": d.get("acc_knn"),
                "improvement": d.get("improvement"),
                "p_value": d.get("p_value"),
                "direction_positive": d.get("direction_positive"),
                "homomorphism_error": d.get("homomorphism_error"),
                "evaluated_at": d.get("ts"),
            },
            "status": "ok",
        }
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        return {"value": None, "status": "unavailable", "note": str(exc)}


def _e4b_readout() -> Dict[str, Any]:
    """E4b ①：recall 读回率（写→召回→改变行动）。数据源 events/memory_readout/*.jsonl。"""
    try:
        if str(_METRICS_DIR) not in sys.path:
            sys.path.insert(0, str(_METRICS_DIR))
        import e4b_readout

        return e4b_readout.compute_readout_rate()
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        return {"value": None, "status": "unavailable", "note": str(exc)}


def _e4b_cascade() -> Dict[str, Any]:
    """E4b ②：级联 σ（复用 E1 shadow 总线事件流）。样本不足如实 insufficient_data。"""
    try:
        if str(_METRICS_DIR) not in sys.path:
            sys.path.insert(0, str(_METRICS_DIR))
        import e4b_cascade

        return e4b_cascade.compute_cascade()
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        return {"value": None, "status": "unavailable", "note": str(exc)}


def _e4b_self_correction() -> Dict[str, Any]:
    """E4b ③：反思→修复 join 比例（session 级时序代理，非因果）。"""
    try:
        if str(_METRICS_DIR) not in sys.path:
            sys.path.insert(0, str(_METRICS_DIR))
        import e4b_reflection

        return e4b_reflection.compute_self_correction_rate()
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        return {"value": None, "status": "unavailable", "note": str(exc)}


def collect() -> Dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "ts": now,
        "e2_self_generated_ratio": _e2_ratio(),
        "e5_capability_scale_curve": {
            "trajectories": _trajectory_count(),
            "cases": _count_lines(_CASE_STORE),
            "trades": _trades_count(),
        },
        "complexity_trajectory": _complexity_trajectory(),
        "m7_demand_loop": _m7_demand_loop(),
        "m1_broadcast_linkage": _m1_linkage(),
        "m3_counterfactual_coupling": _m3_counterfactual(),
        "m6_compositional_generalization": _m6_compositional_generalization(),
        "e4_readout_rate": _e4b_readout(),
        "e4_cascade_sigma": _e4b_cascade(),
        "e4_self_correction_rate": _e4b_self_correction(),
    }


def main() -> int:
    _METRICS_DIR.mkdir(parents=True, exist_ok=True)
    snapshot = collect()
    out = _METRICS_DIR / "emergence_metrics.jsonl"
    with out.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
    print(f"metrics ok: {json.dumps(snapshot['e5_capability_scale_curve'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
