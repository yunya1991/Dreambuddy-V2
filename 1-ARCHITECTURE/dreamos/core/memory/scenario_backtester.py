"""
回测引擎 — 场景×编排模式回测选优

用历史数据文件回测36种场景×5种编排模式，
为每种场景选出综合评分最高的编排，生成初始编排记忆表。

数据源:
    10-经典指标系统/user_data/data/aggregated/futures/ (1h/30m K线)
    格式: [ts, open, high, low, close, volume]

评分公式:
    Score = Sharpe×0.4 + Return×0.3 + (1-MaxDD)×0.2 + WinRate×0.1
"""

from __future__ import annotations

import json
import os
import sys
import logging
import math
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)

# 确保能导入 dreamos
_dreamos_root = Path(__file__).parent.parent.parent.parent
if str(_dreamos_root) not in sys.path:
    sys.path.insert(0, str(_dreamos_root))

from dreamos.core.sense.scenario_classifier import ScenarioClassifier, ScenarioResult
from dreamos.core.memory.orchestration_memory import OrchestrationMemory
from dreamos.shared.state import State, NodeResult, new_state


class ScenarioBacktester:
    """回测引擎

    用法:
        bt = ScenarioBacktester()
        results = bt.run()
        memory = OrchestrationMemory()
        memory.update_from_backtest(results)
        memory.save()
    """

    # 5种编排模式（来自 stress_test.py 第90-96行）
    GRAPH_PATTERNS = {
        "c_chain":     ["C1", "C2", "C3"],
        "c_f_chain":   ["C1", "C2", "F1", "F3"],
        "full_chain":  ["C1", "C2", "F2", "G1"],
        "f_chain":     ["F1", "F2", "F3", "F4"],
        "c_g_chain":   ["C1", "C3", "G1"],
    }

    def __init__(self, data_dir: Optional[str] = None):
        if data_dir is None:
            # 默认: 10-经典指标系统/user_data/data/
            data_dir = str(_dreamos_root.parent / "10-经典指标系统" / "user_data" / "data")
        self.data_dir = data_dir
        self.classifier = ScenarioClassifier()
        self._registry = None

    def _get_registry(self):
        """延迟初始化节点注册表"""
        if self._registry is None:
            from dreamos.registry import get_default_registry
            from dreamos.nodes import register_all
            self._registry = get_default_registry()
            register_all(self._registry)
        return self._registry

    # ============================================================
    # 主入口
    # ============================================================

    def run(self, window_size: int = 24, step: int = 6, hold_periods: int = 12) -> Dict[str, Any]:
        """完整回测

        Args:
            window_size: 滑动窗口K线数（需≥24以计算EMA20+动量）
            step: 窗口步长
            hold_periods: 持有K线数

        Returns:
            {scenario_id: {pattern: {score, sharpe, return, max_dd, win_rate, sample_count}}}
        """
        data_files = self._load_data_files()
        logger.info(f"回测启动: {len(data_files)} 数据文件, 窗口={window_size}, 步长={step}, 持有={hold_periods}")

        # {scenario_id: {pattern: [trade_results]}}
        all_trades: Dict[str, Dict[str, List[float]]] = {}

        for file_path, symbol in data_files:
            try:
                klines = self._load_json(file_path)
                if len(klines) < window_size + hold_periods:
                    logger.warning(f"{symbol}: 数据不足 ({len(klines)} < {window_size + hold_periods})，跳过")
                    continue

                file_trades = self._backtest_file(klines, symbol, window_size, step, hold_periods)

                # 合并到总结果
                for sid, patterns in file_trades.items():
                    if sid not in all_trades:
                        all_trades[sid] = {}
                    for pattern, trades in patterns.items():
                        if pattern not in all_trades[sid]:
                            all_trades[sid][pattern] = []
                        all_trades[sid][pattern].extend(trades)

                logger.info(f"{symbol}: {len(file_trades)} 场景, 窗口数≈{(len(klines)-window_size-hold_periods)//step + 1}")
            except Exception as e:
                logger.error(f"回测 {file_path} 失败: {e}")
                continue

        # 计算评分
        results = self._select_best(all_trades)
        return results

    # ============================================================
    # 数据加载
    # ============================================================

    def _load_data_files(self) -> List[Tuple[str, str]]:
        """扫描数据目录，返回 [(file_path, symbol), ...]"""
        result = []
        # 优先用 aggregated (1h/30m)，数据量适中
        agg_dir = os.path.join(self.data_dir, "aggregated", "futures")
        if os.path.isdir(agg_dir):
            for fname in sorted(os.listdir(agg_dir)):
                if fname.endswith(".json"):
                    symbol = self._extract_symbol(fname)
                    result.append((os.path.join(agg_dir, fname), symbol))

        # 如果aggregated没数据，尝试hyperliquid 5m（数据量大，抽样使用）
        if not result:
            hl_dir = os.path.join(self.data_dir, "hyperliquid", "futures")
            if os.path.isdir(hl_dir):
                for fname in sorted(os.listdir(hl_dir)):
                    if fname.endswith(".json"):
                        symbol = self._extract_symbol(fname)
                        result.append((os.path.join(hl_dir, fname), symbol))

        return result

    def _extract_symbol(self, filename: str) -> str:
        """从文件名提取币种符号"""
        # BTC_USDT-1h-futures.json → BTC
        # BTC-5m-futures.json → BTC
        name = filename.split("-")[0]
        name = name.replace("_USDT", "").replace("_usdt", "")
        return name.upper()

    def _load_json(self, path: str) -> List[list]:
        """加载K线JSON文件"""
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    # ============================================================
    # 回测核心
    # ============================================================

    def _backtest_file(self, klines: list, symbol: str,
                       window_size: int, step: int, hold_periods: int) -> Dict[str, Dict[str, List[float]]]:
        """回测单个数据文件

        Returns:
            {scenario_id: {pattern: [trade_returns]}}
        """
        result: Dict[str, Dict[str, List[float]]] = {}

        for i in range(0, len(klines) - window_size - hold_periods, step):
            window = klines[i:i + window_size]
            future = klines[i + window_size:i + window_size + hold_periods]

            # 构造market_data
            market_data = self._build_market_data(window, symbol)
            if market_data is None:
                continue

            # 场景分类
            scenario = self.classifier.classify(market_data)
            sid = scenario.scenario_id

            if sid not in result:
                result[sid] = {p: [] for p in self.GRAPH_PATTERNS}

            # 对每种编排模式跑节点链并模拟交易
            for pattern_name, nodes in self.GRAPH_PATTERNS.items():
                trade_return = self._simulate_trade(nodes, market_data, future, symbol)
                if trade_return is not None:
                    result[sid][pattern_name].append(trade_return)

        return result

    def _build_market_data(self, window: list, symbol: str) -> Optional[Dict[str, Any]]:
        """从K线窗口构造market_data

        Args:
            window: [[ts, o, h, l, c, v], ...]
            symbol: 币种符号

        Returns:
            market_data dict 或 None（数据不足时）
        """
        if len(window) < 24:
            return None

        closes = [k[4] for k in window]
        highs = [k[2] for k in window]
        lows = [k[3] for k in window]
        volumes = [k[5] for k in window]
        price = closes[-1]

        # 计算EMA
        ema20 = self._ema(closes, min(20, len(closes)))
        ema50 = self._ema(closes, min(50, len(closes)))
        ema200 = self._ema(closes, min(200, len(closes)))

        # 计算涨跌幅
        change_1h = self._pct_change(closes, 1)
        change_4h = self._pct_change(closes, 4)
        change_24h = self._pct_change(closes, min(24, len(closes) - 1))

        # ATR%
        atr_pct = self._atr_pct(highs, lows, closes, 14)

        # RSI
        rsi14 = self._rsi(closes, 14)

        # MACD
        macd_val, macd_signal, macd_hist = self._macd(closes)

        # 波动率均值
        vol_20d_avg = self._vol_avg(closes, 20) if len(closes) >= 20 else atr_pct

        return {
            "symbol": symbol,
            "price": price,
            "ema20": ema20,
            "ema50": ema50,
            "ema200": ema200,
            "change_1h": change_1h,
            "change_4h": change_4h,
            "change_24h": change_24h,
            "atr_pct": atr_pct,
            "rsi14": rsi14,
            "macd": macd_val,
            "macd_signal": macd_signal,
            "macd_hist": macd_hist,
            "vol_ratio": volumes[-1] / (sum(volumes[-20:]) / 20) if len(volumes) >= 20 and sum(volumes[-20:]) > 0 else 1.0,
            "vol_20d_avg": vol_20d_avg,
        }

    def _simulate_trade(self, node_ids: List[str], market_data: Dict[str, Any],
                        future: list, symbol: str) -> Optional[float]:
        """模拟单笔交易

        1. 用窗口数据跑编排链获取方向+置信度
        2. 方向非HOLD且置信度≥0.45时开仓
        3. 持有 future K线后用收盘价平仓
        4. 返回交易收益率

        Returns:
            收益率(float) 或 None(不开仓)
        """
        registry = self._get_registry()

        # 构造State
        cycle_id = f"backtest_{symbol}_{market_data['price']}"
        state = new_state(cycle_id=cycle_id)
        state.market_data = market_data
        state.inputs = {"mkt": market_data, "symbol": symbol}

        # 执行节点链
        direction = "HOLD"
        confidence = 0.0

        for node_id in node_ids:
            node = registry.get(node_id)
            if not node:
                continue
            try:
                result = node.execute(state)
                if result and result.success and result.direction and result.direction != "HOLD":
                    # 取最后一个非HOLD方向
                    direction = result.direction
                    confidence = max(confidence, result.confidence)
                # 将结果存入state供后续节点使用
                if hasattr(state, 'results') and result:
                    state.results[node_id] = result
            except Exception as e:
                logger.debug(f"回测中节点 {node_id} 执行失败: {e}")
                continue

        # 不开仓条件
        if direction == "HOLD" or confidence < 0.45:
            return None

        # 模拟交易
        entry_price = market_data["price"]
        if not future or len(future) == 0:
            return None

        exit_price = future[-1][4]  # 最后K线收盘价

        if direction == "LONG":
            ret = (exit_price - entry_price) / entry_price
        else:  # SHORT
            ret = (entry_price - exit_price) / entry_price

        # 扣除手续费 (0.04% 单边 × 2 = 0.08%)
        ret -= 0.0008

        return ret

    # ============================================================
    # 评分计算
    # ============================================================

    def _select_best(self, all_trades: Dict[str, Dict[str, List[float]]]) -> Dict[str, Any]:
        """计算评分并选优

        Returns:
            {scenario_id: {pattern: {score, sharpe, return, max_dd, win_rate, sample_count}}}
            每个scenario只保留最优pattern的指标
        """
        results: Dict[str, Any] = {}

        for scenario_id, patterns in all_trades.items():
            scenario_results: Dict[str, Any] = {}

            for pattern, trades in patterns.items():
                if not trades:
                    continue

                metrics = self._calc_metrics(trades)
                scenario_results[pattern] = {
                    "score": metrics["score"],
                    "sharpe": metrics["sharpe"],
                    "return": metrics["return"],
                    "max_dd": metrics["max_dd"],
                    "win_rate": metrics["win_rate"],
                    "sample_count": len(trades),
                }

            if scenario_results:
                results[scenario_id] = scenario_results

        return results

    def _calc_metrics(self, trades: List[float]) -> Dict[str, float]:
        """计算综合评分

        Score = Sharpe×0.4 + Return×0.3 + (1-MaxDD)×0.2 + WinRate×0.1
        """
        n = len(trades)
        if n == 0:
            return {"score": 0, "sharpe": 0, "return": 0, "max_dd": 0, "win_rate": 0}

        # 收益率（累计）
        total_return = sum(trades)

        # 平均收益和标准差
        avg_return = total_return / n
        std_return = math.sqrt(sum((t - avg_return) ** 2 for t in trades) / n) if n > 1 else 0.001

        # 夏普比率（年化假设：每笔交易持有12根1h K线，一年8760小时，约730笔/年）
        sharpe = (avg_return / std_return * math.sqrt(730)) if std_return > 0 else 0

        # 最大回撤（基于累计收益曲线）
        cumulative = 0
        peak = 0
        max_dd = 0
        for t in trades:
            cumulative += t
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > max_dd:
                max_dd = dd

        # 胜率
        wins = sum(1 for t in trades if t > 0)
        win_rate = wins / n

        # 归一化评分
        norm_sharpe = self._normalize_sharpe(sharpe)
        norm_return = self._normalize_return(total_return)
        norm_dd = 1 - min(max_dd, 1)
        score = norm_sharpe * 0.4 + norm_return * 0.3 + norm_dd * 0.2 + win_rate * 0.1

        return {
            "score": round(score, 4),
            "sharpe": round(sharpe, 4),
            "return": round(total_return, 4),
            "max_dd": round(max_dd, 4),
            "win_rate": round(win_rate, 4),
        }

    def _normalize_sharpe(self, sharpe: float) -> float:
        """夏普归一化: [-2, 3] → [0, 1]"""
        return (min(max(sharpe, -2), 3) + 2) / 5

    def _normalize_return(self, ret: float) -> float:
        """收益率归一化: [-0.5, 1.0] → [0, 1]"""
        return (min(max(ret, -0.5), 1.0) + 0.5) / 1.5

    # ============================================================
    # 技术指标计算
    # ============================================================

    def _ema(self, values: List[float], period: int) -> float:
        """EMA"""
        if not values or period <= 0:
            return values[-1] if values else 0
        period = min(period, len(values))
        k = 2 / (period + 1)
        ema = values[0]
        for v in values[1:]:
            ema = v * k + ema * (1 - k)
        return ema

    def _pct_change(self, values: List[float], periods: int) -> float:
        """百分比变化"""
        if len(values) <= periods or periods <= 0:
            return 0
        old = values[-periods - 1]
        new = values[-1]
        if old == 0:
            return 0
        return (new - old) / old * 100

    def _atr_pct(self, highs: List[float], lows: List[float], closes: List[float], period: int) -> float:
        """ATR占价格的百分比"""
        if len(closes) < period + 1:
            period = len(closes) - 1
        if period <= 0:
            return 0.02

        trs = []
        for i in range(-period, 0):
            h = highs[i]
            l = lows[i]
            pc = closes[i - 1]
            tr = max(h - l, abs(h - pc), abs(l - pc))
            trs.append(tr)

        atr = sum(trs) / len(trs)
        price = closes[-1]
        return atr / price if price > 0 else 0.02

    def _rsi(self, closes: List[float], period: int) -> float:
        """RSI"""
        if len(closes) < period + 1:
            return 50

        gains = []
        losses = []
        for i in range(-period, 0):
            change = closes[i] - closes[i - 1]
            gains.append(max(change, 0))
            losses.append(max(-change, 0))

        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period

        if avg_loss == 0:
            return 100
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _macd(self, closes: List[float]) -> Tuple[float, float, float]:
        """MACD: (macd_line, signal_line, histogram)"""
        if len(closes) < 35:
            return (0, 0, 0)

        ema12 = self._ema(closes[-26:], 12)
        ema26 = self._ema(closes[-35:], 26)
        macd_line = ema12 - ema26

        # signal = EMA(macd_line, 9)，简化处理
        macd_values = []
        for i in range(-9, 0):
            e12 = self._ema(closes[:i+12] if i+12 < 0 else closes[:12], 12)
            e26 = self._ema(closes[:i+26] if i+26 < 0 else closes[:26], 26)
            macd_values.append(e12 - e26)

        if macd_values:
            signal_line = sum(macd_values) / len(macd_values)
        else:
            signal_line = 0

        hist = macd_line - signal_line
        return (macd_line, signal_line, hist)

    def _vol_avg(self, closes: List[float], period: int) -> float:
        """平均波动率"""
        if len(closes) < period + 1:
            period = len(closes) - 1
        if period <= 0:
            return 0.02

        pcts = []
        for i in range(-period, 0):
            if closes[i - 1] > 0:
                pcts.append(abs(closes[i] - closes[i - 1]) / closes[i - 1])

        return sum(pcts) / len(pcts) if pcts else 0.02
