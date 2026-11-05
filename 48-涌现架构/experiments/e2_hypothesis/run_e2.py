"""run_e2.py — E2 主流程：结构变体生成批 → 新颖度 → ablation gate → M2 落盘。

流程（SPEC v0.5 §4 E2）：
  1. 读人工基线结构向量（48/registry/human_config_hashes.json）
  2. 生成 N 个结构变体（开关/阈值分箱/标的集扰动，非参数微调），min_novelty=2
     （「人未写过」定义要求编辑距离 >= k=2，距离 1 的产物不计入 E2）
  3. 逐变体过 ablation gate（过拟合 + 稳定性双判据）
  4. 落统一批次 JSON，M2 由 emergence_metrics 读取

评估器缺位（45/11 域尚无 config 级回测评估器）时：gate 如实 evaluator_missing，
M2=0，并发 E6 需求单（同类型 open 单存在则不重复发单）。

FAIL-OPEN：任何异常 → status=error，不抛出。
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

_MOD_DIR = Path(__file__).resolve().parent
if str(_MOD_DIR) not in sys.path:
    sys.path.insert(0, str(_MOD_DIR))
_REGISTRY_DIR = _MOD_DIR.parents[1] / "registry"
if str(_REGISTRY_DIR) not in sys.path:
    sys.path.insert(0, str(_REGISTRY_DIR))

import ablation_gate as ag  # noqa: E402
import batch_schema as bs  # noqa: E402
import capability_gaps as cg  # noqa: E402
import variant_generator as vg  # noqa: E402

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
HUMAN_BASELINE_PATH = _REPO_ROOT / "48-涌现架构" / "registry" / "human_baseline.json"
DEFAULT_OUT = _MOD_DIR / "e2_batch_result.json"
GAP_TYPE = "backtest_evaluator_missing"


def _baseline_oos() -> Optional[Dict[str, Any]]:
    try:
        d = json.loads(HUMAN_BASELINE_PATH.read_text(encoding="utf-8"))
        return (d.get("baselines") or [{}])[0].get("oos_metrics")
    except Exception:  # noqa: BLE001 — FAIL-OPEN
        return None


def _has_open_gap(gaps_path: Optional[Path]) -> bool:
    try:
        for gap in cg.load_gaps(gaps_path):
            if (
                gap.get("gap_type") == GAP_TYPE
                and gap.get("created_by") == "e2_hypothesis"
                and gap.get("status") in ("open", "claimed")
            ):
                return True
    except Exception:  # noqa: BLE001 — FAIL-OPEN
        return False
    return False


def _emit_evaluator_gap(result: Dict[str, Any], gaps_path: Optional[Path]) -> bool:
    if _has_open_gap(gaps_path):
        return False
    try:
        gap = cg.new_gap(
            gap_type=GAP_TYPE,
            evidence={
                "source": "e2_hypothesis",
                "n_generated": result.get("stats", {}).get("n_generated", 0),
                "need": "config 级回测评估器：输入策略结构变体，输出 IS/OOS 指标 + 分片指标"
                "（供 ablation gate 双判据判定）",
            },
            expected_value="E2 的 M2 比率可从恒 0 转为可判定（生成物可被真实评估）",
            target_domain_hint="45-评测系统",
            created_by="e2_hypothesis",
        )
        return cg.append_gap(gap, path=gaps_path)
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        logger.warning("发 E6 需求单失败（降级）: %s", exc)
        return False


def run(
    registry_path: Optional[Path] = None,
    gaps_path: Optional[Path] = None,
    out_path: Optional[Path] = None,
    n: int = 32,
    seed: int = 42,
    keep_ratio: float = 1.0,
    min_novelty: int = 2,
    evaluator: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """E2 主流程。evaluator(variant) → {is_metrics, oos_metrics, slice_metrics}。"""
    try:
        base = vg.load_base_vector(registry_path)
        if base is None:
            return {
                "status": "insufficient_data",
                "reason": "human_config_hashes 缺失或不可读——E2「人未写过」判据悬置",
                "stats": bs.compute_stats([]),
            }

        gen = vg.generate_variants(
            base,
            n=n,
            seed=seed,
            registry_path=registry_path,
            min_novelty=min_novelty,
            keep_ratio=keep_ratio,
        )

        baseline_oos = _baseline_oos()
        items: List[Dict[str, Any]] = []
        for v in gen["variants"]:
            if evaluator is None:
                gate = ag.evaluate(None, None, None)
                verify = {
                    "success": None,
                    "evaluated_by": None,
                    "reason": "evaluator_missing",
                }
            else:
                ev = evaluator(v) or {}
                gate = ag.evaluate(
                    ev.get("is_metrics"),
                    ev.get("oos_metrics"),
                    ev.get("slice_metrics"),
                    baseline_oos=baseline_oos,
                )
                verify = {
                    "success": bool(gate.get("admitted")),
                    "evaluated_by": "ablation_gate",
                    "reason": "; ".join(gate.get("reasons") or []) or None,
                }
            items.append(
                {
                    "variant_id": v["variant_id"],
                    "struct_vector": v["struct_vector"],
                    "vector_hash": v["vector_hash"],
                    "novelty": v["novelty"],
                    "gate": gate,
                    "verify": verify,
                    "transform": v["transform"],
                }
            )

        batch = bs.build_batch(
            generator="e2_hypothesis_variant_generator",
            space="trading_struct_vector",
            items=items,
            meta={
                "registry": str(registry_path or vg.sv.REGISTRY_PATH),
                "seed": seed,
                "min_novelty": min_novelty,
                "feedback": gen["feedback"],
                "attempts": gen["attempts"],
                "evaluator": "ablation_gate" if evaluator is not None else None,
            },
        )
        batch["status"] = "ok"
        batch["verify_status"] = "ok" if evaluator is not None else "evaluator_missing"

        if evaluator is None:
            _emit_evaluator_gap(batch, gaps_path)

        out = Path(out_path) if out_path else DEFAULT_OUT
        bs.write_batch(batch, out)
        return batch
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        logger.warning("run_e2 FAIL-OPEN: %s", exc)
        return {"status": "error", "reason": str(exc), "stats": bs.compute_stats([])}


def main() -> int:
    result = run()
    stats = result.get("stats", {})
    print(
        f"E2: status={result.get('status')} verify={result.get('verify_status')} "
        f"n_generated={stats.get('n_generated')} n_novel={stats.get('n_novel')} "
        f"m2_ratio={stats.get('m2_ratio')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
