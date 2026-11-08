"""e5_strong_primitives.py — E5 强原语复测（SPEC v0.5 §4 E5）。
背景（2026-11-06 判读）：旧 5 维原语集预测力弱（kNN 仅 53.6%），组合泛化不成立的
根因是原语集而非组合器容量。本脚本换更强原语重跑：
  1) 原语扩维：6 个状态维度（R_up/R_down/R_smooth/R_flow/R_reflexivity/quality_score）
     + 6 个状态转移增量（next_state - state，捕捉单步动态）= 12 维
  2) 标签口径：median 相对收益分位（reward > 有效样本中位数），替代 positive 绝对口径
方法论：完全复用 cbr_holdout.py 的 SCAN 式 holdout 管线（中位数分箱 cell 整体扣留
+ MLP/logistic 组合器 vs kNN 检索基线 + 配对置换检验 + 方向检查）。
FAIL-OPEN：数据缺失/异常返回 insufficient_data，不抛出。
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from cbr_holdout import (  # noqa: E402
    ENTRY_ACTIONS,
    SHADOW_RL_PATH,
    assign_cells,
    select_holdout_cells,
    holdout_split,
    composition_predict,
    mlp_composition_predict,
    knn_baseline_predict,
    permutation_test,
    verdict,
    homomorphism_error,
)

logger = logging.getLogger("e5_strong_primitives")
RESULT_PATH = _HERE / "e5_strong_primitives_result.json"

# 强原语：6 状态 + 6 转移增量（next_state - state）
STATE_KEYS = ("R_up", "R_down", "R_smooth", "R_flow", "R_reflexivity", "quality_score")
N_FEATURES = 6


def load_strong_cases(
    path: Path = SHADOW_RL_PATH,
    label_mode: str = "median",
    drop_zero: bool = True,
) -> List[Dict[str, Any]]:
    """加载 shadow_rl → 12 维强原语 + median 分位标签。"""
    path = Path(path)
    if not path.exists():
        logger.warning("shadow_rl 样本缺失: %s", path)
        return []
    rows: List[tuple] = []
    n_zero = 0
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        action = str(r.get("action") or "")
        if action not in ENTRY_ACTIONS:
            continue
        state = r.get("state") or {}
        # 实测 next_state 全为空字典（转移增量不可用），强原语=6 维状态（含 quality_score）
        try:
            s_vals = [float(state[k]) for k in STATE_KEYS]
        except (KeyError, TypeError, ValueError):
            continue
        reward = r.get("reward")
        if not isinstance(reward, (int, float)):
            continue
        if drop_zero and float(reward) == 0.0:
            n_zero += 1
            continue
        rows.append((s_vals + [1.0 if action == "short" else 0.0], float(reward)))
    if not rows:
        logger.warning("无有效样本（n_zero=%d）", n_zero)
        return []
    threshold = float(np.median([x[1] for x in rows])) if label_mode == "median" else 0.0
    return [
        {
            "case_id": f"rls-{i}",
            "library": "shadow_rl_strong",
            "features": np.array(f, dtype=np.float64),
            "label": 1 if reward > threshold else 0,
        }
        for i, (f, reward) in enumerate(rows)
    ]


def run(
    max_cases: int = 20000,
    n_perm: int = 10000,
    seed: int = 42,
    label_mode: str = "median",
    max_holdout_cells: int = 8,
    compositor: str = "both",
) -> Dict[str, Any]:
    rng = np.random.default_rng(seed)
    result: Dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "status": "ok",
        "source": "shadow_rl_strong_primitives",
        "n_features": N_FEATURES,
        "state_keys": list(STATE_KEYS),
        "feature_design": "6 state dims incl quality_score + is_short (next_state empty in data, deltas unavailable)",
        "label_mode": label_mode,
        "compositor": compositor,
    }
    try:
        cases = load_strong_cases(label_mode=label_mode)
    except Exception as exc:  # noqa: BLE001
        result.update(status="insufficient_data", reason=f"load_failed: {exc}")
        return result
    result["n_cases_loaded"] = len(cases)
    if len(cases) < 30:
        result.update(status="insufficient_data", reason=f"cases={len(cases)} < 30")
        return result
    # 分层采样控制 O(n^2) 成本（按标签分层）
    if len(cases) > max_cases:
        pos = [c for c in cases if c["label"] == 1]
        neg = [c for c in cases if c["label"] == 0]
        frac = max_cases / len(cases)
        rng.shuffle(pos)
        rng.shuffle(neg)
        cases = pos[: int(len(pos) * frac)] + neg[: int(len(neg) * frac)]
        rng.shuffle(cases)
    result["n_cases"] = len(cases)
    result["pos_ratio"] = float(np.mean([c["label"] for c in cases]))
    # 前 12 维全连续 → 中位数分箱（is_short 已含在转移增量口径外，此处 12 维全连续）
    assign_cells(cases, n_continuous=N_FEATURES)
    cells = select_holdout_cells(cases, min_cell=8, min_train=60)
    result["n_eligible_cells"] = len(cells)
    if not cells:
        result.update(status="insufficient_data", reason="no_eligible_holdout_cells")
        return result
    if max_holdout_cells and len(cells) > max_holdout_cells:
        step = len(cells) / max_holdout_cells
        cells = [cells[int(i * step)] for i in range(max_holdout_cells)]
    result["n_evaluated_cells"] = len(cells)
    comp_correct: List[float] = []
    lin_correct: List[float] = []
    knn_correct: List[float] = []
    per_cell: List[Dict[str, Any]] = []
    for cell in cells:
        train, holdout = holdout_split(cases, cell)
        comp_p = mlp_composition_predict(train, holdout, seed=seed)
        lin_p = composition_predict(train, holdout) if compositor == "both" else None
        knn_p = knn_baseline_predict(train, holdout, k=5)
        labels = [c["label"] for c in holdout]
        cc = [float(int(p >= 0.5) == y) for p, y in zip(comp_p, labels, strict=True)]
        kc = [float(int(p >= 0.5) == y) for p, y in zip(knn_p, labels, strict=True)]
        comp_correct.extend(cc)
        knn_correct.extend(kc)
        entry = {
            "cell": list(cell),
            "n": len(holdout),
            "acc_composition": sum(cc) / len(cc),
            "acc_knn": sum(kc) / len(kc),
        }
        if lin_p is not None:
            lc = [float(int(p >= 0.5) == y) for p, y in zip(lin_p, labels, strict=True)]
            lin_correct.extend(lc)
            entry["acc_composition_linear"] = sum(lc) / len(lc)
        per_cell.append(entry)
    n_eval = len(comp_correct)
    acc_comp = float(np.mean(comp_correct)) if n_eval else 0.0
    acc_knn = float(np.mean(knn_correct)) if n_eval else 0.0
    improvement = acc_comp - acc_knn
    p_value, obs = permutation_test(comp_correct, knn_correct, n_perm=n_perm, rng=rng)
    v = verdict(improvement, p_value, n_eval, min_eval=20)
    result.update(
        verdict=v,
        n_eval=n_eval,
        acc_composition=acc_comp,
        acc_knn=acc_knn,
        improvement=improvement,
        p_value=p_value,
        obs_diff=obs,
        direction_positive=improvement > 0,
        homomorphism_error=homomorphism_error(cases, rng=rng),
        per_cell=per_cell,
    )
    if lin_correct:
        result["acc_composition_linear"] = float(np.mean(lin_correct))
        result["improvement_linear"] = result["acc_composition_linear"] - acc_knn
    if v == "insufficient_data":
        result["status"] = "insufficient_data"
        result["reason"] = f"n_eval={n_eval} < min_eval=20"
    return result


def main() -> int:
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="E5 强原语复测（12 维 + median 分位标签）")
    parser.add_argument("--label-mode", default="median", choices=["median", "positive"])
    parser.add_argument("--compositor", default="both", choices=["both", "mlp", "logistic"])
    parser.add_argument("--n-perm", type=int, default=10000)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    result = run(label_mode=args.label_mode, n_perm=args.n_perm, compositor=args.compositor)
    out = Path(args.out) if args.out else RESULT_PATH
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"E5 strong: status={result['status']} verdict={result.get('verdict')} "
        f"n_cases={result.get('n_cases')} n_eval={result.get('n_eval')} "
        f"acc_comp={result.get('acc_composition')} acc_knn={result.get('acc_knn')} "
        f"improvement={result.get('improvement')} p={result.get('p_value')}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
