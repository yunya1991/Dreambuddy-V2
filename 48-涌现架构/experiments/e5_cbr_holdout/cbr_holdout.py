"""cbr_holdout.py — E5 CBR holdout 原语组合泛化实验（SPEC-EMERGENCE-EVOLUTION v0.5 §4 E5）。

判据 M6（E1 金标准）：把某原语组合（regime 形态 cell）从案例库整体扣留，
测试系统能否用其余案例"组合"出对该新形态的正确响应。

方法对照（SCAN 式，LLM §6.5）：
  - 检索复用基线：kNN（k=5，标准化欧氏距离，邻居成功率投票）——当前 CBR 的真实机制
  - 组合方法：逐原语学习贡献权重并线性组合（logistic 回归，L2 正则，确定性全批 GD）
    ——"组件独立学习、测试时组合"的最小形式

显著性：配对符号翻转置换检验（per-case 正确性差异，默认 10k 次）+ 显式方向检查
（E3 β 原型教训：p 显著但方向为负 → falsified，不得申报 candidate）。

辅助指标：同态误差——特征距离与标签一致性的相关（结构相似行情应激活相似响应）。

数据源（真实回测案例，非合成）：
  - washout_reversal_backtest_cases.jsonl（69 条，reversal_long_success/fail）
  - pump_dump_reversal_backtest_cases.jsonl（93 条，reversal_short_success/fail）

数据现实（2026-11-05 调研）：生产 4-MEMORY/data/evolution_cases/ 仅 1 条 washout
案例（远低于 min_cases=30 的 KNN 激活阈值）——实验改用上述回测导出案例。
entry_price 非市场原语，剔除；is_short 作为方向原语统一两库。

FAIL-OPEN：任何异常 → insufficient_data + reason，不抛出；样本不足联动 E6 需求单。
"""

from __future__ import annotations

import json
import logging
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_TESTDATA = _REPO_ROOT / "11-易经推理系统" / "scripts" / "memory_l4" / "tests"
DEFAULT_SOURCES = {
    "washout_reversal": _TESTDATA / "washout_reversal_backtest_cases.jsonl",
    "pump_dump_reversal": _TESTDATA / "pump_dump_reversal_backtest_cases.jsonl",
}
RESULT_PATH = Path(__file__).resolve().parent / "e5_holdout_result.json"

# 统一原语 schema（entry_price 剔除——绝对价位非市场原语）
PRIMITIVES = [
    "setup_confidence",
    "ending_confidence",
    "combined_confidence",
    "hold_days",
    "is_short",
]
_N_CONTINUOUS = 4  # 前 4 个连续原语做中位数分箱；is_short 保持 0/1

# 两库字段映射：setup 特征键 / 成功标签 / 方向
_LIB_SPEC = {
    "washout_reversal": ("washout_confidence", "reversal_long_success", 0.0),
    "pump_dump_reversal": ("weakness_confidence", "reversal_short_success", 1.0),
}

MIN_CASES_TOTAL = 30  # 与案例库 min_cases=30 降级阈值一致
MIN_CELL = 8
MIN_TRAIN = 60
MIN_EVAL = 20
KNN_K = 5


# ============================================================
# 加载与统一 schema
# ============================================================


def load_cases(sources: Dict[str, Path]) -> List[Dict[str, Any]]:
    """加载双库回测案例 → 统一原语向量 + 二值标签。坏行跳过，文件缺失跳过。"""
    cases: List[Dict[str, Any]] = []
    for library, path in sources.items():
        spec = _LIB_SPEC.get(library)
        if spec is None:
            continue
        setup_key, success_label, is_short = spec
        path = Path(path)
        if not path.exists():
            logger.warning("案例文件缺失（跳过）: %s", path)
            continue
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                fs = r.get("features_snapshot") or {}
                try:
                    features = np.array(
                        [
                            float(fs.get(setup_key, 0.0)),
                            float(fs.get("ending_confidence", 0.0)),
                            float(fs.get("combined_confidence", 0.0)),
                            float(fs.get("hold_days", 0.0)),
                            is_short,
                        ],
                        dtype=np.float64,
                    )
                except (TypeError, ValueError):
                    continue
                cases.append(
                    {
                        "case_id": r.get("case_id", ""),
                        "library": library,
                        "features": features,
                        "label": 1 if r.get("actual_label") == success_label else 0,
                    }
                )
        except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
            logger.warning("加载案例失败（降级）: %s", exc)
    return cases


# ============================================================
# 分箱与 cell（原语组合键）
# ============================================================


def assign_cells(cases: List[Dict[str, Any]]) -> None:
    """每个连续原语按全体中位数分高低两箱，组合成 cell 键（就地写入）。

    分箱只涉及特征不涉及标签，无标签泄漏。is_short 保持 0/1 原值。
    """
    if not cases:
        return
    mat = np.array([c["features"] for c in cases], dtype=np.float64)
    medians = np.median(mat[:, :_N_CONTINUOUS], axis=0)
    for c in cases:
        bins = [int(c["features"][i] >= medians[i]) for i in range(_N_CONTINUOUS)]
        bins.append(int(round(float(c["features"][_N_CONTINUOUS]))))
        c["cell"] = tuple(bins)


def holdout_split(
    cases: List[Dict[str, Any]], cell: Tuple[int, ...]
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """按 cell 整体扣留：训练集绝不含该组合（SCAN 核心约束）。"""
    train = [c for c in cases if c.get("cell") != cell]
    holdout = [c for c in cases if c.get("cell") == cell]
    return train, holdout


def select_holdout_cells(
    cases: List[Dict[str, Any]], min_cell: int = MIN_CELL, min_train: int = MIN_TRAIN
) -> List[Tuple[int, ...]]:
    """可选 holdout cell：组内 ≥ min_cell 且扣留后训练集 ≥ min_train。"""
    counts: Dict[Tuple[int, ...], int] = {}
    for c in cases:
        cell = c.get("cell")
        if cell is None:
            continue
        counts[cell] = counts.get(cell, 0) + 1
    total = len(cases)
    return sorted(cell for cell, n in counts.items() if n >= min_cell and (total - n) >= min_train)


# ============================================================
# 两种响应机制
# ============================================================


def _standardize(
    train: List[Dict[str, Any]], holdout: List[Dict[str, Any]]
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """用训练集均值/方差标准化（防泄漏）；退化维度 std=1。"""
    x_train = np.array([c["features"] for c in train], dtype=np.float64)
    x_hold = np.array([c["features"] for c in holdout], dtype=np.float64)
    y_train = np.array([c["label"] for c in train], dtype=np.float64)
    mu = x_train.mean(axis=0)
    sd = x_train.std(axis=0)
    sd[sd < 1e-12] = 1.0
    return (x_train - mu) / sd, (x_hold - mu) / sd, y_train


def knn_baseline_predict(
    train: List[Dict[str, Any]], holdout: List[Dict[str, Any]], k: int = KNN_K
) -> List[float]:
    """检索复用基线：kNN 邻居成功率投票（当前 CBR 真实机制）。"""
    if not train or not holdout:
        return []
    x_train, x_hold, y_train = _standardize(train, holdout)
    kk = max(1, min(k, len(train)))
    probs: List[float] = []
    for x in x_hold:
        d = np.linalg.norm(x_train - x, axis=1)
        idx = np.argsort(d, kind="stable")[:kk]
        probs.append(float(y_train[idx].mean()))
    return probs


def composition_predict(
    train: List[Dict[str, Any]],
    holdout: List[Dict[str, Any]],
    lr: float = 0.1,
    epochs: int = 5000,
    l2: float = 1e-4,
) -> List[float]:
    """组合方法：逐原语贡献权重线性组合（logistic 回归，确定性全批 GD）。

    SCAN 式最小组合：每个原语独立学习对成功的贡献，测试时线性组合——
    对"训练中从未以该组合出现"的输入可泛化（前提是概念线性可分的部分）。
    """
    if not train or not holdout:
        return []
    x_train, x_hold, y_train = _standardize(train, holdout)
    n, dim = x_train.shape
    w = np.zeros(dim, dtype=np.float64)
    prior = float(np.clip(y_train.mean(), 1e-6, 1 - 1e-6))
    b = math.log(prior / (1 - prior))
    for _ in range(epochs):
        z = x_train @ w + b
        p = 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))
        err = p - y_train
        w -= lr * (x_train.T @ err / n + l2 * w)
        b -= lr * float(err.mean())
    z = x_hold @ w + b
    return [float(v) for v in 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))]


# ============================================================
# 显著性与判定
# ============================================================


def permutation_test(
    correct_a: Sequence[float],
    correct_b: Sequence[float],
    n_perm: int = 10000,
    rng: Optional[np.random.Generator] = None,
) -> Tuple[float, float]:
    """配对符号翻转置换检验。返回 (p_value, obs_diff=mean(a-b))。"""
    a = np.asarray(correct_a, dtype=np.float64)
    b = np.asarray(correct_b, dtype=np.float64)
    diffs = a - b
    obs = float(diffs.mean()) if diffs.size else 0.0
    if diffs.size == 0 or n_perm <= 0:
        return 1.0, obs
    rng = rng or np.random.default_rng(42)
    signs = rng.choice(np.array([-1.0, 1.0]), size=(n_perm, diffs.size))
    perm_means = (signs * diffs).mean(axis=1)
    p = (1.0 + float(np.sum(np.abs(perm_means) >= abs(obs) - 1e-15))) / (n_perm + 1)
    return p, obs


def verdict(
    median_improvement: float,
    p_value: float,
    n_eval: int,
    min_eval: int = MIN_EVAL,
    alpha: float = 0.05,
) -> str:
    """E1 判定（含 E3 β 教训方向检查）。"""
    if n_eval < min_eval:
        return "insufficient_data"
    if p_value < alpha:
        return "e1_candidate" if median_improvement > 0 else "falsified"
    return "inconclusive"


# ============================================================
# 同态误差（辅助指标）
# ============================================================


def homomorphism_error(
    cases: List[Dict[str, Any]],
    rng: Optional[np.random.Generator] = None,
    max_pairs: int = 20000,
) -> Optional[float]:
    """特征距离与标签不一致度的相关：结构相似行情 → 相似响应（正值=表征健康）。"""
    n = len(cases)
    if n < 4:
        return None
    rng = rng or np.random.default_rng(0)
    mat = np.array([c["features"] for c in cases], dtype=np.float64)
    labels = np.array([c["label"] for c in cases], dtype=np.float64)
    sd = mat.std(axis=0)
    sd[sd < 1e-12] = 1.0
    mat = (mat - mat.mean(axis=0)) / sd
    total_pairs = n * (n - 1) // 2
    n_pairs = min(total_pairs, max_pairs)
    i_idx = rng.integers(0, n, size=n_pairs)
    j_idx = rng.integers(0, n, size=n_pairs)
    mask = i_idx != j_idx
    i_idx, j_idx = i_idx[mask], j_idx[mask]
    if i_idx.size < 4:
        return None
    dists = np.linalg.norm(mat[i_idx] - mat[j_idx], axis=1)
    disagree = np.abs(labels[i_idx] - labels[j_idx])
    if dists.std() < 1e-12 or disagree.std() < 1e-12:
        return None
    return float(np.corrcoef(dists, disagree)[0, 1])


# ============================================================
# E6 需求单联动
# ============================================================


def _emit_e6_gap(result: Dict[str, Any], gaps_path: Optional[Path]) -> bool:
    try:
        _reg = str(_REPO_ROOT / "48-涌现架构" / "registry")
        if _reg not in sys.path:
            sys.path.insert(0, _reg)
        import capability_gaps as cg

        gap = cg.new_gap(
            gap_type="case_sparse",
            evidence={
                "source": "e5_cbr_holdout",
                "reason": result.get("reason", ""),
                "n_cases": result.get("n_cases", 0),
                "need": "更多闭环 CBR 案例（washout_reversal / pump_dump_reversal），"
                "使原语组合 holdout 评估达到可判定样本量",
            },
            expected_value="E5 组合泛化评估可从 insufficient_data 转为可判定"
            "（e1_candidate/falsified/inconclusive）",
            target_domain_hint="evolution-case-ingest",
            created_by="e5_cbr_holdout",
        )
        return cg.append_gap(gap, path=gaps_path)
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        logger.warning("发 E6 需求单失败（降级）: %s", exc)
        return False


# ============================================================
# 主流程
# ============================================================


def run(
    sources: Optional[Dict[str, Path]] = None,
    gaps_path: Optional[Path] = None,
    min_cases_total: int = MIN_CASES_TOTAL,
    min_cell: int = MIN_CELL,
    min_train: int = MIN_TRAIN,
    min_eval: int = MIN_EVAL,
    knn_k: int = KNN_K,
    n_perm: int = 10000,
    seed: int = 42,
) -> Dict[str, Any]:
    """E5 主流程：加载 → 分箱 → 逐 eligible cell holdout 评估 → 池化显著性检验。"""
    sources = sources or DEFAULT_SOURCES
    rng = np.random.default_rng(seed)
    result: Dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "status": "ok",
        "sources": {k: str(v) for k, v in sources.items()},
    }

    try:
        cases = load_cases(sources)
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        result.update(status="insufficient_data", reason=f"load_failed: {exc}")
        _emit_e6_gap(result, gaps_path)
        return result

    result["n_cases"] = len(cases)
    if len(cases) < min_cases_total:
        result.update(
            status="insufficient_data",
            reason=f"cases_total={len(cases)} < min_cases_total={min_cases_total}",
        )
        _emit_e6_gap(result, gaps_path)
        return result

    assign_cells(cases)
    cells = select_holdout_cells(cases, min_cell=min_cell, min_train=min_train)
    result["n_eligible_cells"] = len(cells)
    if not cells:
        result.update(
            status="insufficient_data",
            reason="no_eligible_holdout_cells: 原语组合多样性不足"
            f"（min_cell={min_cell}, min_train={min_train}）",
        )
        _emit_e6_gap(result, gaps_path)
        return result

    # 池化评估：每个 eligible cell 依次整体扣留，模型在其余案例上训练后预测该 cell
    comp_correct: List[float] = []
    knn_correct: List[float] = []
    per_cell: List[Dict[str, Any]] = []
    for cell in cells:
        train, holdout = holdout_split(cases, cell)
        comp_p = composition_predict(train, holdout)
        knn_p = knn_baseline_predict(train, holdout, k=knn_k)
        labels = [c["label"] for c in holdout]
        cc = [float(int(p >= 0.5) == y) for p, y in zip(comp_p, labels, strict=True)]
        kc = [float(int(p >= 0.5) == y) for p, y in zip(knn_p, labels, strict=True)]
        comp_correct.extend(cc)
        knn_correct.extend(kc)
        per_cell.append(
            {
                "cell": list(cell),
                "n": len(holdout),
                "acc_composition": sum(cc) / len(cc),
                "acc_knn": sum(kc) / len(kc),
            }
        )

    n_eval = len(comp_correct)
    acc_comp = float(np.mean(comp_correct)) if n_eval else 0.0
    acc_knn = float(np.mean(knn_correct)) if n_eval else 0.0
    improvement = acc_comp - acc_knn
    p_value, obs = permutation_test(comp_correct, knn_correct, n_perm=n_perm, rng=rng)
    v = verdict(improvement, p_value, n_eval, min_eval=min_eval)

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
    if v == "insufficient_data":
        result["status"] = "insufficient_data"
        result["reason"] = f"n_eval={n_eval} < min_eval={min_eval}"
        _emit_e6_gap(result, gaps_path)
    return result


def main() -> int:
    result = run()
    RESULT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"E5 holdout: status={result['status']} verdict={result.get('verdict')} "
        f"n_cases={result.get('n_cases')} n_eval={result.get('n_eval')} "
        f"improvement={result.get('improvement')} p={result.get('p_value')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
