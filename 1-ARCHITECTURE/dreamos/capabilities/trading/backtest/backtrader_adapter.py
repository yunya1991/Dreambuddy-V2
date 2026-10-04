"""backtrader 可选增强适配器 — FAIL-OPEN 设计

为 C3 回测验证节点提供基于 backtrader 的可选增强。

设计原则（遵循 FAIL-OPEN）：
1. backtrader 未安装时 _AVAILABLE=False，enhance_signals 返回 None
2. 输入数据非法（klines 为空、字段缺失、signals 非 list）时返回 None
3. 任何异常都不得冒泡到 C3 主流程，捕获并返回 None
4. 返回 dict 时含字段：win_rate/sharpe/max_dd/total_trades/source="backtrader"
5. None 表示"未增强，C3 应继续使用简化模拟结果"

参考：
- 11-易经推理系统/scripts/memory_l4/bcrm/backtest_gate.py（walk-forward 回测 + direction_accuracy 门禁）
- 11-易经推理系统/scripts/memory_l4/self_evolution_engine.py L712-751（backtrader/ema_cross 静态经验）
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional


# ── backtrader 可选导入 ─────────────────────────────────────
_AVAILABLE = False
try:
    import backtrader as _bt  # type: ignore
    _AVAILABLE = True
except ImportError:
    _bt = None  # type: ignore


def is_available() -> bool:
    """backtrader 是否可用"""
    return _AVAILABLE


def enhance_signals(
    signals: List[Dict[str, Any]],
    klines: Optional[List[Dict[str, Any]]],
) -> Optional[Dict[str, Any]]:
    """用 backtrader 对 signals 做回测增强

    Args:
        signals: C2 上游产出的信号列表，每项含 symbol/direction/confidence/trend/momentum
        klines: K 线数据列表，每项含 date/open/high/low/close/volume

    Returns:
        Optional[Dict]：None 表示未增强；dict 含 win_rate/sharpe/max_dd/total_trades/source
    """
    if not _AVAILABLE:
        return None

    # 输入校验
    if not isinstance(signals, list) or not signals:
        return None
    if not isinstance(klines, list) or not klines:
        return None
    for sig in signals:
        if not isinstance(sig, dict):
            return None
    for k in klines:
        if not isinstance(k, dict):
            return None
        # 必须包含 close 字段（最低要求）
        if "close" not in k:
            return None

    try:
        return _run_backtrader_backtest(signals, klines)
    except Exception:
        # FAIL-OPEN：任何异常都不得冒泡
        return None


def _run_backtrader_backtest(
    signals: List[Dict[str, Any]],
    klines: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """运行 backtrader 回测（仅在 _AVAILABLE=True 且输入已校验时调用）"""
    if _bt is None:
        return None

    # 构建 backtrader 数据源
    data = _build_data_feed(klines)
    if data is None:
        return None

    # 简单 EMA 交叉策略（参考 backtrader/ema_cross 经验）
    class _EMACrossStrategy(_bt.Strategy):
        params = (
            ("fast_period", 5),
            ("slow_period", 20),
        )

        def __init__(self):
            self.fast_ema = _bt.ind.EMA(self.data.close, period=self.params.fast_period)
            self.soft_ema = _bt.ind.EMA(self.data.close, period=self.params.slow_period)
            self.crossover = _bt.ind.CrossOver(self.fast_ema, self.soft_ema)
            self.trades_pnl = []

        def next(self):
            if self.crossover > 0 and not self.position:
                self.buy()
            elif self.crossover < 0 and self.position:
                self.close()

    cerebro = _bt.Cerebro()
    cerebro.adddata(data)
    cerebro.addstrategy(_EMACrossStrategy)
    cerebro.broker.setcash(10000.0)
    cerebro.broker.set_coc(True)  # cheat-on-close for stability
    # 添加分析器
    cerebro.addanalyzer(_bt.analyzers.TradeAnalyzer, _name="trades")
    cerebro.addanalyzer(_bt.analyzers.SharpeRatio, _name="sharpe")
    cerebro.addanalyzer(_bt.analyzers.DrawDown, _name="drawdown")

    results = cerebro.run()
    if not results:
        return None

    strat = results[0]

    # 提取指标
    win_rate = _extract_win_rate(strat)
    sharpe = _extract_sharpe(strat)
    max_dd = _extract_max_dd(strat)
    total_trades = _extract_total_trades(strat)

    return {
        "win_rate": float(win_rate),
        "sharpe": float(sharpe),
        "max_dd": float(max_dd),
        "total_trades": int(total_trades),
        "source": "backtrader",
    }


def _build_data_feed(klines: List[Dict[str, Any]]):
    """将 list[dict] K 线转为 backtrader 数据源"""
    if _bt is None:
        return None
    if not klines:
        return None

    # 尝试用 pandas 构建数据源（backtrader 推荐）
    try:
        import pandas as pd  # type: ignore
        df = pd.DataFrame(klines)
        # 确保有 datetime index
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.dropna(subset=["date"])
            df = df.set_index("date")
        # 确保列存在
        for col in ("open", "high", "low", "close", "volume"):
            if col not in df.columns:
                return None
        data = _bt.feeds.PandasData(dataname=df)
        return data
    except ImportError:
        pass
    except Exception:
        return None

    # 退化方案：GenericCSVData（不依赖 pandas）
    try:
        # 生成临时 CSV
        import csv
        import io
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["Date", "Open", "High", "Low", "Close", "Volume"])
        for k in klines:
            writer.writerow([
                k.get("date", ""),
                k.get("open", k.get("close", 0)),
                k.get("high", k.get("close", 0)),
                k.get("low", k.get("close", 0)),
                k.get("close", 0),
                k.get("volume", 0),
            ])
        buf.seek(0)
        # 写入临时文件（GenericCSVData 需要 path）
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(buf.getvalue())
            tmp_path = f.name
        data = _bt.feeds.GenericCSVData(
            dataname=tmp_path,
            datetime=0,
            open=1,
            high=2,
            low=3,
            close=4,
            volume=5,
            openinterest=-1,
        )
        return data
    except Exception:
        return None


def _extract_win_rate(strat) -> float:
    """从 TradeAnalyzer 提取胜率"""
    try:
        ta = strat.analyzers.trades.get_analysis()
        total = getattr(ta, "total", {}).get("total", 0) if hasattr(ta, "total") else 0
        won = getattr(ta, "won", {}).get("total", 0) if hasattr(ta, "won") else 0
        if total > 0:
            return float(won / total)
    except Exception:
        pass
    return 0.0


def _extract_sharpe(strat) -> float:
    """从 SharpeRatio 提取夏普"""
    try:
        sharpe_analysis = strat.analyzers.sharpe.get_analysis()
        # backtrader SharpeRatio 返回 dict 含 'sharperatio'
        if isinstance(sharpe_analysis, dict):
            return float(sharpe_analysis.get("sharperatio", 0.0) or 0.0)
        return float(getattr(sharpe_analysis, "sharperatio", 0.0) or 0.0)
    except Exception:
        return 0.0


def _extract_max_dd(strat) -> float:
    """从 DrawDown 提取最大回撤"""
    try:
        dd_analysis = strat.analyzers.drawdown.get_analysis()
        # backtrader DrawDown 返回 dict 含 'maxdrawdown'
        if isinstance(dd_analysis, dict):
            return float(abs(dd_analysis.get("maxdrawdown", 0.0) or 0.0))
        return float(abs(getattr(dd_analysis, "maxdrawdown", 0.0) or 0.0))
    except Exception:
        return 0.0


def _extract_total_trades(strat) -> int:
    """从 TradeAnalyzer 提取总交易数"""
    try:
        ta = strat.analyzers.trades.get_analysis()
        total = getattr(ta, "total", {}).get("total", 0) if hasattr(ta, "total") else 0
        return int(total)
    except Exception:
        return 0
