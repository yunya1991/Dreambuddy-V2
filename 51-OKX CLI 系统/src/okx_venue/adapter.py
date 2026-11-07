"""OKX CLI venue adapter implementing the market/account/order ports."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .config import VenueConfig
from .errors import VenueError
from .runner import CliRunner


def _as_list(payload: Any) -> List[Any]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return data
        return [payload]
    return [payload]


def _first(payload: Any) -> Dict[str, Any]:
    items = _as_list(payload)
    if not items:
        return {}
    first = items[0]
    return first if isinstance(first, dict) else {}


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _fmt(value: float) -> str:
    return f"{float(value):.12g}"


def _is_swap(inst_id: str) -> bool:
    return inst_id.upper().endswith("-SWAP")


class OkxCliVenue:
    """Port implementation backed by the `okx` CLI.

    Reads are allowed in demo mode (and in live mode only with an explicit
    flag). Writes are demo-only; live writes always raise.
    """

    def __init__(
        self,
        config: Optional[VenueConfig] = None,
        runner: Optional[CliRunner] = None,
    ) -> None:
        self.config = config or VenueConfig.from_env()
        self.runner = runner or CliRunner(self.config)

    # ── MarketPort ──────────────────────────────────────────────
    def get_ticker(self, inst_id: str) -> Dict[str, Any]:
        payload = self.runner.run(
            ["market", "ticker", inst_id], operation="get_ticker"
        )
        ticker = _first(payload)
        return {
            "ok": True,
            "inst_id": ticker.get("instId", inst_id),
            "last": _float(ticker.get("last")),
            "bid": _float(ticker.get("bidPx")),
            "ask": _float(ticker.get("askPx")),
            "bid_px": _float(ticker.get("bidPx")),
            "ask_px": _float(ticker.get("askPx")),
            "open24h": _float(ticker.get("open24h")),
            "high24h": _float(ticker.get("high24h")),
            "low24h": _float(ticker.get("low24h")),
            "vol24h": _float(ticker.get("vol24h")),
            "ts": ticker.get("ts"),
            "raw": ticker,
        }

    def get_candles(
        self, inst_id: str, bar: str = "1H", limit: int = 100
    ) -> Dict[str, Any]:
        if limit <= 0:
            raise VenueError("limit must be > 0", code="invalid_argument")
        payload = self.runner.run(
            [
                "market",
                "candles",
                inst_id,
                "--bar",
                bar,
                "--limit",
                str(int(limit)),
            ],
            operation="get_candles",
        )
        return {"ok": True, "candles": _as_list(payload), "raw": payload}

    # ── AccountPort ─────────────────────────────────────────────
    def get_balance(self, ccy: Optional[str] = None) -> Dict[str, Any]:
        argv: List[str] = ["account", "balance"]
        if ccy:
            argv.append(ccy)
        payload = self.runner.run(argv, operation="get_balance")
        account = _first(payload)
        details = account.get("details") or []
        wanted = (ccy or "USDT").upper()
        selected = next(
            (item for item in details if str(item.get("ccy", "")).upper() == wanted),
            {},
        )
        available = (
            _float(selected.get("availBal"))
            or _float(selected.get("availEq"))
            or _float(selected.get("cashBal"))
            or _float(account.get("totalEq"))
        )
        return {
            "ok": True,
            "balance": available,
            "total_eq": _float(account.get("totalEq")),
            "ccy": wanted,
            "details": details,
            "raw": account,
        }

    def get_positions(self, inst_id: Optional[str] = None) -> Dict[str, Any]:
        argv: List[str] = ["account", "positions"]
        if inst_id:
            argv.extend(["--instId", inst_id])
        payload = self.runner.run(argv, operation="get_positions")
        positions: List[Dict[str, Any]] = []
        for item in _as_list(payload):
            if not isinstance(item, dict):
                continue
            raw_pos = _float(item.get("pos"))
            pos_side = str(item.get("posSide") or "").lower()
            if pos_side in {"", "net"}:
                pos_side = "long" if raw_pos >= 0 else "short"
            positions.append(
                {
                    "inst_id": item.get("instId"),
                    "coin": str(item.get("instId", "")).split("-")[0],
                    "pos_side": pos_side,
                    "side": "long" if pos_side == "long" else "short",
                    "pos": abs(raw_pos),
                    "avg_px": _float(item.get("avgPx")),
                    "mark_px": _float(item.get("markPx")),
                    "upl": _float(item.get("upl")),
                    "raw": item,
                }
            )
        return {"ok": True, "positions": positions, "count": len(positions)}

    # ── OrderPort（demo only）───────────────────────────────────
    def place_order(
        self,
        inst_id: str,
        side: str,
        size: float,
        *,
        order_type: str = "market",
        price: Optional[float] = None,
        td_mode: Optional[str] = None,
        pos_side: Optional[str] = None,
    ) -> Dict[str, Any]:
        side = side.strip().lower()
        order_type = order_type.strip().lower()
        if side not in {"buy", "sell"}:
            raise VenueError(f"side must be buy|sell, got {side!r}", code="invalid_argument")
        if size <= 0:
            raise VenueError(f"size must be > 0, got {size!r}", code="invalid_argument")
        if order_type not in {"market", "limit"}:
            raise VenueError(
                f"order_type must be market|limit, got {order_type!r}",
                code="invalid_argument",
            )
        if order_type == "limit" and price is None:
            raise VenueError("price is required for limit orders", code="invalid_argument")

        market = "swap" if _is_swap(inst_id) else "spot"
        mode = td_mode or ("cross" if market == "swap" else "cash")
        argv: List[str] = [
            market,
            "place",
            "--instId",
            inst_id,
            "--side",
            side,
            "--ordType",
            order_type,
            "--sz",
            _fmt(size),
            "--tdMode",
            mode,
        ]
        if market == "swap" and pos_side and pos_side.lower() != "net":
            argv.extend(["--posSide", pos_side.lower()])
        if order_type == "limit" and price is not None:
            argv.extend(["--px", _fmt(price)])

        payload = self.runner.run(argv, operation="place_order", write=True)
        return self._normalize_order(payload)

    def cancel_order(
        self,
        inst_id: str,
        *,
        ord_id: Optional[str] = None,
        cl_ord_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not ord_id and not cl_ord_id:
            raise VenueError(
                "ord_id or cl_ord_id is required", code="invalid_argument"
            )
        market = "swap" if _is_swap(inst_id) else "spot"
        argv: List[str] = [market, "cancel", inst_id]
        if ord_id:
            argv.extend(["--ordId", ord_id])
        if cl_ord_id:
            argv.extend(["--clOrdId", cl_ord_id])
        payload = self.runner.run(argv, operation="cancel_order", write=True)
        return self._normalize_order(payload)

    def get_order(
        self,
        inst_id: str,
        *,
        ord_id: Optional[str] = None,
        cl_ord_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not ord_id and not cl_ord_id:
            raise VenueError(
                "ord_id or cl_ord_id is required", code="invalid_argument"
            )
        market = "swap" if _is_swap(inst_id) else "spot"
        argv: List[str] = [market, "get", "--instId", inst_id]
        if ord_id:
            argv.extend(["--ordId", ord_id])
        if cl_ord_id:
            argv.extend(["--clOrdId", cl_ord_id])
        payload = self.runner.run(argv, operation="get_order")
        return {"ok": True, "order": _first(payload), "raw": payload}

    # ── helpers ─────────────────────────────────────────────────
    @staticmethod
    def _normalize_order(payload: Any) -> Dict[str, Any]:
        item = _first(payload)
        s_code = str(item.get("sCode", "0"))
        ok = s_code == "0" and not item.get("error")
        return {
            "ok": ok,
            "order_id": item.get("ordId"),
            "cl_ord_id": item.get("clOrdId"),
            "s_code": s_code,
            "s_msg": item.get("sMsg", ""),
            "raw": item,
        }

    def describe(self) -> Dict[str, Any]:
        return {"config": self.config.describe()}


def build_adapter(
    config: Optional[VenueConfig] = None,
    *,
    runner: Optional[CliRunner] = None,
) -> OkxCliVenue:
    return OkxCliVenue(config=config, runner=runner)