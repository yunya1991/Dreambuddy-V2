#!/usr/bin/env python3
"""
Aster/Hyperliquid 执行层 v2
- 支持永续合约（perp）最大 5 倍杠杆
- 支持多币种：BTC/ETH/SOL/HYPE/AVAX/LINK/ARB/SUI/INJ/TIA
- 市价单（IOC + 滑点保护）
- 止损/止盈单
"""
import os, json, time, hashlib, requests, warnings, struct
from typing import Dict, Optional, Any, List
from pathlib import Path
from dotenv import load_dotenv

warnings.filterwarnings("ignore")
load_dotenv(Path(__file__).parent.parent / "config" / ".env")

HL_INFO     = "https://api.hyperliquid.xyz/info"
HL_EXCHANGE = "https://api.hyperliquid.xyz/exchange"
TIMEOUT     = 15

MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0

_cache = {}
_cache_ttl = {}


def float_to_wire(x):
    """Hyperliquid 价格/数量转换函数"""
    from decimal import Decimal
    rounded = f"{x:.8f}"
    return f"{Decimal(rounded).normalize():f}"


def _try_import_hyperliquid_utils():
    """尝试从本地或官方 SDK 导入 signing 模块"""
    # 先尝试本地包（与 aster_spot.py 同目录）
    try:
        from .hyperliquid.utils.signing import float_to_wire as local_float
        return local_float
    except ImportError:
        pass

    # 再尝试官方 SDK
    try:
        from hyperliquid.utils.signing import float_to_wire as sdk_float
        return sdk_float
    except ImportError:
        pass

    # 返回 None，使用内置的 float_to_wire
    return None


_loaded_float_to_wire = _try_import_hyperliquid_utils()
if _loaded_float_to_wire is not None:
    float_to_wire = _loaded_float_to_wire


try:
    import msgpack
    from eth_account import Account
    from eth_account.messages import encode_typed_data
    from eth_utils import keccak, to_hex
    HAS_ETH = True
except ImportError:
    HAS_ETH = False

# ── 交易标的池（实验允许范围） ───────────────────────────────────────────────
UNIVERSE = ["BTC", "ETH", "HYPE", "UNI", "SOL", "ZEC", "LIT", "ARB", "XRP", "WLD", "NEAR", "SUI", "LDO", "ADA", "ZRO", "ENA", "ETHFI", "JUP", "JTO", "SYRUP"]
MAX_LEVERAGE = 5
DEFAULT_LEVERAGE = 3


def _now_ms() -> int:
    return int(time.time() * 1000)


def _cache_get(key: str, ttl_seconds: int = 30):
    now = time.time()
    if key in _cache and (now - _cache_ttl.get(key, 0)) < ttl_seconds:
        return _cache[key]
    return None


def _cache_set(key: str, value):
    _cache[key] = value
    _cache_ttl[key] = time.time()


def _info_with_retry(session, payload: Dict, proxies=None) -> Any:
    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            r = session.post(HL_INFO, json=payload, proxies=proxies, timeout=TIMEOUT)
            if r.status_code == 429:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                time.sleep(delay)
                last_err = f"rate_limited_429_attempt_{attempt+1}"
                continue
            r.raise_for_status()
            return r.json()
        except requests.exceptions.RequestException as e:
            last_err = str(e)
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                time.sleep(delay)
            else:
                raise
    raise RuntimeError(f"hyperliquid_api_failed_after_{MAX_RETRIES}_retries: {last_err}")


def _info(payload: Dict, proxies=None) -> Any:
    s = requests.Session()
    s.trust_env = False
    return _info_with_retry(s, payload, proxies)


# ── 市场数据（公开，无需签名）────────────────────────────────────────────────

def get_all_mids(proxies=None) -> Dict[str, float]:
    cache_key = "all_mids"
    cached = _cache_get(cache_key, ttl_seconds=15)
    if cached is not None:
        return cached
    data = _info({"type": "allMids"}, proxies)
    result = {k: float(v) for k, v in data.items()}
    _cache_set(cache_key, result)
    return result

def get_meta(proxies=None) -> Dict:
    cache_key = "meta"
    cached = _cache_get(cache_key, ttl_seconds=60)
    if cached is not None:
        return cached
    result = _info({"type": "meta"}, proxies)
    _cache_set(cache_key, result)
    return result

def get_candles(coin: str, interval: str = "1h", count: int = 48,
                proxies=None) -> List[Dict]:
    cache_key = f"candles_{coin}_{interval}_{count}"
    cached = _cache_get(cache_key, ttl_seconds=60)
    if cached is not None:
        return cached
    now_ms = _now_ms()
    # PROP-20260816C: 补全 HL 官方支持的周期映射（V15 日线策略需要 1d；原字典缺 1d 时
    # 会静默按 1h 计算 startTime，interval 却传 1d → 返回数据严重不足）
    intervals = {
        "1m": 60000, "3m": 3*60000, "5m": 5*60000, "15m": 15*60000, "30m": 30*60000,
        "1h": 3600000, "2h": 2*3600000, "4h": 4*3600000, "8h": 8*3600000,
        "12h": 12*3600000, "1d": 24*3600000, "3d": 3*24*3600000,
        "1w": 7*24*3600000, "1M": 30*24*3600000,
    }
    ms = intervals.get(interval, 3600000)
    start = now_ms - ms * count
    data = _info({
        "type": "candleSnapshot",
        "req": {"coin": coin, "interval": interval,
                "startTime": start, "endTime": now_ms}
    }, proxies)
    result = data if isinstance(data, list) else []
    _cache_set(cache_key, result)
    return result

def _get_meta_and_ctxs(proxies=None):
    cache_key = "meta_and_asset_ctxs"
    cached = _cache_get(cache_key, ttl_seconds=30)
    if cached is not None:
        return cached
    data = _info({"type": "metaAndAssetCtxs"}, proxies)
    _cache_set(cache_key, data)
    return data


def get_funding_rate(coin: str, proxies=None) -> float:
    """获取当前资金费率"""
    try:
        data = _get_meta_and_ctxs(proxies)
        meta_list = data[0].get("universe", []) if isinstance(data, list) else []
        ctx_list  = data[1] if isinstance(data, list) and len(data) > 1 else []
        for i, m in enumerate(meta_list):
            if m.get("name") == coin and i < len(ctx_list):
                return float(ctx_list[i].get("funding", 0))
    except Exception:
        pass
    return 0.0

def scan_opportunities(proxies=None) -> List[Dict]:
    """
    扫描 UNIVERSE 所有标的，返回排序后的机会列表
    评分维度：24H涨跌幅、资金费率极值（做反向）、成交量
    """
    mids = get_all_mids(proxies)
    results = []
    try:
        data = _get_meta_and_ctxs(proxies)
        meta_list = data[0].get("universe", []) if isinstance(data, list) else []
        ctx_list  = data[1] if isinstance(data, list) and len(data) > 1 else []
        ctx_map = {m["name"]: ctx_list[i]
                   for i, m in enumerate(meta_list)
                   if m.get("name") in UNIVERSE and i < len(ctx_list)}
    except Exception:
        ctx_map = {}

    for coin in UNIVERSE:
        price = mids.get(coin, 0)
        if price <= 0:
            continue
        ctx = ctx_map.get(coin, {})
        funding = float(ctx.get("funding", 0))
        open_interest = float(ctx.get("openInterest", 0))
        # 资金费率极值 → 拥挤信号（反向操作机会）
        funding_signal = abs(funding) > 0.0003  # >0.03% 为极端
        funding_dir    = "SHORT" if funding > 0.0003 else ("LONG" if funding < -0.0003 else "NEUTRAL")

        results.append({
            "coin":          coin,
            "price":         price,
            "funding":       funding,
            "funding_signal": funding_signal,
            "funding_dir":   funding_dir,
            "open_interest": open_interest,
        })

    return results


# ── 签名工具（EIP-712）────────────────────────────────────────────────────────

def _action_hash(action: Dict, vault_address: Optional[str], nonce: int) -> bytes:
    """Hyperliquid action hash：msgpack 编码后 keccak256"""
    try:
        import msgpack
        packed = msgpack.packb(
            {"action": action, "vaultAddress": vault_address, "nonce": nonce},
            use_bin_type=True
        )
    except ImportError:
        packed = json.dumps(
            {"action": action, "vaultAddress": vault_address, "nonce": nonce},
            sort_keys=True
        ).encode()
    from eth_account._utils.legacy_transactions import serializable_unsigned_transaction_from_dict
    from web3 import Web3
    return Web3.keccak(packed)


def _action_hash_hl(action: Dict, vault_address: Optional[str],
                    nonce: int, expires_after: Optional[int] = None) -> bytes:
    """官方实现：msgpack(action) + nonce(8B big) + vault_flag + expires_flag"""
    data = msgpack.packb(action)
    data += nonce.to_bytes(8, "big")
    if vault_address is None:
        data += b"\x00"
    else:
        data += b"\x01"
        data += bytes.fromhex(vault_address[2:] if vault_address.startswith("0x") else vault_address)
    if expires_after is not None:
        data += b"\x00"
        data += expires_after.to_bytes(8, "big")
    return keccak(data)


def _sign_l1_action(private_key: str, action: Dict,
                    vault_address: Optional[str] = None,
                    nonce: Optional[int] = None) -> Dict:
    """官方 sign_l1_action 实现"""
    if not HAS_ETH:
        raise RuntimeError("pip install eth-account msgpack eth-utils")
    if nonce is None:
        nonce = _now_ms()

    conn_id = _action_hash_hl(action, vault_address, nonce)
    phantom_agent = {"source": "a", "connectionId": conn_id}  # mainnet = "a"

    typed_data = {
        "domain": {
            "chainId":           1337,
            "name":              "Exchange",
            "verifyingContract": "0x0000000000000000000000000000000000000000",
            "version":           "1",
        },
        "types": {
            "Agent": [
                {"name": "source",       "type": "string"},
                {"name": "connectionId", "type": "bytes32"},
            ],
            "EIP712Domain": [
                {"name": "name",              "type": "string"},
                {"name": "version",           "type": "string"},
                {"name": "chainId",           "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
        },
        "primaryType": "Agent",
        "message":     phantom_agent,
    }

    wallet = Account.from_key(private_key)
    structured = encode_typed_data(full_message=typed_data)
    signed = wallet.sign_message(structured)

    return {
        "action":       action,
        "nonce":        nonce,
        "signature":    {"r": to_hex(signed["r"]), "s": to_hex(signed["s"]), "v": signed["v"]},
        "vaultAddress": vault_address,
    }


# ── 客户端 ───────────────────────────────────────────────────────────────────

class HyperliquidClient:
    def __init__(self, agent_id: str):
        self.agent_id = agent_id.lower()
        # 注: 此类连接 Hyperliquid 交易所 (api.hyperliquid.xyz)
        #     兼容 HYPERLIQUID 和 ASTER 两种前缀（优先 HYPERLIQUID）
        def _get_env(name: str) -> str:
            val = os.environ.get(f"AGENT_{agent_id.upper()}_HYPERLIQUID_{name}", "")
            if val:
                return val
            return os.environ.get(f"AGENT_{agent_id.upper()}_ASTER_{name}", "")
        self.user_addr   = _get_env("USER")
        self.api_addr    = _get_env("SIGNER")
        self.private_key = _get_env("SIGNER_PRIVATE_KEY")

        proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        self.proxies = {"https": proxy_url, "http": proxy_url} if proxy_url else None

        self._s = requests.Session()
        self._s.trust_env = False

    # ── 内部 HTTP ───────────────────────────────────────────────────────────

    def _info(self, payload: Dict) -> Any:
        return _info_with_retry(self._s, payload, self.proxies)

    def _exchange(self, action: Dict) -> Dict:
        nonce   = _now_ms()
        payload = _sign_l1_action(self.private_key, action, nonce=nonce)
        last_err = None
        for attempt in range(MAX_RETRIES):
            r = self._s.post(HL_EXCHANGE, json=payload,
                             proxies=self.proxies, timeout=TIMEOUT)
            if r.status_code == 429:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                time.sleep(delay)
                last_err = f"rate_limited_429_attempt_{attempt+1}"
                continue
            if not r.ok:
                raise RuntimeError(f"exchange_error:{r.status_code}:{r.text[:300]}")
            return r.json()
        raise RuntimeError(f"exchange_failed_after_{MAX_RETRIES}_retries: {last_err}")

    # ── 账户查询 ────────────────────────────────────────────────────────────

    def get_account(self) -> Dict:
        r = self._info({"type": "clearinghouseState", "user": self.user_addr})
        margin = r.get("marginSummary", {})
        positions = {}
        for p in r.get("assetPositions", []):
            pos  = p.get("position", {})
            coin = pos.get("coin", "")
            szi  = float(pos.get("szi", 0))
            if abs(szi) > 0:
                positions[coin] = {
                    "size":     szi,
                    "entry_px": float(pos.get("entryPx") or 0),
                    "upnl":     float(pos.get("unrealizedPnl") or 0),
                    "leverage": float((pos.get("leverage") or {}).get("value", 1)),
                }

        perp_equity = float(margin.get("accountValue", 0))
        avail       = float(margin.get("marginAvailable") or 0)
        if avail == 0:
            avail = float(r.get("withdrawable", 0))
        if avail == 0:
            total_margin_used = float(margin.get("totalMarginUsed", 0))
            avail = max(0, perp_equity - total_margin_used)

        # 统一账户模式：现货 USDC 也可作为保证金，合并计算
        if avail == 0 and perp_equity == 0:
            try:
                r2    = self._info({"type": "spotClearinghouseState", "user": self.user_addr})
                spot_usdc = next(
                    (float(b["total"]) for b in r2.get("balances", [])
                     if b.get("coin") == "USDC"), 0
                )
                if spot_usdc > 0:
                    # 统一账户：现货 USDC 视为可用保证金
                    return {
                        "ok":        True,
                        "equity":    spot_usdc,
                        "avail":     spot_usdc,
                        "positions": positions,
                        "mode":      "unified_spot",
                    }
            except Exception:
                pass

        return {
            "ok":        True,
            "equity":    perp_equity,
            "avail":     avail,
            "positions": positions,
            "mode":      "perp",
        }

    def get_mid_price(self, coin: str) -> float:
        mids = self.get_all_mids()
        return float(mids.get(coin, 0))

    def get_all_mids(self) -> Dict[str, float]:
        return get_all_mids(self.proxies)

    def scan_opportunities(self) -> List[Dict]:
        return scan_opportunities(self.proxies)

    # ── 杠杆设置 ────────────────────────────────────────────────────────────

    def set_leverage(self, coin: str, leverage: int,
                     is_cross: bool = True) -> Dict:
        leverage = min(max(1, leverage), MAX_LEVERAGE)
        action = {
            "type":      "updateLeverage",
            "asset":     self._asset_index(coin),
            "isCross":   is_cross,
            "leverage":  leverage,
        }
        return self._exchange(action)

    # ── 下单 ────────────────────────────────────────────────────────────────

    def market_order(self, coin: str, is_buy: bool, sz: float,
                     leverage: int = DEFAULT_LEVERAGE,
                     reduce_only: bool = False,
                     tag: str = "ab") -> Dict:
        """合约市价单（IOC + 3% 滑点）"""
        leverage = min(max(1, leverage), MAX_LEVERAGE)
        # 先设置杠杆
        try:
            self.set_leverage(coin, leverage)
        except Exception:
            pass

        px = self.get_mid_price(coin)
        slippage = 1.03 if is_buy else 0.97
        limit_px = px * slippage

        action = {
            "type": "order",
            "orders": [{
                "a":  self._asset_index(coin),
                "b":  is_buy,
                "p":  _price_to_wire(limit_px),
                "s":  float_to_wire(round(sz, _size_decimals(coin))),
                "r":  reduce_only,
                "t":  {"limit": {"tif": "Ioc"}},
            }],
            "grouping": "na",
        }
        resp = self._exchange(action)
        ok = resp.get("status") == "ok"
        filled = {}
        try:
            filled = resp.get("response", {}).get("data", {}).get("statuses", [{}])[0]
        except Exception:
            pass
        return {
            "ok":       ok,
            "coin":     coin,
            "side":     "BUY" if is_buy else "SELL",
            "sz":       sz,
            "leverage": leverage,
            "filled":   filled,
            "raw":      resp,
        }

    def open_long(self, coin: str, usdt_amount: float,
                  leverage: int = DEFAULT_LEVERAGE, tag: str = "ab") -> Dict:
        """开多：指定 USDT 名义价值，自动保证最小名义 $11"""
        px = self.get_mid_price(coin)
        sz = usdt_amount * leverage / px
        # 保证名义价值 ≥ $11（Hyperliquid 最低 $10）
        min_sz = _min_notional_sz(coin, px)
        sz = max(sz, min_sz)
        return self.market_order(coin, True, sz, leverage, False, tag)

    def open_short(self, coin: str, usdt_amount: float,
                   leverage: int = DEFAULT_LEVERAGE, tag: str = "ab") -> Dict:
        """开空：指定 USDT 名义价值，自动保证最小名义 $11"""
        px = self.get_mid_price(coin)
        sz = usdt_amount * leverage / px
        min_sz = _min_notional_sz(coin, px)
        sz = max(sz, min_sz)
        return self.market_order(coin, False, sz, leverage, False, tag)

    def close_position(self, coin: str, tag: str = "ab") -> Dict:
        """平仓（reduce-only 市价单）"""
        acct = self.get_account()
        pos  = acct["positions"].get(coin)
        if not pos:
            return {"ok": False, "error": "no_position"}
        sz      = abs(pos["size"])
        is_buy  = pos["size"] < 0
        return self.market_order(coin, is_buy, sz, 1, True, tag)

    # ── 条件单（止盈止损 Trigger Order）──────────────────────────────────────

    def set_tpsl_orders(self, coin: str,
                        stop_loss_price: Optional[float] = None,
                        take_profit_price: Optional[float] = None,
                        is_market: bool = True) -> Dict:
        """
        为当前仓位设置止盈止损条件单
        - 使用 Hyperliquid 原生 trigger order
        - 方向：与当前持仓相反（reduce-only）
        """
        acct = self.get_account()
        pos = acct["positions"].get(coin)
        if not pos:
            return {"ok": False, "error": "no_position"}

        sz = abs(pos["size"])
        is_long = pos["size"] > 0
        asset_idx = self._asset_index(coin)

        orders = []

        if stop_loss_price and stop_loss_price > 0:
            order = {
                "a": asset_idx,
                "b": not is_long,
                "p": _price_to_wire(stop_loss_price),
                "s": float_to_wire(round(sz, _size_decimals(coin))),
                "r": True,
                "t": {
                    "trigger": {
                        "isMarket": is_market,
                        "triggerPx": _price_to_wire(stop_loss_price),
                        "tpsl": "sl",
                    }
                },
            }
            orders.append(order)

        if take_profit_price and take_profit_price > 0:
            order = {
                "a": asset_idx,
                "b": not is_long,
                "p": _price_to_wire(take_profit_price),
                "s": float_to_wire(round(sz, _size_decimals(coin))),
                "r": True,
                "t": {
                    "trigger": {
                        "isMarket": is_market,
                        "triggerPx": _price_to_wire(take_profit_price),
                        "tpsl": "tp",
                    }
                },
            }
            orders.append(order)

        if not orders:
            return {"ok": False, "error": "no_sl_or_tp_provided"}

        action = {
            "type": "order",
            "orders": orders,
            "grouping": "na",
        }

        try:
            resp = self._exchange(action)
            statuses = resp.get("response", {}).get("data", {}).get("statuses", [])
            ok = resp.get("status") == "ok" and all(
                "resting" in s or "filled" in s for s in statuses
            )
            oids = []
            for s in statuses:
                if "resting" in s:
                    oids.append(s["resting"]["oid"])
                elif "filled" in s:
                    oids.append(s["filled"]["oid"])
            return {
                "ok": ok,
                "coin": coin,
                "statuses": statuses,
                "oids": oids,
                "sl_price": stop_loss_price,
                "tp_price": take_profit_price,
                "raw": resp,
            }
        except Exception as e:
            return {"ok": False, "error": str(e), "coin": coin}

    def cancel_all_tpsl(self, coin: str) -> Dict:
        """取消该币种所有挂单（含 trigger/tpsl 订单）"""
        orders = self.get_open_orders(coin)
        if not orders:
            return {"ok": True, "cancelled": 0}

        asset_idx = self._asset_index(coin)
        cancels = []
        for o in orders:
            oid = o.get("oid")
            if oid:
                cancels.append({"a": asset_idx, "o": oid})

        if not cancels:
            return {"ok": True, "cancelled": 0}

        action = {
            "type": "cancel",
            "cancels": cancels,
        }

        try:
            resp = self._exchange(action)
            statuses = resp.get("response", {}).get("data", {}).get("statuses", [])
            success_count = sum(1 for s in statuses if s == "success")
            return {
                "ok": resp.get("status") == "ok",
                "cancelled": success_count,
                "raw": resp,
            }
        except Exception as e:
            return {"ok": False, "error": str(e), "cancelled": 0}

    def get_open_orders(self, coin: Optional[str] = None) -> List[Dict]:
        """获取挂单（含 trigger 条件单）"""
        try:
            r = self._info({
                "type": "openOrders",
                "user": self.user_addr,
            })
            if coin:
                return [o for o in r if o.get("coin") == coin]
            return r
        except Exception:
            return []

    def modify_tpsl(self, coin: str,
                    new_sl: Optional[float] = None,
                    new_tp: Optional[float] = None,
                    is_market: bool = True) -> Dict:
        """
        修改止盈止损：先取消现有 tpsl，再重新设置
        - 对于 LONG 仓位：止损只能向上移动（保护利润），止盈可上下调整
        - 对于 SHORT 仓位：止损只能向下移动（保护利润），止盈可上下调整
        """
        acct = self.get_account()
        pos = acct["positions"].get(coin)
        if not pos:
            return {"ok": False, "error": "no_position"}

        is_long = pos["size"] > 0

        # 获取当前挂单中的价格（用于校验移动方向）
        # openOrders 返回的 trigger 单用 limitPx 表示触发价
        current_orders = self.get_open_orders(coin)
        current_sl = None
        current_tp = None

        # 简单判断：LONG 仓位中，价格低于入场的是 SL，高于的是 TP
        entry_px = pos["entry_px"]
        for o in current_orders:
            px = float(o.get("limitPx", 0))
            if px <= 0:
                continue
            if is_long:
                if px < entry_px:
                    current_sl = px if current_sl is None else max(current_sl, px)
                else:
                    current_tp = px if current_tp is None else min(current_tp, px)
            else:
                if px > entry_px:
                    current_sl = px if current_sl is None else min(current_sl, px)
                else:
                    current_tp = px if current_tp is None else max(current_tp, px)

        # 校验：止损只能向有利方向移动
        if new_sl is not None and current_sl is not None:
            if is_long and new_sl <= current_sl:
                new_sl = current_sl
            elif not is_long and new_sl >= current_sl:
                new_sl = current_sl

        # 先取消，再设置
        cancel_res = self.cancel_all_tpsl(coin)

        # 如果 new_sl 和 new_tp 都没有，就只取消
        if new_sl is None and new_tp is None:
            return {
                "ok": cancel_res.get("ok", False),
                "coin": coin,
                "action": "cancel_only",
                "cancelled": cancel_res.get("cancelled", 0),
            }

        set_res = self.set_tpsl_orders(
            coin,
            stop_loss_price=new_sl,
            take_profit_price=new_tp,
            is_market=is_market,
        )

        return {
            "ok": set_res.get("ok", False),
            "coin": coin,
            "action": "modify",
            "new_sl": new_sl,
            "new_tp": new_tp,
            "old_sl": current_sl,
            "old_tp": current_tp,
            "cancelled": cancel_res.get("cancelled", 0),
            "set_result": set_res,
        }

    # ── 现货下单 ─────────────────────────────────────────────────────────────

    def get_spot_balance(self) -> Dict:
        """现货账户余额"""
        r = self._info({"type": "spotClearinghouseState", "user": self.user_addr})
        balances = {}
        for b in r.get("balances", []):
            total = float(b.get("total", 0))
            hold  = float(b.get("hold", 0))
            if total > 0.000001:
                balances[b["coin"]] = {"total": total, "avail": total - hold}
        usdc = balances.get("USDC", {}).get("avail", 0)
        return {"ok": True, "usdc_avail": usdc, "balances": balances}

    def spot_market_buy(self, coin: str, usdc_amount: float,
                        tag: str = "ab") -> Dict:
        """现货市价买入：花费 usdc_amount USDC 买 coin"""
        px = self.get_mid_price(coin)
        if px <= 0:
            return {"ok": False, "error": "price_unavailable"}
        sz = round(usdc_amount / px, _size_decimals(coin))
        # 现货用 spot market order（Hyperliquid spot asset index = token id + 10000）
        token_id = _SPOT_TOKEN.get(coin.upper())
        if token_id is None:
            return {"ok": False, "error": f"unknown_spot_coin:{coin}"}
        limit_px = round(px * 1.03, _price_decimals(coin))  # 3% 滑点
        action = {
            "type": "order",
            "orders": [{
                "a":  token_id,
                "b":  True,
                "p":  str(limit_px),
                "s":  str(sz),
                "r":  False,
                "t":  {"limit": {"tif": "Ioc"}},
                "c":  tag[:10],
            }],
            "grouping": "na",
        }
        resp = self._exchange(action)
        ok = resp.get("status") == "ok"
        filled = {}
        try:
            filled = resp.get("response", {}).get("data", {}).get("statuses", [{}])[0]
        except Exception:
            pass
        return {"ok": ok, "coin": coin, "side": "BUY",
                "usdc_spent": usdc_amount, "sz": sz, "filled": filled, "raw": resp}

    def spot_market_sell(self, coin: str, sz: float,
                         tag: str = "ab") -> Dict:
        """现货市价卖出：卖出 sz 个 coin"""
        token_id = _SPOT_TOKEN.get(coin.upper())
        if token_id is None:
            return {"ok": False, "error": f"unknown_spot_coin:{coin}"}
        px = self.get_mid_price(coin)
        limit_px = round(px * 0.97, _price_decimals(coin))
        action = {
            "type": "order",
            "orders": [{
                "a":  token_id,
                "b":  False,
                "p":  str(limit_px),
                "s":  str(round(sz, _size_decimals(coin))),
                "r":  False,
                "t":  {"limit": {"tif": "Ioc"}},
                "c":  tag[:10],
            }],
            "grouping": "na",
        }
        resp = self._exchange(action)
        ok = resp.get("status") == "ok"
        filled = {}
        try:
            filled = resp.get("response", {}).get("data", {}).get("statuses", [{}])[0]
        except Exception:
            pass
        return {"ok": ok, "coin": coin, "side": "SELL",
                "sz": sz, "filled": filled, "raw": resp}

    # ── 辅助 ────────────────────────────────────────────────────────────────

    def _asset_index(self, coin: str) -> int:
        return _ASSET_INDEX.get(coin.upper(), 0)


# ── 静态数据 ──────────────────────────────────────────────────────────────────

# 永续合约 asset index
_ASSET_INDEX = {
    "BTC": 0, "ETH": 1, "HYPE": 159, "UNI": 39, "SOL": 5, "ZEC": 214, "LIT": 223, "ARB": 11, "XRP": 25, "WLD": 31, "NEAR": 74, "SUI": 14, "LDO": 17, "ADA": 65, "ZRO": 46, "ENA": 122, "ETHFI": 121, "JUP": 90, "JTO": 94, "SYRUP": 199,
}

# 现货 token ID（Hyperliquid spot，asset = token_id + 10000）
_SPOT_TOKEN = {
    "USDC": 10000, "BTC": 10001, "ETH": 10002, "SOL": 10006,
    "HYPE": 10150, "AVAX": 10007,
}

def _price_to_wire(px: float) -> str:
    """Hyperliquid 要求价格用 5 位有效数字"""
    import math
    if px <= 0:
        return "0"
    mag = math.floor(math.log10(abs(px)))
    factor = 10 ** (4 - mag)
    rounded = round(px * factor) / factor
    return float_to_wire(rounded)

def _price_decimals(coin: str) -> int:
    return {"BTC": 1, "ETH": 2, "HYPE": 3, "UNI": 3, "SOL": 3, "ZEC": 3, "LIT": 5, "ARB": 4, "XRP": 5, "WLD": 4, "NEAR": 4, "SUI": 4, "LDO": 4, "ADA": 5, "ZRO": 4, "ENA": 5, "ETHFI": 4, "JUP": 5, "JTO": 5, "SYRUP": 5}.get(coin, 4)

def _size_decimals(coin: str) -> int:
    return {
        "BTC": 5, "ETH": 4, "HYPE": 2, "UNI": 1, "SOL": 2, "ZEC": 2, "LIT": 0, "ARB": 1, "XRP": 0, "WLD": 1, "NEAR": 1, "SUI": 1, "LDO": 1, "ADA": 0, "ZRO": 1, "ENA": 0, "ETHFI": 1, "JUP": 0, "JTO": 0, "SYRUP": 0,
    }.get(coin, 2)


def _min_notional_sz(coin: str, px: float, min_usd: float = 11.0) -> float:
    """计算满足最小名义价值的 size"""
    if px <= 0:
        return 0
    sz = min_usd / px
    return round(sz + 10 ** (-_size_decimals(coin)), _size_decimals(coin))


# ── 快速连通测试 ──────────────────────────────────────────────────────────────

def test_connection(agent_id: str = "b"):
    client = HyperliquidClient(agent_id)
    print(f"\n[Agent {agent_id.upper()}] Aster/Hyperliquid 连接测试")
    print(f"  wallet: {client.user_addr[:12]}...")

    # 价格
    try:
        mids = client.get_all_mids()
        for c in ["BTC", "ETH", "SOL", "HYPE"]:
            if c in mids:
                print(f"  {c}: ${mids[c]:,.2f}")
    except Exception as e:
        print(f"  价格查询失败: {e}"); return False

    # 账户
    try:
        acct = client.get_account()
        print(f"  账户权益: ${acct['equity']:.2f} USDC")
        print(f"  可用保证金: ${acct['avail']:.2f} USDC")
        for coin, p in acct["positions"].items():
            print(f"  仓位 {coin}: sz={p['size']} lev={p['leverage']}x upnl={p['upnl']:.2f}")
        if not acct["positions"]:
            print(f"  无持仓")
    except Exception as e:
        print(f"  账户查询失败: {e}")

    # 扫描机会
    print(f"\n  交易标的池扫描:")
    try:
        opps = client.scan_opportunities()
        for o in opps[:5]:
            fr = o['funding'] * 100
            signal = f"→{o['funding_dir']}" if o['funding_signal'] else ""
            print(f"    {o['coin']:6s} ${o['price']:>12,.2f}  资金费率:{fr:+.4f}% {signal}")
    except Exception as e:
        print(f"  扫描失败: {e}")

    print(f"\n  ✅ 连接正常")
    return True


if __name__ == "__main__":
    import sys
    test_connection(sys.argv[1] if len(sys.argv) > 1 else "b")
