"""
SentimentBridge — 桥接 SentimentEngine 输出为 R_reflexivity 所需的 news_sentiment_score
SPEC §2.3

FAIL-OPEN 三级（对齐硬约束 VM-1788443193342）:
  L0: USE_FINBERT=0 → 规则引擎 → quality 扣 0.15
  L1: SentimentEngine 加载失败 → score=0.5 (中性)
  L2: 单条文本异常 → 该条 score=0.0
  L3: 数据源查询失败 → score=0.5

缓存模式：6h 更新一次，避免每轮调用 FinBERT
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from typing import Any

logger = logging.getLogger(__name__)

_DB_TIMEOUT = 2.0
_CACHE_TTL = 6 * 3600  # 6 小时


class SentimentBridge:
    """SentimentEngine 桥接器"""

    def __init__(
        self,
        data_center_db: str | None = None,
        sentiment_engine: Any = None,
        cache_ttl: int = _CACHE_TTL,
    ) -> None:
        self._db_path = data_center_db
        self._engine = sentiment_engine
        self._cache_ttl = cache_ttl
        self._cached_score: float = 0.5
        self._cache_ts: float = 0.0

    def get_sentiment_score(self, symbol: str | None = None) -> float:
        """
        获取 news_sentiment_score ∈ [0, 1]。

        缓存模式下每 cache_ttl 秒更新一次。
        """
        now = time.time()
        if now - self._cache_ts < self._cache_ttl:
            return self._cached_score

        score = self._compute_score()
        self._cached_score = score
        self._cache_ts = now
        return score

    def _compute_score(self) -> float:
        """从快讯文本计算情绪分数"""
        texts = self._fetch_recent_newsflash()
        if not texts:
            return 0.5  # L3: 数据源失败

        engine = self._get_engine()
        if engine is None:
            return 0.5  # L1: 引擎加载失败

        scores = []
        for text in texts:
            try:
                result = engine.analyze_text(text)
                raw = float(result.get("score", 0.0))
                scores.append(raw)
            except Exception as e:
                logger.debug("[FO] single text sentiment fail: %s", e)
                scores.append(0.0)  # L2: 单条异常

        if not scores:
            return 0.5

        # 时间加权聚合 (简单平均；后续可加 time_decay)
        avg = sum(scores) / len(scores)
        # 归一化 [-1, +1] → [0, 1]
        return max(0.0, min(1.0, (avg + 1.0) / 2.0))

    def _get_engine(self) -> Any:
        """获取 SentimentEngine 实例（延迟加载，单例）"""
        if self._engine is not None:
            return self._engine

        try:
            import sys as _sys
            # 尝试导入 SentimentEngine
            _engine_path = None
            for p in _sys.path:
                if "9-基本面分析" in p:
                    _engine_path = p
                    break

            if _engine_path is None:
                # 尝试从项目根目录导入
                from pathlib import Path
                _root = Path(__file__).resolve().parent.parent.parent.parent
                _bp = str(_root / "9-基本面分析" / "engines")
                if _bp not in _sys.path:
                    _sys.path.insert(0, _bp)

            from sentiment_engine import SentimentEngine  # type: ignore
            self._engine = SentimentEngine()
            return self._engine

        except Exception as e:
            logger.warning("[FO] SentimentEngine load fail (L1): %s", e)
            return None

    def _fetch_recent_newsflash(self, count: int = 5) -> list[str]:
        """从 data_center.db 查询最近 N 条 odaily 快讯文本"""
        if not self._db_path:
            return []

        try:
            conn = sqlite3.connect(self._db_path, timeout=_DB_TIMEOUT)
            cursor = conn.cursor()

            # 尝试查询 odaily newsflash
            try:
                cursor.execute(
                    "SELECT metrics FROM records "
                    "WHERE source = 'odaily' AND sub_category = 'newsflash' "
                    "ORDER BY timestamp DESC LIMIT ?", (count,)
                )
                rows = cursor.fetchall()
            except sqlite3.OperationalError:
                # 表不存在或字段不匹配
                conn.close()
                return []

            conn.close()

            texts = []
            for row in rows:
                try:
                    d = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                    text = d.get("title") or d.get("content") or d.get("text") or ""
                    if text:
                        texts.append(text)
                except Exception:
                    continue
            return texts

        except Exception as e:
            logger.debug("[FO] newsflash fetch fail: %s", e)
            return []

    def invalidate_cache(self) -> None:
        """手动失效缓存（测试用）"""
        self._cache_ts = 0.0
