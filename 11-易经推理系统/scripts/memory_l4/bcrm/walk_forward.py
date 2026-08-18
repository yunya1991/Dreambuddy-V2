"""
Walk-Forward 回测引擎。

用于 BCRM 模型的滚动窗口回测，验证预测准确率。
"""

import json
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Callable
from collections import defaultdict
from random import Random

from .engine import BCRMEngine
from .output_contract import BCRMOutput
from .memory_adapter import MockMemoryAdapter


@dataclass
class WindowData:
    """窗口数据。"""
    train_start: int = 0
    train_end: int = 0
    test_start: int = 0
    test_end: int = 0


@dataclass
class WalkForwardResult:
    """Walk-forward 回测结果。"""
    total_bars: int = 0
    correct_predictions: int = 0
    wrong_predictions: int = 0
    direction_accuracy: float = 0.0
    fail_closed_count: int = 0
    avg_confidence: float = 0.0
    per_window_results: List[Dict] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_bars": self.total_bars,
            "correct_predictions": self.correct_predictions,
            "wrong_predictions": self.wrong_predictions,
            "direction_accuracy": round(self.direction_accuracy, 4),
            "fail_closed_count": self.fail_closed_count,
            "avg_confidence": round(self.avg_confidence, 4),
            "per_window_results": self.per_window_results,
        }


def default_direction_label(current_idx: int,
                             data: List[Dict],
                             prediction_dict: Dict) -> bool:
    """
    默认方向打标函数。

    用未来 N 根 K 线的价格变化方向作为标签。
    - UP: 未来均价 > 当前价 * 1.001
    - DOWN: 未来均价 < 当前价 * 0.999
    - FLAT: 未来均价在 ±0.3% 以内
    - TRANSITIONING: 未来方向与近期方向相反
    """
    if current_idx >= len(data) - 1:
        return False

    predicted = prediction_dict.get("next_state", {}).get("direction", "UNKNOWN")

    # 用未来 5 根的均价判断
    future_start = current_idx + 1
    future_end = min(current_idx + 6, len(data))

    if future_start >= len(data):
        return False

    future_prices = [data[i].get("close", data[i].get("price", 0))
                     for i in range(future_start, future_end)]
    if not future_prices:
        return False

    current_price = data[current_idx].get("close",
                                          data[current_idx].get("price", 0))
    avg_future = sum(future_prices) / len(future_prices)
    change_pct = (avg_future - current_price) / current_price

    if predicted == "UP":
        return change_pct > 0.001
    elif predicted == "DOWN":
        return change_pct < -0.001
    elif predicted == "FLAT":
        return abs(change_pct) <= 0.003
    elif predicted == "TRANSITIONING":
        # 检查近期趋势是否反转
        if current_idx < 5:
            return False
        recent_prices = [data[current_idx - j].get("close",
                          data[current_idx - j].get("price", 0))
                         for j in range(1, min(6, current_idx + 1))]
        recent_change = (recent_prices[0] - recent_prices[-1]) / recent_prices[-1] if recent_prices[-1] > 0 else 0
        # 近期上涨但未来下跌，或近期下跌但未来上涨 → 转折正确
        if recent_change > 0.002 and change_pct < -0.001:
            return True
        if recent_change < -0.002 and change_pct > 0.001:
            return True
        return False
    else:
        return False


def generate_synthetic_data(num_bars: int = 200,
                             seed: int = 42) -> List[Dict]:
    """
    生成合成测试数据。

    模拟三种市场状态（bull/bear/ranging），每种状态有明显的趋势特征。
    """
    rng = Random(seed)
    data = []
    price = 100.0

    regimes = ["bull", "bear", "ranging"]
    current_regime = "bull"
    regime_counter = 0

    for i in range(num_bars):
        # 每 60 根切换 regime
        regime_counter += 1
        if regime_counter > 60:
            regime_counter = 0
            idx = regimes.index(current_regime)
            current_regime = regimes[(idx + 1) % len(regimes)]

        # 价格变化 — 加大 drift 让趋势更明显
        if current_regime == "bull":
            drift = 0.003
            volatility = 0.008
        elif current_regime == "bear":
            drift = -0.003
            volatility = 0.01
        else:
            drift = 0.0
            volatility = 0.005

        change = rng.gauss(drift, volatility)
        price = price * (1 + change)
        price = max(1.0, price)

        volume = 1000000 * (1 + rng.gauss(0, 0.3))

        # 计算技术指标
        ma5 = sum(data[-j]["close"] for j in range(1, min(5, len(data)) + 1)) / min(5, len(data)) if data else price
        ma10 = sum(data[-j]["close"] for j in range(1, min(10, len(data)) + 1)) / min(10, len(data)) if data else price
        ma20 = sum(data[-j]["close"] for j in range(1, min(20, len(data)) + 1)) / min(20, len(data)) if data else price

        # 四维评分 — P2修复: 移除预计算，改由 normalize_snapshot() 统一处理
        # 合成数据提供原始信号字段（rsi/ema/funding_rate等），与实盘链路对齐
        rsi = 50.0
        if current_regime == "bull":
            rsi = 55.0 + rng.gauss(0, 8)
        elif current_regime == "bear":
            rsi = 45.0 + rng.gauss(0, 8)
        else:
            rsi = 50.0 + rng.gauss(0, 5)
        rsi = max(10.0, min(90.0, rsi))

        # EMA 模拟（用于 normalize_snapshot 的 technical_score 计算）
        ema20 = ma5  # 短期均线代理
        ema50 = ma10  # 中期均线代理

        # 资金费率模拟（用于 capital_flow_score）
        funding_rate = 0.0001 * rng.gauss(0, 3)  # 正态分布围绕0

        # FGI 模拟（用于 sentiment_score）
        if current_regime == "bull":
            fgi = 65.0 + rng.gauss(0, 10)
        elif current_regime == "bear":
            fgi = 35.0 + rng.gauss(0, 10)
        else:
            fgi = 50.0 + rng.gauss(0, 8)
        fgi = max(5.0, min(95.0, fgi))

        # 价格位置（在窗口中的相对位置）
        window_size = min(50, len(data) + 1)
        if window_size > 1:
            recent_prices = [d["close"] for d in data[-window_size+1:]] + [price]
            p_min = min(recent_prices)
            p_max = max(recent_prices)
            price_position = ((price - p_min) / (p_max - p_min)
                             if p_max > p_min else 0.5)
        else:
            price_position = 0.5

        bar = {
            "snapshot_ts": f"2024-01-{(i//24)+1:02d}T{(i%24):02d}:00:00",
            "price": price,
            "close": price,
            "open": price * (1 + rng.gauss(0, 0.003)),
            "high": price * (1 + abs(rng.gauss(0, 0.005))),
            "low": price * (1 - abs(rng.gauss(0, 0.005))),
            "volume": volume,
            "regime": current_regime,
            "trend_direction": "UP" if current_regime == "bull" else "DOWN" if current_regime == "bear" else "FLAT",
            "trend_strength": abs(drift) * 100 + rng.random() * 0.3,
            "volatility": volatility,
            "volume_ratio": 0.8 + rng.random() * 0.4,
            "price_position": price_position,
            "ma5": ma5,
            "ma10": ma10,
            "ma20": ma20,
            "momentum_direction": "UP" if price > ma5 else "DOWN",
            # P2修复: 提供原始信号字段，让 normalize_snapshot() 统一计算四维评分
            "rsi": rsi,
            "ema20": ema20,
            "ema50": ema50,
            "funding_rate": funding_rate,
            "fgi": fgi,
            "ch4h": change * 4,  # 4小时涨跌幅代理
            "oi_change_pct": rng.gauss(0, 5),  # OI变化代理
        }
        data.append(bar)

    return data


def build_bcrm_predict_fn(engine: BCRMEngine,
                           num_memory_cases: int = 5) -> Callable:
    """
    构建 BCRM 预测函数。

    返回一个函数: predict(snapshot, train_data) -> BCRMOutput
    """
    def predict(snapshot: Dict, train_data: List[Dict]) -> BCRMOutput:
        # 每次预测前重置力学引擎的速度状态，避免跨窗口累积
        if hasattr(engine, 'force_engine') and hasattr(engine.force_engine, 'reset_velocity'):
            engine.force_engine.reset_velocity()
        # 从训练数据生成 mock 记忆
        adapter = MockMemoryAdapter(num_cases=num_memory_cases)
        memory_cases = adapter.retrieve_similar(snapshot, top_k=5)
        memory_dicts = [c.to_dict() for c in memory_cases]

        # P2修复: 矛盾列表构造与实盘对齐，使用 _build_contradiction_list 逻辑
        # 从 snapshot 原始字段推导矛盾（与 polling_trader 实盘链路一致）
        change = snapshot.get("change_pct", 0)
        if not change and "close" in snapshot:
            # 合成数据路径：从 close 计算 change_pct
            change = snapshot.get("ch4h", 0) / 4 if "ch4h" in snapshot else 0

        trend_str = snapshot.get("trend_strength", 0.5)
        vol_ratio = snapshot.get("volume_ratio", 1.0)
        vol = snapshot.get("volatility", 0.03)

        contradictions = []
        # 主矛盾：趋势方向（与实盘 _build_contradiction_list 一致）
        if change > 0.01:
            contradictions.append({
                "thesis": "多头动能释放，趋势向上",
                "antithesis": "短期超买，回调压力增大",
                "subject": "趋势方向",
                "dominant_side": "BULL",
                "direction": "UP",
                "tension": max(0.2, min(0.4 + trend_str * 0.4, 0.85)),
                "consistency": 0.6,
            })
        elif change < -0.01:
            contradictions.append({
                "thesis": "空头动能释放，趋势向下",
                "antithesis": "短期超卖，反弹预期增强",
                "subject": "趋势方向",
                "dominant_side": "BEAR",
                "direction": "DOWN",
                "tension": max(0.2, min(0.4 + trend_str * 0.4, 0.85)),
                "consistency": 0.6,
            })
        else:
            contradictions.append({
                "thesis": "多空平衡，震荡整理",
                "antithesis": "方向选择临近，变盘在即",
                "subject": "趋势方向",
                "dominant_side": "EQUAL",
                "direction": "NEUTRAL",
                "tension": max(0.2, min(0.3 + vol * 5, 0.85)),
                "consistency": 0.5,
            })

        # 次矛盾：量价关系
        if abs(vol_ratio - 1.0) > 0.2:
            if vol_ratio > 1.2 and change > 0:
                vol_dominant = "BULL"
                vol_direction = "UP"
            elif vol_ratio > 1.2 and change < 0:
                vol_dominant = "BEAR"
                vol_direction = "DOWN"
            else:
                vol_dominant = "EQUAL"
                vol_direction = "NEUTRAL"
            contradictions.append({
                "thesis": "放量运行，资金参与度高" if vol_ratio > 1.2 else "缩量运行，资金参与度低",
                "antithesis": "量能不可持续" if vol_ratio > 1.2 else "可能蓄势待发",
                "subject": "量价配合",
                "dominant_side": vol_dominant,
                "direction": vol_direction,
                "tension": max(0.2, min(0.4 + abs(vol_ratio - 1.0) * 0.5, 0.8)),
                "consistency": 0.6,
            })

        return engine.infer(
            market_snapshot=snapshot,
            contradiction_list=contradictions,
            memory_cases=memory_dicts,
        )

    return predict


class WalkForwardEngine:
    """
    Walk-Forward 回测引擎。
    """

    def __init__(self, predict_fn: Callable, reset_fn: Callable = None):
        """
        Args:
            predict_fn: 预测函数 (snapshot, train_data) -> BCRMOutput
            reset_fn: 重置函数，每个窗口开始时调用（用于重置引擎状态如 prev_velocity）
        """
        self.predict_fn = predict_fn
        self.reset_fn = reset_fn

    def run(self,
            data: List[Dict],
            train_window_size: int = 50,
            test_window_size: int = 10,
            step_size: int = 10) -> WalkForwardResult:
        """
        运行 walk-forward 回测。
        """
        result = WalkForwardResult()
        result.total_bars = len(data)

        total_correct = 0
        total_wrong = 0
        total_confidence = 0.0
        valid_count = 0
        fail_closed = 0

        idx = train_window_size
        while idx + test_window_size <= len(data):
            train_data = data[idx - train_window_size:idx]
            test_data = data[idx:idx + test_window_size]

            window_result = self._run_window(
                train_data, test_data, idx)
            result.per_window_results.append(window_result)

            total_correct += window_result["correct"]
            total_wrong += window_result["wrong"]
            total_confidence += window_result["avg_confidence"] * window_result["valid"]
            valid_count += window_result["valid"]
            fail_closed += window_result["fail_closed"]

            idx += step_size

        result.correct_predictions = total_correct
        result.wrong_predictions = total_wrong
        result.fail_closed_count = fail_closed

        total_valid = total_correct + total_wrong
        result.direction_accuracy = (total_correct / total_valid
                                      if total_valid > 0 else 0.0)
        result.avg_confidence = (total_confidence / valid_count
                                  if valid_count > 0 else 0.0)

        return result

    def _run_window(self,
                    train_data: List[Dict],
                    test_data: List[Dict],
                    start_idx: int) -> Dict:
        """运行单个窗口。"""
        # 每个窗口开始时重置引擎状态（如 prev_velocity）
        if self.reset_fn:
            self.reset_fn()

        correct = 0
        wrong = 0
        fail_closed = 0
        total_confidence = 0.0
        valid = 0
        predictions = []

        for i, bar in enumerate(test_data):
            output = self.predict_fn(bar, train_data)

            if output.is_fail_closed():
                fail_closed += 1
                predictions.append({
                    "index": i,
                    "bagua": output.bagua,
                    "regime": bar.get("regime", ""),
                    "fail_closed": True,
                    "is_correct": False,
                })
                continue

            valid += 1
            total_confidence += output.next_state.confidence

            # 计算正确性
            prediction_dict = output.to_dict()
            is_correct = default_direction_label(i, test_data, prediction_dict)

            if is_correct:
                correct += 1
            else:
                wrong += 1

            # 构建实际结果（用于辩证一致性度量）
            actual_outcome = {}
            if i + 1 < len(test_data):
                next_bar = test_data[i + 1]
                cur_price = bar.get("close", bar.get("price", 0))
                next_price = next_bar.get("close", next_bar.get("price", 0))
                if cur_price > 0:
                    actual_outcome["price_change"] = (
                        (next_price - cur_price) / cur_price)

            predictions.append({
                "index": i,
                "bagua": output.bagua,
                "hexagram": output.hexagram.hexagram_name,
                "regime": bar.get("regime", ""),
                "fail_closed": False,
                "is_correct": is_correct,
                "confidence": output.next_state.confidence,
                "direction": output.next_state.direction,
                "bcrm_output": prediction_dict,
                "actual_outcome": actual_outcome,
            })

        return {
            "train_size": len(train_data),
            "test_size": len(test_data),
            "correct": correct,
            "wrong": wrong,
            "fail_closed": fail_closed,
            "valid": valid,
            "accuracy": correct / valid if valid > 0 else 0.0,
            "avg_confidence": total_confidence / valid if valid > 0 else 0.0,
            "predictions": predictions,
        }


def run_bcrm_backtest(engine: BCRMEngine,
                       data: List[Dict] = None,
                       train_window_size: int = 50,
                       test_window_size: int = 10,
                       step_size: int = 10,
                       memory_adapter=None,
                       knowledge_base=None,
                       num_memory_cases: int = 5) -> WalkForwardResult:
    """
    便捷函数：运行 BCRM walk-forward 回测。

    Args:
        engine: BCRM 引擎
        data: 测试数据，None 时自动生成
        train_window_size: 训练窗口大小
        test_window_size: 测试窗口大小
        step_size: 步长
        memory_adapter: 记忆适配器（传入时用于检索历史案例）
        knowledge_base: 知识库（保留接口，当前未使用）
        num_memory_cases: mock 记忆案例数（memory_adapter 为 None 时使用）
    """
    if data is None:
        data = generate_synthetic_data(num_bars=200, seed=42)

    # 如果传入了 memory_adapter，优先使用；否则用 mock
    if memory_adapter is not None:
        def predict_fn(snapshot, train_data):
            memory_cases = memory_adapter.retrieve_similar(snapshot, top_k=5)
            memory_dicts = [c.to_dict() for c in memory_cases]
            sd = snapshot.get("supply_demand_score", 0.5)
            tech = snapshot.get("technical_score", 0.5)
            cf = snapshot.get("capital_flow_score", 0.5)
            sent = snapshot.get("sentiment_score", 0.5)
            contradictions = [{
                "id": "supply_demand_vs_technical",
                "type": "supply_demand",
                "tension": max(abs(sd - tech), 0.3),
                "dominant_side": "BULL" if sd > 0.5 else "BEAR",
            }]
            return engine.infer(
                market_snapshot=snapshot,
                contradiction_list=contradictions,
                memory_cases=memory_dicts,
            )
    else:
        predict_fn = build_bcrm_predict_fn(engine, num_memory_cases=num_memory_cases)

    wf_engine = WalkForwardEngine(predict_fn)

    return wf_engine.run(
        data=data,
        train_window_size=train_window_size,
        test_window_size=test_window_size,
        step_size=step_size,
    )
