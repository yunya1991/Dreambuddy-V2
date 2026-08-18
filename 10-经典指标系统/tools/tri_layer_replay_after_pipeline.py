#!/usr/bin/env python3
import argparse
import glob
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _http_get_json(base_url: str, path: str, params: Optional[Dict[str, Any]] = None, timeout: float = 1800.0) -> Dict[str, Any]:
    q = ""
    if isinstance(params, dict) and params:
        q = "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    url = f"{base_url.rstrip('/')}{path}{q}"
    req = urllib.request.Request(url=url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="ignore")
    return json.loads(body) if body.strip() else {}


def _http_post_json(base_url: str, path: str, payload: Dict[str, Any], timeout: float = 7200.0) -> Dict[str, Any]:
    url = f"{base_url.rstrip('/')}{path}"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url=url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="ignore")
    return json.loads(body) if body.strip() else {}


def _repo_rel_config_path(p: str) -> Path:
    pp = Path(str(p)).expanduser()
    if pp.is_absolute():
        return pp
    return Path(os.getcwd()) / str(p)


def _prepare_autodownload_config(config_path: str, trace_id: str, enabled: bool) -> Tuple[str, Optional[Path]]:
    if not bool(enabled):
        return str(config_path), None
    src = _repo_rel_config_path(config_path)
    if (not src.exists()) or (not src.is_file()):
        return str(config_path), None
    with open(src, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    if not isinstance(cfg, dict):
        return str(config_path), None
    pol = cfg.get("sandbox_policy")
    if not isinstance(pol, dict):
        pol = {}
    pol["auto_download_data"] = True
    cfg["sandbox_policy"] = pol
    cfg["backtest_auto_download_data"] = True
    out_dir = Path(os.getcwd()) / "user_data" / "tmp"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"tri_layer_auto_download_{str(trace_id)[:24]}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    rel = str(out_path.relative_to(Path(os.getcwd())))
    return rel, out_path


def _pick_new_zip(base_url: str, before_names: set, wait_sec: int) -> str:
    deadline = time.time() + float(max(5, wait_sec))
    while time.time() <= deadline:
        try:
            after_list = _http_get_json(base_url, "/backtest/results", params={"limit": 200})
            for x in (after_list.get("results") or []):
                if not isinstance(x, dict):
                    continue
                name = str(x.get("name") or "").strip()
                if name and (name not in before_names):
                    return name
        except Exception:
            pass
        time.sleep(10.0)
    return ""


def _as_float(v: Any) -> Optional[float]:
    try:
        x = float(v)
        if math.isfinite(x):
            return x
    except Exception:
        pass
    return None


def _is_addon_tag(tag: Any) -> bool:
    t = str(tag or "").lower()
    return ("addon" in t) or ("add_on" in t) or ("scale_in" in t)


def _extract_zip_trades(zip_path: Path, strategy: Optional[str]) -> Tuple[str, List[Dict[str, Any]]]:
    with zipfile.ZipFile(str(zip_path), "r") as zf:
        names = zf.namelist()
        mains = [n for n in names if n.endswith(".json") and ("_config" not in n) and ("_Strategy" not in n)]
        if not mains:
            raise RuntimeError("backtest_main_json_not_found")
        main = json.loads(zf.read(mains[0]))
    strategy_map = main.get("strategy") if isinstance(main.get("strategy"), dict) else {}
    if not isinstance(strategy_map, dict) or not strategy_map:
        raise RuntimeError("backtest_strategy_block_not_found")
    sname = str(strategy or "").strip()
    if not sname:
        sname = str(next(iter(strategy_map.keys())))
    block = strategy_map.get(sname)
    if not isinstance(block, dict):
        raise RuntimeError(f"strategy_not_found:{sname}")
    trades = block.get("trades") if isinstance(block.get("trades"), list) else []
    return sname, trades


def _trade_to_order(tr: Dict[str, Any], strategy: str) -> Optional[Dict[str, Any]]:
    pair = tr.get("pair")
    is_short = bool(tr.get("is_short", False))
    stake = _as_float(tr.get("stake_amount"))
    lev = _as_float(tr.get("leverage"))
    if pair is None or stake is None:
        return None
    enter_tag = tr.get("enter_tag")
    out = {
        "action": "open",
        "status": "filled",
        "pair": str(pair),
        "side": ("short" if is_short else "long"),
        "size": float(stake),
        "leverage": (None if lev is None else float(lev)),
        "strategy_id": str(strategy),
        "entry_type": ("addon" if _is_addon_tag(enter_tag) else "entry"),
        "tag": (None if enter_tag is None else str(enter_tag)),
        "from": "backtest_replay",
    }
    return out


def _load_orders_from_globs(patterns: List[str]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    files: List[str] = []
    for p in patterns:
        files.extend(glob.glob(p))
    for fp in sorted(set(files)):
        with open(fp, "r", encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    o = json.loads(ln)
                except Exception:
                    continue
                rows.append(o)
    return rows


def _extract_leverage(o: Dict[str, Any]) -> Optional[int]:
    lv = _as_float(o.get("leverage"))
    if lv is not None:
        return int(round(lv))
    ex = o.get("exec")
    if isinstance(ex, dict):
        lv = _as_float(ex.get("leverage"))
        if lv is not None:
            return int(round(lv))
    return None


def _is_addon(o: Dict[str, Any]) -> bool:
    et = str(o.get("entry_type") or "").lower().strip()
    if et in ("addon", "add", "scale_in", "add_on"):
        return True
    g = o.get("gate")
    if isinstance(g, dict) and bool(g.get("addon", False)):
        return True
    return _is_addon_tag(o.get("tag"))


def _metrics(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    opens = [r for r in rows if str(r.get("action") or "").lower() == "open"]
    filled = [r for r in opens if str(r.get("status") or "").lower() == "filled"]
    size_dist: Counter = Counter()
    lev_dist: Counter = Counter()
    side_cnt: Counter = Counter()
    side_notional: Counter = Counter()
    addon_total = 0
    addon_filled = 0
    for r in opens:
        s = _as_float(r.get("size"))
        if s is not None:
            size_dist[f"{s:.6f}"] += 1
        lv = _extract_leverage(r)
        if lv is not None:
            lev_dist[str(lv)] += 1
        side = str(r.get("side") or "").lower().strip()
        if side in ("long", "short"):
            side_cnt[side] += 1
            n = _as_float(r.get("size"))
            if n is not None:
                side_notional[side] += n
        if _is_addon(r):
            addon_total += 1
            if str(r.get("status") or "").lower() == "filled":
                addon_filled += 1
    open_total = len(opens)
    ln = int(side_cnt.get("long", 0))
    sn = int(side_cnt.get("short", 0))
    net_bias_count = ((ln - sn) / open_total) if open_total > 0 else 0.0
    l_notional = float(side_notional.get("long", 0.0))
    s_notional = float(side_notional.get("short", 0.0))
    denom = l_notional + s_notional
    net_bias_notional = ((l_notional - s_notional) / denom) if denom > 0 else 0.0
    addon_pass_rate = (float(addon_filled) / float(addon_total)) if addon_total > 0 else 0.0
    return {
        "open_total": int(open_total),
        "filled_open_total": int(len(filled)),
        "size_distribution": dict(size_dist),
        "leverage_distribution": dict(lev_dist),
        "net_bias_count": float(net_bias_count),
        "net_bias_notional": float(net_bias_notional),
        "addon_total": int(addon_total),
        "addon_filled": int(addon_filled),
        "addon_pass_rate": float(addon_pass_rate),
    }


def _delta(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "open_total": int(after.get("open_total", 0)) - int(before.get("open_total", 0)),
        "filled_open_total": int(after.get("filled_open_total", 0)) - int(before.get("filled_open_total", 0)),
        "net_bias_count": float(after.get("net_bias_count", 0.0)) - float(before.get("net_bias_count", 0.0)),
        "net_bias_notional": float(after.get("net_bias_notional", 0.0)) - float(before.get("net_bias_notional", 0.0)),
        "addon_pass_rate": float(after.get("addon_pass_rate", 0.0)) - float(before.get("addon_pass_rate", 0.0)),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8092")
    ap.add_argument("--config", default="user_data/config_local_backtest.json")
    ap.add_argument("--timerange", required=True)
    ap.add_argument("--strategy", default="")
    ap.add_argument("--trace-id", default="tri-layer-replay-after")
    ap.add_argument("--before-glob", action="append", required=True)
    ap.add_argument("--out-dir", default="user_data_prod/replay_reports")
    ap.add_argument("--timeout-sec", type=float, default=1800.0)
    ap.add_argument("--wait-new-zip-sec", type=int, default=1200)
    ap.add_argument("--auto-download-kline", action="store_true", default=False)
    ap.add_argument("--cleanup-temp-config", action="store_true", default=False)
    ap.add_argument("--zip", default="")
    ap.add_argument("--folds", type=int, default=6)
    ap.add_argument("--monte-runs", type=int, default=200)
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    zip_name = str(args.zip or "").strip()
    bt: Dict[str, Any] = {"ok": True, "skipped": True}
    temp_cfg_path: Optional[Path] = None
    if not zip_name:
        before_list = _http_get_json(args.base_url, "/backtest/results", params={"limit": 200})
        before_names = set([str((x or {}).get("name") or "") for x in (before_list.get("results") or []) if isinstance(x, dict)])
        cfg_path_eff, temp_cfg_path = _prepare_autodownload_config(
            config_path=str(args.config),
            trace_id=str(args.trace_id),
            enabled=bool(args.auto_download_kline),
        )
        payload = {
            "trace_id": str(args.trace_id),
            "config": str(cfg_path_eff),
            "timerange": str(args.timerange),
            "timeout_sec": float(max(30.0, args.timeout_sec)),
        }
        if str(args.strategy).strip():
            payload["strategy"] = str(args.strategy).strip()
        try:
            bt = _http_post_json(args.base_url, "/automation/backtest/run", payload=payload, timeout=max(120.0, float(args.timeout_sec) + 120.0))
        except TimeoutError:
            bt = {"ok": False, "error": "client_timeout_waiting_backtest_response"}
        except urllib.error.URLError as e:
            bt = {"ok": False, "error": str(e)}
        if bool(bt.get("ok", False)):
            zip_name = str(bt.get("result_zip") or "").strip()
        else:
            zip_name = _pick_new_zip(args.base_url, before_names, int(max(30, args.wait_new_zip_sec)))
            if not zip_name:
                raise RuntimeError(f"backtest_failed:{bt.get('error')}")
        if not zip_name:
            after_list = _http_get_json(args.base_url, "/backtest/results", params={"limit": 200})
            for x in (after_list.get("results") or []):
                if not isinstance(x, dict):
                    continue
                name = str(x.get("name") or "").strip()
                if name and (name not in before_names):
                    zip_name = name
                    break
    if not zip_name:
        raise RuntimeError("result_zip_not_found")

    rv_payload: Dict[str, Any] = {"trace_id": str(args.trace_id), "zip": zip_name, "n_slices": int(max(1, args.folds))}
    if str(args.strategy).strip():
        rv_payload["strategy"] = str(args.strategy).strip()
    rolling = _http_post_json(args.base_url, "/evaluation/rolling_verify", payload=rv_payload, timeout=1800.0)

    mc_payload: Dict[str, Any] = {"trace_id": str(args.trace_id), "zip": zip_name, "n_bootstrap": int(max(1, args.monte_runs)), "n_shuffle": 0}
    if str(args.strategy).strip():
        mc_payload["strategy"] = str(args.strategy).strip()
    monte = _http_post_json(args.base_url, "/evaluation/monte_carlo", payload=mc_payload, timeout=1800.0)

    zip_path = Path("user_data/backtest_results") / zip_name
    if not zip_path.exists():
        raise RuntimeError(f"zip_not_found:{zip_path}")

    strategy_name, trades = _extract_zip_trades(zip_path=zip_path, strategy=(str(args.strategy).strip() or None))
    after_rows: List[Dict[str, Any]] = []
    for tr in trades:
        if not isinstance(tr, dict):
            continue
        o = _trade_to_order(tr, strategy=strategy_name)
        if isinstance(o, dict):
            after_rows.append(o)

    after_jsonl = out_dir / f"after_orders_{Path(zip_name).stem}.jsonl"
    with open(after_jsonl, "w", encoding="utf-8") as f:
        for r in after_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    before_rows = _load_orders_from_globs(list(args.before_glob))
    before_m = _metrics(before_rows)
    after_m = _metrics(after_rows)
    rep = {
        "ok": True,
        "trace_id": str(args.trace_id),
        "timerange": str(args.timerange),
        "strategy": str(strategy_name),
        "result_zip": str(zip_name),
        "artifacts": {
            "after_orders_jsonl": str(after_jsonl),
            "backtest_zip": str(zip_path),
        },
        "steps": {
            "backtest_run": bt,
            "rolling_verify": rolling,
            "monte_carlo": monte,
        },
        "before": before_m,
        "after": after_m,
        "delta": _delta(before_m, after_m),
    }

    report_path = out_dir / f"delta_report_{Path(zip_name).stem}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)

    out = {
        "ok": True,
        "result_zip": str(zip_name),
        "strategy": str(strategy_name),
        "config_used": str(args.config),
        "auto_download_kline": bool(args.auto_download_kline),
        "after_orders": str(after_jsonl),
        "delta_report": str(report_path),
        "delta": rep.get("delta"),
    }
    if bool(args.cleanup_temp_config) and isinstance(temp_cfg_path, Path):
        try:
            temp_cfg_path.unlink(missing_ok=True)
        except Exception:
            pass
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
