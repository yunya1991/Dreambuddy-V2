import argparse
import sys
import time


import requests


def _now_ms() -> int:
    return int(time.time() * 1000)


def _tf_to_ms(tf: str) -> int:
    s = str(tf or "").strip().lower()
    if not s:
        return 0
    if s.endswith("m"):
        return int(s[:-1]) * 60 * 1000
    if s.endswith("h"):
        return int(s[:-1]) * 60 * 60 * 1000
    if s.endswith("d"):
        return int(s[:-1]) * 24 * 60 * 60 * 1000
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8092")
    ap.add_argument("--pair", default="BTC/USDC")
    ap.add_argument("--side", default="long", choices=["long", "short"])
    ap.add_argument("--strategy_id", default="Strategy005")
    ap.add_argument("--timeframe", default="1h")
    ap.add_argument("--limit", type=int, default=100)
    args = ap.parse_args()

    base = str(args.base).rstrip("/")
    try:
        r = requests.get(base + "/health", timeout=2)
        r.raise_for_status()
    except Exception as e:
        print(f"health_failed base={base} err={e}")
        return 2

    tf_ms = _tf_to_ms(str(args.timeframe))
    if tf_ms <= 0:
        print(f"invalid_timeframe timeframe={args.timeframe}")
        return 2

    now_ms = _now_ms()
    bar_open_ms = int(now_ms // tf_ms * tf_ms)
    bar_close_ms = int(bar_open_ms + tf_ms)
    tag = f"selfcheck_recent_dedup_{now_ms}"

    signal = {
        "signal_schema_version": 1,
        "venue": "hyperliquid",
        "pair": str(args.pair),
        "side": str(args.side),
        "action": "open",
        "timeframe": str(args.timeframe),
        "bar_open_ms": int(bar_open_ms),
        "bar_close_ms": int(bar_close_ms),
        "bar_closed": True,
        "strategy_id": str(args.strategy_id),
        "strategy_version": "selfcheck",
        "group_id": "selfcheck",
        "feature_set_id": "",
        "tag": tag,
        "confidence": 0.5,
        "features": {},
    }

    r1 = requests.post(base + "/signals/v1", json={"signal": dict(signal), "trigger_decision": False}, timeout=10)
    j1 = r1.json() if r1.headers.get("content-type", "").startswith("application/json") else {}
    print("/signals/v1", r1.status_code, "ok", j1.get("ok"), "id", j1.get("id"), "dedup", j1.get("dedup"))

    r2 = requests.post(base + "/signals", json={**dict(signal), "trigger_decision": True}, timeout=10)
    j2 = r2.json() if r2.headers.get("content-type", "").startswith("application/json") else {}
    print("/signals", r2.status_code, "ok", j2.get("ok"), "id", j2.get("id"), "dedup", j2.get("dedup"), "auto_decision", j2.get("auto_decision"))

    id1 = j1.get("id")
    id2 = j2.get("id")

    rr = requests.get(
        base + "/signals/recent",
        params={
            "limit": int(args.limit),
            "sort": "ingest",
            "include_shadow": 1,
            "include_stale": 1,
            "include_backfill": 1,
        },
        timeout=10,
    )
    arr = rr.json() if rr.headers.get("content-type", "").startswith("application/json") else []
    if not isinstance(arr, list):
        print("recent_invalid", type(arr), arr)
        return 2

    hits = [e for e in arr if isinstance(e, dict) and str(e.get("tag") or "") == tag]
    print("recent_hits", len(hits))
    for e in hits:
        print(
            "evt",
            e.get("id"),
            "pair",
            e.get("pair"),
            "side",
            e.get("side"),
            "strategy_id",
            e.get("strategy_id"),
            "tf",
            e.get("timeframe"),
            "action",
            e.get("action"),
            "bar_open_ms",
            e.get("bar_open_ms"),
            "trigger",
            e.get("trigger_decision"),
        )

    ids = [str(e.get("id")) for e in hits if e.get("id") is not None]
    base_keys = [
        "|".join(
            [
                str(e.get("pair") or ""),
                str(e.get("side") or ""),
                str(e.get("strategy_id") or ""),
                str(e.get("timeframe") or ""),
                str(e.get("action") or ""),
                str(e.get("bar_open_ms") or ""),
            ]
        )
        for e in hits
        if isinstance(e, dict)
    ]

    ok = True
    if id1 and id2 and str(id1) != str(id2):
        ok = False
        print("id_mismatch", id1, id2)
    if len(set(ids)) > 1:
        ok = False
        print("recent_event_id_duplicates", ids)
    if len(set(base_keys)) > 1:
        ok = False
        print("recent_base_key_mismatch", base_keys)
    if len(hits) != 1:
        ok = False
        print("recent_expected_one_row_got", len(hits))

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

