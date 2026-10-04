"""软投票仲裁层回测脚本 — 多标的并行回测

对比「当前规则3a 固定29H超时强平」vs「软投票仲裁层」的 PnL/胜率/最大回撤，
并输出四 voter 各自独立胜率（用于贝叶斯权重初始化）。

用法:
    python3 shadow_backtest_soft_vote.py
    python3 shadow_backtest_soft_vote.py --symbols BTC,ETH,SKHYNIX
    python3 shadow_backtest_soft_vote.py --okx  # 从OKX API获取K线（需配置okx_client）

设计要点:
    1. K线加载：优先本地CSV，缺失时可选从OKX API获取，均不可用则合成数据验证脚本可用性
    2. 指标计算：复用 shadow_backtest.calc_indicators (含ATR)，新增 swing_low/支撑位/atr_daily
    3. 模拟交易：在特定bar入场 → 持有到29H超时 → 分别用基线/软投票判断
    4. 对比指标：总PnL/胜率/强平次数/四voter独立胜率
    5. SKHYNIX 1289 案例回放：验证支撑位上方不误强平
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 路径设置
SCRIPT_DIR = Path(__file__).resolve().parent  # scripts/
BASE = SCRIPT_DIR.parent  # dreambuddy_evolution/
ARCH_DIR = BASE.parent  # 23-四层闭环自进化交易架构/
REPO_ROOT = ARCH_DIR.parent  # dreambuddy-v2/
KLINE_DIR = REPO_ROOT / "11-易经推理系统" / "scripts" / "data" / "klines"
PERSIST_PATH = BASE / "gene_data" / "soft_vote_weights.jsonl"
REPORT_PATH = BASE / "gene_data" / "soft_vote_backtest_report.json"

# 确保 dreambuddy_evolution 包可被 import（需要 23-四层闭环自进化交易架构 在 sys.path）
if str(ARCH_DIR) not in sys.path:
    sys.path.insert(0, str(ARCH_DIR))

logger = logging.getLogger(__name__)

# 回测参数
DEFAULT_SYMBOLS = ["BTC", "ETH", "SKHYNIX"]
DEFAULT_KLINE_MAP = {
    "BTC": "BTC_4H.csv",
    "ETH": "ETH_1H.csv",
    "SKHYNIX": "SKHYNIX_1H.csv",
}
DEFAULT_OKX_INST = {
    "BTC": "BTC-USDT-SWAP",
    "ETH": "ETH-USDT-SWAP",
    "SKHYNIX": "SKHYNIX-USDT-SWAP",
}
HOLD_BARS_4H = 8   # 4H K线 × 8 = 32H（超过29H超时阈值）
HOLD_BARS_1H = 30  # 1H K线 × 30 = 30H
LOOKBACK = 20
TIMEOUT_SEC = 29 * 3600  # 29H 超时阈值

# SKHYNIX 1289 案例参数（关键验证场景）
SKHYNIX_CASE_ENTRY = 1289.38
SKHYNIX_CASE_SUPPORT = 1270.0  # 假设支撑位
SKHYNIX_CASE_ATR_PCT = 0.025   # SKHYNIX 典型 ATR 2.5%


# ============================================================================
# K线加载
# ============================================================================

def load_klines_from_csv(path: Path) -> List[dict]:
    """从CSV加载K线数据"""
    if not path.exists():
        return []
    rows = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append({
                "timestamp": r.get("timestamp", ""),
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "volume": float(r.get("volume", 0)),
            })
    return rows


def load_klines_from_okx(inst_id: str, bar: str = "1H", limit: int = 500) -> List[dict]:
    """从OKX API获取K线数据"""
    try:
        sys.path.insert(0, str(REPO_ROOT / "11-易经推理系统" / "scripts" / "memory_l4"))
        from okx_client import OKXClient  # type: ignore
        client = OKXClient()
        resp = client.get_kline(inst_id, bar=bar, limit=limit)
        if not resp or not resp.get("ok"):
            logger.warning("OKX API 获取K线失败: %s", inst_id)
            return []
        candles = resp.get("candles", [])
        # OKX 返回 [ts, o, h, l, c, vol, ...] 逆序
        rows = []
        for c in reversed(candles):
            rows.append({
                "timestamp": str(c[0]),
                "open": float(c[1]),
                "high": float(c[2]),
                "low": float(c[3]),
                "close": float(c[4]),
                "volume": float(c[5] or 0),
            })
        return rows
    except Exception as e:
        logger.warning("OKX K线加载异常: %s", e)
        return []


def generate_synthetic_klines(symbol: str, n: int = 200) -> List[dict]:
    """生成合成K线数据（用于验证脚本自身可用性）"""
    import random
    random.seed(hash(symbol) % 2**32)
    base_price = {"BTC": 45000.0, "ETH": 2500.0, "SKHYNIX": 1289.0}.get(symbol, 100.0)
    rows = []
    price = base_price
    for i in range(n):
        vol_pct = random.uniform(0.005, 0.03)
        drift = random.uniform(-0.008, 0.01)
        o = price
        h = o * (1 + vol_pct)
        l = o * (1 - vol_pct)
        c = o * (1 + drift)
        rows.append({
            "timestamp": str(i),
            "open": round(o, 4),
            "high": round(h, 4),
            "low": round(l, 4),
            "close": round(c, 4),
            "volume": round(random.uniform(100, 10000), 2),
        })
        price = c
    return rows


def load_klines(symbol: str, kline_dir: Path, kline_map: dict, use_okx: bool = False) -> List[dict]:
    """加载K线：CSV优先 → OKX次之 → 合成数据兜底"""
    # 1. 尝试CSV
    csv_name = kline_map.get(symbol, f"{symbol}_1H.csv")
    csv_path = kline_dir / csv_name
    rows = load_klines_from_csv(csv_path)
    if rows:
        logger.info("[%s] CSV 加载 %d bars from %s", symbol, len(rows), csv_path)
        return rows
    # 2. 尝试OKX
    if use_okx:
        inst = DEFAULT_OKX_INST.get(symbol, f"{symbol}-USDT-SWAP")
        rows = load_klines_from_okx(inst, bar="1H", limit=500)
        if rows:
            logger.info("[%s] OKX API 加载 %d bars", symbol, len(rows))
            return rows
    # 3. 合成数据兜底
    logger.warning("[%s] CSV/OKX 均不可用，使用合成数据验证脚本逻辑", symbol)
    rows = generate_synthetic_klines(symbol, n=200)
    logger.info("[%s] 合成数据 %d bars", symbol, len(rows))
    return rows


# ============================================================================
# 指标计算（复用 shadow_backtest + 新增 swing_low/support/atr_daily）
# ============================================================================

def calc_indicators(klines: List[dict]) -> List[dict]:
    """计算指标：ATR(14) + swing_low + 支撑位 + atr_daily"""
    bars = [dict(k) for k in klines]
    n = len(bars)

    for i in range(n):
        # ATR(14)
        if i >= 14:
            trs = []
            for j in range(i - 13, i + 1):
                h = bars[j]["high"]
                l = bars[j]["low"]
                prev_c = bars[j - 1]["close"]
                tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
                trs.append(tr)
            bars[i]["atr"] = sum(trs) / 14
        else:
            bars[i]["atr"] = 0.0

        if bars[i]["close"] > 0 and bars[i]["atr"] > 0:
            bars[i]["atr_pct"] = bars[i]["atr"] / bars[i]["close"]
        else:
            bars[i]["atr_pct"] = 0.0

        # MA(ATR)
        if i >= 14:
            atr_window = [bars[j]["atr"] for j in range(i - 14, i)]
            bars[i]["ma_atr"] = sum(atr_window) / 14 if atr_window else bars[i]["atr"]
        else:
            bars[i]["ma_atr"] = bars[i]["atr"]

        # recent_swing_low: 最近 20 bar 的最低点（long 方向）
        if i >= 20:
            bars[i]["recent_swing_low"] = min(bars[j]["low"] for j in range(i - 20, i))
        else:
            bars[i]["recent_swing_low"] = bars[i]["low"]

        # nearest_support_level: swing low + Fibonacci 0.618 + 前低
        bars[i]["nearest_support_level"] = _calc_nearest_support(bars, i)

        # atr_daily: 1H → ×sqrt(24)，4H → ×sqrt(6)
        if bars[i]["atr_pct"] > 0:
            bars[i]["atr_daily"] = bars[i]["atr_pct"] * math.sqrt(24)
        else:
            bars[i]["atr_daily"] = 0.0

    return bars


def _calc_nearest_support(bars: List[dict], i: int) -> float:
    """计算最近支撑位：swing low / Fibonacci 0.618 / 前低"""
    if i < 20:
        return bars[i].get("low", 0.0)
    # 最近 swing low
    swing_low = min(bars[j]["low"] for j in range(max(0, i - 50), i))
    # Fibonacci 0.618 回撤位（基于最近波动区间）
    recent_high = max(bars[j]["high"] for j in range(max(0, i - 50), i))
    recent_low = min(bars[j]["low"] for j in range(max(0, i - 50), i))
    fib_618 = recent_high - (recent_high - recent_low) * 0.618
    # 取离当前价更近的支撑位
    current_close = bars[i]["close"]
    candidates = [swing_low, fib_618, recent_low]
    valid = [c for c in candidates if c > 0 and c < current_close]
    if not valid:
        return swing_low if swing_low > 0 else current_close
    return max(valid, key=lambda x: x)  # 离当前价最近的支撑


# ============================================================================
# 模拟交易
# ============================================================================

def simulate_position(
    klines: List[dict],
    entry_idx: int,
    pos_side: str = "long",
    hold_bars: int = 30,
) -> Optional[dict]:
    """模拟持仓：入场 → 持有 hold_bars → 平仓

    返回持仓期间的逐 bar 数据，用于基线/软投票分别判断
    """
    n = len(klines)
    exit_idx = min(entry_idx + hold_bars, n - 1)
    if exit_idx <= entry_idx:
        return None

    entry_price = klines[entry_idx]["close"]
    bars_data = []
    for j in range(entry_idx, exit_idx + 1):
        bar = klines[j]
        age_sec = (j - entry_idx) * 3600  # 假设 1H K线
        current_price = bar["close"]
        if pos_side == "long":
            upl_ratio = (current_price - entry_price) / entry_price
        else:
            upl_ratio = (entry_price - current_price) / entry_price
        bars_data.append({
            "bar_idx": j,
            "timestamp": bar["timestamp"],
            "current_price": current_price,
            "entry_price": entry_price,
            "upl_ratio": upl_ratio,
            "position_age_sec": age_sec,
            "recent_swing_low": bar.get("recent_swing_low", 0.0),
            "nearest_support_level": bar.get("nearest_support_level", 0.0),
            "atr_pct": bar.get("atr_pct", 0.0),
            "atr_daily": bar.get("atr_daily", 0.0),
            "pos_side": pos_side,
        })

    # 最终平仓 PnL
    exit_price = klines[exit_idx]["close"]
    if pos_side == "long":
        final_pnl = (exit_price - entry_price) / entry_price
    else:
        final_pnl = (entry_price - exit_price) / entry_price

    return {
        "entry_idx": entry_idx,
        "exit_idx": exit_idx,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "final_pnl": final_pnl,
        "bars_data": bars_data,
    }


# ============================================================================
# 基线规则3a：固定29H超时强平
# ============================================================================

def run_baseline_rule(position: dict) -> dict:
    """基线规则3a：29H超时 → 强平

    逻辑：position_age_sec > 29H 时强制 force_close，
    不管盈亏状况（当前线上行为）
    """
    bars_data = position["bars_data"]
    force_close_idx = None
    force_close_pnl = 0.0
    for bd in bars_data:
        # 基线规则3a：position_age >= 29H 即强平（与线上一致）
        if bd["position_age_sec"] >= TIMEOUT_SEC:
            force_close_idx = bd["bar_idx"]
            force_close_pnl = bd["upl_ratio"]
            break

    if force_close_idx is not None:
        return {
            "action": "force_close",
            "exit_bar_idx": force_close_idx,
            "exit_pnl": force_close_pnl,
            "reason": "baseline:timeout_29h_fixed",
        }
    # 未触发超时强平 → 持有到 hold_bars 结束
    return {
        "action": "hold_to_end",
        "exit_bar_idx": position["exit_idx"],
        "exit_pnl": position["final_pnl"],
        "reason": "baseline:hold_to_end",
    }


# ============================================================================
# 软投票仲裁层
# ============================================================================

def run_soft_vote(position: dict, arbitrator: Any) -> dict:
    """软投票仲裁层：29H超时 → 四方案投票 → 仲裁决策"""
    from dreambuddy_evolution.engines.exit_engine.timeout_voters.base_voter import (
        TimeoutVoter,
    )

    bars_data = position["bars_data"]
    voter_votes: Dict[str, List[dict]] = {"A": [], "B": [], "C": [], "D": []}

    for bd in bars_data:
        # 仅在超时后触发软投票（与基线对齐：position_age >= 29H）
        if bd["position_age_sec"] < TIMEOUT_SEC:
            continue

        ctx = {
            "symbol": position.get("symbol", "UNKNOWN"),
            "current_price": bd["current_price"],
            "entry_price": bd["entry_price"],
            "upl_ratio": bd["upl_ratio"],
            "position_age_sec": bd["position_age_sec"],
            "recent_swing_low": bd["recent_swing_low"],
            "nearest_support_level": bd["nearest_support_level"],
            "atr_pct": bd["atr_pct"],
            "atr_daily": bd["atr_daily"],
            "pos_side": bd["pos_side"],
            "tier": "trend",
        }

        # 记录每个 voter 独立投票（用于统计胜率）
        for voter in arbitrator._voters:
            ticket = voter.evaluate(ctx)
            if ticket is not None:
                voter_votes[ticket.voter_id].append({
                    "bar_idx": bd["bar_idx"],
                    "action": ticket.action,
                    "confidence": ticket.confidence,
                    "reason": ticket.reason,
                    "upl_ratio": bd["upl_ratio"],
                })

        # 调用仲裁层
        decision = arbitrator.arbitrate(ctx)
        if decision is not None and decision.action == "force_close":
            return {
                "action": "force_close",
                "exit_bar_idx": bd["bar_idx"],
                "exit_pnl": bd["upl_ratio"],
                "reason": f"soft_vote:{decision.reason}",
                "voter_votes": voter_votes,
            }
        # adjust_sl_tp 或 hold → 继续持有

    # 未触发软投票强平 → 持有到结束
    return {
        "action": "hold_to_end",
        "exit_bar_idx": position["exit_idx"],
        "exit_pnl": position["final_pnl"],
        "reason": "soft_vote:hold_to_end",
        "voter_votes": voter_votes,
    }


# ============================================================================
# 对比统计
# ============================================================================

def calc_stats(trades: List[dict]) -> dict:
    """计算交易统计"""
    if not trades:
        return {"n": 0, "total_pnl": 0.0, "win_rate": 0.0, "max_drawdown": 0.0, "force_close_count": 0}
    pnls = [t["exit_pnl"] for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    total_pnl = sum(pnls)
    # 最大回撤（累积PnL peak to trough）
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        cum += p
        if cum > peak:
            peak = cum
        dd = peak - cum
        if dd > max_dd:
            max_dd = dd
    force_count = sum(1 for t in trades if t["action"] == "force_close")
    return {
        "n": len(trades),
        "total_pnl": round(total_pnl, 4),
        "win_rate": round(wins / len(pnls), 4),
        "max_drawdown": round(max_dd, 4),
        "force_close_count": force_count,
    }


def calc_voter_stats(voter_votes: Dict[str, List[dict]]) -> dict:
    """计算四 voter 独立胜率（用于贝叶斯权重初始化）"""
    stats = {}
    for vid, votes in voter_votes.items():
        if not votes:
            stats[vid] = {"n": 0, "win_rate": 0.0, "force_close_count": 0, "hold_count": 0}
            continue
        # voter 投 force_close 时的"事后盈亏"（如果 upl < 0 则 voter 判断正确）
        force_close_votes = [v for v in votes if v["action"] == "force_close"]
        hold_votes = [v for v in votes if v["action"] == "hold"]
        # 正确率：force_close 时 upl < 0（避免了亏损）或 hold 时 upl > 0（保住了盈利）
        correct = 0
        for v in force_close_votes:
            if v["upl_ratio"] < 0:
                correct += 1
        for v in hold_votes:
            if v["upl_ratio"] > 0:
                correct += 1
        total = len(votes)
        stats[vid] = {
            "n": total,
            "win_rate": round(correct / total, 4) if total > 0 else 0.0,
            "force_close_count": len(force_close_votes),
            "hold_count": len(hold_votes),
        }
    return stats


# ============================================================================
# SKHYNIX 1289 案例回放
# ============================================================================

def replay_skhynix_case() -> dict:
    """SKHYNIX 1289 案例回放验证

    场景：1289.38 入场 → 29H 超时 → 亏损 0.88% 场景
    预期：
      - Voter C（支撑位保护）：current_price(1278) > support × 1.02 → hold + SL下移
      - Voter B（ATR 标准化）：SKHYNIX ATR≈2.5%，0.88% < 0.3×2.5%=0.75% → force_close
      - 仲裁结果：≥2 票 hold → 不 force_close
    """
    from dreambuddy_evolution.engines.exit_engine.timeout_voters import (
        TimeoutVoteArbitrator,
    )

    arb = TimeoutVoteArbitrator(persist_path=None, log_fn=lambda msg, level: None)

    # 构造 1289 案例的 context
    ctx = {
        "symbol": "SKHYNIX",
        "current_price": 1278.0,
        "entry_price": SKHYNIX_CASE_ENTRY,
        "upl_ratio": -0.0088,  # 亏损 0.88%
        "position_age_sec": TIMEOUT_SEC + 3600,  # 超时 1h
        "recent_swing_low": 1270.0,
        "nearest_support_level": SKHYNIX_CASE_SUPPORT,
        "atr_pct": SKHYNIX_CASE_ATR_PCT,
        "atr_daily": SKHYNIX_CASE_ATR_PCT * math.sqrt(24),
        "pos_side": "long",
        "tier": "trend",
    }

    # 四 voter 独立投票
    votes = {}
    for voter in arb._voters:
        ticket = voter.evaluate(ctx)
        if ticket is not None:
            votes[ticket.voter_id] = {
                "action": ticket.action,
                "confidence": ticket.confidence,
                "reason": ticket.reason,
            }
        else:
            votes[ticket.voter_id] = {"action": "none", "confidence": 0.0, "reason": "FAIL-OPEN"}

    # 仲裁结果
    decision = arb.arbitrate(ctx)
    arbitration_result = {
        "action": decision.action if decision else "none",
        "reason": decision.reason if decision else "FAIL-OPEN",
        "expected": "hold or adjust_sl_tp (支撑位上方不误强平)",
    }

    return {
        "case": "SKHYNIX 1289 超时强平案例",
        "entry_price": SKHYNIX_CASE_ENTRY,
        "current_price": 1278.0,
        "upl_ratio": -0.0088,
        "support_level": SKHYNIX_CASE_SUPPORT,
        "voter_votes": votes,
        "arbitration": arbitration_result,
        "baseline_would": "force_close (固定29H超时)",
        "improvement": "软投票仲裁层应 hold/adjust_sl_tp（支撑位上方）",
    }


# ============================================================================
# 主回测函数
# ============================================================================

def run_soft_vote_backtest(
    symbols: list[str] | None = None,
    kline_dir: Path | None = None,
    kline_map: dict | None = None,
    use_okx: bool = False,
    hold_bars: int = 30,
) -> dict:
    """多标的并行回测

    Args:
        symbols: 回测标的列表
        kline_dir: K线目录
        kline_map: 标的→CSV文件名映射
        use_okx: 是否从OKX API获取K线
        hold_bars: 持有bar数

    Returns:
        回测报告 dict
    """
    from dreambuddy_evolution.engines.exit_engine.timeout_voters import (
        TimeoutVoteArbitrator,
    )

    symbols = symbols or DEFAULT_SYMBOLS
    kline_dir = kline_dir or KLINE_DIR
    kline_map = kline_map or DEFAULT_KLINE_MAP

    # 初始化仲裁器（使用独立持久化路径，不污染线上权重）
    arb = TimeoutVoteArbitrator(
        persist_path=PERSIST_PATH,
        log_fn=lambda msg, level="INFO": logger.info(msg),
    )

    all_results = {}

    for symbol in symbols:
        logger.info("=" * 60)
        logger.info("[%s] 开始回测", symbol)
        klines = load_klines(symbol, kline_dir, kline_map, use_okx=use_okx)
        if len(klines) < 50:
            logger.warning("[%s] K线数据不足 %d bars, 跳过", symbol, len(klines))
            all_results[symbol] = {"error": "insufficient_data", "bars": len(klines)}
            continue

        klines = calc_indicators(klines)

        # 模拟交易：每 10 bar 取一个入场点
        baseline_trades = []
        soft_vote_trades = []
        all_voter_votes = {"A": [], "B": [], "C": [], "D": []}

        step = 10
        for entry_idx in range(LOOKBACK, len(klines) - hold_bars - 1, step):
            pos = simulate_position(klines, entry_idx, pos_side="long", hold_bars=hold_bars)
            if pos is None:
                continue
            pos["symbol"] = symbol

            # 基线
            baseline = run_baseline_rule(pos)
            baseline_trades.append(baseline)

            # 软投票
            sv = run_soft_vote(pos, arb)
            sv["symbol"] = symbol
            soft_vote_trades.append(sv)

            # 收集 voter 投票
            if "voter_votes" in sv:
                for vid, votes in sv["voter_votes"].items():
                    all_voter_votes[vid].extend(votes)

        baseline_stats = calc_stats(baseline_trades)
        soft_vote_stats = calc_stats(soft_vote_trades)
        voter_stats = calc_voter_stats(all_voter_votes)

        all_results[symbol] = {
            "bars": len(klines),
            "trades": len(baseline_trades),
            "baseline": baseline_stats,
            "soft_vote": soft_vote_stats,
            "voter_stats": voter_stats,
            "improvement": {
                "pnl_delta": round(soft_vote_stats["total_pnl"] - baseline_stats["total_pnl"], 4),
                "force_close_reduction": baseline_stats["force_close_count"] - soft_vote_stats["force_close_count"],
            },
        }
        logger.info("[%s] 基线 PnL=%.4f 胜率=%.2f 强平=%d", symbol,
                     baseline_stats["total_pnl"], baseline_stats["win_rate"],
                     baseline_stats["force_close_count"])
        logger.info("[%s] 软投票 PnL=%.4f 胜率=%.2f 强平=%d", symbol,
                     soft_vote_stats["total_pnl"], soft_vote_stats["win_rate"],
                     soft_vote_stats["force_close_count"])

    # SKHYNIX 案例回放
    skhynix_case = replay_skhynix_case()

    report = {
        "config": {
            "symbols": symbols,
            "hold_bars": hold_bars,
            "timeout_sec": TIMEOUT_SEC,
            "use_okx": use_okx,
        },
        "results": all_results,
        "skhynix_case_replay": skhynix_case,
        "summary": _generate_summary(all_results),
    }
    return report


def _generate_summary(results: dict) -> dict:
    """生成汇总对比"""
    total_baseline_pnl = 0.0
    total_sv_pnl = 0.0
    total_baseline_fc = 0
    total_sv_fc = 0
    valid_symbols = 0
    for sym, r in results.items():
        if "error" in r:
            continue
        total_baseline_pnl += r["baseline"]["total_pnl"]
        total_sv_pnl += r["soft_vote"]["total_pnl"]
        total_baseline_fc += r["baseline"]["force_close_count"]
        total_sv_fc += r["soft_vote"]["force_close_count"]
        valid_symbols += 1
    return {
        "valid_symbols": valid_symbols,
        "total_baseline_pnl": round(total_baseline_pnl, 4),
        "total_soft_vote_pnl": round(total_sv_pnl, 4),
        "pnl_improvement": round(total_sv_pnl - total_baseline_pnl, 4),
        "baseline_force_close": total_baseline_fc,
        "soft_vote_force_close": total_sv_fc,
        "force_close_reduction_pct": round(
            (1 - total_sv_fc / total_baseline_fc) * 100 if total_baseline_fc > 0 else 0, 2
        ),
    }


# ============================================================================
# CLI 入口
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="软投票仲裁层回测")
    parser.add_argument("--symbols", type=str, default=",".join(DEFAULT_SYMBOLS),
                        help="回测标的（逗号分隔）")
    parser.add_argument("--okx", action="store_true", help="从OKX API获取K线")
    parser.add_argument("--hold-bars", type=int, default=30, help="持有bar数")
    parser.add_argument("--output", type=str, default=str(REPORT_PATH),
                        help="报告输出路径")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    logger.info("=" * 70)
    logger.info("软投票仲裁层回测 — 多标的并行验证")
    logger.info("标的: %s | OKX: %s | 持有: %d bars", symbols, args.okx, args.hold_bars)
    logger.info("=" * 70)

    report = run_soft_vote_backtest(
        symbols=symbols,
        use_okx=args.okx,
        hold_bars=args.hold_bars,
    )

    # 保存报告
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    logger.info("报告已保存: %s", output_path)

    # 打印汇总
    print("\n" + "=" * 70)
    print("回测汇总")
    print("=" * 70)
    s = report["summary"]
    print(f"有效标的数: {s['valid_symbols']}")
    print(f"基线总 PnL:      {s['total_baseline_pnl']:.4f}")
    print(f"软投票总 PnL:    {s['total_soft_vote_pnl']:.4f}")
    print(f"PnL 提升:        {s['pnl_improvement']:.4f}")
    print(f"基线强平次数:    {s['baseline_force_close']}")
    print(f"软投票强平次数:  {s['soft_vote_force_close']}")
    print(f"强平减少:        {s['force_close_reduction_pct']:.1f}%")
    print()
    print("SKHYNIX 1289 案例回放:")
    case = report["skhynix_case_replay"]
    print(f"  仲裁结果: {case['arbitration']['action']}")
    print(f"  原因: {case['arbitration']['reason']}")
    print(f"  基线会: {case['baseline_would']}")
    print(f"  改进: {case['improvement']}")
    print()
    print("四 voter 独立胜率:")
    for sym, r in report["results"].items():
        if "error" in r:
            continue
        vs = r.get("voter_stats", {})
        for vid in ["A", "B", "C", "D"]:
            v = vs.get(vid, {})
            print(f"  [{sym}] Voter {vid}: 胜率={v.get('win_rate', 0):.2f} "
                  f"(n={v.get('n', 0)}, FC={v.get('force_close_count', 0)}, Hold={v.get('hold_count', 0)})")


if __name__ == "__main__":
    main()
