import argparse
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _safe_float(x: object, d: float = 0.0) -> float:
    try:
        v = float(x)  # type: ignore[arg-type]
    except Exception:
        return float(d)
    if v != v:
        return float(d)
    if v in (float("inf"), float("-inf")):
        return float(d)
    return float(v)


def _load_ohlcv(path: Path) -> Dict[str, List[float]]:
    arr = json.loads(path.read_text(encoding="utf-8"))
    ts: List[float] = []
    op: List[float] = []
    hi: List[float] = []
    lo: List[float] = []
    cl: List[float] = []
    vol: List[float] = []
    for row in arr if isinstance(arr, list) else []:
        if not isinstance(row, list) or len(row) < 6:
            continue
        c = _safe_float(row[4], 0.0)
        if c <= 1000.0:
            continue
        ts.append(_safe_float(row[0], 0.0))
        op.append(_safe_float(row[1], c))
        hi.append(_safe_float(row[2], c))
        lo.append(_safe_float(row[3], c))
        cl.append(c)
        vol.append(_safe_float(row[5], 0.0))
    return {"ts": ts, "open": op, "high": hi, "low": lo, "close": cl, "volume": vol}


def _ema(xs: List[float], span: int) -> List[float]:
    if len(xs) <= 0:
        return []
    alpha = 2.0 / (float(span) + 1.0)
    out: List[float] = []
    last = float(xs[0])
    out.append(last)
    for i in range(1, len(xs)):
        v = float(xs[i]) * alpha + float(last) * (1.0 - alpha)
        out.append(v)
        last = v
    return out


def _rolling_mean(xs: List[float], n: int) -> List[float]:
    out: List[float] = []
    s = 0.0
    q: List[float] = []
    for i, x in enumerate(xs):
        v = float(x)
        q.append(v)
        s += v
        if len(q) > int(n):
            s -= q.pop(0)
        if len(q) < int(n):
            out.append(s / float(len(q)))
        else:
            out.append(s / float(n))
        _ = i
    return out


def _build_features(data: Dict[str, List[float]]) -> Dict[str, List[float]]:
    cl = data["close"]
    hi = data["high"]
    lo = data["low"]
    n = len(cl)
    ema20 = _ema(cl, 20)
    ema100 = _ema(cl, 100)
    tr: List[float] = []
    for i in range(n):
        h = float(hi[i])
        l = float(lo[i])
        pc = float(cl[i - 1]) if i > 0 else float(cl[i])
        tr.append(max(abs(h - l), abs(h - pc), abs(l - pc)))
    atr = _rolling_mean(tr, 14)
    atr_pct = [max(1e-4, (atr[i] / cl[i] if cl[i] != 0 else 1e-4)) for i in range(n)]
    plus_dm: List[float] = [0.0]
    minus_dm: List[float] = [0.0]
    for i in range(1, n):
        up = float(hi[i] - hi[i - 1])
        dn = float(lo[i - 1] - lo[i])
        plus_dm.append(up if (up > dn and up > 0) else 0.0)
        minus_dm.append(dn if (dn > up and dn > 0) else 0.0)
    tr14 = _rolling_mean(tr, 14)
    plus14 = _rolling_mean(plus_dm, 14)
    minus14 = _rolling_mean(minus_dm, 14)
    dx: List[float] = []
    for i in range(n):
        den = plus14[i] + minus14[i]
        if den <= 0:
            dx.append(0.0)
        else:
            dx.append(abs(plus14[i] - minus14[i]) / den * 100.0)
    adx = _rolling_mean(dx, 14)
    out = dict(data)
    out["ema20"] = ema20
    out["ema100"] = ema100
    out["atr_pct"] = atr_pct
    out["adx"] = adx
    return out


def _regime_by_adx(adx_value: float, threshold: float) -> str:
    return "trend" if float(adx_value) >= float(threshold) else "chop"


def _tstp_mult(age_hours: float, regime: str) -> float:
    trend_plan = [(1.0, 6.0), (6.0, 5.0), (12.0, 4.0), (48.0, 3.0), (96.0, 2.5)]
    chop_plan = [(1.0, 4.0), (6.0, 3.0), (12.0, 2.5), (48.0, 2.0), (96.0, 1.5)]
    plan = trend_plan if regime == "trend" else chop_plan
    if age_hours <= plan[0][0]:
        return float(plan[0][1])
    for i in range(1, len(plan)):
        x0, y0 = plan[i - 1]
        x1, y1 = plan[i]
        if age_hours <= x1:
            w = (age_hours - x0) / max(1e-9, (x1 - x0))
            return float(y0 * (1.0 - w) + y1 * w)
    return float(plan[-1][1])


def _entry_indices(data: Dict[str, List[float]]) -> Tuple[List[int], List[int]]:
    n = len(data["close"])
    sig: List[int] = []
    for i in range(n):
        sig.append(1 if data["ema20"][i] > data["ema100"][i] else -1)
    entries: List[int] = []
    for i in range(1, n):
        if sig[i] != sig[i - 1] and i > 120:
            entries.append(i)
    return sig, entries


def _run_backtest(
    data: Dict[str, List[float]],
    sig: List[int],
    entries: List[int],
    target_regime: str,
    adx_threshold: float,
    cfg: Dict[str, float],
) -> Optional[Dict[str, float]]:
    rets: List[float] = []
    for ent in entries:
        regime = _regime_by_adx(float(data["adx"][ent]), adx_threshold)
        if regime != target_regime:
            continue
        side = int(sig[ent])
        entry = float(data["close"][ent])
        atr_pct = float(data["atr_pct"][ent])
        mfe = 0.0
        armed = False
        trade_ret: Optional[float] = None
        max_hold = int(cfg["max_hold_bars"])
        end = min(len(data["close"]), ent + max_hold + 1)
        for i in range(ent + 1, end):
            c = float(data["close"][i])
            h = float(data["high"][i])
            l = float(data["low"][i])
            pnl = (c - entry) / entry * side
            hi = (h - entry) / entry * side
            lo = (l - entry) / entry * side
            inst_max = max(hi, lo, pnl)
            inst_min = min(hi, lo, pnl)
            mfe = max(mfe, inst_max)
            dd = (mfe - pnl) if mfe > 0.0 else 0.0
            sl = max(float(cfg["sl_min_pct"]), atr_pct * float(cfg["sl_atr_mult"]))
            if inst_min <= -sl:
                trade_ret = -sl
                break
            age_h = (i - ent) * 5.0 / 60.0
            tp_mult = _tstp_mult(age_h, target_regime)
            tp = max(float(cfg["tp_min_pct"]), atr_pct * tp_mult)
            if (not armed) and inst_max >= tp:
                armed = True
            if armed and mfe >= float(cfg["trail_arm_pct"]) and dd >= float(cfg["trail_retrace_pct"]):
                trade_ret = max(pnl, 0.0)
                break
        if trade_ret is None:
            j = min(len(data["close"]) - 1, ent + max_hold)
            px = float(data["close"][j])
            trade_ret = (px - entry) / entry * side
        rets.append(float(trade_ret))
    if len(rets) <= 0:
        return None
    gp = 0.0
    gl = 0.0
    wins = 0
    for x in rets:
        if x > 0.0:
            gp += x
            wins += 1
        elif x < 0.0:
            gl += (-x)
    pf = float(gp / gl) if gl > 1e-12 else 9.99
    eq = 0.0
    peak = 0.0
    maxdd = 0.0
    for x in rets:
        eq += x
        if eq > peak:
            peak = eq
        dd = peak - eq
        if dd > maxdd:
            maxdd = dd
    winrate = float(wins / len(rets))
    avg = float(sum(rets) / len(rets))
    score = float(avg * 10000.0 + pf * 10.0 - maxdd * 1000.0)
    return {
        "n": float(len(rets)),
        "avg_ret": avg,
        "pf": pf,
        "winrate": winrate,
        "maxdd": maxdd,
        "score": score,
    }


def _search(
    data: Dict[str, List[float]],
    sig: List[int],
    entries: List[int],
    target_regime: str,
    adx_threshold: float,
) -> List[Dict[str, object]]:
    if target_regime == "trend":
        grid = [
            (sa, sm, tm, ta, td, 288)
            for sa in (4.0, 5.0, 6.0, 7.0)
            for sm in (0.02, 0.03, 0.04)
            for tm in (0.03, 0.04, 0.05, 0.06)
            for ta in (0.02, 0.03, 0.04)
            for td in (0.35, 0.45, 0.55)
        ]
    else:
        grid = [
            (sa, sm, tm, ta, td, 144)
            for sa in (2.5, 3.0, 3.5, 4.0)
            for sm in (0.015, 0.02, 0.025, 0.03)
            for tm in (0.015, 0.02, 0.025, 0.03)
            for ta in (0.01, 0.015, 0.02, 0.025)
            for td in (0.25, 0.30, 0.35, 0.40)
        ]
    rows: List[Dict[str, object]] = []
    for sa, sm, tm, ta, td, mh in grid:
        cfg = {
            "sl_atr_mult": float(sa),
            "sl_min_pct": float(sm),
            "tp_min_pct": float(tm),
            "trail_arm_pct": float(ta),
            "trail_retrace_pct": float(td),
            "max_hold_bars": float(mh),
        }
        m = _run_backtest(data, sig, entries, target_regime, adx_threshold, cfg)
        if m is None:
            continue
        rows.append({"cfg": cfg, "metrics": m})
    rows.sort(key=lambda x: float(((x.get("metrics") or {}).get("score") if isinstance(x.get("metrics"), dict) else 0.0) or 0.0), reverse=True)
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pair-file", default="user_data/data/hyperliquid/futures/BTC_USDT-5m-futures.json")
    ap.add_argument("--adx-threshold", type=float, default=22.0)
    ap.add_argument("--topk", type=int, default=5)
    args = ap.parse_args()
    pair_file = Path(str(args.pair_file)).resolve()
    data = _build_features(_load_ohlcv(pair_file))
    sig, entries = _entry_indices(data)
    trend_rows = _search(data, sig, entries, "trend", float(args.adx_threshold))
    chop_rows = _search(data, sig, entries, "chop", float(args.adx_threshold))
    trend_n = sum(1 for i in entries if _regime_by_adx(float(data["adx"][i]), float(args.adx_threshold)) == "trend")
    chop_n = sum(1 for i in entries if _regime_by_adx(float(data["adx"][i]), float(args.adx_threshold)) == "chop")
    out = {
        "ok": True,
        "pair_file": str(pair_file),
        "bars": int(len(data["close"])),
        "entries_total": int(len(entries)),
        "entries_trend": int(trend_n),
        "entries_chop": int(chop_n),
        "adx_threshold": float(args.adx_threshold),
        "trend_best": trend_rows[0] if trend_rows else None,
        "trend_topk": trend_rows[: max(1, int(args.topk))],
        "chop_best": chop_rows[0] if chop_rows else None,
        "chop_topk": chop_rows[: max(1, int(args.topk))],
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
