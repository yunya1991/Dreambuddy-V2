"""coupling_counterfactual.py — E3 coupling 反事实评估器（SPEC-EMERGENCE-EVOLUTION v0.5 §4 E3）。

判据 M3：耦合模型（自项 + 跨域耦合项）对域状态下一窗口的预测 MAE，必须
显著低于消融模型（抽掉耦合项，仅自项）——置换检验 p<0.05 且方向为正。

β 原型教训（SPEC §1 E3）：上次 p=0.005 但方向为负——本评估器显式做方向检查，
方向为负且显著 → falsified，不得申报 candidate。

数据现实（2026-11-05 调研）：当前域状态序列样本稀疏且 psi 退化（uniq=1），
此时如实返回 insufficient_data，并可联动 E6 发数据需求单（不伪造结果）。

FAIL-OPEN：任何异常 → insufficient_data + reason，不向调用方抛出。
"""

from __future__ import annotations

import itertools
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_JSONL = [
    _REPO_ROOT / ".workbuddy" / "l1_training" / "domain_discovery_training.jsonl",
    _REPO_ROOT / ".workbuddy" / "l1_training" / "domain_discovery_training_real.jsonl",
]
RESULT_PATH = Path(__file__).resolve().parent / "counterfactual_result.json"

DOMAINS = ["cognition", "rea", "search", "semantic", "data", "eval"]
PAIRS = list(itertools.combinations(DOMAINS, 2))  # 与 23 域 domain_coupling_head.PAIRS 同序
_PAIR_IDX = {frozenset(p): i for i, p in enumerate(PAIRS)}
_DRIFT_LEVELS = {"stable": 0.0, "minor_drift": 0.5, "severe_drift": 1.0}

MIN_PAIRS_DEFAULT = 20


def pair_index(a: str, b: str) -> int:
    """域对 → 15 维 coupling 向量下标（顺序无关）。"""
    return _PAIR_IDX[frozenset((a, b))]


def _state_vector(domain_states: Dict[str, Any]) -> Optional[np.ndarray]:
    """单样本 → 6 维状态向量（psi 为主，缺失域用 drift level 兜底，皆缺返回 None）。"""
    vec = np.zeros(6, dtype=np.float64)
    for i, d in enumerate(DOMAINS):
        s = domain_states.get(d)
        if not isinstance(s, dict):
            return None
        psi = s.get("psi")
        if psi is None:
            psi = _DRIFT_LEVELS.get(s.get("drift", "stable"), 0.0)
        try:
            vec[i] = float(psi)
        except (TypeError, ValueError):
            return None
    return vec


def load_domain_state_series(jsonl_paths: Sequence[Path]) -> List[Dict[str, Any]]:
    """加载 JSONL → 按 timestamp 排序的 [{ts, state(6,)}]；坏行跳过，无 ts 排最后。"""
    rows: List[Dict[str, Any]] = []
    for path in jsonl_paths:
        path = Path(path)
        if not path.exists():
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
                ds = (r.get("input") or {}).get("domain_states")
                if not isinstance(ds, dict):
                    continue
                vec = _state_vector(ds)
                if vec is None:
                    continue
                rows.append({"ts": str(r.get("timestamp") or ""), "state": vec})
        except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
            logger.warning("读取 %s 失败（跳过）: %s", path, exc)
    rows.sort(key=lambda r: r["ts"])
    # 去重：完全相同时间戳的批量复制样本只保留一条（real JSONL 85 条同 ts 现状）
    deduped: List[Dict[str, Any]] = []
    seen: set = set()
    for r in rows:
        key = (r["ts"], r["state"].tobytes())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    return deduped


def build_transition_pairs(series: Sequence[Dict[str, Any]]) -> Tuple[np.ndarray, np.ndarray]:
    """连续窗口 → (X, Y) 转移对。X[t]=state_t, Y[t]=state_{t+1}。"""
    states = np.asarray([r["state"] for r in series], dtype=np.float64)
    if states.shape[0] < 2:
        return np.zeros((0, 6)), np.zeros((0, 6))
    return states[:-1], states[1:]


def _ridge_fit(X: np.ndarray, Y: np.ndarray, lam: float = 1e-3) -> np.ndarray:
    """对角 ridge：每域独立拟合 α_a = Σx·y/(Σx²+λ)，W 为 6×6 对角阵。

    必须对角（TDD 回归教训）：全矩阵 W 会让模型通过 x_b 的系数偷偷学到跨域项，
    错误耦合被拟合吸收，ablated/coupled 对比失真。对角约束保证两模型的唯一
    差别就是显式耦合项的有无——这才是"抽掉耦合项"的严格反事实。
    """
    n_dom = X.shape[1]
    w = np.zeros(n_dom)
    for a in range(n_dom):
        xa = X[:, a]
        w[a] = float(xa @ Y[:, a]) / float(xa @ xa + lam)
    return np.diag(w)


def _coupling_feature(x: np.ndarray, coupling: np.ndarray) -> np.ndarray:
    """单样本 6 维 → 每域的耦合加权跨域项 Σ_{b≠a} c_ab·x_b。"""
    cross = np.zeros(6, dtype=np.float64)
    for idx, (a, b) in enumerate(PAIRS):
        ia, ib = DOMAINS.index(a), DOMAINS.index(b)
        c = coupling[idx]
        cross[ia] += c * x[ib]
        cross[ib] += c * x[ia]
    return cross


def _fit_predict(
    Xtr: np.ndarray, Ytr: np.ndarray, Xte: np.ndarray, coupling: np.ndarray, coupled: bool
) -> np.ndarray:
    """拟合并预测。两模型都只拟合自项系数 α（6 维对角），唯一差别是耦合项有无：

    coupled: ŷ_a = α_a·x_a + Σ_{b≠a} c_ab·x_b   （耦合项系数固定=1，c 来自 head）
    ablated: ŷ_a = α_a·x_a                       （抽掉耦合项）

    系数固定的原因（TDD 回归教训）：若耦合项系数也参与拟合，错误的 c 会被拟合
    吸收（β 翻号补偿），反事实检验失真——耦合值本身的预测力必须原样接受检验。
    """
    if coupled:
        off_tr = np.asarray([_coupling_feature(x, coupling) for x in Xtr])
        off_te = np.asarray([_coupling_feature(x, coupling) for x in Xte])
        W = _ridge_fit(Xtr, Ytr - off_tr)  # 残差上拟合 α
        return Xte @ W + off_te
    W = _ridge_fit(Xtr, Ytr)
    return Xte @ W


def _permutation_p(diffs: np.ndarray, n_perm: int, seed: int) -> Tuple[float, float]:
    """符号翻转置换检验。返回 (two_sided_p, observed_median)。diffs = ablated − coupled。"""
    observed = float(np.median(diffs))
    if diffs.size == 0 or not np.all(np.isfinite(diffs)):
        return 1.0, observed
    rng = np.random.default_rng(seed)
    count = 1  # 加一平滑
    for _ in range(n_perm):
        signs = rng.choice((-1.0, 1.0), size=diffs.size)
        perm = float(np.median(diffs * signs))
        if abs(perm) >= abs(observed):
            count += 1
    return count / (n_perm + 1), observed


def evaluate_counterfactual(
    X: Optional[np.ndarray],
    Y: Optional[np.ndarray],
    coupling_vector: Optional[Sequence[float]],
    min_pairs: int = MIN_PAIRS_DEFAULT,
    n_perm: int = 10000,
    seed: int = 42,
    train_frac: float = 0.7,
) -> Dict[str, Any]:
    """E3 反事实主评估。返回 verdict + MAE + p + 方向；FAIL-OPEN → insufficient_data。"""
    try:
        if X is None or Y is None or coupling_vector is None:
            return {"verdict": "insufficient_data", "reason": "missing_input", "n_pairs": 0}
        X = np.asarray(X, dtype=np.float64)
        Y = np.asarray(Y, dtype=np.float64)
        coupling = np.asarray(coupling_vector, dtype=np.float64)
        n = int(X.shape[0])
        if X.shape != Y.shape or coupling.shape[0] != 15:
            return {"verdict": "insufficient_data", "reason": "shape_mismatch", "n_pairs": n}
        if n < min_pairs:
            return {
                "verdict": "insufficient_data",
                "reason": f"n_pairs={n} < min_pairs={min_pairs}",
                "n_pairs": n,
            }
        # 退化方差：任一域的时间维度变化 ~0（real JSONL psi uniq=1 现状），无信号可学。
        # 注意必须按列（每域沿时间轴）判定——全域 std 会把列间水平差误判为有信号。
        if float(Y.std(axis=0).max()) < 1e-8:
            return {
                "verdict": "insufficient_data",
                "reason": "degenerate_variance: Y 近常数，无预测信号",
                "n_pairs": n,
            }

        split = max(1, min(n - 1, int(n * train_frac)))
        Xtr, Ytr, Xte, Yte = X[:split], Y[:split], X[split:], Y[split:]

        pred_c = _fit_predict(Xtr, Ytr, Xte, coupling, coupled=True)
        pred_a = _fit_predict(Xtr, Ytr, Xte, coupling, coupled=False)
        # 每样本 MAE（6 域均值）→ 配对差
        mae_c = np.abs(pred_c - Yte).mean(axis=1)
        mae_a = np.abs(pred_a - Yte).mean(axis=1)
        diffs = mae_a - mae_c  # >0 表示 coupled 更好
        p_value, observed = _permutation_p(diffs, n_perm=n_perm, seed=seed)
        direction_positive = observed > 0

        if p_value < 0.05 and direction_positive:
            verdict = "e3_candidate"
        elif p_value < 0.05 and not direction_positive:
            verdict = "falsified"
        else:
            verdict = "inconclusive"
        return {
            "verdict": verdict,
            "n_pairs": n,
            "n_oos": int(Xte.shape[0]),
            "mae_coupled": round(float(mae_c.mean()), 6),
            "mae_ablated": round(float(mae_a.mean()), 6),
            "median_improvement": round(observed, 6),
            "median_improvement_pct": round(
                float(observed / mae_a.mean() * 100) if mae_a.mean() > 1e-12 else 0.0, 3
            ),
            "p_value": round(p_value, 5),
            "direction_positive": direction_positive,
            "n_perm": n_perm,
            "train_frac": train_frac,
        }
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        logger.warning("evaluate_counterfactual 异常（降级 insufficient_data）: %s", exc)
        return {"verdict": "insufficient_data", "reason": f"exception: {exc}", "n_pairs": 0}


def file_gap_if_insufficient(result: Dict[str, Any], gaps_path: Optional[Path] = None) -> bool:
    """insufficient_data 或纯静态先验耦合 → 联动 E6 发数据需求单（stigmergy）。

    第二种触发（2026-11-06 补）：当前 verdict=falsified 但 coupling_source=static_json
    （生产静态耦合系数、76% 样本为 static_fill 合成）时，结论建立在合成先验上，
    仍需真实域状态时序复核——故与 insufficient_data 同等发单。
    """
    verdict = result.get("verdict")
    static_prior = result.get("coupling_source") == "static_json"
    if verdict != "insufficient_data" and not static_prior:
        return False
    try:
        import sys

        _reg = str(_REPO_ROOT / "48-涌现架构" / "registry")
        if _reg not in sys.path:
            sys.path.insert(0, _reg)
        import capability_gaps as cg

        # 同类型 open/claimed 单不重复发（stigmergy 去重，与 E2/E4b 一致）
        try:
            existing = cg.load_gaps(path=gaps_path)
            if any(
                g.get("gap_type") == "domain_state_series_missing"
                and g.get("status") in ("open", "claimed")
                for g in existing
            ):
                logger.info("E3 缺口单已存在（%s），跳过重复发单", "domain_state_series_missing")
                return False
        except Exception as exc:  # noqa: BLE001 — 去重失败不阻塞发单
            logger.warning("缺口单去重检查失败（继续发单）: %s", exc)

        gap = cg.new_gap(
            gap_type="domain_state_series_missing",
            evidence={
                "source": "e3_counterfactual",
                "reason": result.get("reason", ""),
                "n_pairs": result.get("n_pairs", 0),
                "need": "带时间戳且有真实变化的域状态窗口序列（6 域 psi/drift），用于 E3 反事实 MAE 检验",
                "observed": "现有 236 行仅有 4 个唯一时间戳（全部 2026-11-03 10:28~12:46 单批导出），"
                "training_real.jsonl 85 行同一时刻，psi 仅 3 个唯一值（0/0.44/1.0）→ 无时序可回填",
            },
            expected_value="E3 反事实评估可从 insufficient_data 转为可判定（candidate/falsified/inconclusive）",
            target_domain_hint="4-MEMORY/9-工具与接口:collect_domain_discovery_data",
            created_by="e3_counterfactual",
        )
        return cg.append_gap(gap, path=gaps_path)
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        logger.warning("发 E6 需求单失败（降级）: %s", exc)
        return False


def run(
    jsonl_paths: Optional[Sequence[Path]] = None,
    coupling_vector: Optional[Sequence[float]] = None,
    min_pairs: int = MIN_PAIRS_DEFAULT,
    n_perm: int = 10000,
    seed: int = 42,
    result_path: Path = RESULT_PATH,
    file_gap: bool = True,
) -> Dict[str, Any]:
    """端到端：加载序列 → 评估 → 落盘结果 → 必要时发 E6 需求单。"""
    paths = list(jsonl_paths) if jsonl_paths else DEFAULT_JSONL
    series = load_domain_state_series(paths)
    X, Y = build_transition_pairs(series)
    if coupling_vector is None:
        # 默认用生产 static JSON 的 15 维 coupling（只读）
        static_json = (
            _REPO_ROOT / "mcp_shells" / "_shared" / "assets" / "domain_transmission_static.json"
        )
        coupling_vector = _load_static_coupling(static_json)
    result = evaluate_counterfactual(
        X, Y, coupling_vector, min_pairs=min_pairs, n_perm=n_perm, seed=seed
    )
    result.update(
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "data_sources": [str(p) for p in paths],
            "n_series_raw": len(series),
            "coupling_source": "static_json" if coupling_vector is not None else "none",
            "spec": "SPEC-EMERGENCE-EVOLUTION v0.5 §4 E3",
        }
    )
    if file_gap:
        result["gap_filed"] = file_gap_if_insufficient(result)
    try:
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("结果落盘失败: %s", exc)
    return result


def _load_static_coupling(static_json: Path) -> Optional[List[float]]:
    """从生产 static JSON 读 15 维 coupling（只读，顺序对齐 PAIRS）。"""
    try:
        data = json.loads(Path(static_json).read_text(encoding="utf-8"))
        couplings = data.get("domain_transmission", {}).get("drift_coupling", {})
        out: List[float] = []
        for a, b in PAIRS:
            entry = couplings.get(f"{a}↔{b}") or couplings.get(f"{b}↔{a}")
            if entry is None:
                return None
            out.append(float(entry["coupling"]))
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("static coupling 读取失败: %s", exc)
        return None


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="E3 coupling 反事实评估")
    parser.add_argument("--min-pairs", type=int, default=MIN_PAIRS_DEFAULT)
    parser.add_argument("--n-perm", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--no-gap", action="store_true", help="insufficient_data 时不发 E6 需求单")
    args = parser.parse_args()
    res = run(
        min_pairs=args.min_pairs, n_perm=args.n_perm, seed=args.seed, file_gap=not args.no_gap
    )
    print(json.dumps(res, ensure_ascii=False, indent=2))
