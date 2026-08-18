#!/usr/bin/env python3
"""
实盘验证脚本 — 快速验证五角校验 v3 纯风控版效果（简化版，不重新训练模型）。

验证内容（v3 纯风控版，仅保留预警检测，不干预方向/仓位/置信度）：
  1. P3 风控监控覆盖率（verdict 恒为 P3_RISK_MONITOR）
  2. 置信度校准（v3 不调整，应与基线一致）
  3. 预警有效性（TDA/Ising/力学减速）
  4. P3双重预警止损收紧（TDA+Ising同时触发 → sl_tighten=0.7）
"""
import sys
import os
import json
import time
import logging
import numpy as np
import pandas as pd
from datetime import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# 设置路径
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
sys.path.insert(0, PROJECT_ROOT)

logger = logging.getLogger(__name__)


@dataclass
class VerificationRecord:
    timestamp: str = ""
    bar_index: int = 0
    bcrm2_direction: str = ""
    bcrm2_confidence: float = 0.0
    final_confidence: float = 0.0
    final_direction: str = ""
    fail_closed: bool = False
    verdict: str = ""
    agreement_score: float = 0.0
    # P3预警联动
    position_factor: float = 1.0
    sl_tighten_factor: float = 1.0
    early_exit_signal: bool = False
    # 预警
    reversal_alert: bool = False
    tda_warning: bool = False
    ising_alert: bool = False
    # 未来实际结果
    future_return_10: float = 0.0
    actual_direction: str = ""


@dataclass
class VerificationMetrics:
    total_signals: int = 0
    direction_accuracy: float = 0.0
    high_conf_accuracy: float = 0.0
    low_conf_accuracy: float = 0.0
    # P3 风控监控（v3：verdict 恒为 P3_RISK_MONITOR）
    p3_monitor_count: int = 0
    # 预警有效性
    total_reversal_warnings: int = 0
    reversal_hit_rate: float = 0.0
    tda_warnings: int = 0
    tda_hit_rate: float = 0.0
    ising_alerts: int = 0
    ising_hit_rate: float = 0.0
    # P3双重预警
    dual_warnings: int = 0
    dual_warning_hit_rate: float = 0.0


class FastVerifier:
    """快速验证器（不重新训练模型，用简化推理）"""

    def __init__(self):
        self.records: List[VerificationRecord] = []

    def load_klines(self, symbol: str, timeframe: str = "1H") -> Optional[pd.DataFrame]:
        data_dir = os.path.join(PROJECT_ROOT, "scripts", "data", "klines")
        patterns = [f"{symbol}_{timeframe}.csv", f"{symbol}.csv"]
        for pattern in patterns:
            filepath = os.path.join(data_dir, pattern)
            if os.path.exists(filepath):
                df = pd.read_csv(filepath)
                if "timestamp" in df.columns:
                    df["timestamp"] = pd.to_datetime(df["timestamp"])
                    df.set_index("timestamp", inplace=True)
                return df
        return None

    def run_verification(self, df: pd.DataFrame, symbol: str, step: int = 20) -> List[VerificationRecord]:
        """快速验证：用简化快照推理五角校验"""
        from scripts.memory_l4.triangle_verifier import TriangleVerifier

        verifier = TriangleVerifier()
        closes = df["close"].values.astype(float)
        records = []

        start_idx = 200
        end_idx = len(df) - 20

        total = (end_idx - start_idx) // step

        for idx in range(start_idx, end_idx, step):
            slice_df = df.iloc[:idx + 1].copy()

            # 未来收益
            future_10 = (closes[idx + 10] / closes[idx] - 1) if idx + 10 < len(closes) else 0.0
            actual_dir = "UP" if future_10 > 0.005 else ("DOWN" if future_10 < -0.005 else "FLAT")

            # 简化方向（动量）
            recent_returns = np.diff(np.log(closes[idx-20:idx+1]))
            momentum = np.mean(recent_returns[-10:])
            direction_text = "UP" if momentum > 0.001 else ("DOWN" if momentum < -0.001 else "FLAT")
            confidence = min(1.0, max(0.3, 0.5 + momentum * 50))

            # A0简化结果
            a0_result_dict = {
                "direction_bias": momentum * 20,
                "overall_tension": min(1.0, abs(momentum) * 50),
                "trauma_signal": False,
            }

            # 市场快照
            market_snapshot = {
                "volatility": float(np.std(recent_returns)) if len(recent_returns) > 1 else 0.02,
            }

            # 五角校验
            try:
                triangle_result = verifier.verify(
                    bcrm2_direction=direction_text,
                    bcrm2_confidence=confidence,
                    a0_result_dict=a0_result_dict,
                    market_snapshot=market_snapshot,
                    df=slice_df,
                )
            except Exception as e:
                logger.warning(f"[{symbol}] 校验失败(idx={idx}): {e}")
                continue

            # 提取预警信息
            triangle_dict = triangle_result.to_dict()
            tda_result = triangle_dict.get("tda_result", {})
            ising_result = triangle_dict.get("ising_result", {})
            force_result = triangle_dict.get("force_result", {})

            record = VerificationRecord(
                timestamp=str(df.index[idx]),
                bar_index=idx,
                bcrm2_direction=direction_text,
                bcrm2_confidence=confidence,
                final_confidence=min(1.0, max(0.0, confidence + triangle_result.confidence_adjustment)),
                final_direction=direction_text,
                fail_closed=triangle_result.should_fail_closed,
                verdict=triangle_result.verdict,
                agreement_score=triangle_result.agreement_score,
                position_factor=triangle_result.position_factor,
                sl_tighten_factor=triangle_result.sl_tighten_factor,
                early_exit_signal=triangle_result.early_exit_signal,
                reversal_alert=force_result.get("reversal_warning", False) if force_result else triangle_result.reversal_alert,
                tda_warning=tda_result.get("early_warning", False),
                ising_alert=ising_result.get("phase_transition_alert", False) or ising_result.get("phase") == "CRITICAL",
                future_return_10=future_10,
                actual_direction=actual_dir,
            )

            records.append(record)

        self.records = records
        return records

    def compute_metrics(self, records: List[VerificationRecord]) -> VerificationMetrics:
        """计算验证指标"""
        if not records:
            return VerificationMetrics()

        metrics = VerificationMetrics(total_signals=len(records))

        # 方向准确率
        valid = [r for r in records if not r.fail_closed and r.final_direction != "FLAT"]
        if valid:
            correct = sum(1 for r in valid if r.final_direction == r.actual_direction)
            metrics.direction_accuracy = correct / len(valid)
            high_conf = [r for r in valid if r.final_confidence >= 0.6]
            low_conf = [r for r in valid if r.final_confidence <= 0.4]
            if high_conf:
                metrics.high_conf_accuracy = sum(1 for r in high_conf if r.final_direction == r.actual_direction) / len(high_conf)
            if low_conf:
                metrics.low_conf_accuracy = sum(1 for r in low_conf if r.final_direction == r.actual_direction) / len(low_conf)

        # P3 风控监控（v3：verdict 恒为 P3_RISK_MONITOR，无方向一致性分级）
        for r in records:
            if r.verdict == "P3_RISK_MONITOR":
                metrics.p3_monitor_count += 1

        # 预警有效性
        warnings = [r for r in records if r.reversal_alert]
        metrics.total_reversal_warnings = len(warnings)
        if warnings:
            hits = sum(1 for r in warnings if abs(r.future_return_10) > 0.01)
            metrics.reversal_hit_rate = hits / len(warnings)

        # TDA预警
        tda_warnings = [r for r in records if r.tda_warning]
        metrics.tda_warnings = len(tda_warnings)
        if tda_warnings:
            tda_hits = sum(1 for r in tda_warnings if abs(r.future_return_10) > 0.01)
            metrics.tda_hit_rate = tda_hits / len(tda_warnings)

        # Ising预警
        ising_alerts = [r for r in records if r.ising_alert]
        metrics.ising_alerts = len(ising_alerts)
        if ising_alerts:
            ising_hits = sum(1 for r in ising_alerts if abs(r.future_return_10) > 0.01)
            metrics.ising_hit_rate = ising_hits / len(ising_alerts)

        # P3双重预警
        dual_warnings = [r for r in records if r.early_exit_signal]
        metrics.dual_warnings = len(dual_warnings)
        if dual_warnings:
            dual_hits = sum(1 for r in dual_warnings if abs(r.future_return_10) > 0.01)
            metrics.dual_warning_hit_rate = dual_hits / len(dual_warnings)

        return metrics

    def print_report(self, metrics: VerificationMetrics, symbol: str):
        """打印验证报告"""
        print(f"\n{'='*80}")
        print(f"  {symbol} 五角校验快速验证报告")
        print(f"{'='*80}")
        print(f"\n  [方向准确率]")
        print(f"    总信号数: {metrics.total_signals}")
        print(f"    方向准确率: {metrics.direction_accuracy:.1%}")
        print(f"    高置信(>=0.6)准确率: {metrics.high_conf_accuracy:.1%}")
        print(f"    低置信(<=0.4)准确率: {metrics.low_conf_accuracy:.1%}")

        print(f"\n  [P3 风控监控]")
        if metrics.total_signals > 0:
            print(f"    P3_RISK_MONITOR: {metrics.p3_monitor_count} ({metrics.p3_monitor_count/metrics.total_signals:.1%})")

        print(f"\n  [预警有效性]")
        print(f"    力学减速预警: {metrics.total_reversal_warnings}次, 命中率={metrics.reversal_hit_rate:.1%}")
        print(f"    TDA拓扑预警: {metrics.tda_warnings}次, 命中率={metrics.tda_hit_rate:.1%}")
        print(f"    Ising相变预警: {metrics.ising_alerts}次, 命中率={metrics.ising_hit_rate:.1%}")

        print(f"\n  [P3预警联动策略]")
        print(f"    TDA+Ising双重预警: {metrics.dual_warnings}次, 命中率={metrics.dual_warning_hit_rate:.1%}")


def main():
    logging.basicConfig(level=logging.WARNING, format="%(message)s")

    symbols = ["BTC", "ETH"]
    timeframe = "1H"

    print("=" * 80)
    print("  五角校验快速验证 — P1/P2/P3 优化效果测试")
    print("=" * 80)
    print(f"\n  币种: {symbols}")
    print(f"  周期: {timeframe}")

    verifier = FastVerifier()

    for symbol in symbols:
        df = verifier.load_klines(symbol, timeframe)
        if df is None or len(df) < 300:
            print(f"\n  {symbol} 数据不足，跳过")
            continue

        records = verifier.run_verification(df, symbol, step=20)
        if not records:
            print(f"\n  {symbol} 验证失败")
            continue

        metrics = verifier.compute_metrics(records)
        verifier.print_report(metrics, symbol)


if __name__ == "__main__":
    main()
