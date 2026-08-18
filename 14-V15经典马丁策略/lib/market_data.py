#!/usr/bin/env python3
"""
市场数据模块 - V15经典马丁策略专用
- K线数据获取（OKX API / OKX CLI 双路降级）
- 常用技术指标计算（SMA/EMA/RSI）
"""
import json, os, subprocess, sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / "lib"))

from config_loader import get_config


def _get_okx_client():
    """获取行情客户端（V15_DATA_SOURCE=hyperliquid 时透明切 HL 数据适配器）"""
    # PROP-20260816C 模块1（用户批准 2026-08-16）：
    # 腾讯云大陆封锁 OKX 网络，K线统一改走 Hyperliquid（本机可达、与执行层同源无基差）
    if get_config("V15_DATA_SOURCE", "").strip().lower() == "hyperliquid":
        try:
            from hl_data_adapter import HLDataAdapter
            return HLDataAdapter()
        except Exception:
            return None
    try:
        from okx_client import OKXSimulatedClient
        client = OKXSimulatedClient()
        return client
    except Exception:
        return None


def _run_okx(args):
    """通过 OKX CLI 执行命令（降级方案）"""
    profile = get_config("OKX_PROFILE", "screen_trade")
    home_bin = "/opt/homebrew/bin"
    env = {**os.environ, "NO_UPDATE_CHECK": "1", "PATH": home_bin + ":" + os.environ.get("PATH", "")}
    try:
        r = subprocess.run(
            ["okx", "--profile", profile] + args,
            capture_output=True, text=True, timeout=15,
            env=env
        )
        stdout = "\n".join(l for l in r.stdout.split("\n") if "Update available" not in l and "Run: npm" not in l).strip()
        stderr = "\n".join(l for l in r.stderr.split("\n") if "Update available" not in l and "Run: npm" not in l).strip()
        if r.returncode != 0 and stderr:
            return {"ok": False, "err": stderr[:200]}
        if stdout.startswith("[") or stdout.startswith("{"):
            return {"ok": True, "data": json.loads(stdout)}
        return {"ok": True, "data": stdout}
    except Exception as e:
        return {"ok": False, "err": str(e)}


def fetch_candles(inst_id: str, bar: str = "4H", limit: int = 200) -> list:
    """
    获取K线数据
    :param inst_id: 交易对ID，如 BTC-USDT
    :param bar: K线周期，如 1H, 4H, 1D, 1W
    :param limit: 获取数量
    :return: K线列表，按时间正序排列，每条包含 ts/o/h/l/c/vol
    """
    client = _get_okx_client()
    if client:
        try:
            r = client.get_kline(inst_id, bar=bar, limit=limit)
            if r.get("ok"):
                candles = []
                for c in r.get("candles", []):
                    candles.append({
                        "ts": int(c["ts"]),
                        "o": float(c["o"]),
                        "h": float(c["h"]),
                        "l": float(c["l"]),
                        "c": float(c["c"]),
                        "vol": float(c.get("vol", 0)),
                    })
                return list(reversed(candles))
        except Exception:
            pass
    r = _run_okx(["market", "candles", inst_id, "--bar", bar, "--limit", str(limit), "--json"])
    if not r["ok"]:
        return []
    raw = r["data"]
    candles = []
    for c in raw:
        candles.append({
            "ts": int(c[0]),
            "o": float(c[1]),
            "h": float(c[2]),
            "l": float(c[3]),
            "c": float(c[4]),
            "vol": float(c[5]),
        })
    return list(reversed(candles))


def calc_sma(values: list, period: int) -> float:
    """计算简单移动平均"""
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def calc_ema(values: list, period: int) -> float:
    """计算指数移动平均"""
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    ema = values[0]
    for v in values[1:]:
        ema = v * k + ema * (1 - k)
    return ema


def calc_rsi(prices: list, period: int = 14) -> float:
    """计算RSI指标"""
    if len(prices) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(prices)):
        d = prices[i] - prices[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)
