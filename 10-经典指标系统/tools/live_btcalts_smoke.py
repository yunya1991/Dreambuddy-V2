import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional, Tuple


def _json_loads(b: bytes) -> Any:
    try:
        return json.loads(b.decode("utf-8"))
    except Exception:
        return None


def _http_json(
    method: str,
    url: str,
    payload: Optional[dict] = None,
    headers: Optional[dict] = None,
    timeout_sec: float = 15.0,
) -> Tuple[int, Any, str]:
    data = None
    h = {"Accept": "application/json"}
    if isinstance(headers, dict):
        h.update({str(k): str(v) for k, v in headers.items() if v is not None})
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url=url, data=data, headers=h, method=str(method).upper())
    try:
        with urllib.request.urlopen(req, timeout=float(timeout_sec)) as resp:
            body = resp.read()
            return int(resp.status), _json_loads(body), body.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body = e.read() if hasattr(e, "read") else b""
        return int(getattr(e, "code", 0) or 0), _json_loads(body), body.decode("utf-8", errors="replace")
    except Exception as e:
        return 0, None, str(e)


def _fail(msg: str) -> None:
    raise SystemExit(msg)


def _bool(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, bool):
        return bool(v)
    s = str(v).strip().lower()
    return s in ("1", "true", "yes", "y", "on")


def _get_env_token() -> Optional[str]:
    tok = os.getenv("WEBHOOK_EXECUTE_TOKEN") or os.getenv("X_EXECUTE_TOKEN") or os.getenv("EXECUTE_TOKEN")
    tok = (str(tok).strip() if tok is not None else "")
    return tok or None


def _orders_filter_by_tag(arr: Any, tag_substr: str) -> list:
    out = []
    if not isinstance(arr, list):
        return out
    for x in arr:
        if not isinstance(x, dict):
            continue
        if tag_substr in str(x.get("tag") or ""):
            out.append(x)
    return out


def _orders_pairs_status(orders: list) -> Dict[str, Dict[str, Any]]:
    rep: Dict[str, Dict[str, Any]] = {}
    for o in orders:
        if not isinstance(o, dict):
            continue
        pair = str(o.get("pair") or "").strip() or None
        if pair is None:
            continue
        rep[pair] = {
            "status": str(o.get("status") or ""),
            "side": str(o.get("side") or ""),
            "mode": str(o.get("mode") or ""),
            "tag": str(o.get("tag") or ""),
            "ts": o.get("ts"),
        }
    return rep


def _acct_has_symbol(acct: Any, symbol: str) -> bool:
    if not isinstance(symbol, str) or not symbol:
        return False
    try:
        blob = json.dumps(acct, ensure_ascii=False)
    except Exception:
        blob = str(acct)
    return symbol in blob


def main() -> None:
    p = argparse.ArgumentParser(prog="live_btcalts_smoke", add_help=True)
    p.add_argument("--base-url", default="http://127.0.0.1:8092", help="backend base url (default: http://127.0.0.1:8092)")
    p.add_argument("--alt", default="ETH", help="ALT coin symbol (default: ETH)")
    p.add_argument("--direction", default="short_alt_long_btc", choices=["short_alt_long_btc", "long_alt_short_btc"])
    p.add_argument("--strategy-mode", default="B", choices=["A", "B", "C"])
    p.add_argument("--timeframe", default="1h")
    p.add_argument("--notional-usdc", type=float, default=30.0)
    p.add_argument("--btc-hedge-frac", type=float, default=1.0)
    p.add_argument("--tag", default="", help="custom tag prefix (optional)")
    p.add_argument("--execute", action="store_true", help="place real orders (default: false)")
    p.add_argument("--force-close", dest="force_close", action="store_true", help="force reduceOnly close legs after open")
    p.add_argument("--no-force-close", dest="force_close", action="store_false", help="do not auto close legs (dangerous)")
    p.set_defaults(force_close=True)
    p.add_argument("--timeout-sec", type=float, default=60.0)
    args = p.parse_args()

    base = str(args.base_url).rstrip("/")
    alt = str(args.alt).strip().upper()
    if alt in ("BTC", "USDT", "USDC", ""):
        _fail(f"invalid --alt: {alt!r}")
    if float(args.notional_usdc) <= 0.0:
        _fail("invalid --notional-usdc")

    token = _get_env_token()
    headers = {"X-Execute-Token": token} if token else {}

    tag_ts = int(time.time())
    tag0 = str(args.tag).strip()
    if tag0:
        tag0 = tag0.replace(" ", "_")
        tag = f"{tag0}_live_btcalts_smoke_{tag_ts}"
    else:
        tag = f"live_btcalts_smoke_{tag_ts}"

    ping_url = f"{base}/execution/aster/ping"
    st, ping, raw = _http_json("GET", ping_url, None, headers=headers, timeout_sec=float(args.timeout_sec))
    if st <= 0:
        _fail(f"aster ping failed: {raw}")
    if not isinstance(ping, dict) or not _bool(ping.get("ok")):
        _fail(f"aster ping not ok: status={st} body={raw[:2000]}")
    if _bool(ping.get("trading_enabled")) is False and args.execute:
        _fail(f"aster trading disabled: {ping}")

    if args.execute:
        enable_url = f"{base}/config/live/enable"
        st_en, en, raw_en = _http_json(
            "POST",
            enable_url,
            {"confirm_live": True, "confirm_execute": True},
            headers=headers,
            timeout_sec=float(args.timeout_sec),
        )
        if st_en not in (200, 201) or (not isinstance(en, dict)) or (not _bool(en.get("ok"))):
            _fail(f"live enable failed: status={st_en} body={raw_en[:2000]}")

    try:
        acct_url0 = f"{base}/execution/aster/account_summary"
        st_a0, acct0, raw_a0 = _http_json("GET", acct_url0, None, headers=headers, timeout_sec=float(args.timeout_sec))
        if st_a0 <= 0 or not isinstance(acct0, dict) or not _bool(acct0.get("ok")):
            _fail(f"account_summary failed: status={st_a0} body={raw_a0[:2000]}")

        stats_url0 = f"{base}/tracker/stats?sync=1&force=1&view=ui"
        st_s0, st_json0, raw_s0 = _http_json("GET", stats_url0, None, headers=headers, timeout_sec=float(args.timeout_sec))
        if st_s0 <= 0 or not isinstance(st_json0, dict):
            _fail(f"tracker/stats failed: status={st_s0} body={raw_s0[:2000]}")
        qop0 = st_json0.get("quant_open_positions") if isinstance(st_json0.get("quant_open_positions"), dict) else {}
        want_pairs0 = ["BTC-PERP", f"{alt}-PERP"]
        stale_pairs = []
        for pair in want_pairs0:
            if pair not in qop0:
                continue
            sym = f"{str(pair).split('-')[0]}USDT"
            if not _acct_has_symbol(acct0, sym):
                stale_pairs.append(pair)
        if stale_pairs:
            clr_url = f"{base}/tracker/quant_open_positions/clear"
            st_c0, clr, raw_c0 = _http_json("POST", clr_url, {"pairs": stale_pairs}, headers=headers, timeout_sec=float(args.timeout_sec))
            if st_c0 <= 0 or not isinstance(clr, dict) or not _bool(clr.get("ok")):
                _fail(f"auto clear stale tracker failed: status={st_c0} body={raw_c0[:2000]}")

        open_url = f"{base}/execution/pairs/btcalt/market_open"
        open_payload = {
            "venue": "aster",
            "execute": bool(args.execute),
            "confirm_execute": True,
            "tag": tag,
            "strategy_id": "quant_pairs_btcalt",
            "timeframe": str(args.timeframe),
            "alt": alt,
            "direction": str(args.direction),
            "notional_usdc": float(args.notional_usdc),
            "strategy_mode": str(args.strategy_mode),
            "btc_hedge_frac": float(args.btc_hedge_frac),
            "idempotency_key": f"{tag}|open",
        }
        st_open, open_resp, raw_open = _http_json("POST", open_url, open_payload, headers=headers, timeout_sec=float(args.timeout_sec))
        if st_open <= 0:
            _fail(f"market_open request failed: {raw_open}")
        if not isinstance(open_resp, dict):
            _fail(f"market_open bad response: status={st_open} body={raw_open[:2000]}")
        if not _bool(open_resp.get("ok")):
            _fail(f"market_open not ok: status={st_open} body={raw_open[:2000]}")

        group_id = str(open_resp.get("group_id") or "").strip()
        btc_ok = _bool((open_resp.get("btc") or {}).get("ok")) if isinstance(open_resp.get("btc"), dict) else None
        alt_ok = _bool((open_resp.get("alt_leg") or {}).get("ok")) if isinstance(open_resp.get("alt_leg"), dict) else None
        print(json.dumps({"ok": True, "tag": tag, "group_id": group_id or None, "btc_ok": btc_ok, "alt_ok": alt_ok}, ensure_ascii=False))

        time.sleep(2.0 if args.execute else 0.2)

        if args.execute and args.force_close:
            close_url = f"{base}/execution/aster/market_close"
            for coin in (alt, "BTC"):
                payload = {
                    "coin": str(coin),
                    "execute": True,
                    "confirm_execute": True,
                    "tag": f"{tag}|force_close",
                    "force": True,
                    "exit_owner": "quant",
                    "system_id": "quant",
                    "ignore_post_close_freeze": True,
                }
                st_c, c_resp, raw_c = _http_json("POST", close_url, payload, headers=headers, timeout_sec=float(args.timeout_sec))
                if st_c <= 0 or not isinstance(c_resp, dict) or not _bool(c_resp.get("ok")):
                    _fail(f"force close failed: coin={coin} status={st_c} body={raw_c[:2000]}")
                time.sleep(0.8)

        recent_url = f"{base}/orders/recent?limit=200&include_shadow=1&sort=ingest&ab_owner=quant"
        st_r, recent, raw_r = _http_json("GET", recent_url, None, headers=headers, timeout_sec=float(args.timeout_sec))
        if st_r <= 0 or not isinstance(recent, list):
            _fail(f"orders/recent failed: status={st_r} body={raw_r[:2000]}")
        tagged = _orders_filter_by_tag(recent, tag)
        pairs = _orders_pairs_status(tagged)

        want_open_pairs = {"BTC-PERP", f"{alt}-PERP"}
        missing = [p for p in sorted(list(want_open_pairs)) if p not in pairs]
        if args.execute and missing:
            _fail(f"missing legs in recent orders: {missing} (tag={tag})")
        if args.execute:
            for p1 in want_open_pairs:
                st1 = str((pairs.get(p1) or {}).get("status") or "").lower()
                if st1 not in ("filled", "closed", "ignored"):
                    _fail(f"unexpected order status: pair={p1} status={st1} (tag={tag})")

        acct_url = f"{base}/execution/aster/account_summary"
        st_a, acct, raw_a = _http_json("GET", acct_url, None, headers=headers, timeout_sec=float(args.timeout_sec))
        if st_a <= 0 or not isinstance(acct, dict) or not _bool(acct.get("ok")):
            _fail(f"account_summary failed: status={st_a} body={raw_a[:2000]}")
        blob = json.dumps(acct, ensure_ascii=False)
        if args.execute and (("BTCUSDT" in blob) or (f"{alt}USDT" in blob)):
            _fail(f"position still present in account_summary (tag={tag})")

        print(json.dumps({"ok": True, "tag": tag, "group_id": (group_id or None), "orders_n": len(tagged)}, ensure_ascii=False))
    finally:
        if args.execute:
            disable_url = f"{base}/config/live/disable"
            _http_json("POST", disable_url, {"confirm_live": True, "confirm_execute": True}, headers=headers, timeout_sec=float(args.timeout_sec))


if __name__ == "__main__":
    main()
