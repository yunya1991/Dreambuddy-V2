#!/usr/bin/env python3
"""P3 洗盘识别接入（L4 维度二）：复用 11-易经推理系统 bcrm2 洗盘模块。

对板块传导链资产调用 WashoutDetector 输出 WashoutVerdict：
  washout（洗盘→持有）/ weakness（真弱势→加速离场）/ unknown（未触发或不确定）
触发门仅在『上涨后回调』场景激活（30d 涨幅≥15% + 回撤≥5% + MA200 之上），
未触发返回 unknown 属正常设计。
funding/OI 取自 USDT 本位永续合约；K 线分页拉取 400 根（OKX 单次上限 100 根，
触发门 MA200 检查要求 ≥200 根）。
产出：washout_verdicts.json
"""
import json
import sys
from datetime import datetime, timezone

import pandas as pd

BCRM2 = "/home/luke/dreambuddy/11-易经推理系统/scripts/memory_l4"
OUT = "/home/luke/dreambuddy/40-周期神经网络系统/washout_verdicts.json"

sys.path.insert(0, BCRM2)

from bcrm2.washout_detector import WashoutDetector  # noqa: E402
from bcrm2.washout_features import WashoutFeatureExtractor  # noqa: E402
from bcrm2.washout_classifier import EnhancedWashoutClassifier  # noqa: E402

# 传导链资产（与 sector_transmission.json 对齐）
ASSETS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT",
    "AVAX/USDT", "LINK/USDT", "ADA/USDT",
    "DOGE/USDT", "PEPE/USDT", "WIF/USDT",
]

DAY_MS = 86400000


def fetch_ohlcv_all(ex, symbol, total=400):
    """分页拉取日线 K 线（OKX 单次上限 100 根），凑足 total 根。"""
    candles = {}
    since = ex.milliseconds() - (total + 5) * DAY_MS
    while len(candles) < total:
        batch = ex.fetch_ohlcv(symbol, "1d", since=since, limit=100)
        if not batch:
            break
        for c in batch:
            candles[c[0]] = c
        since = batch[-1][0] + DAY_MS
        if len(batch) < 100:
            break
    rows = [candles[k] for k in sorted(candles)][-total:]
    if not rows:
        return None
    df = pd.DataFrame(
        rows, columns=["ts", "open", "high", "low", "close", "volume"]
    )
    return df[["open", "high", "low", "close", "volume"]].astype(float)


def fetch_funding_series(ex, swap_symbol):
    try:
        fr = ex.fetch_funding_rate_history(swap_symbol, limit=90)
        return [r["fundingRate"] for r in fr if r.get("fundingRate") is not None]
    except Exception:
        return None


def fetch_oi_series(ex, swap_symbol):
    try:
        oi = ex.fetch_open_interest_history(swap_symbol, "1d", limit=30)
        return [r.get("openInterestAmount") for r in oi
                if r.get("openInterestAmount") is not None]
    except Exception:
        return None


def main():
    import ccxt
    ex = ccxt.okx({"enableRateLimit": True})

    detector = WashoutDetector(
        enable=True,
        classifier=EnhancedWashoutClassifier(),
        feature_extractor=WashoutFeatureExtractor(),
    )

    # BTC 收盘序列（供 btc_correlation_30d 特征）
    btc_df = fetch_ohlcv_all(ex, "BTC/USDT")
    btc_close_series = btc_df["close"].tolist() if btc_df is not None else None

    verdicts = {}
    for sym in ASSETS:
        swap = f"{sym}:USDT"  # USDT 本位永续合约
        try:
            df = fetch_ohlcv_all(ex, sym)
            if df is None or len(df) < 200:
                verdicts[sym] = {
                    "error": "insufficient_ohlcv",
                    "samples": 0 if df is None else len(df),
                }
                print(f"{sym:<12} ERROR insufficient_ohlcv ({0 if df is None else len(df)})")
                continue
            macro_data = {
                "btc_close_series": btc_close_series,
                "funding_rate_series": fetch_funding_series(ex, swap),
                "oi_series": fetch_oi_series(ex, swap),
            }
            v = detector.run(sym, df, macro_data)
            d = v.to_dict()
            d["samples"] = len(df)
            verdicts[sym] = d
            print(f"{sym:<12} {d['label']:<8} conf={d['confidence']:.2f} "
                  f"trigger={d['trigger_activated']} reason={d['reason']}")
        except Exception as e:
            verdicts[sym] = {"error": str(e)[:120]}
            print(f"{sym:<12} ERROR {e}")

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "module": "11-易经推理系统/bcrm2/WashoutDetector（复用不复制）",
        "trigger_gate": "30d涨幅>=15% + 距高点回撤>=5% + MA200之上",
        "data_source": "OKX 现货 OHLCV（分页 400 根）+ USDT 本位永续合约 funding/OI；CVD 无数据走中性默认",
        "verdicts": verdicts,
        "note": "unknown 含未触发触发门与信号不足场景（非故障）；washout=洗盘持有，weakness=真弱势",
    }
    with open(OUT, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"saved: {OUT}")


if __name__ == "__main__":
    main()
