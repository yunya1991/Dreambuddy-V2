"""
ReflectionScanner — 反思学习扫描器（自进化闭环第二条起点）

与涟漪检测并列的交易信号来源：
- 起点1: 涟漪检测（资本轮转 → ri ≥ 0.55）
- 起点2: 反思学习（历史胜率高 → reflection_ri ≥ 0.55）

从系统级交易索引库（TradeIndexBuilder）中统计各币种：
- 胜率 win_rate
- 样本量 n_trades
- 平均收益 avg_pnl_pct
- 来源子系统分布

输出 reflection_ri ∈ [0, 1]，与 ripple_ri 取 max 作为最终 ri。

设计目标：提高交易频率，增加标注训练样本，不再单纯等待涟漪触发。
         扫描范围覆盖整个系统（含所有子交易系统），不限于单一子系统。
"""
import time
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ReflectionScanner:
    """反思学习扫描器 — 从系统级交易索引库学习胜率，作为第二条交易起点"""

    # 反思学习触发门槛
    MIN_WIN_RATE = 0.55        # 胜率 ≥ 55% 才触发
    MIN_TRADES = 1             # 至少 1 笔样本（探索期：有交易记录就可轻度触发）
    MAX_HISTORY_DAYS = 90      # 只统计最近 90 天的交易

    # 缓存 TTL
    CACHE_TTL = 600  # 10 分钟

    def __init__(self, trades_path: str | Path | None = None, project_root: str | Path | None = None):
        """
        trades_path: 已废弃，保留兼容。现统一使用 TradeIndexBuilder。
        project_root: 项目根目录，用于定位交易索引库。
        """
        if project_root is None:
            project_root = Path.cwd()
        self._project_root = Path(project_root)

        # 延迟初始化 TradeIndexBuilder
        self._index_builder: Any = None

        self._cache: dict[str, dict[str, Any]] | None = None
        self._cache_ts: float = 0.0

    def _get_index_builder(self):
        """延迟初始化 TradeIndexBuilder"""
        if self._index_builder is None:
            from dreambuddy_evolution.engines.trade_index_builder import TradeIndexBuilder
            self._index_builder = TradeIndexBuilder(project_root=self._project_root)
        return self._index_builder

    def _load_trades(self) -> list[dict[str, Any]]:
        """从系统级交易索引库加载所有交易记录（含全部子系统）"""
        try:
            return self._get_index_builder().get_trades(force=False)
        except Exception as e:
            logger.warning("[FO] load trades from index fail: %s", e)
            return []

    def _is_recent(self, trade: dict[str, Any]) -> bool:
        """判断交易是否在 MAX_HISTORY_DAYS 天内"""
        try:
            from datetime import datetime, timezone, timedelta
            exit_time = trade.get("exit_time") or trade.get("entry_time")
            if not exit_time:
                return True
            dt = datetime.fromisoformat(str(exit_time).replace("Z", "+00:00"))
            cutoff = datetime.now(timezone.utc) - timedelta(days=self.MAX_HISTORY_DAYS)
            return dt >= cutoff
        except Exception:
            return True

    def scan(self, force: bool = False) -> dict[str, dict[str, Any]]:
        """
        扫描系统级交易索引库，返回各币种的反思学习统计。

        返回:
        {
            "BTC": {
                "win_rate": 0.67,
                "n_trades": 6,
                "avg_pnl_pct": 0.012,
                "reflection_ri": 0.60,
                "eligible": True,
                "sources": {"bcrm": 4, "evolution": 2},
            },
            ...
        }
        """
        # 缓存检查
        if not force and self._cache is not None:
            if time.time() - self._cache_ts < self.CACHE_TTL:
                return self._cache

        trades = self._load_trades()
        # 按币种分组（只统计最近 90 天）
        recent = [t for t in trades if self._is_recent(t)]

        by_coin: dict[str, list[dict[str, Any]]] = {}
        for t in recent:
            coin = t.get("coin") or t.get("symbol")
            if not coin:
                continue
            by_coin.setdefault(coin, []).append(t)

        result: dict[str, dict[str, Any]] = {}
        for coin, coin_trades in by_coin.items():
            n = len(coin_trades)
            if n == 0:
                continue
            wins = sum(1 for t in coin_trades if t.get("pnl", 0) > 0)
            win_rate = wins / n
            avg_pnl = sum(t.get("pnl_pct", 0) for t in coin_trades) / n

            # 统计来源子系统分布
            from collections import Counter
            sources = dict(Counter(t.get("source_system", "unknown") for t in coin_trades))

            # reflection_ri: 胜率映射到 [0.5, 0.8]，样本量越小越保守
            # 基础映射: win_rate=0.5→0.50, 0.6→0.56, 0.7→0.62, 1.0→0.80
            base_ri = 0.5 + max(0.0, win_rate - 0.5) * 2 * 0.3
            base_ri = min(0.80, base_ri)

            # 样本量折扣：n=1 打 0.72 折，n=2 打 0.85 折，n≥3 不打折
            sample_discount = min(1.0, 0.72 + (n - 1) * 0.14) if n < 3 else 1.0
            reflection_ri = 0.5 + (base_ri - 0.5) * sample_discount
            reflection_ri = min(0.80, reflection_ri)

            eligible = (win_rate >= self.MIN_WIN_RATE) and (n >= self.MIN_TRADES)

            result[coin] = {
                "win_rate": round(win_rate, 4),
                "n_trades": n,
                "avg_pnl_pct": round(avg_pnl, 6),
                "reflection_ri": round(reflection_ri, 4),
                "eligible": eligible,
                "sources": sources,
            }

        self._cache = result
        self._cache_ts = time.time()
        return result

    def get_coin_stats(self, symbol: str, force: bool = False) -> dict[str, Any]:
        """获取单个币种的反思学习统计"""
        stats = self.scan(force=force)
        return stats.get(symbol, {
            "win_rate": 0.0,
            "n_trades": 0,
            "avg_pnl_pct": 0.0,
            "reflection_ri": 0.50,
            "eligible": False,
            "sources": {},
        })
