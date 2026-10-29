#!/usr/bin/env python3
"""P3 聪明钱采集（L4 维度三扩展，v0.7）：CFTC 持仓 + 稳定币供应。

CFTC：CME Bitcoin 期货非商业/商业头寸与未平仓量（周更，publicreporting.cftc.gov）
稳定币：DefiLlama USDT/USDC 流通量及日/周/月环比（日更）
入库 data_center.db（records 表既有格式）+ 扩展 fund_flow.json 的 smart_money 字段。
"""
import json
import sqlite3
import urllib.parse
import urllib.request
from datetime import datetime, timezone

DB = "/home/luke/dreambuddy/18-数据获取中心/data_center.db"
FF = "/home/luke/dreambuddy/40-周期神经网络系统/fund_flow.json"

CFTC_URL = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"
LLAMA_URL = "https://stablecoins.llama.fi/stablecoins?includePrices=false"


def http_json(url, params=None):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def upsert_record(conn, source, category, sub, ts_iso, metrics, raw):
    dedupe_key = f"{source}|{category}|{sub}|{ts_iso}"
    cur = conn.execute(
        "INSERT OR IGNORE INTO records "
        "(dedupe_key, source, category, sub_category, timestamp, metrics, events, timeseries, raw, schema_version) "
        "VALUES (?, ?, ?, ?, ?, ?, '[]', '[]', ?, 'v1')",
        (dedupe_key, source, category, sub, ts_iso,
         json.dumps(metrics, ensure_ascii=False), json.dumps(raw, ensure_ascii=False)),
    )
    return cur.rowcount > 0


def fetch_cftc_btc(conn):
    """CME Bitcoin 期货持仓（主合约，周更）。"""
    rows = http_json(CFTC_URL, {
        "$limit": 60,
        "commodity_name": "BITCOIN",
        "$order": "report_date_as_yyyy_mm_dd DESC",
    })
    # 主合约：CHICAGO MERCANTILE EXCHANGE 的 BITCOIN（非 Nano/Micro）
    cme = [r for r in rows if "CHICAGO MERCANTILE" in r.get("market_and_exchange_names", "")
           and r.get("contract_market_name", "").strip() == "BITCOIN"]
    inserted = 0
    latest = None
    for r in cme:
        date_str = r.get("report_date_as_yyyy_mm_dd", "")[:10]
        if not date_str:
            continue
        ts_iso = f"{date_str}T00:00:00+00:00"
        noncomm_long = int(r.get("noncomm_positions_long_all", 0))
        noncomm_short = int(r.get("noncomm_positions_short_all", 0))
        comm_long = int(r.get("comm_positions_long_all", 0))
        comm_short = int(r.get("comm_positions_short_all", 0))
        oi = int(r.get("open_interest_all", 0))
        metrics = {
            "noncomm_long": noncomm_long,
            "noncomm_short": noncomm_short,
            "noncomm_net": noncomm_long - noncomm_short,
            "comm_long": comm_long,
            "comm_short": comm_short,
            "comm_net": comm_long - comm_short,
            "open_interest": oi,
            "date": date_str,
        }
        if upsert_record(conn, "cftc", "position", "BTC_FUTURES_CME", ts_iso, metrics, r):
            inserted += 1
        if latest is None:
            latest = metrics
    return latest, inserted, len(cme)


def fetch_stablecoins(conn):
    """DefiLlama 稳定币流通量（USDT/USDC，日更）。"""
    d = http_json(LLAMA_URL)
    assets = {a["symbol"]: a for a in d.get("peggedAssets", [])}
    now = datetime.now(timezone.utc)
    ts_iso = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    results = {}
    inserted = 0
    for sym in ("USDT", "USDC"):
        a = assets.get(sym)
        if not a:
            continue
        circ = a.get("circulating", {}).get("peggedUSD")
        prev_day = a.get("circulatingPrevDay", {}).get("peggedUSD")
        prev_week = a.get("circulatingPrevWeek", {}).get("peggedUSD")
        prev_month = a.get("circulatingPrevMonth", {}).get("peggedUSD")
        metrics = {
            "circulating_usd": circ,
            "change_1d_pct": round((circ / prev_day - 1) * 100, 4) if prev_day else None,
            "change_7d_pct": round((circ / prev_week - 1) * 100, 4) if prev_week else None,
            "change_30d_pct": round((circ / prev_month - 1) * 100, 4) if prev_month else None,
            "date": ts_iso[:10],
        }
        if upsert_record(conn, "defillama", "stablecoin", sym, ts_iso, metrics, {"symbol": sym}):
            inserted += 1
        results[sym] = metrics
    return results, inserted


def main():
    now = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(DB)

    cftc_latest, cftc_ins, cftc_n = fetch_cftc_btc(conn)
    stable, stable_ins = fetch_stablecoins(conn)
    conn.commit()
    conn.close()

    print(f"CFTC BTC CME: rows={cftc_n} inserted={cftc_ins} latest={cftc_latest}")
    for sym, m in stable.items():
        print(f"{sym}: circ={m['circulating_usd']:.0f} 1d={m['change_1d_pct']}% 7d={m['change_7d_pct']}% 30d={m['change_30d_pct']}%")

    # 扩展 fund_flow.json 的 smart_money 字段
    with open(FF) as f:
        ff = json.load(f)

    usdt = stable.get("USDT", {})
    smart_money = {
        "generated_at": now,
        "cftc_btc": {
            "date": cftc_latest["date"] if cftc_latest else None,
            "noncomm_net": cftc_latest["noncomm_net"] if cftc_latest else None,
            "noncomm_long": cftc_latest["noncomm_long"] if cftc_latest else None,
            "noncomm_short": cftc_latest["noncomm_short"] if cftc_latest else None,
            "open_interest": cftc_latest["open_interest"] if cftc_latest else None,
            "note": "非商业净头寸>0=投机资金净多；周更数据",
        },
        "stablecoin_supply": {
            "usdt": usdt,
            "note": "稳定币供应增长=加密资金流入代理；收缩=流出信号",
        },
        "note": "聪明钱观测：CFTC 投机头寸 + 稳定币供应变化",
    }
    ff["smart_money"] = smart_money

    with open(FF, "w") as f:
        json.dump(ff, f, ensure_ascii=False, indent=2)

    print(f"saved: {FF}")


if __name__ == "__main__":
    main()
