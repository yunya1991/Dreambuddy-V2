"""23 独立离场 runner（P3）。

目标：23 的持仓巡检不再依赖 11 主循环。
- 持仓真相：22 PositionLedger（source 归属 23）；显式 --symbols 可补老仓
- 上下文：交易所行情/挂单 + 22 只读接口，不 import 任何 11 模块
- 执行：22 TradeExecutionGateway（13 校验 + 审计 + 自动落账）
- 部署：deploy/dreambuddy-exit23.service，切换前 11 的 23 巡检需先关闭
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

_HERE = Path(__file__).resolve().parents[2]  # 23-四层闭环自进化交易架构
_REPO = _HERE.parent
for _p in (
    _REPO / "22-执行引擎中心",
    _REPO / "22-执行引擎中心" / "executors",
    _HERE,
):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from dreambuddy_evolution.execution.exit_loop import EvolutionExitLoop  # noqa: E402
from dreambuddy_evolution.execution.tracker_sync import (  # noqa: E402
    archive_closed_position,
)

logger = logging.getLogger("exit23")

DEFAULT_TAGS = ("evolution", "23-evolution", "23", "bcrm", "strategy", "event_arbitrage")
_STOP = False


def _on_signal(signum, _frame) -> None:
    global _STOP
    _STOP = True
    logger.info("收到信号 %s，准备退出", signum)


# ── 持仓归属 ──────────────────────────────────────────────────────────
def tag_matches(source: str, tags: Iterable[str]) -> bool:
    _s = str(source or "").lower()
    if not _s:
        return False
    return any(_s == t.lower() or _s.startswith(t.lower()) for t in tags)


def collect_positions(
    gateway: Any, okx: Any, symbols: List[str], tags: Iterable[str]
) -> List[Dict[str, Any]]:
    """账本归属优先；--symbols 用于补录 P2 之前开的老仓。"""
    _want = {s.strip().upper() for s in symbols if s and s.strip()}
    out: List[Dict[str, Any]] = []
    _seen = set()

    for row in gateway.list_positions() or []:
        _inst = str(row.get("inst_id") or "")
        if not _inst:
            continue
        if (_inst.upper() in _want) or tag_matches(row.get("source"), tags):
            _seen.add(_inst)
            out.append(
                {
                    "inst_id": _inst,
                    "coin": _inst.split("-")[0].upper(),
                    "pos_side": row.get("pos_side"),
                    "entry_price": float(row.get("avg_entry") or 0.0),
                    "position_qty": float(row.get("qty") or 0.0),
                    "entry_time": row.get("opened_at"),
                    "source_tag": row.get("source") or "ledger",
                }
            )

    for _inst in _want - _seen:
        _pos = _position_from_exchange(okx, _inst)
        if _pos:
            out.append(_pos)
            logger.warning("%s 不在 22 账本中，按 --symbols 从交易所补录（均价可能不准）", _inst)

    return out


def _position_from_exchange(okx: Any, inst_id: str) -> Optional[Dict[str, Any]]:
    fn = getattr(okx, "get_positions", None)
    if not callable(fn):
        return None
    try:
        data = fn(inst_id) or {}
        for p in data.get("positions") or []:
            _qty = float(p.get("pos") or 0.0)
            if _qty <= 0:
                continue
            return {
                "inst_id": inst_id,
                "coin": inst_id.split("-")[0].upper(),
                "pos_side": str(p.get("pos_side") or "long").lower(),
                "entry_price": float(p.get("avg_px") or p.get("avgPx") or 0.0),
                "position_qty": _qty,
                "source_tag": "exchange",
            }
    except Exception as exc:  # noqa: BLE001
        logger.warning("%s 持仓查询失败: %s", inst_id, exc)
    return None


# ── 上下文组装 ────────────────────────────────────────────────────────
def _atr_pct(okx: Any, inst_id: str, period: int = 14) -> float:
    """Wilder ATR / 最新收盘，返回小数（0.025 = 2.5%）。失败返 0。"""
    fn = getattr(okx, "get_kline", None)
    if not callable(fn):
        return 0.0
    try:
        data = fn(inst_id, bar="1H", limit=period * 4) or {}
        rows = data.get("candles") or []
        if len(rows) < period + 2:
            return 0.0
        # OKX K 线倒序（最新在前），转正序后按 Wilder 平滑
        rows = list(reversed(rows))
        _highs = [float(r["h"]) for r in rows]
        _lows = [float(r["l"]) for r in rows]
        _closes = [float(r["c"]) for r in rows]
        _trs = []
        for i in range(1, len(rows)):
            _trs.append(
                max(
                    _highs[i] - _lows[i],
                    abs(_highs[i] - _closes[i - 1]),
                    abs(_lows[i] - _closes[i - 1]),
                )
            )
        _atr = sum(_trs[:period]) / period
        for tr in _trs[period:]:
            _atr = (_atr * (period - 1) + tr) / period
        _last = _closes[-1]
        return _atr / _last if _last > 0 else 0.0
    except Exception as exc:  # noqa: BLE001
        logger.debug("%s ATR 计算失败: %s", inst_id, exc)
        return 0.0


def _pending_sl_tp(okx: Any, inst_id: str) -> tuple:
    fn = getattr(okx, "get_algo_orders", None)
    if not callable(fn):
        return 0.0, 0.0
    try:
        data = fn(inst_id) or {}
        _sl = _tp = 0.0
        for o in data.get("orders") or []:
            if str(o.get("state") or "").lower() in ("canceled", "filled", "failed"):
                continue
            _sl_px = float(o.get("sl_trigger_px") or 0.0)
            _tp_px = float(o.get("tp_trigger_px") or 0.0)
            if _sl_px > 0:
                _sl = _sl_px if _sl <= 0 else min(_sl, _sl_px)
            if _tp_px > 0:
                _tp = _tp_px if _tp <= 0 else max(_tp, _tp_px)
            if _sl_px <= 0 and _tp_px <= 0:
                # 单腿条件单：用 trigger_px 兜底，按 ordType/side 归类
                _trigger = float(o.get("trigger_px") or 0.0)
                if _trigger > 0 and "tp" in str(o.get("ord_type") or "").lower():
                    _tp = _trigger
                elif _trigger > 0 and _sl <= 0:
                    _sl = _trigger
        return _sl, _tp
    except Exception as exc:  # noqa: BLE001
        logger.debug("%s 挂单查询失败: %s", inst_id, exc)
        return 0.0, 0.0


def build_ctx(pos: Dict[str, Any], okx: Any, ess: float = 0.5) -> Dict[str, Any]:
    inst_id = str(pos["inst_id"])
    entry = float(pos.get("entry_price") or 0.0)
    pos_side = str(pos.get("pos_side") or "long").lower()
    price = 0.0
    fn = getattr(okx, "get_ticker", None)
    if callable(fn):
        try:
            _t = fn(inst_id) or {}
            price = float(_t.get("last") or _t.get("last_px") or 0.0)
        except Exception:  # noqa: BLE001
            price = 0.0
    if price <= 0:
        price = entry
    upl = (price - entry) / entry if pos_side == "long" else (entry - price) / entry
    _sl, _tp = _pending_sl_tp(okx, inst_id)
    _qty = float(pos.get("position_qty") or 0.0)
    return {
        "symbol": inst_id,
        "pos_side": pos_side,
        "tier": str(pos.get("tier") or "standard"),
        "position_age_sec": _age_sec(pos.get("entry_time")),
        "upl_ratio": upl if entry > 0 else 0.0,
        "current_price": price,
        "entry_price": entry,
        "position_qty": _qty,
        "position_usdt": _qty * price,
        "ess": ess,
        "r_vector": {},
        "current_sl_px": _sl,
        "current_tp_px": _tp,
        "atr_pct": _atr_pct(okx, inst_id),
        "source_tag": pos.get("source_tag") or "23-evolution",
    }


def _age_sec(entry_time: Any) -> float:
    if not entry_time:
        return 0.0
    try:
        from datetime import datetime, timezone

        _s = str(entry_time).replace("Z", "+00:00")
        _dt = datetime.fromisoformat(_s)
        if _dt.tzinfo is None:
            _dt = _dt.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - _dt).total_seconds())
    except Exception:  # noqa: BLE001
        return 0.0


# ── 主流程 ────────────────────────────────────────────────────────────
def run_once(loop: EvolutionExitLoop, gateway: Any, okx: Any, args) -> Dict[str, Any]:
    positions = collect_positions(gateway, okx, args.symbols, args.tags)
    if not positions:
        logger.info("无归属 23 的持仓，本轮跳过")
        return {"checked": 0, "hold": 0, "executed": [], "failed": [], "skipped": 0}

    def _enrich(pos: Dict[str, Any], _ctx: Dict[str, Any]) -> Dict[str, Any]:
        _base = build_ctx(pos, okx)
        _base.update({k: v for k, v in _ctx.items() if v not in (None, 0, 0.0)})
        return _base

    def _on_closed(pos, decision, ctx, sig) -> None:
        inst_id = str(pos.get("inst_id") or getattr(decision, "symbol", "") or "")
        logger.info(
            "平仓完成 %s %s %s",
            inst_id,
            getattr(decision, "action", ""),
            getattr(decision, "reason", ""),
        )
        # 22 账本已自动落平仓 + 冷却；这里只清 11 侧幽灵文件（数据级，失败不影响交易）
        try:
            archive_closed_position(inst_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("持仓文件归档失败(FAIL-OPEN) %s: %s", inst_id, exc)

    report = loop.run(
        positions,
        enricher=_enrich,
        on_closed=_on_closed,
        on_ghost=lambda pos, px: logger.warning("幽灵仓 %s 落账价 %.6f", pos.get("inst_id"), px),
    )
    logger.info(
        "巡检完成 checked=%s hold=%s executed=%s failed=%s",
        report.get("checked"),
        report.get("hold"),
        len(report.get("executed") or []),
        len(report.get("failed") or []),
    )
    return report


def build_runtime(dry_run: bool):
    """构造 22 执行栈。生产必须拿到凭证；dry-run 仅影子校验不落单。"""
    from credentials import load_okx_config  # 22/executors/credentials.py
    from executors.domain_clients import DomainTaggedOkxClient
    from executors.okx_client import OKXSimulatedClient
    from trade_execution_gateway import TradeExecutionGateway

    cfg = load_okx_config()
    if not cfg or not cfg.get("api_key"):
        raise RuntimeError("缺少 OKX 凭证（22 credentials.load_okx_config 为空）")
    raw = OKXSimulatedClient(cfg)
    # 网关持 raw（避免 tagged 与 gateway 互相回调成环），23 写操作由 tagged 提交网关
    gateway = TradeExecutionGateway(okx_client=raw, shadow_only=bool(dry_run))
    tagged = DomainTaggedOkxClient(raw, None, gateway=gateway)
    loop = EvolutionExitLoop(gateway=gateway, okx_client=tagged)
    return loop, gateway, tagged


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="23 独立离场 runner")
    parser.add_argument("--symbols", default="", help="逗号分隔，补录不在 22 账本中的老仓")
    parser.add_argument(
        "--tags",
        default=",".join(DEFAULT_TAGS),
        help="账本 source 归属前缀（逗号分隔）",
    )
    parser.add_argument("--interval", type=int, default=60, help="巡检间隔秒")
    parser.add_argument("--once", action="store_true", help="只跑一轮")
    parser.add_argument("--dry-run", action="store_true", help="只读影子校验，不执行")
    parser.add_argument(
        "--reconcile-ledger",
        action="store_true",
        help="一次性存量仓对账回填到 22 账本（幂等，不下单）",
    )
    parser.add_argument("--reconcile-source", default="22-reconciled", help="回填来源标签")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)
    args.symbols = [s for s in str(args.symbols).split(",") if s.strip()]
    args.tags = [t for t in str(args.tags).split(",") if t.strip()]

    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    if args.reconcile_ledger:
        try:
            _loop, gateway, _okx = build_runtime(dry_run=True)
            out = gateway.reconcile_ledger(source=args.reconcile_source)
        except Exception as exc:  # noqa: BLE001
            logger.error("账本对账失败: %s", exc)
            return 2
        logger.info(
            "对账回填完成 inserted=%s skipped=%s",
            out.get("inserted"),
            out.get("skipped"),
        )
        return 0 if out.get("ok") else 1

    try:
        loop, gateway, okx = build_runtime(args.dry_run)
    except Exception as exc:  # noqa: BLE001
        logger.error("运行时构造失败: %s", exc)
        return 2

    while not _STOP:
        try:
            run_once(loop, gateway, okx, args)
        except Exception as exc:  # noqa: BLE001 — 单轮失败不影响下一轮
            logger.exception("巡检异常(FAIL-OPEN): %s", exc)
        if args.once:
            break
        for _ in range(max(1, args.interval)):
            if _STOP:
                break
            time.sleep(1)
    logger.info("exit runner 退出")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
