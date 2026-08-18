import argparse
import json
import math
import os
from bisect import bisect_left
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, List, Optional, Tuple


def _read_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = (line or "").strip()
            if not s:
                continue
            try:
                obj = json.loads(s)
            except Exception:
                continue
            if isinstance(obj, dict):
                yield obj


def _pair_to_base(pair: str) -> str:
    if not pair:
        return ""
    p = str(pair)
    if p.endswith("-PERP"):
        coin = p.replace("-PERP", "")
        return f"{coin}_USDT"
    return p.replace("/", "_").replace(":", "_").replace("-", "_")


def _data_roots(project_root: Path) -> List[Path]:
    roots = [
        project_root / "user_data" / "data" / "gate",
        project_root / "user_data" / "data" / "gateio",
        project_root / "user_data" / "data" / "hyperliquid",
        project_root / "user_data" / "data",
    ]
    return [p for p in roots if p.exists()]


def _build_data_index(project_root: Path) -> Dict[str, List[Path]]:
    idx: Dict[str, List[Path]] = defaultdict(list)
    for root in _data_roots(project_root):
        for p in root.rglob("*-5m.json"):
            key = p.name.replace("-5m.json", "")
            idx[key].append(p)
        for p in root.rglob("*-5m-futures.json"):
            key = p.name.replace("-5m-futures.json", "")
            idx[key].append(p)
    return idx


def _choose_pair_file(idx: Dict[str, List[Path]], pair: str) -> Optional[Path]:
    base = _pair_to_base(pair)
    if not base:
        return None
    direct = idx.get(base)
    if direct:
        return direct[0]
    prefix = base.split("_")[0]
    for k, vs in idx.items():
        if k.startswith(base) or k.startswith(prefix):
            if vs:
                return vs[0]
    return None


@dataclass
class Series:
    ts: List[int]
    close: List[float]

    def price_at(self, ts_ms: int) -> float:
        if not self.ts:
            return 0.0
        i = bisect_left(self.ts, int(ts_ms))
        if i < 0:
            i = 0
        if i >= len(self.close):
            i = len(self.close) - 1
        if i < 0:
            return 0.0
        return float(self.close[i])


def _load_series(path: Path) -> Series:
    try:
        with open(path, "r", encoding="utf-8") as f:
            rows = json.load(f)
    except Exception:
        return Series(ts=[], close=[])
    ts: List[int] = []
    close: List[float] = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, list) or len(r) < 5:
            continue
        try:
            t = int(r[0])
            c = float(r[4])
        except Exception:
            continue
        ts.append(t)
        close.append(c)
    return Series(ts=ts, close=close)


def _quantile(xs: List[float], q: float) -> float:
    if not xs:
        return 0.0
    ys = sorted(xs)
    if len(ys) == 1:
        return float(ys[0])
    q2 = max(0.0, min(1.0, float(q)))
    pos = int(round(q2 * float(len(ys) - 1)))
    pos = max(0, min(len(ys) - 1, pos))
    return float(ys[pos])


def _std(xs: List[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / float(len(xs))
    v = sum((x - m) * (x - m) for x in xs) / float(len(xs) - 1)
    return math.sqrt(max(0.0, v))


def _max_drawdown_pct(daily_returns: List[float]) -> float:
    eq = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in daily_returns:
        eq *= 1.0 + float(r)
        peak = max(peak, eq)
        if peak > 0:
            dd = (peak - eq) / peak
            max_dd = max(max_dd, dd)
    return float(max_dd)


def _equity_curve(daily_returns: List[float]) -> List[float]:
    eq = 1.0
    out: List[float] = []
    for r in daily_returns:
        eq *= 1.0 + float(r)
        out.append(float(eq))
    return out


def _annualized_return_from_equity(eq: float, days: int) -> float:
    if days <= 0:
        return 0.0
    if eq <= 0:
        return -1.0
    try:
        return float(math.pow(float(eq), 365.0 / float(days)) - 1.0)
    except Exception:
        return 0.0


def _pct(xs: List[float], q: float) -> float:
    return _quantile(xs, q)


def _day_key(ts_ms: int) -> str:
    dt = datetime.fromtimestamp(float(ts_ms) / 1000.0, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d")


def _get_event_score(evt: Dict[str, Any]) -> Optional[float]:
    di = evt.get("decision_info")
    if not isinstance(di, dict):
        return None
    if isinstance(di.get("arena"), dict):
        agg = (di.get("arena") or {}).get("agg")
        if isinstance(agg, dict):
            v = agg.get("pc_weighted", agg.get("pc_mean"))
            if v is not None:
                try:
                    return float(v)
                except Exception:
                    pass
    v2 = di.get("pc")
    if v2 is not None:
        try:
            return float(v2)
        except Exception:
            return None
    return None


def _get_event_regime(evt: Dict[str, Any]) -> str:
    di = evt.get("decision_info")
    if isinstance(di, dict) and di.get("regime") is not None:
        return str(di.get("regime") or "")
    arena = evt.get("arena")
    if isinstance(arena, dict) and arena.get("regime") is not None:
        return str(arena.get("regime") or "")
    return ""


def _get_event_side(evt: Dict[str, Any]) -> str:
    s = evt.get("side")
    return ("" if s is None else str(s)).lower()


def _get_event_pair(evt: Dict[str, Any]) -> str:
    p = evt.get("pair")
    return "" if p is None else str(p)


def _get_event_ts(evt: Dict[str, Any]) -> int:
    v = evt.get("ts")
    try:
        return int(v)
    except Exception:
        return 0


def _get_event_atr_pct(evt: Dict[str, Any]) -> float:
    feats = evt.get("features")
    if isinstance(feats, dict) and feats.get("atr_pct") is not None:
        try:
            return float(feats.get("atr_pct") or 0.0)
        except Exception:
            return 0.0
    return 0.0


def _get_event_open_price(evt: Dict[str, Any]) -> float:
    feats = evt.get("features")
    if isinstance(feats, dict) and feats.get("close") is not None:
        try:
            return float(feats.get("close") or 0.0)
        except Exception:
            return 0.0
    return 0.0


def _event_is_candidate(evt: Dict[str, Any]) -> bool:
    if str(evt.get("action") or "").lower() not in ("open", "enter"):
        return False
    if not isinstance(evt.get("arena"), dict):
        return False
    if not isinstance(evt.get("decision_info"), dict):
        return False
    return True


def _event_return_ratio(series: Series, evt: Dict[str, Any], horizon_ms: int) -> Optional[float]:
    ts = _get_event_ts(evt)
    if ts <= 0:
        return None
    open_px = _get_event_open_price(evt)
    if open_px <= 0:
        return None
    px_f = series.price_at(ts + int(horizon_ms))
    if px_f <= 0:
        return None
    side = _get_event_side(evt)
    if side in ("short", "sell"):
        return float((open_px - px_f) / open_px)
    return float((px_f - open_px) / open_px)


def _iter_events(dataset_dir: Path, since_ts: int, until_ts: int, max_files: int) -> List[Dict[str, Any]]:
    files = sorted(dataset_dir.glob("*_events.jsonl"), key=lambda p: p.name)
    if max_files > 0:
        files = files[-int(max_files) :]
    out: List[Dict[str, Any]] = []
    for p in files:
        for evt in _read_jsonl(p):
            if not _event_is_candidate(evt):
                continue
            ts = _get_event_ts(evt)
            if since_ts and ts < int(since_ts):
                continue
            if until_ts and ts > int(until_ts):
                continue
            out.append(evt)
    out.sort(key=lambda e: _get_event_ts(e))
    return out


def _stake_scale(atr_pct: float, stake_target_atr_pct: float, scale_min: float, scale_max: float) -> float:
    ap = float(atr_pct)
    tgt = float(stake_target_atr_pct)
    if ap <= 0.0:
        return 1.0
    s = tgt / ap
    if s < float(scale_min):
        s = float(scale_min)
    if s > float(scale_max):
        s = float(scale_max)
    return float(s)


def _load_config(project_root: Path) -> Dict[str, Any]:
    p = project_root / "user_data" / "ml_config.json"
    if not p.exists():
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}


def _maybe_float(v: Any, default: float) -> float:
    try:
        return float(v)
    except Exception:
        return float(default)


def _maybe_int(v: Any, default: int) -> int:
    try:
        return int(v)
    except Exception:
        return int(default)


def _linspace(lo: float, hi: float, step: float) -> List[float]:
    if step <= 0:
        return [float(lo)]
    xs = []
    x = float(lo)
    while x <= float(hi) + 1e-12:
        xs.append(round(float(x), 10))
        x += float(step)
    return xs


def _fmt(x: Any, nd: int = 4) -> str:
    try:
        return f"{float(x):.{int(nd)}f}"
    except Exception:
        return ""


def _evaluate_combo(
    events: List[Dict[str, Any]],
    series_cache: Dict[str, Series],
    data_idx: Dict[str, List[Path]],
    horizon_ms: int,
    take_rate: float,
    stake_target_atr_pct: float,
    stake_scale_min: float,
    stake_scale_max: float,
    take_rate_window: int,
    take_rate_min_samples: int,
    by_regime: bool,
    take_mode: str,
    score_min_samples: int = 20,
) -> Dict[str, Any]:
    windows: Dict[str, Deque[float]] = defaultdict(lambda: deque(maxlen=int(take_rate_window)))
    min_samples = int(max(take_rate_min_samples, score_min_samples))
    thr_map: Dict[str, float] = {}
    if str(take_mode).lower() == "global":
        scores_by_key: Dict[str, List[float]] = defaultdict(list)
        for evt in events:
            score = _get_event_score(evt)
            if score is None:
                continue
            key = _get_event_regime(evt) if by_regime else "__all__"
            scores_by_key[key].append(float(score))
        for k, xs in scores_by_key.items():
            if len(xs) >= min_samples:
                thr_map[k] = _quantile(xs, 1.0 - float(take_rate))
    daily: Dict[str, float] = defaultdict(float)
    trade_rets: List[float] = []
    trade_risks: List[float] = []
    losses: List[float] = []

    n_total = 0
    n_take = 0
    for evt in events:
        n_total += 1
        pair = _get_event_pair(evt)
        if not pair:
            continue
        if pair not in series_cache:
            fp = _choose_pair_file(data_idx, pair)
            series_cache[pair] = _load_series(fp) if fp is not None else Series(ts=[], close=[])
        ser = series_cache.get(pair) or Series(ts=[], close=[])
        score = _get_event_score(evt)
        if score is None:
            continue
        key = _get_event_regime(evt) if by_regime else "__all__"
        if str(take_mode).lower() == "global":
            thr = thr_map.get(key)
            take = (thr is not None) and (float(score) >= float(thr))
        else:
            w = windows[key]
            if len(w) >= min_samples:
                thr = _quantile(list(w), 1.0 - float(take_rate))
                take = float(score) >= float(thr)
            else:
                take = False
            w.append(float(score))
        if not take:
            continue
        ret_ratio = _event_return_ratio(ser, evt, horizon_ms=horizon_ms)
        if ret_ratio is None:
            continue
        atr_pct = _get_event_atr_pct(evt)
        scale = _stake_scale(atr_pct=atr_pct, stake_target_atr_pct=stake_target_atr_pct, scale_min=stake_scale_min, scale_max=stake_scale_max)
        risk = float(atr_pct) * float(scale) if float(atr_pct) > 0 else float(stake_target_atr_pct)
        tr = float(ret_ratio) * float(scale)
        day = _day_key(_get_event_ts(evt))
        daily[day] += tr
        trade_rets.append(tr)
        trade_risks.append(risk)
        if tr < 0:
            losses.append(-tr)
        n_take += 1

    days = sorted(daily.keys())
    daily_rets = [float(daily[d]) for d in days]
    eq_curve = _equity_curve(daily_rets)
    eq_final = float(eq_curve[-1]) if eq_curve else 1.0
    tot_ret = float(eq_final - 1.0)
    avg_day = (sum(daily_rets) / float(len(daily_rets))) if daily_rets else 0.0
    std_day = _std(daily_rets)
    sharpe = (avg_day / std_day) * math.sqrt(365.0) if std_day > 0 else 0.0
    max_dd = _max_drawdown_pct(daily_rets)
    ann_ret = _annualized_return_from_equity(eq_final, len(days))
    calmar = float(ann_ret / max(1e-12, float(max_dd))) if float(max_dd) > 0 else (float(ann_ret) * 1e6)
    ret_over_dd = float(tot_ret / max(1e-12, float(max_dd))) if float(max_dd) > 0 else (float(tot_ret) * 1e6)

    return {
        "take_rate": float(take_rate),
        "stake_target_atr_pct": float(stake_target_atr_pct),
        "n_events": int(n_total),
        "n_trades": int(n_take),
        "days": int(len(days)),
        "total_return": float(tot_ret),
        "ann_return": float(ann_ret),
        "avg_daily_return": float(avg_day),
        "sharpe": float(sharpe),
        "max_dd": float(max_dd),
        "calmar": float(calmar),
        "ret_over_dd": float(ret_over_dd),
        "risk_p50": _pct(trade_risks, 0.50) if trade_risks else 0.0,
        "risk_p90": _pct(trade_risks, 0.90) if trade_risks else 0.0,
        "risk_p95": _pct(trade_risks, 0.95) if trade_risks else 0.0,
        "risk_p99": _pct(trade_risks, 0.99) if trade_risks else 0.0,
        "loss_p50": _pct(losses, 0.50) if losses else 0.0,
        "loss_p90": _pct(losses, 0.90) if losses else 0.0,
        "loss_p95": _pct(losses, 0.95) if losses else 0.0,
        "loss_p99": _pct(losses, 0.99) if losses else 0.0,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset-dir", default="user_data/datasets")
    ap.add_argument("--max-files", type=int, default=60)
    ap.add_argument("--since-ts", type=int, default=0)
    ap.add_argument("--until-ts", type=int, default=0)
    ap.add_argument("--horizon-hours", type=float, default=None)
    ap.add_argument("--take-rate-window", type=int, default=0)
    ap.add_argument("--take-rate-min-samples", type=int, default=0)
    ap.add_argument("--by-regime", type=int, default=-1)
    ap.add_argument("--score-min-samples", type=int, default=20)
    ap.add_argument("--take-mode", default="")
    ap.add_argument("--take-rate-lo", type=float, default=0.05)
    ap.add_argument("--take-rate-hi", type=float, default=0.20)
    ap.add_argument("--take-rate-step", type=float, default=0.01)
    ap.add_argument("--stake-atr-lo", type=float, default=0.01)
    ap.add_argument("--stake-atr-hi", type=float, default=0.04)
    ap.add_argument("--stake-atr-step", type=float, default=0.005)
    ap.add_argument("--min-trades", type=int, default=0)
    ap.add_argument("--min-days", type=int, default=0)
    ap.add_argument("--rank", default="")
    ap.add_argument("--max-dd-cap", type=float, default=None)
    ap.add_argument("--loss-p95-cap", type=float, default=None)
    ap.add_argument("--robust", type=int, default=0)
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    project_root = Path(__file__).resolve().parent
    cfg = _load_config(project_root)

    horizon_h = args.horizon_hours
    if horizon_h is None:
        horizon_h = _maybe_float(cfg.get("label_horizon_hours"), 12.0)
    horizon_ms = int(float(horizon_h) * 3600.0 * 1000.0)

    take_rate_window = int(args.take_rate_window) if int(args.take_rate_window) > 0 else _maybe_int(cfg.get("arena_take_rate_window"), 2000)
    take_rate_min_samples = int(args.take_rate_min_samples) if int(args.take_rate_min_samples) > 0 else _maybe_int(cfg.get("arena_take_rate_min_samples"), 200)
    if int(args.by_regime) in (0, 1):
        by_regime = bool(int(args.by_regime))
    else:
        by_regime = bool(cfg.get("arena_take_rate_by_regime", True))

    take_mode = str(args.take_mode or "").strip().lower()
    if take_mode not in ("rolling", "global"):
        take_mode = str(cfg.get("arena_take_mode") or "rolling").strip().lower()
    if take_mode not in ("rolling", "global"):
        take_mode = "rolling"
    scale_min = _maybe_float(cfg.get("stake_atr_scale_min"), 0.25)
    scale_max = _maybe_float(cfg.get("stake_atr_scale_max"), 4.0)

    dataset_dir = (project_root / str(args.dataset_dir)).resolve()
    if not dataset_dir.exists():
        raise SystemExit(f"dataset_dir_not_found: {dataset_dir}")

    events = _iter_events(dataset_dir=dataset_dir, since_ts=int(args.since_ts), until_ts=int(args.until_ts), max_files=int(args.max_files))
    if not events:
        raise SystemExit("no_events")

    data_idx = _build_data_index(project_root)
    series_cache: Dict[str, Series] = {}

    take_rates = _linspace(args.take_rate_lo, args.take_rate_hi, args.take_rate_step)
    stake_targets = _linspace(args.stake_atr_lo, args.stake_atr_hi, args.stake_atr_step)

    rows: List[Dict[str, Any]] = []
    for tr in take_rates:
        for st in stake_targets:
            r = _evaluate_combo(
                events=events,
                series_cache=series_cache,
                data_idx=data_idx,
                horizon_ms=horizon_ms,
                take_rate=float(tr),
                stake_target_atr_pct=float(st),
                stake_scale_min=float(scale_min),
                stake_scale_max=float(scale_max),
                take_rate_window=int(take_rate_window),
                take_rate_min_samples=int(take_rate_min_samples),
                by_regime=bool(by_regime),
                take_mode=str(take_mode),
                score_min_samples=int(max(1, int(args.score_min_samples))),
            )
            rows.append(r)

    rank_mode = str(args.rank or "").strip().lower()
    if rank_mode not in ("sharpe", "calmar", "ret_over_dd"):
        rank_mode = "sharpe"

    max_dd_cap = args.max_dd_cap
    if max_dd_cap is not None:
        try:
            max_dd_cap = float(max_dd_cap)
        except Exception:
            max_dd_cap = None
        if max_dd_cap is not None:
            max_dd_cap = max(0.0, min(1.0, float(max_dd_cap)))

    loss_p95_cap = args.loss_p95_cap
    if loss_p95_cap is not None:
        try:
            loss_p95_cap = float(loss_p95_cap)
        except Exception:
            loss_p95_cap = None
        if loss_p95_cap is not None:
            loss_p95_cap = max(0.0, float(loss_p95_cap))

    min_trades = int(max(0, int(args.min_trades)))
    min_days = int(max(0, int(args.min_days)))
    if min_trades > 0 or min_days > 0 or max_dd_cap is not None or loss_p95_cap is not None:
        rows3 = [
            r
            for r in rows
            if int(r.get("n_trades") or 0) >= min_trades
            and int(r.get("days") or 0) >= min_days
            and (max_dd_cap is None or float(r.get("max_dd") or 0.0) <= float(max_dd_cap))
            and (loss_p95_cap is None or float(r.get("loss_p95") or 0.0) <= float(loss_p95_cap))
        ]
        if rows3:
            rows = rows3

    if bool(int(args.robust or 0)) and rows:
        idx: Dict[Tuple[float, float], Dict[str, Any]] = {}
        for r in rows:
            k = (round(float(r.get("take_rate") or 0.0), 10), round(float(r.get("stake_target_atr_pct") or 0.0), 10))
            idx[k] = r

        def _metric(rr: Dict[str, Any]) -> float:
            if rank_mode == "calmar":
                return float(rr.get("calmar") or 0.0)
            if rank_mode == "ret_over_dd":
                return float(rr.get("ret_over_dd") or 0.0)
            return float(rr.get("sharpe") or 0.0)

        for r in rows:
            tr = float(r.get("take_rate") or 0.0)
            st = float(r.get("stake_target_atr_pct") or 0.0)
            ns: List[float] = []
            for dtr in (-float(args.take_rate_step), 0.0, float(args.take_rate_step)):
                for dst in (-float(args.stake_atr_step), 0.0, float(args.stake_atr_step)):
                    k2 = (round(tr + dtr, 10), round(st + dst, 10))
                    rr = idx.get(k2)
                    if rr is not None:
                        ns.append(_metric(rr))
            r["robust_metric"] = float(min(ns)) if ns else _metric(r)

    if bool(int(args.robust or 0)):
        rows.sort(key=lambda x: float(x.get("robust_metric") or 0.0), reverse=True)
    else:
        if rank_mode == "calmar":
            rows.sort(key=lambda x: float(x.get("calmar") or 0.0), reverse=True)
        elif rank_mode == "ret_over_dd":
            rows.sort(key=lambda x: float(x.get("ret_over_dd") or 0.0), reverse=True)
        else:
            rows.sort(key=lambda x: float(x.get("sharpe") or 0.0), reverse=True)
    top_n = max(1, min(int(args.top), len(rows)))
    rows2 = rows[:top_n]

    header = [
        "take_rate",
        "stake_target_atr_pct",
        "sharpe",
        "calmar",
        "ret_over_dd",
        "max_dd",
        "ann_return",
        "total_return",
        "avg_daily_return",
        "n_events",
        "n_trades",
        "days",
        "risk_p95",
        "loss_p95",
    ]
    lines = [",".join(header)]
    for r in rows2:
        lines.append(
            ",".join(
                [
                    _fmt(r.get("take_rate"), 4),
                    _fmt(r.get("stake_target_atr_pct"), 4),
                    _fmt(r.get("sharpe"), 3),
                    _fmt(r.get("calmar"), 3),
                    _fmt(r.get("ret_over_dd"), 3),
                    _fmt(r.get("max_dd"), 4),
                    _fmt(r.get("ann_return"), 6),
                    _fmt(r.get("total_return"), 6),
                    _fmt(r.get("avg_daily_return"), 6),
                    str(int(r.get("n_events") or 0)),
                    str(int(r.get("n_trades") or 0)),
                    str(int(r.get("days") or 0)),
                    _fmt(r.get("risk_p95"), 4),
                    _fmt(r.get("loss_p95"), 6),
                ]
            )
        )

    out_text = "\n".join(lines)
    print(out_text)
    if str(args.out or "").strip():
        op = Path(str(args.out)).expanduser().resolve()
        with open(op, "w", encoding="utf-8") as f:
            f.write(out_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
