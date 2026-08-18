import json
import time
from typing import Any, Dict, Tuple
from urllib.request import Request, urlopen


BASE_URL = "http://127.0.0.1:8092"
STRATEGY_ID = "Strategy005"
BT_CONFIG = "user_data/config_local_backtest.json"
TIMERANGE = "20251115-20260115"


def _post(path: str, payload: Dict[str, Any], timeout_sec: float) -> Tuple[int, Dict[str, Any]]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(
        BASE_URL + path,
        data=data,
        headers={"content-type": "application/json", "accept": "application/json"},
    )
    with urlopen(req, timeout=float(timeout_sec)) as r:
        body = r.read().decode("utf-8", "ignore")
        return int(getattr(r, "status", 200)), json.loads(body)


def _pick(ms: Any) -> Dict[str, Any]:
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
        "tail_loss_p95",
    ]
    return {k: ms.get(k) for k in keys if k in ms}


def _fmt(v: Any) -> str:
    if v is None:
        return "-"
    if isinstance(v, (int, float)):
        return f"{float(v):.6f}".rstrip("0").rstrip(".")
    return str(v)


def _delta(b: Dict[str, Any], a: Dict[str, Any], k: str) -> str:
    vb = b.get(k)
    va = a.get(k)
    if isinstance(vb, (int, float)) and isinstance(va, (int, float)):
        return _fmt(float(va) - float(vb))
    return "-"


def main() -> None:
    trace_id = f"bayesopt_strategy005_n300_{int(time.time())}"
    payload_run = {
        "trace_id": trace_id,
        "mode": "suggest",
        "opt_class": "strategy",
        "strategy_id": STRATEGY_ID,
        "family": "xgb",
        "eval_mode": "backtest",
        "folds": 3,
        "n_init": 10,
        "n_iter": 300,
        "topk": 1,
        "skip_robustness": True,
        "include_suggest_only": True,
        "min_trades_7d": 1,
        "min_effective_days_7d": 1,
        "backtest_config": BT_CONFIG,
        "backtest_timerange": TIMERANGE,
        "backtest_timeout_sec": 1800,
    }

    _, resp = _post("/agent/paramopt/run", payload_run, timeout_sec=7200.0)
    if not isinstance(resp, dict) or not bool(resp.get("ok")):
        raise SystemExit(json.dumps({"ok": False, "trace_id": trace_id, "error": resp.get("error"), "resp": resp}, ensure_ascii=False)[:4000])

    selected = resp.get("selected") if isinstance(resp.get("selected"), dict) else {}
    patch = (
        selected.get("config_patch")
        if isinstance(selected.get("config_patch"), dict)
        else (selected.get("patch") if isinstance(selected.get("patch"), dict) else {})
    )

    bt0 = {
        "trace_id": f"{trace_id}__bt_baseline",
        "config": BT_CONFIG,
        "timerange": TIMERANGE,
        "strategy": STRATEGY_ID,
        "timeout_sec": 1800,
    }
    _, r0 = _post("/automation/backtest/run", bt0, timeout_sec=2400.0)

    env = {"FT_STRATEGY_PARAMS_JSON": json.dumps({STRATEGY_ID: patch}, ensure_ascii=False, sort_keys=True)}
    bt1 = {
        "trace_id": f"{trace_id}__bt_candidate",
        "config": BT_CONFIG,
        "timerange": TIMERANGE,
        "strategy": STRATEGY_ID,
        "timeout_sec": 1800,
        "env": env,
    }
    _, r1 = _post("/automation/backtest/run", bt1, timeout_sec=2400.0)

    m0 = _pick((r0.get("metrics_summary") if isinstance(r0, dict) else None))
    m1 = _pick((r1.get("metrics_summary") if isinstance(r1, dict) else None))

    out = {
        "ok": True,
        "trace_id": trace_id,
        "optimizer_engine": resp.get("optimizer_engine"),
        "optimizer_fallback": resp.get("optimizer_fallback"),
        "optimizer_error": resp.get("optimizer_error"),
        "timerange": TIMERANGE,
        "baseline": m0,
        "candidate": m1,
        "delta": {k: _delta(m0, m1, k) for k in sorted(set(m0.keys()) | set(m1.keys()))},
        "selected_patch_n": (len(patch) if isinstance(patch, dict) else 0),
        "selected_patch_top": dict(list(sorted((patch or {}).items(), key=lambda kv: kv[0]))[:20]) if isinstance(patch, dict) else {},
        "baseline_zip": (r0.get("result_zip") if isinstance(r0, dict) else None),
        "candidate_zip": (r1.get("result_zip") if isinstance(r1, dict) else None),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

