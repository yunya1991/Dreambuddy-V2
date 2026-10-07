"""估值分位真实查询 — ValuationQuery。

优先通过 19-数据访问层 (DAL) 的 MarketMacroRepository.query_metric_by_time
读取 coingecko coin_chart 展平后的 mm_metrics 行（sub_category=chart_{coin_id},
metric_name=market_cap），计算当前 market_cap 在历史序列中的百分位 [0, 100]。

19-DAL 数据缺失时 fallback 直读 18-数据获取中心 data_center.db records 表
的 timeseries JSON（兼容旧路径，保证 FAIL-OPEN）。

数据源：CoinGecko coin_chart（source=coingecko, category=coin, sub_category=chart_{coin_id}）
- 18-DB records.timeseries 格式：[{"date": ISO, "price": float, "market_cap": float, "volume": float}, ...]
- 19-DAL mm_metrics：每点一行 (source, sub_category, metric_name='market_cap', metric_value, timestamp)

FAIL-OPEN：任何异常或数据不足 → 返回 50.0（中性），不阻塞阶段识别。
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from typing import List, Optional

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

# data_center.db 默认路径：dreambuddy-v2/18-数据获取中心/data_center.db
_REPO = os.path.normpath(os.path.join(_THIS_DIR, "..", "..", "..", ".."))
DEFAULT_DB_PATH = os.path.join(_REPO, "18-数据获取中心", "data_center.db")

# 19-DAL dreambuddy_core.db 默认路径：dreambuddy-v2/19-数据访问层/data/dreambuddy_core.db
DEFAULT_DAL_DB_PATH = os.path.join(_REPO, "19-数据访问层", "data", "dreambuddy_core.db")

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

def _query_via_18db(coin: str, db_path: Optional[str] = None) -> float:
    """Fallback 路径：直读 18-数据获取中心 data_center.db records 表的 timeseries JSON。

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


def _query_via_dal(coin: str, dal_db_path: Optional[str] = None) -> float:
    """优先路径：通过 19-数据访问层 MarketMacroRepository 读取 mm_metrics 展平数据。

    流程：
    1. get_coingecko_id(coin) → coin_id
    2. 实例化 SqliteMarketMacroRepository(dal_db_path)
    3. query_metric_by_time(sub_category=chart_{coin_id}, metric_name='market_cap',
       start_ts=2000-01-01, end_ts=2100-01-01) → 全部 720 点
    4. 取序列最后一点作为 current market_cap
    5. 调用 _compute_percentile 返回百分位

    FAIL-OPEN：任何异常（DAL 未导入/db 缺失/表空/数据不足）→ 返回 50.0，
    调用方应再 fallback 到 _query_via_18db。
    """
    try:
        from force_vector.coin_fundamental_ranker import get_coingecko_id
        coin_id = get_coingecko_id(coin)
        if not coin_id:
            return _NEUTRAL_PERCENTILE

        if not dal_db_path:
            dal_db_path = DEFAULT_DAL_DB_PATH

        if not os.path.exists(dal_db_path):
            return _NEUTRAL_PERCENTILE

        # 延迟导入 DAL，避免未安装时影响其他模块
        dal_root = os.path.join(_REPO, "19-数据访问层")
        if dal_root not in sys.path:
            sys.path.insert(0, dal_root)
        from dreambuddy_dal.implementations.sqlite_unified.market_macro_impl import (
            SqliteMarketMacroRepository,
        )

        repo = SqliteMarketMacroRepository(dal_db_path)
        # 查询全部历史数据（时间范围足够大覆盖 720 点）
        rows = repo.query_metric_by_time(
            sub_category=f"chart_{coin_id}",
            metric_name="market_cap",
            start_ts=datetime(2000, 1, 1, tzinfo=timezone.utc),
            end_ts=datetime(2100, 1, 1, tzinfo=timezone.utc),
        )
        if not rows:
            return _NEUTRAL_PERCENTILE

        # rows: [(source, metric_name, value, datetime), ...] 按 timestamp ASC
        mcaps: List[float] = []
        for r in rows:
            try:
                mcaps.append(float(r[2]) if r[2] is not None else 0.0)
            except (TypeError, ValueError):
                mcaps.append(0.0)

        if not mcaps:
            return _NEUTRAL_PERCENTILE

        current = mcaps[-1]
        return _compute_percentile(mcaps, current)
    except Exception:
        # FAIL-OPEN：DAL 路径任何异常 → 中性 50，调用方应 fallback 18-DB
        return _NEUTRAL_PERCENTILE


def query_valuation_percentile(coin: str, db_path: Optional[str] = None) -> float:
    """查询指定币种的估值分位 [0, 100]，供阶段识别器使用。

    优先路径：19-数据访问层 (DAL) mm_metrics 展平数据（统一数据底座）。
    Fallback 路径：18-数据获取中心 data_center.db records timeseries JSON。

    策略：
    1. 先调 _query_via_dal(coin, db_path) 走 19-DAL
    2. 如果 DAL 返回中性 50.0（可能数据未导入），再调 _query_via_18db fallback
    3. 取两者中"非中性"的值；都中性则返回 50.0

    FAIL-OPEN：任何异常或数据不足 → 返回 50.0（中性），不阻塞阶段识别。

    Args:
        coin: 币种符号（BTC/ETH/...）
        db_path: 可选，18-DB 路径（fallback 用）；DAL 路径用 DEFAULT_DAL_DB_PATH
    """
    # 优先 19-DAL
    dal_pct = _query_via_dal(coin)
    if dal_pct != _NEUTRAL_PERCENTILE:
        return dal_pct

    # DAL 中性 → fallback 18-DB
    db_pct = _query_via_18db(coin, db_path)
    if db_pct != _NEUTRAL_PERCENTILE:
        return db_pct

    # 都中性 → 返回中性 50.0
    return _NEUTRAL_PERCENTILE
