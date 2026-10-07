"""TDD-SVC-003: 跟涨催化因子（Follow-up Catalyst）。

> 版本: v1.0 (TDD-SVC-003 GREEN)
> SPEC: docs/superpowers/specs/2026-10-07-sector-valuation-comparison-spec.md §4.5

指标定义（SPEC §3.2 指标 3）：
  catalyst = leader_momentum × sector_breadth
    leader_momentum: 龙头 7d 收益率归一化 [-1, +1]（±20% 为满量程，线性映射）
    sector_breadth: 赛道内 7d 上涨币占比 [0, 1]

信号阈值：
  catalyst > 0.3：龙头强势 + 赛道广度好 → 跟涨概率高
  catalyst < -0.3：龙头弱势 + 赛道广度差 → 回避

铁律（SPEC §0.2）：
  R5 跟涨需龙头动量确认：仅「同赛道低估」不足以买入，需叠加龙头强势
  R4 FAIL-OPEN：数据不足不触发信号

调用复用：
  - SECTOR_MAP / _SECTOR_COIN_META / _fetch_coin_info（coin_fundamental_crypto）
  - _identify_sector_leader / _fetch_leader_7d_momentum（sector_waterline，TDD-SVC-001）
"""
from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from force_vector.coin_fundamental_crypto import (  # noqa: E402
    SECTOR_MAP,
    _SECTOR_COIN_META,
    _fetch_coin_info,
    _safe_json,
    DEFAULT_DB_PATH,
)
from force_vector.coin_fundamental_ranker import get_coingecko_id  # noqa: E402
from force_vector.sector_waterline import (  # noqa: E402
    _identify_sector_leader,
    _fetch_leader_7d_momentum,
)


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 龙头动量归一化尺度（与 sector_waterline 一致：±20% 为满量程）
_LEADER_MOMENTUM_SCALE = 0.20

# catalyst 信号阈值
_CATALYST_HIGH_THRESHOLD = 0.3
_CATALYST_LOW_THRESHOLD = -0.3


# ---------------------------------------------------------------------------
# 纯函数：compute_catalyst_score
# ---------------------------------------------------------------------------

def compute_catalyst_score(leader_momentum: float, sector_breadth: float) -> float:
    """合成跟涨催化因子：catalyst = leader_momentum × sector_breadth。

    Args:
        leader_momentum: 龙头 7d 收益率归一化 [-1, +1]
        sector_breadth: 赛道内 7d 上涨币占比 [0, 1]

    Returns:
        catalyst [-1, +1]：
          > 0.3：龙头强势 + 赛道广度好 → 跟涨概率高
          < -0.3：龙头弱势 + 赛道广度差 → 回避
    """
    if leader_momentum is None or sector_breadth is None:
        return 0.0
    try:
        lm = float(leader_momentum)
        sb = float(sector_breadth)
    except (TypeError, ValueError):
        return 0.0

    # clamp 输入到合理范围
    lm = max(-1.0, min(1.0, lm))
    sb = max(0.0, min(1.0, sb))

    catalyst = lm * sb
    return max(-1.0, min(1.0, catalyst))


# ---------------------------------------------------------------------------
# 数据获取：赛道内各币 7d 收益率
# ---------------------------------------------------------------------------

def _fetch_coin_7d_returns(sector: str, db_path: str) -> Dict[str, float]:
    """获取赛道内各币的 7d 收益率。

    数据源：CoinGecko coin_chart（source=coingecko, category=coin, sub_category=chart_{coin_id}）
    timeseries 格式：[{"date": ISO, "price": float, "market_cap": float, "volume": float}, ...]

    Returns:
        {coin_upper: 7d_return}，仅包含成功获取数据的币
        7d_return = price_now / price_7d_ago - 1
    """
    returns: Dict[str, float] = {}
    members = SECTOR_MAP.get(sector, [])
    if len(members) < 3:
        return returns

    for member in members:
        try:
            coin_id = get_coingecko_id(member)
            if not coin_id or not db_path or not os.path.exists(db_path):
                continue

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
                    continue

                ts = _safe_json(row[0])
                if not isinstance(ts, list) or len(ts) < 8:
                    continue

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
                    continue

                price_now = valid_prices[-1]
                price_7d_ago = valid_prices[-8]
                if price_7d_ago <= 0:
                    continue

                returns[member] = (price_now / price_7d_ago) - 1.0
            finally:
                conn.close()
        except Exception:
            continue  # FAIL-OPEN

    return returns


# ---------------------------------------------------------------------------
# 赛道广度：7d 上涨币占比
# ---------------------------------------------------------------------------

def _compute_sector_breadth(sector: str, db_path: str) -> float:
    """计算赛道内 7d 上涨币占比 [0, 1]。

    上涨定义：7d 收益率 >= 0（持平计为上涨）
    广度 = 上涨币数 / 总币数

    FAIL-OPEN：无数据 → 返回 0.0
    """
    try:
        returns = _fetch_coin_7d_returns(sector, db_path)
        if not returns:
            return 0.0

        up_count = sum(1 for r in returns.values() if r >= 0)
        return up_count / len(returns)
    except Exception:
        return 0.0  # FAIL-OPEN


# ---------------------------------------------------------------------------
# 主函数：compute_follow_up_catalyst
# ---------------------------------------------------------------------------

def compute_follow_up_catalyst(
    sector: str, db_path: Optional[str] = None
) -> Dict[str, object]:
    """计算跟涨催化因子（SPEC §4.5）。

    流程：
      1. 识别龙头（市值最大）+ 7d 动量
      2. 计算赛道广度（7d 上涨币占比）
      3. 合成 catalyst = leader_momentum × sector_breadth

    Args:
        sector: 赛道名称（如 "DEX"）
        db_path: data_center.db 路径；None 用 DEFAULT_DB_PATH

    Returns:
        Dict 包含：
          - leader: 龙头币符号（空字符串表示未识别）
          - leader_momentum: 龙头 7d 动量 [-1, +1]
          - sector_breadth: 赛道广度 [0, 1]
          - catalyst: 跟涨催化因子 [-1, +1]
          - timestamp: ISO 时间戳
    """
    if not db_path:
        db_path = DEFAULT_DB_PATH

    # FAIL-OPEN 中性默认
    neutral: Dict[str, object] = {
        "leader": "",
        "leader_momentum": 0.0,
        "sector_breadth": 0.0,
        "catalyst": 0.0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if not sector:
        return neutral

    members = SECTOR_MAP.get(sector, [])
    if len(members) < 3:
        return neutral  # R4 FAIL-OPEN

    try:
        # 1. 识别龙头 + 7d 动量
        leader, _ = _identify_sector_leader(members, db_path)
        if not leader:
            # 龙头识别失败 → 仍计算赛道广度但 catalyst=0
            breadth = _compute_sector_breadth(sector, db_path)
            return {
                "leader": "",
                "leader_momentum": 0.0,
                "sector_breadth": breadth,
                "catalyst": 0.0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        leader_momentum = _fetch_leader_7d_momentum(leader, db_path)

        # 2. 赛道广度
        sector_breadth = _compute_sector_breadth(sector, db_path)

        # 3. 合成 catalyst
        catalyst = compute_catalyst_score(leader_momentum, sector_breadth)

        return {
            "leader": leader,
            "leader_momentum": leader_momentum,
            "sector_breadth": sector_breadth,
            "catalyst": catalyst,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        return neutral  # FAIL-OPEN
