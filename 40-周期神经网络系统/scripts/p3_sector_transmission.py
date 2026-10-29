#!/usr/bin/env python3
"""P3 板块传导：BTC → ETH/SOL → 增长型 → meme 层级梯度。

资金沿传导链扩散（expanding）为牛市健康传导；
资金收缩回主流层（contracting）为周期晚期/顶部预警信号。
与 cycle_state.json 的 MA200 牛熊锚点联动，结果写入 sector_transmission.json。
"""
import json
from datetime import datetime, timezone
from statistics import median

STATE = "/home/luke/dreambuddy/40-周期神经网络系统/cycle_state.json"
OUT = "/home/luke/dreambuddy/40-周期神经网络系统/sector_transmission.json"

# 四层传导链（OKX 交易对）
LAYERS = {
    "L1_anchor": ["BTC/USDT"],
    "L2_major": ["ETH/USDT", "SOL/USDT"],
    "L3_growth": ["AVAX/USDT", "LINK/USDT", "ADA/USDT"],
    "L4_meme": ["DOGE/USDT", "PEPE/USDT", "WIF/USDT"],
}


def fetch_daily(symbol):
    import ccxt
    ex = ccxt.okx({"enableRateLimit": True})
    o = ex.fetch_ohlcv(symbol, "1d", limit=120)
    return [c[4] for c in o if c[4]]


def momentum_3m(closes):
    if len(closes) < 63:
        return None
    return round((closes[-1] / closes[-63] - 1) * 100, 2)


def main():
    now = datetime.now(timezone.utc).isoformat()

    assets = {}
    for layer, symbols in LAYERS.items():
        for sym in symbols:
            closes = fetch_daily(sym)
            mom = momentum_3m(closes)
            assets[sym] = {
                "layer": layer,
                "momentum_3m_pct": mom,
                "samples": len(closes),
            }
            print(f"{sym:<12} layer={layer:<9} mom={mom}%  samples={len(closes)}")

    btc_mom = assets["BTC/USDT"]["momentum_3m_pct"]
    for sym, a in assets.items():
        if a["momentum_3m_pct"] is not None and btc_mom is not None:
            a["relative_strength_vs_btc"] = round(a["momentum_3m_pct"] - btc_mom, 2)
        else:
            a["relative_strength_vs_btc"] = None

    # 各层动量中位数
    layer_medians = {}
    for layer, symbols in LAYERS.items():
        moms = [assets[s]["momentum_3m_pct"] for s in symbols
                if assets[s]["momentum_3m_pct"] is not None]
        layer_medians[layer] = round(median(moms), 2) if moms else None

    # 传导梯度判定：
    # expanding  = meme/增长层动量接近或超过主流层（资金下沉扩散）
    # neutral    = 部分扩散，梯度不明显
    # contracting= meme 层动量显著弱于主流层（资金收缩回主流）
    l2, l3, l4 = layer_medians["L2_major"], layer_medians["L3_growth"], layer_medians["L4_meme"]
    if l4 is not None and l2 is not None:
        gap_42 = round(l4 - l2, 2)
        if gap_42 >= -5:
            transmission = "expanding"
        elif gap_42 <= -15:
            transmission = "contracting"
        else:
            transmission = "neutral"
    else:
        gap_42 = None
        transmission = "unknown"

    # 与 MA200 牛熊锚点联动
    with open(STATE) as f:
        state = json.load(f)
    btc_anchor = state.get("technical_anchor", {}).get("assets", {}).get("BTC/USDT", {})
    btc_above_ma200 = btc_anchor.get("above")

    if btc_above_ma200 and transmission == "expanding":
        regime = "healthy_bull_expansion"  # 牛市健康扩散
    elif btc_above_ma200 and transmission == "contracting":
        regime = "late_cycle_warning"  # 牛市晚期：资金收缩回主流层
    elif btc_above_ma200:
        regime = "bull_consolidation"
    else:
        regime = "bear_or_transition"

    result = {
        "generated_at": now,
        "layers": LAYERS,
        "assets": assets,
        "layer_median_momentum_3m_pct": layer_medians,
        "transmission": {
            "state": transmission,
            "meme_vs_major_gap_pct": gap_42,
            "btc_above_ma200": btc_above_ma200,
            "regime": regime,
        },
        "note": "expanding=资金沿传导链下沉扩散；contracting=资金收缩回主流层（周期晚期信号）；regime 联动 MA200 牛熊锚点",
    }

    with open(OUT, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # cycle_state.json 补充传导摘要
    state["sector_transmission"] = {
        "generated_at": now,
        "state": transmission,
        "regime": regime,
        "layer_median_momentum_3m_pct": layer_medians,
    }
    with open(STATE, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    print(f"\nlayer medians: {layer_medians}")
    print(f"transmission={transmission}  meme_vs_major_gap={gap_42}%  regime={regime}")


if __name__ == "__main__":
    main()
