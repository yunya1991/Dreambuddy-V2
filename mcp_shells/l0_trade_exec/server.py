#!/usr/bin/env python3
"""mcp_shells/l0_trade_exec/server.py — L0 交易执行 MCP（trade-exec 壳）

SPEC-L0-TRADE-EXEC-MCP v0.2 + mcp_capabilities.yaml（port=event, domain=trade-exec）
硬约束（遵守 47-MCP 奠基性边界）：
  - 本壳**仅承载 paper 模拟盘模式**，绝不触真实交易所
  - 实盘 live 由 11 域 okx_client 旁路网关直连，不经过 MCP
  - 壳内零真实下单能力：无 OKX API credentials、无签名逻辑、仅 HTTP GET 公开行情端点
  - 行情走 OKX 公开 ticker（/api/v5/market/ticker），FAIL-OPEN 超时返回 None
  - 账本走本地 JSON 文件锁（atomic write + flock），参考 V15PaperClient 设计

4 个工具（初版）：
  - place_order    write, requires_mandate=true, destructive
  - cancel_order   write, requires_mandate=true, destructive
  - get_positions  read
  - get_balance    read

信封 meta 承载 {mode: "paper", cost: {latency_ms, slippage_bps}}，不改 envelope_wrap 签名（H1 壳 diff=0）。
stdio JSON-RPC 2.0，按需拉起，不常驻。
"""

from __future__ import annotations

import fcntl
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── 壳进程 import 规约（SPEC-L0-MCP-PACKAGING §3.4）────────
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from mcp_shells._shared.envelope_wrap import wrap  # noqa: E402
from mcp_shells._shared.shadow_hook import observe_envelope  # noqa: E402

SHELL_SOURCE = "l0.trade-exec.mcp"  # 与注册表 shell_id 对齐（多词统一连字符）

# ── OKX 行情配置 ──────────────────────────────────────────
OKX_BASE_URL = os.environ.get("OKX_BASE_URL", "https://www.okx.com").rstrip("/")
OKX_TICKER_PATH = "/api/v5/market/ticker"
HTTP_TIMEOUT = float(os.environ.get("TRADE_EXEC_HTTP_TIMEOUT", "5"))

# ── Paper 账本配置 ─────────────────────────────────────────
_LEDGER_DIR = Path(
    os.environ.get(
        "TRADE_EXEC_LEDGER_DIR",
        str(_REPO_ROOT / "mcp_shells" / "l0_trade_exec" / "ledger"),
    )
)
_LEDGER_DIR.mkdir(parents=True, exist_ok=True)
LEDGER_PATH = str(_LEDGER_DIR / "paper_ledger.json")

DEFAULT_INITIAL_CAPITAL = float(os.environ.get("TRADE_EXEC_INITIAL_CAPITAL", "260.0"))

# 模拟撮合常量（与 V15PaperClient 对齐）
SLIPPAGE = 0.0005  # 5bps 单边滑点
TAKER_FEE = 0.00045  # HL taker ~0.045%（近似 OKX）
FILL_EPS = 1e-12
MAX_FILL_HISTORY = 500


# ── 行情配置：OKX 为主（需 User-Agent header 绕过 OKX 屏蔽 Python urllib），HL 兜底 ──
OKX_BASE_URL = os.environ.get("OKX_BASE_URL", "https://www.okx.com").rstrip("/")
OKX_TICKER_PATH = "/api/v5/market/ticker"
HL_BASE_URL = os.environ.get("HL_BASE_URL", "https://api.hyperliquid.xyz").rstrip("/")
HTTP_TIMEOUT = float(os.environ.get("TRADE_EXEC_HTTP_TIMEOUT", "4"))
_USER_AGENT = os.environ.get("TRADE_EXEC_USER_AGENT", "curl/7.81.0")  # OKX 屏蔽 urllib 默认 UA


def _okx_get_ticker(inst_id: str) -> Optional[Dict[str, float]]:
    """OKX 公开 ticker → {last, bid, ask} 或 None（FAIL-OPEN）。"""
    try:
        url = f"{OKX_BASE_URL}{OKX_TICKER_PATH}?instId={inst_id}"
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            d = json.loads(resp.read().decode("utf-8"))
        if d.get("code") != "0" or not d.get("data"):
            return None
        row = d["data"][0]
        return {
            "last": float(row.get("last", 0)),
            "bid": float(row.get("bidPx", row.get("last", 0))),
            "ask": float(row.get("askPx", row.get("last", 0))),
        }
    except Exception:  # noqa: BLE001 — FAIL-OPEN
        return None


def _hl_get_ticker(hl_coin: str) -> Optional[Dict[str, float]]:
    """Hyperliquid public allMids → {last, bid, ask} 或 None（FAIL-OPEN）。"""
    try:
        body = json.dumps({"type": "allMids"}).encode("utf-8")
        req = urllib.request.Request(
            f"{HL_BASE_URL}/info",
            data=body,
            headers={"Content-Type": "application/json", "User-Agent": _USER_AGENT},
        )
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            d = json.loads(resp.read().decode("utf-8"))
        mid = d.get(hl_coin)
        if not mid:
            return None
        mid_f = float(mid)
        half = 0.0001 * mid_f
        return {"last": mid_f, "bid": mid_f - half, "ask": mid_f + half}
    except Exception:  # noqa: BLE001 — FAIL-OPEN
        return None


def _get_ticker(inst_id: str) -> Optional[Dict[str, float]]:
    """OKX 优先，HL 兜底（腾讯云 OKX 可达但需 User-Agent header）。"""
    r = _okx_get_ticker(inst_id)
    if r:
        return r
    hl_coin = inst_id.split("-")[0].upper()
    return _hl_get_ticker(hl_coin)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coin(inst_id: str) -> str:
    return (inst_id or "").split("-")[0].upper()


# ── OKXPaperLedger（自包含，不依赖 14 域或 HL）──────────────────
class OKXPaperLedger:
    """纯 paper 账本：原子 JSON 文件锁 + 模拟撮合。无任何实盘能力。"""

    def __init__(self, path: str = LEDGER_PATH, initial_capital: float = DEFAULT_INITIAL_CAPITAL):
        self.path = path
        self.initial_capital = initial_capital
        self._ensure_default()

    def _ensure_default(self) -> None:
        if not os.path.exists(self.path):
            led = {
                "version": 1,
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
                "initial_capital": self.initial_capital,
                "balance": self.initial_capital,
                "fee_paid": 0.0,
                "realized_pnl": 0.0,
                "positions": {},  # coin -> {inst_id, pos_side, pos, avg_px, opened_at}
                "pending_orders": {},  # ord_id -> {...}
                "fills": [],  # 成交流水
                "executed_signals": [],  # {signal_id, ts, ord_id} 幂等去重（阶段三）
            }
            self._save(led)

    # ── 文件锁原子读写 ─────────────────────────────────────
    def _load(self) -> Dict[str, Any]:
        with open(self.path, "r") as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            try:
                return json.load(f)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def _save(self, led: Dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        led["updated_at"] = _now_iso()
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                json.dump(led, f, ensure_ascii=False, indent=1)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
        os.replace(tmp, self.path)

    # ── 撮合引擎 ──────────────────────────────────────────
    def _fill_px(self, mid: float, side: str) -> float:
        """买入向上滑、卖出向下滑（保守方向）"""
        return mid * (1 + SLIPPAGE) if side == "buy" else mid * (1 - SLIPPAGE)

    def _apply_fill(
        self,
        led: Dict[str, Any],
        coin: str,
        inst_id: str,
        side: str,
        pos_side: str,
        sz: float,
        px: float,
        reason: str,
    ) -> float:
        """应用成交到账本，返回 realized pnl"""
        pos = led["positions"].get(coin)

        # net 模式方向推导：有仓沿用现有方向（同向加仓/反向平仓），无仓按 side 开户
        if pos_side == "net":
            if pos and pos.get("pos", 0) > FILL_EPS:
                pos_side = pos.get("pos_side", "long")
            else:
                pos_side = "long" if side == "buy" else "short"

        notional = sz * px
        fee = notional * TAKER_FEE
        led["fee_paid"] = led.get("fee_paid", 0.0) + fee
        led["balance"] = led.get("balance", 0.0) - fee

        realized = 0.0
        opening = (side == "buy" and pos_side == "long") or (side == "sell" and pos_side == "short")

        if opening:
            if pos and pos.get("pos_side") == pos_side and pos.get("pos", 0) > 0:
                # 同向加仓：加权均价
                old_sz, old_px = pos["pos"], pos["avg_px"]
                new_sz = old_sz + sz
                pos["avg_px"] = (old_sz * old_px + sz * px) / new_sz
                pos["pos"] = new_sz
            else:
                led["positions"][coin] = {
                    "inst_id": inst_id,
                    "pos_side": pos_side,
                    "pos": sz,
                    "avg_px": px,
                    "opened_at": _now_iso(),
                }
        else:
            # 减仓/平仓
            if pos and pos.get("pos_side") == pos_side and pos.get("pos", 0) > FILL_EPS:
                direction = 1.0 if pos_side == "long" else -1.0
                close_sz = min(sz, pos["pos"])
                realized = (px - pos["avg_px"]) * close_sz * direction
                pos["pos"] -= close_sz
                if pos["pos"] <= FILL_EPS:
                    del led["positions"][coin]

        # 记 fill 流水
        fill = {
            "ts": _now_iso(),
            "coin": coin,
            "inst_id": inst_id,
            "side": side,
            "pos_side": pos_side,
            "sz": sz,
            "px": round(px, 8),
            "fee": round(fee, 6),
            "realized_pnl": round(realized, 6),
            "reason": reason,
        }
        led.setdefault("fills", []).append(fill)
        if len(led["fills"]) > MAX_FILL_HISTORY:
            led["fills"] = led["fills"][-MAX_FILL_HISTORY:]

        if abs(realized) > FILL_EPS:
            led["realized_pnl"] = led.get("realized_pnl", 0.0) + realized
            led["balance"] = led.get("balance", 0.0) + realized
        return realized

    def _check_limit_fills(self, led: Dict[str, Any]) -> bool:
        """限价单穿越成交"""
        changed = False
        if not led.get("pending_orders"):
            return False
        for oid, o in list(led["pending_orders"].items()):
            if o.get("state") != "live":
                continue
            coin = _coin(o.get("inst_id", ""))
            ticker = _get_ticker(o.get("inst_id", ""))
            if not ticker:
                continue
            mid = (ticker["bid"] + ticker["ask"]) / 2.0
            px = float(o.get("px", 0))
            side = o.get("side")
            filled = (side == "buy" and mid <= px) or (side == "sell" and mid >= px)
            if not filled:
                continue
            self._apply_fill(
                led,
                coin,
                o.get("inst_id", ""),
                side,
                o.get("pos_side", "net"),
                float(o.get("sz", 0)),
                px,
                f"limit_cross:{oid}",
            )
            o["state"] = "filled"
            o["avg_px"] = px
            o["filled_sz"] = float(o.get("sz", 0))
            changed = True
        return changed

    # ── 公开操作 ──────────────────────────────────────────
    def place_market_order(
        self, inst_id: str, side: str, sz: float, pos_side: str = "net"
    ) -> Dict[str, Any]:
        """市价单：按行情源 ticker mid ± 滑点 立即成交"""
        ticker = _get_ticker(inst_id)
        if not ticker:
            return {
                "ok": False,
                "error": f"no market data for {inst_id} (OKX + HL both unavailable)",
            }
        mid = (ticker["bid"] + ticker["ask"]) / 2.0
        fill = self._fill_px(mid, side)
        led = self._load()
        self._check_limit_fills(led)
        coin = _coin(inst_id)
        realized = self._apply_fill(led, coin, inst_id, side, pos_side, sz, fill, "market")
        self._save(led)
        slippage_bps = abs(fill - mid) / mid * 10000.0 if mid > 0 else 0.0
        return {
            "ok": True,
            "ord_id": f"paper_mkt_{int(time.time() * 1000)}",
            "inst_id": inst_id,
            "side": side,
            "pos_side": pos_side,
            "sz": sz,
            "avg_px": round(fill, 8),
            "mid_px": round(mid, 8),
            "realized_pnl": round(realized, 8),
            "fee": round(sz * fill * TAKER_FEE, 8),
            "simulated": True,
            "paper": True,
            "slippage_bps": round(slippage_bps, 4),
        }

    def place_limit_order(
        self, inst_id: str, side: str, sz: float, px: float, pos_side: str = "net"
    ) -> Dict[str, Any]:
        """限价单：入账本等待穿越"""
        led = self._load()
        self._check_limit_fills(led)
        oid = f"paper_lmt_{int(time.time() * 1000)}"
        led["pending_orders"][oid] = {
            "ord_id": oid,
            "inst_id": inst_id,
            "coin": _coin(inst_id),
            "side": side,
            "pos_side": pos_side,
            "ord_type": "limit",
            "sz": sz,
            "px": px,
            "state": "live",
            "created_at": _now_iso(),
        }
        # 挂单瞬间若已穿越立即成交
        self._check_limit_fills(led)
        self._save(led)
        state = led["pending_orders"].get(oid, {}).get("state", "live")
        return {
            "ok": True,
            "ord_id": oid,
            "inst_id": inst_id,
            "side": side,
            "pos_side": pos_side,
            "sz": sz,
            "px": px,
            "state": state,
            "simulated": True,
            "paper": True,
        }

    def cancel_order(self, ord_id: str) -> Dict[str, Any]:
        led = self._load()
        o = led.get("pending_orders", {}).get(ord_id)
        if not o:
            return {"ok": False, "error": f"order not found: {ord_id}"}
        if o.get("state") != "live":
            return {"ok": False, "error": f"order state not cancellable: {o.get('state')}"}
        o["state"] = "cancelled"
        o["cancel_ts"] = _now_iso()
        self._save(led)
        return {"ok": True, "ord_id": ord_id}

    def get_balance(self) -> Dict[str, Any]:
        led = self._load()
        return {
            "ok": True,
            "balance": round(led.get("balance", 0.0), 8),
            "initial_capital": led.get("initial_capital", 0.0),
            "realized_pnl": round(led.get("realized_pnl", 0.0), 8),
            "fee_paid": round(led.get("fee_paid", 0.0), 8),
        }

    # ── 信号幂等（阶段三：同一 signal_id 只执行一次）──────────
    def is_signal_executed(self, signal_id: str) -> bool:
        if not signal_id:
            return False
        led = self._load()
        return any(r.get("signal_id") == signal_id for r in led.get("executed_signals", []))

    def mark_signal_executed(self, signal_id: str, ord_id: str) -> None:
        if not signal_id:
            return
        led = self._load()
        records = led.setdefault("executed_signals", [])
        records.append({"signal_id": signal_id, "ts": _now_iso(), "ord_id": ord_id})
        if len(records) > MAX_FILL_HISTORY:
            del records[:-MAX_FILL_HISTORY]
        self._save(led)

    def get_positions(self, inst_id: Optional[str] = None) -> Dict[str, Any]:
        led = self._load()
        self._check_limit_fills(led)
        positions: List[Dict[str, Any]] = []
        for coin, pos in led.get("positions", {}).items():
            ticker = _get_ticker(pos.get("inst_id", f"{coin}-USDT-SWAP"))
            mid = (ticker["bid"] + ticker["ask"]) / 2.0 if ticker else pos.get("avg_px", 0.0)
            direction = 1.0 if pos.get("pos_side") == "long" else -1.0
            upl = (mid - pos.get("avg_px", 0.0)) * pos.get("pos", 0.0) * direction
            positions.append(
                {
                    "inst_id": pos.get("inst_id"),
                    "coin": coin,
                    "pos_side": pos.get("pos_side"),
                    "side": "long" if direction > 0 else "short",
                    "pos": round(pos.get("pos", 0.0), 8),
                    "avg_px": round(pos.get("avg_px", 0.0), 8),
                    "mark_px": round(mid, 8),
                    "upl": round(upl, 8),
                }
            )
        return {"ok": True, "positions": positions, "count": len(positions)}


_ledger = OKXPaperLedger()


# ── ExecutionRights：标的级执行权（阶段四 SPEC §4）───────────────
# 硬约束：同一标的同一时刻单出口。声明 live:11-bypass / disabled 的标的，
# MCP 一律拒单（实盘由 11 域 okx_client 旁路网关执行，不经 MCP）。
EXECUTION_RIGHTS_PATH = Path(
    os.environ.get(
        "TRADE_EXEC_RIGHTS_PATH",
        str(
            Path(__file__).resolve().parents[2]
            / "47-MCP管理系统"
            / "registry"
            / "execution_rights.json"
        ),
    )
)


class ExecutionRights:
    """标的级执行权注册表（JSON，零依赖，按 mtime 热加载）。

    匹配顺序：完整 inst_id → coin（BTC-USDT-SWAP → BTC）→ defaults.outcome。
    """

    _cache: Optional[Dict[str, Any]] = None
    _mtime: float = -1.0
    _load_error: Optional[str] = None

    @classmethod
    def _load(cls) -> Dict[str, Any]:
        try:
            mtime = EXECUTION_RIGHTS_PATH.stat().st_mtime
            if cls._cache is not None and mtime == cls._mtime:
                return cls._cache
            with open(EXECUTION_RIGHTS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            cls._cache = data
            cls._mtime = mtime
            cls._load_error = None
            return data
        except Exception as e:  # noqa: BLE001 — 文件缺失按 defaults(paper) 兜底
            if cls._cache is None:
                cls._load_error = f"{type(e).__name__}: {e}"
                cls._cache = {}
            return cls._cache

    @classmethod
    def outcome_for(cls, inst_id: str) -> str:
        data = cls._load()
        symbols = data.get("symbols") or {}
        for key in (inst_id, _coin(inst_id)):
            entry = symbols.get(key)
            if isinstance(entry, str):
                return entry.strip().lower()
            if isinstance(entry, dict) and entry.get("outcome"):
                return str(entry["outcome"]).strip().lower()
        return str((data.get("defaults") or {}).get("outcome") or "paper").strip().lower()

    @classmethod
    def conflict(cls, inst_id: str) -> Optional[str]:
        outcome = cls.outcome_for(inst_id)
        if outcome == "paper":
            return None
        if outcome.startswith("live"):
            detail = "实盘由 11 域 okx_client 旁路网关执行（见 registry/execution_rights.json）"
        else:
            detail = "该标的已声明停单，两个出口均不执行（见 registry/execution_rights.json）"
        return (
            f"execution_rights_conflict: {inst_id} 当前出口为 {outcome}，"
            f"MCP 仅承担 paper；{detail}"
        )

    @classmethod
    def summary(cls) -> Dict[str, Any]:
        data = cls._load()
        return {
            "path": str(EXECUTION_RIGHTS_PATH),
            "available": cls._load_error is None,
            "defaults": data.get("defaults"),
            "declared_symbols": list((data.get("symbols") or {}).keys()),
            "load_error": cls._load_error,
        }


_exec_rights = ExecutionRights()


# ── RiskBridge：事前风控 + 定容（桥接 13 域 RiskEngine）─────────
# Fail-Closed 原则：RiskEngine 加载失败/不可用时，place_order 全部拒绝。
# 这是 SPEC §1.2 + §1.5 "风控不可用时拒绝下单" 的硬性体现。
class RiskBridge:
    """桥接 13-通用风控模块 RiskEngine → MCP 壳前置管道。

    执行顺序：
      1. pre_trade_check(signal, context) → RiskCheckResult
      2. calculate_position(signal, context, position_modifier) → PositionSizeResult

    壳侧只拿 RiskCheckResult.passed + PositionSizeResult.base_size_coins，
    做不做自动定容由 MCP 调用方决定（通过 size 参数显式覆盖）。
    """

    _available: Optional[bool] = None  # None=未尝试, True=可用, False=不可用
    _engine: Any = None
    _last_error: Optional[str] = None

    @classmethod
    def _try_load(cls) -> None:
        if cls._available is not None:
            return
        try:
            repo_root = Path(__file__).resolve().parents[2]
            risk_path = str(repo_root / "13-通用风控模块")
            if risk_path not in sys.path:
                sys.path.insert(0, risk_path)
            from core.engine import RiskEngine  # noqa: E402

            cls._engine = RiskEngine({})
            cls._engine.register_default_rules()
            cls._available = True
        except Exception as e:  # noqa: BLE001
            cls._available = False
            cls._last_error = f"{type(e).__name__}: {e}"
            cls._engine = None

    @classmethod
    def is_available(cls) -> bool:
        cls._try_load()
        return cls._available is True

    @classmethod
    def check(
        cls,
        *,
        coin: str,
        side: str,
        confidence: float,
        inst_id: str = "",
        account_balance: float = 0.0,
        current_positions: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """事前风控检查。Fail-Closed：不可用时返回 passed=False。"""
        cls._try_load()
        if not cls._available or cls._engine is None:
            return {
                "passed": False,
                "reason_code": "RISK_BRIDGE_UNAVAILABLE",
                "message": f"RiskEngine 不可用: {cls._last_error or 'unknown'}",
                "position_modifier": 1.0,
                "risk_level": "HIGH",
            }
        try:
            from core.context import Direction, RiskContext, Signal  # noqa: E402

            direction = Direction.LONG if side == "buy" else Direction.SHORT
            signal = Signal(coin=coin, direction=direction, confidence=confidence)
            ctx = RiskContext(
                total_equity=account_balance,
                available_balance=account_balance,
                positions=current_positions or [],
            )
            result = cls._engine.pre_trade_check(signal, ctx)
            return {
                "passed": result.passed,
                "reason_code": getattr(result.reason_code, "name", str(result.reason_code)),
                "message": result.message,
                "position_modifier": result.position_modifier,
                "risk_level": getattr(result.risk_level, "name", str(result.risk_level)),
            }
        except Exception as e:  # noqa: BLE001
            return {
                "passed": False,
                "reason_code": "RISK_BRIDGE_EXCEPTION",
                "message": f"RiskEngine 执行异常: {type(e).__name__}: {e}",
                "position_modifier": 1.0,
                "risk_level": "HIGH",
            }

    @classmethod
    def suggest_size(
        cls,
        *,
        coin: str,
        side: str,
        confidence: float,
        inst_id: str = "",
        account_balance: float = 0.0,
        current_positions: Optional[List[Dict[str, Any]]] = None,
        position_modifier: float = 1.0,
    ) -> Dict[str, Any]:
        """定容建议。返回 PositionSizeResult 核心字段。"""
        cls._try_load()
        if not cls._available or cls._engine is None:
            return {"ok": False, "error": "RiskEngine 不可用"}
        try:
            from core.context import Direction, RiskContext, Signal  # noqa: E402

            direction = Direction.LONG if side == "buy" else Direction.SHORT
            signal = Signal(coin=coin, direction=direction, confidence=confidence)
            ctx = RiskContext(
                total_equity=account_balance,
                available_balance=account_balance,
                positions=current_positions or [],
            )
            result = cls._engine.calculate_position(signal, ctx, position_modifier)
            return {
                "ok": True,
                "base_size_usdt": result.base_size_usdt,
                "base_size_coins": result.base_size_coins,
                "position_tier": result.position_tier,
                "max_addons": result.max_addons,
                "leverage": result.leverage,
            }
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    @classmethod
    def check_exit(
        cls,
        *,
        coin: str,
        side: str,
        entry_price: float,
        current_price: float,
        position_size: float,
        unrealized_pnl_pct: float = 0.0,
        account_balance: float = 0.0,
        held_seconds: float = 0.0,
    ) -> Dict[str, Any]:
        """离场决策（13 域 ExitEngine.check_exit）。

        Fail-OPEN：只读建议，不可用时返回 HOLD + degraded，不阻断任何执行。
        """
        cls._try_load()
        if not cls._available or cls._engine is None:
            return {
                "ok": False,
                "action": "HOLD",
                "reason": f"RiskEngine 不可用: {cls._last_error or 'unknown'}",
                "degraded": True,
            }
        try:
            from core.context import (  # noqa: E402
                Direction,
                MarketSnapshot,
                PositionState,
                RiskContext,
            )

            direction = Direction.LONG if side in ("buy", "long") else Direction.SHORT
            position = PositionState(
                coin=coin,
                side=direction,
                entry_price=entry_price,
                current_price=current_price,
                position_size=position_size,
                position_age_sec=held_seconds,
                unrealized_pnl_pct=unrealized_pnl_pct,
            )
            market = MarketSnapshot(coin=coin, price=current_price)
            ctx = RiskContext(
                total_equity=account_balance,
                available_balance=account_balance,
                positions=[],
            )
            result = cls._engine.check_exit(position, market, ctx)
            action = getattr(result.action, "name", str(result.action))
            return {
                "ok": True,
                "action": action,
                "should_exit": action != "HOLD",
                "priority": getattr(result.priority, "name", str(result.priority)),
                "reason": result.reason,
                "reduce_frac": result.reduce_frac,
            }
        except Exception as e:  # noqa: BLE001
            return {
                "ok": False,
                "action": "HOLD",
                "reason": f"ExitEngine 执行异常: {type(e).__name__}: {e}",
                "degraded": True,
            }


_risk_bridge = RiskBridge()


# ── SignalAdapter：23/42 域信号接入（阶段三 SPEC §4）─────────────
# 信号侧 FAIL-OPEN（SPEC §5）：读不到/格式错误只降级，不阻断。
# 执行侧仍 FAIL-CLOSED（风控不可用则拒绝），不对称是刻意设计。
DEFAULT_SIGNAL_NOTIONAL_USDT = float(os.environ.get("TRADE_EXEC_SIGNAL_NOTIONAL", "10.0"))
SIGNAL_FRESHNESS_SECONDS = float(os.environ.get("TRADE_EXEC_SIGNAL_FRESHNESS", "120"))

_SIGNAL_SOURCES = {
    "23": Path(
        os.environ.get(
            "SIGNAL_23_STATE_PATH",
            "/home/luke/dreambuddy/11-易经推理系统/data/event_driven_state.json",
        )
    ),
    "42": Path(
        os.environ.get(
            "SIGNAL_42_BUS_PATH",
            "/home/luke/dreambuddy/42-神经网络交易协调层/runtime/bus_state.json",
        )
    ),
}


def _to_inst_id(symbol: str) -> str:
    """符号归一化：BTC / HYPE / BTC-USDT / BTC-USDT-SWAP → OKX instId。"""
    s = (symbol or "").strip().upper()
    if not s:
        return ""
    if "-" in s:
        parts = s.split("-")
        if len(parts) >= 2 and parts[-1] in ("SWAP", "FUTURES"):
            return s
        if parts[-1] == "USDT":
            return f"{s}-SWAP"
        return s
    return f"{s}-USDT-SWAP"


class SignalAdapter:
    """把 23 域 state / 42 域 bus_state 归一化为统一内部信号。

    统一结构：
      {signal_id, source, symbol(instId), direction(long/short/neutral),
       confidence, risk_exposure_hint, ts, expires_at, shadow, raw}
    """

    @staticmethod
    def from_23_state(state: Dict[str, Any]) -> Dict[str, Any]:
        symbol = str(state.get("symbol") or "").strip()
        updated_at = str(state.get("updated_at") or "")
        sig = state.get("signal") or {}
        main = state.get("main_chain") or {}
        action = str(main.get("action") or "neutral").strip().lower()
        direction = {"long": "long", "short": "short", "buy": "long", "sell": "short"}.get(
            action, "neutral"
        )
        # signal 自带明确方向时优先（event-driven 信号）
        raw_sig = str(sig.get("signal") or "").strip().lower()
        if raw_sig in ("long", "short"):
            direction = raw_sig
        confidence = float(sig.get("confidence") or 0.0)
        # 23 域无 expires_at：以 updated_at + 新鲜度窗口推导
        expires_at = ""
        try:
            dt = datetime.fromisoformat(updated_at)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            expires_at = (dt + timedelta(seconds=SIGNAL_FRESHNESS_SECONDS)).isoformat()
        except Exception:  # noqa: BLE001
            expires_at = ""
        return {
            "signal_id": f"23_{updated_at}_{symbol}".replace(" ", ""),
            "source": "23-evolution",
            "symbol": _to_inst_id(symbol),
            "direction": direction,
            "confidence": confidence,
            "risk_exposure_hint": 0.0,
            "ts": updated_at,
            "expires_at": expires_at,
            "shadow": str(state.get("mode") or "") == "shadow",
            "raw": state,
        }

    @staticmethod
    def from_42_signal(signal: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """42 域 SignalSchema → 统一结构（字段缺失返回 None）。"""
        required = ("signal_id", "source", "ts", "symbol", "direction", "confidence")
        if not isinstance(signal, dict) or any(k not in signal for k in required):
            return None
        direction = str(signal.get("direction") or "neutral").lower()
        if direction not in ("long", "short", "neutral"):
            return None
        return {
            "signal_id": str(signal.get("signal_id")),
            "source": str(signal.get("source") or "unknown"),
            "symbol": _to_inst_id(str(signal.get("symbol") or "")),
            "direction": direction,
            "confidence": float(signal.get("confidence") or 0.0),
            "risk_exposure_hint": float(signal.get("risk_exposure_hint") or 0.0),
            "ts": str(signal.get("ts") or ""),
            "expires_at": str(signal.get("expires_at") or ""),
            "shadow": bool(signal.get("shadow", False)),
            "raw": signal,
        }

    @staticmethod
    def read_source(name: str) -> Dict[str, Any]:
        """读取单个信号源。FAIL-OPEN：任何异常返回空列表 + error。"""
        path = _SIGNAL_SOURCES.get(name)
        if path is None:
            return {"ok": False, "error": f"unknown signal source: {name}", "signals": []}
        try:
            if not path.exists():
                return {"ok": False, "error": f"source not found: {path}", "signals": []}
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"{type(e).__name__}: {e}", "signals": []}

        signals: List[Dict[str, Any]] = []
        if name == "23":
            signals.append(SignalAdapter.from_23_state(raw))
        elif name == "42":
            for sig in raw.get("signals") or []:
                norm = SignalAdapter.from_42_signal(sig)
                if norm:
                    signals.append(norm)
        return {"ok": True, "path": str(path), "signals": signals}

    @staticmethod
    def read_latest(sources: Optional[List[str]] = None) -> Dict[str, Any]:
        """读取多个源（FAIL-OPEN：单源失败不影响其他源）。"""
        names = sources or list(_SIGNAL_SOURCES.keys())
        out: List[Dict[str, Any]] = []
        errors: Dict[str, str] = {}
        for name in names:
            res = SignalAdapter.read_source(name)
            if res.get("ok"):
                out.extend(res["signals"])
            else:
                errors[name] = res.get("error", "unknown")
        return {"signals": out, "errors": errors}

    @staticmethod
    def is_expired(signal: Dict[str, Any]) -> bool:
        exp = signal.get("expires_at") or ""
        if not exp:
            return False  # 无过期字段视为不过期（由幂等兜底）
        try:
            dt = datetime.fromisoformat(exp)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return datetime.now(timezone.utc) > dt
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def size_from_signal(
        signal: Dict[str, Any], balance: float, mid_px: float, explicit_size: Optional[float] = None
    ) -> float:
        """定容：显式 size 优先；否则 risk_exposure_hint × balance / mid；再否则默认名义。"""
        if explicit_size is not None and float(explicit_size) > 0:
            return float(explicit_size)
        notional = DEFAULT_SIGNAL_NOTIONAL_USDT
        hint = float(signal.get("risk_exposure_hint") or 0.0)
        if hint > 0 and balance > 0:
            notional = min(balance * hint, balance)
        if mid_px <= 0:
            return 0.0
        return notional / mid_px


_signal_adapter = SignalAdapter()


# ── Tool Handlers ───────────────────────────────────────────
# 训练样本落盘（training_hooks 载体）：成交/拒单/跳过 → JSONL，供 23/42 域进化使用。
# FAIL-OPEN：写失败静默，绝不影响交易主流程。
TRAINING_SAMPLE_PATH = Path(
    os.environ.get(
        "TRADE_EXEC_SAMPLE_PATH",
        str(Path(__file__).resolve().parent / "ml_data" / "samples.jsonl"),
    )
)


def _emit_sample(kind: str, payload: Dict[str, Any]) -> None:
    try:
        record = {
            "ts": _now_iso(),
            "kind": kind,
            "trace_id": os.environ.get("MCP_TRACE_ID", ""),
            "mode": "paper",
        }
        record.update(payload)
        TRAINING_SAMPLE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(TRAINING_SAMPLE_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass


def _wrap_paper(
    data: Any,
    latency_ms: float,
    slippage_bps: float = 0.0,
    degraded: bool = False,
    error_code: str = "",
    reason: str = "",
    extra_meta: Optional[Dict[str, Any]] = None,
) -> str:
    """信封包装：mode=paper, cost={latency_ms, slippage_bps} 承载于 meta。"""
    meta: Dict[str, Any] = {
        "mode": "paper",
        "cost": {
            "latency_ms": round(latency_ms, 3),
            "slippage_bps": round(slippage_bps, 4),
        },
    }
    if reason:
        meta["reason"] = reason
    if extra_meta:
        meta.update(extra_meta)
    env = wrap(
        data,
        SHELL_SOURCE,
        degraded=degraded,
        error_code=error_code,
        meta=meta,
    )
    return json.dumps(env, ensure_ascii=False)


def _apply_sizing_clamp(sz: float, sizing: Dict[str, Any]) -> float:
    """定容钳位：PositionSizer 建议作为上限，只可收紧不可放大。

    建议缺失/非正时保持原值（例如行情不可用），并在 sizing 里记录决策依据。
    """
    if not sizing.get("ok"):
        return sz
    suggested = float(sizing.get("base_size_coins") or 0.0)
    if suggested <= 0:
        return sz
    sizing["requested_size"] = sz
    if sz > suggested:
        sizing["applied_size"] = suggested
        sizing["clamped"] = True
        return suggested
    sizing["applied_size"] = sz
    sizing["clamped"] = False
    return sz


def _handle_place_order(args: Dict[str, Any]) -> str:
    inst_id = str(args.get("symbol") or args.get("inst_id") or "").strip()
    side = str(args.get("side") or "").strip().lower()
    sz = args.get("size") if args.get("size") is not None else args.get("sz")
    ord_type = str(args.get("order_type") or args.get("ord_type") or "market").strip().lower()
    px = args.get("price") if args.get("price") is not None else args.get("px")
    pos_side = str(args.get("pos_side") or "net").strip().lower()
    confidence = float(args.get("confidence") or 0.5)
    skip_risk = bool(args.get("skip_risk_check", False))
    skip_sizing = bool(args.get("skip_sizing", False))

    # ── 参数校验 ──
    if not inst_id or not side or sz is None:
        return _wrap_paper(
            None,
            0.0,
            degraded=True,
            error_code="invalid",
            reason=f"missing required args: symbol/side/size (got {args})",
        )
    if side not in ("buy", "sell"):
        return _wrap_paper(
            None,
            0.0,
            degraded=True,
            error_code="invalid",
            reason=f"side must be buy/sell, got {side}",
        )
    try:
        sz_f = float(sz)
        if sz_f <= 0:
            return _wrap_paper(
                None,
                0.0,
                degraded=True,
                error_code="invalid",
                reason=f"size must be > 0, got {sz}",
            )
    except (TypeError, ValueError):
        return _wrap_paper(
            None,
            0.0,
            degraded=True,
            error_code="invalid",
            reason=f"size not numeric: {sz}",
        )

    coin = _coin(inst_id)

    # ── 执行权校验（阶段四：同一标的单出口）───────────────────
    rights_conflict = _exec_rights.conflict(inst_id)
    if rights_conflict:
        return _wrap_paper(
            {"rejected": True, "reason": rights_conflict},
            0.0,
            degraded=True,
            error_code="execution_rights_conflict",
            reason=rights_conflict,
        )

    # ── 执行管道（SPEC §1.5 固定顺序）─────────────────────────
    # 1. RiskCheckPort（fail-closed：RiskEngine 不可用则拒绝）
    # 2. 定容（13 PositionSizer 钳位；16 capital_allocator 属实盘资金层，未接入，见 SPEC §11 P1）
    # 3. OrderPort（撮合）
    risk_result: Dict[str, Any] = {}
    sizing_result: Dict[str, Any] = {}

    if not skip_risk:
        bal = _ledger.get_balance()["balance"]
        pos = _ledger.get_positions()["positions"]
        risk_result = _risk_bridge.check(
            coin=coin,
            side=side,
            confidence=confidence,
            inst_id=inst_id,
            account_balance=bal,
            current_positions=pos,
        )
        if not risk_result.get("passed"):
            started = time.perf_counter()
            _emit_sample(
                "risk_rejected",
                {
                    "inst_id": inst_id,
                    "side": side,
                    "size": sz_f,
                    "confidence": confidence,
                    "reason_code": risk_result.get("reason_code"),
                    "risk_level": risk_result.get("risk_level"),
                },
            )
            return _wrap_paper(
                {
                    "rejected": True,
                    "reason_code": risk_result.get("reason_code"),
                    "message": risk_result.get("message"),
                    "risk_level": risk_result.get("risk_level"),
                },
                time.perf_counter() - started,
                degraded=True,
                error_code="risk_rejected",
                reason=f"风控拒绝: {risk_result.get('reason_code')} - {risk_result.get('message')}",
            )

        # 2. 定容：用 RiskEngine 的 position_modifier + PositionSizer 建议
        if not skip_sizing and _risk_bridge.is_available():
            sizing_result = _risk_bridge.suggest_size(
                coin=coin,
                side=side,
                confidence=confidence,
                inst_id=inst_id,
                account_balance=bal,
                current_positions=pos,
                position_modifier=risk_result.get("position_modifier", 1.0),
            )
            # 定容钳位：PositionSizer 建议作为上限，只可收紧不可放大（skip_sizing 可跳过）
            sz_f = _apply_sizing_clamp(sz_f, sizing_result)

    # ── 3. OrderPort（撮合）──
    started = time.perf_counter()
    try:
        if ord_type == "market":
            result = _ledger.place_market_order(inst_id, side, sz_f, pos_side)
        elif ord_type == "limit":
            if px is None:
                return _wrap_paper(
                    None,
                    time.perf_counter() - started,
                    degraded=True,
                    error_code="invalid",
                    reason="price required for limit order",
                )
            result = _ledger.place_limit_order(inst_id, side, sz_f, float(px), pos_side)
        else:
            return _wrap_paper(
                None,
                time.perf_counter() - started,
                degraded=True,
                error_code="invalid",
                reason=f"unsupported order_type: {ord_type}",
            )
    except Exception as e:  # noqa: BLE001
        return _wrap_paper(
            None,
            time.perf_counter() - started,
            degraded=True,
            error_code="internal",
            reason=f"{type(e).__name__}: {e}",
        )

    latency_ms = (time.perf_counter() - started) * 1000.0
    if not result.get("ok"):
        return _wrap_paper(
            result,
            latency_ms,
            degraded=True,
            error_code="rejected",
            reason=result.get("error", ""),
            extra_meta={"risk": risk_result} if risk_result else None,
        )
    slippage_bps = result.get("slippage_bps", 0.0)
    extra_meta: Optional[Dict[str, Any]] = {}
    if risk_result:
        extra_meta["risk"] = risk_result
    if sizing_result.get("ok"):
        extra_meta["sizing"] = {
            k: sizing_result[k]
            for k in (
                "base_size_usdt",
                "base_size_coins",
                "position_tier",
                "leverage",
                "requested_size",
                "applied_size",
                "clamped",
            )
            if k in sizing_result
        }
    _emit_sample(
        "order_filled",
        {
            "inst_id": inst_id,
            "side": side,
            "size": sz_f,
            "confidence": confidence,
            "ord_type": ord_type,
            "avg_px": result.get("avg_px"),
            "mid_px": result.get("mid_px"),
            "slippage_bps": slippage_bps,
            "realized_pnl": result.get("realized_pnl"),
            "fee": result.get("fee"),
            "risk": risk_result or None,
            "sizing": extra_meta.get("sizing"),
        },
    )
    return _wrap_paper(result, latency_ms, slippage_bps, extra_meta=extra_meta or None)


def _handle_cancel_order(args: Dict[str, Any]) -> str:
    ord_id = str(args.get("order_id") or args.get("ord_id") or "").strip()
    if not ord_id:
        return _wrap_paper(
            None,
            0.0,
            degraded=True,
            error_code="invalid",
            reason="order_id required",
        )
    started = time.perf_counter()
    result = _ledger.cancel_order(ord_id)
    latency_ms = (time.perf_counter() - started) * 1000.0
    if not result.get("ok"):
        return _wrap_paper(
            result,
            latency_ms,
            degraded=True,
            error_code="not_found",
            reason=result.get("error", ""),
        )
    return _wrap_paper(result, latency_ms)


def _handle_get_positions(args: Dict[str, Any]) -> str:
    inst_id = args.get("symbol") or args.get("inst_id")
    started = time.perf_counter()
    result = _ledger.get_positions(str(inst_id) if inst_id else None)
    latency_ms = (time.perf_counter() - started) * 1000.0
    return _wrap_paper(result, latency_ms)


def _handle_get_balance(args: Dict[str, Any]) -> str:
    started = time.perf_counter()
    result = _ledger.get_balance()
    latency_ms = (time.perf_counter() - started) * 1000.0
    return _wrap_paper(result, latency_ms)


def _handle_pre_trade_check(args: Dict[str, Any]) -> str:
    """独立风控查询（SPEC §1.2 RiskCheckPort 单独暴露）。"""
    inst_id = str(args.get("symbol") or args.get("inst_id") or "").strip()
    side = str(args.get("side") or "buy").strip().lower()
    confidence = float(args.get("confidence") or 0.5)
    coin = _coin(inst_id)
    started = time.perf_counter()
    risk = _risk_bridge.check(
        coin=coin,
        side=side,
        confidence=confidence,
        inst_id=inst_id,
        account_balance=_ledger.get_balance()["balance"],
        current_positions=_ledger.get_positions()["positions"],
    )
    sizing = (
        _risk_bridge.suggest_size(
            coin=coin,
            side=side,
            confidence=confidence,
            inst_id=inst_id,
            account_balance=_ledger.get_balance()["balance"],
            current_positions=_ledger.get_positions()["positions"],
            position_modifier=risk.get("position_modifier", 1.0),
        )
        if risk.get("passed")
        else {}
    )
    latency_ms = (time.perf_counter() - started) * 1000.0
    return _wrap_paper(
        {"risk": risk, "sizing": sizing},
        latency_ms,
        extra_meta={"risk": risk, "sizing": sizing if sizing.get("ok") else None},
    )


def _handle_check_exit(args: Dict[str, Any]) -> str:
    """离场决策查询（SPEC §1.2 ExitCheckPort）：13 域 ExitEngine 对 paper 持仓逐仓评估。

    只读建议，不下单；FAIL-OPEN（引擎不可用 → HOLD + degraded）。
    """
    started = time.perf_counter()
    inst_id = str(args.get("symbol") or args.get("inst_id") or "").strip()
    bal = _ledger.get_balance()["balance"]
    positions = _ledger.get_positions(inst_id or None)["positions"]

    decisions: List[Dict[str, Any]] = []
    for p in positions:
        avg_px = float(p.get("avg_px") or 0.0)
        mark_px = float(p.get("mark_px") or 0.0)
        size = float(p.get("pos") or 0.0)
        notional = avg_px * size
        pnl_pct = (float(p.get("upl") or 0.0) / notional * 100.0) if notional > 0 else 0.0
        res = _risk_bridge.check_exit(
            coin=p.get("coin", ""),
            side=p.get("side", "long"),
            entry_price=avg_px,
            current_price=mark_px,
            position_size=size,
            unrealized_pnl_pct=pnl_pct,
            account_balance=bal,
        )
        decisions.append({"inst_id": p.get("inst_id"), **res})

    latency_ms = (time.perf_counter() - started) * 1000.0
    degraded = any(d.get("degraded") for d in decisions)
    return _wrap_paper(
        {
            "decisions": decisions,
            "count": len(decisions),
            "should_exit_count": sum(1 for d in decisions if d.get("should_exit")),
        },
        latency_ms,
        degraded=degraded,
        error_code="exit_engine_unavailable" if degraded else "",
        reason="ExitEngine 不可用，全部 HOLD" if degraded else "",
    )


def _handle_get_account_mode(args: Dict[str, Any]) -> str:
    """AccountPort.get_account_mode：壳侧固定 paper-only。"""
    latency_ms = 0.1
    return _wrap_paper(
        {
            "mode": "paper",
            "exchange": "okx",
            "endpoints": {
                "ticker": f"{OKX_BASE_URL}{OKX_TICKER_PATH}",
                "ledger": LEDGER_PATH,
            },
            "risk_engine_available": _risk_bridge.is_available(),
            "execution_rights": _exec_rights.summary(),
        },
        latency_ms,
    )


def _handle_reconcile(args: Dict[str, Any]) -> str:
    """PositionPort.reconcile：paper-only 无需对账，返回自洽报告。"""
    latency_ms = 0.2
    bal = _ledger.get_balance()
    pos = _ledger.get_positions()
    fills_count = (
        len(json.loads(open(LEDGER_PATH).read()).get("fills", []))
        if os.path.exists(LEDGER_PATH)
        else 0
    )
    report = {
        "mode": "paper",
        "status": "self_consistent",
        "local_positions_count": pos["count"],
        "local_balance": bal["balance"],
        "fills_count": fills_count,
        "diff_with_exchange": None,  # paper-only 无交易所对比
    }
    return _wrap_paper(report, latency_ms)


def _handle_read_signals(args: Dict[str, Any]) -> str:
    """读取信号源（23/42），归一化返回。信号侧 FAIL-OPEN。"""
    started = time.perf_counter()
    sources = args.get("sources") or ["23", "42"]
    include_neutral = bool(args.get("include_neutral", True))
    limit = int(args.get("limit") or 20)
    res = _signal_adapter.read_latest(
        list(sources) if isinstance(sources, (list, tuple)) else [sources]
    )
    signals = res.get("signals", [])
    if not include_neutral:
        signals = [s for s in signals if s.get("direction") in ("long", "short")]
    signals = signals[:limit]
    data = {
        "signals": signals,
        "count": len(signals),
        "errors": res.get("errors", {}),
        "sources": list(sources) if isinstance(sources, (list, tuple)) else [sources],
    }
    latency_ms = (time.perf_counter() - started) * 1000.0
    degraded = bool(data["errors"])
    return _wrap_paper(
        data,
        latency_ms,
        degraded=degraded,
        error_code="signal_source_partial" if degraded else "",
        reason="; ".join(f"{k}: {v}" for k, v in data["errors"].items()) if degraded else "",
    )


def _handle_ingest_signal(args: Dict[str, Any]) -> str:
    """信号 → 完整执行管道（风控→定容→paper 下单），幂等 + 过期校验。

    参数：
      signal: dict（42 域 SignalSchema 或任意含 symbol/direction/confidence 的 dict）
      source: "inline"（默认）| "23" | "42"（从对应源取最新一条）
      size: 显式覆盖定容
      paper_execute: false 时只做风控+定容，不下单
    """
    started = time.perf_counter()
    source = str(args.get("source") or "inline")
    explicit_size = args.get("size")
    paper_execute = bool(args.get("paper_execute", True))

    # 1. 取信号
    if source in _SIGNAL_SOURCES:
        res = _signal_adapter.read_source(source)
        if not res.get("ok") or not res.get("signals"):
            return _wrap_paper(
                {"skipped": True, "reason": res.get("error", "no signal")},
                (time.perf_counter() - started) * 1000.0,
                degraded=True,
                error_code="signal_source_unavailable",
                reason=res.get("error", "no signal"),
            )
        raw_sig = res["signals"][0]
        norm = raw_sig  # read_source 已返回归一化结构
    else:
        raw_sig = args.get("signal") or {}
        if source == "42" or ("signal_id" in raw_sig and "source" in raw_sig):
            norm = _signal_adapter.from_42_signal(raw_sig)
        else:
            # inline 宽松模式：用 42 schema 校验，失败则按简化 dict 兜底
            norm = _signal_adapter.from_42_signal(raw_sig)
            if norm is None and raw_sig.get("symbol"):
                direction = str(raw_sig.get("direction") or raw_sig.get("side") or "").lower()
                direction = {"buy": "long", "sell": "short"}.get(direction, direction)
                norm = {
                    "signal_id": str(
                        raw_sig.get("signal_id") or f"inline_{int(time.time() * 1000)}"
                    ),
                    "source": str(raw_sig.get("source") or "inline"),
                    "symbol": _to_inst_id(str(raw_sig.get("symbol"))),
                    "direction": direction,
                    "confidence": float(raw_sig.get("confidence") or 0.5),
                    "risk_exposure_hint": float(raw_sig.get("risk_exposure_hint") or 0.0),
                    "ts": str(raw_sig.get("ts") or _now_iso()),
                    "expires_at": str(raw_sig.get("expires_at") or ""),
                    "shadow": bool(raw_sig.get("shadow", False)),
                    "raw": raw_sig,
                }
        if norm is None:
            return _wrap_paper(
                {"skipped": True, "reason": "invalid signal schema"},
                (time.perf_counter() - started) * 1000.0,
                degraded=True,
                error_code="signal_invalid",
                reason="signal 不满足 42 域 SignalSchema（需 signal_id/source/ts/symbol/direction/confidence）",
            )

    sig = norm
    # 2. 前置过滤：neutral / 过期 / 幂等
    if sig.get("direction") not in ("long", "short"):
        _emit_sample(
            "signal_skipped",
            {
                "signal_id": sig.get("signal_id"),
                "source": sig.get("source"),
                "symbol": sig.get("symbol"),
                "direction": sig.get("direction"),
                "reason": "neutral",
            },
        )
        return _wrap_paper(
            {"skipped": True, "reason": "neutral direction", "signal_id": sig.get("signal_id")},
            (time.perf_counter() - started) * 1000.0,
        )
    if _signal_adapter.is_expired(sig):
        _emit_sample(
            "signal_skipped",
            {
                "signal_id": sig.get("signal_id"),
                "source": sig.get("source"),
                "symbol": sig.get("symbol"),
                "direction": sig.get("direction"),
                "reason": "expired",
                "expires_at": sig.get("expires_at"),
            },
        )
        return _wrap_paper(
            {
                "skipped": True,
                "reason": "signal expired",
                "signal_id": sig.get("signal_id"),
                "expires_at": sig.get("expires_at"),
            },
            (time.perf_counter() - started) * 1000.0,
            degraded=True,
            error_code="signal_expired",
            reason=f"signal expired at {sig.get('expires_at')}",
        )
    sig_id = sig.get("signal_id") or ""
    if sig_id and _ledger.is_signal_executed(sig_id):
        _emit_sample(
            "signal_skipped",
            {
                "signal_id": sig_id,
                "source": sig.get("source"),
                "symbol": sig.get("symbol"),
                "direction": sig.get("direction"),
                "reason": "duplicate",
            },
        )
        return _wrap_paper(
            {"skipped": True, "reason": "duplicate signal (already executed)", "signal_id": sig_id},
            (time.perf_counter() - started) * 1000.0,
        )

    inst_id = sig.get("symbol") or ""
    side = "buy" if sig.get("direction") == "long" else "sell"
    confidence = float(sig.get("confidence") or 0.5)
    if not inst_id:
        return _wrap_paper(
            {"skipped": True, "reason": "empty symbol"},
            (time.perf_counter() - started) * 1000.0,
            degraded=True,
            error_code="signal_invalid",
            reason="signal symbol 为空",
        )

    # ── 执行权校验（阶段四：同一标的单出口）──
    rights_conflict = _exec_rights.conflict(inst_id)
    if rights_conflict:
        return _wrap_paper(
            {"rejected": True, "signal_id": sig_id, "reason": rights_conflict},
            (time.perf_counter() - started) * 1000.0,
            degraded=True,
            error_code="execution_rights_conflict",
            reason=rights_conflict,
            extra_meta={"signal": sig},
        )

    # 3. 行情 + 定容
    ticker = _get_ticker(inst_id)
    if not ticker:
        return _wrap_paper(
            {"skipped": True, "reason": "no market data", "signal_id": sig_id},
            (time.perf_counter() - started) * 1000.0,
            degraded=True,
            error_code="market_unavailable",
            reason=f"no market data for {inst_id}",
        )
    mid = (ticker["bid"] + ticker["ask"]) / 2.0
    balance = _ledger.get_balance()["balance"]
    size = _signal_adapter.size_from_signal(sig, balance, mid, explicit_size)

    # 4. 风控（FAIL-CLOSED）
    risk_result = _risk_bridge.check(
        coin=_coin(inst_id),
        side=side,
        confidence=confidence,
        inst_id=inst_id,
        account_balance=balance,
        current_positions=_ledger.get_positions()["positions"],
    )
    if not risk_result.get("passed"):
        _emit_sample(
            "risk_rejected",
            {
                "signal_id": sig_id,
                "source": sig.get("source"),
                "inst_id": inst_id,
                "side": side,
                "size": size,
                "confidence": confidence,
                "reason_code": risk_result.get("reason_code"),
            },
        )
        return _wrap_paper(
            {
                "rejected": True,
                "signal_id": sig_id,
                "reason_code": risk_result.get("reason_code"),
                "message": risk_result.get("message"),
            },
            (time.perf_counter() - started) * 1000.0,
            degraded=True,
            error_code="risk_rejected",
            reason=f"风控拒绝: {risk_result.get('reason_code')}",
            extra_meta={"risk": risk_result, "signal": sig},
        )

    if not paper_execute:
        return _wrap_paper(
            {
                "paper_execute": False,
                "signal_id": sig_id,
                "symbol": inst_id,
                "side": side,
                "size": round(size, 8),
                "mid_px": round(mid, 8),
            },
            (time.perf_counter() - started) * 1000.0,
            extra_meta={"risk": risk_result, "signal": sig},
        )

    # 5. paper 撮合（OrderPort）
    if size <= 0:
        return _wrap_paper(
            {"skipped": True, "reason": "size calculated to 0", "signal_id": sig_id},
            (time.perf_counter() - started) * 1000.0,
            degraded=True,
            error_code="sizing_zero",
            reason="定容结果 0（hint=0 或余额为 0）",
        )
    result = _ledger.place_market_order(inst_id, side, size, "net")
    latency_ms = (time.perf_counter() - started) * 1000.0
    if not result.get("ok"):
        return _wrap_paper(
            {"signal_id": sig_id, "order_error": result.get("error")},
            latency_ms,
            degraded=True,
            error_code="order_rejected",
            reason=result.get("error", ""),
            extra_meta={"risk": risk_result, "signal": sig},
        )
    _ledger.mark_signal_executed(sig_id, result.get("ord_id", ""))
    _emit_sample(
        "order_filled",
        {
            "signal_id": sig_id,
            "source": sig.get("source"),
            "inst_id": inst_id,
            "side": side,
            "size": size,
            "confidence": confidence,
            "avg_px": result.get("avg_px"),
            "mid_px": result.get("mid_px"),
            "slippage_bps": result.get("slippage_bps"),
            "realized_pnl": result.get("realized_pnl"),
            "fee": result.get("fee"),
            "risk": risk_result,
        },
    )
    return _wrap_paper(
        {
            "signal_id": sig_id,
            "source": sig.get("source"),
            "shadow": sig.get("shadow"),
            "order": result,
        },
        latency_ms,
        result.get("slippage_bps", 0.0),
        extra_meta={"risk": risk_result, "signal": sig},
    )


TOOL_HANDLERS = {
    "place_order": _handle_place_order,
    "cancel_order": _handle_cancel_order,
    "get_positions": _handle_get_positions,
    "get_balance": _handle_get_balance,
    "pre_trade_check": _handle_pre_trade_check,
    "check_exit": _handle_check_exit,
    "get_account_mode": _handle_get_account_mode,
    "reconcile": _handle_reconcile,
    "read_signals": _handle_read_signals,
    "ingest_signal": _handle_ingest_signal,
}


# ── JSON-RPC 主处理 ────────────────────────────────────────
def _handle_request(req: Dict[str, Any]) -> Dict[str, Any]:
    method = req.get("method", "")
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req.get("id"),
            "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}},
        }
    if method == "tools/list":
        tools = [
            {
                "name": "place_order",
                "description": (
                    "Place a simulated (paper) order. "
                    "Only paper mode — does NOT touch real exchange. "
                    "Market orders fill instantly at OKX mid ± 5bps; "
                    "Limit orders cross when OKX mid crosses the price."
                ),
                "annotations": {"readOnlyHint": False, "destructiveHint": True},
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "symbol": {
                            "type": "string",
                            "description": "OKX instId, e.g. BTC-USDT-SWAP",
                        },
                        "side": {"type": "string", "enum": ["buy", "sell"]},
                        "order_type": {
                            "type": "string",
                            "enum": ["market", "limit"],
                            "default": "market",
                        },
                        "size": {"type": "number", "description": "contract size"},
                        "price": {"type": "number", "description": "required for limit orders"},
                        "pos_side": {
                            "type": "string",
                            "enum": ["long", "short", "net"],
                            "default": "net",
                        },
                    },
                    "required": ["symbol", "side", "size"],
                },
            },
            {
                "name": "cancel_order",
                "description": "Cancel a pending paper order by order_id.",
                "annotations": {"readOnlyHint": False, "destructiveHint": True},
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "order_id": {
                            "type": "string",
                            "description": "order_id returned by place_order",
                        },
                    },
                    "required": ["order_id"],
                },
            },
            {
                "name": "get_positions",
                "description": "Get current paper positions. mark_px uses live OKX ticker when available.",
                "annotations": {"readOnlyHint": True, "destructiveHint": False},
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string", "description": "optional: filter by instId"},
                    },
                },
            },
            {
                "name": "get_balance",
                "description": "Get paper account balance (balance / realized_pnl / fee_paid).",
                "annotations": {"readOnlyHint": True, "destructiveHint": False},
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "pre_trade_check",
                "description": (
                    "Run pre-trade risk check via 13-domain RiskEngine "
                    "(RiskCheckPort, SPEC §1.2). Fail-Closed: RiskEngine unavailable → rejected. "
                    "Returns risk pass/fail + reason_code + position_modifier + sizing suggestion."
                ),
                "annotations": {"readOnlyHint": True, "destructiveHint": False},
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string", "description": "OKX instId"},
                        "side": {"type": "string", "enum": ["buy", "sell"], "default": "buy"},
                        "confidence": {
                            "type": "number",
                            "description": "signal confidence 0-1",
                            "default": 0.5,
                        },
                    },
                    "required": ["symbol"],
                },
            },
            {
                "name": "check_exit",
                "description": (
                    "Evaluate exit decisions for paper positions via 13-domain ExitEngine "
                    "(ExitCheckPort, SPEC §1.2). Read-only advisory: returns action/reason/reduce_frac, "
                    "never places orders. FAIL-OPEN: engine unavailable → all HOLD + degraded."
                ),
                "annotations": {"readOnlyHint": True, "destructiveHint": False},
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "symbol": {
                            "type": "string",
                            "description": "OKX instId; omit to evaluate all paper positions",
                        }
                    },
                },
            },
            {
                "name": "get_account_mode",
                "description": "AccountPort.get_account_mode. Returns {mode, exchange, endpoints, risk_engine_available}.",
                "annotations": {"readOnlyHint": True, "destructiveHint": False},
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "reconcile",
                "description": (
                    "PositionPort.reconcile. Paper-only shell returns self-consistent report "
                    "(no real exchange to compare against). Live-mode reconciliation belongs to 11-domain."
                ),
                "annotations": {"readOnlyHint": True, "destructiveHint": False},
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "read_signals",
                "description": (
                    "Read latest signals from 23-evolution (event_driven_state.json) and "
                    "42-coordination (bus_state.json), normalized to a unified schema. "
                    "FAIL-OPEN: a broken source degrades only itself."
                ),
                "annotations": {"readOnlyHint": True, "destructiveHint": False},
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "sources": {
                            "type": "array",
                            "items": {"type": "string", "enum": ["23", "42"]},
                            "description": "signal sources, default ['23','42']",
                        },
                        "include_neutral": {"type": "boolean", "default": True},
                        "limit": {"type": "integer", "default": 20},
                    },
                },
            },
            {
                "name": "ingest_signal",
                "description": (
                    "Signal → full execution pipeline (RiskCheck → sizing → paper order), "
                    "with expiry check and signal_id idempotency. "
                    "Risk side is FAIL-CLOSED. This is the stage-3 entry for 23-domain signals."
                ),
                "annotations": {"readOnlyHint": False, "destructiveHint": True},
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "source": {
                            "type": "string",
                            "enum": ["inline", "23", "42"],
                            "default": "inline",
                            "description": "inline=use signal arg; 23/42=read latest from that source",
                        },
                        "signal": {
                            "type": "object",
                            "description": "inline signal (42 SignalSchema or simplified {symbol,direction,confidence})",
                        },
                        "size": {
                            "type": "number",
                            "description": "explicit size overriding sizing step",
                        },
                        "paper_execute": {"type": "boolean", "default": True},
                    },
                },
            },
        ]
        return {"jsonrpc": "2.0", "id": req.get("id"), "result": {"tools": tools}}
    if method == "tools/call":
        params = req.get("params", {})
        name = params.get("name", "")
        handler = TOOL_HANDLERS.get(name)
        if handler is None:
            return {
                "jsonrpc": "2.0",
                "id": req.get("id"),
                "error": {"code": -32601, "message": f"Method not found: {name}"},
            }
        started = time.perf_counter()
        result_text = handler(params.get("arguments", {}))
        observe_envelope(
            result_text,
            latency_ms=round((time.perf_counter() - started) * 1000.0, 3),
            action=name,
        )
        return {
            "jsonrpc": "2.0",
            "id": req.get("id"),
            "result": {"content": [{"type": "text", "text": result_text}], "isError": False},
        }
    return {
        "jsonrpc": "2.0",
        "id": req.get("id"),
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main() -> None:
    """stdio 主循环。"""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            sys.stdout.write(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32700, "message": "Parse error"},
                    }
                )
                + "\n"
            )
            sys.stdout.flush()
            continue
        resp = _handle_request(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
