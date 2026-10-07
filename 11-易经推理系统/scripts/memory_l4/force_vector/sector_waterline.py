"""TDD-SVC-001: 赛道整体估值水位（Sector Valuation Waterline）。

> 版本: v1.0 (TDD-SVC-001 GREEN)
> SPEC: docs/superpowers/specs/2026-10-07-sector-valuation-comparison-spec.md §4.2

设计决策（SPEC §4.2）：
  水位用「纵向百分位的中位数」而非「横向百分位的中位数」：
    - 横向百分位：该币在赛道中相对便宜/贵，无法判断赛道整体是否处于历史高位
    - 纵向百分位：该币自身是否处于历史高位，中位数反映赛道整体泡沫程度

铁律（SPEC §0.2）：
  R2 中位数优先于均值（抗异常值，估值倍数右偏分布）
  R4 FAIL-OPEN 中性（数据不足不触发信号）

调用复用：
  - query_valuation_percentile（coin_fundamental_valuation_query）→ 纵向百分位
  - SECTOR_MAP / _SECTOR_COIN_META / _fetch_coin_info（coin_fundamental_crypto）→ 赛道成员 + 市值
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from statistics import median
from typing import Dict, List, Optional

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

# 复用现有 BDSM E8 的赛道定义与数据读取
from force_vector.coin_fundamental_crypto import (  # noqa: E402
    SECTOR_MAP,
    _SECTOR_COIN_META,
    _fetch_coin_info,
    _safe_json,
    DEFAULT_DB_PATH,
)
from force_vector.coin_fundamental_ranker import get_coingecko_id  # noqa: E402
from force_vector.coin_fundamental_valuation_query import (  # noqa: E402
    query_valuation_percentile,
    _NEUTRAL_PERCENTILE,
)


# ---------------------------------------------------------------------------
# 常量（SPEC §3.2 指标 1）
# ---------------------------------------------------------------------------

# waterline >= 80 → 赛道过热（离场信号）
_OVERHEATED_THRESHOLD = 80.0
# waterline <= 20 → 赛道低估（关注机会）
_UNDERVALUED_THRESHOLD = 20.0
# 有效数据成员下限（R4 FAIL-OPEN：成员 < 3 → 返回 None）
_MIN_MEMBER_COUNT = 3
# 龙头动量归一化尺度：±20% 为 1σ 满量程（tanh(1) ≈ 0.76）
_LEADER_MOMENTUM_SCALE = 0.20


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class SectorWaterline:
    """赛道整体估值水位（SPEC §4.2）。

    Attributes:
        sector: 赛道名称（DEX/Lending/L1/L2/Meme/Perp_DEX）
        median_percentile: 赛道整体估值百分位 [0, 100]
        member_count: 有效数据成员数
        overheated: waterline >= 80 → 赛道过热（离场信号）
        undervalued: waterline <= 20 → 赛道低估（关注机会）
        leader: 赛道龙头（市值最大）
        leader_momentum_7d: 龙头 7d 收益率归一化 [-1, +1]
        timestamp: ISO 时间戳
    """
    sector: str
    median_percentile: float
    member_count: int
    overheated: bool
    undervalued: bool
    leader: str
    leader_momentum_7d: float
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ---------------------------------------------------------------------------
# 龙头 7d 动量（从 coingecko coin_chart timeseries 取 price 序列）
# ---------------------------------------------------------------------------

def _fetch_leader_7d_momentum(coin: str, db_path: str) -> float:
    """计算龙头 7d 价格收益率并归一化到 [-1, +1]。

    数据源优先级：
      1. _fetch_coin_info 的 metrics 中 price_now/price_7d_ago 字段（如有则直接用）
      2. CoinGecko coin_chart timeseries（chart_{coin_id}）的 price 序列首尾对比

    归一化：return = (price_now / price_7d_ago - 1)，再用线性映射 ret / 0.20 → [-1, +1]
      ±20% 收益率 → ±1.0（满量程，与 SPEC §4.5 §8.1 一致）
      ±10% 收益率 → ±0.5
      超过 ±20% → clamp 到 ±1.0

    FAIL-OPEN：任何异常 / 数据不足 → 返回 0.0（中性）
    """
    try:
        coin_id = get_coingecko_id(coin)
        if not coin_id:
            return 0.0

        # 优先级 1：从 _fetch_coin_info 取 price_now/price_7d_ago
        if coin_id:
            try:
                info = _fetch_coin_info(db_path, coin_id) if db_path else {}
                if info:
                    price_now = float(info.get("price_now", 0) or 0)
                    price_7d = float(info.get("price_7d_ago", 0) or 0)
                    if price_now > 0 and price_7d > 0:
                        ret = (price_now / price_7d) - 1.0
                        # 线性归一化：±20% 为满量程，clamp 到 [-1, +1]
                        momentum = max(-1.0, min(1.0, ret / _LEADER_MOMENTUM_SCALE))
                        return momentum
            except Exception:
                pass  # fall-through 到优先级 2

        # 优先级 2：从 chart timeseries 取 price 序列
        if not db_path or not os.path.exists(db_path):
            return 0.0

        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.execute(
                "SELECT timeseries FROM records "
                "WHERE source='coingecko' AND category='coin' "
                "AND sub_category=? "
                "ORDER BY timestamp DESC LIMIT 1",
                (f"chart_{coin_id}",),
            )
            row = cursor.fetchone()
            if not row or not row[0]:
                return 0.0

            ts = _safe_json(row[0])
            if not isinstance(ts, list) or len(ts) < 8:
                return 0.0  # 至少需要 8 天才能算 7d 前

            # 提取 price 序列
            prices: List[float] = []
            for item in ts:
                if isinstance(item, dict):
                    p = item.get("price", 0)
                    try:
                        prices.append(float(p) if p is not None else 0.0)
                    except (TypeError, ValueError):
                        prices.append(0.0)

            valid_prices = [p for p in prices if p > 0]
            if len(valid_prices) < 8:
                return 0.0

            price_now = valid_prices[-1]
            price_7d_ago = valid_prices[-8]  # 7 天前（含今天共 8 个点）
            if price_7d_ago <= 0:
                return 0.0

            ret = (price_now / price_7d_ago) - 1.0
            # 线性归一化：±20% 为满量程，clamp 到 [-1, +1]
            momentum = max(-1.0, min(1.0, ret / _LEADER_MOMENTUM_SCALE))
            return momentum
        finally:
            conn.close()
    except Exception:
        return 0.0  # FAIL-OPEN


# ---------------------------------------------------------------------------
# 龙头识别（市值最大）
# ---------------------------------------------------------------------------

def _identify_sector_leader(
    sector_members: List[str], db_path: str
) -> tuple[Optional[str], Dict[str, float]]:
    """识别赛道龙头（市值最大）。

    Returns:
        (leader_coin, market_caps_map) — leader_coin 为 None 表示无有效市值数据
        market_caps_map: {coin_upper: market_cap_usd}
    """
    market_caps: Dict[str, float] = {}
    for member in sector_members:
        meta = _SECTOR_COIN_META.get(member)
        if meta is None:
            continue
        coin_id = meta.get("coingecko_id")
        if not coin_id:
            continue
        try:
            info = _fetch_coin_info(db_path, coin_id) if coin_id else {}
            mc = float(info.get("market_cap_usd", 0) or 0)
            if mc > 0:
                market_caps[member] = mc
        except Exception:
            continue  # FAIL-OPEN：单个币失败不影响其他

    if not market_caps:
        return None, market_caps

    # 市值最大者为龙头
    leader = max(market_caps, key=market_caps.get)
    return leader, market_caps


# ---------------------------------------------------------------------------
# 主函数：compute_sector_waterline
# ---------------------------------------------------------------------------

def compute_sector_waterline(
    sector: str, db_path: Optional[str] = None
) -> Optional[SectorWaterline]:
    """计算赛道整体估值水位（SPEC §4.2）。

    流程：
      1. 取赛道 SECTOR_MAP 成员
      2. 对每个币，调用 query_valuation_percentile 获取纵向百分位
      3. 过滤中性值（== 50.0 数据不足），统计有效数据点
      4. 若有效数据点 < 3 → FAIL-OPEN 返回 None
      5. 取所有有效百分位的中位数作为赛道水位
      6. 识别龙头（市值最大），计算龙头 7d 动量

    Args:
        sector: 赛道名称（如 "DEX"）
        db_path: data_center.db 路径；None 用 DEFAULT_DB_PATH

    Returns:
        SectorWaterline 或 None（成员 < 3 / 数据不足）
    """
    if not sector:
        return None

    members = SECTOR_MAP.get(sector, [])
    if len(members) < _MIN_MEMBER_COUNT:
        return None  # R4 FAIL-OPEN：成员 < 3

    if not db_path:
        db_path = DEFAULT_DB_PATH

    # 1. 收集各币纵向百分位
    percentiles: List[float] = []
    for member in members:
        try:
            pct = query_valuation_percentile(member, db_path)
            if pct is not None and 0.0 <= pct <= 100.0:
                percentiles.append(float(pct))
        except Exception:
            continue  # FAIL-OPEN：单个币失败不影响其他

    # 2. 过滤中性值（数据不足返回 50.0）
    #    如果所有百分位都是 50.0，说明赛道整体数据不足 → FAIL-OPEN
    non_neutral = [p for p in percentiles if abs(p - _NEUTRAL_PERCENTILE) > 1e-6]
    if len(non_neutral) < _MIN_MEMBER_COUNT:
        return None  # R4 FAIL-OPEN：有效数据 < 3

    # 3. 中位数作为赛道水位（R2 中位数优先）
    waterline = float(median(non_neutral))

    # 4. 识别龙头 + 7d 动量
    leader, _ = _identify_sector_leader(members, db_path)
    leader_name = leader or ""
    leader_momentum = 0.0
    if leader:
        leader_momentum = _fetch_leader_7d_momentum(leader, db_path)

    # 5. 判定过热/低估标志
    overheated = waterline >= _OVERHEATED_THRESHOLD
    undervalued = waterline <= _UNDERVALUED_THRESHOLD

    return SectorWaterline(
        sector=sector,
        median_percentile=waterline,
        member_count=len(non_neutral),
        overheated=overheated,
        undervalued=undervalued,
        leader=leader_name,
        leader_momentum_7d=leader_momentum,
    )
