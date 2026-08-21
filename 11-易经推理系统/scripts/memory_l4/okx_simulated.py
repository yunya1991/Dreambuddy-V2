#!/usr/bin/env python3
"""
OKX 模拟交易客户端 - 易经推理模型训练用
基于 OKX 模拟盘 API，支持模拟下单、持仓跟踪、盈亏统计

安全设计：
- 默认 dry_run=True，不会真正下单
- 模拟盘使用独立 API Key
- 所有下单操作记录审计日志
"""
import base64
import hashlib
import hmac
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import requests

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
    "default_usdt_amount": 100,  # 名义价值，会在 _load_config 中根据保证金和杠杆重新计算
    "default_leverage": 10,
    "td_mode": "isolated",  # 逐仓模式（cross=全仓, isolated=逐仓）
}

_CUSTOM_HOSTS = {
    "www.okx.com": "47.52.118.149",
    "api.okx.com": "47.52.118.149",
}


def _load_config() -> Dict:
    """加载配置，优先级：1. os.environ 环境变量 2. config.json 3. .env 文件 4. 默认值"""
    import os

    cfg = DEFAULT_CONFIG.copy()

    # 1. 优先从环境变量读取（支持外部传入配置）
    if os.environ.get("OKX_API_KEY"):
        cfg["api_key"] = os.environ["OKX_API_KEY"]
    if os.environ.get("OKX_SECRET_KEY"):
        cfg["secret_key"] = os.environ["OKX_SECRET_KEY"]
    if os.environ.get("OKX_PASSPHRASE"):
        cfg["passphrase"] = os.environ["OKX_PASSPHRASE"]
    if os.environ.get("OKX_BASE_URL"):
        cfg["base_url"] = os.environ["OKX_BASE_URL"]
    if os.environ.get("OKX_SIMULATED"):
        cfg["simulated"] = os.environ["OKX_SIMULATED"].lower() in ("true", "1", "yes")
    if os.environ.get("OKX_DRY_RUN"):
        cfg["dry_run"] = os.environ["OKX_DRY_RUN"].lower() in ("true", "1", "yes")
    if os.environ.get("OKX_DEFAULT_INST_ID"):
        cfg["default_inst_id"] = os.environ["OKX_DEFAULT_INST_ID"]
    if os.environ.get("DEFAULT_LEVERAGE"):
        cfg["default_leverage"] = float(os.environ["DEFAULT_LEVERAGE"])
    if os.environ.get("OKX_TD_MODE"):
        cfg["td_mode"] = os.environ["OKX_TD_MODE"]  # cross / isolated
    if cfg["api_key"]:
        return cfg

    # 2. 其次读取 config.json（configure() 写入的配置）
    config_path = CONFIG_DIR / "config.json"
    if config_path.exists():
        with open(config_path) as f:
            saved_cfg = json.load(f)
        cfg.update(saved_cfg)
        if cfg["api_key"]:
            return cfg

    # 3. 最后读取 .env 文件（易经推理系统默认配置）
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if env_path.exists():
        env_vars = {}
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    env_vars[key.strip()] = value.strip()

        leverage = cfg.get("default_leverage", 10)
        if "DEFAULT_LEVERAGE" in env_vars:
            leverage = float(env_vars["DEFAULT_LEVERAGE"])
            cfg["default_leverage"] = leverage

        if "DEFAULT_MARGIN_USDT" in env_vars:
            cfg["default_usdt_amount"] = float(env_vars["DEFAULT_MARGIN_USDT"]) * leverage

        if "OKX_API_KEY" in env_vars:
            cfg["api_key"] = env_vars["OKX_API_KEY"]
        if "OKX_SECRET_KEY" in env_vars:
            cfg["secret_key"] = env_vars["OKX_SECRET_KEY"]
        if "OKX_PASSPHRASE" in env_vars:
            cfg["passphrase"] = env_vars["OKX_PASSPHRASE"]
        if "OKX_BASE_URL" in env_vars:
            cfg["base_url"] = env_vars["OKX_BASE_URL"]
        if "OKX_SIMULATED" in env_vars:
            cfg["simulated"] = env_vars["OKX_SIMULATED"].lower() in ("true", "1", "yes")
        if "OKX_DRY_RUN" in env_vars:
            cfg["dry_run"] = env_vars["OKX_DRY_RUN"].lower() in ("true", "1", "yes")
        if "OKX_DEFAULT_INST_ID" in env_vars:
            cfg["default_inst_id"] = env_vars["OKX_DEFAULT_INST_ID"]
        if "OKX_TD_MODE" in env_vars:
            cfg["td_mode"] = env_vars["OKX_TD_MODE"]  # cross / isolated
        if cfg["api_key"]:
            return cfg

    return cfg.copy()


def _save_config(cfg: Dict) -> None:
    config_path = CONFIG_DIR / "config.json"
    with open(config_path, "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.chmod(config_path, 0o600)


def configure(
    api_key: str = None,
    secret_key: str = None,
    passphrase: str = None,
    simulated: bool = None,
    dry_run: bool = None,
) -> Dict:
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
    def init_poolmanager(self, *args, **kwargs):
        from urllib3.poolmanager import PoolManager

        class CustomPoolManager(PoolManager):
            def _new_pool(self, scheme, host, port, request_context=None):
                host = _CUSTOM_HOSTS.get(host, host)
                return super()._new_pool(scheme, host, port, request_context=request_context)

        kwargs.setdefault("num_pools", 10)
        kwargs.setdefault("maxsize", 10)
        self.poolmanager = CustomPoolManager(**kwargs)


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
        # P0 修复：macOS 下 ClashX / Surge 等 GUI 代理软件只对当前 Aqua login session 生效，
        # requests.Session 默认的 proxy 选择依赖 trust_env=True。但为了兼容显式 session.proxies
        # 手动设置的场景，这里保持 trust_env=False，并在 _proxy_setup 中强制
        # 把 os.environ 里的 HTTP(S)_PROXY / ALL_PROXY 写入 self.session.proxies。
        # 为了调试代理问题，初始化后记录 session.proxies 到日志。
        self.session.trust_env = False

        # dry_run 模式下的本地内存订单簿（止盈止损单）
        self._dry_run_algo_orders: Dict[str, list] = {}  # inst_id -> [orders]

        self._proxy_setup()

    def _proxy_setup(self):
        # 1) 优先使用环境变量代理
        https_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        http_proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
        all_proxy = os.environ.get("ALL_PROXY") or os.environ.get("all_proxy")
        proxies = {}
        if https_proxy:
            proxies["https"] = https_proxy
        if http_proxy:
            proxies["http"] = http_proxy
        if all_proxy and not proxies:
            # ALL_PROXY 通常是 socks5 格式，requests >= 2.28 原生支持 socks
            proxies["http"] = all_proxy
            proxies["https"] = all_proxy

        # 2) 环境变量未设置时，尝试本地 Clash 默认端口（fake-ip 模式下必须走代理）
        if not proxies:
            for port in (7890, 7891, 14122, 38324):
                try:
                    import socket as _sock

                    with _sock.create_connection(("127.0.0.1", port), timeout=0.3):
                        proxies = {
                            "http": f"http://127.0.0.1:{port}",
                            "https": f"http://127.0.0.1:{port}",
                        }
                        break
                except Exception:
                    continue

        # 关键：直接赋值而非 update，避免之前的 session.proxies 中残留空值影响。
        # （macOS ClashX GUI 代理只对当前 Aqua login session 生效；
        #  进程若被 launchd 收养为 PPID=1，会因 session 隔离导致直接 TCP 连接失败 -> "Host is down"。
        #  所以启动 polling_trader 时必须保持在 Aqua login session 中，例如：
        #    setopt NO_HUP; (python3 -u -m scripts.memory_l4.polling_trader ... &)
        #  不要用 nohup / setsid / disown 让进程脱离会话。）
        if proxies:
            self.session.proxies = dict(proxies)
        else:
            self.session.proxies = {}

        # P0 诊断：尝试用当前代理发一次 probe 请求，如果失败就打印明确的诊断日志，
        # 便于快速区分"代理没配好"和"OKX 侧故障"。
        try:
            self._probe_proxy_or_log()
        except Exception:
            # 任何探测异常都不能影响初始化
            pass

    def _has_credentials(self) -> bool:
        return bool(self.api_key and self.secret_key and self.passphrase)

    def _probe_proxy_or_log(self):
        """P0 诊断：探测当前代理能否连通 OKX。失败时用 print 打到 stdout（会被重定向到 trading_stdout.log）。
        注意：不能用 self._log / _audit_log，因为这些在 __init__ 早期可能未准备好。
        成功时静默（避免高频实例化导致 stdout I/O 阻塞 GIL 拖慢整个服务）。"""
        import time as _t

        proxies = dict(getattr(self, "session", None) and self.session.proxies or {})
        try:
            t0 = _t.time()
            r = self.session.get(
                self.base_url + "/api/v5/public/time",
                timeout=5,
            )
            dt_ms = int((_t.time() - t0) * 1000)
            try:
                j = r.json()
            except Exception:
                j = {}
            ok = (j.get("code") == "0") or (200 <= r.status_code < 300)
            if not ok:
                print(
                    f"[OKX 代理探测/FAIL] status={r.status_code} code={j.get('code')} "
                    f"t={dt_ms}ms proxies={proxies}",
                    flush=True,
                )
        except Exception as e:
            print(
                f"[OKX 代理探测/FAIL] {type(e).__name__}: {e} | proxies={proxies} | "
                f"建议：请不要用 nohup/setsid/disown 启动进程，否则会因 Aqua session 隔离连不上 GUI 代理。"
                f"正确启动方式：在当前 Aqua login session（正常终端）里执行 `setopt NO_HUP; "
                f"export HTTPS_PROXY=http://127.0.0.1:7890 HTTP_PROXY=http://127.0.0.1:7890; "
                f"(python3 -u -m scripts.memory_l4.polling_trader ... &)`",
                flush=True,
            )

    def _headers(self, method: str, path: str, body: str = "") -> Dict:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
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

    def _get(self, path: str, params: Optional[Dict] = None, auth: bool = True) -> Dict:
        sign_path = path
        if params:
            qs = "&".join(f"{k}={v}" for k, v in params.items())
            sign_path = f"{path}?{qs}"
        headers = self._headers("GET", sign_path) if auth else {}
        try:
            resp = self.session.get(
                self.base_url + path, params=params, headers=headers, timeout=15
            )
            return resp.json()
        except Exception as e:
            return {"code": "-1", "msg": str(e), "data": []}

    def _post(self, path: str, body: Dict, auth: bool = True) -> Dict:
        body_str = json.dumps(body)
        headers = self._headers("POST", path, body_str) if auth else {}
        try:
            resp = self.session.post(
                self.base_url + path, data=body_str, headers=headers, timeout=15
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
        r = self._get(
            "/api/v5/public/instruments", {"instType": "SWAP", "instId": inst_id}, auth=False
        )
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

    _KNOWN_LOT_SIZES = {
        # Layer1
        "BTC-USDT-SWAP": 0.01,
        "ETH-USDT-SWAP": 0.01,
        "SOL-USDT-SWAP": 0.01,
        "BNB-USDT-SWAP": 0.01,
        "XRP-USDT-SWAP": 1,
        "ADA-USDT-SWAP": 1,
        "AVAX-USDT-SWAP": 0.1,
        "NEAR-USDT-SWAP": 0.1,
        "SUI-USDT-SWAP": 1,
        "APT-USDT-SWAP": 0.1,
        "DOT-USDT-SWAP": 0.1,
        "ATOM-USDT-SWAP": 0.1,
        "LTC-USDT-SWAP": 0.01,
        "LINK-USDT-SWAP": 0.1,
        # Layer2/DeFi
        "ARB-USDT-SWAP": 1,
        "OP-USDT-SWAP": 1,
        "UNI-USDT-SWAP": 0.1,
        "AAVE-USDT-SWAP": 0.01,
        # Meme
        "DOGE-USDT-SWAP": 1,
        "PEPE-USDT-SWAP": 1,
        # 美股个股
        "NVDA-USDT-SWAP": 0.01,
        "TSLA-USDT-SWAP": 0.01,
        "MSFT-USDT-SWAP": 0.01,
        "META-USDT-SWAP": 0.01,
        "GOOGL-USDT-SWAP": 0.01,
        "AAPL-USDT-SWAP": 0.01,
        "AMZN-USDT-SWAP": 0.01,
        "COIN-USDT-SWAP": 0.01,
        # TradFi（贵金属）
        "XAU-USDT-SWAP": 1,  # 黄金指数永续 ctVal=0.001
        "XAG-USDT-SWAP": 1,  # 白银 ctVal=0.01
    }

    def _usdt_to_sz(self, inst_id: str, usdt_amount: float) -> float:
        ticker = self.get_ticker(inst_id)
        if not ticker["ok"]:
            return float(int(usdt_amount))

        lot_sz = self._KNOWN_LOT_SIZES.get(inst_id, 0.01)
        ct_val = 1
        ct_mult = 1

        instrument = self.get_instrument(inst_id)
        if instrument["ok"]:
            ct_val = instrument["ct_val"]
            ct_mult = instrument["ct_mult"]
            lot_sz = instrument["lot_sz"]

        last_price = ticker["last"]
        contract_value = last_price * ct_val * ct_mult
        if contract_value <= 0:
            return float(int(usdt_amount))

        raw_sz = usdt_amount / contract_value
        if lot_sz > 0:
            aligned_sz = math.floor(raw_sz / lot_sz) * lot_sz
        else:
            aligned_sz = raw_sz

        # 保证金不足买 1 张合约时返回 0（由调用方决定是否跳过）
        if lot_sz > 0 and aligned_sz < lot_sz:
            return 0.0

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

    def get_kline(self, inst_id: str = None, bar: str = "1H", limit: int = 100) -> Dict:
        inst_id = inst_id or self.cfg["default_inst_id"]
        r = self._get(
            "/api/v5/market/candles",
            {"instId": inst_id, "bar": bar, "limit": str(limit)},
            auth=False,
        )
        if r.get("code") != "0":
            return {"ok": False, "error": r.get("msg", "unknown")}
        candles = []
        for d in r["data"]:
            candles.append(
                {
                    "ts": int(d[0]),
                    "o": float(d[1]),
                    "h": float(d[2]),
                    "l": float(d[3]),
                    "c": float(d[4]),
                    "vol": float(d[5]),
                }
            )
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
        # inst_id 为空时批量查询全部持仓（一次API调用，避免逐个查询因限流导致计数不准）
        params = {"instId": inst_id} if inst_id else {}
        r = self._get("/api/v5/account/positions", params)
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
            return {
                "ok": True,
                "dry_run": True,
                "transfer": {"ccy": ccy, "amt": amt, "from": from_acct, "to": to_acct},
            }
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

    def place_order(
        self,
        inst_id: str,
        side: str,
        ord_type: str = "market",
        sz: float = None,
        px: float = None,
        td_mode: str = None,
        pos_side: str = "net",
        tag: str = "yijing_sim",
        reason: str = "",
    ) -> Dict:
        """
        下单（默认 dry_run 模式，仅记录不下单）

        Args:
            inst_id: 合约/现货 ID，如 BTC-USDT-SWAP
            side: buy / sell
            ord_type: market / limit
            sz: 数量（USDT 金额或币数量）
            px: 限价（限价单必填）
            td_mode: cross / isolated / cash（默认用配置中的 td_mode）
            pos_side: net / long / short
            tag: 订单标签
            reason: 下单原因（审计用）
        """
        if td_mode is None:
            td_mode = self.cfg.get("td_mode", "isolated")
        if not self._has_credentials():
            return {"ok": False, "error": "missing api credentials", "dry_run_result": None}

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
            self._audit_log(
                "place_order_dry", body, {"code": "0", "msg": "dry_run", "data": [dry_result]}
            )
            return dry_result

        r = self._post("/api/v5/trade/order", body)
        self._audit_log("place_order", body, r)

        ok = r.get("code") == "0"
        # 从 OKX 响应中提取错误信息
        error = ""
        if not ok:
            data_list = r.get("data") or []
            if data_list and isinstance(data_list, list):
                error = data_list[0].get("sMsg", "") or data_list[0].get("sCode", "")
            if not error:
                error = r.get("msg", "")
            # P2 修复：失败时追加 session.proxies 诊断信息，
            # 便于快速定位 "Host is down" 是代理未配置还是 OKX 侧故障
            try:
                _proxies = getattr(self, "session", None) and self.session.proxies
            except Exception:
                _proxies = None
            _proxy_str = str(_proxies) if _proxies else "empty"
            if not error:
                error = f"unknown_error; proxies={_proxy_str}"
            else:
                error = f"{error}; proxies={_proxy_str}"
        return {
            "ok": ok,
            "dry_run": False,
            "simulated": self.simulated,
            "ord_id": r["data"][0]["ordId"] if ok and r.get("data") else None,
            "error": error,
            "raw": r,
        }

    def market_open_long(
        self, inst_id: str = None, usdt_amount: float = None, reason: str = ""
    ) -> Dict:
        inst_id = inst_id or self.cfg["default_inst_id"]
        usdt_amount = usdt_amount or self.cfg["default_usdt_amount"]
        sz = self._usdt_to_sz(inst_id, usdt_amount)
        return self.place_order(
            inst_id=inst_id,
            side="buy",
            ord_type="market",
            sz=sz,
            pos_side="long",
            reason=reason or "bcrm_reasoning_open_long",
        )

    def market_open_short(
        self, inst_id: str = None, usdt_amount: float = None, reason: str = ""
    ) -> Dict:
        inst_id = inst_id or self.cfg["default_inst_id"]
        usdt_amount = usdt_amount or self.cfg["default_usdt_amount"]
        sz = self._usdt_to_sz(inst_id, usdt_amount)
        return self.place_order(
            inst_id=inst_id,
            side="sell",
            ord_type="market",
            sz=sz,
            pos_side="short",
            reason=reason or "bcrm_reasoning_open_short",
        )

    def market_close_long(self, inst_id: str = None, reason: str = "") -> Dict:
        """市价平多"""
        inst_id = inst_id or self.cfg["default_inst_id"]
        pos = self.get_positions(inst_id)
        if not pos["ok"]:
            return pos
        long_pos = [p for p in pos["positions"] if p["pos_side"] == "long" and p["pos"] > 0]
        if not long_pos:
            return {"ok": False, "error": "no long position to close"}
        sz = long_pos[0]["pos"]
        return self.place_order(
            inst_id=inst_id,
            side="sell",
            ord_type="market",
            sz=sz,
            pos_side="long",
            reason=reason or "bcrm_reasoning_close_long",
        )

    def market_close_short(self, inst_id: str = None, reason: str = "") -> Dict:
        """市价平空"""
        inst_id = inst_id or self.cfg["default_inst_id"]
        pos = self.get_positions(inst_id)
        if not pos["ok"]:
            return pos
        short_pos = [p for p in pos["positions"] if p["pos_side"] == "short" and p["pos"] > 0]
        if not short_pos:
            return {"ok": False, "error": "no short position to close"}
        sz = short_pos[0]["pos"]
        return self.place_order(
            inst_id=inst_id,
            side="buy",
            ord_type="market",
            sz=sz,
            pos_side="short",
            reason=reason or "bcrm_reasoning_close_short",
        )

    # ── 止盈止损单（OKX Algo Order） ──────────────────────────

    def place_stop_loss_take_profit(
        self,
        inst_id: str = None,
        pos_side: str = "long",
        stop_loss_px: float = 0,
        take_profit_px: float = 0,
        sz: float = None,
        reason: str = "",
    ) -> Dict:
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

        # v3.0修复：按tickSz对齐SL/TP价格，避免OKX Parameter slTriggerPx error
        tick_sz = 0.01  # 默认精度
        try:
            inst_info = self.get_instrument(inst_id)
            if inst_info.get("ok"):
                tick_sz = inst_info.get("tick_sz", 0.01) or 0.01
        except Exception:
            pass

        def _round_to_tick(px: float, tick: float) -> float:
            """将价格对齐到tickSz的整数倍"""
            if tick <= 0 or px <= 0:
                return px
            return round(px / tick) * tick

        if stop_loss_px > 0:
            stop_loss_px = _round_to_tick(stop_loss_px, tick_sz)
        if take_profit_px > 0:
            take_profit_px = _round_to_tick(take_profit_px, tick_sz)

        # ── P0修复：调整一侧止盈止损时，保留另一侧的价格，避免取消原保护 ──
        existing_sl = 0
        existing_tp = 0
        try:
            current_orders = self.get_algo_orders(inst_id)
            if current_orders.get("ok") and current_orders.get("orders"):
                for order in current_orders["orders"]:
                    # 宽松匹配：pending 接口返回的都是未触发订单，优先匹配同方向
                    pos_match = order.get("pos_side") == pos_side or not order.get("pos_side")
                    state_match = order.get("state") in ("live", "ordering", None, "")
                    if pos_match and state_match:
                        if order.get("sl_trigger_px", 0) > 0:
                            existing_sl = order["sl_trigger_px"]
                        if order.get("tp_trigger_px", 0) > 0:
                            existing_tp = order["tp_trigger_px"]
            # 实盘调试：记录查询到的现有止盈止损
            if not self.dry_run and (
                stop_loss_px is None
                or take_profit_px is None
                or stop_loss_px == 0
                or take_profit_px == 0
            ):
                self._audit_log(
                    "algo_preserve_check",
                    {
                        "inst_id": inst_id,
                        "pos_side": pos_side,
                        "input_sl": stop_loss_px,
                        "input_tp": take_profit_px,
                        "existing_sl": existing_sl,
                        "existing_tp": existing_tp,
                        "order_count": current_orders.get("count", 0),
                    },
                    current_orders,
                )
        except Exception as e:
            self._audit_log("algo_preserve_error", {"inst_id": inst_id}, {"error": str(e)})

        # 如果只更新一侧，保留另一侧的现有价格
        # 注意：stop_loss_px 可能是 None 或 0，都表示未传入
        if (stop_loss_px is None or stop_loss_px == 0) and existing_sl > 0:
            stop_loss_px = existing_sl
        if (take_profit_px is None or take_profit_px == 0) and existing_tp > 0:
            take_profit_px = existing_tp

        # 先撤销已有未触发的止盈止损单，避免重复下单
        try:
            self.cancel_algo_orders(inst_id)
        except Exception:
            pass

        # 获取持仓数量
        if sz is None:
            pos_data = self.get_positions(inst_id)
            if not pos_data["ok"]:
                return pos_data
            matched = [
                p for p in pos_data["positions"] if p["pos_side"] == pos_side and p["pos"] > 0
            ]
            if not matched:
                return {"ok": False, "error": f"无 {pos_side} 持仓可设置止盈止损"}
            sz = matched[0]["pos"]

        # OCO 单：止损和止盈必须同时设置，如果只有一个，用 conditional 单
        if stop_loss_px and take_profit_px:
            # OCO 类型
            side = "sell" if pos_side == "long" else "buy"
            body = {
                "instId": inst_id,
                "tdMode": self.cfg.get("td_mode", "isolated"),
                "side": side,
                "ordType": "oco",
                "sz": str(sz),
                "posSide": pos_side,
                "slTriggerPx": f"{stop_loss_px:.12f}",
                "slOrdPx": "-1",  # 市价触发
                "tpTriggerPx": f"{take_profit_px:.12f}",
                "tpOrdPx": "-1",
                "tag": "yijingsltp",
            }
            if self.dry_run:
                result = {
                    "ok": True,
                    "dry_run": True,
                    "type": "oco",
                    "stop_loss_px": stop_loss_px,
                    "take_profit_px": take_profit_px,
                    "sz": sz,
                    "side": side,
                    "algo_id": f"dry_oco_{int(time.time()*1000)}",
                }
            else:
                r = self._post("/api/v5/trade/order-algo", body)
                result = {
                    "ok": r.get("code") == "0",
                    "dry_run": False,
                    "type": "oco",
                    "stop_loss_px": stop_loss_px,
                    "take_profit_px": take_profit_px,
                    "sz": sz,
                    "side": side,
                    "algo_id": r.get("data", [{}])[0].get("algoId") if r.get("data") else None,
                    "raw": r,
                }
                self._audit_log("oco_sltp_order", body, r)
            oco_error = None if result.get("ok") else (result.get("raw", {}).get("msg", "unknown"))
            # dry_run 模式：记录到本地内存订单簿
            if self.dry_run and result.get("ok"):
                self._dry_run_algo_orders[inst_id] = [
                    {
                        "algo_id": result["algo_id"],
                        "ord_type": "oco",
                        "side": side,
                        "pos_side": pos_side,
                        "sz": sz,
                        "trigger_px": 0,
                        "sl_trigger_px": stop_loss_px,
                        "tp_trigger_px": take_profit_px,
                        "order_px": "-1",
                        "state": "live",
                        "actual_px": 0,
                        "tag": "yijingsltp",
                    }
                ]
            return {
                "orders": [result],
                "stop_loss": result,
                "take_profit": result,
                "ok": result.get("ok"),
                "error": oco_error,
                "reason": reason or "bcrm_risk_management",
            }

        # 仅止损或仅止盈（止盈止损条件单）
        if stop_loss_px:
            sl_side = "sell" if pos_side == "long" else "buy"
            body = {
                "instId": inst_id,
                "tdMode": self.cfg.get("td_mode", "isolated"),
                "side": sl_side,
                "ordType": "conditional",
                "sz": str(sz),
                "posSide": pos_side,
                "slTriggerPx": f"{stop_loss_px:.12f}",
                "slOrdPx": "-1",
                "slTriggerPxType": "last",
                "tag": "yijingsl",
            }
            if self.dry_run:
                sl_result = {
                    "ok": True,
                    "dry_run": True,
                    "type": "stop_loss",
                    "trigger_px": stop_loss_px,
                    "sz": sz,
                    "side": sl_side,
                    "algo_id": f"dry_sl_{int(time.time()*1000)}",
                }
            else:
                r = self._post("/api/v5/trade/order-algo", body)
                sl_result = {
                    "ok": r.get("code") == "0",
                    "dry_run": False,
                    "type": "stop_loss",
                    "trigger_px": stop_loss_px,
                    "sz": sz,
                    "side": sl_side,
                    "algo_id": r.get("data", [{}])[0].get("algoId") if r.get("data") else None,
                    "raw": r,
                }
                self._audit_log("stop_loss_order", body, r)
            sl_error = (
                None if sl_result.get("ok") else (sl_result.get("raw", {}).get("msg", "unknown"))
            )
            # dry_run 模式：记录到本地内存订单簿
            if self.dry_run and sl_result.get("ok"):
                orders = self._dry_run_algo_orders.setdefault(inst_id, [])
                # 移除同方向旧的仅止损单
                orders[:] = [
                    o
                    for o in orders
                    if not (
                        o["pos_side"] == pos_side
                        and o["ord_type"] == "conditional"
                        and o.get("sl_trigger_px", 0) > 0
                    )
                ]
                orders.append(
                    {
                        "algo_id": sl_result["algo_id"],
                        "ord_type": "conditional",
                        "side": sl_side,
                        "pos_side": pos_side,
                        "sz": sz,
                        "trigger_px": stop_loss_px,
                        "sl_trigger_px": stop_loss_px,
                        "tp_trigger_px": 0,
                        "order_px": "-1",
                        "state": "live",
                        "actual_px": 0,
                        "tag": "yijingsl",
                    }
                )
            return {
                "orders": [sl_result],
                "stop_loss": sl_result,
                "ok": sl_result.get("ok"),
                "error": sl_error,
                "reason": reason or "bcrm_risk_management",
            }

        # 仅止盈
        tp_side = "sell" if pos_side == "long" else "buy"
        body = {
            "instId": inst_id,
            "tdMode": self.cfg.get("td_mode", "isolated"),
            "side": tp_side,
            "ordType": "conditional",
            "sz": str(sz),
            "posSide": pos_side,
            "tpTriggerPx": f"{take_profit_px:.12f}",
            "tpOrdPx": "-1",
            "tpTriggerPxType": "last",
            "tag": "yijingtp",
        }
        if self.dry_run:
            tp_result = {
                "ok": True,
                "dry_run": True,
                "type": "take_profit",
                "trigger_px": take_profit_px,
                "sz": sz,
                "side": tp_side,
                "algo_id": f"dry_tp_{int(time.time()*1000)}",
            }
        else:
            r = self._post("/api/v5/trade/order-algo", body)
            tp_result = {
                "ok": r.get("code") == "0",
                "dry_run": False,
                "type": "take_profit",
                "trigger_px": take_profit_px,
                "sz": sz,
                "side": tp_side,
                "algo_id": r.get("data", [{}])[0].get("algoId") if r.get("data") else None,
                "raw": r,
            }
            self._audit_log("take_profit_order", body, r)
        tp_error = None if tp_result.get("ok") else (tp_result.get("raw", {}).get("msg", "unknown"))
        # dry_run 模式：记录到本地内存订单簿
        if self.dry_run and tp_result.get("ok"):
            orders = self._dry_run_algo_orders.setdefault(inst_id, [])
            # 移除同方向旧的仅止盈单
            orders[:] = [
                o
                for o in orders
                if not (
                    o["pos_side"] == pos_side
                    and o["ord_type"] == "conditional"
                    and o.get("tp_trigger_px", 0) > 0
                )
            ]
            orders.append(
                {
                    "algo_id": tp_result["algo_id"],
                    "ord_type": "conditional",
                    "side": tp_side,
                    "pos_side": pos_side,
                    "sz": sz,
                    "trigger_px": take_profit_px,
                    "sl_trigger_px": 0,
                    "tp_trigger_px": take_profit_px,
                    "order_px": "-1",
                    "state": "live",
                    "actual_px": 0,
                    "tag": "yijingtp",
                }
            )
        return {
            "orders": [tp_result],
            "take_profit": tp_result,
            "ok": tp_result.get("ok"),
            "error": tp_error,
            "reason": reason or "bcrm_risk_management",
        }

    def reduce_position(
        self,
        inst_id: str = None,
        pos_side: str = "long",
        reduce_ratio: float = 0.5,
        reason: str = "",
    ) -> Dict:
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

        matched = [p for p in pos_data["positions"] if p["pos_side"] == pos_side and p["pos"] > 0]
        if not matched:
            return {"ok": False, "error": f"无 {pos_side} 持仓可减仓"}

        full_sz = matched[0]["pos"]
        reduce_sz = int(full_sz * reduce_ratio)
        if reduce_sz < 1:
            return {
                "ok": False,
                "error": f"减仓数量不足（持仓 {full_sz}，减仓比例 {reduce_ratio}）",
            }

        side = "sell" if pos_side == "long" else "buy"
        result = self.place_order(
            inst_id=inst_id,
            side=side,
            ord_type="market",
            sz=reduce_sz,
            pos_side=pos_side,
            reason=reason or f"bcrm_reduce_{int(reduce_ratio*100)}pct",
        )
        result["reduce_ratio"] = reduce_ratio
        result["original_pos"] = full_sz
        result["reduce_sz"] = reduce_sz
        result["remaining_pos"] = full_sz - reduce_sz
        return result

    def cancel_algo_orders(self, inst_id: str = None) -> Dict:
        """撤销所有未触发的止盈止损单"""
        inst_id = inst_id or self.cfg["default_inst_id"]

        # dry_run 模式：直接清空本地内存订单簿
        if self.dry_run:
            orders = self._dry_run_algo_orders.get(inst_id, [])
            count = len(orders)
            self._dry_run_algo_orders[inst_id] = []
            return {
                "ok": True,
                "cancelled": count,
                "total": count,
                "msg": f"dry_run: 取消 {count} 个 algo orders",
                "dry_run": True,
            }

        if not self._has_credentials():
            return {"ok": False, "error": "missing api credentials"}

        algo_ids = []
        for ord_type in ("conditional", "oco"):
            r = self._get(
                "/api/v5/trade/orders-algo-pending", {"instId": inst_id, "ordType": ord_type}
            )
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
        """查询未触发的止盈止损单"""
        inst_id = inst_id or self.cfg["default_inst_id"]

        # dry_run 模式：从本地内存订单簿读取
        if self.dry_run:
            orders = self._dry_run_algo_orders.get(inst_id, [])
            return {"ok": True, "orders": list(orders), "count": len(orders), "dry_run": True}

        if not self._has_credentials():
            return {"ok": False, "error": "missing api credentials"}
        orders = []
        for ord_type in ("conditional", "oco"):
            r = self._get(
                "/api/v5/trade/orders-algo-pending", {"instId": inst_id, "ordType": ord_type}
            )
            if r.get("code") != "0":
                continue
            for d in r.get("data", []):
                orders.append(
                    {
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
                    }
                )
        return {"ok": True, "orders": orders, "count": len(orders)}

    def get_order(self, inst_id: str, ord_id: str) -> Dict:
        if not self._has_credentials():
            return {"ok": False, "error": "missing api credentials"}
        r = self._get("/api/v5/trade/order", {"instId": inst_id, "ordId": ord_id})
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

    def simulate_trade_from_bcrm(
        self, bcrm_result: Dict, inst_id: str = None, usdt_amount: float = None
    ) -> Dict:
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
        reason = (
            f"卦象:{bcrm_result.get('hexagram','?')} 两仪:{bcrm_result.get('two_yi_state','?')}"
        )
        stop_loss_px = bcrm_result.get("stop_loss_px", 0)
        take_profit_px = bcrm_result.get("take_profit_px", 0)
        reduce_ratio = bcrm_result.get("reduce_ratio", 0)

        result = {
            "action": action,
            "reason": reason,
            "executed": False,
            "risk_management": None,
        }

        if action == "open_long":
            r = self.market_open_long(inst_id, usdt_amount, reason=reason)
            result["order_result"] = r
            result["executed"] = r.get("ok", False)
            # 开仓后设置止盈止损
            if r.get("ok") and (stop_loss_px or take_profit_px):
                sl_tp = self.place_stop_loss_take_profit(
                    inst_id=inst_id,
                    pos_side="long",
                    stop_loss_px=stop_loss_px,
                    take_profit_px=take_profit_px,
                    reason=reason,
                )
                result["risk_management"] = sl_tp

        elif action == "open_short":
            r = self.market_open_short(inst_id, usdt_amount, reason=reason)
            result["order_result"] = r
            result["executed"] = r.get("ok", False)
            if r.get("ok") and (stop_loss_px or take_profit_px):
                sl_tp = self.place_stop_loss_take_profit(
                    inst_id=inst_id,
                    pos_side="short",
                    stop_loss_px=stop_loss_px,
                    take_profit_px=take_profit_px,
                    reason=reason,
                )
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
            r = self.reduce_position(
                inst_id=inst_id, pos_side="long", reduce_ratio=ratio, reason=reason
            )
            result["order_result"] = r
            result["executed"] = r.get("ok", False)
            # 减仓后更新止盈止损（撤旧设新）
            if r.get("ok") and (stop_loss_px or take_profit_px):
                self.cancel_algo_orders(inst_id)
                remaining = r.get("remaining_pos", 0)
                if remaining > 0:
                    sl_tp = self.place_stop_loss_take_profit(
                        inst_id=inst_id,
                        pos_side="long",
                        stop_loss_px=stop_loss_px,
                        take_profit_px=take_profit_px,
                        sz=remaining,
                        reason=reason,
                    )
                    result["risk_management"] = sl_tp

        elif action == "reduce_short":
            ratio = reduce_ratio or 0.5
            r = self.reduce_position(
                inst_id=inst_id, pos_side="short", reduce_ratio=ratio, reason=reason
            )
            result["order_result"] = r
            result["executed"] = r.get("ok", False)
            if r.get("ok") and (stop_loss_px or take_profit_px):
                self.cancel_algo_orders(inst_id)
                remaining = r.get("remaining_pos", 0)
                if remaining > 0:
                    sl_tp = self.place_stop_loss_take_profit(
                        inst_id=inst_id,
                        pos_side="short",
                        stop_loss_px=stop_loss_px,
                        take_profit_px=take_profit_px,
                        sz=remaining,
                        reason=reason,
                    )
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
        trade_logs = [l for l in logs if l.get("action", "").startswith("place_order")]

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
                kwargs["api_key"] = sys.argv[i + 1]
                i += 2
            elif sys.argv[i] == "--secret" and i + 1 < len(sys.argv):
                kwargs["secret_key"] = sys.argv[i + 1]
                i += 2
            elif sys.argv[i] == "--pass" and i + 1 < len(sys.argv):
                kwargs["passphrase"] = sys.argv[i + 1]
                i += 2
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
                pos_side = sys.argv[i + 1]
                i += 2
            elif sys.argv[i] == "--sl" and i + 1 < len(sys.argv):
                sl_px = float(sys.argv[i + 1])
                i += 2
            elif sys.argv[i] == "--tp" and i + 1 < len(sys.argv):
                tp_px = float(sys.argv[i + 1])
                i += 2
            else:
                i += 1
        r = client.place_stop_loss_take_profit(
            pos_side=pos_side, stop_loss_px=sl_px, take_profit_px=tp_px
        )
        print(json.dumps(r, indent=2, ensure_ascii=False))
        return

    if cmd == "reduce":
        # reduce --side long --ratio 0.5
        pos_side = "long"
        ratio = 0.5
        i = 2
        while i < len(sys.argv):
            if sys.argv[i] == "--side" and i + 1 < len(sys.argv):
                pos_side = sys.argv[i + 1]
                i += 2
            elif sys.argv[i] == "--ratio" and i + 1 < len(sys.argv):
                ratio = float(sys.argv[i + 1])
                i += 2
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
