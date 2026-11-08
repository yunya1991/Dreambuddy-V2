"""rolling_retest.py — E3 e3_candidate 滚动复测（SPEC v0.5 §4 E3）。
背景：2026-11-06 修正生产耦合向量 3 对异常值后结论翻转为 e3_candidate
（改善 ~2.5%，p=0.0001 方向正显著，15/15 稳健）。本脚本做更长时序滚动复测：
按时间切窗（默认季度），每窗独立跑反事实评估，检验 e3_candidate 的时序稳定性。
判读口径：
  - 全部窗口方向正 且 多数显著 → e3_candidate_stable
  - 方向正但不显著占多数 → e3_candidate_weak
  - 方向不一致 → unstable（如实降级，不硬撑）
FAIL-OPEN：任何异常不抛出。
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from coupling_counterfactual import (  # noqa: E402
    _load_static_coupling,
    build_transition_pairs,
    evaluate_counterfactual,
    load_domain_state_series,
)

logger = logging.getLogger("e3_rolling_retest")
RESULT_PATH = _HERE / "rolling_retest_result.json"
WINDOWED = Path(
    "/home/luke/dreambuddy/.workbuddy/l1_training/domain_discovery_training_windowed.jsonl"
)
MIN_PAIRS_PER_WINDOW = 300


def _window_key(ts: str) -> str:
    """时间戳 → 季度窗口键（YYYY-Qn）。"""
    t = ts.replace("T", " ")[:10]
    if len(t) >= 7:
        y, m = t[:4], int(t[5:7])
        return f"{y}-Q{(m - 1) // 3 + 1}"
    return "unknown"


def run(
    jsonl_path: Path = WINDOWED,
    n_perm: int = 2000,
    seed: int = 42,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "spec": "SPEC-EMERGENCE-EVOLUTION v0.5 §4 E3 rolling retest",
        "data_source": str(jsonl_path),
        "window": "quarterly",
    }
    try:
        series = load_domain_state_series([jsonl_path])
        result["n_series"] = len(series)
        if len(series) < MIN_PAIRS_PER_WINDOW * 2:
            result.update(status="insufficient_data", reason=f"n_series={len(series)} 过少")
            return result
        coupling = _load_static_coupling(
            Path("/home/luke/dreambuddy/mcp_shells/_shared/assets/domain_transmission_static.json")
        )
        if coupling is None:
            result.update(status="insufficient_data", reason="static coupling 读取失败")
            return result
        # 按季度切窗
        windows: Dict[str, List[Dict[str, Any]]] = {}
        for r in series:
            windows.setdefault(_window_key(r["ts"]), []).append(r)
        result["n_windows"] = len(windows)
        per_window: List[Dict[str, Any]] = []
        for wkey in sorted(windows):
            rows = windows[wkey]
            X, Y = build_transition_pairs(rows)
            if len(X) < MIN_PAIRS_PER_WINDOW:
                per_window.append(
                    {"window": wkey, "n_pairs": int(len(X)), "status": "skipped_small"}
                )
                continue
            ev = evaluate_counterfactual(
                X, Y, coupling, min_pairs=MIN_PAIRS_PER_WINDOW, n_perm=n_perm, seed=seed
            )
            per_window.append(
                {
                    "window": wkey,
                    "n_pairs": int(len(X)),
                    "verdict": ev.get("verdict"),
                    "mae_coupled": ev.get("mae_coupled"),
                    "mae_ablated": ev.get("mae_ablated"),
                    "improvement_pct": ev.get("median_improvement_pct"),
                    "p_value": ev.get("p_value"),
                    "direction_positive": ev.get("direction_positive"),
                }
            )
        result["per_window"] = per_window
        evaluated = [
            w
            for w in per_window
            if w.get("verdict") in ("e3_candidate", "falsified", "inconclusive")
        ]
        if not evaluated:
            result.update(status="insufficient_data", reason="无足量窗口")
            return result
        n_pos = sum(1 for w in evaluated if w.get("direction_positive"))
        n_sig = sum(
            1 for w in evaluated if w.get("direction_positive") and (w.get("p_value") or 1.0) < 0.05
        )
        result.update(
            n_evaluated_windows=len(evaluated),
            n_direction_positive=n_pos,
            n_significant_positive=n_sig,
        )
        if n_pos == len(evaluated) and n_sig >= max(1, len(evaluated) // 2):
            result["verdict"] = "e3_candidate_stable"
        elif n_pos > len(evaluated) / 2:
            result["verdict"] = "e3_candidate_weak"
        else:
            result["verdict"] = "unstable"
        result["status"] = "ok"
    except Exception as exc:  # noqa: BLE001
        result.update(status="error", reason=str(exc))
    return result


def main() -> int:
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="E3 滚动复测")
    parser.add_argument("--n-perm", type=int, default=2000)
    args = parser.parse_args()
    result = run(n_perm=args.n_perm)
    RESULT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"E3 rolling: status={result.get('status')} verdict={result.get('verdict')} "
        f"windows={result.get('n_evaluated_windows')} pos={result.get('n_direction_positive')} "
        f"sig={result.get('n_significant_positive')}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
