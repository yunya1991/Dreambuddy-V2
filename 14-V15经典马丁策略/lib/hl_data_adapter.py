#!/usr/bin/env python3
"""
hl_data_adapter.py — Hyperliquid 数据适配器（V15 专用）
PROP-20260816C 模块1（用户批准 2026-08-16）

职责：把 experiments/ab-trading/execution/aster_spot.py 的 Hyperliquid 公共数据
包装成 OKX 客户端兼容接口（get_kline / get_ticker），供 market_data.fetch_candles
在 V15_DATA_SOURCE=hyperliquid 时透明替换 OKX 数据源。

背景（D链根因 #1）：腾讯云大陆封锁 www.okx.com 与 aws.okx.com，
OKX REST K线在生产环境 100% 超时，V15 只能吃降级模拟数据（假突破根因）。
HL API 在本机可达，且 V15 执行层已切 HL，数据源统一到 HL 消除基差。

接口契约（与 lib/okx_client.py 对齐）：
- get_kline(inst_id, bar, limit) -> {"ok", "inst_id", "bar", "candles": [{ts,o,h,l,c,vol}]}
  candles 按 OKX 约定【新→旧】排列（market_data.fetch_candles 会 reversed 成升序）
- get_ticker(inst_id) -> {"ok", "inst_id", "last", "bid", "ask", "vol24h", "ts"}

只读公共数据，不持有任何凭据。
"""
import os
import sys
import time
from typing import Dict, Optional

# aster_spot 所在目录：repo_root/experiments/ab-trading/execution
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_ASTER_DIR = os.path.join(_REPO_ROOT, "experiments", "ab-trading", "execution")

# OKX bar -> HL interval 映射（HL 官方: 1m 3m 5m 15m 30m 1h 2h 4h 8h 12h 1d 3d 1w 1M）
BAR_MAP = {
    "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1H": "1h", "1h": "1h", "1Hutc": "1h",
    "2H": "2h", "2h": "2h", "4H": "4h", "4h": "4h",
    "6H": "6h", "6h": "6h", "12H": "12h", "12h": "12h",
    "1D": "1d", "1d": "1d", "1Dutc": "1d",
    "1W": "1w", "1w": "1w", "1Wutc": "1w",
    "1M": "1M", "1mUtc": "1M",
}


def _coin_from_inst_id(inst_id: str) -> str:
    """BTC-USDT-SWAP / BTC-USDT / BTC -> BTC"""
    if not inst_id:
        return ""
    return inst_id.split("-")[0].upper()


class HLDataAdapter:
    """Hyperliquid 数据适配器（OKX 客户端鸭子类型兼容）"""

    def __init__(self):
        if _ASTER_DIR not in sys.path:
            sys.path.insert(0, _ASTER_DIR)
        self._aster = None
        self._last_error = ""

    # ── 内部 ──────────────────────────────────────────────

    def _ensure_aster(self):
        if self._aster is None:
            import aster_spot  # noqa: 延迟导入（依赖 requests）
            self._aster = aster_spot
        return self._aster

    def _has_credentials(self) -> bool:
        """公共数据无需凭据；保持与 OKX 客户端同名方法兼容"""
        return True

    # ── OKX 兼容接口 ──────────────────────────────────────

    def get_kline(self, inst_id: str = None, bar: str = "1H",
                  limit: int = 100) -> Dict:
        """拉取 K 线，返回 OKX get_kline 格式（candles 新→旧）"""
        coin = _coin_from_inst_id(inst_id or "BTC-USDT")
        if not coin:
            return {"ok": False, "error": f"无法解析币种: {inst_id}"}
        interval = BAR_MAP.get(bar)
        if interval is None:
            return {"ok": False, "error": f"不支持的 K 线周期: {bar}"}
        try:
            aster = self._ensure_aster()
            # HL 单次上限 5000 根；V15 日线需求 ~300 根，富余充足
            raw = aster.get_candles(coin, interval=interval, count=min(int(limit), 5000))
            if not raw:
                return {"ok": False, "error": f"HL 返回空数据: {coin} {interval}"}
            candles = []
            for c in raw:
                try:
                    candles.append({
                        "ts": int(c["t"]),        # HL: t=K线起始时间(ms)
                        "o": float(c["o"]),
                        "h": float(c["h"]),
                        "l": float(c["l"]),
                        "c": float(c["c"]),
                        "vol": float(c.get("v", 0)),
                    })
                except (KeyError, TypeError, ValueError):
                    continue
            if not candles:
                return {"ok": False, "error": f"HL K线解析失败: {coin} {interval}"}
            # HL 返回升序（旧→新）；OKX 约定降序（新→旧）
            candles.sort(key=lambda x: x["ts"], reverse=True)
            return {"ok": True, "inst_id": inst_id, "bar": bar, "candles": candles}
        except Exception as e:
            self._last_error = str(e)
            return {"ok": False, "error": f"HL K线异常: {e}"}

    def get_ticker(self, inst_id: str = None) -> Dict:
        """获取现价（HL allMids 中间价；bid/ask 用 mid 近似，V15 仅消费 last）"""
        coin = _coin_from_inst_id(inst_id or "BTC-USDT")
        if not coin:
            return {"ok": False, "error": f"无法解析币种: {inst_id}"}
        try:
            aster = self._ensure_aster()
            mids = aster.get_all_mids()
            px = mids.get(coin)
            if px is None:
                return {"ok": False, "error": f"HL 无该币种中间价: {coin}"}
            px = float(px)
            if px <= 0:
                return {"ok": False, "error": f"HL 中间价非法: {coin}={px}"}
            return {
                "ok": True,
                "inst_id": inst_id,
                "last": px,
                "bid": px,
                "ask": px,
                "vol24h": 0.0,
                "ts": str(int(time.time() * 1000)),
            }
        except Exception as e:
            self._last_error = str(e)
            return {"ok": False, "error": f"HL 现价异常: {e}"}

    def get_positions(self, inst_id: str = None) -> Dict:
        """数据适配器无持仓概念，返回空（持仓接口由执行客户端提供）"""
        return {"ok": True, "positions": [], "count": 0}

    # ── OKX REST 原始格式兼容（_get 鸭子类型）──────────────
    # strategy_params.py 的 fetch_*_klines 走 client._get("/api/v5/market/candles")
    # 并解析 OKX 原始格式 {"code":"0","data":[[ts,o,h,l,c,vol,...],...]}（新→旧）

    def _get(self, path: str, params: Dict = None, auth: bool = False) -> Dict:
        """兼容 OKX REST 公共行情端点；其余端点返回 code=1（调用方有兜底）"""
        params = params or {}
        try:
            if path == "/api/v5/market/candles":
                r = self.get_kline(params.get("instId"),
                                   bar=params.get("bar", "1H"),
                                   limit=int(params.get("limit", 100)))
                if not r.get("ok"):
                    return {"code": "1", "msg": r.get("error", "")}
                # candles 已是新→旧；补零对齐 OKX 10 列格式
                data = [[str(c["ts"]), str(c["o"]), str(c["h"]), str(c["l"]),
                         str(c["c"]), str(c["vol"]), "0", "0", "0", "0"]
                        for c in r["candles"]]
                return {"code": "0", "data": data}
            if path == "/api/v5/market/ticker":
                r = self.get_ticker(params.get("instId"))
                if not r.get("ok"):
                    return {"code": "1", "msg": r.get("error", "")}
                return {"code": "0", "data": [
                    {"last": str(r["last"]), "ts": r["ts"]}]}
        except Exception as e:
            return {"code": "1", "msg": str(e)}
        return {"code": "1", "msg": f"HL适配器不支持该端点: {path}"}


if __name__ == "__main__":
    # 自检：python hl_data_adapter.py
    a = HLDataAdapter()
    r = a.get_kline("BTC-USDT-SWAP", bar="1D", limit=5)
    print("get_kline BTC 1D x5:", {k: v for k, v in r.items() if k != "candles"},
          "| first:", r["candles"][0] if r.get("ok") else None)
    t = a.get_ticker("BTC-USDT-SWAP")
    print("get_ticker BTC:", t)
