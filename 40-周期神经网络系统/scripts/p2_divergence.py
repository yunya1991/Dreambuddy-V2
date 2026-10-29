#!/usr/bin/env python3
"""P2 背离检测：美林时钟象限（预期）vs 资产动量（真实）互为印证修正。

以 asset_rotation.json 中的象限判定为预期基准，对照六资产 3 月动量的
实际方向，逐项判定 consistent / divergent，并按背离数量对象限置信度降级。
结果写入 asset_rotation.json 的 divergence 字段。
"""
import json
import sqlite3
from datetime import datetime, timezone

ROT = "/home/luke/dreambuddy/40-周期神经网络系统/asset_rotation.json"
DB = "/home/luke/dreambuddy/18-数据获取中心/data_center.db"

# 各象限下资产的预期 3 月动量方向：+1 预期上涨 / -1 预期下跌 / 0 中性（不参与判定）
# crypto 视为高风险流动性资产，与股票同向处理
QUADRANT_RULES = {
    "recovery": {  # 增长↑ 通胀↓：股票强、商品强、债券中性偏弱、美元中性
        "equity_spx": +1,
        "crypto_btc": +1,
        "crypto_eth": +1,
        "gold_xaut": 0,
        "usd_dxy": 0,
        "rates_10y": +1,
    },
    "overheat": {  # 增长↑ 通胀↑：黄金/商品强、债券弱（收益率上行）、股票中性偏弱、美元偏弱
        "equity_spx": 0,
        "crypto_btc": +1,
        "crypto_eth": +1,
        "gold_xaut": +1,
        "usd_dxy": -1,
        "rates_10y": +1,
    },
    "stagflation": {  # 增长↓ 通胀↑：黄金强、股票弱、债券弱、美元中性
        "equity_spx": -1,
        "crypto_btc": -1,
        "crypto_eth": -1,
        "gold_xaut": +1,
        "usd_dxy": 0,
        "rates_10y": +1,
    },
    "reflation": {  # 增长↓ 通胀↓：债券强（收益率下行）、股票中性、黄金中性、美元偏强
        "equity_spx": 0,
        "crypto_btc": 0,
        "crypto_eth": 0,
        "gold_xaut": 0,
        "usd_dxy": +1,
        "rates_10y": -1,
    },
}

# 方向判定阈值：动量绝对值低于该值视为走平（flat）
FLAT_BAND = 1.0


def direction(momentum):
    if momentum is None:
        return None
    if momentum > FLAT_BAND:
        return +1
    if momentum < -FLAT_BAND:
        return -1
    return 0


def hy_oas_signal(window=20, widen_threshold=0.5):
    """HY OAS 信用利差走阔背离检测（v0.7 新增）。

    过热象限下风险偏好应扩张，信用利差持续走阔为反向证据：
    20 日走阔 >= widen_threshold → 背离信号（自动纳入背离计数）。
    """
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "SELECT timestamp, json_extract(metrics, '$.value') FROM records "
        "WHERE source = 'fred' AND sub_category = 'BAMLH0A0HYM2' ORDER BY timestamp",
    ).fetchall()
    conn.close()
    vals = [float(r[1]) for r in rows if r[1] is not None]
    dates = [r[0][:10] for r in rows if r[1] is not None]
    if len(vals) < window + 5:
        return None
    latest = vals[-1]
    prev = vals[-1 - window]
    change = round(latest - prev, 3)
    return {
        "latest": latest,
        "date": dates[-1],
        "change_20d": change,
        "widen_threshold": widen_threshold,
        "divergent": change >= widen_threshold,
    }


def downgrade_confidence(n_divergent):
    if n_divergent <= 1:
        return "high"
    if n_divergent == 2:
        return "medium"
    return "low"


def main():
    with open(ROT) as f:
        rot = json.load(f)

    quadrant = rot["merrill_clock"]["quadrant"]
    rules = QUADRANT_RULES[quadrant]
    momentum = rot["asset_momentum_3m_pct"]

    checks = []
    n_div = 0
    for asset, expected in rules.items():
        actual_mom = momentum.get(asset)
        actual_dir = direction(actual_mom)
        if expected == 0 or actual_dir is None:
            verdict = "neutral"
        elif actual_dir == expected:
            verdict = "consistent"
        elif actual_dir == 0:
            verdict = "flat"
        else:
            verdict = "divergent"
            n_div += 1
        checks.append({
            "asset": asset,
            "expected_dir": expected,
            "actual_momentum_3m_pct": actual_mom,
            "actual_dir": actual_dir,
            "verdict": verdict,
        })

    # HY OAS 信用利差走阔背离（v0.7 新增，自动纳入背离计数）
    oas = hy_oas_signal()
    if oas and oas["divergent"]:
        n_div += 1

    confidence = downgrade_confidence(n_div)
    rot["divergence"] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "quadrant": quadrant,
        "flat_band_pct": FLAT_BAND,
        "checks": checks,
        "n_divergent": n_div,
        "n_scored": sum(1 for c in checks if c["verdict"] != "neutral"),
        "hy_oas_check": oas,
        "quadrant_confidence": confidence,
        "note": "美林时钟（预期）vs 资产动量（真实）互为印证修正；背离数>1 时象限置信度降级；HY OAS 20日走阔>=0.5=信用利差背离（v0.7，候选移交23矛盾系统）",
    }
    rot["merrill_clock"]["confidence"] = confidence

    with open(ROT, "w") as f:
        json.dump(rot, f, ensure_ascii=False, indent=2)

    print(f"quadrant={quadrant}  divergent={n_div}  confidence={confidence}")
    for c in checks:
        print(f"  {c['asset']:<12} expected={c['expected_dir']:+d}  "
              f"actual={str(c['actual_momentum_3m_pct']):>7}%  {c['verdict']}")
    if oas:
        print(f"  HY_OAS        latest={oas['latest']}  chg20d={oas['change_20d']:+.2f}  "
              f"divergent={oas['divergent']}")


if __name__ == "__main__":
    main()
