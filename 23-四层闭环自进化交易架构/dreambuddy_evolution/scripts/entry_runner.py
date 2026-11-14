"""23 独立开仓 runner。

目标：23 的开仓链路不再依赖 11 主循环。
- 行情源：18-数据获取中心（data_center.compat.market_compat，ccxt 公共行情）
- 复盘/装配：23 DataPipelineAdapter（data_center.db 衍生数据 + 18 行情）
- 决策：23 KlineEventHandler → EvolutionPipeline → EvolutionEntryLoop
- 闸门数据：22 PositionLedger（LedgerGuards：持仓/冷静期/子池）
- 执行：22 TradeExecutionGateway（13 校验 + 审计 + 自动落账）

本模块不 import 任何 11 模块。
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

_HERE = Path(__file__).resolve().parents[2]  # 23-四层闭环自进化交易架构
_REPO = _HERE.parent
for _p in (
    _REPO / "22-执行引擎中心",
    _REPO / "22-执行引擎中心" / "executors",
    _HERE,
    _REPO / "18-数据获取中心",
):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from dreambuddy_evolution.adapters.data_pipeline import DataPipelineAdapter  # noqa: E402
from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler  # noqa: E402
from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline  # noqa: E402
from dreambuddy_evolution.execution.entry_loop import EvolutionEntryLoop  # noqa: E402
from dreambuddy_evolution.execution.ledger_guards import LedgerGuards  # noqa: E402

logger = logging.getLogger("entry23")

DATA_CENTER_DB = _REPO / "18-数据获取中心" / "data_center.db"
GENE_DATA_ROOT = _HERE / "dreambuddy_evolution" / "gene_data"
DEFAULT_SYMBOLS = ("BTC", "ETH", "SOL")
DEFAULT_EXEC_TAGS = ("23-evolution", "evolution", "event_arbitrage")

_STOP = False


def _on_signal(signum, _frame) -> None:
    global _STOP
    _STOP = True
    logger.info("收到信号 %s，准备退出", signum)


# ── 18 行情源 ─────────────────────────────────────────────────────────
class DataCenterMarketClient:
    """把 18 的统一行情接口包装成 23 适配器需要的 OKX 客户端形状。

    `OKXMarketAdapter` 只消费 `get_kline` / `get_ticker`；其余方法缺失时由
    适配器内部 FAIL-OPEN 降级，因此这里只实现行情只读部分。
    """

    def __init__(
        self,
        bar: str = "1H",
        candles_fn: Optional[Callable[..., List[dict]]] = None,
        ticker_fn: Optional[Callable[..., Optional[dict]]] = None,
        positions_fn: Optional[Callable[[], List[dict]]] = None,
    ) -> None:
        self._bar = bar
        self._candles_fn = candles_fn
        self._ticker_fn = ticker_fn
        self._positions_fn = positions_fn

    @staticmethod
    def to_ccxt_symbol(inst_id: str) -> str:
        _coin = str(inst_id or "").upper().replace("-USDT-SWAP", "").split("-")[0]
        return f"{_coin}/USDT:USDT"

    def _fetch_candles(self, symbol: str, bar: str, limit: int) -> List[dict]:
        if self._candles_fn is not None:
            return self._candles_fn(symbol, bar=bar, limit=limit)
        from data_center.compat.market_compat import fetch_candles

        return fetch_candles(symbol, bar, limit)

    def _fetch_ticker(self, symbol: str) -> Optional[dict]:
        if self._ticker_fn is not None:
            return self._ticker_fn(symbol)
        from data_center.compat.market_compat import fetch_ticker

        return fetch_ticker(symbol)

    def get_kline(self, inst_id: str, bar: str | None = None, limit: int = 200) -> Dict[str, Any]:
        _sym = self.to_ccxt_symbol(inst_id)
        try:
            candles = self._fetch_candles(_sym, bar or self._bar, int(limit))
        except Exception as exc:  # noqa: BLE001 — 行情失败由适配器 FAIL-OPEN
            logger.warning("%s 18 行情获取失败: %s", inst_id, exc)
            return {"ok": False, "error": str(exc)}
        if not candles:
            return {"ok": False, "error": "data_center_empty"}
        # 18 返回升序（旧→新）；OKXMarketAdapter 约定降序（新→旧）
        return {"ok": True, "candles": list(reversed(candles))}

    def get_ticker(self, inst_id: str) -> Dict[str, Any]:
        _sym = self.to_ccxt_symbol(inst_id)
        try:
            data = self._fetch_ticker(_sym) or {}
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s 18 ticker 获取失败: %s", inst_id, exc)
            return {"ok": False, "error": str(exc)}
        _last = float(data.get("last") or 0.0)
        if _last <= 0:
            return {"ok": False, "error": "no_last"}
        # 公共行情无盘口，用最新价填充 bid/ask（价差=0，不影响下单）
        return {"ok": True, "last": _last, "bid": _last, "ask": _last}

    def get_positions(self, inst_id: str | None = None) -> Dict[str, Any]:
        """持仓真相在 22 账本，按 OKX 形状回放给 23 适配器。"""
        if self._positions_fn is None:
            return {"ok": False, "error": "no_positions_source"}
        try:
            rows = self._positions_fn() or []
        except Exception as exc:  # noqa: BLE001 — 持仓维度 FAIL-OPEN
            logger.warning("22 账本持仓查询失败: %s", exc)
            return {"ok": False, "error": str(exc)}
        _out = []
        for _r in rows:
            _iid = str(_r.get("inst_id") or "")
            if inst_id and _iid.upper() != str(inst_id).upper():
                continue
            _qty = float(_r.get("qty") or 0.0)
            if _qty <= 0:
                continue
            _out.append(
                {
                    "inst_id": _iid,
                    "pos": _qty,
                    "pos_side": str(_r.get("pos_side") or "long").lower(),
                    "avg_px": float(_r.get("avg_entry") or 0.0),
                }
            )
        return {"ok": True, "positions": _out}


# ── 22 账户/合约辅助 ──────────────────────────────────────────────────
def _equity(okx: Any) -> float:
    try:
        _bal = okx.get_balance() or {}
        for _k in ("total_eq", "adj_eq", "iso_eq"):
            _v = float(_bal.get(_k) or 0.0)
            if _v > 0:
                return _v
    except Exception as exc:  # noqa: BLE001
        logger.warning("权益查询失败(用 100 兜底): %s", exc)
    return 100.0


def _min_sz(okx: Any, inst_id: str) -> float:
    fn = getattr(okx, "get_instrument", None)
    if not callable(fn):
        return 0.0
    try:
        info = fn(inst_id) or {}
        if info.get("ok"):
            return float(info.get("min_sz") or info.get("lot_sz") or 0.0)
    except Exception as exc:  # noqa: BLE001
        logger.debug("%s 最小下单量查询失败: %s", inst_id, exc)
    return 0.0


# ── 主流程 ────────────────────────────────────────────────────────────
class EntryRunner:
    """KlineEventHandler → EvolutionEntryLoop → 22 网关。"""

    def __init__(
        self,
        adapter: Any,
        handler: Any,
        loop: EvolutionEntryLoop,
        symbols: List[str],
        bar: str = "1H",
    ) -> None:
        self._adapter = adapter
        self._handler = handler
        self._loop = loop
        self._symbols = [s.strip().upper() for s in symbols if s and s.strip()]
        self._bar = bar
        self._klines: Dict[str, Dict[str, Any]] = {}
        if getattr(handler, "_build_position_callback", None) is None:
            handler._build_position_callback = self.on_signal

    def on_signal(
        self,
        symbol: str,
        action: str,
        u_open: float,
        d_star: str,
        confidence: float,
        tier: str = "standard",
        source_tag: Optional[str] = None,
        cbr_sim: float = 0.5,
        signal: Optional[dict] = None,
    ) -> Dict[str, Any]:
        """建仓回调：把 23 决策交给 23 自己的闸门/定容/22 下单。"""
        _coin = str(symbol or "").upper().replace("-USDT-SWAP", "")
        _kline = self._klines.get(_coin) or {}
        return self._loop.run(
            symbol=_coin,
            action=action,
            u_open=u_open,
            d_star=d_star,
            confidence=confidence,
            tier=tier,
            source_tag=source_tag,
            cbr_sim=cbr_sim,
            signal=signal,
            kline=_kline,
        )

    def assemble(self, coin: str) -> Dict[str, Any]:
        _inst = f"{coin}-USDT-SWAP"
        kline_data = self._adapter.assemble(symbol=coin, inst_id=_inst)
        if not isinstance(kline_data, dict):
            kline_data = {}
        kline_data["symbol"] = coin
        return kline_data

    def run_once(self) -> Dict[str, Any]:
        _opened = _blocked = _waited = _failed = 0
        for _coin in self._symbols:
            try:
                kline_data = self.assemble(_coin)
                _close = kline_data.get("close")
                if _close is None or len(_close) < 20:
                    logger.warning("%s 行情不足（close 缺失或 <20 根），跳过", _coin)
                    _failed += 1
                    continue
                self._klines[_coin] = kline_data
                result = self._handler.on_kline_close(kline_data, alpha=0.1, beta=0.2, gamma=0.2)
            except Exception as exc:  # noqa: BLE001 — 单币失败不影响其他币
                logger.exception("%s 开仓巡检异常(FAIL-OPEN): %s", _coin, exc)
                _failed += 1
                continue

            _action = str((result or {}).get("action") or "WAIT")
            if _action in ("long", "short"):
                _opened += 1
            else:
                _waited += 1
            logger.info(
                "%s action=%s d_star=%s ri=%.3f tier=%s auto_execute=%s",
                _coin,
                _action,
                (result or {}).get("d_star"),
                float((result or {}).get("ri") or 0.0),
                (result or {}).get("tier"),
                (result or {}).get("auto_execute"),
            )
        logger.info(
            "巡检完成 symbols=%s signal=%s wait=%s failed=%s",
            len(self._symbols),
            _opened,
            _waited,
            _failed,
        )
        return {
            "symbols": len(self._symbols),
            "signal": _opened,
            "wait": _waited,
            "failed": _failed,
            "blocked": _blocked,
        }


def _authority(dry_run: bool, tags: tuple[str, ...]) -> Callable[[str], bool]:
    """执行权闸门：dry-run / 全局开关 off 一律拦截；live 仅放行白名单标签。"""
    _allow = {t.lower() for t in tags}

    def _fn(tag: str) -> bool:
        _enabled = str(os.getenv("EVOLUTION_ENTRY23_ENABLED", "on")).strip().lower()
        return (
            (not dry_run)
            and _enabled not in ("0", "off", "false", "no")
            and str(tag or "").lower() in _allow
        )

    return _fn


def build_runtime(dry_run: bool, symbols: List[str], bar: str = "1H"):
    """构造 18 行情 + 23 管线 + 22 执行栈。"""
    from credentials import load_okx_config  # 22/executors/credentials.py
    from executors.okx_client import OKXSimulatedClient
    from trade_execution_gateway import TradeExecutionGateway

    cfg = load_okx_config()
    if not cfg or not cfg.get("api_key"):
        raise RuntimeError("缺少 OKX 凭证（22 credentials.load_okx_config 为空）")

    raw = OKXSimulatedClient(cfg)
    gateway = TradeExecutionGateway(okx_client=raw, shadow_only=bool(dry_run))
    guards = LedgerGuards(gateway)
    market = DataCenterMarketClient(bar=bar, positions_fn=gateway.list_positions)
    adapter = DataPipelineAdapter(
        okx_client=market,
        trader=None,
        data_center_db=str(DATA_CENTER_DB),
        gene_data_root=str(GENE_DATA_ROOT),
    )

    tags = tuple(
        t.strip().lower()
        for t in str(os.getenv("EVOLUTION_EXEC_TAGS", ",".join(DEFAULT_EXEC_TAGS))).split(",")
        if t.strip()
    )

    loop = EvolutionEntryLoop(
        gateway=gateway,
        authority_fn=_authority(dry_run, tags),
        has_position_fn=guards.has_position,
        cooldown_fn=guards.cooldown,
        subpool_fn=guards.subpool,
        track_mult_fn=lambda kd: adapter.get_ftc_track_multiplier(
            (kd or {}).get("top_ftc_track", "exploit")
        ),
        equity_fn=lambda: _equity(raw),
        min_sz_fn=lambda inst_id: _min_sz(raw, inst_id),
        price_fn=lambda inst_id: float(market.get_ticker(inst_id).get("last") or 0.0),
    )

    handler = KlineEventHandler(
        mode="Phase2",
        build_position_callback=None,
        project_root=str(_REPO),
        pipeline=EvolutionPipeline(),
    )
    runner = EntryRunner(adapter=adapter, handler=handler, loop=loop, symbols=symbols, bar=bar)
    return runner, gateway, adapter


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="23 独立开仓 runner")
    parser.add_argument(
        "--symbols",
        default=",".join(DEFAULT_SYMBOLS),
        help="逗号分隔币种（不含 -USDT-SWAP）",
    )
    parser.add_argument("--bar", default="1H", help="K 线周期")
    parser.add_argument("--interval", type=int, default=300, help="巡检间隔秒")
    parser.add_argument("--once", action="store_true", help="只跑一轮")
    parser.add_argument("--dry-run", action="store_true", help="影子模式：只产出决策不执行")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)
    _symbols = [s.strip().upper() for s in str(args.symbols).split(",") if s.strip()]

    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    try:
        runner, _gateway, _adapter = build_runtime(args.dry_run, _symbols, args.bar)
    except Exception as exc:  # noqa: BLE001
        logger.error("运行时构造失败: %s", exc)
        return 2

    while not _STOP:
        try:
            runner.run_once()
        except Exception as exc:  # noqa: BLE001 — 单轮失败不影响下一轮
            logger.exception("巡检异常(FAIL-OPEN): %s", exc)
        if args.once:
            break
        for _ in range(max(1, args.interval)):
            if _STOP:
                break
            time.sleep(1)
    logger.info("entry runner 退出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
