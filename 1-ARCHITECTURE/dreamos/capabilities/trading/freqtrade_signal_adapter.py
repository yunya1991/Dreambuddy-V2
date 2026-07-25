"""
Freqtrade 策略信号适配器 — 将 Freqtrade 量化策略接入 Dream OS

功能:
    1. 离线加载 IStrategy 策略类，生成交易信号（无需运行 Freqtrade 进程）
    2. 读取 strategy_registry.json 回测结果，评估策略质量
    3. 读取 V15 回测结果，纳入策略评估
    4. 统一信号格式，输出到 Dream OS 的编排系统

信号输出格式:
    {
        "source": "freqtrade",
        "strategy": "Strategy005",
        "symbol": "BTC",
        "direction": "LONG" | "SHORT" | "HOLD",
        "confidence": 0.0-1.0,
        "tag": "rsi_deep",
        "timeframe": "1h",
        "metrics": {  # 回测指标
            "sharpe": ...,
            "sortino": ...,
            "win_rate": ...,
            "profit_factor": ...,
            "max_drawdown": ...,
        },
        "tier": "good" | "pass" | "unrated",
    }

用法:
    adapter = FreqtradeSignalAdapter()
    signal = adapter.get_signal("BTC")
    # 或批量获取
    signals = adapter.get_all_signals(["BTC", "ETH", "SOL"])
"""

from __future__ import annotations

import os
import sys
import json
import time
import logging
import importlib
import importlib.util
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ============================================================
# 路径常量
# ============================================================

_PROJECT_ROOT = Path("/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2")
_STRATEGY_DIR = _PROJECT_ROOT / "10-经典指标系统" / "user_data" / "strategies"
_CLASSIC_10_DIR = _STRATEGY_DIR / "classic_10_strategies"
_GITHUB_FUTURES_DIR = _STRATEGY_DIR / "github" / "freqtrade-strategies" / "futures"
_REGISTRY_PATH = _PROJECT_ROOT / "10-经典指标系统" / "user_data" / "strategy_registry.json"
_V15_BACKTEST_DIR = _PROJECT_ROOT / "14-V15经典马丁策略" / "data"
_FREQTRADE_DATA_DIR = _PROJECT_ROOT / "10-经典指标系统" / "user_data" / "data"

# 策略注册表（类名 → 文件路径）
_STRATEGY_FILES: Dict[str, Path] = {}

# 回测结果缓存
_BACKTEST_CACHE: Dict[str, Dict[str, Any]] = {}


def _scan_strategies() -> Dict[str, Path]:
    """扫描策略目录，建立 类名 → 文件路径 映射"""
    result = {}
    dirs = [_STRATEGY_DIR, _CLASSIC_10_DIR, _GITHUB_FUTURES_DIR]
    for d in dirs:
        if not d.exists():
            continue
        for py_file in d.glob("*.py"):
            if py_file.name.startswith("_"):
                continue
            # 类名 = 文件名（去掉 .py）
            class_name = py_file.stem
            result[class_name] = py_file
    return result


def _ensure_freqtrade_shims():
    """确保 Freqtrade IStrategy 等依赖可用（最小 shim）"""
    if "freqtrade" in sys.modules:
        return True

    # 尝试导入真实 freqtrade
    try:
        import freqtrade  # noqa
        from freqtrade.strategy import IStrategy  # noqa
        return True
    except ImportError:
        pass

    # 创建最小 shim
    if "freqtrade" not in sys.modules:
        import types

        freqtrade_mod = types.ModuleType("freqtrade")
        freqtrade_mod.__path__ = []
        sys.modules["freqtrade"] = freqtrade_mod

        strategy_mod = types.ModuleType("freqtrade.strategy")
        sys.modules["freqtrade.strategy"] = strategy_mod

        class IStrategy:
            """最小 IStrategy shim — 提供 populate_indicators/entry/exit 的空实现"""

            def populate_indicators(self, dataframe, metadata):
                return dataframe

            def populate_entry_trend(self, dataframe, metadata):
                return dataframe

            def populate_exit_trend(self, dataframe, metadata):
                return dataframe

            # 兼容旧版
            def populate_buy_trend(self, dataframe, metadata):
                return dataframe

            def populate_sell_trend(self, dataframe, metadata):
                return dataframe

        strategy_mod.IStrategy = IStrategy

        # freqtrade.persistence shim
        persistence_mod = types.ModuleType("freqtrade.persistence")
        sys.modules["freqtrade.persistence"] = persistence_mod
        persistence_mod.Trade = type("Trade", (), {})

        # freqtrade.data.history shim
        data_mod = types.ModuleType("freqtrade.data")
        sys.modules["freqtrade.data"] = data_mod

        history_mod = types.ModuleType("freqtrade.data.history")
        sys.modules["freqtrade.data.history"] = history_mod

        def _load_pair_history(pair, timeframe, datadir, **kwargs):
            """空实现 — 返回空 DataFrame"""
            import pandas as pd
            return pd.DataFrame()

        history_mod.load_pair_history = _load_pair_history
        history_mod.HistoryHandler = type("HistoryHandler", (), {"load_pair_history": staticmethod(_load_pair_history)})

    return True


def _load_strategy_class(class_name: str, file_path: Path):
    """动态加载策略类"""
    _ensure_freqtrade_shims()

    try:
        spec = importlib.util.spec_from_file_location(class_name, str(file_path))
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # 查找 IStrategy 子类
        from freqtrade.strategy import IStrategy

        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if isinstance(attr, type) and issubclass(attr, IStrategy) and attr is not IStrategy:
                return attr

        # 兼容：非 IStrategy 但有 populate 方法的类
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if isinstance(attr, type) and hasattr(attr, "populate_indicators"):
                return attr

        return None
    except Exception as e:
        logger.debug(f"加载策略 {class_name} 失败: {e}")
        return None


class FreqtradeSignalAdapter:
    """Freqtrade 策略信号适配器

    将 Freqtrade 量化策略的信号统一接入 Dream OS。

    工作流程:
        1. 扫描策略目录，加载所有 IStrategy 类
        2. 读取 strategy_registry.json 获取回测指标
        3. 读取 V15 回测结果
        4. 为每个币种生成信号：加载 K 线 → 运行策略 → 读取 enter_long/short
        5. 综合多个策略的信号，输出统一的 direction + confidence
    """

    CACHE_TTL = 300  # 5 分钟缓存

    def __init__(self):
        global _STRATEGY_FILES
        if not _STRATEGY_FILES:
            _STRATEGY_FILES = _scan_strategies()
        self._strategy_files = _STRATEGY_FILES
        self._loaded_strategies: Dict[str, Any] = {}  # class_name → strategy_instance
        self._signal_cache: Dict[str, Tuple[float, Dict]] = {}  # symbol → (timestamp, signal)
        self._registry_data: Optional[Dict] = None
        self._v15_results: Optional[Dict] = None

    # ============================================================
    # 策略加载
    # ============================================================

    def _get_strategy(self, class_name: str):
        """延迟加载策略实例"""
        if class_name in self._loaded_strategies:
            return self._loaded_strategies[class_name]

        file_path = self._strategy_files.get(class_name)
        if not file_path or not file_path.exists():
            return None

        cls = _load_strategy_class(class_name, file_path)
        if cls is None:
            return None

        try:
            instance = cls()
            self._loaded_strategies[class_name] = instance
            return instance
        except Exception as e:
            logger.debug(f"实例化策略 {class_name} 失败: {e}")
            return None

    def list_strategies(self) -> List[str]:
        """列出所有可用策略"""
        return sorted(self._strategy_files.keys())

    # ============================================================
    # 回测结果加载
    # ============================================================

    def _load_registry(self) -> Dict:
        """加载 strategy_registry.json"""
        if self._registry_data is not None:
            return self._registry_data

        if not _REGISTRY_PATH.exists():
            self._registry_data = {}
            return self._registry_data

        try:
            with open(_REGISTRY_PATH, "r", encoding="utf-8") as f:
                self._registry_data = json.load(f)
        except Exception as e:
            logger.warning(f"加载 strategy_registry.json 失败: {e}")
            self._registry_data = {}

        return self._registry_data

    def _load_v15_results(self) -> Dict:
        """加载 V15 回测结果"""
        if self._v15_results is not None:
            return self._v15_results

        self._v15_results = {}
        if not _V15_BACKTEST_DIR.exists():
            return self._v15_results

        # 加载 kelly_backtest_result.json
        kelly_path = _V15_BACKTEST_DIR / "kelly_backtest_result.json"
        if kelly_path.exists():
            try:
                with open(kelly_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for result in data.get("results", []):
                        coin = result.get("coin", "")
                        self._v15_results[f"V15_{coin}"] = {
                            "strategy": "V15_kelly",
                            "symbol": coin,
                            "total_return_pct": result.get("kelly", {}).get("total_return_pct", 0),
                            "max_drawdown_pct": result.get("kelly", {}).get("max_drawdown_pct", 0),
                            "sharpe_ratio": result.get("kelly", {}).get("sharpe_ratio", 0),
                            "win_rate": result.get("kelly", {}).get("win_rate", 0),
                            "total_trades": result.get("kelly", {}).get("total_trades", 0),
                            "source": "v15_kelly_backtest",
                        }
            except Exception as e:
                logger.debug(f"加载 V15 kelly 回测失败: {e}")

        # 加载 btc_windvane_backtest_result.json
        windvane_path = _V15_BACKTEST_DIR / "btc_windvane_backtest_result.json"
        if windvane_path.exists():
            try:
                with open(windvane_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        for item in data:
                            coin = item.get("coin", "BTC")
                            self._v15_results[f"V15_windvane_{coin}"] = {
                                "strategy": "V15_windvane",
                                "symbol": coin,
                                "total_return_pct": item.get("total_return_pct", 0),
                                "max_drawdown_pct": item.get("max_drawdown_pct", 0),
                                "sharpe_ratio": item.get("sharpe_ratio", 0),
                                "win_rate": item.get("win_rate", 0),
                                "total_trades": item.get("total_trades", 0),
                                "source": "v15_windvane_backtest",
                            }
                    elif isinstance(data, dict):
                        for coin, item in data.items():
                            self._v15_results[f"V15_windvane_{coin}"] = {
                                "strategy": "V15_windvane",
                                "symbol": coin,
                                "total_return_pct": item.get("total_return_pct", 0),
                                "max_drawdown_pct": item.get("max_drawdown_pct", 0),
                                "sharpe_ratio": item.get("sharpe_ratio", 0),
                                "win_rate": item.get("win_rate", 0),
                                "total_trades": item.get("total_trades", 0),
                                "source": "v15_windvane_backtest",
                            }
            except Exception as e:
                logger.debug(f"加载 V15 windvane 回测失败: {e}")

        return self._v15_results

    def get_strategy_metrics(self, strategy_id: str) -> Optional[Dict[str, Any]]:
        """获取策略的回测指标"""
        registry = self._load_registry()

        # 查找该策略的最佳回测结果
        best_entry = None
        best_score = -1e18

        for key, entry in registry.get("entries", {}).items():
            if entry.get("strategy_id") != strategy_id:
                continue
            gate = entry.get("gate_result", {})
            score = gate.get("eval", {}).get("score", -1e18)
            if score > best_score:
                best_score = score
                best_entry = entry

        if best_entry is None:
            return None

        metrics_summary = best_entry.get("metrics_summary", {})
        gate = best_entry.get("gate_result", {}).get("eval", {})

        return {
            "strategy_id": strategy_id,
            "tier": best_entry.get("tier", "unrated"),
            "family": best_entry.get("family", "unknown"),
            "profit_factor": metrics_summary.get("profit_factor", 0),
            "max_drawdown_pct": metrics_summary.get("max_drawdown_pct", 0),
            "win_rate": metrics_summary.get("winrate", 0),
            "total_trades": metrics_summary.get("trades", 0),
            "backtest_days": metrics_summary.get("backtest_days", 0),
            "timeframe": metrics_summary.get("timeframe", "1h"),
            "sharpe": gate.get("metrics", {}).get("sharpe"),
            "calmar": gate.get("metrics", {}).get("calmar"),
            "total_return_pct": gate.get("metrics", {}).get("total_pct", 0),
            "hard_fails": gate.get("hard_fails", []),
            "signal_density": best_entry.get("signal_density", 0),
        }

    # ============================================================
    # 信号生成
    # ============================================================

    def _load_klines(self, symbol: str, timeframe: str = "1h", limit: int = 200) -> "Optional[Any]":
        """加载 K 线数据

        优先从 Freqtrade 数据缓存加载，其次尝试交易所 API。
        """
        import pandas as pd

        # 尝试从 Hyperliquid 缓存加载
        pair = f"{symbol}USDT"
        for data_root in [_FREQTRADE_DATA_DIR]:
            for exchange in ["hyperliquid", "gate", "aggregated"]:
                for market in ["futures", "spot"]:
                    feath_path = data_root / exchange / market / f"{pair}-{timeframe}-feather"
                    json_path = data_root / exchange / market / f"{pair}-{timeframe}.json"

                    if feath_path.exists():
                        try:
                            return pd.read_feather(str(feath_path)).tail(limit)
                        except Exception:
                            pass

                    if json_path.exists():
                        try:
                            with open(json_path, "r") as f:
                                raw = json.load(f)
                            if isinstance(raw, list) and raw:
                                df = pd.DataFrame(raw, columns=["date", "open", "high", "low", "close", "volume"])
                                df["date"] = pd.to_datetime(df["date"], unit="ms")
                                return df.tail(limit)
                        except Exception:
                            pass

        # 尝试从缓存目录加载
        cache_dir = _FREQTRADE_DATA_DIR / "hyperliquid" / "futures"
        if cache_dir.exists():
            for ext in [".feather", ".json"]:
                pattern = f"{pair}-{timeframe}{ext}"
                for p in cache_dir.glob(pattern):
                    try:
                        if ext == ".feather":
                            return pd.read_feather(str(p)).tail(limit)
                        else:
                            with open(p, "r") as f:
                                raw = json.load(f)
                            if isinstance(raw, list) and raw:
                                df = pd.DataFrame(raw, columns=["date", "open", "high", "low", "close", "volume"])
                                df["date"] = pd.to_datetime(df["date"], unit="ms")
                                return df.tail(limit)
                    except Exception:
                        pass

        return None

    def _generate_strategy_signal(self, strategy_name: str, symbol: str, timeframe: str = "1h") -> Optional[Dict]:
        """运行单个策略，生成信号"""
        instance = self._get_strategy(strategy_name)
        if instance is None:
            return None

        df = self._load_klines(symbol, timeframe)
        if df is None or len(df) < 50:
            return None

        try:
            metadata = {"pair": f"{symbol}/USDT:USDT"}

            # 运行策略三步
            df = instance.populate_indicators(df, metadata)
            df = instance.populate_entry_trend(df, metadata) if hasattr(instance, "populate_entry_trend") else df
            df = instance.populate_exit_trend(df, metadata) if hasattr(instance, "populate_exit_trend") else df

            # 旧版兼容
            if hasattr(instance, "populate_buy_trend"):
                df = instance.populate_buy_trend(df, metadata)
            if hasattr(instance, "populate_sell_trend"):
                df = instance.populate_sell_trend(df, metadata)

            # 读取最后一根 K 线的信号
            last = df.iloc[-1] if len(df) > 0 else None
            if last is None:
                return None

            enter_long = 0
            enter_short = 0
            tag = ""

            if "enter_long" in df.columns:
                enter_long = int(last.get("enter_long", 0) or 0)
            if "enter_short" in df.columns:
                enter_short = int(last.get("enter_short", 0) or 0)
            if "buy" in df.columns and enter_long == 0:
                enter_long = int(last.get("buy", 0) or 0)
            if "enter_tag" in df.columns:
                tag = str(last.get("enter_tag", "") or "")

            direction = "HOLD"
            if enter_long and not enter_short:
                direction = "LONG"
            elif enter_short and not enter_long:
                direction = "SHORT"

            if direction == "HOLD":
                return None  # 无信号

            # 获取该策略的回测指标
            metrics = self.get_strategy_metrics(strategy_name)

            # 置信度：基于回测质量
            confidence = 0.5  # 默认
            if metrics:
                if metrics.get("tier") == "good":
                    confidence = 0.7
                elif metrics.get("tier") == "pass":
                    confidence = 0.6
                elif metrics.get("win_rate", 0) > 0.5:
                    confidence = 0.55

                # 有 Sharpe 数据时调整
                sharpe = metrics.get("sharpe")
                if sharpe is not None and sharpe > 0:
                    confidence = min(0.9, confidence + 0.1 * min(sharpe, 3))

            return {
                "source": "freqtrade",
                "strategy": strategy_name,
                "symbol": symbol,
                "direction": direction,
                "confidence": round(confidence, 3),
                "tag": tag,
                "timeframe": timeframe,
                "metrics": metrics or {},
                "timestamp": time.time(),
            }

        except Exception as e:
            logger.debug(f"策略 {strategy_name} 信号生成失败: {e}")
            return None

    # ============================================================
    # 综合信号
    # ============================================================

    def get_signal(self, symbol: str, timeframe: str = "1h") -> Dict[str, Any]:
        """获取单个币种的综合信号

        运行所有可用策略，综合投票得出方向。

        Args:
            symbol: 币种符号 (如 "BTC")
            timeframe: K 线周期

        Returns:
            综合信号字典
        """
        cached = self._signal_cache.get(symbol)
        if cached and time.time() - cached[0] < self.CACHE_TTL:
            return cached[1]

        all_signals: List[Dict] = []
        strategy_names = self.list_strategies()

        for name in strategy_names:
            sig = self._generate_strategy_signal(name, symbol, timeframe)
            if sig is not None:
                all_signals.append(sig)

        # 加载 V15 回测结果作为参考
        v15_results = self._load_v15_results()
        for key, v15 in v15_results.items():
            if v15.get("symbol") == symbol.upper():
                all_signals.append({
                    "source": "v15_backtest",
                    "strategy": v15["strategy"],
                    "symbol": symbol,
                    "direction": "LONG" if v15.get("total_return_pct", 0) > 0 else "SHORT",
                    "confidence": min(0.6, abs(v15.get("sharpe_ratio", 0)) * 0.2 + 0.3),
                    "tag": "v15_historical",
                    "timeframe": "4h",
                    "metrics": v15,
                    "timestamp": time.time(),
                })

        # 综合投票
        if not all_signals:
            result = {
                "source": "freqtrade",
                "symbol": symbol,
                "direction": "HOLD",
                "confidence": 0.3,
                "strategy_count": 0,
                "signals": [],
                "long_votes": 0,
                "short_votes": 0,
                "timestamp": time.time(),
            }
        else:
            long_votes = sum(1 for s in all_signals if s["direction"] == "LONG")
            short_votes = sum(1 for s in all_signals if s["direction"] == "SHORT")
            total = len(all_signals)

            # 加权投票：按置信度加权
            long_weight = sum(s["confidence"] for s in all_signals if s["direction"] == "LONG")
            short_weight = sum(s["confidence"] for s in all_signals if s["direction"] == "SHORT")

            if long_weight > short_weight:
                direction = "LONG"
                confidence = long_weight / (long_weight + short_weight) if (long_weight + short_weight) > 0 else 0.5
            elif short_weight > long_weight:
                direction = "SHORT"
                confidence = short_weight / (long_weight + short_weight) if (long_weight + short_weight) > 0 else 0.5
            else:
                direction = "HOLD"
                confidence = 0.3

            result = {
                "source": "freqtrade",
                "symbol": symbol,
                "direction": direction,
                "confidence": round(confidence, 3),
                "strategy_count": total,
                "long_votes": long_votes,
                "short_votes": short_votes,
                "signals": all_signals[:10],  # 只保留前 10 个
                "timestamp": time.time(),
            }

        self._signal_cache[symbol] = (time.time(), result)
        return result

    def get_all_signals(self, symbols: List[str], timeframe: str = "1h") -> Dict[str, Dict]:
        """批量获取多个币种的信号"""
        return {s: self.get_signal(s, timeframe) for s in symbols}

    # ============================================================
    # 策略评估报告
    # ============================================================

    def get_strategy_report(self) -> Dict[str, Any]:
        """生成所有策略的评估报告"""
        registry = self._load_registry()
        v15 = self._load_v15_results()

        report = {
            "total_strategies": len(self._strategy_files),
            "loaded_strategies": len(self._loaded_strategies),
            "freqtrade_registry_entries": len(registry.get("entries", {})),
            "v15_backtest_results": len(v15),
            "strategies": [],
        }

        # Freqtrade 策略
        for name in sorted(self._strategy_files.keys()):
            metrics = self.get_strategy_metrics(name)
            report["strategies"].append({
                "name": name,
                "source": "freqtrade",
                "file": str(self._strategy_files[name]),
                "tier": metrics.get("tier", "unrated") if metrics else "unrated",
                "metrics": metrics,
            })

        # V15 策略
        for key, v15_data in v15.items():
            report["strategies"].append({
                "name": key,
                "source": "v15",
                "tier": "pass" if v15_data.get("total_return_pct", 0) > 0 else "unrated",
                "metrics": v15_data,
            })

        return report

    def clear_cache(self, symbol: Optional[str] = None) -> None:
        """清除缓存"""
        if symbol:
            self._signal_cache.pop(symbol, None)
        else:
            self._signal_cache.clear()
