"""β 原型验证：路径签名时序特征是否带来真实增量（F1/F2/F3 预演）。

数据源：云端持续运行的真实事件流
  39/semantic_events.jsonl（按 term 分流的交易决策口径）
  39/atomic_events.jsonl （按 category 分流的市场指标口径）
两条流都持续运行、时间对齐、事件驱动，用来在"还没有 L0 六域轨迹"时提前验证方法。

验证三项：
  F1  消融：baseline（均值/方差/末值/斜率/计数）vs baseline+签名，比较下一窗目标 MAE
  F2  随机对照：baseline+同维随机向量（置换 200 次），若与真签名无显著差异则增量来自参数而非时序
  F3  lead-lag：窗口 Lévy area（2D 签名反对称项）符号 vs 互相关峰值滞后符号的一致率

硬约束（SPEC-L0-L1-DOMAIN-DISCOVERY §4.6）：
  T1 零训练——只用 Ridge 闭式解，不训练任何网络
  T2 无 look-ahead——归一化统计量只用当前 bin 之前的历史（shift 1）
  T3 FAIL-OPEN——缺数据/稀疏流自动剔除，不抛错
"""

from __future__ import annotations

import importlib.util
import itertools
import json
from datetime import datetime
from pathlib import Path

import numpy as np

DATA = Path(__file__).parent / "data"
ROOT = Path(__file__).resolve().parents[3]
BIN_MINUTES = 60
WINDOW = 8  # 8 小时路径窗口
GAP = 1  # 训练/测试间隔 1 bin
N_FOLDS = 5
N_PERM = 200
RANDOM_SEED = 20261103
MIN_COVERAGE = 0.50  # 流入选门槛：非空 bin 占比
MIN_BINS = 100  # 绝对样本量门槛


def load_signature_engine():
    """直接加载现网 signature_engine.py（绕过包 __init__ 的重依赖）。"""
    path = (
        ROOT / "23-四层闭环自进化交易架构" / "dreambuddy_evolution" / "core" / "signature_engine.py"
    )
    spec = importlib.util.spec_from_file_location("_sig_engine", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.SignatureEngine(depth=3)


def parse_rows(fname: str, group_key: str):
    """读取事件流，统一为 (group, ts, value)。"""
    out = []
    with (DATA / fname).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            group = r.get(group_key)
            if not group:
                continue
            raw = r.get("value")
            if raw is None:
                raw = (r.get("values") or [None])[0]
            try:
                v = float(raw)
            except (TypeError, ValueError):
                continue
            try:
                ts = datetime.fromisoformat(str(r["timestamp"]).replace("Z", "+00:00")).timestamp()
            except (KeyError, ValueError):
                continue
            out.append((str(group), ts, v))
    return out


def build_grids(rows):
    """事件流 → 等宽 bin 网格（同组同 bin 取均值），返回 {group: (arr, real_mask)}。"""
    t0, t1 = min(r[1] for r in rows), max(r[1] for r in rows)
    nbins = int((t1 - t0) // (BIN_MINUTES * 60)) + 1
    acc = {}
    for group, ts, v in rows:
        i = int((ts - t0) // (BIN_MINUTES * 60))
        acc.setdefault(group, [[] for _ in range(nbins)])[i].append(v)
    grids = {}
    for group, buckets in acc.items():
        arr = np.full(nbins, np.nan)
        for i, vals in enumerate(buckets):
            if vals:
                arr[i] = float(np.mean(vals))
        grids[group] = arr
    return grids


def forward_fill(arr, limit=2):
    """限长前向填充（避免长空档造出伪平线）。"""
    out = arr.copy()
    run = 0
    for i in range(1, len(out)):
        if np.isnan(out[i]):
            run += 1
            if run <= limit and not np.isnan(out[i - 1]):
                out[i] = out[i - 1]
        else:
            run = 0
    return out


def expanding_z(arr):
    """扩展窗口 z-score，统计量只用当前位置之前的历史（无 look-ahead）。"""
    n = len(arr)
    z = np.full(n, np.nan)
    for i in range(n):
        hist = arr[:i]
        hist = hist[~np.isnan(hist)]
        if len(hist) < 10:
            continue
        mu, sd = float(np.mean(hist)), float(np.std(hist))
        if sd < 1e-8:
            continue
        z[i] = (arr[i] - mu) / sd
    return z


def make_signature(engine, zwin):
    sig = engine.signature(zwin)
    return sig if len(sig) else np.zeros(engine.depth)


def window_features(z, i):
    """baseline 窗口特征（= mean-pool 等价物：均值/方差/末值/斜率/计数）。"""
    win = z[i - WINDOW + 1 : i + 1]
    if np.any(np.isnan(win)):
        return None
    slope = float(np.polyfit(np.arange(len(win)), win, 1)[0])
    return np.array(
        [float(np.mean(win)), float(np.std(win)), float(win[-1]), slope, float(len(win))]
    )


def _ridge_solve(X, y, alpha):
    return np.linalg.solve(X.T @ X + alpha * np.eye(X.shape[1]), X.T @ y)


def ridge_fit_predict(Xtr, ytr, Xte):
    """Ridge 闭式解，alpha 由训练集内部 70/30 时间切分选择（不碰测试集）。"""
    cut = max(10, int(len(Xtr) * 0.7))
    best = None
    for alpha in (1e-3, 1e-2, 1e-1, 1.0, 10.0):
        Xa, ya = Xtr[:cut], ytr[:cut]
        Xb, yb = Xtr[cut:], ytr[cut:]
        if len(Xb) < 3:
            continue
        mu, sd = Xa.mean(0), Xa.std(0) + 1e-8
        ym = ya.mean()
        w = _ridge_solve((Xa - mu) / sd, ya - ym, alpha)
        mae = float(np.mean(np.abs(((Xb - mu) / sd) @ w + ym - yb)))
        if best is None or mae < best[0]:
            best = (mae, alpha)
    alpha = best[1]
    mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-8
    ym = ytr.mean()
    w = _ridge_solve((Xtr - mu) / sd, ytr - ym, alpha)
    return ((Xte - mu) / sd) @ w + ym


def fold_mae(X, y):
    """扩展窗口 walk-forward：5 折，训练集只含测试块之前的数据。"""
    n, step = len(y), max(20, len(y) // (N_FOLDS + 1))
    out = []
    for k in range(N_FOLDS):
        te_end = n - step * (N_FOLDS - 1 - k)
        tr_end = te_end - step - GAP
        if tr_end < 40:
            continue
        pred = ridge_fit_predict(X[:tr_end], y[:tr_end], X[te_end - step : te_end])
        out.append(float(np.mean(np.abs(pred - y[te_end - step : te_end]))))
    return float(np.mean(out)) if out else float("nan")


def cross_corr_lag(a, b, max_lag=8):
    """a 领先 b 的最优滞后（正 = a 领先，单位 bin）。"""
    best = (0.0, 0)
    for lag in range(-max_lag, max_lag + 1):
        x, y = (a[: len(a) - lag], b[lag:]) if lag >= 0 else (a[-lag:], b[: len(b) + lag])
        if len(x) < 20:
            continue
        c = float(np.corrcoef(x, y)[0, 1])
        if abs(c) > abs(best[0]):
            best = (c, lag)
    return best[1]


def levy_area(a, b):
    """2D 路径 Lévy area（签名二级反对称项），符号编码 lead-lag 方向。"""
    da, db = np.diff(a), np.diff(b)
    return float(np.sum(a[:-1] * db - b[:-1] * da))


def run_dataset(name, group_key, engine, rng):
    rows = parse_rows(name, group_key)
    if not rows:
        return None
    grids = build_grids(rows)
    nbins = len(next(iter(grids.values())))
    selected, rejected = [], {}
    for group, arr in grids.items():
        cov = float(np.mean(~np.isnan(arr)))
        if cov >= MIN_COVERAGE and int(np.sum(~np.isnan(arr))) >= MIN_BINS:
            selected.append(group)
        else:
            rejected[group] = round(cov, 3)

    z = {g: expanding_z(forward_fill(grids[g])) for g in selected}
    real = {g: ~np.isnan(grids[g]) for g in selected}

    pair_rows, f3 = [], []
    for a, b in itertools.combinations(sorted(selected), 2):
        Xb, Xs, ys = [], [], []
        for i in range(WINDOW - 1, nbins - 1):
            ok_a = np.sum(real[a][i - WINDOW + 1 : i + 1]) >= 0.6 * WINDOW
            ok_b = np.sum(real[b][i - WINDOW + 1 : i + 1]) >= 0.6 * WINDOW
            if not (ok_a and ok_b) or np.isnan(z[b][i + 1]):
                continue
            base = window_features(z[a], i)
            if base is None:
                continue
            Xb.append(base)
            Xs.append(np.concatenate([base, make_signature(engine, z[a][i - WINDOW + 1 : i + 1])]))
            ys.append(z[b][i + 1])
        if len(ys) < 60:
            continue
        Xb, Xs, y = map(np.asarray, (Xb, Xs, ys))
        m_base, m_sig = fold_mae(Xb, y), fold_mae(Xs, y)
        dim = Xs.shape[1] - Xb.shape[1]
        Xr = np.concatenate([Xb, rng.standard_normal((len(y), dim))], axis=1)
        m_rand = fold_mae(Xr, y)

        # F2：打乱签名（行置换）200 次，看有多少次能达到真签名的改善幅度
        target = m_sig
        hits = 0
        for _ in range(N_PERM):
            idx = rng.permutation(len(y))
            Xp = np.concatenate([Xb, Xs[:, Xb.shape[1] :][idx]], axis=1)
            if fold_mae(Xp, y) <= target:
                hits += 1
        p_val = hits / N_PERM

        valid = ~np.isnan(z[a]) & ~np.isnan(z[b])
        za, zb = z[a][valid], z[b][valid]
        lag = cross_corr_lag(za, zb)
        area = np.sign(levy_area(za, zb)) if len(za) > 2 else 0
        f3.append(int(area) == (0 if lag == 0 else int(np.sign(lag))))

        pair_rows.append(
            {
                "pair": f"{a}→{b}",
                "n": int(len(y)),
                "mae_base": round(m_base, 4),
                "mae_sig": round(m_sig, 4),
                "mae_rand": round(m_rand, 4),
                "improve_pct": round(100 * (m_base - m_sig) / m_base, 2),
                "rand_improve_pct": round(100 * (m_base - m_rand) / m_base, 2),
                "perm_p": round(p_val, 3),
                "lag_bins": int(lag),
            }
        )

    if not pair_rows:
        return {
            "dataset": name,
            "bins": nbins,
            "selected": selected,
            "rejected": rejected,
            "pairs": [],
        }

    improve = [r["improve_pct"] for r in pair_rows]
    pvals = [r["perm_p"] for r in pair_rows]
    sig_dim = int(len(make_signature(engine, np.zeros(WINDOW))))
    return {
        "dataset": name,
        "bins": nbins,
        "signature_dim": sig_dim,
        "selected": selected,
        "rejected_coverage": rejected,
        "pairs": pair_rows,
        "windows_mean": round(float(np.mean([r["n"] for r in pair_rows])), 1),
        "mean_improve_pct": round(float(np.mean(improve)), 2),
        "median_improve_pct": round(float(np.median(improve)), 2),
        "pairs_improved_ge10": int(sum(1 for v in improve if v >= 10)),
        "pairs_rand_worse_or_equal": int(
            sum(1 for r in pair_rows if r["improve_pct"] > r["rand_improve_pct"])
        ),
        "pairs_p_lt_005": int(sum(1 for p in pvals if p < 0.05)),
        "f3_agreement_pct": round(100 * float(np.mean(f3)), 1) if f3 else None,
    }


def main():
    rng = np.random.default_rng(RANDOM_SEED)
    engine = load_signature_engine()
    results = [
        r
        for r in (
            run_dataset("semantic_events.jsonl", "term", engine, rng),
            run_dataset("atomic_events.jsonl", "category", engine, rng),
        )
        if r
    ]
    verdict = {}
    for r in results:
        rows = r["pairs"]
        if rows:
            verdict[r["dataset"]] = {
                "F1_median_improve_ge10": bool(r["median_improve_pct"] >= 10),
                "F2_significant_pairs": f"{r['pairs_p_lt_005']}/{len(rows)}",
                "F3_agreement_ge80": bool((r["f3_agreement_pct"] or 0) >= 80),
            }
        else:
            verdict[r["dataset"]] = "insufficient_streams"
    out = {
        "params": {
            "bin_minutes": BIN_MINUTES,
            "window": WINDOW,
            "folds": N_FOLDS,
            "perms": N_PERM,
            "min_coverage": MIN_COVERAGE,
        },
        "results": results,
        "verdict": verdict,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    (Path(__file__).parent / "beta_result.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
