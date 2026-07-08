#!/usr/bin/env python3
"""
OKX 模拟交易客户端 - 易经推理模型训练用
基于 OKX 模拟盘 API，支持模拟下单、持仓跟踪、盈亏统计

安全设计：
- 默认 dry_run=True，不会真正下单
- 模拟盘使用独立 API Key
- 所有下单操作记录审计日志
"""
import os
import json
import time
import hmac
import math
import base64
import hashlib
import requests
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone
from pathlib import Path


CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "okx_sim"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

AUDIT_LOG = CONFIG_DIR / "sim_trades_audit.jsonl"

DEFAULT_CONFIG = {
    "api_key": "",
    "secret_key": "",
    "passphrase": "",
    "simulated": True,
    "dry_run": True,
    "base_url": "https://www.okx.com",
    "default_inst_id": "BTC-USDT-SWAP",
    "default_usdt_amount": 100,
}

_CUSTOM_HOSTS = {
    "www.okx.com": "47.52.118.149",
    "api.okx.com": "47.52.118.149",
}


def _load_config() -> Dict:
    config_path = CONFIG_DIR / "config.json"
    if config_path.exists():
        with open(config_path) as f:
            cfg = json.load(f)
        return {**DEFAULT_CONFIG, **cfg}
    return DEFAULT_CONFIG.copy()


def _save_config(cfg: Dict) -> None:
    config_path = CONFIG_DIR / "config.json"
    with open(config_path, "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.chmod(config_path, 0o600)


def configure(api_key: str = None, secret_key: str = None,
              passphrase: str = None, simulated: bool = None,
              dry_run: bool = None) -> Dict:
    """配置 OKX 模拟交易参数"""
    cfg = _load_config()
    if api_key is not None:
        cfg["api_key"] = api_key
    if secret_key is not None:
        cfg["secret_key"] = secret_key
    if passphrase is not None:
        cfg["passphrase"] = passphrase
    if simulated is not None:
        cfg["simulated"] = simulated
    if dry_run is not None:
        cfg["dry_run"] = dry_run
    _save_config(cfg)
    safe_cfg = {k: v for k, v in cfg.items() if k not in ("secret_key",)}
    safe_cfg["secret_key"] = "***" if cfg["secret_key"] else ""
    return safe_cfg


class _CustomDNSAdapter(requests.adapters.HTTPAdapter):
    def resolve_host(self, hostname):
        return _CUSTOM_HOSTS.get(hostname, hostname)

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        import urllib3
        from urllib3.poolmanager import PoolManager

        class CustomPoolManager(PoolManager):
            def _new_pool(self, scheme, host, port):
                host = _CUSTOM_HOSTS.get(host, host)
                return super()._new_pool(scheme, host, port)

        self.poolmanager = CustomPoolManager(
            num_pools=connections, maxsize=maxsize, block=block, **pool_kwargs
        )


class OKXSimulatedClient:
    """OKX 模拟交易客户端"""

    def __init__(self, config: Dict = None):
        self.cfg = config or _load_config()
        self.api_key = self.cfg["api_key"]
        self.secret_key = self.cfg["secret_key"]
        self.passphrase = self.cfg["passphrase"]
        self.base_url = self.cfg["base_url"]
        self.simulated = self.cfg["simulated"]
        self.dry_run = self.cfg["dry_run"]
        self.session = requests.Session()
        self.session.mount("https://", _CustomDNSAdapter())

        self._proxy_setup()

    def _proxy_setup(self):
        https_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        http_proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
        if https_proxy or http_proxy:
            proxies = {}
            if https_proxy:
                proxies["https"] = https_proxy
            if http_proxy:
                proxies["http"] = http_proxy
            self.session.proxies.update(proxies)

    def _has_credentials(self) -> bool:
        return bool(self.api_key and self.secret_key and self.passphrase)

    def _headers(self, method: str, path: str, body: str = "") -> Dict:
        ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')
        msg = ts + method + path + body
        sign = base64.b64encode(
            hmac.new(self.secret_key.encode(), msg.encode(), hashlib.sha256).digest()
        ).decode()
        headers = {
            "OK-ACCESS-KEY": self.api_key,
            "OK-ACCESS-SIGN": sign,
            "OK-ACCESS-TIMESTAMP": ts,
            "OK-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
        }
        if self.simulated:
            headers["x-simulated-trading"] = "1"
        return headers

    def _get(self, path: str, params: Optional[Dict] = None,
             auth: bool = True) -> Dict:
        sign_path = path
        if params:
            qs = "&".join(f"{k}={v}" for k, v in params.items())
            sign_path = f"{path}?{qs}"
        headers = self._headers("GET", sign_path) if auth else {}
        try:
            resp = self.session.get(
                self.base_url + path, params=params,
                headers=headers, timeout=15
            )
            return resp.json()
        except Exception as e:
            return {"code": "-1", "msg": str(e), "data": []}

    def _post(self, path: str, body: Dict, auth: bool = True) -> Dict:
        body_str = json.dumps(body)
        headers = self._headers("POST", path, body_str) if auth else {}
        try:
            resp = self.session.post(
                self.base_url + path, data=body_str,
                headers=headers, timeout=15
            )
            return resp.json()
        except Exception as e:
            return {"code": "-1", "msg": str(e), "data": []}

    def _audit_log(self, action: str, payload: Dict, result: Dict):
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "dry_run": self.dry_run,
            "simulated": self.simulated,
            "payload": payload,
            "result_code": result.get("code"),
            "result_msg": result.get("msg"),
            "result_data": result.get("data", []),
        }
        try:
            with open(AUDIT_LOG, "a") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass

    # ── 公共行情 ──────────────────────────────────────────────

    def get_ticker(self, inst_id: str = None) -> Dict:
        inst_id = inst_id or self.cfg["default_inst_id"]
        r = self._get("/api/v5/market/ticker", {"instId": inst_id}, auth=False)
        if r.get("code") != "0":
            return {"ok": False, "error": r.get("msg", "unknown")}
        d = r["data"][0]
        return {
            "ok": True,
            "inst_id": inst_id,
            "last": float(d["last"]),
            "bid": float(d["bidPx"]),
            "ask": float(d["askPx"]),
            "vol24h": float(d["vol24h"]),
            "ts": d.get("ts"),
        }

    def get_instrument(self, inst_id: str = None) -> Dict:
        inst_id = inst_id or self.cfg["default_inst_id"]
        r = self._get("/api/v5/market/instruments", {"instId": inst_id}, auth=False)
        if r.get("code") != "0":
            return {"ok": False, "error": r.get("msg", "unknown")}
        d = r["data"][0]
        return {
            "ok": True,
            "inst_id": inst_id,
            "ct_val": float(d.get("ctVal", 1)),
            "ct_mult": float(d.get("ctMult", 1)),
            "ct_type": d.get("ctType"),
            "tick_sz": float(d.get("tickSz", 0.0001)),
            "lot_sz": float(d.get("lotSz", 1)),
        }

    def _usdt_to_sz(self, inst_id: str, usdt_amount: float) -> float:
        ticker = self.get_ticker(inst_id)
        if not ticker["ok"]:
            return usdt_amount
        instrument = self.get_instrument(inst_id)
        if not instrument["ok"]:
            return usdt_amount
        last_price = ticker["last"]
        ct_val = instrument["ct_val"]
        ct_mult = instrument["ct_mult"]
        lot_sz = instrument["lot_sz"]
        contract_value = last_price * ct_val * ct_mult
        if contract_value <= 0:
            return usdt_amount
        raw_sz = usdt_amount / contract_value
        # 按 lot_sz 取整（向下取整，保证可成交）
        if lot_sz > 0:
            aligned_sz = math.floor(raw_sz / lot_sz) * lot_sz
        else:
            aligned_sz = raw_sz
        # 保留有效精度
        if lot_sz >= 1:
            return float(int(aligned_sz))
        elif lot_sz >= 0.1:
            return round(aligned_sz, 1)
        elif lot_sz >= 0.01:
            return round(aligned_sz, 2)
        elif lot_sz >= 0.001:
            return round(aligned_sz, 3)
        else:
            return round(aligned_sz, 4)

    def get_kline(self, inst_id: str = None, bar: str = "1H",
                  limit: int = 100) -> Dict:
        inst_id = inst_id or self.cfg["default_inst_id"]
        r = self._get(
            "/api/v5/market/candles",
            {"instId": inst_id, "bar": bar, "limit": str(limit)},
            auth=False
        )
        if r.get("code") != "0":
            return {"ok": False, "error": r.get("msg", "unknown")}
        candles = []
        for d in r["data"]:
            candles.append({
                "ts": int(d[0]),
                "o": float(d[1]),
                "h": float(d[2]),
                "l": float(d[3]),
                "c": float(d[4]),
                "vol": float(d[5]),
            })
        return {"ok": True, "inst_id": inst_id, "bar": bar, "candles": candles}

    # ── 账户信息 ──────────────────────────────────────────────

    def get_balance(self) -> Dict:
        if not self._has_credentials():
            return {"ok": False, "error": "missing api credentials"}
        r = self._get("/api/v5/account/balance")
        if r.get("code") != "0":
            return {"ok": False, "error": r.get("msg", "unknown"), "raw": r}
        acct = r["data"][0]
        result = {
            "ok": True,
            "total_eq": float(acct.get("totalEq") or 0),
            "iso_eq": float(acct.get("isoEq") or 0),
            "adj_eq": float(acct.get("adjEq") or 0),
            "assets": {},
        }
        for d in acct.get("details", []):
            result["assets"][d["ccy"]] = {
                "avail": float(d.get("availBal", 0)),
                "frozen": float(d.get("frozenBal", 0)),
                "eq": float(d.get("eq", 0)),
                "usd_eq": float(d.get("eqUsd", 0)),
            }
        return result

    def get_positions(self, inst_id: str = None) -> Dict:
        if not self._has_credentials():
            return {"ok": False, "error": "missing api credentials"}
        inst_id = inst_id or self.cfg["default_inst_id"]
        r = self._get("/api/v5/account/positions", {"instId": inst_id})
        if r.get("code") != "0":
            return {"ok": False, "error": r.get("msg", "unknown"), "raw": r}
        positions = []
        for d in r.get("data", []):
            pos = {
                "inst_id": d["instId"],
                "pos_side": d.get("posSide", "net"),
                "side": d.get("side"),
                "pos": float(d.get("pos", 0)),
                "avg_px": float(d.get("avgPx", 0) or 0),
                "upl": float(d.get("upl", 0) or 0),
                "upl_ratio": float(d.get("uplRatio", 0) or 0),
                "lever": d.get("lever"),
                "liq_px": float(d.get("liqPx", 0) or 0),
                "mark_px": float(d.get("markPx", 0) or 0),
            }
            if pos["pos"] != 0:
                positions.append(pos)
        return {"ok": True, "positions": positions, "count": len(positions)}

    def transfer(self, ccy: str, amt: float, from_acct: str = "6", to_acct: str = "18") -> Dict:
        if not self._has_credentials():
            return {"ok": False, "error": "missing api credentials"}
        if self.cfg["dry_run"]:
            return {"ok": True, "dry_run": True, "transfer": {"ccy": ccy, "amt": amt, "from": from_acct, "to": to_acct}}
        body = {
            "ccy": ccy,
            "amt": str(amt),
            "from": from_acct,
            "to": to_acct,
        }
        r = self._post("/api/v5/asset/transfer", body)
        if r.get("code") == "0":
            self._audit_log("transfer", body, r)
            return {"ok": True, "transfer": r.get("data", [{}])[0]}
        self._audit_log("transfer_fail", body, r)
        return {"ok": False, "error": r.get("msg", "unknown"), "code": r.get("code")}

    # ── 交易下单 ──────────────────────────────────────────────

    def place_order(self, inst_id: str, side: str, ord_type: str = "market",
                    sz: float = None, px: float = None,
                    td_mode: str = "cross", pos_side: str = "net",
                    tag: str = "yijing_sim",
                    reason: str = "") -> Dict:
        """
        下单（默认 dry_run 模式，仅记录不下单）

        Args:
            inst_id: 合约/现货 ID，如 BTC-USDT-SWAP
            side: buy / sell
            ord_type: market / limit
            sz: 数量（USDT 金额或币数量）
            px: 限价（限价单必填）
            td_mode: cross / isolated / cash
            pos_side: net / long / short
            tag: 订单标签
            reason: 下单原因（审计用）
        """
        if not self._has_credentials():
            return {"ok": False, "error": "missing api credentials",
                    "dry_run_result": None}

        body = {
            "instId": inst_id,
            "tdMode": td_mode,
            "side": side,
            "ordType": ord_type,
            "posSide": pos_side,
            "tag": "yijingsim",
        }

        if ord_type == "market":
            body["sz"] = str(sz)
        else:
            body["px"] = str(px)
            body["sz"] = str(sz)

        if self.dry_run:
            ticker = self.get_ticker(inst_id)
            estimated_price = ticker.get("last", 0) if ticker["ok"] else 0
            dry_result = {
                "ok": True,
                "dry_run": True,
                "simulated": self.simulated,
                "inst_id": inst_id,
                "side": side,
                "ord_type": ord_type,
                "sz": sz,
                "px": px,
                "estimated_price": estimated_price,
                "reason": reason,
                "ord_id": f"dry_run_{int(time.time()*1000)}",
            }
            self._audit_log("place_order_dry", body, {"code": "0", "msg": "dry_run", "data": [dry_result]})
            return dry_result

        r = self._post("/api/v5/trade/order", body)
        self._audit_log("place_order", body, r)

        ok = r.get("code") == "0"
        return {
            "ok": ok,
            "dry_run": False,
            "simulated": self.simulated,
            "ord_id": r["data"][0]["ordId"] if ok and r.get("data") else None,
            "raw": r,
        }

    def market_open_long(self, inst_id: str = None, usdt_amount: float = None,
                         reason: str = "") -> Dict:
        inst_id = inst_id or self.cfg["default_inst_id"]
        usdt_amount = usdt_amount or self.cfg["default_usdt_amount"]
        sz = self._usdt_to_sz(inst_id, usdt_amount)
        return self.place_order(
            inst_id=inst_id, side="buy", ord_type="market",
            sz=sz, pos_side="long", td_mode="cross",
            reason=reason or "bcrm_reasoning_open_long"
        )

    def market_open_short(self, inst_id: str = None, usdt_amount: float = None,
                          reason: str = "") -> Dict:
        inst_id = inst_id or self.cfg["default_inst_id"]
        usdt_amount = usdt_amount or self.cfg["default_usdt_amount"]
        sz = self._usdt_to_sz(inst_id, usdt_amount)
        return self.place_order(
            inst_id=inst_id, side="sell", ord_type="market",
            sz=sz, pos_side="short", td_mode="cross",
            reason=reason or "bcrm_reasoning_open_short"
        )

    def market_close_long(self, inst_id: str = None, reason: str = "") -> Dict:
        """市价平多"""
        inst_id = inst_id or self.cfg["default_inst_id"]
        pos = self.get_positions(inst_id)
        if not pos["ok"]:
            return pos
        long_pos = [p for p in pos["positions"]
                    if p["pos_side"] == "long" and p["pos"] > 0]
        if not long_pos:
            return {"ok": False, "error": "no long position to close"}
        sz = long_pos[0]["pos"]
        return self.place_order(
            inst_id=inst_id, side="sell", ord_type="market",
            sz=sz, pos_side="long", td_mode="cross",
            reason=reason or "bcrm_reasoning_close_long"
        )

    def market_close_short(self, inst_id: str = None, reason: str = "") -> Dict:
        """市价平空"""
        inst_id = inst_id or self.cfg["default_inst_id"]
        pos = self.get_positions(inst_id)
        if not pos["ok"]:
            return pos
        short_pos = [p for p in pos["positions"]
                     if p["pos_side"] == "short" and p["pos"] > 0]
        if not short_pos:
            return {"ok": False, "error": "no short position to close"}
        sz = short_pos[0]["pos"]
        return self.place_order(
            inst_id=inst_id, side="buy", ord_type="market",
            sz=sz, pos_side="short", td_mode="cross",
            reason=reason or "bcrm_reasoning_close_short"
        )

    # ── 止盈止损单（OKX Algo Order） ──────────────────────────

    def place_stop_loss_take_profit(self, inst_id: str = None,
                                     pos_side: str = "long",
                                     stop_loss_px: float = 0,
                                     take_profit_px: float = 0,
                                     sz: float = None,
                                     reason: str = "") -> Dict:
        """
        设置止盈止损单（OKX algo order: OCO 条件单）

        使用 OKX OCO（One-Cancels-the-Other）类型，
        止损和止盈同时设置，触发一个时自动撤销另一个。

        Args:
            inst_id: 合约 ID
            pos_side: 持仓方向 long / short
            stop_loss_px: 止损价
            take_profit_px: 止盈价
            sz: 数量（None 则用全部持仓）
            reason: 设置原因
        """
        inst_id = inst_id or self.cfg["default_inst_id"]

        if not stop_loss_px and not take_profit_px:
            return {"ok": False, "error": "需指定止损价或止盈价"}

        # 获取持仓数量
        if sz is None:
            pos_data = self.get_positions(inst_id)
            if not pos_data["ok"]:
                return pos_data
            matched = [p for p in pos_data["positions"]
                       if p["pos_side"] == pos_side and p["pos"] > 0]
            if not matched:
                return {"ok": False, "error": f"无 {pos_side} 持仓可设置止盈止损"}
            sz = matched[0]["pos"]

        # OCO 单：止损和止盈必须同时设置，如果只有一个，用 conditional 单
        if stop_loss_px and take_profit_px:
            # OCO 类型
            side = "sell" if pos_side == "long" else "buy"
            body = {
                "instId": inst_id,
                "tdMode": "cross",
                "side": side,
                "ordType": "oco",
                "sz": str(sz),
                "posSide": pos_side,
                "slTriggerPx": str(stop_loss_px),
                "slOrdPx": "-1",   # 市价触发
                "tpTriggerPx": str(take_profit_px),
                "tpOrdPx": "-1",
                "tag": "yijingsltp",
            }
            if self.dry_run:
                result = {"ok": True, "dry_run": True, "type": "oco",
                          "stop_loss_px": stop_loss_px, "take_profit_px": take_profit_px,
                          "sz": sz, "side": side,
                          "algo_id": f"dry_oco_{int(time.time()*1000)}"}
            else:
                r = self._post("/api/v5/trade/order-algo", body)
                result = {"ok": r.get("code") == "0",
                          "dry_run": False, "type": "oco",
                          "stop_loss_px": stop_loss_px,
                          "take_profit_px": take_profit_px,
                          "sz": sz, "side": side,
                          "algo_id": r.get("data", [{}])[0].get("algoId") if r.get("data") else None,
                          "raw": r}
                self._audit_log("oco_sltp_order", body, r)
            return {"orders": [result], "stop_loss": result,
                    "take_profit": result, "ok": result.get("ok"),
                    "reason": reason or "bcrm_risk_management"}

        # 仅止损或仅止盈（conditional 单）
        if stop_loss_px:
            sl_side = "sell" if pos_side == "long" else "buy"
            body = {
                "instId": inst_id,
                "tdMode": "cross",
                "side": sl_side,
                "ordType": "conditional",
                "sz": str(sz),
                "posSide": pos_side,
                "triggerPx": str(stop_loss_px),
                "orderPx": "-1",
                "triggerPxType": "last",
                "tag": "yijingsl",
            }
            if self.dry_run:
                sl_result = {"ok": True, "dry_run": True, "type": "stop_loss",
                             "trigger_px": stop_loss_px, "sz": sz, "side": sl_side,
                             "algo_id": f"dry_sl_{int(time.time()*1000)}"}
            else:
                r = self._post("/api/v5/trade/order-algo", body)
                sl_result = {"ok": r.get("code") == "0",
                             "dry_run": False, "type": "stop_loss",
                             "trigger_px": stop_loss_px, "sz": sz, "side": sl_side,
                             "algo_id": r.get("data", [{}])[0].get("algoId") if r.get("data") else None,
                             "raw": r}
                self._audit_log("stop_loss_order", body, r)
            return {"orders": [sl_result], "stop_loss": sl_result,
                    "ok": sl_result.get("ok"), "reason": reason or "bcrm_risk_management"}

        # 仅止盈
        tp_side = "sell" if pos_side == "long" else "buy"
        body = {
            "instId": inst_id,
            "tdMode": "cross",
            "side": tp_side,
            "ordType": "conditional",
            "sz": str(sz),
            "posSide": pos_side,
            "triggerPx": str(take_profit_px),
            "orderPx": "-1",
            "triggerPxType": "last",
            "tag": "yijingtp",
        }
        if self.dry_run:
            tp_result = {"ok": True, "dry_run": True, "type": "take_profit",
                         "trigger_px": take_profit_px, "sz": sz, "side": tp_side,
                         "algo_id": f"dry_tp_{int(time.time()*1000)}"}
        else:
            r = self._post("/api/v5/trade/order-algo", body)
            tp_result = {"ok": r.get("code") == "0",
                         "dry_run": False, "type": "take_profit",
                         "trigger_px": take_profit_px, "sz": sz, "side": tp_side,
                         "algo_id": r.get("data", [{}])[0].get("algoId") if r.get("data") else None,
                         "raw": r}
            self._audit_log("take_profit_order", body, r)
        return {"orders": [tp_result], "take_profit": tp_result,
                "ok": tp_result.get("ok"), "reason": reason or "bcrm_risk_management"}

    def reduce_position(self, inst_id: str = None, pos_side: str = "long",
                        reduce_ratio: float = 0.5, reason: str = "") -> Dict:
        """
        减仓操作（按比例减少持仓）

        Args:
            inst_id: 合约 ID
            pos_side: 持仓方向 long / short
            reduce_ratio: 减仓比例 0~1（0.5 = 减仓 50%）
            reason: 减仓原因
        """
        inst_id = inst_id or self.cfg["default_inst_id"]
        reduce_ratio = max(0.01, min(reduce_ratio, 1.0))

        pos_data = self.get_positions(inst_id)
        if not pos_data["ok"]:
            return pos_data

        matched = [p for p in pos_data["positions"]
                   if p["pos_side"] == pos_side and p["pos"] > 0]
        if not matched:
            return {"ok": False, "error": f"无 {pos_side} 持仓可减仓"}

        full_sz = matched[0]["pos"]
        reduce_sz = int(full_sz * reduce_ratio)
        if reduce_sz < 1:
            return {"ok": False, "error": f"减仓数量不足（持仓 {full_sz}，减仓比例 {reduce_ratio}）"}

        side = "sell" if pos_side == "long" else "buy"
        result = self.place_order(
            inst_id=inst_id, side=side, ord_type="market",
            sz=reduce_sz, pos_side=pos_side, td_mode="cross",
            reason=reason or f"bcrm_reduce_{int(reduce_ratio*100)}pct"
        )
        result["reduce_ratio"] = reduce_ratio
        result["original_pos"] = full_sz
        result["reduce_sz"] = reduce_sz
        result["remaining_pos"] = full_sz - reduce_sz
        return result

    def cancel_algo_orders(self, inst_id: str = None) -> Dict:
        """撤销所有未触发的止盈止损单（含 conditional 和 oco）"""
        inst_id = inst_id or self.cfg["default_inst_id"]
        if not self._has_credentials():
            return {"ok": False, "error": "missing api credentials"}

        algo_ids = []
        for ord_type in ("conditional", "oco"):
            r = self._get("/api/v5/trade/orders-algo-pending",
                           {"instId": inst_id, "ordType": ord_type})
            if r.get("code") != "0":
                continue
            algo_ids.extend(d["algoId"] for d in r.get("data", []))

        if not algo_ids:
            return {"ok": True, "cancelled": 0, "msg": "无未触发的 algo orders"}

        cancelled = 0
        for aid in algo_ids:
            body = {"algoId": aid, "instId": inst_id}
            cr = self._post("/api/v5/trade/cancel-algos", [body])
            if cr.get("code") == "0":
                cancelled += 1
            self._audit_log("cancel_algo", body, cr)

        return {"ok": True, "cancelled": cancelled, "total": len(algo_ids)}

    def get_algo_orders(self, inst_id: str = None) -> Dict:
        """查询未触发的止盈止损单（含 conditional 和 oco 类型）"""
        inst_id = inst_id or self.cfg["default_inst_id"]
        if not self._has_credentials():
            return {"ok": False, "error": "missing api credentials"}
        orders = []
        for ord_type in ("conditional", "oco"):
            r = self._get("/api/v5/trade/orders-algo-pending",
                           {"instId": inst_id, "ordType": ord_type})
            if r.get("code") != "0":
                continue
            for d in r.get("data", []):
                orders.append({
                    "algo_id": d.get("algoId"),
                    "ord_type": ord_type,
                    "side": d.get("side"),
                    "pos_side": d.get("posSide"),
                    "sz": float(d.get("sz", 0) or 0),
                    "trigger_px": float(d.get("triggerPx", 0) or 0),
                    "sl_trigger_px": float(d.get("slTriggerPx", 0) or 0),
                    "tp_trigger_px": float(d.get("tpTriggerPx", 0) or 0),
                    "order_px": d.get("orderPx"),
                    "state": d.get("state"),
                    "actual_px": float(d.get("actualPx", 0) or 0),
                    "tag": d.get("tag", ""),
                })
        return {"ok": True, "orders": orders, "count": len(orders)}

    def get_order(self, inst_id: str, ord_id: str) -> Dict:
        if not self._has_credentials():
            return {"ok": False, "error": "missing api credentials"}
        r = self._get("/api/v5/trade/order",
                      {"instId": inst_id, "ordId": ord_id})
        if r.get("code") != "0":
            return {"ok": False, "error": r.get("msg", "unknown")}
        d = r["data"][0]
        return {
            "ok": True,
            "ord_id": ord_id,
            "state": d["state"],
            "side": d.get("side"),
            "pos_side": d.get("posSide"),
            "filled_sz": float(d.get("fillSz", 0) or 0),
            "avg_px": float(d.get("avgPx", 0) or 0),
            "fee": float(d.get("fee", 0) or 0),
            "pnl": float(d.get("pnl", 0) or 0),
        }

    # ── 模拟交易训练闭环 ────────────────────────────────────

    def simulate_trade_from_bcrm(self, bcrm_result: Dict,
                                 inst_id: str = None,
                                 usdt_amount: float = None) -> Dict:
        """
        根据 BCRM 推理结果执行模拟交易（含止盈止损/减仓风控）

        BCRM 输出字段:
        - hexagram: 卦象
        - two_yi_state: 两仪状态 (老阳/老阴/少阳/少阴)
        - direction: 方向 (bullish/bearish/neutral)
        - confidence: 置信度
        - action: 建议操作 (open_long/open_short/hold/close/reduce)
        - stop_loss_px: 止损价
        - take_profit_px: 止盈价
        - reduce_ratio: 减仓比例
        - strategy_branches: 策略分支列表
        """
        inst_id = inst_id or self.cfg["default_inst_id"]
        usdt_amount = usdt_amount or self.cfg["default_usdt_amount"]

        action = bcrm_result.get("action", "hold")
        reason = f"卦象:{bcrm_result.get('hexagram','?')} 两仪:{bcrm_result.get('two_yi_state','?')}"
        stop_loss_px = bcrm_result.get("stop_loss_px", 0)
        take_profit_px = bcrm_result.get("take_profit_px", 0)
        reduce_ratio = bcrm_result.get("reduce_ratio", 0)

        result = {
            "action": action, "reason": reason, "executed": False,
            "risk_management": None,
        }

        if action == "open_long":
            r = self.market_open_long(inst_id, usdt_amount, reason=reason)
            result["order_result"] = r
            result["executed"] = r.get("ok", False)
            # 开仓后设置止盈止损
            if r.get("ok") and (stop_loss_px or take_profit_px):
                sl_tp = self.place_stop_loss_take_profit(
                    inst_id=inst_id, pos_side="long",
                    stop_loss_px=stop_loss_px, take_profit_px=take_profit_px,
                    reason=reason)
                result["risk_management"] = sl_tp

        elif action == "open_short":
            r = self.market_open_short(inst_id, usdt_amount, reason=reason)
            result["order_result"] = r
            result["executed"] = r.get("ok", False)
            if r.get("ok") and (stop_loss_px or take_profit_px):
                sl_tp = self.place_stop_loss_take_profit(
                    inst_id=inst_id, pos_side="short",
                    stop_loss_px=stop_loss_px, take_profit_px=take_profit_px,
                    reason=reason)
                result["risk_management"] = sl_tp

        elif action == "close_long":
            r = self.market_close_long(inst_id, reason=reason)
            result["order_result"] = r
            result["executed"] = r.get("ok", False)

        elif action == "close_short":
            r = self.market_close_short(inst_id, reason=reason)
            result["order_result"] = r
            result["executed"] = r.get("ok", False)

        elif action == "reduce_long":
            ratio = reduce_ratio or 0.5
            r = self.reduce_position(inst_id=inst_id, pos_side="long",
                                      reduce_ratio=ratio, reason=reason)
            result["order_result"] = r
            result["executed"] = r.get("ok", False)
            # 减仓后更新止盈止损（撤旧设新）
            if r.get("ok") and (stop_loss_px or take_profit_px):
                self.cancel_algo_orders(inst_id)
                remaining = r.get("remaining_pos", 0)
                if remaining > 0:
                    sl_tp = self.place_stop_loss_take_profit(
                        inst_id=inst_id, pos_side="long",
                        stop_loss_px=stop_loss_px, take_profit_px=take_profit_px,
                        sz=remaining, reason=reason)
                    result["risk_management"] = sl_tp

        elif action == "reduce_short":
            ratio = reduce_ratio or 0.5
            r = self.reduce_position(inst_id=inst_id, pos_side="short",
                                      reduce_ratio=ratio, reason=reason)
            result["order_result"] = r
            result["executed"] = r.get("ok", False)
            if r.get("ok") and (stop_loss_px or take_profit_px):
                self.cancel_algo_orders(inst_id)
                remaining = r.get("remaining_pos", 0)
                if remaining > 0:
                    sl_tp = self.place_stop_loss_take_profit(
                        inst_id=inst_id, pos_side="short",
                        stop_loss_px=stop_loss_px, take_profit_px=take_profit_px,
                        sz=remaining, reason=reason)
                    result["risk_management"] = sl_tp

        else:
            result["order_result"] = {"ok": True, "note": "no action (hold)"}
            result["executed"] = True

        return result

    def get_audit_logs(self, limit: int = 50) -> List[Dict]:
        """读取审计日志"""
        if not AUDIT_LOG.exists():
            return []
        logs = []
        with open(AUDIT_LOG) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        logs.append(json.loads(line))
                    except Exception:
                        pass
        return logs[-limit:]

    def get_performance_summary(self) -> Dict:
        """模拟交易绩效汇总"""
        logs = self.get_audit_logs(limit=1000)
        trade_logs = [l for l in logs
                       if l.get("action", "").startswith("place_order")]

        total_orders = len(trade_logs)
        dry_run_count = sum(1 for l in trade_logs if l.get("dry_run"))
        sim_count = sum(1 for l in trade_logs if l.get("simulated"))

        return {
            "total_orders": total_orders,
            "dry_run_orders": dry_run_count,
            "simulated_orders": sim_count - dry_run_count,
            "audit_log_path": str(AUDIT_LOG),
            "latest_orders": trade_logs[-5:],
        }


def cli():
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m scripts.memory_l4.okx_simulated <command> [args]")
        print("Commands:")
        print("  config --key <api_key> --secret <secret> --pass <passphrase>")
        print("  status [--live]")
        print("  ticker [inst_id]")
        print("  balance")
        print("  positions [inst_id]")
        print("  test-order <side> <usdt_amount>")
        print("  set-sl-tp --side <long|short> --sl <price> --tp <price>")
        print("  reduce --side <long|short> --ratio <0~1>")
        print("  algo-orders")
        print("  cancel-algo")
        print("  performance")
        print("  set-dry-run <true|false>")
        return

    cmd = sys.argv[1]

    if cmd == "config":
        kwargs = {}
        i = 2
        while i < len(sys.argv):
            if sys.argv[i] == "--key" and i + 1 < len(sys.argv):
                kwargs["api_key"] = sys.argv[i + 1]; i += 2
            elif sys.argv[i] == "--secret" and i + 1 < len(sys.argv):
                kwargs["secret_key"] = sys.argv[i + 1]; i += 2
            elif sys.argv[i] == "--pass" and i + 1 < len(sys.argv):
                kwargs["passphrase"] = sys.argv[i + 1]; i += 2
            else:
                i += 1
        result = configure(**kwargs)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    if cmd == "set-dry-run":
        val = sys.argv[2].lower() == "true" if len(sys.argv) > 2 else True
        result = configure(dry_run=val)
        print(f"dry_run 已设置为: {val}")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    client = OKXSimulatedClient()

    if cmd == "status":
        live = "--live" in sys.argv
        cfg = _load_config()
        print(f"Simulated mode: {cfg['simulated']}")
        print(f"Dry run: {cfg['dry_run']}")
        print(f"API Key: {'configured' if cfg['api_key'] else 'missing'}")
        print(f"Secret: {'configured' if cfg['secret_key'] else 'missing'}")
        print(f"Passphrase: {'configured' if cfg['passphrase'] else 'missing'}")
        if live and client._has_credentials():
            bal = client.get_balance()
            pos = client.get_positions()
            print(f"\n账户余额: {bal.get('total_eq', 'N/A')} USDT")
            print(f"持仓数: {pos.get('count', 0)}")
        return

    if cmd == "ticker":
        inst_id = sys.argv[2] if len(sys.argv) > 2 else None
        r = client.get_ticker(inst_id)
        print(json.dumps(r, indent=2, ensure_ascii=False))
        return

    if cmd == "balance":
        r = client.get_balance()
        print(json.dumps(r, indent=2, ensure_ascii=False))
        return

    if cmd == "positions":
        inst_id = sys.argv[2] if len(sys.argv) > 2 else None
        r = client.get_positions(inst_id)
        print(json.dumps(r, indent=2, ensure_ascii=False))
        return

    if cmd == "test-order":
        side = sys.argv[2] if len(sys.argv) > 2 else "buy"
        amount = float(sys.argv[3]) if len(sys.argv) > 3 else 10
        if side == "buy":
            r = client.market_open_long(usdt_amount=amount)
        else:
            r = client.market_open_short(usdt_amount=amount)
        print(json.dumps(r, indent=2, ensure_ascii=False))
        return

    if cmd == "performance":
        r = client.get_performance_summary()
        print(json.dumps(r, indent=2, ensure_ascii=False))
        return

    if cmd == "set-sl-tp":
        # set-sl-tp --side long --sl 60000 --tp 70000
        pos_side = "long"
        sl_px = 0
        tp_px = 0
        i = 2
        while i < len(sys.argv):
            if sys.argv[i] == "--side" and i + 1 < len(sys.argv):
                pos_side = sys.argv[i + 1]; i += 2
            elif sys.argv[i] == "--sl" and i + 1 < len(sys.argv):
                sl_px = float(sys.argv[i + 1]); i += 2
            elif sys.argv[i] == "--tp" and i + 1 < len(sys.argv):
                tp_px = float(sys.argv[i + 1]); i += 2
            else:
                i += 1
        r = client.place_stop_loss_take_profit(
            pos_side=pos_side, stop_loss_px=sl_px, take_profit_px=tp_px)
        print(json.dumps(r, indent=2, ensure_ascii=False))
        return

    if cmd == "reduce":
        # reduce --side long --ratio 0.5
        pos_side = "long"
        ratio = 0.5
        i = 2
        while i < len(sys.argv):
            if sys.argv[i] == "--side" and i + 1 < len(sys.argv):
                pos_side = sys.argv[i + 1]; i += 2
            elif sys.argv[i] == "--ratio" and i + 1 < len(sys.argv):
                ratio = float(sys.argv[i + 1]); i += 2
            else:
                i += 1
        r = client.reduce_position(pos_side=pos_side, reduce_ratio=ratio)
        print(json.dumps(r, indent=2, ensure_ascii=False))
        return

    if cmd == "algo-orders":
        r = client.get_algo_orders()
        print(json.dumps(r, indent=2, ensure_ascii=False))
        return

    if cmd == "cancel-algo":
        r = client.cancel_algo_orders()
        print(json.dumps(r, indent=2, ensure_ascii=False))
        return

    print(f"Unknown command: {cmd}")


if __name__ == "__main__":
    cli()
