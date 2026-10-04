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

P0: backtest 来源折扣（source_system="backtest" 施加 0.85 折扣）
P1a: 跨币种类先验继承（无交易记录的币种从同 asset_class 继承先验）
"""
import os
import time
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _get_backtest_discount() -> float:
    """从环境变量读取回测来源折扣系数，默认 0.85。FAIL-OPEN：异常返回 0.85。"""
    try:
        raw = os.environ.get("REFLECTION_BACKTEST_DISCOUNT", "0.85")
        val = float(raw)
        if val <= 0 or val > 1.0:
            logger.warning("[FO] backtest discount out of range: %s, use default 0.85", raw)
            return 0.85
        return val
    except (ValueError, TypeError) as e:
        logger.warning("[FO] backtest discount parse fail: %s, use default 0.85", e)
        return 0.85


class ReflectionScanner:
    """反思学习扫描器 — 从系统级交易索引库学习胜率，作为第二条交易起点"""

    MIN_WIN_RATE = 0.55
    MIN_TRADES = 1
    MAX_HISTORY_DAYS = 90
    CACHE_TTL = 600

    def __init__(self, trades_path: str | Path | None = None, project_root: str | Path | None = None):
        if project_root is None:
            project_root = Path.cwd()
        self._project_root = Path(project_root)
        self._index_builder: Any = None
        self._cache: dict[str, dict[str, Any]] | None = None
        self._cache_ts: float = 0.0
        self._class_priors: dict[str, dict[str, Any]] = {}

    def _get_index_builder(self):
        if self._index_builder is None:
            from dreambuddy_evolution.engines.trade_index_builder import TradeIndexBuilder
            self._index_builder = TradeIndexBuilder(project_root=self._project_root)
        return self._index_builder

    def _load_trades(self) -> list[dict[str, Any]]:
        try:
            return self._get_index_builder().get_trades(force=False)
        except Exception as e:
            logger.warning("[FO] load trades from index fail: %s", e)
            return []

    def _is_recent(self, trade: dict[str, Any]) -> bool:
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
        if not force and self._cache is not None:
            if time.time() - self._cache_ts < self.CACHE_TTL:
                return self._cache

        trades = self._load_trades()
        recent = [t for t in trades if self._is_recent(t)]

        by_coin: dict[str, list[dict[str, Any]]] = {}
        for t in recent:
            coin = t.get("coin") or t.get("symbol")
            if not coin:
                continue
            by_coin.setdefault(coin, []).append(t)

        result: dict[str, dict[str, Any]] = {}
        backtest_discount = _get_backtest_discount()
        for coin, coin_trades in by_coin.items():
            n = len(coin_trades)
            if n == 0:
                continue

            real_trades = [t for t in coin_trades if t.get("source_system") != "backtest"]
            backtest_trades = [t for t in coin_trades if t.get("source_system") == "backtest"]
            stat_trades = real_trades if real_trades else backtest_trades
            is_backtest_only = len(real_trades) == 0 and len(backtest_trades) > 0

            stat_n = len(stat_trades)
            wins = sum(1 for t in stat_trades if t.get("pnl", 0) > 0)
            win_rate = wins / stat_n
            avg_pnl = sum(t.get("pnl_pct", 0) for t in stat_trades) / stat_n

            from collections import Counter
            sources = dict(Counter(t.get("source_system", "unknown") for t in coin_trades))

            base_ri = 0.5 + max(0.0, win_rate - 0.5) * 2 * 0.3
            base_ri = min(0.80, base_ri)
            sample_discount = min(1.0, 0.72 + (stat_n - 1) * 0.14) if stat_n < 3 else 1.0
            reflection_ri = 0.5 + (base_ri - 0.5) * sample_discount
            reflection_ri = max(0.50, min(0.80, reflection_ri))

            min_win_rate = 0.50 if is_backtest_only else self.MIN_WIN_RATE
            eligible = (win_rate >= min_win_rate) and (stat_n >= self.MIN_TRADES)

            if is_backtest_only:
                try:
                    reflection_ri = reflection_ri * backtest_discount
                    if eligible and reflection_ri < 0.55:
                        reflection_ri = 0.55
                    reflection_ri = min(0.80, reflection_ri)
                except Exception as e:
                    logger.warning("[FO] backtest discount apply fail for %s: %s", coin, e)

            result[coin] = {
                "win_rate": round(win_rate, 4),
                "n_trades": stat_n,
                "avg_pnl_pct": round(avg_pnl, 6),
                "reflection_ri": round(reflection_ri, 4),
                "eligible": eligible,
                "sources": sources,
                "is_backtest_only": is_backtest_only,
                "is_prior": False,
            }

        # P1a: 计算类先验
        self._class_priors = self._compute_class_priors(result, backtest_discount)

        self._cache = result
        self._cache_ts = time.time()
        return result

    def _compute_class_priors(
        self, coin_stats: dict[str, dict[str, Any]], backtest_discount: float
    ) -> dict[str, dict[str, Any]]:
        """P1a: 按 asset_class 分组计算类先验。

        类先验 ri 上限 0.65（比单币种 0.80 更保守）。
        FAIL-OPEN: 整个方法 try/except，失败返回 {}。
        """
        try:
            from dreambuddy_evolution.engines.asset_class_mapper import get_asset_class

            class_data: dict[str, dict[str, Any]] = {}
            for coin, s in coin_stats.items():
                ac = get_asset_class(coin)
                if ac is None:
                    continue
                cd = class_data.setdefault(ac, {"total_n": 0, "total_wins": 0, "has_real": False})
                n = s.get("n_trades", 0)
                cd["total_n"] += n
                cd["total_wins"] += int(n * s.get("win_rate", 0.0))
                if not s.get("is_backtest_only", False):
                    cd["has_real"] = True

            priors: dict[str, dict[str, Any]] = {}
            for ac, cd in class_data.items():
                n = cd["total_n"]
                if n == 0:
                    continue
                class_wr = cd["total_wins"] / n
                base_ri = 0.5 + max(0.0, class_wr - 0.5) * 2 * 0.3
                sample_discount = min(1.0, 0.72 + (n - 1) * 0.14) if n < 3 else 1.0
                class_ri = 0.5 + (base_ri - 0.5) * sample_discount
                class_ri = max(0.50, min(0.80, class_ri))
                if not cd["has_real"]:
                    class_ri = class_ri * backtest_discount
                class_ri = min(0.65, class_ri)  # 类先验上限 0.65
                class_eligible = class_wr >= 0.50
                if class_eligible and class_ri < 0.55:
                    class_ri = 0.55

                priors[ac] = {
                    "class_win_rate": round(class_wr, 4),
                    "class_n_trades": n,
                    "class_reflection_ri": round(class_ri, 4),
                    "class_eligible": class_eligible,
                    "has_real_trades": cd["has_real"],
                }
            return priors
        except Exception as e:
            logger.warning("[FO] class priors compute fail: %s", e)
            return {}

    def get_coin_stats(self, symbol: str, force: bool = False) -> dict[str, Any]:
        """获取单个币种统计。无记录时尝试类先验继承（P1a）。"""
        stats = self.scan(force=force)
        if symbol in stats:
            return stats[symbol]

        # P1a: 类先验继承
        try:
            from dreambuddy_evolution.engines.asset_class_mapper import get_asset_class
            ac = get_asset_class(symbol)
            if ac and ac in self._class_priors:
                prior = self._class_priors[ac]
                return {
                    "win_rate": prior["class_win_rate"],
                    "n_trades": 0,
                    "avg_pnl_pct": 0.0,
                    "reflection_ri": prior["class_reflection_ri"],
                    "eligible": prior["class_eligible"],
                    "sources": {},
                    "is_backtest_only": not prior["has_real_trades"],
                    "is_prior": True,
                    "asset_class": ac,
                }
        except Exception as e:
            logger.warning("[FO] class prior lookup fail for %s: %s", symbol, e)

        return {
            "win_rate": 0.0,
            "n_trades": 0,
            "avg_pnl_pct": 0.0,
            "reflection_ri": 0.50,
            "eligible": False,
            "sources": {},
            "is_backtest_only": False,
            "is_prior": False,
        }
