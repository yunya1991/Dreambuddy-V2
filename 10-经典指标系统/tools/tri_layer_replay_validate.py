#!/usr/bin/env python3
import argparse
import glob
import json
import math
from collections import Counter


def _load_orders(patterns):
    files = []
    for p in patterns:
        files.extend(glob.glob(p))
    files = sorted(set(files))
    rows = []
    for fp in files:
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
    return files, rows


def _as_float(v):
    try:
        x = float(v)
        if math.isfinite(x):
            return x
    except Exception:
        pass
    return None


def _extract_leverage(o):
    x = _as_float(o.get("leverage"))
    if x is not None:
        return int(round(x))
    ex = o.get("exec")
    if isinstance(ex, dict):
        x = _as_float(ex.get("leverage"))
        if x is not None:
            return int(round(x))
    return None


def _is_addon(o):
    et = str(o.get("entry_type") or "").lower().strip()
    if et in ("addon", "add", "scale_in", "add_on"):
        return True
    g = o.get("gate")
    if isinstance(g, dict) and bool(g.get("addon", False)):
        return True
    tag = str(o.get("tag") or "").lower()
    return ("addon" in tag) or ("scale_in" in tag) or ("add_on" in tag)


def _metrics(rows):
    opens = [r for r in rows if str(r.get("action") or "").lower() == "open"]
    filled = [r for r in opens if str(r.get("status") or "").lower() == "filled"]
    size_hist = Counter()
    lev_hist = Counter()
    side_n = Counter()
    side_notional = Counter()
    addon_total = 0
    addon_filled = 0
    for r in opens:
        s = _as_float(r.get("size"))
        if s is not None:
            size_hist[f"{s:.6f}"] += 1
        lv = _extract_leverage(r)
        if lv is not None:
            lev_hist[str(lv)] += 1
        side = str(r.get("side") or "").lower().strip()
        if side in ("long", "short"):
            side_n[side] += 1
            n = _as_float(r.get("size"))
            if n is not None:
                side_notional[side] += n
        if _is_addon(r):
            addon_total += 1
            if str(r.get("status") or "").lower() == "filled":
                addon_filled += 1
    open_n = len(opens)
    long_n = int(side_n.get("long", 0))
    short_n = int(side_n.get("short", 0))
    net_bias_count = ((long_n - short_n) / open_n) if open_n > 0 else 0.0
    ln = float(side_notional.get("long", 0.0))
    sn = float(side_notional.get("short", 0.0))
    denom = ln + sn
    net_bias_notional = ((ln - sn) / denom) if denom > 0 else 0.0
    addon_pass_rate = (addon_filled / addon_total) if addon_total > 0 else 0.0
    return {
        "open_total": open_n,
        "filled_open_total": len(filled),
        "size_distribution": dict(size_hist),
        "leverage_distribution": dict(lev_hist),
        "net_bias_count": net_bias_count,
        "net_bias_notional": net_bias_notional,
        "addon_total": addon_total,
        "addon_filled": addon_filled,
        "addon_pass_rate": addon_pass_rate,
    }


def _delta(before, after):
    return {
        "open_total": int(after.get("open_total", 0)) - int(before.get("open_total", 0)),
        "filled_open_total": int(after.get("filled_open_total", 0)) - int(before.get("filled_open_total", 0)),
        "net_bias_count": float(after.get("net_bias_count", 0.0)) - float(before.get("net_bias_count", 0.0)),
        "net_bias_notional": float(after.get("net_bias_notional", 0.0)) - float(before.get("net_bias_notional", 0.0)),
        "addon_pass_rate": float(after.get("addon_pass_rate", 0.0)) - float(before.get("addon_pass_rate", 0.0)),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", nargs="+", required=True)
    ap.add_argument("--after", nargs="+", required=True)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    before_files, before_rows = _load_orders(args.before)
    after_files, after_rows = _load_orders(args.after)
    before_m = _metrics(before_rows)
    after_m = _metrics(after_rows)
    out = {
        "before_files": before_files,
        "after_files": after_files,
        "before": before_m,
        "after": after_m,
        "delta": _delta(before_m, after_m),
    }
    txt = json.dumps(out, ensure_ascii=False, indent=2)
    print(txt)
    if str(args.out).strip():
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(txt)


if __name__ == "__main__":
    main()
