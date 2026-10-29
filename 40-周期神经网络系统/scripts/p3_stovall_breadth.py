#!/usr/bin/env python3
"""P3 Stovall 板块轮动映射 + 市场广度指标（L4 维度一传统金融方法融合，v0.7）。

Stovall 映射：美林象限 → 周期阶段 → 板块偏好（预注册规则表，不产生交易信号）
市场广度：传导链全部 14 资产站上 MA200 的占比（分层统计）
  - L1/L2 锚点资产取 cycle_state.json 既有 MA200 锚点（8 资产）
  - L3/L4 层资产从 OKX 分页拉取日线现算 MA200
产出：stovall_breadth.json + sector_transmission.json 补充 breadth 字段
"""
import json
from datetime import datetime, timezone

BASE = "/home/luke/dreambuddy/40-周期神经网络系统"
ROT = f"{BASE}/asset_rotation.json"
STATE = f"{BASE}/cycle_state.json"
TRANS = f"{BASE}/sector_transmission.json"
OUT = f"{BASE}/stovall_breadth.json"

STOVALL_MAP = {
    "recovery": {
        "phase": "复苏（Recovery）",
        "equity_sectors": ["科技", "工业", "可选消费", "金融"],
        "crypto_analog": "增长型层（AVAX/ADA 类）",
        "rationale": "增长回升+通胀回落，周期性与高贝塔板块领先",
    },
    "overheat": {
        "phase": "扩张（Expansion）",
        "equity_sectors": ["能源", "材料", "工业"],
        "crypto_analog": "主流层（BTC/ETH/SOL）+ 增长型层",
        "rationale": "增长与通胀同步上行，受益于价格与产能的板块领先",
    },
    "stagflation": {
        "phase": "放缓（Slowdown）",
        "equity_sectors": ["必需消费", "医疗", "公用事业"],
        "crypto_analog": "主流层（BTC 为主，防御性配置）",
        "rationale": "增长放缓+通胀高企，防御性板块相对抗跌",
    },
    "reflation": {
        "phase": "衰退（Recession）",
        "equity_sectors": ["公用事业", "金融", "债券类资产"],
        "crypto_analog": "现金/稳定币为主（广度坍塌期）",
        "rationale": "增长与通胀双降，久期资产与防御板块占优",
    },
}

# 传导链资产 → 层级（与 sector_transmission.json 对齐）
# V1.2：UNI/AAVE/NEAR/ARB/LINK 入验证白名单，归 L2_major 龙头梯队（历经完整牛熊）
CHAIN = {
    "BTC/USDT": "L1_anchor",
    "ETH/USDT": "L2_major",
    "SOL/USDT": "L2_major",
    "UNI/USDT": "L2_major",
    "AAVE/USDT": "L2_major",
    "NEAR/USDT": "L2_major",
    "ARB/USDT": "L2_major",
    "LINK/USDT": "L2_major",
    "AVAX/USDT": "L3_growth",
    "ADA/USDT": "L3_growth",
    "DOGE/USDT": "L4_meme",
    "PEPE/USDT": "L4_meme",
    "WIF/USDT": "L4_meme",
}


def fetch_okx_ma200(symbol, total=400):
    """分页拉取 OKX 日线，现算 MA200 位置。"""
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
    closes = [candles[k][4] for k in sorted(candles)][-total:]
    if len(closes) < 200:
        return None
    ma200 = sum(closes[-200:]) / 200
    last = closes[-1]
    return {
        "last_close": round(last, 6),
        "ma200": round(ma200, 6),
        "above": last > ma200,
        "distance_pct": round((last - ma200) / ma200 * 100, 2),
        "samples": len(closes),
    }


def main():
    now = datetime.now(timezone.utc).isoformat()

    with open(ROT) as f:
        rot = json.load(f)
    with open(STATE) as f:
        state = json.load(f)

    quadrant = rot["merrill_clock"]["quadrant"]
    quadrant_confidence = rot["merrill_clock"].get("confidence", "high")
    stovall = STOVALL_MAP[quadrant]

    # 锚点资产既有 MA200（白名单 8 资产 + ^GSPC）
    anchors = state.get("technical_anchor", {}).get("assets", {})
    anchor_map = {
        "BTC/USDT": anchors.get("BTC/USDT"),
        "ETH/USDT": anchors.get("ETH/USDT"),
        "SOL/USDT": anchors.get("SOL/USDT"),
        "UNI/USDT": anchors.get("UNI/USDT"),
        "AAVE/USDT": anchors.get("AAVE/USDT"),
        "NEAR/USDT": anchors.get("NEAR/USDT"),
        "ARB/USDT": anchors.get("ARB/USDT"),
        "LINK/USDT": anchors.get("LINK/USDT"),
    }

    # 传导链 14 资产广度（锚点复用 + L3/L4 现算）
    detail = {}
    for sym, layer in CHAIN.items():
        if sym in anchor_map and anchor_map[sym]:
            a = anchor_map[sym]
            detail[sym] = {
                "layer": layer,
                "above": a.get("above"),
                "distance_pct": a.get("distance_pct"),
                "source": "cycle_state_anchor",
            }
        else:
            m = fetch_okx_ma200(sym)
            if m is None:
                detail[sym] = {"layer": layer, "above": None, "source": "insufficient_data"}
            else:
                detail[sym] = {
                    "layer": layer,
                    "above": m["above"],
                    "distance_pct": m["distance_pct"],
                    "source": "okx_ma200",
                }

    # 分层广度统计
    layer_breadth = {}
    for layer in ("L1_anchor", "L2_major", "L3_growth", "L4_meme"):
        members = [d for d in detail.values() if d["layer"] == layer]
        valid = [d for d in members if d["above"] is not None]
        above = sum(1 for d in valid if d["above"])
        layer_breadth[layer] = {
            "above": above,
            "valid": len(valid),
            "total": len(members),
            "breadth_pct": round(above / len(valid) * 100, 1) if valid else None,
        }

    valid_all = [d for d in detail.values() if d["above"] is not None]
    above_all = sum(1 for d in valid_all if d["above"])
    breadth_pct = round(above_all / len(valid_all) * 100, 1) if valid_all else None

    if breadth_pct is None:
        breadth_state = "unknown"
    elif breadth_pct >= 75:
        breadth_state = "strong"
    elif breadth_pct >= 50:
        breadth_state = "mixed"
    else:
        breadth_state = "weak"

    out = {
        "generated_at": now,
        "stovall_rotation": {
            "quadrant": quadrant,
            "quadrant_confidence": quadrant_confidence,
            "phase": stovall["phase"],
            "equity_sector_preference": stovall["equity_sectors"],
            "crypto_layer_analog": stovall["crypto_analog"],
            "rationale": stovall["rationale"],
            "note": "预注册先验映射，仅输出板块偏好建议，不产生交易信号；置信度非 high 时建议降权使用",
        },
        "market_breadth": {
            "assets_above_ma200": above_all,
            "assets_valid": len(valid_all),
            "assets_total": len(detail),
            "breadth_pct": breadth_pct,
            "state": breadth_state,
            "layer_breadth": layer_breadth,
            "detail": detail,
            "note": "广度=传导链 14 资产站上 MA200 占比（L1/L2 复用锚点 8 资产，L3/L4 OKX 现算）；>=75 强势 / 50-75 分化 / <50 走弱；配合 meme 平台毕业率构成双层广度观测",
        },
    }

    with open(OUT, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    with open(TRANS) as f:
        trans = json.load(f)
    trans["breadth"] = out["market_breadth"]
    with open(TRANS, "w") as f:
        json.dump(trans, f, ensure_ascii=False, indent=2)

    print(f"quadrant={quadrant} (conf={quadrant_confidence}) -> Stovall phase: {stovall['phase']}")
    print(f"板块偏好: {stovall['equity_sectors']}")
    print(f"市场广度（14 资产）: {above_all}/{len(valid_all)} above MA200 = {breadth_pct}% ({breadth_state})")
    for layer, lb in layer_breadth.items():
        print(f"  {layer}: {lb['above']}/{lb['valid']} ({lb['breadth_pct']}%)")
    print(f"saved: {OUT}")


if __name__ == "__main__":
    main()
