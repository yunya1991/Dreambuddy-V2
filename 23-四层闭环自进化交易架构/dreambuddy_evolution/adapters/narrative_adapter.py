"""
NarrativeAdapter — odaily 叙事标签库适配器
SPEC §2.3 / Phase 2

从 data_center.db 查询最近 odaily_newsflash 快讯，按 ticker 匹配 + 事件重要性
+ 情绪 + 时间衰减 计算叙事驱动力评分 ∈ [0, 1]。

叙事驱动力 = R_narrative，用于 apply_narrative_modifier 增强 R_flow。
三角验证①：叙事必须有资金验证（capital_flow > 0.5 才全额增强）。

FAIL-OPEN: 查询失败/无数据 → 返回 None（修饰子不生效）
"""
from __future__ import annotations

import json
import logging
import math
import sqlite3
import time
from typing import Any

logger = logging.getLogger(__name__)

_DB_TIMEOUT = 2.0

# 事件类型权重：不同事件对叙事驱动力的影响程度
_EVENT_TYPE_WEIGHT: dict[str, float] = {
    "regulatory": 1.3,           # 监管 — 高影响
    "monetary_policy": 1.2,      # 货币政策 — 高影响
    "project_ecosystem": 1.15,   # 项目生态 — 中高影响
    "market_sentiment": 1.0,     # 市场情绪 — 基准
    "partnership": 1.0,          # 合作 — 基准
    "integration": 1.0,          # 集成 — 基准
    "exchange_listing": 1.1,     # 交易所上线 — 中高
    "security_breach": 0.8,      # 安全事件 — 低（负面情绪由 sentiment 体现）
}

# 关注度类型偏移
_ATTENTION_BONUS: dict[str, float] = {
    "market_risk_on": 0.15,
    "market_risk_off": -0.15,
    "neutral": 0.0,
}

# Symbol 别名映射（odaily ticker 可能用全称）
_SYMBOL_ALIASES: dict[str, list[str]] = {
    "BTC": ["BTC", "BITCOIN"],
    "ETH": ["ETH", "ETHER", "ETHEREUM"],
    "SOL": ["SOL", "SOLANA"],
}


class NarrativeAdapter:
    """odaily 叙事标签库适配器"""

    def __init__(
        self,
        db_path: str | None = None,
        lookback_hours: int = 24,
        max_records: int = 200,
    ) -> None:
        self._db_path = db_path
        self._lookback_hours = lookback_hours
        self._max_records = max_records

    def get_narrative_score(self, symbol: str) -> float | None:
        """
        计算指定币种的叙事驱动力评分 ∈ [0, 1]。

        Returns:
            float in [0, 1] — 叙事驱动力（越高 = 越强看多叙事）
            None — 无数据或查询失败
        """
        if not self._db_path:
            return None

        try:
            records = self._query_recent_odaily(symbol)
            if not records:
                return None

            score = self._compute_narrative(records, symbol)
            if score is None:
                return None

            return max(0.0, min(1.0, score))

        except Exception as e:
            logger.debug("[FO] narrative score crash: %s", e)
            return None

    # ------------------------------------------------------------------ 查询
    def _query_recent_odaily(self, symbol: str) -> list[dict[str, Any]]:
        """查询最近 N 条 odaily_newsflash 记录"""
        try:
            conn = sqlite3.connect(self._db_path, timeout=_DB_TIMEOUT)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # 查询最近 lookback_hours 内的 odaily 快讯
            # 用 published_ms 过滤（比 timestamp 更可靠）
            cutoff_ms = int((time.time() - self._lookback_hours * 3600) * 1000)

            cursor.execute(
                "SELECT metrics, events, raw, timestamp FROM records "
                "WHERE source = 'odaily_newsflash' AND category = 'news' "
                "ORDER BY timestamp DESC LIMIT ?",
                (self._max_records,),
            )
            rows = cursor.fetchall()
            conn.close()

            records: list[dict[str, Any]] = []
            for row in rows:
                d = dict(row)
                try:
                    d["metrics"] = json.loads(d["metrics"]) if d.get("metrics") else {}
                except Exception:
                    d["metrics"] = {}
                try:
                    d["events"] = json.loads(d["events"]) if d.get("events") else []
                except Exception:
                    d["events"] = []
                try:
                    d["raw"] = json.loads(d["raw"]) if d.get("raw") else {}
                except Exception:
                    d["raw"] = {}
                records.append(d)

            return records

        except sqlite3.OperationalError as e:
            logger.debug("[FO] narrative DB query fail: %s", e)
            return []
        except Exception as e:
            logger.debug("[FO] narrative DB unexpected: %s", e)
            return []

    # ------------------------------------------------------------------ 计算
    def _compute_narrative(
        self, records: list[dict[str, Any]], symbol: str
    ) -> float | None:
        """
        从 odaily 记录计算叙事驱动力评分。

        算法:
        1. 分类: coin-specific (ticker 匹配) / broad-market (无 ticker)
        2. coin-specific 权重 = 1.0，broad-market 权重 = 0.3（广谱叙事打折）
        3. 每条记录评分 = clamp(sentiment + attention_bonus, 0, 1)
                        × importance_mult × event_type_weight × time_decay
        4. 加权平均
        """
        aliases = _SYMBOL_ALIASES.get(symbol.upper(), [symbol.upper()])

        weighted_sum = 0.0
        weight_total = 0.0

        for rec in records:
            metrics = rec.get("metrics", {}) if isinstance(rec, dict) else {}
            if not isinstance(metrics, dict):
                continue

            # 1. 分类: coin-specific vs broad-market
            tickers_str = str(metrics.get("od_tickers_hit_csl", "")).upper()
            if tickers_str:
                tickers = {t.strip() for t in tickers_str.split(",") if t.strip()}
                if not any(a in tickers for a in aliases):
                    continue  # 其他币种，跳过
                scope_weight = 1.0
            else:
                scope_weight = 0.3  # 广谱市场新闻，打折

            # 2. 基础情绪分
            sentiment = float(metrics.get("od_policy_sentiment_0_1", 0.5))

            # 3. 关注度偏移
            attention = str(metrics.get("od_attention_type", "neutral"))
            attention_bonus = _ATTENTION_BONUS.get(attention, 0.0)

            # 4. 基础分（clamp 到 [0, 1]）
            base = max(0.0, min(1.0, sentiment + attention_bonus))

            # 5. 重要性乘数
            is_important = bool(metrics.get("od_is_important", False))
            importance_mult = 2.0 if is_important else 1.0

            # 6. 事件类型权重
            event_type = str(metrics.get("od_event_type", "market_sentiment"))
            event_weight = _EVENT_TYPE_WEIGHT.get(event_type, 1.0)

            # 7. 时间衰减
            decay_hl = float(metrics.get("od_decay_hl_hrs", 6.0))
            decay_hl = max(decay_hl, 1.0)  # 防止除零
            age_hours = self._age_hours(rec)
            time_decay = math.exp(-age_hours / decay_hl)

            # 8. 加权
            weight = importance_mult * time_decay * scope_weight
            score = base * event_weight  # event_weight 作为加成

            weighted_sum += score * weight
            weight_total += weight

        if weight_total <= 0:
            return None

        return weighted_sum / weight_total

    @staticmethod
    def _age_hours(record: dict[str, Any]) -> float:
        """计算记录距今的小时数"""
        try:
            # 优先从 events[0].published_ms 取
            events = record.get("events", [])
            if isinstance(events, list) and events:
                pub_ms = events[0].get("published_ms")
                if pub_ms:
                    age_ms = time.time() * 1000 - float(pub_ms)
                    return max(0.0, age_ms / 3600000.0)

            # 回退到 timestamp 字段
            ts = record.get("timestamp")
            if ts:
                from datetime import datetime
                dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                age_s = time.time() - dt.timestamp()
                return max(0.0, age_s / 3600.0)
        except Exception:
            pass

        return 0.0  # 无法计算年龄 → 假设最新
