#!/usr/bin/env python3
"""
实盘验证脚本 — 用真实BCRM2推理路径验证五角校验效果。

与简化回测的区别：
  - 简化回测：用动量代理供需/资金（32%准确率）
  - 本脚本：走完整BCRM2 ML推理+特征工程路径

验证指标：
  1. 五角校验各源方向一致性
  2. 置信度校准（高置信度信号是否更准确）
  3. 预警有效性（TDA/Ising/力学减速）
  4. 三角校验修正后的置信度与实际收益的关系
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
# SCRIPT_DIR = .../11-易经推理系统/scripts/memory_l4
# 退2层到 11-易经推理系统/
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
sys.path.insert(0, PROJECT_ROOT)

logger = logging.getLogger(__name__)


@dataclass
class RealInferenceRecord:
    """真实推理记录"""
    timestamp: str = ""
    bar_index: int = 0
    # BCRM2 ML结果
    bcrm2_direction: str = ""
    bcrm2_confidence: float = 0.0
    # 五角校验结果
    triangle_result: dict = field(default_factory=dict)
    # 综合结果
    final_confidence: float = 0.0
    final_direction: str = ""
    fail_closed: bool = False
    # 未来实际结果
    future_return_5: float = 0.0
    future_return_10: float = 0.0
    actual_direction: str = ""


@dataclass
class RealVerificationMetrics:
    """实盘验证指标"""
    total_signals: int = 0
    # 方向准确率
    direction_accuracy: float = 0.0
    # 置信度校准
    high_conf_accuracy: float = 0.0
    low_conf_accuracy: float = 0.0
    # 五角校验一致性
    strong_agree_count: int = 0
    majority_agree_count: int = 0
    divergent_count: int = 0
    conflict_count: int = 0
    # 预警有效性
    total_reversal_warnings: int = 0
    reversal_hit_rate: float = 0.0
    tda_warnings: int = 0
    tda_hit_rate: float = 0.0
    ising_alerts: int = 0
    ising_hit_rate: float = 0.0
    # 三角校验修正效果
    adjusted_confidence_accuracy: float = 0.0


class BCRM2RealVerifier:
    """BCRM2实盘路径验证器"""

    def __init__(self, data_dir: str = ""):
        if not data_dir:
            data_dir = os.path.join(PROJECT_ROOT, "scripts", "data", "klines")
        self.data_dir = data_dir
        self.records: List[RealInferenceRecord] = []

    def load_klines(self, symbol: str, timeframe: str = "1H") -> Optional[pd.DataFrame]:
        """加载K线数据"""
        patterns = [f"{symbol}_{timeframe}.csv", f"{symbol}.csv"]
        for pattern in patterns:
            filepath = os.path.join(self.data_dir, pattern)
            if os.path.exists(filepath):
                df = pd.read_csv(filepath)
                if "timestamp" in df.columns:
                    df["timestamp"] = pd.to_datetime(df["timestamp"])
                    df.set_index("timestamp", inplace=True)
                logger.info(f"加载 {pattern}: {len(df)} 根K线")
                return df
        logger.warning(f"未找到 {symbol} {timeframe} 的K线数据")
        return None

    def run_verification(
        self,
        df: pd.DataFrame,
        symbol: str,
        start_idx: int = 500,
        end_idx: int = None,
        step: int = 10,
    ) -> List[RealInferenceRecord]:
        """
        运行实盘路径验证。

        Args:
            df: K线DataFrame
            symbol: 币种
            start_idx: 起始索引（留出训练空间）
            end_idx: 结束索引
            step: 采样步长（减少计算量）
        """
        if end_idx is None:
            end_idx = len(df) - 20

        closes = df["close"].values.astype(float)
        records = []

        # 延迟导入BCRM2Adapter（避免启动时加载慢）
        from scripts.memory_l4.bcrm2_adapter import BCRM2Adapter
        adapter = BCRM2Adapter(
            symbol=symbol,
            timeframe="1H",
            tp_atr=3.0,
            sl_atr=1.5,
            max_hold_bars=60,
        )

        # 首次训练
        train_df = df.iloc[:start_idx].copy()
        logger.info(f"[{symbol}] 首次训练模型...")
        try:
            adapter.train(train_df)
        except Exception as e:
            logger.error(f"[{symbol}] 训练失败: {e}")
            return records

        total_bars = (end_idx - start_idx) // step
        processed = 0

        for idx in range(start_idx, end_idx, step):
            slice_df = df.iloc[:idx + 1].copy()

            # 预测未来收益
            future_5 = (closes[idx + 5] / closes[idx] - 1) if idx + 5 < len(closes) else 0.0
            future_10 = (closes[idx + 10] / closes[idx] - 1) if idx + 10 < len(closes) else 0.0

            # 实际方向
            if future_10 > 0.005:
                actual_dir = "UP"
            elif future_10 < -0.005:
                actual_dir = "DOWN"
            else:
                actual_dir = "FLAT"

            # BCRM2推理（完整路径）
            try:
                result = adapter.infer(slice_df, idx=-1)
            except Exception as e:
                logger.warning(f"[{symbol}] 推理失败(idx={idx}): {e}")
                continue

            record = RealInferenceRecord(
                timestamp=str(df.index[idx]),
                bar_index=idx,
                bcrm2_direction=result.get("direction", "FLAT"),
                bcrm2_confidence=result.get("confidence", 0.0),
                triangle_result=result.get("triangle_verification", {}),
                final_confidence=result.get("confidence", 0.0),
                final_direction=result.get("direction", "FLAT"),
                fail_closed=result.get("fail_closed", False),
                future_return_5=future_5,
                future_return_10=future_10,
                actual_direction=actual_dir,
            )

            records.append(record)

            processed += 1
            if processed % 20 == 0:
                logger.info(f"[{symbol}] 进度: {processed}/{total_bars}")

        self.records = records
        return records

    def compute_metrics(self, records: List[RealInferenceRecord]) -> RealVerificationMetrics:
        """计算验证指标"""
        if not records:
            return RealVerificationMetrics()

        metrics = RealVerificationMetrics(total_signals=len(records))

        # 方向准确率（排除fail_closed和FLAT）
        valid = [r for r in records if not r.fail_closed and r.final_direction != "FLAT"]
        if valid:
            correct = sum(1 for r in valid if r.final_direction == r.actual_direction)
            metrics.direction_accuracy = correct / len(valid)

            # 置信度分档
            high_conf = [r for r in valid if r.final_confidence >= 0.6]
            low_conf = [r for r in valid if r.final_confidence <= 0.4]
            if high_conf:
                metrics.high_conf_accuracy = sum(1 for r in high_conf if r.final_direction == r.actual_direction) / len(high_conf)
            if low_conf:
                metrics.low_conf_accuracy = sum(1 for r in low_conf if r.final_direction == r.actual_direction) / len(low_conf)

        # 五角校验一致性统计
        for r in records:
            triangle = r.triangle_result
            verdict = triangle.get("verdict", "")
            if verdict == "STRONG_AGREE":
                metrics.strong_agree_count += 1
            elif verdict == "MAJORITY_AGREE":
                metrics.majority_agree_count += 1
            elif verdict == "DIVERGENT":
                metrics.divergent_count += 1
            elif verdict == "CONFLICT":
                metrics.conflict_count += 1

        # 预警有效性
        warnings = [r for r in records if r.triangle_result.get("reversal_alert", False)]
        metrics.total_reversal_warnings = len(warnings)
        if warnings:
            hits = sum(1 for r in warnings if abs(r.future_return_10) > 0.01 or r.future_return_10 * r.future_return_5 < 0)
            metrics.reversal_hit_rate = hits / len(warnings)

        # TDA预警
        tda_warnings = []
        for r in records:
            tda = r.triangle_result.get("tda_result", {})
            if tda.get("early_warning", False):
                tda_warnings.append(r)
        metrics.tda_warnings = len(tda_warnings)
        if tda_warnings:
            tda_hits = sum(1 for r in tda_warnings if abs(r.future_return_10) > 0.01)
            metrics.tda_hit_rate = tda_hits / len(tda_warnings)

        # Ising预警
        ising_alerts = []
        for r in records:
            ising = r.triangle_result.get("ising_result", {})
            phase = ising.get("phase", "")
            alert = ising.get("phase_transition_alert", False)
            if phase == "CRITICAL" or alert:
                ising_alerts.append(r)
        metrics.ising_alerts = len(ising_alerts)
        if ising_alerts:
            ising_hits = sum(1 for r in ising_alerts if abs(r.future_return_10) > 0.01)
            metrics.ising_hit_rate = ising_hits / len(ising_alerts)

        return metrics

    def print_report(self, metrics: RealVerificationMetrics, symbol: str):
        """打印验证报告"""
        print(f"\n{'='*80}")
        print(f"  {symbol} 实盘路径验证报告（BCRM2完整推理）")
        print(f"{'='*80}")
        print(f"\n  [方向准确率]")
        print(f"    总信号数: {metrics.total_signals}")
        print(f"    方向准确率: {metrics.direction_accuracy:.1%}")
        print(f"    高置信(>=0.6)准确率: {metrics.high_conf_accuracy:.1%}")
        print(f"    低置信(<=0.4)准确率: {metrics.low_conf_accuracy:.1%}")

        print(f"\n  [五角校验一致性]")
        total_consensus = metrics.strong_agree_count + metrics.majority_agree_count + metrics.divergent_count + metrics.conflict_count
        if total_consensus > 0:
            print(f"    STRONG_AGREE: {metrics.strong_agree_count} ({metrics.strong_agree_count/total_consensus:.1%})")
            print(f"    MAJORITY_AGREE: {metrics.majority_agree_count} ({metrics.majority_agree_count/total_consensus:.1%})")
            print(f"    DIVERGENT: {metrics.divergent_count} ({metrics.divergent_count/total_consensus:.1%})")
            print(f"    CONFLICT: {metrics.conflict_count} ({metrics.conflict_count/total_consensus:.1%})")

        print(f"\n  [预警有效性]")
        print(f"    力学减速预警: {metrics.total_reversal_warnings}次, 命中率={metrics.reversal_hit_rate:.1%}")
        print(f"    TDA拓扑预警: {metrics.tda_warnings}次, 命中率={metrics.tda_hit_rate:.1%}")
        print(f"    Ising相变预警: {metrics.ising_alerts}次, 命中率={metrics.ising_hit_rate:.1%}")


def main():
    logging.basicConfig(level=logging.WARNING, format="%(message)s")

    symbols = ["BTC", "ETH"]
    timeframe = "1H"

    print("=" * 80)
    print("  BCRM2实盘路径验证 — 五角校验效果测试")
    print("=" * 80)
    print(f"\n  币种: {symbols}")
    print(f"  周期: {timeframe}")

    verifier = BCRM2RealVerifier()

    for symbol in symbols:
        df = verifier.load_klines(symbol, timeframe)
        if df is None or len(df) < 800:
            print(f"\n  {symbol} 数据不足，跳过")
            continue

        records = verifier.run_verification(df, symbol, start_idx=500, step=10)
        if not records:
            print(f"\n  {symbol} 推理失败")
            continue

        metrics = verifier.compute_metrics(records)
        verifier.print_report(metrics, symbol)


if __name__ == "__main__":
    main()
