import argparse
import json
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
from urllib.request import Request, urlopen


def _now_ms() -> int:
    return int(time.time() * 1000)


def _get_json(base_url: str, path: str, *, timeout_sec: float) -> Tuple[int, Dict[str, Any]]:
    req = Request(
        str(base_url).rstrip("/") + str(path),
        headers={"accept": "application/json"},
    )
    with urlopen(req, timeout=float(timeout_sec)) as r:
        body = r.read().decode("utf-8", "ignore")
    out = json.loads(body)
    return int(getattr(r, "status", 200)), out


def _post_json(base_url: str, path: str, payload: Dict[str, Any], timeout_sec: float) -> Tuple[int, Dict[str, Any]]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(
        str(base_url).rstrip("/") + str(path),
        data=data,
        headers={"content-type": "application/json", "accept": "application/json"},
    )
    with urlopen(req, timeout=float(timeout_sec)) as r:
        body = r.read().decode("utf-8", "ignore")
    out = json.loads(body)
    return int(getattr(r, "status", 200)), out


def _pick_metrics(ms: Any) -> Dict[str, Any]:
    if not isinstance(ms, dict):
        return {}
    keys = [
        "backtest_days",
        "trades",
        "trades_per_day",
        "winrate",
        "profit_total_pct",
        "profit_total_abs",
        "profit_factor",
        "sharpe",
        "sortino",
        "calmar",
        "max_drawdown_account",
        "max_drawdown_abs",
    ]
    return {k: ms.get(k) for k in keys if k in ms}


def _fmt(v: Any) -> str:
    if v is None:
        return "-"
    if isinstance(v, (int, float)):
        return f"{float(v):.6f}".rstrip("0").rstrip(".")
    return str(v)


def _delta(b: Dict[str, Any], a: Dict[str, Any], k: str) -> Optional[float]:
    vb = b.get(k)
    va = a.get(k)
    if isinstance(vb, (int, float)) and isinstance(va, (int, float)):
        return float(va) - float(vb)
    return None


@dataclass
class CompareResult:
    trace_id: str
    strategy_id: str
    optimizer_engine: Optional[str]
    optimizer_fallback: Optional[bool]
    optimizer_error: Optional[str]
    selected_patch: Dict[str, Any]
    baseline_backtest: Dict[str, Any]
    candidate_backtest: Dict[str, Any]
    paramopt_response: Dict[str, Any]


def _pick_top1_active_strategy(base_url: str, *, timeout_sec: float) -> Optional[str]:
    try:
        _, d = _get_json(base_url, "/tracker/stats?view=ui", timeout_sec=timeout_sec)
    except Exception:
        return None
    weights = d.get("strategy_weights") if isinstance(d, dict) else None
    if not isinstance(weights, dict):
        return None
    best_sid = None
    best_w = None
    for sid, w0 in weights.items():
        try:
            w = float(w0)
        except Exception:
            continue
        if w <= 0:
            continue
        if best_w is None or w > best_w:
            best_w = w
            best_sid = str(sid).strip() or None
    return best_sid


def run_compare(
    base_url: str,
    strategy_id: str,
    timerange: str,
    config_path: str,
    n_init: int,
    n_iter: int,
    folds: int,
    topk: int,
    min_trades_7d: int,
    min_effective_days_7d: int,
    timeout_sec_paramopt: float,
    timeout_sec_backtest: float,
    skip_robustness: bool,
    family: str,
    eval_mode: str,
) -> CompareResult:
    trace_id = f"cmp_{strategy_id.lower()}_{eval_mode}_{timerange}_n{int(n_iter)}_{int(time.time())}"
    payload_run: Dict[str, Any] = {
        "trace_id": trace_id,
        "mode": "suggest",
        "opt_class": "strategy",
        "strategy_id": strategy_id,
        "family": family,
        "eval_mode": eval_mode,
        "folds": int(folds),
        "n_init": int(n_init),
        "n_iter": int(n_iter),
        "topk": int(topk),
        "skip_robustness": bool(skip_robustness),
        "include_suggest_only": True,
        "min_trades_7d": int(min_trades_7d),
        "min_effective_days_7d": int(min_effective_days_7d),
        "backtest_config": config_path,
        "backtest_timerange": timerange,
        "backtest_timeout_sec": int(timeout_sec_backtest),
    }
    _, d = _post_json(base_url, "/agent/paramopt/run", payload_run, timeout_sec=timeout_sec_paramopt)
    if not isinstance(d, dict) or not bool(d.get("ok")):
        raise RuntimeError(f"paramopt_failed: {json.dumps(d, ensure_ascii=False)[:2000]}")
    sel = d.get("selected") if isinstance(d.get("selected"), dict) else {}
    patch = sel.get("config_patch") if isinstance(sel.get("config_patch"), dict) else (sel.get("patch") if isinstance(sel.get("patch"), dict) else {})

    payload_bt0 = {
        "trace_id": f"{trace_id}__bt_baseline",
        "config": config_path,
        "timerange": timerange,
        "strategy": strategy_id,
        "timeout_sec": float(timeout_sec_backtest),
    }
    _, bt0 = _post_json(base_url, "/automation/backtest/run", payload_bt0, timeout_sec=timeout_sec_backtest + 120.0)

    env = {"FT_STRATEGY_PARAMS_JSON": json.dumps({strategy_id: patch}, ensure_ascii=False, sort_keys=True)}
    payload_bt1 = {
        "trace_id": f"{trace_id}__bt_candidate",
        "config": config_path,
        "timerange": timerange,
        "strategy": strategy_id,
        "timeout_sec": float(timeout_sec_backtest),
        "env": env,
    }
    _, bt1 = _post_json(base_url, "/automation/backtest/run", payload_bt1, timeout_sec=timeout_sec_backtest + 120.0)

    return CompareResult(
        trace_id=str(trace_id),
        strategy_id=str(strategy_id),
        optimizer_engine=(None if d.get("optimizer_engine") is None else str(d.get("optimizer_engine"))),
        optimizer_fallback=(None if d.get("optimizer_fallback") is None else bool(d.get("optimizer_fallback"))),
        optimizer_error=(None if d.get("optimizer_error") is None else str(d.get("optimizer_error"))),
        selected_patch=(patch if isinstance(patch, dict) else {}),
        baseline_backtest=(bt0 if isinstance(bt0, dict) else {"ok": False}),
        candidate_backtest=(bt1 if isinstance(bt1, dict) else {"ok": False}),
        paramopt_response=d,
    )


def _to_markdown(res: CompareResult) -> str:
    mb = _pick_metrics(res.baseline_backtest.get("metrics_summary"))
    ma = _pick_metrics(res.candidate_backtest.get("metrics_summary"))
    lines = []
    lines.append(f"trace_id: {res.trace_id}")
    lines.append(f"strategy_id: {res.strategy_id}")
    lines.append(f"optimizer_engine: {res.optimizer_engine} fallback={res.optimizer_fallback} error={res.optimizer_error}")
    lines.append("")
    lines.append("METRICS (baseline -> candidate):")
    for k, label in [
        ("backtest_days", "days"),
        ("trades", "trades"),
        ("trades_per_day", "tpd"),
        ("winrate", "winrate"),
        ("profit_total_pct", "profit_pct"),
        ("profit_total_abs", "profit_abs"),
        ("profit_factor", "pf"),
        ("sharpe", "sharpe"),
        ("sortino", "sortino"),
        ("calmar", "calmar"),
        ("max_drawdown_account", "mdd_pct"),
    ]:
        dv = _delta(mb, ma, k)
        ds = "" if dv is None else f" (Δ {_fmt(dv)})"
        lines.append(f"- {label}: {_fmt(mb.get(k))} -> {_fmt(ma.get(k))}{ds}")
    lines.append("")
    lines.append(f"SELECTED PATCH (n={len(res.selected_patch)}):")
    for i, (k, v) in enumerate(sorted(res.selected_patch.items(), key=lambda kv: kv[0])):
        if i >= 40:
            lines.append("... (truncated)")
            break
        lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("BACKTEST ARTIFACTS:")
    lines.append(f"- baseline_zip: {str(res.baseline_backtest.get('result_zip') or '')}")
    lines.append(f"- candidate_zip: {str(res.candidate_backtest.get('result_zip') or '')}")
    return "\n".join(lines) + "\n"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default="http://127.0.0.1:8092")
    p.add_argument("--strategy-id", default="Strategy005")
    p.add_argument("--auto-top1", action="store_true")
    p.add_argument("--timerange", default="20251115-20260115")
    p.add_argument("--config", default="user_data/config_local_backtest.json")
    p.add_argument("--family", default="xgb")
    p.add_argument("--eval-mode", default="backtest", choices=["rolling", "backtest"])
    p.add_argument("--n-init", type=int, default=10)
    p.add_argument("--n-iter", type=int, default=300)
    p.add_argument("--folds", type=int, default=3)
    p.add_argument("--topk", type=int, default=1)
    p.add_argument("--min-trades-7d", type=int, default=1)
    p.add_argument("--min-effective-days-7d", type=int, default=1)
    p.add_argument("--timeout-paramopt-sec", type=float, default=7200.0)
    p.add_argument("--timeout-backtest-sec", type=float, default=1800.0)
    p.add_argument("--skip-robustness", action="store_true")
    p.add_argument("--out-json", default="user_data/agent_outbox/paramopt_strategy_compare_last.json")
    p.add_argument("--out-md", default="user_data/agent_outbox/paramopt_strategy_compare_last.md")
    args = p.parse_args()

    strategy_id = str(args.strategy_id)
    if bool(args.auto_top1):
        sid = _pick_top1_active_strategy(str(args.base_url), timeout_sec=20.0)
        if sid:
            strategy_id = sid

    res = run_compare(
        base_url=str(args.base_url),
        strategy_id=str(strategy_id),
        timerange=str(args.timerange),
        config_path=str(args.config),
        n_init=int(args.n_init),
        n_iter=int(args.n_iter),
        folds=int(args.folds),
        topk=int(args.topk),
        min_trades_7d=int(args.min_trades_7d),
        min_effective_days_7d=int(args.min_effective_days_7d),
        timeout_sec_paramopt=float(args.timeout_paramopt_sec),
        timeout_sec_backtest=float(args.timeout_backtest_sec),
        skip_robustness=bool(args.skip_robustness),
        family=str(args.family),
        eval_mode=str(args.eval_mode),
    )
    out_json = str(args.out_json)
    out_md = str(args.out_md)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(
            {
                "ok": True,
                "ts": _now_ms(),
                "trace_id": res.trace_id,
                "strategy_id": res.strategy_id,
                "optimizer_engine": res.optimizer_engine,
                "optimizer_fallback": res.optimizer_fallback,
                "optimizer_error": res.optimizer_error,
                "selected_patch": res.selected_patch,
                "baseline_backtest": res.baseline_backtest,
                "candidate_backtest": res.candidate_backtest,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    with open(out_md, "w", encoding="utf-8") as f:
        f.write(_to_markdown(res))
    print(json.dumps({"ok": True, "trace_id": res.trace_id, "strategy_id": res.strategy_id, "out_json": out_json, "out_md": out_md}, ensure_ascii=False))


if __name__ == "__main__":
    main()
