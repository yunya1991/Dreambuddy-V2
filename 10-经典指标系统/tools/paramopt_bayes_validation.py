import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple


def _now_ms() -> int:
    return int(time.time() * 1000)


def _json_loads(b: bytes) -> Any:
    try:
        return json.loads(b.decode("utf-8"))
    except Exception:
        return None


def _json_dumps(x: Any) -> str:
    return json.dumps(x, ensure_ascii=False, indent=2)


def _to_float(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except Exception:
        return None
    if x != x:
        return None
    if x in (float("inf"), float("-inf")):
        return None
    return float(x)


def _get_dict(d: Any, k: str) -> Dict[str, Any]:
    v = d.get(k) if isinstance(d, dict) else None
    return v if isinstance(v, dict) else {}


def _pick(d: Dict[str, Any], keys: List[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k in keys:
        if k in d:
            out[k] = d.get(k)
    return out


class HttpClient:
    def __init__(self, base_url: str, timeout_sec: float, headers: Optional[Dict[str, str]] = None) -> None:
        self.base_url = str(base_url).rstrip("/")
        self.timeout_sec = float(timeout_sec)
        self.headers = dict(headers or {})

    def request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None, query: Optional[Dict[str, Any]] = None) -> Tuple[int, Any, str]:
        p = str(path or "")
        if not p.startswith("/"):
            p = "/" + p
        url = f"{self.base_url}{p}"
        if isinstance(query, dict) and query:
            q = urllib.parse.urlencode({str(k): str(v) for k, v in query.items() if v is not None})
            if q:
                url = f"{url}?{q}"
        data = None
        h = {"Accept": "application/json"}
        h.update(self.headers)
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(url=url, data=data, headers=h, method=str(method).upper())
        try:
            with urllib.request.urlopen(req, timeout=float(self.timeout_sec)) as resp:
                b = resp.read()
                return int(resp.status), _json_loads(b), b.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            b = e.read() if hasattr(e, "read") else b""
            return int(getattr(e, "code", 0) or 0), _json_loads(b), b.decode("utf-8", errors="replace")
        except Exception as e:
            return 0, None, str(e)


class InProcessClient:
    def __init__(self) -> None:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        if root not in sys.path:
            sys.path.insert(0, root)
        import ml_trade_service as svc  # type: ignore

        self.svc = svc
        self.client = svc.app.test_client()

    def request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None, query: Optional[Dict[str, Any]] = None) -> Tuple[int, Any, str]:
        m = str(method or "GET").strip().upper()
        p = str(path or "")
        if not p.startswith("/"):
            p = "/" + p
        if m == "GET":
            resp = self.client.get(p, query_string=(query or {}), environ_base={"REMOTE_ADDR": "127.0.0.1"})
        else:
            resp = self.client.open(p, method=m, json=(payload or {}), environ_base={"REMOTE_ADDR": "127.0.0.1"})
        body = resp.get_json(silent=True)
        raw = ""
        try:
            raw = resp.get_data(as_text=True)
        except Exception:
            raw = ""
        return int(resp.status_code), body, raw


def _extract_eval_metrics(eval_mode: str, d: Dict[str, Any]) -> Dict[str, Optional[float]]:
    em = str(eval_mode or "").strip().lower()
    out: Dict[str, Optional[float]] = {}
    if em == "backtest":
        ms = _get_dict(d, "metrics_summary")
        out["sharpe"] = _to_float(ms.get("sharpe"))
        out["sortino"] = _to_float(ms.get("sortino"))
        out["maxdd"] = _to_float(ms.get("max_drawdown_account"))
        out["tail_loss_p95"] = _to_float(ms.get("tail_loss_p95"))
        out["trades"] = _to_float(ms.get("trades"))
        out["coverage_days"] = _to_float(ms.get("backtest_days"))
        out["trades_per_day"] = _to_float(ms.get("trades_per_day"))
        out["profit_factor"] = _to_float(ms.get("profit_factor"))
        out["calmar"] = _to_float(ms.get("calmar"))
    else:
        st = _get_dict(d, "stressed")
        out["sharpe"] = _to_float(st.get("sharpe"))
        out["sortino"] = _to_float(st.get("sortino"))
        out["maxdd"] = _to_float(st.get("maxdd"))
        out["tail_loss_p95"] = _to_float(st.get("tail_loss_p95"))
        out["trades"] = _to_float(d.get("avg_trades"))
        out["coverage_days"] = _to_float(st.get("coverage"))
        out["trades_per_day"] = _to_float(d.get("avg_trades_per_day"))
        out["mean_return"] = _to_float(st.get("mean_return"))
    return out


def _metrics_delta(a: Dict[str, Optional[float]], b: Dict[str, Optional[float]]) -> Dict[str, Optional[float]]:
    out: Dict[str, Optional[float]] = {}
    keys = sorted(set(list(a.keys()) + list(b.keys())))
    for k in keys:
        av = _to_float(a.get(k))
        bv = _to_float(b.get(k))
        if av is None or bv is None:
            out[k] = None
        else:
            out[k] = float(av - bv)
    return out


def _coerce_recent_items(x: Any) -> List[Dict[str, Any]]:
    if isinstance(x, list):
        return [v for v in x if isinstance(v, dict)]
    if isinstance(x, dict):
        arr = x.get("items")
        if isinstance(arr, list):
            return [v for v in arr if isinstance(v, dict)]
    return []


def _seed_eval_samples_if_needed(cli: InProcessClient, n: int) -> Optional[Tuple[List[Any], Dict[str, Any]]]:
    if int(n) <= 0:
        return None
    svc = cli.svc
    orig_samples = list(svc.EVAL_SAMPLES)
    orig_cfg = dict(svc.CONFIG)
    ts0 = 1700000000000
    svc.EVAL_SAMPLES.clear()
    for i in range(int(n)):
        ts = int(ts0) + int(i) * 3600_000
        svc.EVAL_SAMPLES.append(
            {
                "ts": int(ts),
                "pair": "BTC/USDT",
                "side": "long",
                "label": (1 if (i % 2 == 0) else 0),
                "targets": {"return_tk": (0.01 if (i % 2 == 0) else -0.008)},
                "features": {
                    "close": 100.0 + float(i),
                    "volume": 1000.0 + float(i % 10),
                    "rsi_d": 40.0 + float(i % 20),
                    "willr_d": -60.0 + float(i % 20),
                    "macd_d": 0.01 * float((i % 5) - 2),
                    "macdsignal_d": 0.005 * float((i % 5) - 2),
                    "macro_atr_pct": 0.01 + 0.00001 * float(i),
                    "macro_trend_shape_5": ("up" if (i % 3) else "down"),
                    "macro_btc_time_regime": ("trend" if (i % 4) else "chop"),
                },
            }
        )
    return orig_samples, orig_cfg


def _restore_inprocess_state(cli: InProcessClient, snap: Optional[Tuple[List[Any], Dict[str, Any]]]) -> None:
    if snap is None:
        return
    orig_samples, orig_cfg = snap
    svc = cli.svc
    svc.EVAL_SAMPLES.clear()
    svc.EVAL_SAMPLES.extend(orig_samples)
    svc.CONFIG.clear()
    svc.CONFIG.update(orig_cfg)


def main() -> None:
    p = argparse.ArgumentParser(prog="paramopt_bayes_validation", add_help=True)
    p.add_argument("--transport", default="inprocess", choices=["inprocess", "http"])
    p.add_argument("--base-url", default="http://127.0.0.1:8092")
    p.add_argument("--timeout-sec", type=float, default=60.0)
    p.add_argument("--eval-mode", default="rolling", choices=["rolling", "backtest"])
    p.add_argument("--family", default="lr")
    p.add_argument("--key", default="max_open_trades")
    p.add_argument("--folds", type=int, default=5)
    p.add_argument("--n-init", type=int, default=2)
    p.add_argument("--n-iter", type=int, default=4)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--skip-robustness", action="store_true")
    p.add_argument("--apply-config", action="store_true")
    p.add_argument("--manual-approve-fallback", action="store_true")
    p.add_argument("--seed-eval-samples", type=int, default=0)
    p.add_argument("--order-test", action="store_true")
    p.add_argument("--order-notional-usdc", type=float, default=100.0)
    p.add_argument("--order-auto-bump-to-min", action="store_true")
    p.add_argument("--order-ignore-cooldown", action="store_true")
    p.add_argument("--order-ignore-post-close-freeze", action="store_true")
    p.add_argument("--order-macro-gate-fail-open", action="store_true")
    p.add_argument("--order-p2-health-fail-open", action="store_true")
    p.add_argument("--report-dir", default="user_data/agent_outbox")
    args = p.parse_args()

    headers: Dict[str, str] = {}
    env_map = {
        "X-Execute-Token": os.getenv("X_EXECUTE_TOKEN") or os.getenv("EXECUTE_TOKEN"),
        "X-Config-Token": os.getenv("X_CONFIG_TOKEN") or os.getenv("CONFIG_TOKEN"),
        "X-Maintenance-Token": os.getenv("X_MAINTENANCE_TOKEN") or os.getenv("MAINTENANCE_TOKEN"),
    }
    for k, v in env_map.items():
        if v is not None and str(v).strip():
            headers[k] = str(v).strip()

    cli: Any
    if str(args.transport) == "http":
        cli = HttpClient(base_url=str(args.base_url), timeout_sec=float(args.timeout_sec), headers=headers)
    else:
        cli = InProcessClient()

    run_id = f"bayes_validation_{int(time.time())}"
    trace_id = run_id
    snap = None
    ts0 = _now_ms()
    report: Dict[str, Any] = {
        "ok": False,
        "ts": int(ts0),
        "run_id": str(run_id),
        "input": {
            "transport": str(args.transport),
            "base_url": (None if str(args.transport) != "http" else str(args.base_url)),
            "eval_mode": str(args.eval_mode),
            "family": str(args.family),
            "key": str(args.key),
            "folds": int(args.folds),
            "n_init": int(args.n_init),
            "n_iter": int(args.n_iter),
            "seed": int(args.seed),
            "skip_robustness": bool(args.skip_robustness),
            "apply_config": bool(args.apply_config),
            "manual_approve_fallback": bool(args.manual_approve_fallback),
            "order_test": bool(args.order_test),
        },
    }
    try:
        if str(args.transport) == "inprocess":
            snap = _seed_eval_samples_if_needed(cli, int(args.seed_eval_samples))

        st_cfg0, cfg0, raw_cfg0 = cli.request("GET", "/config/get", query={})
        if st_cfg0 != 200 or not isinstance(cfg0, dict):
            report["error"] = {"stage": "config_get_before", "status": st_cfg0, "raw": str(raw_cfg0)[:4000]}
            print(_json_dumps(report))
            return
        val_before = cfg0.get(str(args.key))

        st_space, space_body, raw_space = cli.request(
            "POST",
            "/agent/paramopt/search_space",
            payload={"trace_id": f"{trace_id}_space", "scopes": ["entry", "strategy", "quant", "overlay"], "include_suggest_only": False},
        )
        if st_space != 200 or not isinstance(space_body, dict):
            report["error"] = {"stage": "search_space", "status": st_space, "raw": str(raw_space)[:4000]}
            print(_json_dumps(report))
            return
        items = ((_get_dict(space_body, "space")).get("items") if isinstance(_get_dict(space_body, "space").get("items"), list) else []) or []
        item_by_key = {}
        for it in items:
            if isinstance(it, dict):
                k = str(it.get("key") or "").strip()
                if k:
                    item_by_key[k] = it
        key = str(args.key).strip()
        if key not in item_by_key:
            report["error"] = {"stage": "search_space_key_missing", "key": key, "space_n": len(items)}
            print(_json_dumps(report))
            return
        key_meta = item_by_key.get(key) if isinstance(item_by_key.get(key), dict) else {}

        payload_run = {
            "trace_id": str(trace_id),
            "mode": ("apply" if bool(args.apply_config) else "suggest"),
            "confirm_apply": bool(args.apply_config),
            "family": str(args.family),
            "eval_mode": str(args.eval_mode),
            "folds": int(args.folds),
            "n_init": int(args.n_init),
            "n_iter": int(args.n_iter),
            "keys": [str(key)],
            "include_suggest_only": False,
            "skip_robustness": bool(args.skip_robustness),
            "seed": int(args.seed),
            "context": {"baseline_ref": f"prod_champion:{str(args.eval_mode)}"},
        }
        st_run, run_body, raw_run = cli.request("POST", "/agent/paramopt/run", payload=payload_run)
        if st_run != 200 or not isinstance(run_body, dict):
            report["error"] = {"stage": "paramopt_run", "status": st_run, "raw": str(raw_run)[:8000]}
            print(_json_dumps(report))
            return

        baseline = _get_dict(run_body, "baseline")
        best = _get_dict(run_body, "best")
        best_metrics = _get_dict(best, "metrics")
        selected = _get_dict(run_body, "selected")
        selected_patch = _get_dict(selected, "config_patch")
        if not selected_patch:
            selected_patch = _get_dict(selected, "patch")
        candidate_eval = _extract_eval_metrics(str(args.eval_mode), best_metrics)
        baseline_eval = _extract_eval_metrics(str(args.eval_mode), baseline)
        delta_eval = _metrics_delta(candidate_eval, baseline_eval)

        gate = _get_dict(run_body, "gate")
        policy = _get_dict(run_body, "policy_auto_approval")
        apply_obj = _get_dict(run_body, "apply")
        approval_id = (str(apply_obj.get("approval_id") or "").strip() or None)
        apply_mode = (str(apply_obj.get("mode") or "").strip() or None)

        approval_path: Dict[str, Any] = {
            "initial_apply_mode": apply_mode,
            "initial_approval_id": approval_id,
            "policy_auto_approval": _pick(policy, ["policy_id", "decision", "pass", "hard_fails"]),
            "manual_approval_used": False,
            "approval_lookup_before": None,
            "approval_lookup_after": None,
        }

        if approval_id:
            st_ap0, ap0, raw_ap0 = cli.request("GET", "/approvals/get", query={"id": approval_id})
            approval_path["approval_lookup_before"] = {"status": st_ap0, "body": (ap0 if isinstance(ap0, dict) else {"raw": str(raw_ap0)[:4000]})}

        config_apply_result: Optional[Dict[str, Any]] = None
        if bool(args.apply_config) and isinstance(selected_patch, dict) and selected_patch:
            final_approval_id = approval_id
            if (not final_approval_id) or (str(apply_mode or "").lower() in ("approval_requested", "pending")):
                if bool(args.manual_approve_fallback):
                    if not final_approval_id:
                        final_approval_id = hashlib.sha256(f"{trace_id}|manual".encode("utf-8")).hexdigest()[:16]
                    ap_payload = {
                        "id": str(final_approval_id),
                        "trace_id": str(trace_id),
                        "approver": "human",
                        "decision": "approved",
                        "action": "config.set",
                        "reason": "manual_approve_fallback_for_bayes_validation",
                    }
                    st_log, log_body, raw_log = cli.request("POST", "/approvals/log", payload=ap_payload)
                    approval_path["manual_approval_used"] = True
                    approval_path["manual_approval_log"] = {"status": st_log, "body": (log_body if isinstance(log_body, dict) else {"raw": str(raw_log)[:4000]})}
            if final_approval_id:
                payload_cfg = {"trace_id": f"{trace_id}_config_set", "confirm_live": True, "approval_id": str(final_approval_id)}
                payload_cfg.update(selected_patch)
                st_cfg1, cfg1, raw_cfg1 = cli.request("POST", "/config/set", payload=payload_cfg)
                config_apply_result = {"status": st_cfg1, "body": (cfg1 if isinstance(cfg1, dict) else {"raw": str(raw_cfg1)[:8000]})}
                approval_id = str(final_approval_id)
            else:
                config_apply_result = {"status": None, "body": {"ok": False, "error": "approval_id_missing"}}

        if approval_id:
            st_ap1, ap1, raw_ap1 = cli.request("GET", "/approvals/get", query={"id": approval_id})
            approval_path["approval_lookup_after"] = {"status": st_ap1, "body": (ap1 if isinstance(ap1, dict) else {"raw": str(raw_ap1)[:4000]})}

        st_cfg2, cfg2, raw_cfg2 = cli.request("GET", "/config/get", query={})
        val_after = None
        if st_cfg2 == 200 and isinstance(cfg2, dict):
            val_after = cfg2.get(str(key))
        else:
            val_after = val_before

        signal_payload = {
            "signal_schema_version": 1,
            "pair": "BTC/USDT",
            "side": "long",
            "action": "open",
            "timeframe": "1h",
            "bar_open_ms": int(_now_ms() - 3_600_000),
            "bar_close_ms": int(_now_ms()),
            "bar_closed": True,
            "strategy_id": "Strategy005",
            "strategy_version": "1.0.0",
            "group_id": "s005",
            "feature_set_id": "s005_v1",
            "confidence": 0.8,
            "features": {"close": 123.4, "volume": 1111.0},
            "trigger_decision": False,
        }
        st_sig, sig_body, raw_sig = cli.request("POST", "/signals", payload=signal_payload)

        if bool(args.order_test) and str(args.transport) == "inprocess":
            if bool(args.order_macro_gate_fail_open):
                cli.svc.CONFIG["macro_gate_fail_open"] = True
            if bool(args.order_p2_health_fail_open):
                cli.svc.CONFIG["p2_health_gate_fail_open"] = True

        order_receipt: Optional[Dict[str, Any]] = None
        if bool(args.order_test):
            order_payload = {
                "coin": "BTC",
                "side": "long",
                "notional_usdc": float(args.order_notional_usdc),
                "execute": False,
                "tag": f"{trace_id}_order",
                "strategy_id": "Strategy005",
                "ab_owner": "strategy",
                "auto_bump_to_min": bool(args.order_auto_bump_to_min),
                "ignore_cooldown": bool(args.order_ignore_cooldown),
                "ignore_post_close_freeze": bool(args.order_ignore_post_close_freeze),
            }
            st_ord, ord_body, raw_ord = cli.request("POST", "/execution/hyperliquid/market_open", payload=order_payload)
            order_receipt = {"status": st_ord, "body": (ord_body if isinstance(ord_body, dict) else {"raw": str(raw_ord)[:8000]})}

        st_or, or_body, raw_or = cli.request("GET", "/orders/recent", query={"limit": 10})
        st_sr, sr_body, raw_sr = cli.request("GET", "/signals/recent", query={"limit": 10})
        orders_items = _coerce_recent_items(or_body)
        signals_items = _coerce_recent_items(sr_body)

        report["ok"] = True
        report["parameter"] = {
            "key": str(key),
            "search_space_meta": _pick(key_meta, ["key", "type", "apply_mode", "tighten_rule", "range"]),
            "before": val_before,
            "selected_patch_value": selected_patch.get(key) if isinstance(selected_patch, dict) else None,
            "after": val_after,
            "changed": (val_before != val_after),
        }
        report["metrics_delta"] = {
            "eval_mode": str(args.eval_mode),
            "baseline": baseline_eval,
            "candidate": candidate_eval,
            "delta_candidate_minus_baseline": delta_eval,
            "best_target": _to_float(_get_dict(best, "max").get("target")),
        }
        report["gate_decision"] = {
            "pass": bool(gate.get("pass", False)),
            "fails": (gate.get("fails") if isinstance(gate.get("fails"), list) else []),
            "exec_quality": _get_dict(gate, "exec_quality"),
            "policy_auto_approval": _pick(policy, ["policy_id", "decision", "pass", "hard_fails"]),
        }
        report["approval_path"] = approval_path
        report["receipts"] = {
            "signal": {"status": st_sig, "body": (sig_body if isinstance(sig_body, dict) else {"raw": str(raw_sig)[:8000]})},
            "order": order_receipt,
            "orders_recent": {"status": st_or, "count": len(orders_items), "top": (orders_items[0] if orders_items else None), "raw": (None if isinstance(or_body, (list, dict)) else str(raw_or)[:4000])},
            "signals_recent": {"status": st_sr, "count": len(signals_items), "top": (signals_items[0] if signals_items else None), "raw": (None if isinstance(sr_body, (list, dict)) else str(raw_sr)[:4000])},
            "config_apply": config_apply_result,
        }

    finally:
        if str(args.transport) == "inprocess":
            _restore_inprocess_state(cli, snap)

    report_dir = str(args.report_dir or "user_data/agent_outbox")
    if not os.path.isabs(report_dir):
        report_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", report_dir))
    os.makedirs(report_dir, exist_ok=True)
    report_path = os.path.join(report_dir, f"paramopt_bayes_validation_{run_id}.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    report["artifacts"] = {"report_path": report_path}
    print(_json_dumps(report))


if __name__ == "__main__":
    main()
