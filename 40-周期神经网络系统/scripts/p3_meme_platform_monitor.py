#!/usr/bin/env python3
"""P3 meme 平台监控（L4 维度一 meme 层）：Pump 平台指标观测。

meme 热点更替快，固定代币清单会滞后，改为平台级指标观测：
  - 新池数量与毕业率（pumpswap 池占比，毕业=从 bonding curve 迁移到 AMM）
  - 新池 FDV 分布中位数
  - 买卖人数比、24h 价格变化分布
数据源：GeckoTerminal 公开 API（已验证可用，无需鉴权）。
产出：meme_platform.json
"""
import json
import urllib.request
from datetime import datetime, timezone
from statistics import median

API = "https://api.geckoterminal.com/api/v2/networks/solana/new_pools"
OUT = "/home/luke/dreambuddy/40-周期神经网络系统/meme_platform.json"
PAGES = 5  # 5 页 × 20 池 = 100 个最新池


def fetch_page(page):
    url = f"{API}?include=dex&page={page}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def main():
    now = datetime.now(timezone.utc).isoformat()

    pools = []
    dex_names = {}  # dex id -> name
    for page in range(1, PAGES + 1):
        try:
            d = fetch_page(page)
        except Exception as e:
            print(f"page {page} fetch error: {e}")
            break
        for inc in d.get("included", []):
            if inc.get("type") == "dex":
                dex_names[inc["id"]] = inc.get("attributes", {}).get("name", inc["id"])
        pools.extend(d.get("data", []))

    print(f"fetched pools={len(pools)}  dexs={sorted(set(dex_names))}")

    # 按 dex 关系归属分类（pool 的 relationships.dex.data.id）
    pump_fun_pools = []   # pump-fun：内盘 bonding curve
    pumpswap_pools = []    # pumpswap：毕业池（AMM）
    other_pools = []
    for p in pools:
        dex_id = (p.get("relationships", {}).get("dex", {}).get("data") or {}).get("id", "")
        if dex_id == "pump-fun":
            pump_fun_pools.append(p)
        elif dex_id == "pumpswap":
            pumpswap_pools.append(p)
        else:
            other_pools.append(p)

    def pool_stats(plist):
        fdvs = [float(p["attributes"]["fdv_usd"]) for p in plist
                if p["attributes"].get("fdv_usd") is not None]
        vol24 = [float(p["attributes"].get("volume_usd", {}).get("h24", 0)) for p in plist]
        buys = sum(int(p["attributes"].get("transactions", {}).get("h24", {}).get("buys", 0)) for p in plist)
        sells = sum(int(p["attributes"].get("transactions", {}).get("h24", {}).get("sells", 0)) for p in plist)
        chg = [float(p["attributes"].get("price_change_percentage", {}).get("h24", 0)) for p in plist]
        return {
            "count": len(plist),
            "fdv_median_usd": round(median(fdvs), 2) if fdvs else None,
            "fdv_max_usd": round(max(fdvs), 2) if fdvs else None,
            "vol24_total_usd": round(sum(vol24), 2),
            "buys_24h": buys,
            "sells_24h": sells,
            "buy_sell_ratio": round(buys / sells, 3) if sells else None,
            "chg24_median_pct": round(median(chg), 2) if chg else None,
        }

    n_pump = len(pump_fun_pools) + len(pumpswap_pools)
    graduation_rate = (len(pumpswap_pools) / n_pump * 100) if n_pump else None

    out = {
        "generated_at": now,
        "data_source": "GeckoTerminal public API /networks/solana/new_pools",
        "sample": {"pages": PAGES, "pools_total": len(pools)},
        "pump_platform": {
            "pump_fun_bonding_pools": pool_stats(pump_fun_pools),
            "pumpswap_graduated_pools": pool_stats(pumpswap_pools),
            "graduation_rate_pct": round(graduation_rate, 2) if graduation_rate is not None else None,
        },
        "other_dex_pools": pool_stats(other_pools),
        "note": "毕业率=新池样本中 pumpswap 池占比（毕业=从 bonding curve 迁移到 AMM）；毕业率上升=meme 热度健康，下降=热度退潮；回购费用指标需链上数据，列为后续扩展",
    }

    with open(OUT, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"pump-fun(内盘): {len(pump_fun_pools)}  pumpswap(毕业): {len(pumpswap_pools)}  "
          f"毕业率: {out['pump_platform']['graduation_rate_pct']}%")
    print(f"saved: {OUT}")


if __name__ == "__main__":
    main()
