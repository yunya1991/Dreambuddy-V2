#!/usr/bin/env python3
"""
Walk-Forward 验证框架

职责：
  将回测结果按时间分成 N 段，逐段对比 BASE vs TEST 方案。
  全段 ≥ 基线（或退化 < 阈值）才判定通过，防止过拟合到特定时段。

设计原则：
  - 模块化：接收已完成的回测 trades，按 exit_idx 分段统计
  - 可配置段数和退化容忍度
  - 输出逐段对比表 + 最终决策

用法：
  from walk_forward_validator import WalkForwardValidator
  validator = WalkForwardValidator(n_segments=5)
  report = validator.validate(base_trades, test_trades, total_bars=1500)
"""
import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class WalkForwardValidator:
    """Walk-Forward 分段验证

    将 trades 按 exit_idx 分成 n_segments 段，逐段对比 metrics。
    通过条件：全段 Calmar 退化 < max_degradation_pct，且整体不退化。
    """

    def __init__(
        self,
        n_segments: int = 5,
        max_degradation_pct: float = 5.0,
        min_pass_segments: int = None,
    ):
        """
        Args:
            n_segments: 分段数（默认5）
            max_degradation_pct: 单段允许的最大退化幅度（%，默认5%）
            min_pass_segments: 最少通过段数（默认 = n_segments，即全段通过）
        """
        self.n_segments = n_segments
        self.max_degradation_pct = max_degradation_pct
        self.min_pass_segments = min_pass_segments or n_segments

    def _segment_trades(
        self, trades: List[Dict], total_bars: int
    ) -> List[List[Dict]]:
        """按 exit_idx 将 trades 分成 n_segments 段"""
        if not trades or total_bars <= 0:
            return [[] for _ in range(self.n_segments)]

        # 找到 exit_idx 的范围
        min_idx = min(t.get("exit_idx", 0) for t in trades)
        max_idx = max(t.get("exit_idx", 0) for t in trades)
        span = max_idx - min_idx + 1
        seg_size = max(1, span // self.n_segments)

        segments = [[] for _ in range(self.n_segments)]
        for t in trades:
            idx = t.get("exit_idx", 0)
            seg = min(self.n_segments - 1, (idx - min_idx) // seg_size)
            segments[seg].append(t)
        return segments

    @staticmethod
    def _calc_metrics(trades: List[Dict]) -> Dict:
        """从 trades 列表计算 metrics"""
        if not trades:
            return {
                "total_return_pct": 0.0,
                "total_trades": 0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "max_drawdown_pct": 0.0,
                "calmar": 0.0,
            }

        total_pnl = sum(t.get("pnl_usd", 0) for t in trades)
        wins = [t for t in trades if t.get("pnl_usd", 0) > 0]
        losses = [t for t in trades if t.get("pnl_usd", 0) <= 0]

        gross_profit = sum(t["pnl_usd"] for t in wins)
        gross_loss = abs(sum(t["pnl_usd"] for t in losses))
        pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        # 简化回撤计算（按 trade 序列）
        cumulative = 0
        peak = 0
        max_dd = 0
        for t in trades:
            cumulative += t.get("pnl_usd", 0)
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > max_dd:
                max_dd = dd

        total_return = total_pnl  # 绝对 PnL 作为收益
        win_rate = len(wins) / len(trades) if trades else 0
        calmar = total_return / max_dd if max_dd > 0 else (float("inf") if total_return > 0 else 0)

        return {
            "total_return_pct": round(total_return, 2),
            "total_trades": len(trades),
            "win_rate": round(win_rate, 4),
            "profit_factor": round(pf, 2),
            "max_drawdown_pct": round(max_dd, 2),
            "calmar": round(calmar, 2) if calmar != float("inf") else 999.0,
        }

    def validate(
        self,
        base_trades: List[Dict],
        test_trades: List[Dict],
        total_bars: int = 1500,
        label_base: str = "BASE",
        label_test: str = "TEST",
    ) -> Dict:
        """执行 walk-forward 验证

        Args:
            base_trades: 基线方案的所有 trades
            test_trades: 测试方案的所有 trades
            total_bars: 总 bar 数（用于分段）
            label_base / label_test: 方案标签

        Returns:
            验证报告 dict（含逐段对比、整体对比、最终决策）
        """
        base_segs = self._segment_trades(base_trades, total_bars)
        test_segs = self._segment_trades(test_trades, total_bars)

        segment_reports = []
        pass_count = 0

        for i in range(self.n_segments):
            bm = self._calc_metrics(base_segs[i])
            tm = self._calc_metrics(test_segs[i])

            # 退化判定：Calmar 或 收益 退化超过阈值
            ret_delta = tm["total_return_pct"] - bm["total_return_pct"]
            calmar_delta = tm["calmar"] - bm["calmar"]
            wr_delta = tm["win_rate"] - bm["win_rate"]

            # 通过条件：收益不退化超过 max_degradation_pct（相对基线）
            # 或 Calmar 不退化
            if bm["total_return_pct"] != 0:
                ret_degradation = -ret_delta / abs(bm["total_return_pct"]) * 100
            else:
                ret_degradation = 0 if ret_delta >= 0 else 100

            seg_pass = ret_degradation <= self.max_degradation_pct
            if seg_pass:
                pass_count += 1

            segment_reports.append({
                "segment": i + 1,
                "base": bm,
                "test": tm,
                "ret_delta": round(ret_delta, 2),
                "calmar_delta": round(calmar_delta, 2),
                "wr_delta": round(wr_delta * 100, 2),
                "ret_degradation_pct": round(ret_degradation, 1),
                "pass": seg_pass,
            })

        # 整体对比
        overall_base = self._calc_metrics(base_trades)
        overall_test = self._calc_metrics(test_trades)

        overall_ret_delta = overall_test["total_return_pct"] - overall_base["total_return_pct"]
        overall_wr_delta = overall_test["win_rate"] - overall_base["win_rate"]
        overall_calmar_delta = overall_test["calmar"] - overall_base["calmar"]

        # 最终决策：通过段数 >= min_pass_segments 且整体不退化
        overall_pass = (
            pass_count >= self.min_pass_segments
            and overall_ret_delta >= 0
        )

        return {
            "n_segments": self.n_segments,
            "max_degradation_pct": self.max_degradation_pct,
            "pass_count": pass_count,
            "min_pass_segments": self.min_pass_segments,
            "overall_pass": overall_pass,
            "overall_base": overall_base,
            "overall_test": overall_test,
            "overall_ret_delta": round(overall_ret_delta, 2),
            "overall_wr_delta": round(overall_wr_delta * 100, 2),
            "overall_calmar_delta": round(overall_calmar_delta, 2),
            "segments": segment_reports,
            "label_base": label_base,
            "label_test": label_test,
        }

    @staticmethod
    def format_report(report: Dict) -> str:
        """格式化验证报告为可读字符串"""
        lines = []
        lines.append("=" * 100)
        lines.append(f"  Walk-Forward 验证报告 ({report['n_segments']} 段)")
        lines.append(f"  通过段数: {report['pass_count']}/{report['n_segments']} "
                     f"(最少需 {report['min_pass_segments']})")
        lines.append(f"  单段最大退化容忍: {report['max_degradation_pct']}%")
        lines.append("=" * 100)

        # 逐段对比表
        lines.append(f"  {'段':>4}  {'BASE收益':>10}  {'TEST收益':>10}  {'差值':>8}  "
                     f"{'BASE胜率':>8}  {'TEST胜率':>8}  {'退化%':>7}  {'通过':>4}")
        lines.append("-" * 100)
        for seg in report["segments"]:
            lines.append(
                f"  {seg['segment']:>4}  "
                f"{seg['base']['total_return_pct']:>+10.2f}  "
                f"{seg['test']['total_return_pct']:>+10.2f}  "
                f"{seg['ret_delta']:>+8.2f}  "
                f"{seg['base']['win_rate']*100:>7.1f}%  "
                f"{seg['test']['win_rate']*100:>7.1f}%  "
                f"{seg['ret_degradation_pct']:>+6.1f}%  "
                f"{'✅' if seg['pass'] else '❌'}"
            )
        lines.append("-" * 100)

        # 整体对比
        ob = report["overall_base"]
        ot = report["overall_test"]
        lines.append(f"  {'整体':>4}  "
                     f"{ob['total_return_pct']:>+10.2f}  "
                     f"{ot['total_return_pct']:>+10.2f}  "
                     f"{report['overall_ret_delta']:>+8.2f}  "
                     f"{ob['win_rate']*100:>7.1f}%  "
                     f"{ot['win_rate']*100:>7.1f}%  "
                     f"{'':>7}  "
                     f"{'✅' if report['overall_pass'] else '❌'}")
        lines.append("")
        lines.append(f"  最终决策: {'✅ 通过 → 可部署' if report['overall_pass'] else '❌ 未通过 → 回退'}")
        lines.append(f"    - 通过段数: {report['pass_count']}/{report['n_segments']}")
        lines.append(f"    - 整体收益差: {report['overall_ret_delta']:+.2f}")
        lines.append(f"    - 整体胜率差: {report['overall_wr_delta']:+.2f}%")
        lines.append(f"    - 整体Calmar差: {report['overall_calmar_delta']:+.2f}")
        lines.append("=" * 100)

        return "\n".join(lines)
