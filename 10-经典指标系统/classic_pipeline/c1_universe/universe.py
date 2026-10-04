"""C1 品种筛选 — 纯计算函数集合。

所有函数均为纯函数：不依赖全局状态（CONFIG/UNIVERSE_STATE）、不调用数据源（_hl_*）。
依赖仅限于 math / numpy。
"""

import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

__all__ = [
    "_universe_beta_from_ret",
    "_universe_pair_aliases",
    "_universe_pearson_corr",
    "_universe_rankdata",
    "_universe_spearman_corr",
    "_universe_tf_ms",
    "_universe_kmeans_assign",
    "_universe_ari_nmi",
    "_compute_btc_corr_from_closes",
]


def _universe_beta_from_ret(x: "np.ndarray", y: "np.ndarray") -> Optional[float]:
    try:
        if x.size < 10 or y.size < 10:
            return None
        xv = float(np.var(x))
        if (not math.isfinite(float(xv))) or float(xv) <= 0.0:
            return None
        cov = float(np.mean((x - float(np.mean(x))) * (y - float(np.mean(y)))))
        b = cov / xv
        if not math.isfinite(float(b)):
            return None
        return float(b)
    except Exception:
        return None


def _universe_pair_aliases(pair: str) -> List[str]:
    p = str(pair or "").strip()
    if not p:
        return []
    p = p.replace(":USDT", "").replace(":USDC", "")
    out: List[str] = []
    if p not in out:
        out.append(p)
    try:
        coin0 = ""
        if "/" in p:
            coin0 = str(p.split("/", 1)[0] or "").strip()
        elif p.endswith("USDT") and len(p) > 4:
            coin0 = str(p[:-4] or "").strip()
        elif p.endswith("USDC") and len(p) > 4:
            coin0 = str(p[:-4] or "").strip()
        else:
            coin0 = str(p).strip()
    except Exception:
        coin0 = ""
    if coin0:
        for x in (
            coin0,
            f"{coin0}-PERP",
            f"{coin0}_PERP",
            f"{coin0}/USDT:USDT",
            f"{coin0}/USDT",
            f"{coin0}USDT",
            f"{coin0}_USDT",
            f"{coin0}_USDT_USDT",
        ):
            xs = str(x or "").strip()
            if xs and xs not in out:
                out.append(xs)
    if "/" in p:
        p2 = p.replace("/", "")
        if p2 not in out:
            out.append(p2)
    else:
        if p.endswith("USDT") and (not p.endswith("/USDT")):
            coin = p[:-4]
            p2 = f"{coin}/USDT"
            if p2 not in out:
                out.append(p2)
        if p.endswith("USDC") and (not p.endswith("/USDC")):
            coin = p[:-4]
            p2 = f"{coin}/USDC"
            if p2 not in out:
                out.append(p2)
    return out


def _universe_pearson_corr(xs: List[float], ys: List[float]) -> Optional[float]:
    pairs: List[Tuple[float, float]] = []
    for a, b in zip(xs, ys):
        try:
            fa = float(a)
            fb = float(b)
            if math.isfinite(fa) and math.isfinite(fb):
                pairs.append((fa, fb))
        except Exception:
            continue
    if len(pairs) < 10:
        return None
    mx = sum(p[0] for p in pairs) / float(len(pairs))
    my = sum(p[1] for p in pairs) / float(len(pairs))
    sxx = 0.0
    syy = 0.0
    sxy = 0.0
    for a, b in pairs:
        da = float(a) - float(mx)
        db = float(b) - float(my)
        sxx += da * da
        syy += db * db
        sxy += da * db
    if (not math.isfinite(sxx)) or (not math.isfinite(syy)) or (not math.isfinite(sxy)):
        return None
    if sxx <= 0.0 or syy <= 0.0:
        return None
    try:
        return float(sxy) / float(math.sqrt(float(sxx) * float(syy)))
    except Exception:
        return None


def _universe_rankdata(values: List[float]) -> List[float]:
    n = int(len(values))
    if n <= 0:
        return []
    order = list(range(n))
    order.sort(key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i + 1
        v = values[order[i]]
        while j < n and values[order[j]] == v:
            j += 1
        avg = (float(i + 1) + float(j)) / 2.0
        for k in range(i, j):
            ranks[order[k]] = float(avg)
        i = j
    return ranks


def _universe_spearman_corr(xs: List[float], ys: List[float]) -> Optional[float]:
    pairs: List[Tuple[float, float]] = []
    for a, b in zip(xs, ys):
        try:
            fa = float(a)
            fb = float(b)
            if math.isfinite(fa) and math.isfinite(fb):
                pairs.append((fa, fb))
        except Exception:
            continue
    if len(pairs) < 10:
        return None
    ax = [p[0] for p in pairs]
    ay = [p[1] for p in pairs]
    rx = _universe_rankdata(ax)
    ry = _universe_rankdata(ay)
    return _universe_pearson_corr(rx, ry)


def _universe_tf_ms(timeframe: str) -> Optional[int]:
    tf = str(timeframe or "").strip().lower()
    if tf == "1h":
        return 3600 * 1000
    if tf == "30m":
        return 30 * 60 * 1000
    return None


def _universe_kmeans_assign(X: "np.ndarray", k: int, iters: int = 30) -> "np.ndarray":
    n = int(X.shape[0])
    if n <= 0:
        return np.zeros((0,), dtype=int)
    kk = int(min(max(1, int(k)), int(n)))
    if kk == 1:
        return np.zeros((n,), dtype=int)
    rng = np.random.RandomState(7)

    centers = np.zeros((kk, int(X.shape[1])), dtype=float)
    idx0 = int(rng.randint(0, n))
    centers[0] = X[idx0]
    d2 = np.sum((X - centers[0]) ** 2, axis=1)
    for j in range(1, kk):
        s = float(np.sum(d2))
        if (not math.isfinite(float(s))) or float(s) <= 0.0:
            centers[j] = X[int(rng.randint(0, n))]
            d2 = np.minimum(d2, np.sum((X - centers[j]) ** 2, axis=1))
            continue
        p = d2 / s
        try:
            idx = int(rng.choice(n, p=p))
        except Exception:
            idx = int(rng.randint(0, n))
        centers[j] = X[idx]
        d2 = np.minimum(d2, np.sum((X - centers[j]) ** 2, axis=1))

    labels = np.zeros((n,), dtype=int)
    for _ in range(int(max(1, iters))):
        dist = np.sum((X[:, None, :] - centers[None, :, :]) ** 2, axis=2)
        new_labels = np.argmin(dist, axis=1)
        if np.array_equal(new_labels, labels):
            break
        labels = new_labels
        for j in range(kk):
            m = labels == j
            if not bool(np.any(m)):
                centers[j] = X[int(rng.randint(0, n))]
                continue
            centers[j] = np.mean(X[m], axis=0)
    return labels


def _universe_ari_nmi(old_labels: List[int], new_labels: List[int]) -> Dict[str, Optional[float]]:
    out: Dict[str, Optional[float]] = {"ari": None, "nmi": None}
    try:
        if (not old_labels) or (not new_labels) or len(old_labels) != len(new_labels):
            return out
        n = int(len(old_labels))
        if n < 10:
            return out

        old_u = sorted(set(int(x) for x in old_labels))
        new_u = sorted(set(int(x) for x in new_labels))
        oi = {v: i for i, v in enumerate(old_u)}
        ni = {v: i for i, v in enumerate(new_u)}
        cont = np.zeros((len(old_u), len(new_u)), dtype=float)
        for a, b in zip(old_labels, new_labels):
            cont[oi[int(a)], ni[int(b)]] += 1.0

        def comb2(x: float) -> float:
            return float(x * (x - 1.0) * 0.5)

        sum_comb = float(np.sum([comb2(v) for v in cont.flatten()]))
        a = np.sum(cont, axis=1)
        b = np.sum(cont, axis=0)
        sum_comb_a = float(np.sum([comb2(v) for v in a]))
        sum_comb_b = float(np.sum([comb2(v) for v in b]))
        total = float(n)
        prod = (sum_comb_a * sum_comb_b) / comb2(total) if total > 1 else 0.0
        mean = 0.5 * (sum_comb_a + sum_comb_b)
        denom = mean - prod
        ari = None
        if math.isfinite(float(denom)) and float(denom) != 0.0:
            ari_v = (sum_comb - prod) / denom
            if math.isfinite(float(ari_v)):
                ari = float(ari_v)

        pxy = cont / total
        px = a / total
        py = b / total
        mi = 0.0
        for i in range(pxy.shape[0]):
            for j in range(pxy.shape[1]):
                v = float(pxy[i, j])
                if v <= 0.0:
                    continue
                den = float(px[i] * py[j])
                if den <= 0.0:
                    continue
                mi += v * float(math.log(v / den))
        hx = 0.0
        for v in px:
            vv = float(v)
            if vv > 0.0:
                hx -= vv * float(math.log(vv))
        hy = 0.0
        for v in py:
            vv = float(v)
            if vv > 0.0:
                hy -= vv * float(math.log(vv))
        nmi = None
        den = float(hx * hy)
        if den > 0.0 and math.isfinite(float(den)):
            nmi_v = mi / float(math.sqrt(den))
            if math.isfinite(float(nmi_v)):
                nmi = float(nmi_v)

        out["ari"] = ari
        out["nmi"] = nmi
        return out
    except Exception:
        return out


def _compute_btc_corr_from_closes(
    a_close: Dict[int, float],
    b_close: Dict[int, float],
    method: str,
    n: int,
) -> Dict[str, Any]:
    """从两个币种的收盘价序列计算相关性（纯函数）。

    从 _universe_btc_corr_custom 拆分而来：数据获取（_universe_pair_close_by_ts）
    留在单体，本函数只负责 log-return 序列构建 + 相关性计算。
    """
    out: Dict[str, Any] = {"corr": None}
    if not a_close or not b_close:
        return out
    ts = sorted(set(a_close.keys()) & set(b_close.keys()))
    if len(ts) < int(n + 2):
        return out
    ts = ts[-int(n + 2) :]
    ax: List[float] = []
    bx: List[float] = []
    for t0, t1 in zip(ts[:-1], ts[1:]):
        try:
            ca0 = float(a_close.get(int(t0)) or 0.0)
            ca1 = float(a_close.get(int(t1)) or 0.0)
            cb0 = float(b_close.get(int(t0)) or 0.0)
            cb1 = float(b_close.get(int(t1)) or 0.0)
            if ca0 > 0.0 and ca1 > 0.0 and cb0 > 0.0 and cb1 > 0.0:
                ax.append(float(math.log(ca1 / ca0)))
                bx.append(float(math.log(cb1 / cb0)))
        except Exception:
            continue
    mm = str(method or "").strip().lower()
    if mm == "spearman":
        corr = _universe_spearman_corr(ax, bx)
    else:
        corr = _universe_pearson_corr(ax, bx)
    if corr is not None:
        out["corr"] = float(corr)
    return out
