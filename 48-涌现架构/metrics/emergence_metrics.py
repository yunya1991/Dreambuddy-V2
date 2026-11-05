"""emergence_metrics.py — E4a 涌现度量骨架（SPEC-EMERGENCE-EVOLUTION v0.5 §4 E4a）。

每日落盘 48-涌现架构/metrics/emergence_metrics.jsonl（追加式历史快照）：
  - e2_self_generated_ratio：做梦器生成且 verify 成功且满足编辑距离>=k 的产物比率
    （当前做梦器未升级为结构变体生成器，比率恒 0——如实记录，E2 落地后自动开始非零）
  - e5_capability_scale_curve：能力-规模曲线数据点（记忆数/案例数/成交数/轨迹数）
  - complexity_trajectory：策略复杂度轨迹（人工配置结构向量的开关位数/阈值分箱跨度）

FAIL-OPEN：任何数据源缺失记 null，不阻断。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
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


def _e2_ratio() -> Dict[str, Any]:
    """E2 自生成比率。当前做梦器未升级为结构变体生成器——如实记 0 并标注状态。"""
    return {
        "value": 0.0,
        "status": "generator_not_upgraded",
        "note": "E2 做梦器升级（结构变体生成）未落地，比率按定义恒 0；升级后自动开始统计",
    }


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
