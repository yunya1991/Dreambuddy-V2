#!/usr/bin/env python3
"""P3 资金流动识别（L4 维度三）：板块内流动 + 跨资产流动 + 传统金融方法融合。

板块内：层内动量离散度 + 龙头/跟风轮动
跨资产：六资产动量排序 → 资金流动方向矩阵
传统金融方法（v0.7）：60 日滚动相关性矩阵 + 跨资产 RS 比率线 + 利差指标
输入：sector_transmission.json + asset_rotation.json + data_center.db + OKX
产出：fund_flow.json
"""
import json
import sqlite3
from datetime import datetime, timezone
from statistics import mean, stdev

BASE = "/home/luke/dreambuddy/40-周期神经网络系统"
TRANS = f"{BASE}/sector_transmission.json"
ROT = f"{BASE}/asset_rotation.json"
OUT = f"{BASE}/fund_flow.json"
DB = "/home/luke/dreambuddy/18-数据获取中心/data_center.db"

ASSET_LABELS = {
    "crypto_btc": "加密",
    "crypto_eth": "加密",
    "equity_spx": "股票",
    "gold_xaut": "黄金",
    "usd_dxy": "美元",
    "rates_10y": "债券(收益率)",
}


def load_daily(sid):
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "SELECT timestamp, json_extract(metrics, '$.value') FROM records "
        "WHERE source = 'fred' AND sub_category = ? ORDER BY timestamp",
        (sid,),
    ).fetchall()
    conn.close()
    return {r[0][:10]: float(r[1]) for r in rows if r[1] is not None}


def fetch_okx_daily(symbol, total=400):
    """分页拉取 OKX 日线，返回 {日期字符串: 收盘价}。"""
    import ccxt
    ex = ccxt.okx({"enableRateLimit": True})
    day_ms = 86400000
    candles = {}
    since = ex.milliseconds() - (total + 5) * day_ms
    while len(candles) < total:
        batch = ex.fetch_ohlcv(symbol, "1d", since=since, limit=100)
        if not batch:
            break
        for c in batch:
            candles[c[0]] = c
        since = batch[-1][0] + day_ms
        if len(batch) < 100:
            break
    out = {}
    for ts in sorted(candles)[-total:]:
        d = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        out[d] = float(candles[ts][4])
    return out


def corr(a, b):
    n = len(a)
    if n < 20:
        return None
    ma, mb = mean(a), mean(b)
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va == 0 or vb == 0:
        return None
    return round(cov / (va ** 0.5 * vb ** 0.5), 3)


def rolling_corr_last(s1, s2, window=60):
    common = sorted(set(s1) & set(s2))
    if len(common) < window:
        return None
    a = [s1[d] for d in common[-window:]]
    b = [s2[d] for d in common[-window:]]
    return corr(a, b)


def rs_ratio_line(s_num, s_den, window=20):
    common = sorted(set(s_num) & set(s_den))
    if len(common) < window + 5:
        return None
    ratios = [s_num[d] / s_den[d] for d in common]
    last = ratios[-1]
    ma = mean(ratios[-window:])
    ma_prev = mean(ratios[-2 * window:-window]) if len(ratios) >= 2 * window else None
    if ma_prev is None:
        direction = "flat"
    elif ma > ma_prev:
        direction = "up"
    else:
        direction = "down"
    return {
        "last_ratio": round(last, 6),
        "ma20": round(ma, 6),
        "above_ma20": last > ma,
        "ma20_direction": direction,
    }


def spread_indicator(sid, window=20):
    s = load_daily(sid)
    if not s:
        return None
    dates = sorted(s)
    last_val = s[dates[-1]]
    if len(dates) > window:
        prev_val = s[dates[-1 - window]]
        change = round(last_val - prev_val, 3)
        direction = "widening" if change > 0.05 else ("narrowing" if change < -0.05 else "flat")
    else:
        change = None
        direction = "flat"
    return {
        "latest": last_val,
        "date": dates[-1],
        "change_20d": change,
        "direction": direction,
    }


def main():
    now = datetime.now(timezone.utc).isoformat()

    with open(TRANS) as f:
        trans = json.load(f)
    with open(ROT) as f:
        rot = json.load(f)

    # ---------- 板块内资金流动 ----------
    layer_flows = {}
    layers = {}
    for sym, a in trans["assets"].items():
        layers.setdefault(a["layer"], []).append((sym, a["momentum_3m_pct"]))

    for layer, members in layers.items():
        moms = [m for _, m in members if m is not None]
        if len(moms) < 2:
            layer_flows[layer] = {"n": len(moms), "note": "样本不足"}
            continue
        med = mean(moms)
        disp = stdev(moms) if len(moms) > 1 else 0.0
        ranked = sorted(members, key=lambda x: x[1] if x[1] is not None else -999)
        leader = ranked[-1]
        laggard = ranked[0]
        if disp > 10:
            pattern = "分化轮动（资金选择性流动）"
        elif med > 5:
            pattern = "同步上涨（资金集中流入）"
        elif med < -5:
            pattern = "同步下跌（资金集中流出）"
        else:
            pattern = "中性整固"
        layer_flows[layer] = {
            "n": len(moms),
            "median_momentum_pct": round(med, 2),
            "dispersion_pct": round(disp, 2),
            "leader": {"symbol": leader[0], "momentum_pct": leader[1]},
            "laggard": {"symbol": laggard[0], "momentum_pct": laggard[1]},
            "pattern": pattern,
        }

    # ---------- 跨资产类别流动 ----------
    mom = rot["asset_momentum_3m_pct"]
    ranked_assets = sorted(
        [(k, v) for k, v in mom.items() if v is not None],
        key=lambda x: x[1],
        reverse=True,
    )
    cat_mom = {}
    for k, v in mom.items():
        cat = ASSET_LABELS.get(k, k)
        cat_mom.setdefault(cat, []).append(v)
    cat_ranked = sorted(
        [(c, round(mean(vs), 2)) for c, vs in cat_mom.items()],
        key=lambda x: x[1],
        reverse=True,
    )
    flow_matrix = []
    for src, src_mom in cat_ranked:
        for dst, dst_mom in cat_ranked:
            if src_mom <= dst_mom:
                continue
            gap = round(src_mom - dst_mom, 2)
            strength = "强" if gap > 15 else ("中" if gap > 5 else "弱")
            flow_matrix.append({
                "from": src, "to": dst,
                "momentum_gap_pct": gap, "strength": strength,
            })

    # ---------- 传统金融方法（v0.7） ----------
    spx = load_daily("SP500")
    dgs10 = load_daily("DGS10")
    dxy = load_daily("DTWEXBGS")
    btc = fetch_okx_daily("BTC/USDT", 400)

    xaut = fetch_okx_daily("XAUT/USDT", 400)
    correlation_matrix = {
        "spx_vs_10y": rolling_corr_last(spx, dgs10),
        "gold_vs_usd": rolling_corr_last(xaut, dxy),
        "btc_vs_spx": rolling_corr_last(btc, spx),
        "note": "60 日滚动皮尔逊相关系数；股债相关性由负转正为体制切换经典信号",
    }

    rs_ratio_lines = {
        "gold_vs_spx": rs_ratio_line(xaut, spx),
        "btc_vs_spx": rs_ratio_line(btc, spx),
        "note": "RS 比率线 + 20 日均线方向；above_ma20=true 表示相对强势",
    }
    spread_indicators = {
        "t10y2y": spread_indicator("T10Y2Y"),
        "hy_oas": spread_indicator("BAMLH0A0HYM2"),
        "note": "期限利差倒挂=衰退预警；信用利差走阔=风险偏好收缩",
    }

    out = {
        "generated_at": now,
        "intra_sector_flow": {
            "layers": layer_flows,
            "note": "离散度高=资金选择性流动；龙头动量衰减+跟风补涨=扩散末期",
        },
        "cross_asset_flow": {
            "category_momentum_pct": dict(cat_ranked),
            "asset_ranking": [{"asset": k, "momentum_pct": v} for k, v in ranked_assets],
            "flow_matrix": flow_matrix,
            "inflow_leader": cat_ranked[0] if cat_ranked else None,
            "outflow_leader": cat_ranked[-1] if cat_ranked else None,
            "note": "动量差为正=资金从弱类别流向强类别；rates_10y 上行=债券价格走弱",
        },
        "correlation_matrix": correlation_matrix,
        "rs_ratio_lines": rs_ratio_lines,
        "spread_indicators": spread_indicators,
    }

    with open(OUT, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print("=== 板块内资金流动 ===")
    for layer, lf in layer_flows.items():
        print(f"  {layer}: {lf.get('pattern', lf)}")
    print("=== 跨资产类别动量排序 ===")
    for c, m in cat_ranked:
        print(f"  {c:<10} {m:+.2f}%")
    print("=== 相关性矩阵（60日） ===")
    for k in ("spx_vs_10y", "gold_vs_usd", "btc_vs_spx"):
        print(f"  {k}: {correlation_matrix[k]}")
    print("=== RS 比率线 ===")
    for k in ("gold_vs_spx", "btc_vs_spx"):
        print(f"  {k}: {rs_ratio_lines[k]}")
    print("=== 利差指标 ===")
    print(f"  T10Y2Y: {spread_indicators['t10y2y']}")
    print(f"  HY OAS: {spread_indicators['hy_oas']}")
    print(f"saved: {OUT}")


if __name__ == "__main__":
    main()
