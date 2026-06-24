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

try:
    import msgpack
    from eth_account import Account
    from eth_account.messages import encode_typed_data
    from eth_utils import keccak, to_hex
    from hyperliquid.utils.signing import float_to_wire
    HAS_ETH = True
except ImportError:
    HAS_ETH = False
    def float_to_wire(x):
        from decimal import Decimal
        rounded = f"{x:.8f}"
        return f"{Decimal(rounded).normalize():f}"

# ── 交易标的池（实验允许范围） ───────────────────────────────────────────────
UNIVERSE = ["BTC", "ETH", "SOL", "HYPE", "AVAX", "LINK", "ARB", "SUI", "INJ", "TIA"]
MAX_LEVERAGE = 5
DEFAULT_LEVERAGE = 3


def _now_ms() -> int:
    return int(time.time() * 1000)


def _info(payload: Dict, proxies=None) -> Any:
    s = requests.Session()
    s.trust_env = False
    r = s.post(HL_INFO, json=payload, proxies=proxies, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


# ── 市场数据（公开，无需签名）────────────────────────────────────────────────

def get_all_mids(proxies=None) -> Dict[str, float]:
    data = _info({"type": "allMids"}, proxies)
    return {k: float(v) for k, v in data.items()}

def get_meta(proxies=None) -> Dict:
    return _info({"type": "meta"}, proxies)

def get_candles(coin: str, interval: str = "1h", count: int = 48,
                proxies=None) -> List[Dict]:
    """K线数据"""
    now_ms = _now_ms()
    intervals = {"5m": 5*60000, "15m": 15*60000, "1h": 3600000, "4h": 4*3600000}
    ms = intervals.get(interval, 3600000)
    start = now_ms - ms * count
    data = _info({
        "type": "candleSnapshot",
        "req": {"coin": coin, "interval": interval,
                "startTime": start, "endTime": now_ms}
    }, proxies)
    return data if isinstance(data, list) else []

def get_funding_rate(coin: str, proxies=None) -> float:
    """获取当前资金费率"""
    try:
        data = _info({"type": "metaAndAssetCtxs"}, proxies)
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
        data = _info({"type": "metaAndAssetCtxs"}, proxies)
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
        pfx = f"AGENT_{agent_id.upper()}_ASTER"
        self.user_addr   = os.environ.get(f"{pfx}_USER", "")
        self.api_addr    = os.environ.get(f"{pfx}_SIGNER", "")
        self.private_key = os.environ.get(f"{pfx}_SIGNER_PRIVATE_KEY", "")

        proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        self.proxies = {"https": proxy_url, "http": proxy_url} if proxy_url else None

        self._s = requests.Session()
        self._s.trust_env = False

    # ── 内部 HTTP ───────────────────────────────────────────────────────────

    def _info(self, payload: Dict) -> Any:
        r = self._s.post(HL_INFO, json=payload,
                         proxies=self.proxies, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()

    def _exchange(self, action: Dict) -> Dict:
        nonce   = _now_ms()
        payload = _sign_l1_action(self.private_key, action, nonce=nonce)
        r = self._s.post(HL_EXCHANGE, json=payload,
                         proxies=self.proxies, timeout=TIMEOUT)
        if not r.ok:
            raise RuntimeError(f"exchange_error:{r.status_code}:{r.text[:300]}")
        return r.json()

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
        return {
            "ok":        True,
            "equity":    float(margin.get("accountValue", 0)),
            "avail":     float(margin.get("marginAvailable") or 0),
            "positions": positions,
        }

    def get_mid_price(self, coin: str) -> float:
        mids = self._info({"type": "allMids"})
        return float(mids.get(coin, 0))

    def get_all_mids(self) -> Dict[str, float]:
        return {k: float(v) for k, v in self._info({"type": "allMids"}).items()}

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
    "BTC": 0, "ETH": 1, "ATOM": 2, "MATIC": 3, "DYDX": 4,
    "SOL": 5, "AVAX": 6, "BNB": 7, "APE": 8, "OP": 9,
    "LTC": 10, "ARB": 11, "DOGE": 12, "INJ": 13, "SUI": 14,
    "TIA": 17, "LINK": 25, "HYPE": 159, "WIF": 23,
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
    return {"BTC": 1, "ETH": 2, "SOL": 3, "HYPE": 3}.get(coin, 4)

def _size_decimals(coin: str) -> int:
    return {
        "BTC": 5, "ETH": 4, "SOL": 2, "AVAX": 2,
        "TIA": 1, "INJ": 1, "SUI": 1, "ARB": 0,
        "LINK": 1, "HYPE": 2,
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
