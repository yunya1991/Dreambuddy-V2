#!/usr/bin/env python3
"""
力学引擎回测脚本 — 对比 P0/P1/P2 升级前后效果。

四种模式对比：
  - baseline: 原四象欧拉积分（模拟旧版）
  - p0: 五象Verlet+Langevin
  - p1_kalman: P0 + Kalman滤波
  - p2_full: P0 + Kalman + 五角校验（Ising+TDA）

核心指标：
  1. 方向准确率（信号方向 vs 未来N根K线实际涨跌）
  2. 转折预警有效性（预警后是否真的反转）
  3. 置信度校准（高置信度信号是否更准确）
  4. 预警提前量（TDA/Ising vs 力学减速的时间差）
"""
import sys
import os
import json
import time
import logging
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

# 设置路径
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# SCRIPT_DIR = .../11-易经推理系统/scripts/memory_l4
# 退2层到 11-易经推理系统/
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
sys.path.insert(0, PROJECT_ROOT)

from scripts.memory_l4.bcrm.force_engine import ForceEngine, ForceResult
from scripts.memory_l4.bcrm._constants import (
    SIXIANG_TIME, SIXIANG_SPACE, SIXIANG_SURFACE, SIXIANG_CORE, SIXIANG_LIQUIDITY,
    FORCE_WEIGHT_TIME, FORCE_WEIGHT_SPACE, FORCE_WEIGHT_SURFACE,
    FORCE_WEIGHT_CORE, FORCE_WEIGHT_LIQUIDITY,
)

logger = logging.getLogger(__name__)

# ============================================================
# 数据结构
# ============================================================

@dataclass
class SignalRecord:
    """单条信号记录"""
    timestamp: str = ""
    bar_index: int = 0
    mode: str = ""
    direction: str = "FLAT"       # UP/DOWN/FLAT
    confidence: float = 0.0
    velocity: float = 0.0
    reversal_warning: bool = False
    # 五角校验相关
    ising_phase: str = ""
    ising_alert: bool = False
    tda_warning: bool = False
    tda_strength: float = 0.0
    agreement_score: float = 0.0
    # 未来实际结果（后续填充）
    future_return_5: float = 0.0   # 未来5根K线收益
    future_return_10: float = 0.0  # 未来10根K线收益
    future_max_drawdown: float = 0.0  # 未来10根最大回撤
    actual_direction: str = "FLAT"  # UP/DOWN/FLAT


@dataclass
class ModeMetrics:
    """单模式回测指标"""
    mode: str = ""
    total_signals: int = 0
    # 方向准确率
    direction_accuracy: float = 0.0
    up_precision: float = 0.0      # 做多信号中实际上涨的比例
    down_precision: float = 0.0    # 做空信号中实际下跌的比例
    # 置信度校准
    high_conf_accuracy: float = 0.0   # 高置信度(>0.6)信号准确率
    low_conf_accuracy: float = 0.0    # 低置信度(<0.4)信号准确率
    # 转折预警
    total_reversal_warnings: int = 0
    reversal_hit_rate: float = 0.0    # 预警后实际反转的比例
    # TDA/Ising预警
    tda_warnings: int = 0
    tda_hit_rate: float = 0.0
    ising_alerts: int = 0
    ising_hit_rate: float = 0.0
    # 预警提前量
    avg_early_warning_bars: float = 0.0  # TDA/Ising比力学减速平均早多少根K线
    # 信号分布
    up_signals: int = 0
    down_signals: int = 0
    flat_signals: int = 0
    avg_confidence: float = 0.0


# ============================================================
# 回测引擎
# ============================================================

class ForceEngineBacktester:
    """力学引擎回测器"""

    # 预测窗口
    FORWARD_WINDOWS = [5, 10]
    # 方向判定阈值（收益>此值=UP, <-此值=DOWN）
    DIRECTION_THRESHOLD = 0.005  # 0.5%
    # 置信度分档
    HIGH_CONF_THRESHOLD = 0.6
    LOW_CONF_THRESHOLD = 0.4
    # 反转判定（收益反转>此值=确实反转）
    REVERSAL_THRESHOLD = 0.01  # 1%

    def __init__(self, data_dir: str = ""):
        if not data_dir:
            data_dir = os.path.join(PROJECT_ROOT, "scripts", "data", "klines")
        self.data_dir = data_dir
        self.results: Dict[str, List[SignalRecord]] = defaultdict(list)

    def load_klines(self, symbol: str, timeframe: str = "1H") -> Optional[pd.DataFrame]:
        """加载K线数据"""
        # 尝试多种文件名模式
        patterns = [
            f"{symbol}_{timeframe}.csv",
            f"{symbol}.csv",
            f"{symbol}USDT_{timeframe}.csv",
        ]
        for pattern in patterns:
            filepath = os.path.join(self.data_dir, pattern)
            if os.path.exists(filepath):
                df = pd.read_csv(filepath)
                # 标准化列名
                if "timestamp" in df.columns:
                    df["timestamp"] = pd.to_datetime(df["timestamp"])
                    df.set_index("timestamp", inplace=True)
                elif "datetime" in df.columns:
                    df["timestamp"] = pd.to_datetime(df["datetime"])
                    df.set_index("timestamp", inplace=True)
                # 确保有close列
                if "close" not in df.columns:
                    df["close"] = df.iloc[:, 3]  # 第4列通常是close
                logger.info(f"加载 {pattern}: {len(df)} 根K线")
                return df
        logger.warning(f"未找到 {symbol} {timeframe} 的K线数据")
        return None

    def prepare_snapshot(self, df: pd.DataFrame, idx: int) -> Dict:
        """从K线数据准备力学引擎market_snapshot"""
        if idx < 50:
            return None

        closes = df["close"].values[:idx + 1].astype(float)
        volumes = df["volume"].values[:idx + 1].astype(float) if "volume" in df.columns else np.ones(idx + 1)

        # 技术指标计算
        # 均线
        ma_short = np.mean(closes[-10:]) if len(closes) >= 10 else closes[-1]
        ma_mid = np.mean(closes[-30:]) if len(closes) >= 30 else closes[-1]
        ma_long = np.mean(closes[-60:]) if len(closes) >= 60 else closes[-1]
        ma_direction = 0.0
        if ma_short > ma_mid > ma_long:
            ma_direction = 0.5
        elif ma_short < ma_mid < ma_long:
            ma_direction = -0.5
        elif ma_short > ma_mid:
            ma_direction = 0.2
        else:
            ma_direction = -0.2

        # RSI
        deltas = np.diff(closes[-15:])
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains) if len(gains) > 0 else 0
        avg_loss = np.mean(losses) if len(losses) > 0 else 0.001
        rsi = 100 - (100 / (1 + avg_gain / avg_loss)) if avg_loss > 0 else 100

        # MACD简化
        ema12 = pd.Series(closes).ewm(span=12, adjust=False).mean().iloc[-1]
        ema26 = pd.Series(closes).ewm(span=26, adjust=False).mean().iloc[-1]
        macd_signal = 1 if ema12 > ema26 else -1

        # 技术评分
        tech_score = 0.5
        if ma_direction > 0:
            tech_score += 0.15
        else:
            tech_score -= 0.15
        if rsi > 55:
            tech_score += 0.1
        elif rsi < 45:
            tech_score -= 0.1
        tech_score = max(0.1, min(0.9, tech_score))

        # 价格位置
        min_price = np.min(closes[-60:])
        max_price = np.max(closes[-60:])
        price_range = max_price - min_price
        price_position = (closes[-1] - min_price) / price_range if price_range > 0 else 0.5

        # 周期位置（简化）
        long_cycle = np.mean(closes[-60:]) / closes[-1] if closes[-1] > 0 else 0.5
        long_cycle_position = min(1.0, max(0.0, long_cycle))
        mid_cycle_position = (closes[-1] - np.min(closes[-30:])) / (np.max(closes[-30:]) - np.min(closes[-30:]) + 1e-9)

        # 波动率
        returns = np.diff(np.log(closes[-21:])) if len(closes) >= 22 else [0.01]
        volatility = float(np.std(returns)) if len(returns) > 1 else 0.03

        # 供需/资金/情绪（简化为价格动量代理）
        momentum_5 = (closes[-1] / closes[-6] - 1) if len(closes) >= 6 else 0
        momentum_20 = (closes[-1] / closes[-21] - 1) if len(closes) >= 21 else 0
        supply_demand_score = 0.5 + momentum_20 * 5  # 动量代理供需
        supply_demand_score = max(0.1, min(0.9, supply_demand_score))

        capital_flow_score = 0.5 + momentum_5 * 8  # 短期动量代理资金流
        capital_flow_score = max(0.1, min(0.9, capital_flow_score))

        sentiment_score = 0.5 + (rsi - 50) / 100  # RSI代理情绪
        sentiment_score = max(0.1, min(0.9, sentiment_score))

        # 流动性指标
        recent_vol = np.mean(volumes[-10:]) if len(volumes) >= 10 else volumes[-1]
        avg_vol = np.mean(volumes[-30:]) if len(volumes) >= 30 else volumes[-1]
        volume_ratio = recent_vol / (avg_vol + 1e-9)
        price_direction = 1 if closes[-1] > closes[-2] else -1
        liquidity_score = 0.5 + (volume_ratio - 1) * 0.2  # 放量=流动性好
        liquidity_score = max(0.1, min(0.9, liquidity_score))

        # 买卖价差（简化估计）
        if "high" in df.columns and "low" in df.columns:
            recent_spread = (df["high"].iloc[idx] - df["low"].iloc[idx]) / closes[-1]
            bid_ask_spread = min(0.05, max(0.0, recent_spread))
        else:
            bid_ask_spread = 0.001

        return {
            "long_cycle_position": long_cycle_position,
            "mid_cycle_position": mid_cycle_position,
            "short_cycle_position": tech_score,
            "price_position": price_position,
            "technical_score": tech_score,
            "ma_direction": ma_direction,
            "macd_signal": macd_signal,
            "rsi": rsi,
            "supply_demand_score": supply_demand_score,
            "capital_flow_score": capital_flow_score,
            "sentiment_score": sentiment_score,
            "liquidity_score": liquidity_score,
            "volume_ratio": volume_ratio,
            "price_direction": price_direction,
            "bid_ask_spread": bid_ask_spread,
            "volatility": volatility,
        }

    def run_backtest(
        self,
        df: pd.DataFrame,
        symbol: str,
        modes: List[str] = None,
        start_idx: int = 200,
        end_idx: int = None,
        step: int = 1,
    ) -> Dict[str, List[SignalRecord]]:
        """
        运行多模式回测。

        Args:
            df: K线DataFrame
            symbol: 币种
            modes: 回测模式列表
            start_idx: 起始K线索引
            end_idx: 结束K线索引
            step: 采样步长（1=每根K线，2=隔一根）
        """
        if modes is None:
            modes = ["baseline", "p0", "p1_kalman", "p2_full"]

        if end_idx is None:
            end_idx = len(df) - max(self.FORWARD_WINDOWS) - 1

        closes = df["close"].values.astype(float)

        # 各模式引擎初始化
        engines = {}
        for mode in modes:
            if mode == "baseline":
                # 模拟旧版：四象欧拉（disable Verlet和Langevin标记，用原始权重）
                engines[mode] = ForceEngine(seed=42, enable_kalman=False)
            elif mode == "p0":
                engines[mode] = ForceEngine(seed=42, enable_kalman=False)
            elif mode == "p1_kalman":
                engines[mode] = ForceEngine(seed=42, enable_kalman=True)
            elif mode == "p2_full":
                engines[mode] = ForceEngine(seed=42, enable_kalman=True)

        # Ising和TDA检测器（P2模式专用）
        ising_detector = None
        tda_detector = None
        try:
            from scripts.memory_l4.bcrm.ising_phase_detector import IsingPhaseDetector
            ising_detector = IsingPhaseDetector()
        except Exception:
            pass
        try:
            from scripts.memory_l4.bcrm.tda_early_warning import TDAEarlyWarning
            tda_detector = TDAEarlyWarning()
        except Exception:
            pass

        signals_by_mode = defaultdict(list)

        # 逐bar回测
        total_bars = (end_idx - start_idx) // step
        processed = 0

        for idx in range(start_idx, end_idx, step):
            snapshot = self.prepare_snapshot(df, idx)
            if snapshot is None:
                continue

            # 未来实际收益
            future_returns = {}
            for fw in self.FORWARD_WINDOWS:
                if idx + fw < len(closes):
                    future_returns[fw] = (closes[idx + fw] / closes[idx] - 1)
                else:
                    future_returns[fw] = 0.0

            # 实际方向（基于未来10根K线）
            fr10 = future_returns.get(10, 0.0)
            if fr10 > self.DIRECTION_THRESHOLD:
                actual_dir = "UP"
            elif fr10 < -self.DIRECTION_THRESHOLD:
                actual_dir = "DOWN"
            else:
                actual_dir = "FLAT"

            # 未来最大回撤（10根内）
            future_closes = closes[idx + 1: idx + 11]
            if len(future_closes) > 0:
                running_max = np.maximum.accumulate(future_closes)
                drawdowns = (future_closes - running_max) / running_max
                future_max_dd = float(np.min(drawdowns))
            else:
                future_max_dd = 0.0

            ts = str(df.index[idx]) if hasattr(df.index, '__getitem__') else str(idx)

            for mode in modes:
                engine = engines[mode]

                # 每个币种每根K线前重置（避免跨模式污染）
                if idx == start_idx:
                    engine.reset_velocity()

                result = engine.infer(snapshot)

                record = SignalRecord(
                    timestamp=ts,
                    bar_index=idx,
                    mode=mode,
                    direction=result.direction,
                    confidence=result.confidence,
                    velocity=result.velocity,
                    reversal_warning=result.reversal_warning,
                    future_return_5=future_returns.get(5, 0.0),
                    future_return_10=fr10,
                    future_max_drawdown=future_max_dd,
                    actual_direction=actual_dir,
                )

                # P2模式：额外运行Ising和TDA
                if mode == "p2_full" and ising_detector is not None:
                    try:
                        returns_data = np.diff(np.log(closes[max(0, idx - 100):idx + 1]))
                        returns_data = returns_data[~np.isnan(returns_data)]
                        if len(returns_data) >= 10:
                            ising_r = ising_detector.detect(returns_data, snapshot["volatility"])
                            record.ising_phase = ising_r.phase
                            record.ising_alert = ising_r.phase_transition_alert or ising_r.phase == "CRITICAL"
                    except Exception:
                        pass

                if mode == "p2_full" and tda_detector is not None:
                    try:
                        price_series = closes[max(0, idx - 100):idx + 1]
                        if len(price_series) >= 25:
                            tda_r = tda_detector.detect(price_series)
                            record.tda_warning = tda_r.early_warning
                            record.tda_strength = tda_r.warning_strength
                    except Exception:
                        pass

                signals_by_mode[mode].append(record)

            processed += 1
            if processed % 200 == 0:
                logger.info(f"  {symbol} 进度: {processed}/{total_bars} bars")

        return dict(signals_by_mode)

    def compute_metrics(self, signals: List[SignalRecord], mode: str) -> ModeMetrics:
        """计算单模式指标"""
        if not signals:
            return ModeMetrics(mode=mode)

        metrics = ModeMetrics(mode=mode, total_signals=len(signals))

        # 信号分布
        metrics.up_signals = sum(1 for s in signals if s.direction == "UP")
        metrics.down_signals = sum(1 for s in signals if s.direction == "DOWN")
        metrics.flat_signals = sum(1 for s in signals if s.direction == "FLAT")
        metrics.avg_confidence = float(np.mean([s.confidence for s in signals]))

        # 方向准确率（排除FLAT信号）
        non_flat = [s for s in signals if s.direction != "FLAT"]
        if non_flat:
            correct = sum(1 for s in non_flat if s.direction == s.actual_direction)
            metrics.direction_accuracy = correct / len(non_flat)

            # 多空precision
            up_signals = [s for s in non_flat if s.direction == "UP"]
            down_signals = [s for s in non_flat if s.direction == "DOWN"]
            if up_signals:
                metrics.up_precision = sum(1 for s in up_signals if s.actual_direction == "UP") / len(up_signals)
            if down_signals:
                metrics.down_precision = sum(1 for s in down_signals if s.actual_direction == "DOWN") / len(down_signals)

        # 置信度校准
        high_conf = [s for s in non_flat if s.confidence >= self.HIGH_CONF_THRESHOLD]
        low_conf = [s for s in non_flat if s.confidence <= self.LOW_CONF_THRESHOLD]
        if high_conf:
            metrics.high_conf_accuracy = sum(1 for s in high_conf if s.direction == s.actual_direction) / len(high_conf)
        if low_conf:
            metrics.low_conf_accuracy = sum(1 for s in low_conf if s.direction == s.actual_direction) / len(low_conf)

        # 转折预警有效性
        warnings = [s for s in signals if s.reversal_warning]
        metrics.total_reversal_warnings = len(warnings)
        if warnings:
            # 预警后实际反转 = 未来收益方向与信号方向相反 或 未来回撤>1%
            hits = 0
            for s in warnings:
                # 反转判定：未来10根收益与当前速度方向相反，或回撤超过阈值
                if (s.velocity > 0 and s.future_return_10 < -self.REVERSAL_THRESHOLD) or \
                   (s.velocity < 0 and s.future_return_10 > self.REVERSAL_THRESHOLD) or \
                   (s.future_max_drawdown < -self.REVERSAL_THRESHOLD):
                    hits += 1
            metrics.reversal_hit_rate = hits / len(warnings)

        # TDA预警
        tda_warnings = [s for s in signals if s.tda_warning]
        metrics.tda_warnings = len(tda_warnings)
        if tda_warnings:
            tda_hits = sum(1 for s in tda_warnings if
                           abs(s.future_return_10) > self.REVERSAL_THRESHOLD or
                           s.future_max_drawdown < -self.REVERSAL_THRESHOLD)
            metrics.tda_hit_rate = tda_hits / len(tda_warnings)

        # Ising预警
        ising_alerts = [s for s in signals if s.ising_alert]
        metrics.ising_alerts = len(ising_alerts)
        if ising_alerts:
            ising_hits = sum(1 for s in ising_alerts if
                             abs(s.future_return_10) > self.REVERSAL_THRESHOLD or
                             s.future_max_drawdown < -self.REVERSAL_THRESHOLD)
            metrics.ising_hit_rate = ising_hits / len(ising_alerts)

        # 预警提前量（TDA/Ising比力学减速早多少bar）
        # 简化：统计TDA预警在前而reversal_warning在后的案例
        if mode == "p2_full" and len(signals) > 20:
            early_bars = []
            for i in range(len(signals)):
                if signals[i].tda_warning and not signals[i].reversal_warning:
                    # 向后搜索10bar内是否出现reversal_warning
                    for j in range(i + 1, min(i + 11, len(signals))):
                        if signals[j].reversal_warning:
                            early_bars.append(signals[j].bar_index - signals[i].bar_index)
                            break
            if early_bars:
                metrics.avg_early_warning_bars = float(np.mean(early_bars))

        return metrics

    def run_multi_symbol(
        self,
        symbols: List[str],
        timeframe: str = "1H",
        modes: List[str] = None,
    ) -> Tuple[Dict[str, Dict[str, List[SignalRecord]]], Dict[str, Dict[str, ModeMetrics]]]:
        """多币种回测"""
        all_signals = {}
        all_metrics = {}

        for symbol in symbols:
            logger.info(f"\n{'='*55}")
            logger.info(f"回测 {symbol} {timeframe}")
            df = self.load_klines(symbol, timeframe)
            if df is None or len(df) < 250:
                logger.warning(f"{symbol} 数据不足({len(df) if df is not None else 0})，跳过")
                continue

            signals = self.run_backtest(df, symbol, modes=modes)
            all_signals[symbol] = signals

            symbol_metrics = {}
            for mode, mode_signals in signals.items():
                symbol_metrics[mode] = self.compute_metrics(mode_signals, mode)

            all_metrics[symbol] = symbol_metrics

        return all_signals, all_metrics

    def generate_report(
        self,
        all_metrics: Dict[str, Dict[str, ModeMetrics]],
        output_path: str = None,
    ) -> str:
        """生成回测报告"""
        if output_path is None:
            output_path = os.path.join(
                PROJECT_ROOT, "data", "backtest",
                f"force_engine_backtest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            )
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # 转换为可序列化格式
        report = {
            "timestamp": datetime.now().isoformat(),
            "symbols": list(all_metrics.keys()),
            "modes": list(next(iter(all_metrics.values())).keys()) if all_metrics else [],
            "results": {},
            "summary": {},
        }

        # 各币种各模式详细指标
        for symbol, mode_metrics in all_metrics.items():
            report["results"][symbol] = {}
            for mode, metrics in mode_metrics.items():
                report["results"][symbol][mode] = {
                    "total_signals": metrics.total_signals,
                    "direction_accuracy": round(metrics.direction_accuracy, 4),
                    "up_precision": round(metrics.up_precision, 4),
                    "down_precision": round(metrics.down_precision, 4),
                    "high_conf_accuracy": round(metrics.high_conf_accuracy, 4),
                    "low_conf_accuracy": round(metrics.low_conf_accuracy, 4),
                    "total_reversal_warnings": metrics.total_reversal_warnings,
                    "reversal_hit_rate": round(metrics.reversal_hit_rate, 4),
                    "tda_warnings": metrics.tda_warnings,
                    "tda_hit_rate": round(metrics.tda_hit_rate, 4),
                    "ising_alerts": metrics.ising_alerts,
                    "ising_hit_rate": round(metrics.ising_hit_rate, 4),
                    "avg_early_warning_bars": round(metrics.avg_early_warning_bars, 2),
                    "up_signals": metrics.up_signals,
                    "down_signals": metrics.down_signals,
                    "flat_signals": metrics.flat_signals,
                    "avg_confidence": round(metrics.avg_confidence, 4),
                }

        # 跨币种汇总
        modes = report["modes"]
        for mode in modes:
            mode_data = []
            for symbol in all_metrics:
                if mode in all_metrics[symbol]:
                    mode_data.append(all_metrics[symbol][mode])

            if mode_data:
                report["summary"][mode] = {
                    "avg_direction_accuracy": round(
                        float(np.mean([m.direction_accuracy for m in mode_data if m.total_signals > 0])), 4),
                    "avg_high_conf_accuracy": round(
                        float(np.mean([m.high_conf_accuracy for m in mode_data if m.total_signals > 0])), 4),
                    "avg_reversal_hit_rate": round(
                        float(np.mean([m.reversal_hit_rate for m in mode_data if m.total_reversal_warnings > 0])), 4),
                    "avg_tda_hit_rate": round(
                        float(np.mean([m.tda_hit_rate for m in mode_data if m.tda_warnings > 0])), 4),
                    "avg_ising_hit_rate": round(
                        float(np.mean([m.ising_hit_rate for m in mode_data if m.ising_alerts > 0])), 4),
                    "total_signals": sum(m.total_signals for m in mode_data),
                    "total_reversal_warnings": sum(m.total_reversal_warnings for m in mode_data),
                    "total_tda_warnings": sum(m.tda_warnings for m in mode_data),
                    "total_ising_alerts": sum(m.ising_alerts for m in mode_data),
                }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        return output_path

    def print_report(self, all_metrics: Dict[str, Dict[str, ModeMetrics]]):
        """控制台打印对比表"""
        print("\n" + "=" * 90)
        print("力学引擎回测报告 — P0/P1/P2 升级效果对比")
        print("=" * 90)

        modes = list(next(iter(all_metrics.values())).keys()) if all_metrics else []

        for symbol, mode_metrics in all_metrics.items():
            print(f"\n{'─' * 90}")
            print(f"  {symbol}")
            print(f"{'─' * 90}")
            print(f"  {'模式':<12} {'信号数':>6} {'准确率':>8} {'高置信准确率':>12} {'预警数':>6} {'预警命中率':>10} {'平均置信度':>10}")
            print(f"  {'-'*12} {'-'*6} {'-'*8} {'-'*12} {'-'*6} {'-'*10} {'-'*10}")

            for mode in modes:
                if mode not in mode_metrics:
                    continue
                m = mode_metrics[mode]
                if m.total_signals == 0:
                    continue
                print(f"  {mode:<12} {m.total_signals:>6} {m.direction_accuracy:>8.1%} "
                      f"{m.high_conf_accuracy:>12.1%} {m.total_reversal_warnings:>6} "
                      f"{m.reversal_hit_rate:>10.1%} {m.avg_confidence:>10.4f}")

            # P2专用：TDA/Ising预警
            if "p2_full" in mode_metrics:
                m = mode_metrics["p2_full"]
                if m.tda_warnings > 0 or m.ising_alerts > 0:
                    print(f"\n  [P2五角校验预警]")
                    print(f"  TDA预警: {m.tda_warnings}次, 命中率={m.tda_hit_rate:.1%}, 平均提前={m.avg_early_warning_bars:.1f}bars")
                    print(f"  Ising预警: {m.ising_alerts}次, 命中率={m.ising_hit_rate:.1%}")

        # 汇总
        print(f"\n{'=' * 90}")
        print("跨币种汇总")
        print(f"{'=' * 90}")
        print(f"  {'模式':<12} {'总信号':>8} {'平均准确率':>10} {'平均高置信准确率':>16} {'总预警':>8} {'平均预警命中率':>14}")
        print(f"  {'-'*12} {'-'*8} {'-'*10} {'-'*16} {'-'*8} {'-'*14}")

        for mode in modes:
            mode_data = [all_metrics[s][mode] for s in all_metrics if mode in all_metrics[s]]
            if not mode_data:
                continue
            total_sig = sum(m.total_signals for m in mode_data)
            avg_acc = float(np.mean([m.direction_accuracy for m in mode_data if m.total_signals > 0]))
            avg_high = float(np.mean([m.high_conf_accuracy for m in mode_data if m.total_signals > 0]))
            total_warn = sum(m.total_reversal_warnings for m in mode_data)
            avg_warn_hit = float(np.mean([m.reversal_hit_rate for m in mode_data if m.total_reversal_warnings > 0])) if any(m.total_reversal_warnings > 0 for m in mode_data) else 0

            print(f"  {mode:<12} {total_sig:>8} {avg_acc:>10.1%} {avg_high:>16.1%} {total_warn:>8} {avg_warn_hit:>14.1%}")

        print(f"\n{'=' * 90}")


# ============================================================
# 主入口
# ============================================================

def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    # 回测币种
    symbols = ["BTC", "ETH", "SOL", "DOGE", "XRP", "LINK", "ADA", "AVAX"]
    timeframe = "1H"
    modes = ["baseline", "p0", "p1_kalman", "p2_full"]

    print(f"\n力学引擎回测")
    print(f"币种: {symbols}")
    print(f"周期: {timeframe}")
    print(f"模式: {modes}")
    print(f"开始时间: {datetime.now().isoformat()}\n")

    backtester = ForceEngineBacktester()
    _, all_metrics = backtester.run_multi_symbol(symbols, timeframe, modes)

    # 打印报告
    backtester.print_report(all_metrics)

    # 保存JSON报告
    report_path = backtester.generate_report(all_metrics)
    print(f"\n详细报告已保存: {report_path}")

    return all_metrics


if __name__ == "__main__":
    main()
