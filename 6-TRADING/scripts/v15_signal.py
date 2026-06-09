#!/usr/bin/env python3
"""
V15 基线实时信号计算器 v1.1
数据来源:
  历史 K 线 (SMA/RSI/Fib) → Binance 公开 klines API（免鉴权）
  当前价格 (无 --price 时)  → Tavily 搜索 (TAVILY_API_KEY 环境变量)
输出 V15 机械入场信号，供 screen2_runner.py Phase-D 裁决层使用。

独立运行: python v15_signal.py [--direction SHORT|LONG] [--price 103500]
"""
import json, sys, io, ssl, argparse, re, os, urllib.request
from datetime import datetime, timezone

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

BINANCE_KLINES_URL = (
    'https://api.binance.com/api/v3/klines'
    '?symbol=BTCUSDT&interval=1d&limit=201'
)
TAVILY_SEARCH_URL = 'https://api.tavily.com/search'

ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

SMA_PERIODS  = [30, 65, 128, 200]
FIB_LOOKBACK = 30   # 近 N 日的 swing high/low
RSI_PERIOD   = 14
GRID_DEFAULT = 0.015  # V15 默认层间距 1.5%


# ─── 数据获取 ──────────────────────────────────────────────────────────────────

def _parse_binance_klines(raw: str, days: int) -> list:
    """将 Binance klines JSON 字符串解析为收盘价列表。"""
    data = json.loads(raw)
    prices = [float(candle[4]) for candle in data]   # index 4 = close
    return prices[-days:]


def fetch_prices_direct(days: int = 200) -> list:
    """直连 Binance 公开 klines API（无需鉴权）。"""
    url = f'https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1d&limit={days + 1}'
    req = urllib.request.Request(url, headers={'User-Agent': '6-trading-v15/1.0'})
    with urllib.request.urlopen(req, context=ssl_ctx, timeout=30) as r:
        return _parse_binance_klines(r.read(), days)


def fetch_prices_via_tavily(tavily_key: str, days: int = 200) -> list:
    """通过 Tavily /extract 代理抓取 Binance klines（本机网络受限时回退）。"""
    binance_url = (
        f'https://api.binance.com/api/v3/klines'
        f'?symbol=BTCUSDT&interval=1d&limit={days + 1}'
    )
    payload = json.dumps({'api_key': tavily_key, 'urls': [binance_url]}).encode()
    req = urllib.request.Request(
        'https://api.tavily.com/extract', data=payload,
        headers={'Content-Type': 'application/json'},
    )
    with urllib.request.urlopen(req, context=ssl_ctx, timeout=45) as r:
        result = json.loads(r.read())
    results = result.get('results', [])
    if not results:
        raise ValueError('Tavily extract: no results returned')
    raw = results[0].get('raw_content', '')
    return _parse_binance_klines(raw, days)


def fetch_prices(days: int = 200) -> list:
    """
    获取 BTC 日线收盘价:
      1. 直连 Binance klines（优先，Hermes/生产环境）
      2. Tavily /extract 代理 Binance（本机网络受限回退，需 TAVILY_API_KEY）
    """
    try:
        return fetch_prices_direct(days)
    except Exception as e:
        print(f'[v15] Binance direct failed ({e.__class__.__name__}), trying Tavily extract...',
              file=sys.stderr)
    tavily_key = os.environ.get('TAVILY_API_KEY', '')
    if not tavily_key:
        raise RuntimeError('Binance unreachable and TAVILY_API_KEY not set')
    return fetch_prices_via_tavily(tavily_key, days)


def fetch_price_tavily(tavily_key: str) -> float | None:
    """Tavily 搜索获取 BTC 当前价格（独立运行且无 --price 时调用）。"""
    payload = json.dumps({
        'api_key': tavily_key,
        'query': 'Bitcoin BTC price USD current',
        'search_depth': 'basic',
        'max_results': 3,
    }).encode()
    req = urllib.request.Request(
        TAVILY_SEARCH_URL, data=payload,
        headers={'Content-Type': 'application/json'},
    )
    with urllib.request.urlopen(req, context=ssl_ctx, timeout=30) as r:
        result = json.loads(r.read())
    text = ' '.join(item.get('content', '') for item in result.get('results', []))
    for pattern in [
        r'\$?\b(7[0-9],\d{3}|8[0-9],\d{3}|9[0-9],\d{3}|1[01][0-9],\d{3})\b',
        r'\b(7\d{4}|8\d{4}|9\d{4}|1[01]\d{4})\b',
    ]:
        m = re.findall(pattern, text)
        if m:
            return float(m[0].replace(',', ''))
    return None


# ─── 技术指标 ──────────────────────────────────────────────────────────────────

def calc_sma(prices: list, period: int):
    if len(prices) < period:
        return None
    return sum(prices[-period:]) / period


def calc_rsi(prices: list, period: int = 14) -> float:
    if len(prices) < period + 1:
        return 50.0
    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    recent = deltas[-period:]
    gains  = [max(d, 0) for d in recent]
    losses = [max(-d, 0) for d in recent]
    avg_g  = sum(gains) / period
    avg_l  = sum(losses) / period
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return round(100 - 100 / (1 + rs), 2)


def determine_position(price: float, smas: dict) -> str:
    valid = {k: v for k, v in smas.items() if v is not None}
    if not valid:
        return 'IN_ZONE'
    if all(price > v for v in valid.values()):
        return 'ABOVE_ALL'
    if all(price < v for v in valid.values()):
        return 'BELOW_ALL'
    return 'IN_ZONE'


def calc_fibonacci(prices: list, lookback: int = 30) -> dict:
    window     = prices[-lookback:]
    swing_high = max(window)
    swing_low  = min(window)
    rng        = swing_high - swing_low
    return {
        'swing_high': round(swing_high),
        'swing_low':  round(swing_low),
        'f382':       round(swing_low + 0.382 * rng),
        'f500':       round(swing_low + 0.500 * rng),
        'f618':       round(swing_low + 0.618 * rng),
    }


# ─── V15 信号逻辑 ──────────────────────────────────────────────────────────────

def _make_layers(entry: float, direction: str, size_mult: float,
                 tp, sl, position_cap: float = 150) -> list:
    sign  = 1 if direction == 'SHORT' else -1
    l0_sz = round(position_cap * 0.30 * size_mult, 1)
    rest  = round(position_cap - l0_sz, 1)
    pcts  = [l0_sz] + [round(rest / 3, 1)] * 3
    return [
        {
            'layer': f'L{i}', 'type': 'limit', 'direction': direction,
            'price': round(entry * (1 + sign * GRID_DEFAULT * i)),
            'size_usdt': pcts[i], 'tp': tp, 'sl': sl, 'status': 'pending',
        }
        for i in range(4)
    ]


def calc_v15_signal(price: float, position: str, fib: dict, rsi: float,
                    screen1_direction: str, position_cap: float = 150) -> dict:
    """
    BELOW_ALL:  price 在 [f382, f618] 且 RSI > 45 → SHORT 马丁格
    ABOVE_ALL:  price 在回调 [f618_long, f382_long] 且 RSI < 55 → LONG 马丁格
    IN_ZONE:    RSI < 35 → LONG 单层；RSI > 65 → SHORT 单层；else WAIT
    """
    if position == 'BELOW_ALL':
        in_zone = fib['f382'] <= price <= fib['f618']
        if in_zone and rsi > 45:
            size_mult = 1.0 if price >= fib['f500'] else 0.5
            fib_zone  = 'golden' if price >= fib['f500'] else 'shallow'
            tp = round(fib['swing_low'] * 0.95)
            sl = round(fib['f618'] * 1.02)
            orders = _make_layers(price, 'SHORT', size_mult, tp, sl, position_cap)
            return {
                'signal': 'SHORT', 'entry': round(price),
                'TP': tp, 'SL': sl, 'fib_zone': fib_zone,
                'size_mult': size_mult, 'rsi': rsi, 'position': position,
                'in_fib_zone': True, 'orders': orders,
            }
        return {
            'signal': 'WAIT', 'rsi': rsi, 'position': position,
            'in_fib_zone': in_zone,
            'reason': 'not in Fib zone' if not in_zone else 'RSI <= 45',
        }

    elif position == 'ABOVE_ALL':
        # 回调 Fib（从 swing_high 往下量）
        rng       = fib['swing_high'] - fib['swing_low']
        f382_long = round(fib['swing_high'] - 0.382 * rng)
        f500_long = round(fib['swing_high'] - 0.500 * rng)
        f618_long = round(fib['swing_high'] - 0.618 * rng)
        in_zone   = f618_long <= price <= f382_long
        if in_zone and rsi < 55:
            size_mult = 1.0 if price <= f500_long else 0.5
            fib_zone  = 'golden' if price <= f500_long else 'shallow'
            tp = round(fib['swing_high'] * 1.05)
            sl = round(f618_long * 0.98)
            orders = _make_layers(price, 'LONG', size_mult, tp, sl, position_cap)
            return {
                'signal': 'LONG', 'entry': round(price),
                'TP': tp, 'SL': sl, 'fib_zone': fib_zone,
                'size_mult': size_mult, 'rsi': rsi, 'position': position,
                'in_fib_zone': True, 'orders': orders,
                'fib_long': {'f382': f382_long, 'f500': f500_long, 'f618': f618_long},
            }
        return {
            'signal': 'WAIT', 'rsi': rsi, 'position': position,
            'in_fib_zone': in_zone,
            'reason': 'not in Fib pullback zone' if not in_zone else 'RSI >= 55',
        }

    else:  # IN_ZONE — BB 简化替代
        if rsi < 35:
            tp = round(price * 1.05)
            sl = round(price * 0.97)
            orders = _make_layers(price, 'LONG', 1.0, tp, sl, position_cap)
            return {'signal': 'LONG', 'entry': round(price), 'TP': tp, 'SL': sl,
                    'rsi': rsi, 'position': position, 'reason': 'IN_ZONE RSI oversold',
                    'orders': orders}
        elif rsi > 65:
            tp = round(price * 0.95)
            sl = round(price * 1.03)
            orders = _make_layers(price, 'SHORT', 1.0, tp, sl, position_cap)
            return {'signal': 'SHORT', 'entry': round(price), 'TP': tp, 'SL': sl,
                    'rsi': rsi, 'position': position, 'reason': 'IN_ZONE RSI overbought',
                    'orders': orders}
        return {'signal': 'WAIT', 'rsi': rsi, 'position': position,
                'reason': 'IN_ZONE no extreme RSI'}


# ─── 主函数 ────────────────────────────────────────────────────────────────────

def run(screen1_direction: str = 'SHORT',
        current_price_override: float = None,
        position_cap: float = 150) -> dict:
    prices = fetch_prices(200)
    if current_price_override:
        price = current_price_override
    else:
        tavily_key = os.environ.get('TAVILY_API_KEY', '')
        price = (fetch_price_tavily(tavily_key) if tavily_key else None) or prices[-1]

    smas     = {p: calc_sma(prices, p) for p in SMA_PERIODS}
    rsi      = calc_rsi(prices, RSI_PERIOD)
    position = determine_position(price, smas)
    fib      = calc_fibonacci(prices, FIB_LOOKBACK)
    signal   = calc_v15_signal(price, position, fib, rsi, screen1_direction, position_cap)

    return {
        'date':           datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        'current_price':  round(price),
        'sma30':          round(smas[30])  if smas[30]  else None,
        'sma65':          round(smas[65])  if smas[65]  else None,
        'sma128':         round(smas[128]) if smas[128] else None,
        'sma200':         round(smas[200]) if smas[200] else None,
        'rsi14':          rsi,
        'price_position': position,
        'fibonacci':      fib,
        'v15_signal':     signal,
        'screen1_direction': screen1_direction,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--direction', default='SHORT')
    parser.add_argument('--price', type=float, default=None)
    args = parser.parse_args()

    result = run(screen1_direction=args.direction, current_price_override=args.price)
    print(json.dumps(result, ensure_ascii=False, indent=2))
