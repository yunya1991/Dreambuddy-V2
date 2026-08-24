"""三屏趋势系统 — 策略运行器

定时运行策略，获取实时数据，生成信号，执行纸交易。
支持多策略并行对比验证。
"""

import time
import signal
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
import json
import pandas as pd
import numpy as np

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))
# 添加 data_center 包路径
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "18-数据获取中心"))

from live.paper_trading import PaperTradingEngine
from data_center.compat import fetch_candles, resample_candles
from core.least_resistance import compute_least_resistance
from core.config import CANDIDATE_COINS


class StrategyRunner:
    """策略运行器

    功能：
    - 定时获取实时数据
    - 运行多个策略生成信号
    - 执行纸交易
    - 记录交易日志
    - 生成验证报告
    """

    def __init__(
        self,
        engine: PaperTradingEngine,
        symbols: Optional[List[Dict]] = None,
        run_interval_seconds: int = 300,  # 5分钟
        data_dir: Optional[str] = None,
    ):
        """
        参数:
            engine: 纸交易引擎
            symbols: 交易对配置列表
            run_interval_seconds: 运行间隔（秒）
            data_dir: 数据目录
        """
        self.engine = engine
        self.symbols = symbols or CANDIDATE_COINS[:2]  # 默认 BTC、ETH
        self.run_interval = run_interval_seconds

        self.data_dir = Path(data_dir) if data_dir else Path(__file__).parent / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # 策略注册表
        self.strategies: Dict[str, Callable] = {}

        # 运行状态
        self._running = False
        self._last_run_time: Optional[datetime] = None

        # 信号缓存
        self._signal_cache: Dict[str, Dict[str, float]] = {}

    def register_strategy(self, name: str, strategy_func: Callable) -> None:
        """注册策略

        参数:
            name: 策略名
            strategy_func: 策略函数，签名: (prices: pd.DataFrame) -> float
        """
        self.strategies[name] = strategy_func
        self.engine.register_strategy(name)

    def _fetch_data(self, inst_id: str, bar: str = "1D", limit: int = 300) -> pd.DataFrame:
        """获取K线数据"""
        try:
            candles = fetch_candles(inst_id, bar=bar, limit=limit)
            if not candles:
                return pd.DataFrame()

            df = pd.DataFrame(candles)
            df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
            df = df.set_index("timestamp")

            # 重命名列
            df = df.rename(columns={
                "o": "open", "h": "high", "l": "low", "c": "close", "vol": "volume"
            })

            return df[["open", "high", "low", "close", "volume"]]

        except Exception as e:
            print(f"  [ERROR] 获取数据失败 {inst_id}: {e}")
            return pd.DataFrame()

    def _fetch_multi_timeframe(
        self,
        inst_id: str,
        bars: List[str] = ["1W", "1D", "4H"],
        limit: int = 300,
    ) -> Dict[str, pd.DataFrame]:
        """获取多周期数据"""
        result = {}
        for bar in bars:
            df = self._fetch_data(inst_id, bar=bar, limit=limit)
            if not df.empty:
                result[bar] = df
        return result

    def run_once(self) -> Dict[str, Any]:
        """单次运行

        返回:
            运行结果摘要
        """
        ts = datetime.now()
        results = {
            "timestamp": ts.isoformat(),
            "signals": {},
            "orders": [],
            "errors": [],
        }

        print(f"\n{'='*60}")
        print(f"  策略运行 @ {ts.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}")

        for coin in self.symbols:
            inst_id = coin["swap"]  # 使用永续合约
            symbol = coin["symbol"]

            print(f"\n[{symbol}] 获取数据...")

            # 获取多周期数据
            multi_tf = self._fetch_multi_timeframe(inst_id)
            if not multi_tf:
                results["errors"].append(f"{symbol}: 无法获取数据")
                continue

            daily_df = multi_tf.get("1D")
            if daily_df is None or daily_df.empty:
                results["errors"].append(f"{symbol}: 日线数据为空")
                continue

            current_price = daily_df["close"].iloc[-1]
            print(f"  当前价格: {current_price:.2f}")

            # 运行各策略
            for strategy_name, strategy_func in self.strategies.items():
                try:
                    # 调用策略生成信号
                    signal = strategy_func(daily_df)

                    # 缓存信号
                    if symbol not in self._signal_cache:
                        self._signal_cache[symbol] = {}
                    self._signal_cache[symbol][strategy_name] = signal

                    # 执行纸交易
                    order = self.engine.execute_signal(
                        strategy_name=strategy_name,
                        inst_id=symbol,
                        signal=signal,
                        current_price=current_price,
                        timestamp=ts,
                        notes=f"自动运行",
                    )

                    # 记录结果
                    if strategy_name not in results["signals"]:
                        results["signals"][strategy_name] = {}
                    results["signals"][strategy_name][symbol] = {
                        "signal": signal,
                        "price": current_price,
                        "order": order.order_id if order else None,
                    }

                    if order:
                        results["orders"].append(order.to_dict())
                        print(f"  [{strategy_name}] 信号: {signal:+.3f} → 订单: {order.order_id}")
                    else:
                        print(f"  [{strategy_name}] 信号: {signal:+.3f} (无交易)")

                except Exception as e:
                    error_msg = f"{strategy_name}@{symbol}: {e}"
                    results["errors"].append(error_msg)
                    print(f"  [ERROR] {error_msg}")

        # 更新持仓价格
        prices = {}
        for coin in self.symbols:
            symbol = coin["symbol"]
            inst_id = coin["swap"]
            try:
                df = self._fetch_data(inst_id, bar="1D", limit=1)
                if not df.empty:
                    prices[symbol] = df["close"].iloc[-1]
            except Exception:
                pass
        self.engine.update_prices(prices)

        self._last_run_time = ts

        return results

    def run_forever(self) -> None:
        """持续运行（定时循环）"""
        self._running = True

        def signal_handler(sig, frame):
            print("\n\n接收到停止信号，正在退出...")
            self._running = False
            self._save_final_report()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        print(f"\n策略运行器启动，间隔: {self.run_interval}秒")
        print(f"交易对: {[c['symbol'] for c in self.symbols]}")
        print(f"策略: {list(self.strategies.keys())}")
        print(f"\n按 Ctrl+C 停止...\n")

        while self._running:
            try:
                self.run_once()

                # 保存日志
                self.engine.save_trading_log()

                # 等待下次运行
                for _ in range(self.run_interval):
                    if not self._running:
                        break
                    time.sleep(1)

            except Exception as e:
                print(f"\n[ERROR] 运行异常: {e}")
                time.sleep(10)

    def _save_final_report(self) -> None:
        """保存最终报告"""
        ts = datetime.now()
        report = {
            "end_time": ts.isoformat(),
            "summary": self.engine.get_summary(),
            "signal_cache": self._signal_cache,
        }

        filepath = self.data_dir / f"final_report_{ts.strftime('%Y%m%d_%H%M%S')}.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        print(f"\n最终报告已保存: {filepath}")

        # 打印汇总
        print("\n" + "=" * 60)
        print("  最终汇总")
        print("=" * 60)
        for name, data in report["summary"]["strategies"].items():
            print(f"\n[{name}]")
            print(f"  收益率: {data['return_pct']:.2f}%")
            print(f"  总盈亏: {data['total_pnl']:.2f}")
            print(f"  交易次数: {data['order_count']}")


# ==================== 预定义策略函数 ====================

def create_rule_strategy(weekly_weight: float = 0.6) -> Callable:
    """创建规则引擎策略

    参数:
        weekly_weight: 周线权重

    返回:
        策略函数
    """
    def rule_strategy(prices: pd.DataFrame) -> float:
        """规则引擎策略：基于最小阻力方向"""
        if len(prices) < 50:
            return 0.0

        # 计算最小阻力
        try:
            lr = compute_least_resistance(prices)
            res_diff = lr.get("resistance_diff", 0)
            confidence = lr.get("confidence", 0)

            # 信号 = 方向 * 置信度
            signal = np.sign(res_diff) * min(abs(confidence), 1.0)
            return float(np.clip(signal, -1, 1))

        except Exception:
            return 0.0

    return rule_strategy


def create_ai_v1_strategy(
    label_lookahead: int = 7,
    ml_weight: float = 0.4,
) -> Callable:
    """创建 AI v1 策略

    参数:
        label_lookahead: 标签前瞻天数
        ml_weight: ML 权重

    返回:
        策略函数
    """
    from ml.lr_ml_strategy import LeastResistanceAIStrategy
    from ml.lr_feature_engineer import LeastResistanceFeatureEngineer

    strategy = LeastResistanceAIStrategy(
        label_lookahead=label_lookahead,
        ml_weight=ml_weight,
        enable_walk_forward=True,
        feature_engineer=LeastResistanceFeatureEngineer(enable_fundamental=False),
    )

    # 缓存信号序列
    _last_signals = None

    def ai_v1_strategy(prices: pd.DataFrame) -> float:
        """AI v1 策略"""
        nonlocal _last_signals

        if len(prices) < 200:
            return 0.0

        try:
            signals = strategy.generate_signals(prices)
            _last_signals = signals
            return float(signals.iloc[-1])
        except Exception:
            return 0.0

    return ai_v1_strategy


def create_ai_v2_strategy(
    label_lookahead: int = 7,
    enable_multitask: bool = True,
    enable_dynamic_weight: bool = True,
) -> Callable:
    """创建 AI v2 策略

    参数:
        label_lookahead: 标签前瞻天数
        enable_multitask: 启用多任务学习
        enable_dynamic_weight: 启用动态权重

    返回:
        策略函数
    """
    from ml.lr_ml_strategy_v2 import LeastResistanceAIStrategyV2

    strategy = LeastResistanceAIStrategyV2(
        label_lookahead=label_lookahead,
        enable_fundamental=False,
        enable_multitask=enable_multitask,
        enable_dynamic_weight=enable_dynamic_weight,
        enable_feature_selection=False,
    )

    def ai_v2_strategy(prices: pd.DataFrame) -> float:
        """AI v2 策略"""
        if len(prices) < 200:
            return 0.0

        try:
            signals = strategy.generate_signals(prices)
            return float(signals.iloc[-1])
        except Exception:
            return 0.0

    return ai_v2_strategy


# ==================== 主函数 ====================

def main():
    """主函数：启动策略运行器"""
    import argparse

    parser = argparse.ArgumentParser(description="三屏趋势系统 — 策略运行器")
    parser.add_argument("--capital", type=float, default=10000, help="初始资金")
    parser.add_argument("--interval", type=int, default=300, help="运行间隔（秒）")
    parser.add_argument("--symbols", type=str, default="BTC,ETH", help="交易对（逗号分隔）")
    parser.add_argument("--strategies", type=str, default="rule,ai_v1", help="策略（逗号分隔）")
    parser.add_argument("--once", action="store_true", help="只运行一次")
    args = parser.parse_args()

    # 解析交易对
    symbol_map = {c["symbol"]: c for c in CANDIDATE_COINS}
    symbols = []
    for s in args.symbols.split(","):
        s = s.strip().upper()
        if s in symbol_map:
            symbols.append(symbol_map[s])

    if not symbols:
        print("错误：未找到有效的交易对")
        return

    # 创建引擎和运行器
    engine = PaperTradingEngine(initial_capital=args.capital)
    runner = StrategyRunner(
        engine=engine,
        symbols=symbols,
        run_interval_seconds=args.interval,
    )

    # 注册策略
    available_strategies = {
        "rule": create_rule_strategy(),
        "ai_v1": create_ai_v1_strategy(),
        "ai_v2": create_ai_v2_strategy(),
    }

    for s in args.strategies.split(","):
        s = s.strip().lower()
        if s in available_strategies:
            runner.register_strategy(s, available_strategies[s])
            print(f"注册策略: {s}")

    # 运行
    if args.once:
        runner.run_once()
        print("\n单次运行完成")
        print(json.dumps(engine.get_summary(), indent=2, ensure_ascii=False))
    else:
        runner.run_forever()


if __name__ == "__main__":
    main()