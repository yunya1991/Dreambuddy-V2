"""离场算法逐笔重放回测（baseline vs fixed 对照）

用途
----
现有 `exit_backtest_runner.py` 只用 close 价判 SL/TP，且自己注入 r_multiple /
tp_decayed_pct（生产 enricher 并不注入），与实盘链路不同源。本脚本按生产语义重放：

1. 逐 1H K 线用 **high/low** 判交易所侧 SL/TP 触达（插针可成交）；
2. 每根 K 线收盘后调用 `EvolutionExitEngine.decide()`，等价于 5min 巡检的聚合；
3. 不注入 r_multiple / tp_decayed_pct（生产 enricher 不注入，规则4 因此不可达）；
4. 手续费 + 滑点双边计费；部分减仓按比例落账（生产侧不上账，这里按真实资金曲线算）；
5. 每笔交易使用独立引擎实例，隔离 `_peak_upl_ratio` 跨仓污染（该缺陷由单测覆盖，
   不进入本对照，避免把"状态泄漏"混入"离场规则"归因）。

入场信号为**占位**（每 12 根 K 线按 EMA48 斜率方向入场），只用于生成同分布离场样本，
不评估开仓 alpha。两种模式使用完全相同的入场、K 线、费率，差异仅来自离场决策。

输出：JSON（含逐笔明细 + 汇总指标 + SL 单调性计数）。

用法::

    python -m dreambuddy_evolution.scripts.exit_replay_backtest \
        --symbols BTC/USDT:USDT,ETH/USDT:USDT --days 90 --out /tmp/exit_bt_baseline.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parents[2]  # 23-四层闭环自进化交易架构
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from dreambuddy_evolution.engines.exit_engine import EvolutionExitEngine  # noqa: E402

CACHE_DIR = Path(os.getenv("EXIT_BT_CACHE", "/tmp/exit_bt_cache"))
TF_MS = {"1h": 3600_000, "4h": 4 * 3600_000}
ATR_PERIOD = 14
EMA_PERIOD = 48
ENTRY_STEP_BARS = 12  # 每 12 根 K 线生成一个入场样本
TP_PCT = 0.12  # 与 exit_engine.TIER_TP_PCT 一致
TIER = "standard"
ATR_MULT = {"probe": 4.0, "standard": 4.5, "trend": 5.0}
SL_FLOOR = 0.04
SL_CEIL = 0.15


# ── 数据 ──────────────────────────────────────────────────────────────
def fetch_klines(symbol: str, timeframe: str, days: int) -> List[List[float]]:
    """拉取并缓存 K 线（OKX 公共接口，只读）。返回 [[ts, o, h, l, c, v], ...]"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _key = symbol.replace("/", "_").replace(":", "_")
    _cache = CACHE_DIR / f"{_key}_{timeframe}_{days}d.json"
    if _cache.exists():
        return json.loads(_cache.read_text())

    import ccxt  # 延迟导入：缓存命中时不依赖 ccxt

    ex = ccxt.okx({"enableRateLimit": True})
    tf_ms = TF_MS[timeframe]
    since = int(time.time() * 1000) - days * 86400_000
    since = since // tf_ms * tf_ms
    out: List[List[float]] = []
    cursor = since
    while cursor < int(time.time() * 1000):
        batch = None
        for attempt in range(4):
            try:
                batch = ex.fetch_ohlcv(symbol, timeframe, since=cursor, limit=300)
                break
            except Exception as exc:  # noqa: BLE001 — 网络抖动重试
                if attempt == 3:
                    raise
                print(f"[retry {attempt + 1}] {symbol}: {exc}", file=sys.stderr)
                time.sleep(2.0 * (attempt + 1))
        if not batch:
            break
        out.extend(batch)
        nxt = batch[-1][0] + tf_ms
        if nxt <= cursor:
            break
        cursor = nxt
        if len(batch) < 300:
            break
    # 去重 + 排序
    _seen = {}
    for r in out:
        _seen[int(r[0])] = r
    rows = [list(_seen[k]) for k in sorted(_seen)]
    _cache.write_text(json.dumps(rows))
    return rows


def atr_series(rows: List[List[float]], period: int = ATR_PERIOD) -> List[float]:
    """Wilder ATR；前 period 根用 TR 均值填充。"""
    trs: List[float] = []
    out: List[float] = []
    for i, (_ts, _o, h, lo, _c, _v) in enumerate(rows):
        if i == 0:
            tr = h - lo
        else:
            pc = rows[i - 1][4]
            tr = max(h - lo, abs(h - pc), abs(lo - pc))
        trs.append(tr)
        if i < period:
            out.append(sum(trs) / len(trs))
        else:
            out.append((out[-1] * (period - 1) + tr) / period)
    return out


def ema_series(vals: List[float], period: int) -> List[float]:
    if not vals:
        return []
    k = 2.0 / (period + 1)
    out = [vals[0]]
    for v in vals[1:]:
        out.append(out[-1] + k * (v - out[-1]))
    return out


# ── 重放 ──────────────────────────────────────────────────────────────
class TradeReplay:
    """单笔交易重放。engine 每笔独立，避免状态跨仓污染干扰归因。"""

    def __init__(
        self,
        fee_rate: float,
        slip_rate: float,
        retrace: float | None = None,
        partial_tp: bool = True,
        breakeven: bool = True,
        tp_pct: float = TP_PCT,
        sl_mult: float | None = None,
        sl_floor: float = SL_FLOOR,
        trail_arm: float | None = None,
        legacy_path: str | None = None,
        tp_mult: float = 0.0,
        retrace_atr_mult: float = 0.0,
    ):
        self.fee = fee_rate
        self.slip = slip_rate
        self.round_trip_cost = 2.0 * (fee_rate + slip_rate)
        self.retrace = retrace
        self.partial_tp = partial_tp
        self.breakeven = breakeven
        self.tp_pct = tp_pct
        self.sl_mult = sl_mult
        self.sl_floor = sl_floor
        self.trail_arm = trail_arm
        self.legacy_path = legacy_path
        self.tp_mult = tp_mult
        self.retrace_atr_mult = retrace_atr_mult

    def _new_engine(self):
        """legacy 模式加载 git HEAD 的旧版引擎（忠实 baseline），否则用当前实现。"""
        if not self.legacy_path:
            return EvolutionExitEngine(log_fn=lambda m, lv="INFO": None)
        import importlib.util

        _spec = importlib.util.spec_from_file_location("legacy_exit_engine", self.legacy_path)
        _mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)  # type: ignore[union-attr]
        return _mod.EvolutionExitEngine(log_fn=lambda m, lv="INFO": None)

    def run(
        self,
        symbol: str,
        side: str,
        entry_i: int,
        rows: List[List[float]],
        atrs: List[float],
        entry_px: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        if entry_i >= len(rows) - 1:
            return None
        entry_px = float(entry_px or rows[entry_i][4])
        if entry_px <= 0:
            return None
        entry_ts = float(rows[entry_i][0])
        _atr_pct = max(0.0, atrs[entry_i] / entry_px)
        _mult = self.sl_mult if self.sl_mult is not None else ATR_MULT[TIER]
        sl_pct = min(SL_CEIL, max(self.sl_floor, _mult * _atr_pct))
        # 生产口径（polling_trader L12229）：TP = max(SL×3, 12%)，上限 30%
        _tp_pct = min(0.30, max(self.tp_mult * sl_pct, 0.12)) if self.tp_mult > 0 else self.tp_pct
        if side == "long":
            cur_sl = entry_px * (1 - sl_pct)
            cur_tp = entry_px * (1 + _tp_pct)
        else:
            cur_sl = entry_px * (1 + sl_pct)
            cur_tp = entry_px * (1 - _tp_pct)

        engine = self._new_engine()
        # 消融开关（仅回测用，不改生产默认）
        if self.retrace_atr_mult > 0:
            # 直接走生产 Chandelier 路径：回撤 = clamp(倍数 × ATR%, 3%, 20%)
            engine.strategy_params.trailing_atr_mult = float(self.retrace_atr_mult)
        if self.retrace is not None:
            # 固定回撤消融：关闭 ATR 缩放，强制用固定百分比
            engine.strategy_params.trailing_atr_mult = 0.0
            engine.strategy_params.trailing_retrace_pct = float(self.retrace)
        if not self.partial_tp:
            engine.PARTIAL_TP_R_THRESHOLDS = []
            engine.PARTIAL_TP_PCTAGES = []
        if not self.breakeven:
            engine.BREAK_EVEN_ARM_PCT = 9.99
        if self.trail_arm is not None:
            engine.TRAILING_ARM_PCT = {
                "probe": self.trail_arm,
                "standard": self.trail_arm,
                "trend": self.trail_arm,
            }
        remaining = 1.0
        realized = 0.0
        peak_fav = entry_px
        worst_adv = entry_px
        exit_reason = "kline_exhausted"
        exit_ts = float(rows[-1][0])
        hold_bars = 0
        sl_raises = 0
        sl_lowers = 0
        decisions = 0
        last_px = entry_px

        for i in range(entry_i + 1, len(rows)):
            ts, op, h, lo, c, _v = rows[i]
            age = (float(ts) - entry_ts) / 1000.0
            hold_bars = i - entry_i
            # 1) 交易所侧 SL/TP 触达（用 high/low；跳空按 open 成交）
            hit = self._check_sl_tp(side, op, h, lo, cur_sl, cur_tp)
            if hit is not None:
                px, exit_reason = hit
                realized += remaining * self._ret(side, entry_px, px)
                exit_ts = float(ts)
                last_px = px
                remaining = 0.0
                break

            # 2) 记录 MFE / MAE（含影线）
            fav = h if side == "long" else lo
            adv = lo if side == "long" else h
            peak_fav = max(peak_fav, fav) if side == "long" else min(peak_fav, fav)
            worst_adv = min(worst_adv, adv) if side == "long" else max(worst_adv, adv)

            # 3) 决策（生产 5min 巡检的 1H 聚合近似）
            upl = self._ret(side, entry_px, c)
            ctx = {
                "symbol": symbol,
                "pos_side": side,
                "entry_price": entry_px,
                "current_price": float(c),
                "upl_ratio": upl,
                "position_age_sec": age,
                "ess": 0.6,
                "r_vector": {},
                "tier": TIER,
                "atr_pct": _atr_pct,
                "current_sl_px": cur_sl,
                "current_tp_px": cur_tp,
                "okx_algo_triggered": False,
                "has_stronger_signal": False,
                "stronger_signal_info": None,
                "source_tag": "evolution",
                # 生产 enricher 不注入 r_multiple / tp_decayed_pct
            }
            decision = engine.decide(ctx)
            decisions += 1

            if decision.action == "force_close":
                realized += remaining * upl
                exit_reason = (
                    decision.reason.split(":")[1] if ":" in decision.reason else decision.reason
                )
                exit_ts = float(ts)
                last_px = float(c)
                remaining = 0.0
                break
            if decision.action == "partial_close":
                pct = float((decision.params or {}).get("partial_pct", 0.0) or 0.0)
                pct = max(0.0, min(1.0, pct))
                if pct > 0:
                    realized += remaining * pct * upl
                    remaining *= 1 - pct
                continue
            if decision.action in ("trailing", "adjust_sl_tp"):
                new_sl = float(decision.sl_px or 0.0)
                if new_sl > 0:
                    improved = new_sl > cur_sl if side == "long" else new_sl < cur_sl
                    worsened = new_sl < cur_sl if side == "long" else new_sl > cur_sl
                    if improved:
                        sl_raises += 1
                    elif worsened:
                        sl_lowers += 1
                    cur_sl = new_sl
            if remaining <= 1e-6:
                break

        if remaining > 1e-6:
            realized += remaining * self._ret(side, entry_px, last_px)

        # 扣费：按已平比例计（未平部分已在上面按 close 计入）
        cost = self.round_trip_cost
        pnl = realized - cost
        mfe = abs(peak_fav - entry_px) / entry_px
        mae = abs(worst_adv - entry_px) / entry_px
        return {
            "symbol": symbol,
            "side": side,
            "entry_ts": entry_ts,
            "exit_ts": exit_ts,
            "hold_hours": round(hold_bars, 2),
            "pnl_pct": pnl,
            "exit_reason": exit_reason,
            "mfe_pct": mfe,
            "mae_pct": mae,
            "capture": (pnl / mfe) if mfe > 1e-6 else None,
            "sl_raises": sl_raises,
            "sl_lowers": sl_lowers,
            "decisions": decisions,
        }

    @staticmethod
    def _ret(side: str, entry: float, px: float) -> float:
        return (px - entry) / entry if side == "long" else (entry - px) / entry

    @staticmethod
    def _check_sl_tp(
        side: str, op: float, h: float, lo: float, sl: float, tp: float
    ) -> Optional[Tuple[float, str]]:
        """先判不利方向（保守），跳空按 open 成交。"""
        if side == "long":
            if sl > 0 and lo <= sl:
                return (min(op, sl), "sl_hit")
            if tp > 0 and h >= tp:
                return (max(op, tp), "tp_hit")
        else:
            if sl > 0 and h >= sl:
                return (max(op, sl), "sl_hit")
            if tp > 0 and lo <= tp:
                return (min(op, tp), "tp_hit")
        return None


# ── 汇总 ──────────────────────────────────────────────────────────────
def summarize(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not trades:
        return {"n": 0}
    pnls = [t["pnl_pct"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    ordered = sorted(trades, key=lambda t: t["exit_ts"])
    equity = 1.0
    peak_eq = 1.0
    max_dd = 0.0
    curve = []
    for t in ordered:
        equity *= 1 + t["pnl_pct"]
        peak_eq = max(peak_eq, equity)
        max_dd = max(max_dd, (peak_eq - equity) / peak_eq)
        curve.append(round(equity, 6))
    gross_win = sum(wins)
    gross_loss = -sum(losses)
    reasons: Dict[str, int] = {}
    for t in trades:
        reasons[t["exit_reason"]] = reasons.get(t["exit_reason"], 0) + 1
    caps = [t["capture"] for t in trades if t.get("capture") is not None and t["mfe_pct"] > 0.01]
    # 利润回吐诊断：曾浮盈≥4% 却最终不赚钱的比例（P0-1 的直接症状指标）
    _gb = [t for t in trades if t["mfe_pct"] >= 0.04]
    _gb_lost = [t for t in _gb if t["pnl_pct"] <= 0]
    return {
        "n": len(trades),
        "win_rate": round(len(wins) / len(trades), 4),
        "avg_pnl_pct": round(sum(pnls) / len(pnls), 5),
        "median_pnl_pct": round(sorted(pnls)[len(pnls) // 2], 5),
        "sum_pnl_pct": round(sum(pnls), 3),
        "avg_win_pct": round(sum(wins) / len(wins), 5) if wins else 0.0,
        "avg_loss_pct": round(sum(losses) / len(losses), 5) if losses else 0.0,
        "profit_factor": round(gross_win / gross_loss, 3) if gross_loss > 0 else None,
        "expectancy_pct": round(sum(pnls) / len(pnls), 5),
        "compounded_return": round(equity - 1, 4),
        "max_drawdown": round(max_dd, 4),
        "avg_hold_hours": round(sum(t["hold_hours"] for t in trades) / len(trades), 2),
        "avg_mfe_pct": round(sum(t["mfe_pct"] for t in trades) / len(trades), 5),
        "avg_mae_pct": round(sum(t["mae_pct"] for t in trades) / len(trades), 5),
        "avg_capture_ratio": round(sum(caps) / len(caps), 4) if caps else None,
        "mfe4_n": len(_gb),
        "mfe4_giveback_n": len(_gb_lost),
        "mfe4_giveback_rate": round(len(_gb_lost) / len(_gb), 4) if _gb else None,
        "mfe4_avg_pnl": round(sum(t["pnl_pct"] for t in _gb) / len(_gb), 5) if _gb else None,
        "exit_reasons": dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
        "sl_raises": sum(t["sl_raises"] for t in trades),
        "sl_lowers": sum(t["sl_lowers"] for t in trades),
        "trades_with_sl_lower": sum(1 for t in trades if t["sl_lowers"] > 0),
        "avg_decisions_per_trade": round(sum(t["decisions"] for t in trades) / len(trades), 1),
    }


def build_samples(rows: List[List[float]], step: int = ENTRY_STEP_BARS):
    """占位入场：EMA48 斜率方向，每 step 根一个样本。"""
    closes = [r[4] for r in rows]
    ema = ema_series(closes, EMA_PERIOD)
    out = []
    for i in range(EMA_PERIOD + 1, len(rows) - 1, step):
        side = "long" if ema[i] >= ema[i - 1] else "short"
        out.append((side, i))
    return out


def load_real_entries(path: str) -> Dict[str, List[Tuple[str, float, float]]]:
    """加载真实策略入场记录 → {symbol: [(side, entry_ts_ms, entry_px), ...]}

    只取入场时刻/方向/入场价，离场完全由被对比的引擎决定，保证"纯离场 A/B"。
    """
    import datetime as _dt

    out: Dict[str, List[Tuple[str, float, float]]] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            coin = str(d.get("coin", "")).upper()
            side = str(d.get("direction", "")).lower()
            ts = d.get("entry_time")
            if not coin or side not in ("long", "short") or not ts:
                continue
            _ts = str(ts).replace("Z", "+00:00")
            try:
                ms = _dt.datetime.fromisoformat(_ts).timestamp() * 1000
            except ValueError:
                continue
            out.setdefault(f"{coin}/USDT:USDT", []).append(
                (side, ms, float(d.get("entry_price") or 0.0))
            )
    return out


def ts_to_index(rows: List[List[float]], ts_ms: float) -> Optional[int]:
    """入场时间戳 → K 线索引（落在该根 K 线内即视为该根入场）。"""
    import bisect

    stamps = [r[0] for r in rows]
    i = bisect.bisect_right(stamps, ts_ms) - 1
    if i < 0 or i >= len(rows) - 1:
        return None
    return i


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--symbols",
        default="BTC/USDT:USDT,ETH/USDT:USDT,SOL/USDT:USDT,DOGE/USDT:USDT,LINK/USDT:USDT,ARB/USDT:USDT",
    )
    ap.add_argument("--timeframe", default="1h", choices=list(TF_MS))
    ap.add_argument("--days", type=int, default=95)
    ap.add_argument("--fee", type=float, default=0.0005, help="单边 taker 费率")
    ap.add_argument("--slip", type=float, default=0.0002, help="单边滑点")
    ap.add_argument(
        "--entries-jsonl",
        default="",
        help="真实入场记录 jsonl（coin/direction/entry_time）；提供后只重放离场，实现纯离场 A/B",
    )
    ap.add_argument("--out", default="/tmp/exit_bt_result.json")
    ap.add_argument("--label", default="current")
    ap.add_argument("--retrace", type=float, default=None, help="覆盖 trailing_retrace_pct（消融）")
    ap.add_argument(
        "--retrace-atr-mult",
        type=float,
        default=0.0,
        help=">0 时按 Chandelier 口径 trailing_retrace_pct = clamp(该倍数×ATR%%,3%%,20%%)",
    )
    ap.add_argument("--no-partial-tp", action="store_true", help="关闭规则4分批止盈（消融）")
    ap.add_argument("--no-breakeven", action="store_true", help="关闭含费保本位（消融）")
    ap.add_argument("--tp", type=float, default=TP_PCT, help="固定 TP 间距（消融）")
    ap.add_argument(
        "--tp-mult",
        type=float,
        default=0.0,
        help=">0 时按生产口径 TP=max(SL×该倍数,12%%)，上限 30%%（如 3.0）",
    )
    ap.add_argument("--sl-mult", type=float, default=None, help="初始 SL 的 ATR 倍数（消融）")
    ap.add_argument("--sl-floor", type=float, default=SL_FLOOR, help="初始 SL 下限（消融）")
    ap.add_argument("--trail-arm", type=float, default=None, help="trailing 武装阈值（消融）")
    ap.add_argument(
        "--engine",
        default="fixed",
        choices=["fixed", "legacy"],
        help="fixed=当前实现；legacy=git HEAD 旧实现（忠实 baseline）",
    )
    ap.add_argument(
        "--legacy-path",
        default="/tmp/exit_bt_cache/legacy_exit_engine.py",
        help="legacy 引擎文件路径（git show HEAD:... 导出）",
    )
    args = ap.parse_args()

    replay = TradeReplay(
        args.fee,
        args.slip,
        retrace=args.retrace,
        partial_tp=not args.no_partial_tp,
        breakeven=not args.no_breakeven,
        tp_pct=args.tp,
        sl_mult=args.sl_mult,
        sl_floor=args.sl_floor,
        trail_arm=args.trail_arm,
        legacy_path=args.legacy_path if args.engine == "legacy" else None,
        tp_mult=args.tp_mult,
        retrace_atr_mult=args.retrace_atr_mult,
    )
    all_trades: List[Dict[str, Any]] = []
    per_symbol: Dict[str, Any] = {}
    real_entries = load_real_entries(args.entries_jsonl) if args.entries_jsonl else None
    for sym in [s.strip() for s in args.symbols.split(",") if s.strip()]:
        try:
            rows = fetch_klines(sym, args.timeframe, args.days)
        except Exception as exc:  # noqa: BLE001 — 单标的失败不阻断整体回测
            print(f"[skip] {sym} fetch_failed: {exc}", file=sys.stderr)
            continue
        if len(rows) < EMA_PERIOD + 10:
            print(f"[skip] {sym} klines={len(rows)}", file=sys.stderr)
            continue
        atrs = atr_series(rows)
        if real_entries is not None:
            samples = []
            for side, ts_ms, px in real_entries.get(sym, []):
                idx = ts_to_index(rows, ts_ms)
                if idx is not None:
                    samples.append((side, idx, px))
        else:
            samples = build_samples(rows)
        trades = []
        for _s in samples:
            side, idx = _s[0], _s[1]
            _px = _s[2] if len(_s) > 2 else None
            r = replay.run(sym, side, idx, rows, atrs, entry_px=_px)
            if r:
                trades.append(r)
        all_trades.extend(trades)
        per_symbol[sym] = {
            "klines": len(rows),
            "span": [int(rows[0][0]), int(rows[-1][0])],
            "samples": len(samples),
            "summary": summarize(trades),
        }
        print(
            f"[{sym}] klines={len(rows)} samples={len(samples)} "
            f"avg={per_symbol[sym]['summary'].get('avg_pnl_pct')} "
            f"win={per_symbol[sym]['summary'].get('win_rate')}",
            file=sys.stderr,
        )

    result = {
        "label": args.label,
        "params": {
            "timeframe": args.timeframe,
            "days": args.days,
            "fee": args.fee,
            "slip": args.slip,
            "entry_step_bars": ENTRY_STEP_BARS,
            "tp_pct": TP_PCT,
            "tier": TIER,
        },
        "summary": summarize(all_trades),
        "per_symbol": per_symbol,
        "trades": all_trades,
    }
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print(
        json.dumps(
            {"label": args.label, "summary": result["summary"]}, ensure_ascii=False, indent=1
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
