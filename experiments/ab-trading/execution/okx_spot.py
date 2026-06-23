#!/usr/bin/env python3
"""
OKX 现货执行层 - 双账户版
支持 Agent A / Agent B 两个独立账户
"""
import os, json, time, hmac, base64, hashlib, requests
from typing import Dict, Optional
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "../config/.env"))

BASE_URL = "https://www.okx.com"

# 从 .env 读取代理设置，requests 会自动使用 HTTP_PROXY / HTTPS_PROXY 环境变量
# 如果未设置则不走代理（服务器环境直连）
_PROXIES: Optional[Dict] = None
_https_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
_http_proxy  = os.environ.get("HTTP_PROXY")  or os.environ.get("http_proxy")
if _https_proxy or _http_proxy:
    _PROXIES = {}
    if _https_proxy: _PROXIES["https"] = _https_proxy
    if _http_proxy:  _PROXIES["http"]  = _http_proxy


class OKXSpotClient:
    def __init__(self, agent_id: str):
        prefix = f"AGENT_{agent_id.upper()}_OKX"
        self.api_key     = os.environ[f"{prefix}_KEY"]
        self.secret_key  = os.environ[f"{prefix}_SECRET"]
        self.passphrase  = os.environ[f"{prefix}_PASSPHRASE"]
        self.agent_id    = agent_id

    def _headers(self, method: str, path: str, body: str = "") -> Dict:
        ts = time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime())
        msg = ts + method + path + body
        sign = base64.b64encode(
            hmac.new(self.secret_key.encode(), msg.encode(), hashlib.sha256).digest()
        ).decode()
        return {
            "OK-ACCESS-KEY": self.api_key,
            "OK-ACCESS-SIGN": sign,
            "OK-ACCESS-TIMESTAMP": ts,
            "OK-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
        }

    def _get(self, path: str, params: Optional[Dict] = None) -> Dict:
        sign_path = path
        if params:
            qs = "&".join(f"{k}={v}" for k, v in params.items())
            sign_path = f"{path}?{qs}"
        resp = requests.get(BASE_URL + path, params=params,
                            headers=self._headers("GET", sign_path),
                            proxies=_PROXIES, timeout=15)
        return resp.json()

    def _post(self, path: str, body: Dict) -> Dict:
        body_str = json.dumps(body)
        resp = requests.post(BASE_URL + path, data=body_str,
                             headers=self._headers("POST", path, body_str),
                             proxies=_PROXIES, timeout=15)
        return resp.json()

    # ── 账户信息 ──────────────────────────────────────────────────

    def get_balance(self) -> Dict:
        """获取账户余额，返回 {total_eq, usdt_avail, btc_avail}"""
        r = self._get("/api/v5/account/balance")
        if r.get("code") != "0":
            return {"ok": False, "error": r}
        acct = r["data"][0]
        result = {"ok": True, "total_eq": float(acct["totalEq"]), "assets": {}}
        for d in acct.get("details", []):
            result["assets"][d["ccy"]] = {
                "avail": float(d.get("availBal", 0)),
                "total": float(d.get("cashBal", 0)),
            }
        return result

    def get_ticker(self, inst_id: str = "BTC-USDT") -> Dict:
        """获取当前价格"""
        r = self._get("/api/v5/market/ticker", {"instId": inst_id})
        if r.get("code") != "0":
            return {"ok": False, "error": r}
        d = r["data"][0]
        return {
            "ok": True,
            "inst_id": inst_id,
            "last": float(d["last"]),
            "bid": float(d["bidPx"]),
            "ask": float(d["askPx"]),
            "vol24h": float(d["vol24h"]),
        }

    def get_positions(self, inst_id: str = "BTC-USDT") -> Dict:
        """获取现货持仓（BTC余额）"""
        bal = self.get_balance()
        if not bal["ok"]:
            return bal
        btc = bal["assets"].get("BTC", {"avail": 0, "total": 0})
        return {"ok": True, "btc_avail": btc["avail"], "btc_total": btc["total"]}

    # ── 下单 ──────────────────────────────────────────────────────

    def market_buy(self, inst_id: str, usdt_amount: float,
                   tag: str = "ab_experiment") -> Dict:
        """市价买入，指定 USDT 金额"""
        body = {
            "instId": inst_id,
            "tdMode": "cash",
            "side": "buy",
            "ordType": "market",
            "tgtCcy": "quote_ccy",   # 以 USDT 计量
            "sz": str(round(usdt_amount, 2)),
            "tag": tag,
        }
        r = self._post("/api/v5/trade/order", body)
        return {"ok": r.get("code") == "0", "raw": r,
                "ord_id": r["data"][0]["ordId"] if r.get("code") == "0" else None}

    def market_sell(self, inst_id: str, btc_amount: float,
                    tag: str = "ab_experiment") -> Dict:
        """市价卖出，指定 BTC 数量"""
        body = {
            "instId": inst_id,
            "tdMode": "cash",
            "side": "sell",
            "ordType": "market",
            "sz": str(round(btc_amount, 8)),
            "tag": tag,
        }
        r = self._post("/api/v5/trade/order", body)
        return {"ok": r.get("code") == "0", "raw": r,
                "ord_id": r["data"][0]["ordId"] if r.get("code") == "0" else None}

    def limit_buy(self, inst_id: str, usdt_amount: float, price: float,
                  tag: str = "ab_experiment") -> Dict:
        btc_sz = round(usdt_amount / price, 8)
        body = {
            "instId": inst_id,
            "tdMode": "cash",
            "side": "buy",
            "ordType": "limit",
            "px": str(price),
            "sz": str(btc_sz),
            "tag": tag,
        }
        r = self._post("/api/v5/trade/order", body)
        return {"ok": r.get("code") == "0", "raw": r,
                "ord_id": r["data"][0]["ordId"] if r.get("code") == "0" else None}

    def get_order(self, inst_id: str, ord_id: str) -> Dict:
        r = self._get("/api/v5/trade/order", {"instId": inst_id, "ordId": ord_id})
        if r.get("code") != "0":
            return {"ok": False, "error": r}
        d = r["data"][0]
        return {
            "ok": True, "ord_id": ord_id,
            "state": d["state"],       # live / filled / canceled
            "filled_sz": float(d.get("fillSz", 0)),
            "avg_px": float(d.get("avgPx", 0) or 0),
        }

    def cancel_order(self, inst_id: str, ord_id: str) -> Dict:
        r = self._post("/api/v5/trade/cancel-order",
                       {"instId": inst_id, "ordId": ord_id})
        return {"ok": r.get("code") == "0", "raw": r}


if __name__ == "__main__":
    import sys
    agent_id = sys.argv[1] if len(sys.argv) > 1 else "a"
    client = OKXSpotClient(agent_id)
    bal = client.get_balance()
    ticker = client.get_ticker()
    print(f"[Agent {agent_id.upper()}] 余额: {json.dumps(bal, ensure_ascii=False, indent=2)}")
    print(f"[Agent {agent_id.upper()}] BTC价格: {ticker.get('last')}")
