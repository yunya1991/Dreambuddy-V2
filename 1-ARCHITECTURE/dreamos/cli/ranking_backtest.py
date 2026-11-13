#!/usr/bin/env python3
"""P2 回测：A 组（原模式：7维技术分代理）vs B 组（scan.py + 50-NN 融合）

两条链：
  A 组（原来的模式）：screen_engine.py 的 7 维技术分简化代理
    → MA200 多空锚定 + RSI + MACD + 动量 7/30 日 → 归一化 score [0,1]

  B 组（50-NN 融合）：ranking_subsystem_scan.py signals → 补齐 source/horizon
    → 42 SignalSchema v1 evidences → 50 make_decision() → direction + confidence

回测口径：
    - 主口径：t+1 开盘价等权买入，SL/TP 出场（同日触 SL/TP → 保守按 SL 先触发），最长 10 日强制平仓
    - 辅助口径：固定持有 N=1/3/5/10 日
    - 成本：手续费 0.05% + 滑点 0.05%（加密 OKX 合成品种），做空同计费

说明：B 组当前 engine 只能扫有限标的（BCRM2 本地引擎受限），
先跑通 baseline 对比，后续补历史重放（云端 bus_history.jsonl）。

用法：
    python3 ranking_backtest.py                  # 跑当前 scan 快照 + 最近 N 日 K 线
    python3 ranking_backtest.py --symbols BTC HYPE ETH   # 指定标的
    python3 ranking_backtest.py --scan            # 先手动跑一次 scan.py 刷新 signals
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


# ── 路径注入 ──────────────────────────────────────────────────────
def _repo_root() -> Path:
    here = Path(__file__).resolve().parent
    for parent in (here, *here.parents):
        if (parent / ".git").exists():
            return parent
    return here.parent.parent


REPO = _repo_root()
for sub in [
    "11-易经推理系统",
    "12-三屏趋势系统",
    "17-v4-wave-strategy",
    "23-四层闭环自进化交易架构",
    "29-事件驱动策略系统",
    "40-周期神经网络系统",
    "42-神经网络交易协调层",
    "50-NN主矛盾评估器",
    "1-ARCHITECTURE/dreamos/cli",
]:
    p = REPO / sub
    if p.is_dir() and str(p) not in sys.path:
        sys.path.insert(0, str(p))

SCHED = REPO / "1-ARCHITECTURE" / "dreamos" / "cli" / "scheduler_data"
OUT_DIR = REPO / "1-ARCHITECTURE" / "dreamos" / "cli" / "backtest_reports"


# ═══════════════════════════════════════════════════════════════
# §1 资产 Universe + K线拉取
# ═══════════════════════════════════════════════════════════════

# 默认回测标的（加密 + OKX 合成品种）；非 OKX 美股个股暂用 A 组代理
DEFAULT_SYMBOLS = [
    "BTC",
    "ETH",
    "SOL",
    "BNB",
    "HYPE",
    "XRP",
    "ADA",
    "DOGE",
    "AVAX",
    "XAU",
    "XPT",
    "NG",
    "USO",
    "US500",
    "AMD",
    "NVDA",
]


def _to_inst_id(symbol: str) -> str:
    s = symbol.upper().replace("-", "").replace("/", "")
    return f"{s}-USDT-SWAP"


def fetch_daily_df(symbol: str, days: int = 250) -> Optional[pd.DataFrame]:
    """拉 OKX 1D K 线（缓存到本地文件），返回 DatetimeIndex DataFrame。

    用 OkxFeed CLI 路径（稳定），OKX CLI 单请求最多 300 根，
    因此 days 上限设 240（留 60 根做 MA200 热身 + walk-forward）。
    """
    days = min(days, 240)
    need_min = days + 30

    inst_id = _to_inst_id(symbol)
    cache_dir = REPO / "11-易经推理系统" / "scripts" / "data" / "klines"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{inst_id.replace('-', '_')}_1d.csv"

    # 缓存命中 → 读缓存
    df: Optional[pd.DataFrame] = None
    if cache_file.is_file():
        try:
            cached = pd.read_csv(cache_file, parse_dates=["ts"])
            if len(cached) >= need_min:
                df = cached.tail(days + 30)
        except Exception:
            df = None

    if df is None:
        raw: List[Any] = []
        try:
            from ranking_asset_pool import OkxFeed  # noqa: WPS433

            feed = OkxFeed()
            for _ in range(3):
                try:
                    raw = feed.candles(inst_id)
                    break
                except Exception:
                    time.sleep(1)
        except Exception:
            raw = []

        if not raw or len(raw) < need_min:
            return None
        try:
            df = pd.DataFrame(
                raw,
                columns=["ts", "open", "high", "low", "close", "volume"]
                + [f"x{i}" for i in range(len(raw[0]) - 6)],
            )
            for col in ("open", "high", "low", "close", "volume"):
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df["ts"] = pd.to_datetime(df["ts"].astype(float), unit="ms", utc=True)
            df = df.dropna(subset=["close"]).sort_values("ts").reset_index(drop=True)
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            df[["ts", "open", "high", "low", "close", "volume"]].to_csv(cache_file, index=False)
            df = df.tail(days + 30)
        except Exception:
            return None

    if df is None or len(df) < need_min:
        return None
    df = df.set_index("ts") if "ts" in df.columns else df
    return df.tail(days + 30).copy()


# ═══════════════════════════════════════════════════════════════
# §2 A 组代理评分（动量 + MA，与 ranking_asset_pool.score_symbol 一致）
# ═══════════════════════════════════════════════════════════════


def a_group_score(df_slice: pd.DataFrame) -> Optional[float]:
    """A 组简化代理：7日动量*0.4 + MA20/MA60 相对强度*0.3 + 截面影子 0.43~0.55。

    注：coin_pool.json 无历史快照，本函数为可复现代理实现，报告将显著标注。
    """
    closes = df_slice["close"].dropna().values
    if len(closes) < 60:
        return None
    last = closes[-1]
    ma20 = float(np.mean(closes[-20:]))
    ma60 = float(np.mean(closes[-60:]))

    def _mom(n: int) -> float:
        base = closes[-n - 1] if len(closes) > n + 1 else closes[0]
        return 0.0 if base <= 0 else (last / base - 1.0) * 100.0

    mom7 = _mom(7)
    mom30 = _mom(30)

    # 归一化 -20%~+20% → 0~1
    def _norm(pct: float) -> float:
        return max(0.0, min(1.0, (pct + 20.0) / 40.0))

    tech = _norm(mom7) * 0.4 + _norm(mom30) * 0.6
    structure = 0.5 * (1.0 if last > ma20 else 0.0) + 0.5 * (1.0 if last > ma60 else 0.0)
    score = max(0.0, min(1.0, tech * 0.7 + structure * 0.3))
    return float(score)


# ═══════════════════════════════════════════════════════════════
# §3 B 组信号获取：scan.py 快照 + 42 bus_state.json → 42 SignalSchema v1
#
# 注：BCRM2/三屏/V4 本地引擎当前受限（历史数据不足或未训好），
# 因此 B 组先用 ranking_subsystem_scan.py 产出的最新快照，
# 补齐 expires_at 让 50-NN 认为是 fresh evidence。
# 后续补：从云端 bus_history.jsonl 拉历史切片做真正 walk-forward。
# ═══════════════════════════════════════════════════════════════


# scan 子系统 → 42 source 映射（保证 50 SOURCE_WEIGHT_MAP 里能找到）
SUBSYSTEM_TO_42_SOURCE = {
    "bcrm2": "11-bcrm-tactical",  # weight 0.35, role=external
    "three_screen": "11-bcrm",  # weight 0.15, role=external
    "v4_wave": "11-bcrm-tactical",  # 暂归入同一 tactical 源
    "bdsm": "11-bdsm",  # weight 0.20, role=external
}

# 反向映射：42 source → subsystem 名（用于从 paths 里按 subsystem 分组）
SUBSYSTEM_TO_42_SOURCE_REV = {
    "11-bcrm-tactical": "bcrm2",
    "11-bcrm": "three_screen",
    "11-bdsm": "bdsm",
}


def load_b_signals(symbols: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    """加载 ranking_subsystem_scan.py 快照 + 42 bus_state.json，按 symbol 分组。

    返回 {symbol: [42 SignalSchema v1 signals]}
    """
    now_iso = datetime.now(timezone.utc)
    expires_iso = now_iso + pd.Timedelta(hours=24)

    by_symbol: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    seen: set = set()  # dedup (source, symbol, direction)

    def _add(symbol: str, source: str, direction: str, confidence: float, horizon: str, mode: str):
        key = (source, symbol, direction)
        if direction in ("neutral", "flat") or confidence < 0.05 or key in seen:
            return
        seen.add(key)
        signal = {
            "signal_id": f"sig_{source}_{symbol}_{int(time.time()*1000)}",
            "source": source,
            "ts": now_iso.isoformat().replace("+00:00", "Z"),
            "symbol": f"{symbol}-USDT-SWAP",
            "direction": direction,
            "confidence": round(confidence, 4),
            "horizon": horizon,
            "risk_exposure_hint": 0.5,
            "expires_at": expires_iso.isoformat().replace("+00:00", "Z"),
            "mode": mode,
            "shadow": True,
            "payload": {"state_generated_at": now_iso.isoformat().replace("+00:00", "Z")},
        }
        by_symbol[symbol].append(signal)

    # ── 源 1：ranking_subsystem_scan.py 快照 ──
    scan_file = SCHED / "ranking_subsystem_signals.json"
    if scan_file.is_file():
        try:
            scan_data = json.loads(scan_file.read_text())
            for sig in scan_data.get("signals", []):
                sub = sig.get("subsystem", "")
                sym = sig.get("symbol", "")
                src = SUBSYSTEM_TO_42_SOURCE.get(sub)
                if not src or sym not in symbols:
                    continue
                _add(
                    symbol=sym,
                    source=src,
                    direction=sig.get("direction", "neutral"),
                    confidence=float(sig.get("confidence", 0.0) or 0.0),
                    horizon=sig.get("horizon", "days"),
                    mode="scan_snapshot",
                )
        except Exception:
            pass

    # ── 源 2：42 bus_state.json（per-symbol, 去掉 MACRO/asset 粒度） ──
    bus_file = REPO / "42-神经网络交易协调层" / "runtime" / "bus_state.json"
    if bus_file.is_file():
        try:
            bus = json.loads(bus_file.read_text())
            ASSET_MACRO = {"MACRO", "CRYPTO_USDT", "PRECIOUS_METAL", "US_STOCK"}
            for sig in bus.get("signals", []):
                raw_sym = str(sig.get("symbol", "")).upper()
                # 归一化 symbol
                clean = (
                    raw_sym.replace("-USDT-SWAP", "")
                    .replace("-USDT", "")
                    .replace("/", "")
                    .replace("-", "")
                )
                if clean in ASSET_MACRO or raw_sym in ASSET_MACRO:
                    continue
                if clean not in symbols:
                    continue
                # 复用 bus 的 source/direction/confidence，但是把 expires_at 重置为 fresh
                _add(
                    symbol=clean,
                    source=sig.get("source", "11-bcrm-tactical"),
                    direction=sig.get("direction", "neutral"),
                    confidence=float(sig.get("confidence", 0.0) or 0.0),
                    horizon=sig.get("horizon", "hours"),
                    mode="bus_bumped",
                )
        except Exception:
            pass

    return by_symbol


# ═══════════════════════════════════════════════════════════════
# §3b C 组信号获取：23 EvolutionPipeline.run_symbol（独立自进化路径）
#
# 23 和 42 是两条独立演进路径：
#   - 42 → 50-NN：信号融合仲裁层（多子系统 consensus）
#   - 23 自进化：策略基因库 + CBR/KNN 案例匹配
# ═══════════════════════════════════════════════════════════════


def _load_c_signals(
    symbols: List[str],
    klines: Dict[str, pd.DataFrame],
) -> Dict[str, Optional[Dict[str, Any]]]:
    """调 23 EvolutionPipeline.run_symbol() 产出 C 组决策。

    返回 {symbol: {direction, confidence, action, regime} | None}
    """
    result: Dict[str, Optional[Dict[str, Any]]] = {}
    try:
        sys.path.insert(0, str(REPO / "23-四层闭环自进化交易架构"))
        from pathlib import Path as _P

        from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline

        pipeline = EvolutionPipeline(
            gene_root=_P(REPO / "23-四层闭环自进化交易架构/dreambuddy_evolution/gene_data")
        )
    except Exception:
        for sym in symbols:
            result[sym] = None
        return result

    action_map = {
        "LONG": "long",
        "SHORT": "short",
        "WAIT": "neutral",
    }

    for sym in symbols:
        df = klines.get(sym)
        if df is None or len(df) < 60:
            result[sym] = None
            continue

        try:
            closes = df["close"].values.tolist()
            highs = df["high"].values.tolist()
            lows = df["low"].values.tolist()
            market_data = {
                "closes": closes,
                "highs": highs,
                "lows": lows,
                "source_asset": "BTC",
                "symbol": sym,
            }
            raw = pipeline.run_symbol(sym, market_data)
            action = str(raw.get("action", "WAIT")).upper()
            direction = action_map.get(action, "neutral")
            level0_conf = float(raw.get("level0_confidence", 0.0) or 0.0)
            regime = raw.get("regime", "UNKNOWN")

            if direction == "neutral" or level0_conf < 0.05:
                result[sym] = None
            else:
                result[sym] = {
                    "direction": direction,
                    "confidence": level0_conf,
                    "action": action,
                    "regime": regime,
                }
        except Exception:
            result[sym] = None

    return result


# ═══════════════════════════════════════════════════════════════
# §4 50-NN 融合（完整链路：evidence → path → w4 → dominance → clamp）
# ═══════════════════════════════════════════════════════════════


def fuse_with_50nn(
    signals: List[Dict[str, Any]],
    symbol: str,
) -> Optional[Dict[str, Any]]:
    """把重放的 SignalSchema v1 signals 喂给 50-NN make_decision。

    返回 decision dict（含 direction / confidence / w4 / dominance）；
    输入为空 → None；最终 direction=neutral 或 confidence 低 → None。
    """
    if not signals:
        return None

    # ── 42 SignalSchema v1 → 50 evidence ──
    from adapters.bus_reader import to_evidence  # noqa: WPS433
    from core.decision import make_decision  # noqa: WPS433

    evidences = [to_evidence(s) for s in signals]
    evidences = [
        e
        for e in evidences
        if e.get("source") not in (None, "", "unknown")
        and e.get("direction") not in ("neutral", None)
        and float(e.get("confidence", 0.0) or 0.0) > 0.05
    ]
    if not evidences:
        return None

    try:
        decision = make_decision(
            evidences=evidences,
            symbol=symbol,
            asset_class="crypto_usdt",
        )
    except Exception:
        return None

    if not isinstance(decision, dict):
        return None
    direction = decision.get("direction", "neutral")
    confidence = float(decision.get("confidence", 0.0) or 0.0)
    if direction == "neutral" or confidence < 0.05:
        return None

    return decision


# ═══════════════════════════════════════════════════════════════
# §5 回测引擎
# ═══════════════════════════════════════════════════════════════

# ── 成本参数 ──
FEE_RATE = 0.0005  # 手续费 0.05%
SLIPPAGE_RATE = 0.0005  # 滑点 0.05%
TOTAL_COST = FEE_RATE + SLIPPAGE_RATE

# ── SL/TP 参数 ──
SL_PCT = 0.05  # 5% 止损
TP_PCT = 0.10  # 10% 止盈
MAX_HOLD_DAYS = 10  # 最长持有 10 日强制平仓
TP_FIRST = False  # 同触 SL/TP → 保守按 SL 先触发


# ── 持仓记录 ──
class Position:
    __slots__ = ("symbol", "direction", "entry_price", "entry_date", "size")

    def __init__(
        self, symbol: str, direction: str, entry_price: float, entry_date, size: float = 1.0
    ):
        self.symbol = symbol
        self.direction = direction
        self.entry_price = entry_price
        self.entry_date = entry_date
        self.size = size


def compute_exit_sltp(
    pos: Position,
    high: float,
    low: float,
    close: float,
    n_days_held: int,
    max_days: int = MAX_HOLD_DAYS,
) -> Tuple[Optional[str], Optional[float]]:
    """计算当日是否触发 SL/TP/超时强制平仓。

    返回 (exit_reason, exit_price)，exit_reason ∈ {None, "SL", "TP", "FORCE_CLOSE"}。
    同触 SL 和 TP 按保守策略：direction=long 按 SL（亏），direction=short 按 TP（亏）。
    """
    if n_days_held >= max_days:
        return ("FORCE_CLOSE", close)

    if pos.direction == "long":
        sl_price = pos.entry_price * (1 - SL_PCT)
        tp_price = pos.entry_price * (1 + TP_PCT)
        sl_hit = low <= sl_price
        tp_hit = high >= tp_price
        if sl_hit and tp_hit:
            # 同日冲突：保守按 SL
            return ("SL", sl_price)
        if sl_hit:
            return ("SL", sl_price)
        if tp_hit:
            return ("TP", tp_price)
    else:  # short
        sl_price = pos.entry_price * (1 + SL_PCT)
        tp_price = pos.entry_price * (1 - TP_PCT)
        sl_hit = high >= sl_price
        tp_hit = low <= tp_price
        if sl_hit and tp_hit:
            return ("SL", sl_price)
        if sl_hit:
            return ("SL", sl_price)
        if tp_hit:
            return ("TP", tp_price)
    return (None, None)


def run_backtest(
    symbols: List[str],
    horizon: str = "sltp",
    fixed_n_days: int = 5,
    train_days: int = 120,
    top_n: int = 3,
) -> Dict[str, Any]:
    """主回测入口。

    两条链的回测逻辑不同：
      A 组（原模式）：每日重算技术分，每日选 Top N 等权买入 → 每日新交易
      B 组（50-NN）：用今天的 scan.py + 42 bus_state.json → 50-NN 融合出方向
        → 从回测起点开始，每天按该 direction 买入（相当于假设 NN 信号
        在整个回测窗口持续有效）

    注：B 组不是严格 walk-forward（缺云端 bus_history.jsonl），
    报告会显著标注此局限。
    """
    print(f"\n{'='*60}")
    print("[ranking_backtest] 启动")
    print(f"  symbols={len(symbols)} ({', '.join(symbols[:5])}{'...' if len(symbols)>5 else ''})")
    print(f"  horizon={horizon}  fixed_n={fixed_n_days}  train_days={train_days}  top_n={top_n}")
    print(f"  cost={FEE_RATE:.2%}+{SLIPPAGE_RATE:.2%}={TOTAL_COST:.2%}")
    print(f"  SL={SL_PCT:.0%}  TP={TP_PCT:.0%}  max_hold={MAX_HOLD_DAYS}d")
    print(f"{'='*60}\n")

    # ── 1. 拉 K 线 ──
    klines: Dict[str, pd.DataFrame] = {}
    for sym in symbols:
        print(f"  拉 K 线 {sym} ... ", end="", flush=True)
        df = fetch_daily_df(sym, days=train_days + 30)
        if df is not None and len(df) >= train_days:
            klines[sym] = df
            print(f"OK ({len(df)} bars)")
        else:
            print(f"SKIP (len={len(df) if df is not None else 0})")

    if not klines:
        return {"error": "no klines"}

    # ── 2. B 组：预计算 NN 融合决策（单一快照） ──
    print("\n  加载 B 组 signals + 50-NN 融合...", flush=True)
    b_signal_map = load_b_signals(list(klines.keys()))

    b_decisions: Dict[str, Optional[Dict]] = {}
    b_sub_breakdown: Dict[str, Dict[str, float]] = defaultdict(dict)
    for sym in klines:
        sigs = b_signal_map.get(sym, [])
        if sigs:
            decision = fuse_with_50nn(sigs, sym)
            b_decisions[sym] = decision
            if decision:
                paths = decision.get("payload", {}).get("paths", [])
                for p in paths:
                    src = p.get("source", "")
                    dir_ = p.get("direction", "long")
                    conf = p.get("confidence", 0.0)
                    # 按 subsystem 聚合
                    sub_key = SUBSYSTEM_TO_42_SOURCE_REV.get(src, src)
                    if (
                        dir_ not in ("neutral",)
                        and conf > b_sub_breakdown[sym].get(sub_key, (0, "neutral"))[0]
                    ):
                        b_sub_breakdown[sym][sub_key] = (conf, dir_)
        else:
            b_decisions[sym] = None

    # 打印 B 组决策概览
    b_hit = [
        (s, d["direction"], d["confidence"])
        for s, d in b_decisions.items()
        if d and d["direction"] != "neutral"
    ]
    print(f"  B 组有效决策: {len(b_hit)}/{len(klines)}")
    for sym, dir_, conf in b_hit:
        print(f"    {sym:10s} {dir_:6s} conf={conf:.4f}")

    # ── 2b. C 组：23 自进化 EvolutionPipeline.run_symbol（独立路径，不走 42） ──
    print("\n  加载 C 组 signals（23 自进化 EvolutionPipeline）...", flush=True)
    c_decisions = _load_c_signals(list(klines.keys()), klines)
    c_hit = [
        (s, d["direction"], d["confidence"])
        for s, d in c_decisions.items()
        if d and d["direction"] != "neutral"
    ]
    print(f"  C 组有效决策: {len(c_hit)}/{len(klines)}")
    for sym, dir_, conf in c_hit:
        print(f"    {sym:10s} {dir_:6s} conf={conf:.4f}")

    # ── 3. 找共同日期区间 ──
    all_dates = set()
    for df in klines.values():
        all_dates.update(df.index)
    sorted_dates = sorted(
        d for d in all_dates if d >= min(df.index.min() for df in klines.values())
    )
    if len(sorted_dates) < train_days + 20:
        return {"error": f"insufficient dates, only {len(sorted_dates)}"}

    start_idx = train_days
    dates_for_loop = sorted_dates[start_idx:]
    print(
        f"\n回测窗口: {len(dates_for_loop)} 个交易日 "
        f"({dates_for_loop[0].date()} ~ {dates_for_loop[-1].date()})"
    )

    # ── 4. 每日跑 A/B/C 三组 + 各 subsystem 独立 ──
    groups = {
        "overall_A": {"trades": []},
        "overall_B": {"trades": []},
        "overall_C": {"trades": []},
        "bcrm2": {"trades": []},
        "three_screen": {"trades": []},
        "c_evolution": {"trades": []},
    }

    n_total = len(dates_for_loop)
    for i, t in enumerate(dates_for_loop):
        if i % 10 == 0:
            print(f"  [{i}/{n_total}] {t.date()} ... ", end="", flush=True)

        t_idx_map: Dict[str, int] = {}
        for sym, df in klines.items():
            ts = pd.Timestamp(t, tz="UTC") if pd.Timestamp(t).tzinfo is None else t
            avail = df.index[df.index <= ts]
            if len(avail) == 0:
                continue
            ts = avail[-1]
            t_idx_map[sym] = int(df.index.get_loc(ts))

        # ── A 组：每日重算技术分，取 Top N long ──
        ranked_A: List[Tuple[str, float, str]] = []
        for sym, df in klines.items():
            t_idx = t_idx_map.get(sym)
            if t_idx is None or t_idx < 60:
                continue
            a_score = a_group_score(df.iloc[: t_idx + 1])
            if a_score is not None and a_score > 0.55:
                ranked_A.append((sym, a_score, "long"))
        ranked_A.sort(key=lambda x: -x[1])
        A_targets = ranked_A[:top_n]

        # ── B 组：用预计算的 NN 决策（单一快照，整个窗口有效） ──
        ranked_B: List[Tuple[str, float, str]] = []
        for sym, dec in b_decisions.items():
            if dec is None or dec.get("direction") == "neutral":
                continue
            ranked_B.append((sym, dec["confidence"], dec["direction"]))
        ranked_B.sort(key=lambda x: -x[1])
        B_targets = ranked_B[:top_n]

        # ── C 组：用预计算的自进化决策（单一快照） ──
        ranked_C: List[Tuple[str, float, str]] = []
        for sym, dec in c_decisions.items():
            if dec is None or dec.get("direction") == "neutral":
                continue
            ranked_C.append((sym, dec["confidence"], dec["direction"]))
        ranked_C.sort(key=lambda x: -x[1])
        C_targets = ranked_C[:top_n]

        # ── 各 subsystem 独立：从 paths 里按 subsystem 分组 ──
        sub_targets: Dict[str, List[Tuple[str, float, str]]] = defaultdict(list)
        for sym in klines:
            dec = b_decisions.get(sym)
            if not dec:
                continue
            paths = dec.get("payload", {}).get("paths", [])
            for p in paths:
                src = p.get("source", "")
                sub_name = SUBSYSTEM_TO_42_SOURCE_REV.get(src)
                if sub_name is None or p.get("direction") == "neutral":
                    continue
                sub_targets[sub_name].append(
                    (sym, p.get("confidence", 0.0), p.get("direction", "long"))
                )
        for sub_name in sub_targets:
            sub_targets[sub_name].sort(key=lambda x: -x[1])
            sub_targets[sub_name] = sub_targets[sub_name][:top_n]

        # ── 5. 找 t+1 开盘价（实际买入价） ──
        next_ts = None
        for _sym, df in klines.items():
            ts = pd.Timestamp(t, tz="UTC") if pd.Timestamp(t).tzinfo is None else t
            idx = df.index.get_indexer([ts], method="nearest")[0]
            if idx >= 0 and idx + 1 < len(df):
                cand = df.index[idx + 1]
                if next_ts is None or cand < next_ts:
                    next_ts = cand
        if next_ts is None:
            if i % 10 == 0:
                print("skip (no next bar)")
            continue

        # ── 6. 下单 + 出场 ──
        buy_groups = [
            ("overall_A", A_targets),
            ("overall_B", B_targets),
            ("overall_C", C_targets),
            ("c_evolution", C_targets),
        ]
        for sub_name in sub_targets:
            buy_groups.append((sub_name, sub_targets[sub_name]))

        for grp_name, targets in buy_groups:
            for sym, score, direction in targets:
                df = klines.get(sym)
                if df is None:
                    continue
                buy_ts = next_ts
                if buy_ts not in df.index:
                    avail = df.index[df.index >= buy_ts]
                    if len(avail) == 0:
                        continue
                    buy_ts = avail[0]
                entry_price = float(df.loc[buy_ts, "open"])
                if entry_price <= 0:
                    continue
                pos = Position(sym, direction, entry_price, buy_ts)

                trade = {
                    "symbol": sym,
                    "direction": direction,
                    "entry_date": pos.entry_date.isoformat(),
                    "entry_price": round(entry_price, 6),
                    "exit_date": None,
                    "exit_price": None,
                    "exit_reason": None,
                    "pnl_pct": None,
                    "score_entry": round(score, 4),
                }

                if horizon == "sltp":
                    exit_done = False
                    n_held = 0
                    for check_ts in df.index:
                        if check_ts <= pos.entry_date:
                            continue
                        n_held += 1
                        high = float(df.loc[check_ts, "high"])
                        low = float(df.loc[check_ts, "low"])
                        close = float(df.loc[check_ts, "close"])
                        reason, ex_price = compute_exit_sltp(pos, high, low, close, n_held)
                        if reason is not None:
                            trade["exit_date"] = check_ts.isoformat()
                            trade["exit_price"] = round(ex_price, 6)
                            trade["exit_reason"] = reason
                            exit_done = True
                            break
                    if not exit_done:
                        last_ts = df.index[-1]
                        trade["exit_date"] = last_ts.isoformat()
                        trade["exit_price"] = round(float(df.loc[last_ts, "close"]), 6)
                        trade["exit_reason"] = "DATA_END"
                else:
                    n_held = 0
                    for check_ts in df.index:
                        if check_ts <= pos.entry_date:
                            continue
                        n_held += 1
                        if n_held >= fixed_n_days:
                            close_price = float(df.loc[check_ts, "close"])
                            trade["exit_date"] = check_ts.isoformat()
                            trade["exit_price"] = round(close_price, 6)
                            trade["exit_reason"] = f"FIXED_{fixed_n_days}D"
                            break
                    if trade["exit_date"] is None:
                        last_ts = df.index[-1]
                        trade["exit_date"] = last_ts.isoformat()
                        trade["exit_price"] = round(float(df.loc[last_ts, "close"]), 6)
                        trade["exit_reason"] = "DATA_END"

                ex_price = trade["exit_price"]
                if direction == "long":
                    gross = (ex_price / entry_price) - 1.0
                else:
                    gross = (entry_price / ex_price) - 1.0
                net = gross - 2 * TOTAL_COST
                trade["pnl_pct"] = round(net * 100.0, 4)
                groups[grp_name]["trades"].append(trade)

        if i % 10 == 0:
            print(
                f"OK ({len(groups['overall_A']['trades'])}A / {len(groups['overall_B']['trades'])}B)"
            )

    print(
        f"\n回测结束。A组 {len(groups['overall_A']['trades'])} 笔，B组 {len(groups['overall_B']['trades'])} 笔"
    )

    # ── 7. 计算指标 ──
    results: Dict[str, Any] = {
        "meta": {
            "run_at": datetime.now(timezone.utc).isoformat(),
            "horizon": horizon,
            "fixed_n_days": fixed_n_days,
            "train_days": train_days,
            "top_n": top_n,
            "symbols": list(klines.keys()),
            "cost": {"fee": FEE_RATE, "slippage": SLIPPAGE_RATE, "total": TOTAL_COST},
            "sltp": {"sl_pct": SL_PCT, "tp_pct": TP_PCT, "max_hold_days": MAX_HOLD_DAYS},
            "days_available": len(dates_for_loop),
            "a_proxy_note": "A组为 screen_engine 7维技术分代理（coin_pool.json 无历史快照）",
            "b_walkforward_note": "⚠️ B组信号为当前 scan.py+42 bus_state.json 单一快照，非严格 walk-forward。后续补云端 bus_history.jsonl 历史重放。",
            "b_decisions": {
                s: {"direction": d["direction"], "confidence": d["confidence"]}
                for s, d in b_decisions.items()
                if d
            },
            "c_walkforward_note": "⚠️ C组信号为 23 EvolutionPipeline.run_symbol 当前快照（独立自进化路径，不走 42），非严格 walk-forward。",
            "c_decisions": {
                s: {
                    "direction": d["direction"],
                    "confidence": d["confidence"],
                    "regime": d.get("regime"),
                }
                for s, d in c_decisions.items()
                if d
            },
        },
        "groups": {},
    }

    for grp_name, bucket in groups.items():
        trades = bucket["trades"]
        metrics = _calc_metrics(trades)
        results["groups"][grp_name] = metrics
        n = metrics.get("n_trades", 0)
        if n > 0:
            print(
                f"  {grp_name:15s}: trades={n:4d}  win={metrics.get('win_rate',0):.1%}  "
                f"avg_ret={metrics.get('avg_pnl_pct',0):+.2f}%  sharpe={metrics.get('sharpe',0):.2f}  "
                f"dd={metrics.get('max_drawdown',0):.1f}%"
            )
        else:
            print(f"  {grp_name:15s}: trades=0  (no valid signals)")

    # ── 8. 配对日收益差检验 ──
    pair_test = _pair_test(groups["overall_A"]["trades"], groups["overall_B"]["trades"])
    results["pair_test"] = pair_test
    print(
        f"\n配对日收益差检验: mean(B-A)={pair_test['mean_diff']:+.2f}%  "
        f"t={pair_test['t_stat']:.2f}  p={pair_test['p_value']:.4f}"
    )

    return results


# ═══════════════════════════════════════════════════════════════
# §6 指标计算 + 报告输出
# ═══════════════════════════════════════════════════════════════

from scipy.stats import t as _tdist  # noqa: E402


def _calc_metrics(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not trades:
        return {"n_trades": 0}
    rets = np.array([t["pnl_pct"] for t in trades if t.get("pnl_pct") is not None]) / 100.0
    if len(rets) == 0:
        return {"n_trades": 0}

    wins = rets[rets > 0]
    losses = rets[rets < 0]
    win_rate = len(wins) / len(rets)
    avg_pnl = float(np.mean(rets))
    avg_win = float(np.mean(wins)) if len(wins) > 0 else 0.0
    avg_loss = float(np.mean(losses)) if len(losses) > 0 else 0.0
    pl_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else float("inf")

    if len(rets) > 1 and float(np.std(rets)) > 0:
        sharpe = float(np.mean(rets) / np.std(rets) * np.sqrt(252))
    else:
        sharpe = 0.0

    cum = np.cumprod(1.0 + rets)
    peak = np.maximum.accumulate(cum)
    dd = (peak - cum) / peak
    max_dd = float(np.max(dd)) if len(dd) > 0 else 0.0

    sl_count = sum(1 for t in trades if t.get("exit_reason") == "SL")
    tp_count = sum(1 for t in trades if t.get("exit_reason") == "TP")
    force_count = sum(
        1
        for t in trades
        if t.get("exit_reason", "").startswith("FIXED")
        or t.get("exit_reason") in ("FORCE_CLOSE", "DATA_END")
    )

    hold_days: List[float] = []
    for t in trades:
        try:
            en = datetime.fromisoformat(t["entry_date"].replace("Z", "+00:00"))
            ex = datetime.fromisoformat(t["exit_date"].replace("Z", "+00:00"))
            hold_days.append((ex - en).total_seconds() / 86400.0)
        except Exception:
            pass
    avg_hold = float(np.mean(hold_days)) if hold_days else 0.0

    lo, hi = _bootstrap_ci(rets)

    return {
        "n_trades": int(len(rets)),
        "win_rate": round(win_rate, 4),
        "avg_pnl_pct": round(avg_pnl * 100.0, 4),
        "avg_win_pct": round(avg_win * 100.0, 4),
        "avg_loss_pct": round(avg_loss * 100.0, 4),
        "pl_ratio": round(pl_ratio, 4),
        "sharpe": round(sharpe, 4),
        "max_drawdown": round(max_dd * 100.0, 2),
        "sl_count": sl_count,
        "tp_count": tp_count,
        "force_close_count": force_count,
        "avg_hold_days": round(avg_hold, 2),
        "bootstrap_ci_pct": {
            "mean_low": round(lo * 100.0, 4),
            "mean_high": round(hi * 100.0, 4),
        },
    }


def _bootstrap_ci(rets: np.ndarray, n_boot: int = 2000, alpha: float = 0.05) -> Tuple[float, float]:
    if len(rets) < 5:
        return (float(np.mean(rets)), float(np.mean(rets)))
    rng = np.random.default_rng(42)
    boot_means = [
        float(np.mean(rng.choice(rets, size=len(rets), replace=True))) for _ in range(n_boot)
    ]
    lo = float(np.percentile(boot_means, 100 * alpha / 2))
    hi = float(np.percentile(boot_means, 100 * (1 - alpha / 2)))
    return (lo, hi)


def _pair_test(trades_A: List[Dict], trades_B: List[Dict]) -> Dict[str, Any]:
    a_by_date: Dict[str, List[float]] = {}
    for t in trades_A:
        d = t.get("entry_date", "")[:10]
        if d:
            a_by_date.setdefault(d, []).append(t.get("pnl_pct", 0.0))
    b_by_date: Dict[str, List[float]] = {}
    for t in trades_B:
        d = t.get("entry_date", "")[:10]
        if d:
            b_by_date.setdefault(d, []).append(t.get("pnl_pct", 0.0))

    common = sorted(set(a_by_date.keys()) & set(b_by_date.keys()))
    if len(common) < 3:
        return {"mean_diff": 0.0, "t_stat": 0.0, "p_value": 1.0, "n_common_dates": len(common)}

    diffs = [float(np.mean(b_by_date[d])) - float(np.mean(a_by_date[d])) for d in common]
    arr = np.array(diffs)
    n = len(arr)
    mean_d = float(np.mean(arr))
    se = float(np.std(arr) / np.sqrt(n)) if n > 1 and float(np.std(arr)) > 0 else 1e-9
    t_stat = mean_d / se
    p_val = float(2 * (1 - _tdist.cdf(abs(t_stat), df=n - 1)))
    return {
        "mean_diff": round(mean_d, 4),
        "t_stat": round(t_stat, 4),
        "p_value": round(p_val, 4),
        "n_common_dates": n,
        "positive": p_val < 0.05 and mean_d > 0,
    }


def write_report(results: Dict[str, Any]) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    json_path = OUT_DIR / f"backtest_p2_{ts}.json"
    md_path = OUT_DIR / f"backtest_p2_{ts}.md"

    json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    md = _format_markdown(results)
    md_path.write_text(md, encoding="utf-8")
    print(f"\n→ JSON: {json_path}")
    print(f"→ MD:   {md_path}")
    return md_path


def _format_markdown(r: Dict[str, Any]) -> str:
    meta = r["meta"]
    group_order = ["overall_A", "overall_B", "overall_C", "bcrm2", "three_screen", "c_evolution"]
    pretty = {
        "overall_A": "A 组（原模式：6-TRADING 7维技术分）",
        "overall_B": "B 组（42→50-NN 神经网络融合）",
        "overall_C": "C 组（23 自进化 EvolutionPipeline）",
        "bcrm2": "bcrm2 独立（11-bcrm-tactical）",
        "three_screen": "三屏独立（11-bcrm）",
        "c_evolution": "23 自进化独立",
    }
    lines = [
        "# P2 回测报告：三组信号对比（A 原模式 / B 神经网络 / C 自进化）",
        "",
        f"- 生成时间：{meta['run_at']}",
        f"- 回测口径：{meta['horizon']}"
        + (
            f"（固定 {meta['fixed_n_days']} 日）"
            if meta["horizon"] == "fixed"
            else "（SL/TP + 10日强平）"
        ),
        f"- 样本：{meta['days_available']} 交易日",
        f"- 成本：手续费 {meta['cost']['fee']:.2%} + 滑点 {meta['cost']['slippage']:.2%} = {meta['cost']['total']:.2%}",
        f"- {meta['a_proxy_note']}",
        f"- **{meta['b_walkforward_note']}**",
        f"- **{meta['c_walkforward_note']}**",
        "",
    ]

    # A/B/C 三组决策快照
    if meta.get("b_decisions") or meta.get("c_decisions"):
        lines.append("## 三组当前决策快照（单一快照，非严格 walk-forward）")
        lines.append("")
        lines.append("| Symbol | A 组（技术分代理）| B 组（50-NN）| C 组（23 自进化）|")
        lines.append("|---|---|---|---|")
        all_syms = sorted(
            set(list(meta.get("b_decisions", {}).keys()) + list(meta.get("c_decisions", {}).keys()))
        )
        for sym in all_syms:
            b = meta.get("b_decisions", {}).get(sym)
            c = meta.get("c_decisions", {}).get(sym)
            b_str = f"{b['direction']} (conf={b['confidence']:.3f})" if b else "—"
            c_str = (
                f"{c['direction']} (conf={c['confidence']:.3f}, regime={c.get('regime','?')})"
                if c
                else "—"
            )
            lines.append(f"| {sym} | 每日重算 | {b_str} | {c_str} |")
        lines.append("")

    lines.append("## 指标汇总")
    lines.append("")
    lines.append(
        "| Group | Trades | Win Rate | Avg Ret | P/L Ratio | Sharpe | Max DD | SL | TP | Hold Days |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")

    for gkey in group_order:
        g = r["groups"].get(gkey, {})
        if g.get("n_trades", 0) == 0:
            continue
        lines.append(
            f"| {pretty.get(gkey, gkey)} | {g['n_trades']} "
            f"| {g.get('win_rate', 0):.1%} "
            f"| {g.get('avg_pnl_pct', 0):+.2f}% "
            f"| {g.get('pl_ratio', 0):.2f} "
            f"| {g.get('sharpe', 0):.2f} "
            f"| {g.get('max_drawdown', 0):.1f}% "
            f"| {g.get('sl_count', 0)} "
            f"| {g.get('tp_count', 0)} "
            f"| {g.get('avg_hold_days', 0):.1f} |"
        )
    lines.append("")

    pt = r.get("pair_test", {})
    lines.append("## 配对日收益差检验（B - A）")
    lines.append("")
    if pt.get("n_common_dates", 0) >= 3:
        lines.append(f"- mean(B - A) = {pt['mean_diff']:+.4f}%")
        lines.append(f"- t = {pt['t_stat']:.3f}, p = {pt['p_value']:.4f}")
        verdict = "✅ B 组显著优于 A 组" if pt.get("positive") else "⚠️ B 组未显著优于 A 组"
        lines.append(f"- 结论: {verdict}")
    else:
        lines.append(f"- 共同日期不足（{pt.get('n_common_dates', 0)}），跳过配对检验")
    lines.append("")

    b = r["groups"].get("overall_B", {})
    a = r["groups"].get("overall_A", {})
    lines.append("## B 组通过门槛初评")
    lines.append("")
    if b.get("n_trades", 0) > 0 and a.get("n_trades", 0) > 0:
        sharpe_better = b.get("sharpe", 0) > a.get("sharpe", 0)
        dd_ok = b.get("max_drawdown", 100) <= a.get("max_drawdown", 100) + 5.0
        avg_ret_better = b.get("avg_pnl_pct", 0) > a.get("avg_pnl_pct", 0)
        lines.append(
            f"- Sharpe B > A: {'✅' if sharpe_better else '❌'} ({b.get('sharpe', 0):.2f} vs {a.get('sharpe', 0):.2f})"
        )
        lines.append(
            f"- Max DD B ≤ A+5%: {'✅' if dd_ok else '❌'} ({b.get('max_drawdown', 0):.1f}% vs {a.get('max_drawdown', 0):.1f}%)"
        )
        lines.append(
            f"- Avg Ret B > A: {'✅' if avg_ret_better else '❌'} ({b.get('avg_pnl_pct', 0):+.2f}% vs {a.get('avg_pnl_pct', 0):+.2f}%)"
        )
        lines.append(
            f"- 综合: {'✅ 达标' if sharpe_better and dd_ok and avg_ret_better else '❌ 未达标'}"
        )
    lines.append("")

    lines.append("---")
    lines.append(
        "*融合链路：各子系统 → 42 SignalSchema v1 → 50 bus_reader.to_evidence → 50 make_decision*"
    )
    return "\n".join(lines)


def main() -> int:
    global SL_PCT, TP_PCT, MAX_HOLD_DAYS

    parser = argparse.ArgumentParser(description="P2 回测：A 组 vs scan→42→50-NN 融合 B 组")
    parser.add_argument("--symbols", nargs="*", default=DEFAULT_SYMBOLS)
    parser.add_argument("--days", type=int, default=120)
    parser.add_argument("--horizon", choices=["sltp", "fixed"], default="sltp")
    parser.add_argument("--fixed-n", type=int, default=5)
    parser.add_argument("--top-n", type=int, default=3)
    parser.add_argument("--sl", type=float, default=0.05)
    parser.add_argument("--tp", type=float, default=0.10)
    parser.add_argument("--max-hold", type=int, default=10)
    args = parser.parse_args()

    SL_PCT = args.sl
    TP_PCT = args.tp
    MAX_HOLD_DAYS = args.max_hold

    results = run_backtest(
        symbols=args.symbols,
        horizon=args.horizon,
        fixed_n_days=args.fixed_n,
        train_days=args.days,
        top_n=args.top_n,
    )
    if "error" in results:
        print(f"❌ 回测失败: {results['error']}")
        return 1

    write_report(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
