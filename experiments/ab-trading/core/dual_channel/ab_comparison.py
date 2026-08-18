#!/usr/bin/env python3
"""
AB 对比框架 (A/B Comparison Framework)

P2-8 落地前置条件：验证双通道决策的 path_advantage ≥ +0.2。
在同一历史数据上对比：
  A组（baseline）：单通道（左脑 → A7 阈值门禁）
  B组（treatment）：双通道（左脑 + 右脑 → 胼胝体整合）

复用：
  - SimpleBacktestEngine（历史K线回测）
  - evaluation_engine.compute_path_advantage（path_advantage 计算）

启动：
  cd experiments/ab-trading
  python3 -m core.dual_channel.ab_comparison --coin BTC --bars 500
  python3 -m core.dual_channel.ab_comparison --help
"""
from __future__ import annotations
import sys
import json
import time
import argparse
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any

from .corpus_callosum import CorpusCallosum, ChannelResult, IntegrationResult
from .dual_channel_runner import DualChannelRunner


# ── 注入 4-MEMORY 路径（复用 evaluation_engine）──────────────────
_MEM_TOOLS = (
    Path(__file__).resolve().parents[4]
    / "4-MEMORY" / "9-工具与接口"
)
if str(_MEM_TOOLS) not in sys.path:
    sys.path.insert(0, str(_MEM_TOOLS))

_EVAL_AVAILABLE = False
try:
    from evaluation_engine import compute_path_advantage, decide_learning_action
    from evaluation_engine import EvaluationSample
    _EVAL_AVAILABLE = True
except Exception:
    pass


@dataclass
class TradeRecord:
    """单笔交易记录（AB 对比用）"""
    bar: int
    direction: str        # LONG / SHORT / HOLD
    confidence: float
    entry_price: float
    exit_price: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: str = ""  # tp / sl / time / gate_reject
    agreement_level: str = ""  # B组专属：整合等级
    divergence_flag: bool = False


@dataclass
class ChannelStats:
    """单组回测统计"""
    total_signals: int = 0       # 总信号数（含被门禁拒绝）
    traded: int = 0              # 实际交易数
    wins: int = 0
    losses: int = 0
    hold_rejected: int = 0       # 被门禁拒绝数
    total_pnl_pct: float = 0.0
    avg_confidence: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    win_rate: float = 0.0
    divergences: int = 0         # B组专属：左右分歧次数
    full_consensus: int = 0      # B组专属：三者一致次数

    def to_metrics(self) -> Dict[str, float]:
        """转为 evaluation_engine 期望的 outcome_metrics 格式"""
        return {
            "task_completion_success": 1.0 if self.traded > 0 else 0.0,
            "hard_gate_violation_count": 0.0,
            "rework_count": float(self.hold_rejected),
            "duration_minutes": float(self.total_signals),
            "follow_score": self.avg_confidence,
            "win_rate": self.win_rate,
            "total_pnl_pct": self.total_pnl_pct,
            "sharpe_ratio": self.sharpe_ratio,
            "max_drawdown_pct": self.max_drawdown_pct,
        }


@dataclass
class ABComparisonReport:
    """AB 对比报告"""
    coin: str
    bars: int
    group_a: ChannelStats
    group_b: ChannelStats
    path_advantage: float
    decision: str          # upgrade / alert / observe
    reason: str
    yijing_available: bool
    timestamp: str = ""

    def summary(self) -> str:
        """生成可读摘要"""
        lines = [
            f"=== AB 对比报告: {self.coin} ({self.bars} bars) ===",
            f"时间: {self.timestamp}",
            f"Yijing引擎: {'✅ 可用' if self.yijing_available else '❌ 不可用（右脑仅做梦部）'}",
            "",
            f"--- A组（单通道 baseline）---",
            f"  信号数: {self.group_a.total_signals}  交易数: {self.group_a.traded}",
            f"  胜率: {self.group_a.win_rate:.1%}  总收益: {self.group_a.total_pnl_pct:+.2f}%",
            f"  平均置信度: {self.group_a.avg_confidence:.1%}  夏普: {self.group_a.sharpe_ratio:.2f}",
            f"  门禁拒绝: {self.group_a.hold_rejected}",
            "",
            f"--- B组（双通道 treatment）---",
            f"  信号数: {self.group_b.total_signals}  交易数: {self.group_b.traded}",
            f"  胜率: {self.group_b.win_rate:.1%}  总收益: {self.group_b.total_pnl_pct:+.2f}%",
            f"  平均置信度: {self.group_b.avg_confidence:.1%}  夏普: {self.group_b.sharpe_ratio:.2f}",
            f"  门禁拒绝: {self.group_b.hold_rejected}",
            f"  三者一致: {self.group_b.full_consensus}  左右分歧: {self.group_b.divergences}",
            "",
            f"--- path_advantage ---",
            f"  值: {self.path_advantage:+.4f}",
            f"  决策: {self.decision}",
            f"  理由: {self.reason}",
            "",
            f"  落地门槛: path_advantage ≥ +0.2 → {'✅ 通过' if self.path_advantage >= 0.2 else '❌ 未通过'}",
        ]
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "coin": self.coin,
            "bars": self.bars,
            "group_a": asdict(self.group_a),
            "group_b": asdict(self.group_b),
            "path_advantage": round(self.path_advantage, 4),
            "decision": self.decision,
            "reason": self.reason,
            "yijing_available": self.yijing_available,
            "timestamp": self.timestamp,
        }


class ABComparison:
    """
    AB 对比回测框架

    用法：
        ab = ABComparison()
        report = ab.run(coin="BTC", bars=500)
        print(report.summary())
    """

    def __init__(
        self,
        corpus_callosum: Optional[CorpusCallosum] = None,
        gate_threshold: float = 0.65,
    ):
        self.cc = corpus_callosum or CorpusCallosum(gate_threshold=gate_threshold)
        self.gate_threshold = gate_threshold
        self._backtest_engine = None
        self._dual_runner = DualChannelRunner(
            corpus_callosum=self.cc,
            right_channel_enabled=True,
        )

    # ── 主入口 ────────────────────────────────────────────────────

    def run(
        self,
        coin: str = "BTC",
        bars: int = 500,
        klines: Optional[List[Dict]] = None,
    ) -> ABComparisonReport:
        """
        运行 AB 对比回测。

        Args:
            coin: 交易标的
            bars: 回测K线数量
            klines: 预加载的K线数据（None 则从缓存/API获取）

        Returns:
            ABComparisonReport
        """
        from datetime import datetime, timezone

        # ── 获取K线数据 ────────────────────────────────────────────
        if klines is None:
            klines = self._fetch_klines(coin, bars)
        if len(klines) < 50:
            return self._empty_report(coin, bars, "K线数据不足")

        # ── A组：单通道回测 ────────────────────────────────────────
        trades_a, stats_a = self._run_single_channel(klines, coin)

        # ── B组：双通道回测 ────────────────────────────────────────
        trades_b, stats_b = self._run_dual_channel(klines, coin)

        # ── 计算 path_advantage ───────────────────────────────────
        path_adv, decision, reason = self._compute_advantage(stats_a, stats_b)

        return ABComparisonReport(
            coin=coin,
            bars=len(klines),
            group_a=stats_a,
            group_b=stats_b,
            path_advantage=path_adv,
            decision=decision,
            reason=reason,
            yijing_available=self._dual_runner.status()["yijing_available"],
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    # ── A组：单通道 ────────────────────────────────────────────────

    def _run_single_channel(
        self, klines: List[Dict], coin: str
    ) -> tuple[List[TradeRecord], ChannelStats]:
        """A组：左脑单通道 → A7 阈值门禁"""
        trades = []
        position = None
        entry_price = 0.0
        entry_bar = 0

        closes = [float(k.get("c", 0)) for k in klines]
        volumes = [float(k.get("v", 0)) for k in klines]

        for i in range(50, len(closes)):
            price = closes[i]
            mkt = self._build_mkt_data(klines, i, coin)

            # 左脑信号：简单技术分析（模拟 A0-A3 链输出）
            left = self._simulate_left_brain(mkt)

            # A7 门禁（单通道阈值）
            gate_passed = left.confidence >= self.gate_threshold and left.direction != "HOLD"

            if not gate_passed:
                if position is None:
                    trades.append(TradeRecord(
                        bar=i, direction="HOLD", confidence=left.confidence,
                        entry_price=price, exit_reason="gate_reject",
                    ))
                continue

            # 开仓
            if position is None and left.direction != "HOLD":
                position = left.direction
                entry_price = price
                entry_bar = i

            # 平仓检查
            if position:
                exit_price, exit_reason = self._check_exit(
                    position, entry_price, klines, i, entry_bar
                )
                if exit_price > 0:
                    pnl = self._calc_pnl(position, entry_price, exit_price)
                    trades.append(TradeRecord(
                        bar=entry_bar, direction=position,
                        confidence=left.confidence,
                        entry_price=entry_price, exit_price=exit_price,
                        pnl_pct=pnl, exit_reason=exit_reason,
                    ))
                    position = None
                    entry_price = 0.0

        # 强制平仓未关闭的仓位
        if position:
            exit_price = closes[-1]
            pnl = self._calc_pnl(position, entry_price, exit_price)
            trades.append(TradeRecord(
                bar=entry_bar, direction=position,
                confidence=0.5,
                entry_price=entry_price, exit_price=exit_price,
                pnl_pct=pnl, exit_reason="time_exit",
            ))

        stats = self._calc_stats(trades)
        return trades, stats

    # ── B组：双通道 ────────────────────────────────────────────────

    def _run_dual_channel(
        self, klines: List[Dict], coin: str
    ) -> tuple[List[TradeRecord], ChannelStats]:
        """B组：左脑 + 右脑 → 胼胝体整合"""
        trades = []
        position = None
        entry_price = 0.0
        entry_bar = 0

        closes = [float(k.get("c", 0)) for k in klines]

        # 模拟记忆数据
        memory = {"recent_decisions": [], "loss_streaks": 0}

        for i in range(50, len(closes)):
            price = closes[i]
            mkt = self._build_mkt_data(klines, i, coin)

            # 左脑信号
            left = self._simulate_left_brain(mkt)
            a0_dir = left.metadata.get("a0_direction", "HOLD")

            # 双通道运行
            decision = self._dual_runner.run(mkt, memory, left, a0_dir)
            integration = decision.integration

            # 更新记忆
            memory["recent_decisions"].append({
                "action": integration.direction,
                "confidence": integration.confidence,
            })
            if len(memory["recent_decisions"]) > 20:
                memory["recent_decisions"] = memory["recent_decisions"][-20:]

            if not integration.gate_passed:
                if position is None:
                    trades.append(TradeRecord(
                        bar=i, direction="HOLD",
                        confidence=integration.confidence,
                        entry_price=price, exit_reason="gate_reject",
                        agreement_level=integration.agreement_level.value,
                        divergence_flag=integration.divergence_flag,
                    ))
                continue

            # 开仓
            if position is None and integration.direction != "HOLD":
                position = integration.direction
                entry_price = price
                entry_bar = i

            # 平仓检查
            if position:
                exit_price, exit_reason = self._check_exit(
                    position, entry_price, klines, i, entry_bar
                )
                if exit_price > 0:
                    pnl = self._calc_pnl(position, entry_price, exit_price)
                    trades.append(TradeRecord(
                        bar=entry_bar, direction=position,
                        confidence=integration.confidence,
                        entry_price=entry_price, exit_price=exit_price,
                        pnl_pct=pnl, exit_reason=exit_reason,
                        agreement_level=integration.agreement_level.value,
                        divergence_flag=integration.divergence_flag,
                    ))
                    position = None
                    entry_price = 0.0

        # 强制平仓
        if position:
            exit_price = closes[-1]
            pnl = self._calc_pnl(position, entry_price, exit_price)
            trades.append(TradeRecord(
                bar=entry_bar, direction=position,
                confidence=0.5,
                entry_price=entry_price, exit_price=exit_price,
                pnl_pct=pnl, exit_reason="time_exit",
            ))

        stats = self._calc_stats(trades)
        return trades, stats

    # ── 辅助方法 ──────────────────────────────────────────────────

    def _simulate_left_brain(self, mkt: Dict) -> ChannelResult:
        """模拟左脑 A0-A3 链输出（简化版，实际应调用 chain_router）"""
        price = mkt.get("price", 0)
        ema20 = mkt.get("ema20", price)
        ema50 = mkt.get("ema50", price)
        rsi = mkt.get("rsi14", 50)
        ch24 = mkt.get("change_24h", 0)
        vol_ratio = mkt.get("vol_ratio", 1.0)

        # A0 矛盾方向
        if ch24 > 1.5 and price > ema20:
            a0_dir = "LONG"
        elif ch24 < -1.5 and price < ema20:
            a0_dir = "SHORT"
        else:
            a0_dir = "HOLD"

        # 技术面信号
        if price > ema20 > ema50 and rsi < 70:
            direction = "LONG"
            conf = 0.65 + min(vol_ratio * 0.03, 0.15)
        elif price < ema20 < ema50 and rsi > 30:
            direction = "SHORT"
            conf = 0.65 + min(vol_ratio * 0.03, 0.15)
        elif abs(ch24) > 2:
            direction = "LONG" if ch24 > 0 else "SHORT"
            conf = 0.60
        else:
            direction = "HOLD"
            conf = 0.45

        return ChannelResult(
            direction=direction,
            confidence=min(conf, 0.90),
            source="left_brain",
            reasoning=[f"左脑: EMA排列+RSI+量比 → {direction} {conf:.0%}"],
            metadata={"a0_direction": a0_dir},
        )

    def _build_mkt_data(self, klines: List[Dict], idx: int, coin: str) -> Dict:
        """从K线数据构建市场数据 dict"""
        closes = [float(k.get("c", 0)) for k in klines[:idx+1]]
        volumes = [float(k.get("v", 0)) for k in klines[:idx+1]]
        highs = [float(k.get("h", 0)) for k in klines[:idx+1]]
        lows = [float(k.get("l", 0)) for k in klines[:idx+1]]

        price = closes[idx] if closes else 0
        # EMA
        def ema(data, n):
            if len(data) < n:
                return data[-1] if data else 0
            k = 2 / (n + 1)
            e = data[0]
            for p in data:
                e = p * k + e * (1 - k)
            return e

        # RSI
        def rsi_calc(data, n=14):
            if len(data) < n + 1:
                return 50.0
            deltas = [data[i] - data[i-1] for i in range(1, len(data))]
            gains = [max(d, 0) for d in deltas]
            losses = [max(-d, 0) for d in deltas]
            avg_g = sum(gains[:n]) / n
            avg_l = sum(losses[:n]) / n
            for i in range(n, len(gains)):
                avg_g = (avg_g * (n-1) + gains[i]) / n
                avg_l = (avg_l * (n-1) + losses[i]) / n
            if avg_l == 0:
                return 100.0
            return 100 - 100 / (1 + avg_g / avg_l)

        ch24 = (closes[idx] - closes[idx-24]) / closes[idx-24] if idx >= 24 and closes[idx-24] > 0 else 0
        avg_vol = sum(volumes[max(0, idx-20):idx+1]) / min(20, idx+1) if idx > 0 else 1
        vol_ratio = volumes[idx] / avg_vol if avg_vol > 0 else 1.0

        return {
            "coin": coin,
            "price": price,
            "ema20": ema(closes, 20),
            "ema50": ema(closes, 50),
            "rsi14": rsi_calc(closes),
            "change_24h": ch24 * 100,
            "vol_ratio": vol_ratio,
            "funding_rate": 0.0001,
            "regime": "TREND" if abs(ch24) > 2 else "RANGE",
            "high": highs[idx] if highs else 0,
            "low": lows[idx] if lows else 0,
        }

    def _check_exit(
        self, position: str, entry_price: float,
        klines: List[Dict], idx: int, entry_bar: int
    ) -> tuple:
        """检查止损/止盈/超时"""
        sl_pct, tp_pct = 0.04, 0.08
        high = float(klines[idx].get("h", 0))
        low = float(klines[idx].get("l", 0))

        if position == "LONG":
            sl_price = entry_price * (1 - sl_pct)
            tp_price = entry_price * (1 + tp_pct)
            if low <= sl_price:
                return sl_price, "stop_loss"
            if high >= tp_price:
                return tp_price, "take_profit"
        else:
            sl_price = entry_price * (1 + sl_pct)
            tp_price = entry_price * (1 - tp_pct)
            if high >= sl_price:
                return sl_price, "stop_loss"
            if low <= tp_price:
                return tp_price, "take_profit"

        # 超时平仓（100根K线）
        if idx - entry_bar >= 100:
            return float(klines[idx].get("c", 0)), "time_exit"

        return 0.0, ""

    def _calc_pnl(self, position: str, entry: float, exit_price: float) -> float:
        if entry <= 0:
            return 0.0
        if position == "LONG":
            return (exit_price - entry) / entry
        return (entry - exit_price) / entry

    def _calc_stats(self, trades: List[TradeRecord]) -> ChannelStats:
        """计算回测统计"""
        signal_trades = [t for t in trades if t.direction != "HOLD" or t.exit_reason == "gate_reject"]
        actual_trades = [t for t in trades if t.direction != "HOLD" and t.exit_reason != "gate_reject"]
        rejected = len([t for t in trades if t.exit_reason == "gate_reject"])

        wins = [t for t in actual_trades if t.pnl_pct > 0]
        losses = [t for t in actual_trades if t.pnl_pct <= 0]
        total_pnl = sum(t.pnl_pct for t in actual_trades)

        # 最大回撤
        peak = 0
        current = 0
        max_dd = 0
        for t in actual_trades:
            current += t.pnl_pct
            peak = max(peak, current)
            dd = peak - current
            max_dd = max(max_dd, dd)

        # 夏普比率
        returns = [t.pnl_pct for t in actual_trades]
        avg_ret = sum(returns) / len(returns) if returns else 0
        std_ret = (sum((r - avg_ret)**2 for r in returns) / len(returns))**0.5 if returns else 0
        sharpe = (avg_ret / std_ret) * (len(returns)**0.5) if std_ret > 0 else 0

        # 置信度统计
        confs = [t.confidence for t in signal_trades if t.confidence > 0]
        avg_conf = sum(confs) / len(confs) if confs else 0

        # B组专属统计
        divergences = len([t for t in trades if t.divergence_flag])
        full_consensus = len([t for t in trades if t.agreement_level == "full_consensus"])

        return ChannelStats(
            total_signals=len(signal_trades),
            traded=len(actual_trades),
            wins=len(wins),
            losses=len(losses),
            hold_rejected=rejected,
            total_pnl_pct=round(total_pnl * 100, 2),
            avg_confidence=round(avg_conf, 4),
            max_drawdown_pct=round(max_dd * 100, 2),
            sharpe_ratio=round(sharpe, 4),
            win_rate=round(len(wins) / len(actual_trades), 4) if actual_trades else 0,
            divergences=divergences,
            full_consensus=full_consensus,
        )

    def _compute_advantage(
        self, stats_a: ChannelStats, stats_b: ChannelStats
    ) -> tuple:
        """计算 path_advantage"""
        if not _EVAL_AVAILABLE:
            # 降级：简单对比
            pnl_diff = stats_b.total_pnl_pct - stats_a.total_pnl_pct
            sharpe_diff = stats_b.sharpe_ratio - stats_a.sharpe_ratio
            adv = max(-1.0, min(1.0, (pnl_diff / 100) * 0.5 + (sharpe_diff / 10) * 0.5))
            if adv >= 0.2:
                return adv, "upgrade", f"双通道优于单通道 (pnl差={pnl_diff:+.2f}%, sharpe差={sharpe_diff:+.2f})"
            elif adv <= -0.2:
                return adv, "alert", f"双通道劣于单通道 (pnl差={pnl_diff:+.2f}%, sharpe差={sharpe_diff:+.2f})"
            return adv, "observe", f"无明显差异 (pnl差={pnl_diff:+.2f}%, sharpe差={sharpe_diff:+.2f})"

        # 使用 evaluation_engine
        import time as _time
        ts = int(_time.time())
        baseline = EvaluationSample(
            session_id="A_single",
            task_summary=f"单通道回测 {stats_a.traded} trades",
            skill_ids_injected=[],
            thought_chain_compressed=[],
            action_chain_compressed=[],
            hard_gate_violations=[],
            outcome_metrics=stats_a.to_metrics(),
            timestamp=ts,
        )
        current = EvaluationSample(
            session_id="B_dual",
            task_summary=f"双通道回测 {stats_b.traded} trades",
            skill_ids_injected=["dual_channel"],
            thought_chain_compressed=[],
            action_chain_compressed=[],
            hard_gate_violations=[],
            outcome_metrics=stats_b.to_metrics(),
            timestamp=ts,
        )
        adv = compute_path_advantage(current, baseline)
        result = decide_learning_action(
            path_advantage=adv,
            hard_gate_violation_count=0,
            consecutive_positive=1 if adv > 0 else 0,
            consecutive_negative=1 if adv < 0 else 0,
        )
        return adv, result["decision"], result["reason"]

    def _fetch_klines(self, coin: str, bars: int) -> List[Dict]:
        """从缓存或API获取K线"""
        # __file__ = experiments/ab-trading/core/dual_channel/ab_comparison.py
        # parents[2] = experiments/ab-trading/
        cache_dir = (
            Path(__file__).resolve().parents[2]
            / "data" / "backtest_cache"
        )
        # 尝试多个文件名模式
        for fname in [f"{coin}_4h_{bars}.json", f"{coin}_4h_500.json",
                      f"{coin}_4h_600.json", f"{coin}_4h_200.json"]:
            cache_file = cache_dir / fname
            if cache_file.exists():
                try:
                    with open(cache_file) as f:
                        raw = json.load(f)
                    # 缓存格式: {"cached_at":..., "data":[...]} 或 直接 [...]
                    if isinstance(raw, dict) and "data" in raw:
                        return raw["data"]
                    elif isinstance(raw, list):
                        return raw
                except Exception:
                    pass

        # 尝试从 evolution backtest_engine 获取
        try:
            ab_core = Path(__file__).resolve().parents[2]
            if str(ab_core) not in sys.path:
                sys.path.insert(0, str(ab_core))
            from evolution.backtest_engine import SimpleBacktestEngine
            engine = SimpleBacktestEngine()
            return engine.fetch_historical_klines(coin, "1h", bars)
        except Exception:
            return []

    def _empty_report(self, coin: str, bars: int, reason: str) -> ABComparisonReport:
        from datetime import datetime, timezone
        empty = ChannelStats()
        return ABComparisonReport(
            coin=coin, bars=bars,
            group_a=empty, group_b=empty,
            path_advantage=0.0, decision="observe",
            reason=f"回测失败: {reason}",
            yijing_available=self._dual_runner.status()["yijing_available"],
            timestamp=datetime.now(timezone.utc).isoformat(),
        )


# ── 启动入口 ────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="AB-Trading 双通道回测对比（P2-8 落地前置验证）"
    )
    parser.add_argument("--coin", default="BTC", help="交易标的（默认 BTC）")
    parser.add_argument("--bars", type=int, default=500, help="回测K线数量（默认 500）")
    parser.add_argument("--output", default="", help="报告输出 JSON 路径（默认仅终端）")
    parser.add_argument("--status", action="store_true", help="仅检查环境就绪度")
    args = parser.parse_args()

    if args.status:
        runner = DualChannelRunner()
        print(json.dumps(runner.status(), indent=2, ensure_ascii=False))
        return

    print(f"启动 AB 对比回测: {args.coin} / {args.bars} bars ...")
    ab = ABComparison()
    report = ab.run(coin=args.coin, bars=args.bars)
    print(report.summary())

    if args.output:
        with open(args.output, "w") as f:
            json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
        print(f"\n报告已保存: {args.output}")


if __name__ == "__main__":
    main()
