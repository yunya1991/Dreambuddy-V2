"""估值分位真实查询 — ValuationQuery。

从 data_center.db records 表查 coingecko coin_chart 的 timeseries，
计算当前 market_cap 在历史序列中的百分位 [0, 100]，供阶段识别器使用。

数据源：CoinGecko coin_chart（source=coingecko, category=coin, sub_category=chart_{coin_id}）
timeseries 格式：[{"date": ISO, "price": float, "market_cap": float, "volume": float}, ...]

FAIL-OPEN：任何异常或数据不足 → 返回 50.0（中性），不阻塞阶段识别。
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from typing import List, Optional

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

# data_center.db 默认路径：dreambuddy-v2/18-数据获取中心/data_center.db
_REPO = os.path.normpath(os.path.join(_THIS_DIR, "..", "..", "..", ".."))
DEFAULT_DB_PATH = os.path.join(_REPO, "18-数据获取中心", "data_center.db")

# 数据不足的阈值：序列长度 < 7（不足一周）→ 返回中性 50
_MIN_SERIES_LEN = 7

# 中性默认值
_NEUTRAL_PERCENTILE = 50.0


# ===========================================================================
# 纯函数：百分位计算
# ===========================================================================

def _compute_percentile(series: List[float], current: float) -> float:
    """计算 current 在 series 中的百分位 [0, 100]。

    规则：
    - 过滤 market_cap=0 的点（数据缺失）
    - 序列长度 < 7（不足一周）→ 返回 50（中性，数据不足）
    - current <= 0 → 返回 50（中性，避免误判）
    - 百分位 = (rank of current) / len(valid) * 100
      rank = 序列中 <= current 的元素个数
    """
    # 过滤 0 值（数据缺失）
    valid = [float(x) for x in series if x and float(x) > 0]
    if len(valid) < _MIN_SERIES_LEN:
        return _NEUTRAL_PERCENTILE
    if not current or float(current) <= 0:
        return _NEUTRAL_PERCENTILE

    current = float(current)
    # rank = 序列中 <= current 的元素个数
    rank = sum(1 for x in valid if x <= current)
    pct = rank / len(valid) * 100.0
    # 钳制到 [0, 100]
    return max(0.0, min(100.0, pct))


# ===========================================================================
# DB 查询
# ===========================================================================

def query_valuation_percentile(coin: str, db_path: Optional[str] = None) -> float:
    """从 data_center.db 查询指定币种的估值分位。

    流程：
    1. get_coingecko_id(coin) → coin_id
    2. 查 records 表 sub_category=chart_{coin_id} 的最新一条记录
    3. 解析 timeseries JSON，提取 market_cap 序列
    4. 取序列最后一点作为 current market_cap
    5. 调用 _compute_percentile 返回百分位

    FAIL-OPEN：任何异常（db 不存在/表缺失/JSON 畸形/数据不足）→ 返回 50.0。
    """
    try:
        # 延迟导入避免循环依赖
        from force_vector.coin_fundamental_ranker import get_coingecko_id
        coin_id = get_coingecko_id(coin)
        if not coin_id:
            return _NEUTRAL_PERCENTILE

        if not db_path:
            db_path = DEFAULT_DB_PATH

        if not os.path.exists(db_path):
            return _NEUTRAL_PERCENTILE

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
                return _NEUTRAL_PERCENTILE

            ts_json = row[0]
            ts = json.loads(ts_json)
            if not isinstance(ts, list) or not ts:
                return _NEUTRAL_PERCENTILE

            # 提取 market_cap 序列
            mcaps: List[float] = []
            for item in ts:
                if isinstance(item, dict):
                    mc = item.get("market_cap", 0)
                    try:
                        mcaps.append(float(mc) if mc is not None else 0.0)
                    except (TypeError, ValueError):
                        mcaps.append(0.0)

            if not mcaps:
                return _NEUTRAL_PERCENTILE

            current = mcaps[-1]
            return _compute_percentile(mcaps, current)
        finally:
            conn.close()
    except Exception:
        # FAIL-OPEN：任何异常 → 中性 50
        return _NEUTRAL_PERCENTILE
