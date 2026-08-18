#!/usr/bin/env python3
"""
行情数据接入模块 - 获取真实 BTC 和美股数据
用于跨市场关联分析和投资决策支持
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path

# 尝试导入 requests，如果没有安装则使用 urllib
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    import urllib.request
    import urllib.error
    HAS_REQUESTS = False


def _http_get_json(url, params=None, timeout=10):
    if HAS_REQUESTS:
        resp = requests.get(
            url,
            params=params,
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        return resp.json()
    query = ""
    if params:
        from urllib.parse import urlencode
        query = "?" + urlencode(params)
    req = urllib.request.Request(url + query, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _http_get_json_with_retry(url, params=None, timeout=10, retries=3, backoff_s=0.6):
    last_err = None
    for i in range(max(1, int(retries))):
        try:
            return _http_get_json(url, params=params, timeout=timeout)
        except Exception as e:
            last_err = e
            if i < retries - 1:
                time.sleep(backoff_s * (2 ** i))
    raise last_err


def _extract_last_two_closes(closes):
    valid = [v for v in closes if isinstance(v, (int, float))]
    if len(valid) < 2:
        return None, None
    return float(valid[-1]), float(valid[-2])


def _fetch_yahoo_chart(symbol):
    data = _http_get_json(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
        params={"range": "5d", "interval": "1d"},
        timeout=10,
    )
    chart = data.get("chart", {})
    result = (chart.get("result") or [{}])[0]
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    close = quote.get("close") or []
    last_close, prev_close = _extract_last_two_closes(close)
    if not last_close or not prev_close:
        return None
    change_pct = (last_close - prev_close) / prev_close * 100
    return {"value": last_close, "change_24h": change_pct, "source": "Yahoo Finance"}


def _fetch_binance_24hr(symbol: str):
    data = _http_get_json_with_retry(
        "https://api.binance.com/api/v3/ticker/24hr",
        params={"symbol": symbol},
        timeout=10,
        retries=3,
        backoff_s=0.5,
    )
    price = float(data.get("lastPrice", 0) or 0)
    change_pct = float(data.get("priceChangePercent", 0) or 0)
    if price > 0:
        return {"price_usd": price, "change_24h": change_pct, "source": "Binance"}
    return None


def _fetch_coingecko_simple_price(coin_id: str):
    data = _http_get_json_with_retry(
        "https://api.coingecko.com/api/v3/simple/price",
        params={"ids": coin_id, "vs_currencies": "usd", "include_24h_change": "true"},
        timeout=12,
        retries=3,
        backoff_s=0.8,
    )
    c = (data or {}).get(coin_id, {}) or {}
    price = float(c.get("usd", 0) or 0)
    change_pct = float(c.get("usd_24h_change", 0) or 0)
    if price > 0:
        return {"price_usd": price, "change_24h": change_pct, "source": "CoinGecko"}
    return None


def fetch_btc_price():
    try:
        binance = _fetch_binance_24hr("BTCUSDT")
        if binance:
            return binance
    except Exception:
        pass
    try:
        cg = _fetch_coingecko_simple_price("bitcoin")
        if cg:
            return cg
    except Exception as e:
        return {"price_usd": 0, "change_24h": 0, "source": f"Error: {e}"}
    return {"price_usd": 0, "change_24h": 0, "source": "N/A"}


def fetch_eth_price():
    try:
        binance = _fetch_binance_24hr("ETHUSDT")
        if binance:
            return binance
    except Exception:
        pass
    try:
        cg = _fetch_coingecko_simple_price("ethereum")
        if cg:
            return cg
    except Exception as e:
        return {"price_usd": 0, "change_24h": 0, "source": f"Error: {e}"}
    return {"price_usd": 0, "change_24h": 0, "source": "N/A"}


def fetch_nasdaq_price():
    """获取纳斯达克 100 ETF (QQQ) 价格作为纳指代理"""
    api_key = os.environ.get("ALPHA_VANTAGE_API_KEY", "demo")

    try:
        data = _http_get_json_with_retry(
            "https://www.alphavantage.co/query",
            params={
                "function": "GLOBAL_QUOTE",
                "symbol": "QQQ",
                "apikey": api_key
            },
            timeout=10,
            retries=2,
            backoff_s=0.8,
        )
        quote = data.get("Global Quote", {})
        price = float(quote.get("05. price", 0))
        change = float(quote.get("10. change percent", "0%").replace("%", ""))
        if price > 0:
            return {
                "price_usd": price,
                "change_24h": change,
                "source": "Alpha Vantage"
            }
    except Exception:
        pass
    try:
        yahoo = _fetch_yahoo_chart("QQQ")
        if yahoo:
            return {
                "price_usd": yahoo["value"],
                "change_24h": yahoo["change_24h"],
                "source": yahoo["source"],
            }
    except Exception:
        pass
    return {"price_usd": 0, "change_24h": 0, "source": "N/A"}


def fetch_vix():
    """获取 VIX 恐慌指数"""
    try:
        data = _http_get_json_with_retry(
            "https://www.alphavantage.co/query",
            params={
                "function": "GLOBAL_QUOTE",
                "symbol": "^VIX",
                "apikey": os.environ.get("ALPHA_VANTAGE_API_KEY", "demo")
            },
            timeout=10,
            retries=2,
            backoff_s=0.8,
        )
        quote = data.get("Global Quote", {})
        value = float(quote.get("05. price", 0))
        if value > 0:
            return {
                "value": value,
                "source": "CBOE via Alpha Vantage"
            }
    except Exception:
        pass
    try:
        yahoo = _fetch_yahoo_chart("^VIX")
        if yahoo:
            return {"value": yahoo["value"], "source": yahoo["source"]}
    except Exception:
        pass
    return {"value": 0, "source": "N/A"}


def fetch_btc_etf_flows():
    """
    获取 BTC ETF 资金流向
    由于没有免费实时 API，返回结构化占位数据
    实际使用可接入：
    - Farside Investors (手动更新)
    - CoinGlass API
    """
    # 这里返回一个占位结构，实际可替换为真实 API
    return {
        "total_net_flow_usd": "需接入付费 API",
        "blackrock_ibit": "需接入付费 API",
        "note": "建议接入 CoinGlass 或 Farside Investors"
    }


def _read_snapshot_file(path: Path):
    try:
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_snapshot_file(path: Path, snapshot: dict):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2, ensure_ascii=False)
        tmp.replace(path)
    except Exception:
        pass


def _merge_snapshot_value(new_value: dict, cached_value: dict, key: str):
    if not isinstance(new_value, dict) or not isinstance(cached_value, dict):
        return new_value
    if key == "price_usd":
        if float(new_value.get("price_usd", 0) or 0) <= 0 and float(cached_value.get("price_usd", 0) or 0) > 0:
            return dict(cached_value)
    if key == "value":
        if float(new_value.get("value", 0) or 0) <= 0 and float(cached_value.get("value", 0) or 0) > 0:
            return dict(cached_value)
    return new_value


def get_market_snapshot():
    """获取完整市场快照"""
    base_dir = Path(__file__).parent.parent
    raw_dir = base_dir / "raw"
    latest_path = raw_dir / "market_snapshot_latest.json"
    cached = _read_snapshot_file(latest_path) or {}

    btc = fetch_btc_price()
    eth = fetch_eth_price()
    nasdaq = fetch_nasdaq_price()
    vix = fetch_vix()

    cached_btc = (cached.get("crypto") or {}).get("btc") or {}
    cached_eth = (cached.get("crypto") or {}).get("eth") or {}
    cached_nasdaq = (cached.get("traditional") or {}).get("nasdaq") or {}
    cached_vix = (cached.get("traditional") or {}).get("vix") or {}

    btc = _merge_snapshot_value(btc, cached_btc, "price_usd")
    eth = _merge_snapshot_value(eth, cached_eth, "price_usd")
    nasdaq = _merge_snapshot_value(nasdaq, cached_nasdaq, "price_usd")
    vix = _merge_snapshot_value(vix, cached_vix, "value")

    etf_flows = fetch_btc_etf_flows()

    btc_p = float((btc or {}).get("price_usd", 0) or 0)
    eth_p = float((eth or {}).get("price_usd", 0) or 0)
    eth_btc_ratio = eth_p / btc_p if btc_p > 0 else 0

    snapshot = {
        "timestamp": datetime.now().isoformat(),
        "crypto": {
            "btc": btc,
            "eth": eth,
            "eth_btc_ratio": eth_btc_ratio
        },
        "traditional": {
            "nasdaq": nasdaq,
            "vix": vix
        },
        "institutional": {
            "btc_etf_flows": etf_flows
        }
    }

    # 计算简单的相关性判断
    btc_change = btc.get("change_24h", 0)
    nasdaq_change = nasdaq.get("change_24h", 0)

    if btc_change and nasdaq_change:
        same_direction = (btc_change > 0) == (nasdaq_change > 0)
        snapshot["correlation_signal"] = {
            "same_direction": same_direction,
            "interpretation": "正相关" if same_direction else "负相关/独立行情"
        }

    _write_snapshot_file(latest_path, snapshot)

    return snapshot


def main():
    """测试行情数据获取"""
    print("=== 行情数据接入测试 ===")

    snapshot = get_market_snapshot()

    print(f"\n时间戳：{snapshot['timestamp']}")
    print("\n【加密货币】")
    print(f"  BTC: ${snapshot['crypto']['btc']['price_usd']:.2f} ({snapshot['crypto']['btc']['change_24h']:.2f}%)")
    print(f"  ETH: ${snapshot['crypto']['eth']['price_usd']:.2f} ({snapshot['crypto']['eth']['change_24h']:.2f}%)")
    print(f"  ETH/BTC: {snapshot['crypto']['eth_btc_ratio']:.4f}")

    print("\n【传统市场】")
    print(f"  纳斯达克 (QQQ): ${snapshot['traditional']['nasdaq']['price_usd']:.2f} ({snapshot['traditional']['nasdaq']['change_24h']:.2f}%)")
    print(f"  VIX: {snapshot['traditional']['vix']['value']:.2f}")

    if "correlation_signal" in snapshot:
        print("\n【相关性信号】")
        print(f"  方向：{snapshot['correlation_signal']['interpretation']}")

    print("\n【ETF 资金流】")
    print(f"  {snapshot['institutional']['btc_etf_flows']}")

    # 保存快照
    output_path = Path(__file__).parent.parent / "raw" / f"market_snapshot_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)

    print(f"\n[✓] 快照已保存：{output_path}")

    return snapshot


if __name__ == "__main__":
    main()
