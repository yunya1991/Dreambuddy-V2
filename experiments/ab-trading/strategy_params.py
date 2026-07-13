#!/usr/bin/env python3
"""
V15-CT 策略参数计算模块
- 动态止损：日线MA200 + EMA200
- 动态止盈：根据30天波动率调整（比特币基准）
- 动态加仓间距：根据30天波动率调整
- 三屏趋势过滤：周线+日线双周期趋势一致性检查（both_bear + MA104）
- 资金计算：基于保证金和名义价值
"""
import math
from typing import List, Optional, Tuple, Dict
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys

BASE_DIR = Path(__file__).parent

try:
    from config_loader import load_config, get_config, get_config_float, get_config_int, get_config_list
    load_config("v15ct")
except Exception:
    pass


def _calc_sma(closes: List[float], period: int) -> Optional[float]:
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def _calc_ema(closes: List[float], period: int) -> Optional[float]:
    if len(closes) < period:
        return None
    k = 2 / (period + 1)
    ema = closes[0]
    for p in closes[1:]:
        ema = p * k + ema * (1 - k)
    return ema


def calc_daily_ma200(klines_1d: List[Dict]) -> Optional[float]:
    closes = [float(k["c"]) for k in klines_1d if "c" in k]
    return _calc_sma(closes, 200)


def calc_daily_ema200(klines_1d: List[Dict]) -> Optional[float]:
    closes = [float(k["c"]) for k in klines_1d if "c" in k]
    return _calc_ema(closes, 200)


def calc_weekly_ma200(klines_1w: List[Dict]) -> Optional[float]:
    closes = [float(k["c"]) for k in klines_1w if "c" in k]
    return _calc_sma(closes, 200)


def calc_weekly_ema200(klines_1w: List[Dict]) -> Optional[float]:
    closes = [float(k["c"]) for k in klines_1w if "c" in k]
    return _calc_ema(closes, 200)


def calc_30d_volatility(klines_1d: List[Dict]) -> float:
    closes = [float(k["c"]) for k in klines_1d if "c" in k]
    if len(closes) < 31:
        return 0.02
    returns = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]
    recent_returns = returns[-30:]
    avg = sum(recent_returns) / len(recent_returns)
    variance = sum((r - avg) ** 2 for r in recent_returns) / len(recent_returns)
    return variance ** 0.5


def get_dynamic_stop_loss(direction: str, current_price: float,
                          daily_ma200: Optional[float], daily_ema200: Optional[float],
                          weekly_ma200: Optional[float] = None, weekly_ema200: Optional[float] = None,
                          last_daily_close: Optional[float] = None,
                          last_weekly_close: Optional[float] = None) -> Dict:
    """
    动态止损计算：
    1. 止损线 = 价格下方最近的一条均线（日MA200、日EMA200、周MA200、周EMA200）
    2. 是否触发 = 对应周期的已收盘价确认跌破（日线看昨收，周线看上周收）
       未收盘的周期不算跌破，即使实时价已在均线下方
    """
    result = {
        "stop_loss_price": None,
        "stop_loss_pct": None,
        "stop_type": None,
        "is_triggered": False,
        "daily_ma200": daily_ma200,
        "daily_ema200": daily_ema200,
        "weekly_ma200": weekly_ma200,
        "weekly_ema200": weekly_ema200,
        "last_daily_close": last_daily_close,
        "last_weekly_close": last_weekly_close,
        "above_daily_ma200_close": None,
        "above_daily_ema200_close": None,
        "above_weekly_ma200_close": None,
        "above_weekly_ema200_close": None,
    }

    if daily_ma200 is None and daily_ema200 is None and weekly_ma200 is None and weekly_ema200 is None:
        return result

    if last_daily_close is not None:
        result["above_daily_ma200_close"] = last_daily_close > daily_ma200 if daily_ma200 else None
        result["above_daily_ema200_close"] = last_daily_close > daily_ema200 if daily_ema200 else None
    if last_weekly_close is not None:
        result["above_weekly_ma200_close"] = last_weekly_close > weekly_ma200 if weekly_ma200 else None
        result["above_weekly_ema200_close"] = last_weekly_close > weekly_ema200 if weekly_ema200 else None

    if direction.upper() == "LONG":
        candidates = []
        if daily_ma200 is not None and daily_ma200 < current_price:
            dist = (current_price - daily_ma200) / current_price
            candidates.append(("日MA200", daily_ma200, dist, "daily"))
        if daily_ema200 is not None and daily_ema200 < current_price:
            dist = (current_price - daily_ema200) / current_price
            candidates.append(("日EMA200", daily_ema200, dist, "daily"))
        if weekly_ma200 is not None and weekly_ma200 < current_price:
            dist = (current_price - weekly_ma200) / current_price
            candidates.append(("周MA200", weekly_ma200, dist, "weekly"))
        if weekly_ema200 is not None and weekly_ema200 < current_price:
            dist = (current_price - weekly_ema200) / current_price
            candidates.append(("周EMA200", weekly_ema200, dist, "weekly"))

        if candidates:
            candidates.sort(key=lambda x: x[2])
            stop_type, stop_price, _, period = candidates[0]
            result["stop_loss_price"] = round(stop_price, 4)
            result["stop_loss_pct"] = round((current_price - stop_price) / current_price * 100, 2)
            result["stop_type"] = stop_type

            if period == "daily" and last_daily_close is not None:
                result["is_triggered"] = last_daily_close <= stop_price
            elif period == "weekly" and last_weekly_close is not None:
                result["is_triggered"] = last_weekly_close <= stop_price
            else:
                result["is_triggered"] = False
        else:
            all_below_daily = True
            if daily_ma200 is not None and last_daily_close is not None and last_daily_close > daily_ma200:
                all_below_daily = False
            if daily_ema200 is not None and last_daily_close is not None and last_daily_close > daily_ema200:
                all_below_daily = False
            all_below_weekly = True
            if weekly_ma200 is not None and last_weekly_close is not None and last_weekly_close > weekly_ma200:
                all_below_weekly = False
            if weekly_ema200 is not None and last_weekly_close is not None and last_weekly_close > weekly_ema200:
                all_below_weekly = False

            has_any_above = (not all_below_daily) or (not all_below_weekly)

            result["stop_loss_price"] = None
            result["stop_loss_pct"] = None
            result["stop_type"] = "BELOW_ALL_MA_INTRADAY" if has_any_above else "BELOW_ALL_MA_CONFIRMED"
            result["is_triggered"] = not has_any_above

    elif direction.upper() == "SHORT":
        candidates = []
        if daily_ma200 is not None and daily_ma200 > current_price:
            dist = (daily_ma200 - current_price) / current_price
            candidates.append(("日MA200", daily_ma200, dist, "daily"))
        if daily_ema200 is not None and daily_ema200 > current_price:
            dist = (daily_ema200 - current_price) / current_price
            candidates.append(("日EMA200", daily_ema200, dist, "daily"))
        if weekly_ma200 is not None and weekly_ma200 > current_price:
            dist = (weekly_ma200 - current_price) / current_price
            candidates.append(("周MA200", weekly_ma200, dist, "weekly"))
        if weekly_ema200 is not None and weekly_ema200 > current_price:
            dist = (weekly_ema200 - current_price) / current_price
            candidates.append(("周EMA200", weekly_ema200, dist, "weekly"))

        if candidates:
            candidates.sort(key=lambda x: x[2])
            stop_type, stop_price, _, period = candidates[0]
            result["stop_loss_price"] = round(stop_price, 4)
            result["stop_loss_pct"] = round((stop_price - current_price) / current_price * 100, 2)
            result["stop_type"] = stop_type

            if period == "daily" and last_daily_close is not None:
                result["is_triggered"] = last_daily_close >= stop_price
            elif period == "weekly" and last_weekly_close is not None:
                result["is_triggered"] = last_weekly_close >= stop_price
            else:
                result["is_triggered"] = False
        else:
            result["stop_loss_price"] = None
            result["stop_loss_pct"] = None
            result["stop_type"] = "ABOVE_ALL_MA"
            result["is_triggered"] = True

    return result


def get_vol_adjusted_params(coin_vol: float, btc_vol: float,
                            base_tp_pct: float = None,
                            base_addon_pct: float = None) -> Dict:
    if base_tp_pct is None:
        base_tp_pct = get_config_float("BASE_TP_PCT", 0.04)
    if base_addon_pct is None:
        base_addon_pct = get_config_float("ADDON_PCT", 0.08)

    if btc_vol <= 0:
        ratio = 1.0
    else:
        ratio = coin_vol / btc_vol

    ratio = max(0.5, min(2.5, ratio))

    tp_pct = base_tp_pct * ratio
    addon_pct = base_addon_pct * ratio

    return {
        "btc_volatility": round(btc_vol * 100, 4),
        "coin_volatility": round(coin_vol * 100, 4),
        "vol_ratio": round(ratio, 4),
        "take_profit_pct": round(tp_pct * 100, 2),
        "addon_pct": round(addon_pct * 100, 2),
        "base_tp_pct": round(base_tp_pct * 100, 2),
        "base_addon_pct": round(base_addon_pct * 100, 2),
    }


# ── 三屏趋势过滤 ──────────────────────────────────────────────────────────

TREND_FILTER_MODE = "both_bear"
TREND_FILTER_PERIOD = 104


def calc_sma_value(closes: List[float], period: int) -> Optional[float]:
    """计算SMA"""
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def check_trend_filter(current_price: float,
                       daily_klines: List[Dict],
                       weekly_klines: List[Dict],
                       mode: str = None,
                       period: int = None) -> Dict:
    """三屏趋势过滤检查
    
    借用三屏策略的周线/日线趋势一致性思路：
    - both_bear: 周线+日线都看空（价格在均线下方）时禁止做多
    - weekly_bear: 仅周线看空时禁止做多
    - none: 不过滤
    
    返回:
        {
            "blocked": bool,          # 是否禁止开多
            "mode": str,              # 过滤模式
            "period": int,            # 均线周期
            "weekly_ma": float/None,  # 周线MA值
            "daily_ma": float/None,   # 日线MA值
            "weekly_bear": bool,      # 周线是否看空
            "daily_bear": bool,       # 日线是否看空
            "reason": str,            # 原因说明
        }
    """
    if mode is None:
        mode = get_config("TREND_FILTER_MODE", TREND_FILTER_MODE)
    if period is None:
        period = get_config_int("TREND_FILTER_PERIOD", TREND_FILTER_PERIOD)
    
    result = {
        "blocked": False,
        "mode": mode,
        "period": period,
        "weekly_ma": None,
        "daily_ma": None,
        "weekly_bear": False,
        "daily_bear": False,
        "reason": "",
    }
    
    if mode == "none":
        result["reason"] = "趋势过滤未启用"
        return result
    
    # 计算周线MA
    weekly_closes = [float(k["c"]) for k in weekly_klines if "c" in k]
    weekly_ma = calc_sma_value(weekly_closes, period)
    result["weekly_ma"] = weekly_ma
    
    # 计算日线MA
    daily_closes = [float(k["c"]) for k in daily_klines if "c" in k]
    daily_ma = calc_sma_value(daily_closes, period)
    result["daily_ma"] = daily_ma
    
    weekly_bear = weekly_ma is not None and current_price < weekly_ma
    daily_bear = daily_ma is not None and current_price < daily_ma
    result["weekly_bear"] = weekly_bear
    result["daily_bear"] = daily_bear
    
    if mode == "both_bear":
        if weekly_bear and daily_bear:
            result["blocked"] = True
            result["reason"] = f"周线+日线均看空(价格<MA{period})，禁止做多"
        else:
            result["reason"] = f"周线{'看空' if weekly_bear else '看多'} + 日线{'看空' if daily_bear else '看多'}，允许做多"
    elif mode == "weekly_bear":
        if weekly_bear:
            result["blocked"] = True
            result["reason"] = f"周线看空(价格<MA{period})，禁止做多"
        else:
            result["reason"] = f"周线看多(价格≥MA{period})，允许做多"
    else:
        result["reason"] = f"未知过滤模式: {mode}"
    
    return result


def _get_okx_client():
    root_path = Path(__file__).resolve().parent.parent.parent
    yijing_path = root_path / "11-易经推理系统" / "scripts" / "memory_l4"
    sys.path.insert(0, str(yijing_path))
    try:
        from okx_simulated import OKXSimulatedClient
        from config_loader import get_config
        config = {
            "api_key": get_config("OKX_API_KEY", ""),
            "secret_key": get_config("OKX_SECRET_KEY", ""),
            "passphrase": get_config("OKX_PASSPHRASE", ""),
            "simulated": False,
            "dry_run": False,
            "base_url": "https://www.okx.com",
            "default_inst_id": "BTC-USDT-SWAP",
            "default_usdt_amount": 100,
            "default_leverage": 10,
        }
        return OKXSimulatedClient(config=config)
    except Exception:
        return None


def fetch_daily_klines(client, inst_id: str, limit: int = 250) -> List[Dict]:
    try:
        r = client._get(
            "/api/v5/market/candles",
            {"instId": inst_id, "bar": "1D", "limit": str(limit)},
            auth=False
        )
        if r.get("code") == "0" and r.get("data"):
            data = r["data"]
            klines = []
            for k in data:
                klines.append({
                    "t": int(k[0]),
                    "o": float(k[1]),
                    "h": float(k[2]),
                    "l": float(k[3]),
                    "c": float(k[4]),
                    "vol": float(k[5]) if len(k) > 5 else 0,
                })
            klines.reverse()
            return klines
    except Exception:
        pass
    return []


def fetch_weekly_klines(client, inst_id: str, limit: int = 200) -> List[Dict]:
    try:
        r = client._get(
            "/api/v5/market/candles",
            {"instId": inst_id, "bar": "1W", "limit": str(limit)},
            auth=False
        )
        if r.get("code") == "0" and r.get("data"):
            data = r["data"]
            klines = []
            for k in data:
                klines.append({
                    "t": int(k[0]),
                    "o": float(k[1]),
                    "h": float(k[2]),
                    "l": float(k[3]),
                    "c": float(k[4]),
                    "vol": float(k[5]) if len(k) > 5 else 0,
                })
            klines.reverse()
            return klines
    except Exception:
        pass
    return []


def get_coin_strategy_params(symbol: str, direction: str = "LONG") -> Dict:
    client = _get_okx_client()
    if not client:
        return {"error": "OKX客户端不可用"}

    inst_id = f"{symbol}-USDT-SWAP"

    btc_daily_raw = fetch_daily_klines(client, "BTC-USDT-SWAP", 251)
    coin_daily_raw = fetch_daily_klines(client, inst_id, 251)
    coin_weekly_raw = fetch_weekly_klines(client, inst_id, 201)

    btc_daily = btc_daily_raw[:-1] if len(btc_daily_raw) > 1 else btc_daily_raw
    coin_daily = coin_daily_raw[:-1] if len(coin_daily_raw) > 1 else coin_daily_raw
    coin_weekly = coin_weekly_raw[:-1] if len(coin_weekly_raw) > 1 else coin_weekly_raw

    btc_vol = calc_30d_volatility(btc_daily)
    coin_vol = calc_30d_volatility(coin_daily)

    daily_ma200 = calc_daily_ma200(coin_daily)
    daily_ema200 = calc_daily_ema200(coin_daily)
    weekly_ma200 = calc_weekly_ma200(coin_weekly)
    weekly_ema200 = calc_weekly_ema200(coin_weekly)

    last_daily_close = float(coin_daily[-1]["c"]) if coin_daily else None
    last_weekly_close = float(coin_weekly[-1]["c"]) if coin_weekly else None

    ticker = client.get_ticker(inst_id)
    current_price = float(ticker.get("last", 0)) if ticker.get("ok") else 0

    vol_params = get_vol_adjusted_params(coin_vol, btc_vol)
    stop_loss = get_dynamic_stop_loss(direction, current_price,
                                       daily_ma200, daily_ema200,
                                       weekly_ma200, weekly_ema200,
                                       last_daily_close, last_weekly_close)

    # 三屏趋势过滤
    trend_filter = check_trend_filter(current_price, coin_daily, coin_weekly)

    tp_pct_decimal = vol_params["take_profit_pct"] / 100
    addon_pct_decimal = vol_params["addon_pct"] / 100

    take_profit_price = round(current_price * (1 + tp_pct_decimal), 4) if direction == "LONG" else round(current_price * (1 - tp_pct_decimal), 4)

    return {
        "symbol": symbol,
        "direction": direction,
        "current_price": current_price,
        "last_daily_close": last_daily_close,
        "last_weekly_close": last_weekly_close,
        "volatility": vol_params,
        "stop_loss": stop_loss,
        "trend_filter": trend_filter,
        "take_profit_price": take_profit_price,
        "take_profit_pct": vol_params["take_profit_pct"],
        "addon_pct": vol_params["addon_pct"],
    }


def get_all_coins_params() -> Dict:
    coins = get_config_list("V15CT_COINS", default=["BTC", "ETH", "SOL", "ARB", "OP", "UNI", "HYPE", "OKB"])
    result = {}
    for coin in coins:
        try:
            result[coin] = get_coin_strategy_params(coin, "LONG")
        except Exception as e:
            result[coin] = {"error": str(e)}
    return result


if __name__ == "__main__":
    import json
    params = get_all_coins_params()
    print(json.dumps(params, indent=2, ensure_ascii=False))
