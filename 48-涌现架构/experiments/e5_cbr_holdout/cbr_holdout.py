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

# shadow_rl 回填源（2026-11-06 扩容）：23 域 gene_data/shadow_rl_samples.jsonl
# 42.17 万行 / 16.59 万唯一 5 维市场状态向量；85% 为 WAIT → 只取入场决策
SHADOW_RL_PATH = (
    _REPO_ROOT
    / "23-四层闭环自进化交易架构"
    / "dreambuddy_evolution"
    / "gene_data"
    / "shadow_rl_samples.jsonl"
)
SHADOW_RL_STATE_KEYS = ("R_up", "R_down", "R_smooth", "R_flow", "R_reflexivity")
ENTRY_ACTIONS = frozenset({"long", "light_long", "short"})
DEFAULT_SHADOW_RL_MAX_CASES = 20000  # kNN/全批 GD 的 O(n²) 成本上限，按 cell 分层采样


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


def load_shadow_rl_cases(
    path: Path = SHADOW_RL_PATH,
    actions: frozenset = ENTRY_ACTIONS,
    label_mode: str = "positive",
    drop_zero: bool = True,
    primitives: str = "base",
) -> List[Dict[str, Any]]:
    """加载 shadow_rl 样本 → 市场状态原语 + is_short + 二值标签。

    primitives（路径 A，2026-11-06）:
      - "base"：[R_up, R_down, R_smooth, R_flow, R_reflexivity, is_short]
        注：R_down = 1 - R_up 完全共线（构造公式），保留仅为口径兼容
      - "extended"：剔除 R_down，加 quality_score（vol_quantile 新信息维）
        + 3 个交互原语（up×flow / reflex×flow / smooth×reflex）→ 9 维
        [R_up, R_smooth, R_flow, R_reflexivity, quality,
         up_x_flow, reflex_x_flow, smooth_x_reflex, is_short]

    drop_zero（默认 True）：实测 reward 92.9% 为 0（未平仓占位，非有效标签），
    保留会让任何模型都预测负类、准确率虚高到 95%。丢弃后有效样本 ~2857 条，
    正例占比 48.2%（自然平衡）。

    label_mode:
      - "positive"：reward > 0（业务语义：是否盈利；默认）
      - "median"：reward > 有效样本中位数（相对好坏口径）
      - "band"（路径 B，风险调整口径）：reward≥q75 记显著盈利(1)、≤q25 记
        显著亏损(0)、中间噪声带丢弃——剔除近零噪声交易，标签天然平衡
    """
    path = Path(path)
    if not path.exists():
        logger.warning("shadow_rl 样本缺失（跳过）: %s", path)
        return []

    rows: List[Tuple[Dict[str, Any], List[float], float, str]] = []
    n_zero = 0
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            action = str(r.get("action") or "")
            if action not in actions:
                continue
            state = r.get("state") or {}
            keys = (
                SHADOW_RL_STATE_KEYS
                if primitives == "base"
                else (
                    "R_up",
                    "R_smooth",
                    "R_flow",
                    "R_reflexivity",
                    "quality_score",
                )
            )
            try:
                vals = [float(state[k]) for k in keys]
            except (KeyError, TypeError, ValueError):
                continue
            reward = r.get("reward")
            if not isinstance(reward, (int, float)):
                continue
            if drop_zero and float(reward) == 0.0:
                n_zero += 1
                continue
            rows.append((r, vals, float(reward), action))
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        logger.warning("加载 shadow_rl 失败（降级）: %s", exc)
        return []

    if not rows:
        logger.warning("shadow_rl 无非零 reward 有效样本（n_zero=%d）", n_zero)
        return []

    # 标签口径
    kept: List[Tuple[Dict[str, Any], List[float], float, str]] = rows
    rewards = np.array([x[2] for x in rows], dtype=np.float64)
    if label_mode == "band":
        q75 = float(np.percentile(rewards, 75))
        q25 = float(np.percentile(rewards, 25))
        kept = [x for x in rows if x[2] >= q75 or x[2] <= q25]
        threshold = None
    elif label_mode == "median":
        threshold = float(np.median(rewards))
    else:  # positive
        threshold = 0.0

    cases: List[Dict[str, Any]] = []
    for i, (_r, vals, reward, action) in enumerate(kept):
        is_short = 1.0 if action == "short" else 0.0
        if primitives == "extended":
            r_up, r_smooth, r_flow, r_reflex, quality = vals
            feats = [
                r_up,
                r_smooth,
                r_flow,
                r_reflex,
                quality,
                r_up * r_flow,
                r_reflex * r_flow,
                r_smooth * r_reflex,
                is_short,
            ]
        else:
            feats = vals + [is_short]
        if label_mode == "band":
            label = 1 if reward >= q75 else 0
        else:
            label = 1 if reward > float(threshold or 0.0) else 0
        cases.append(
            {
                "case_id": f"rl-{i}",
                "library": "shadow_rl",
                "features": np.array(feats, dtype=np.float64),
                "label": label,
            }
        )
    return cases


# ============================================================
# 分箱与 cell（原语组合键）
# ============================================================


def assign_cells(
    cases: List[Dict[str, Any]],
    n_continuous: int = _N_CONTINUOUS,
    binary_dims: Optional[Sequence[int]] = None,
) -> None:
    """每个连续原语按全体中位数分高低两箱，组合成 cell 键（就地写入）。

    分箱只涉及特征不涉及标签，无标签泄漏。binary_dims 指定以原值（0/1）
    进 cell 键的特征下标，默认 (n_continuous,)——即紧随连续维之后的 is_short。
    extended 口径下交互原语（下标 5-7）不进 cell 键：它们是分箱维的派生量，
    进 cell 会碎片化组合空间。
    """
    if not cases:
        return
    if binary_dims is None:
        binary_dims = (n_continuous,)
    mat = np.array([c["features"] for c in cases], dtype=np.float64)
    medians = np.median(mat[:, :n_continuous], axis=0)
    for c in cases:
        bins = [int(c["features"][i] >= medians[i]) for i in range(n_continuous)]
        bins.extend(int(round(float(c["features"][i]))) for i in binary_dims)
        c["cell"] = tuple(bins)


def _stratified_sample(
    cases: List[Dict[str, Any]],
    max_cases: int,
    rng: np.random.Generator,
) -> List[Dict[str, Any]]:
    """按 cell 分层随机采样，保证每个原语组合仍被覆盖（控 O(n²) 成本）。"""
    if max_cases <= 0 or len(cases) <= max_cases:
        return cases
    by_cell: Dict[Any, List[Dict[str, Any]]] = {}
    for c in cases:
        by_cell.setdefault(c.get("cell"), []).append(c)
    per = max(1, max_cases // len(by_cell))
    sampled: List[Dict[str, Any]] = []
    for cell in sorted(by_cell, key=str):
        group = by_cell[cell]
        if len(group) <= per:
            sampled.extend(group)
        else:
            idx = np.sort(rng.choice(len(group), size=per, replace=False))
            sampled.extend(group[int(i)] for i in idx)
    return sampled


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


def mlp_composition_predict(
    train: List[Dict[str, Any]],
    holdout: List[Dict[str, Any]],
    hidden: Tuple[int, ...] = (16,),
    max_iter: int = 1500,
    alpha: float = 1e-3,
    seed: int = 0,
) -> List[float]:
    """非线性组合器：单隐层 MLP 逐原语非线性组合。

    E1 判据要求「组合法 vs 检索复用」。上一轮线性 logistic 在 shadow_rl 上
    falsified（45.2% vs kNN 53.6%），但市场状态→收益高度非线性时线性组合天然
    劣势——本函数用于排除「组合器能力不足」这一混淆项。sklearn 不可用时
    FAIL-OPEN 回退线性组合器并记录。
    """
    if not train or not holdout:
        return []
    x_train, x_hold, y_train = _standardize(train, holdout)
    if len(np.unique(y_train)) < 2:
        return [float(y_train.mean())] * len(x_hold)
    try:
        from sklearn.neural_network import MLPClassifier
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN 回退线性
        logger.warning("sklearn 不可用，回退 logistic 组合器: %s", exc)
        return composition_predict(train, holdout)

    clf = MLPClassifier(
        hidden_layer_sizes=hidden,
        activation="tanh",
        solver="adam",
        alpha=alpha,
        max_iter=max_iter,
        random_state=seed,
        early_stopping=False,
        learning_rate_init=0.01,
    )
    clf.fit(x_train, y_train)
    return [float(p) for p in clf.predict_proba(x_hold)[:, 1]]


def _limitation_text(compositor: str) -> str:
    """结果可信度限定（机器可读，防误读为「E1 永久证伪」）。"""
    if compositor == "logistic":
        return (
            "组合法为线性 logistic；若原语→结果关系非线性，线性组合天然劣势。"
            "falsified 只证伪「线性组合泛化」，不等于「组合泛化不可能」——"
            "需升级为非线性组合器（MLP/GBDT）复测才能对 E1 判据下最终结论。"
        )
    return (
        "组合法为单隐层 tanh MLP（非线性），已排除「线性组合器能力不足」混淆项。"
        "若仍 falsified，说明在当前 5 维市场状态原语上组合泛化不优于 kNN 检索复用；"
        "但 2857 样本仍有容量/过拟合空间，须结合同态误差与逐 cell 分布解读，"
        "不据此宣布「E1 永久不可满足」。"
    )


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
    source: str = "backtest",
    shadow_rl_path: Optional[Path] = None,
    max_cases: Optional[int] = None,
    label_mode: str = "positive",
    max_holdout_cells: int = 8,
    compositor: str = "both",
    primitives: str = "base",
) -> Dict[str, Any]:
    """E5 主流程：加载 → 分箱 → 逐 eligible cell holdout 评估 → 池化显著性检验。

    source:
      - "backtest"（默认）：11 域双库回测案例（162 条，原语 3 confidence 高度相关）
      - "shadow_rl"：23 域 shadow_rl_samples（5 维独立市场状态，可分层采样到 2 万条）
    compositor:
      - "both"（默认）：MLP 非线性为主判据 + logistic 线性对照，同 fold 对比
      - "mlp"：只跑非线性组合器
      - "logistic"：只跑线性组合器（旧口径，可复现上一轮 falsified）
    """
    rng = np.random.default_rng(seed)
    model_name = {
        "mlp": "mlp_tanh_h16",
        "logistic": "logistic_linear",
        "both": "mlp_tanh_h16+logistic_linear",
    }.get(compositor, compositor)
    result: Dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "status": "ok",
        "source": source,
        "compositor": compositor,
        "composition_model": model_name,
        "primitives": primitives,
        "limitation": _limitation_text(compositor),
    }

    try:
        if source == "shadow_rl":
            path = Path(shadow_rl_path) if shadow_rl_path else SHADOW_RL_PATH
            result["sources"] = {"shadow_rl": str(path)}
            result["label_mode"] = label_mode
            cases = load_shadow_rl_cases(path, label_mode=label_mode, primitives=primitives)
            result["n_cases_loaded"] = len(cases)
            if cases:
                # 两种口径都分箱前 5 个连续维（extended 的交互维不进 cell）；
                # is_short 下标：base=5，extended=8
                assign_cells(
                    cases,
                    n_continuous=5,
                    binary_dims=(5 if primitives == "base" else 8,),
                )
                cases = _stratified_sample(
                    cases,
                    max_cases or DEFAULT_SHADOW_RL_MAX_CASES,
                    rng,
                )
        else:
            sources = sources or DEFAULT_SOURCES
            result["sources"] = {k: str(v) for k, v in sources.items()}
            result["label_mode"] = "actual_label"
            cases = load_cases(sources)
            result["n_cases_loaded"] = len(cases)
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        result.update(status="insufficient_data", reason=f"load_failed: {exc}")
        _emit_e6_gap(result, gaps_path)
        return result

    result["n_cases"] = len(cases)
    result["pos_ratio"] = float(np.mean([c["label"] for c in cases])) if cases else 0.0
    if len(cases) < min_cases_total:
        result.update(
            status="insufficient_data",
            reason=f"cases_total={len(cases)} < min_cases_total={min_cases_total}",
        )
        _emit_e6_gap(result, gaps_path)
        return result

    if source != "shadow_rl":
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

    # 大样本下控制评估成本：eligible cell 均匀抽样（不是取最大的，避免选择性偏置）
    if max_holdout_cells and len(cells) > max_holdout_cells:
        step = len(cells) / max_holdout_cells
        cells = [cells[int(i * step)] for i in range(max_holdout_cells)]
    result["n_evaluated_cells"] = len(cells)

    # 池化评估：每个 eligible cell 依次整体扣留，模型在其余案例上训练后预测该 cell
    comp_correct: List[float] = []
    comp_linear_correct: List[float] = []
    knn_correct: List[float] = []
    per_cell: List[Dict[str, Any]] = []
    for cell in cells:
        train, holdout = holdout_split(cases, cell)
        if compositor == "logistic":
            comp_p = composition_predict(train, holdout)
            lin_p: Optional[List[float]] = comp_p
        else:
            comp_p = mlp_composition_predict(train, holdout, seed=seed)
            lin_p = composition_predict(train, holdout) if compositor == "both" else None
        knn_p = knn_baseline_predict(train, holdout, k=knn_k)
        labels = [c["label"] for c in holdout]
        cc = [float(int(p >= 0.5) == y) for p, y in zip(comp_p, labels, strict=True)]
        kc = [float(int(p >= 0.5) == y) for p, y in zip(knn_p, labels, strict=True)]
        comp_correct.extend(cc)
        knn_correct.extend(kc)
        entry: Dict[str, Any] = {
            "cell": list(cell),
            "n": len(holdout),
            "acc_composition": sum(cc) / len(cc),
            "acc_knn": sum(kc) / len(kc),
        }
        if lin_p is not None:
            lc = [float(int(p >= 0.5) == y) for p, y in zip(lin_p, labels, strict=True)]
            comp_linear_correct.extend(lc)
            entry["acc_composition_linear"] = sum(lc) / len(lc)
        per_cell.append(entry)

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
    if comp_linear_correct:
        result["acc_composition_linear"] = float(np.mean(comp_linear_correct))
        result["improvement_linear"] = result["acc_composition_linear"] - acc_knn
    if v == "insufficient_data":
        result["status"] = "insufficient_data"
        result["reason"] = f"n_eval={n_eval} < min_eval={min_eval}"
        _emit_e6_gap(result, gaps_path)
    return result


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="E5 CBR holdout 组合泛化实验")
    parser.add_argument("--source", default="backtest", choices=["backtest", "shadow_rl"])
    parser.add_argument("--max-cases", type=int, default=None, help="分层采样上限（shadow_rl）")
    parser.add_argument("--label-mode", default="positive", choices=["median", "positive", "band"])
    parser.add_argument("--compositor", default="both", choices=["both", "mlp", "logistic"])
    parser.add_argument("--primitives", default="base", choices=["base", "extended"])
    parser.add_argument("--n-perm", type=int, default=10000)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    result = run(
        source=args.source,
        max_cases=args.max_cases,
        label_mode=args.label_mode,
        n_perm=args.n_perm,
        compositor=args.compositor,
        primitives=args.primitives,
    )
    if args.out:
        out = Path(args.out)
    elif args.source == "shadow_rl":
        out = RESULT_PATH.parent / "e5_holdout_shadow_rl_result.json"
    else:
        out = RESULT_PATH
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"E5 holdout[{args.source}]: status={result['status']} "
        f"verdict={result.get('verdict')} n_cases={result.get('n_cases')} "
        f"n_eval={result.get('n_eval')} improvement={result.get('improvement')} "
        f"p={result.get('p_value')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
