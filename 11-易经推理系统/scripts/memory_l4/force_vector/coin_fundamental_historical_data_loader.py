"""真实历史数据加载器 — HistoricalDataLoader (F3)。

从 data_center.db 查询三个数据源的历史时间序列，构造真实 PhaseSnapshot 序列，
替换 phase_replay.py 中的合成快照数据，用于 UNI/CRCL/HYPE 案例真实回放。

数据源：
  1. DeFiLlama protocol_fees（source=defillama, category=chain,
     sub_category=fees_{protocol}）
     timeseries: [{"date": ISO, "fees_usd": float}, ...]
  2. CoinGecko market_chart（source=coingecko, category=coin,
     sub_category=chart_{coin_id}）
     timeseries: [{"date": ISO, "price": float, "market_cap": float, "volume": float}, ...]
  3. yfinance 价格（source=yfinance, category=stock/crypto,
     sub_category=symbol）
     timeseries: [{"date": ISO, "close": float}, ...]

信号计算（从历史数据推导 E5/E6/valuation_percentile）：
  - valuation_percentile: 当前 mcap 在历史 mcap 序列中的百分位（复用 F1 逻辑）
  - E5 (supply_shrinkage_intensity): fees/mcap 比率归一化（代理指标）
  - E6 (value_capture_delta): fees 增长率 vs mcap 增长率

FAIL-OPEN：任何异常或数据不足 → 返回空 list，调用方回退合成数据。
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from typing import Any, Dict, List, Optional

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

# data_center.db 默认路径
_REPO = os.path.normpath(os.path.join(_THIS_DIR, "..", "..", "..", ".."))
DEFAULT_DB_PATH = os.path.join(_REPO, "18-数据获取中心", "data_center.db")

# 最小数据点数（与 F1 一致，不足一周 → 数据不足）
_MIN_SERIES_LEN = 7


# ===========================================================================
# 辅助：安全 JSON 解析（兼容双重编码，与 F2 一致）
# ===========================================================================

def _safe_json_loads(s: Any, default: Any) -> Any:
    """安全解析 JSON 字符串，兼容双重编码。"""
    if not isinstance(s, str) or not s:
        return default
    try:
        v = json.loads(s)
    except Exception:
        return default
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return default
    return v


# ===========================================================================
# 查询函数 1: DeFiLlama 历史 fees
# ===========================================================================

def query_historical_fees(coin: str, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """从 data_center.db 查询指定币种的 DeFiLlama 历史 fees 时间序列。

    流程：
      1. get_protocol_mapping(coin) → protocol slug（如 UNI → uniswap）
      2. 查 records 表 sub_category=fees_{protocol} 的最新一条
      3. 解析 timeseries JSON，返回 [{date, fees_usd}, ...]

    FAIL-OPEN：protocol 为空 / db 不存在 / JSON 畸形 → 返回空 list。
    """
    try:
        # 延迟导入避免循环依赖
        from force_vector.coin_fundamental_ranker import get_protocol_mapping
        protocol = get_protocol_mapping(coin)
        if not protocol:
            return []

        if not db_path:
            db_path = DEFAULT_DB_PATH
        if not os.path.exists(db_path):
            return []

        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.execute(
                "SELECT timeseries FROM records "
                "WHERE source='defillama' AND category='chain' "
                "AND sub_category=? "
                "ORDER BY timestamp DESC LIMIT 1",
                (f"fees_{protocol}",),
            )
            row = cursor.fetchone()
            if not row or not row[0]:
                return []

            ts = _safe_json_loads(row[0], [])
            if not isinstance(ts, list):
                return []

            result: List[Dict[str, Any]] = []
            for item in ts:
                if isinstance(item, dict) and "fees_usd" in item:
                    result.append({
                        "date": str(item.get("date", "")),
                        "fees_usd": float(item.get("fees_usd", 0) or 0),
                    })
            return result
        finally:
            conn.close()
    except Exception:
        return []


# ===========================================================================
# 查询函数 2: CoinGecko 历史 market_cap
# ===========================================================================

def query_historical_mcap(coin: str, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """从 data_center.db 查询指定币种的 CoinGecko 历史 market_cap 时间序列。

    流程：
      1. get_coingecko_id(coin) → coin_id（如 UNI → uniswap）
      2. 查 records 表 sub_category=chart_{coin_id} 的最新一条
      3. 解析 timeseries JSON，过滤 market_cap=0 的点
      4. 返回 [{date, market_cap, price}, ...]

    FAIL-OPEN：coin_id 为空 / db 不存在 / JSON 畸形 → 返回空 list。
    """
    try:
        from force_vector.coin_fundamental_ranker import get_coingecko_id
        coin_id = get_coingecko_id(coin)
        if not coin_id:
            return []

        if not db_path:
            db_path = DEFAULT_DB_PATH
        if not os.path.exists(db_path):
            return []

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
                return []

            ts = _safe_json_loads(row[0], [])
            if not isinstance(ts, list):
                return []

            result: List[Dict[str, Any]] = []
            for item in ts:
                if not isinstance(item, dict):
                    continue
                mc = item.get("market_cap", 0)
                try:
                    mc = float(mc) if mc is not None else 0.0
                except (TypeError, ValueError):
                    mc = 0.0
                # 过滤 market_cap=0 的点
                if mc <= 0:
                    continue
                result.append({
                    "date": str(item.get("date", "")),
                    "market_cap": mc,
                    "price": float(item.get("price", 0) or 0),
                })
            return result
        finally:
            conn.close()
    except Exception:
        return []


# ===========================================================================
# 查询函数 3: yfinance 历史价格
# ===========================================================================

def query_historical_price(symbol: str, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """从 data_center.db 查询 yfinance 历史价格时间序列。

    流程：
      1. 查 records 表 source=yfinance, sub_category=symbol 的最新一条
      2. 解析 timeseries JSON，返回 [{date, close}, ...]

    FAIL-OPEN：symbol 为空 / db 不存在 / JSON 畸形 → 返回空 list。
    """
    try:
        if not symbol:
            return []

        if not db_path:
            db_path = DEFAULT_DB_PATH
        if not os.path.exists(db_path):
            return []

        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.execute(
                "SELECT timeseries FROM records "
                "WHERE source='yfinance' "
                "AND sub_category=? "
                "ORDER BY timestamp DESC LIMIT 1",
                (symbol,),
            )
            row = cursor.fetchone()
            if not row or not row[0]:
                return []

            ts = _safe_json_loads(row[0], [])
            if not isinstance(ts, list):
                return []

            result: List[Dict[str, Any]] = []
            for item in ts:
                if not isinstance(item, dict):
                    continue
                close = item.get("close", item.get("Close", 0))
                try:
                    close = float(close) if close is not None else 0.0
                except (TypeError, ValueError):
                    close = 0.0
                if close > 0:
                    result.append({
                        "date": str(item.get("date", "")),
                        "close": close,
                    })
            return result
        finally:
            conn.close()
    except Exception:
        return []


# ===========================================================================
# 信号计算（从历史数据推导 E5/E6/valuation_percentile）
# ===========================================================================

def _compute_percentile_at(series: List[float], current: float, min_len: int = _MIN_SERIES_LEN) -> float:
    """计算 current 在 series[0:index+1] 中的百分位 [0, 100]。

    与 F1 的 _compute_percentile 类似，但 min_len 可配置。
    数据不足 → 返回 50.0（中性）。
    """
    valid = [float(x) for x in series if x and float(x) > 0]
    if len(valid) < min_len:
        return 50.0
    if not current or float(current) <= 0:
        return 50.0
    current = float(current)
    rank = sum(1 for x in valid if x <= current)
    pct = rank / len(valid) * 100.0
    return max(0.0, min(100.0, pct))


def _compute_e5_proxy(fees: float, mcap: float) -> float:
    """E5 代理：供给收缩强度（fees/mcap 比率归一化）。

    真实 E5 需要 circulating_supply/max_supply，历史数据中可能缺失。
    用 fees/mcap 比率作为代理：
      - 比率高 → 协议有费用收入 → 可能存在销毁机制 → 正信号
      - 比率低 → 费用收入弱 → 负信号

    归一化到 [-1, 1]，中性点 0.0001（0.01% 日费用率）。
    """
    try:
        fees = float(fees) if fees else 0.0
        mcap = float(mcap) if mcap else 0.0
        if mcap <= 0:
            return 0.0
        import math
        ratio = fees / mcap
        # tanh 归一化，中性点 0.0001
        return max(-1.0, min(1.0, math.tanh((ratio - 0.0001) / 0.0005)))
    except Exception:
        return 0.0


def _compute_e6_proxy(fees_growth: float, mcap_growth: float) -> float:
    """E6 代理：价值捕获质变（fees 增长率 vs mcap 增长率）。

    真实 E6 判断协议是否从"无收入回馈"转变为"有自动销毁/分红"。
    用 fees 增长率 - mcap 增长率作为代理：
      - fees 增长 > mcap 增长 → 费用收入加速 → 正信号
      - fees 增长 < mcap 增长 → 估值膨胀快于盈收 → 负信号

    归一化到 [-1, 1]。
    """
    try:
        diff = float(fees_growth) - float(mcap_growth)
        import math
        return max(-1.0, min(1.0, math.tanh(diff / 0.1)))
    except Exception:
        return 0.0


def _calc_growth_rate(series: List[float]) -> float:
    """计算序列的增长率（首末对比）。"""
    try:
        valid = [float(x) for x in series if x and float(x) > 0]
        if len(valid) < 2:
            return 0.0
        first = valid[0]
        last = valid[-1]
        if first <= 0:
            return 0.0
        return (last - first) / first
    except Exception:
        return 0.0


# ===========================================================================
# 构造真实 PhaseSnapshot 序列
# ===========================================================================

def build_real_snapshots(coin: str, db_path: Optional[str] = None) -> List[Any]:
    """从真实历史数据构造 PhaseSnapshot 序列。

    流程：
      1. 查询 mcap 时间序列（CoinGecko）和 fees 时间序列（DeFiLlama）
      2. 按 date 对齐两个序列
      3. 对每个时间点：
         - valuation_percentile: 当前 mcap 在 mcap 序列中的百分位
         - e5: fees/mcap 比率代理
         - e6: fees 增长率 vs mcap 增长率代理
      4. 返回 PhaseSnapshot 列表

    数据要求：mcap 序列长度 >= 7（不足一周），否则返回空 list。

    FAIL-OPEN：任何异常或数据不足 → 返回空 list，调用方回退合成数据。
    """
    try:
        # 延迟导入 PhaseSnapshot（phase_replay 在 scripts 目录下，不在 force_vector 包内）
        _L4_DIR = os.path.dirname(_THIS_DIR)
        _SCRIPTS_DIR = os.path.join(_L4_DIR, "scripts")
        if _SCRIPTS_DIR not in sys.path:
            sys.path.insert(0, _SCRIPTS_DIR)
        from coin_fundamental_phase_replay import PhaseSnapshot

        # 查询 mcap 和 fees
        mcap_series = query_historical_mcap(coin, db_path)
        fees_series = query_historical_fees(coin, db_path)

        # mcap 数据不足 → 返回空
        if len(mcap_series) < _MIN_SERIES_LEN:
            return []

        # 构建 date → fees 映射（用于对齐）
        fees_map: Dict[str, float] = {}
        if fees_series:
            for item in fees_series:
                d = item.get("date", "")
                if d:
                    fees_map[d] = item.get("fees_usd", 0.0)

        # 构建 date → mcap 映射
        mcap_map: Dict[str, float] = {}
        mcap_values: List[float] = []
        for item in mcap_series:
            d = item.get("date", "")
            mc = item.get("market_cap", 0.0)
            if d and mc > 0:
                mcap_map[d] = mc
                mcap_values.append(mc)

        if len(mcap_values) < _MIN_SERIES_LEN:
            return []

        # 按 date 排序
        sorted_dates = sorted(mcap_map.keys())
        # 对齐 fees 序列
        sorted_fees: List[float] = []
        for d in sorted_dates:
            sorted_fees.append(fees_map.get(d, 0.0))

        # 构造快照序列
        snapshots: List[Any] = []
        for i, d in enumerate(sorted_dates):
            mc = mcap_map[d]
            # valuation_percentile: 当前 mcap 在 mcap[0:i+1] 中的百分位
            sub_series = mcap_values[:i + 1]
            val_pct = _compute_percentile_at(sub_series, mc, min_len=1)

            # e5: fees/mcap 比率代理
            fee = fees_map.get(d, 0.0)
            e5 = _compute_e5_proxy(fee, mc)

            # e6: fees 增长率 vs mcap 增长率（使用到当前点的序列）
            fees_sub = sorted_fees[:i + 1]
            mcap_sub = mcap_values[:i + 1]
            fees_growth = _calc_growth_rate(fees_sub)
            mcap_growth = _calc_growth_rate(mcap_sub)
            e6 = _compute_e6_proxy(fees_growth, mcap_growth)

            snapshots.append(PhaseSnapshot(
                ts=d,
                e5=round(e5, 4),
                e6=round(e6, 4),
                valuation_percentile=round(val_pct, 2),
                events=[],  # 历史回放无事件时间线（由 F2 实时查询补充）
            ))

        return snapshots
    except Exception:
        # FAIL-OPEN：任何异常 → 空 list，调用方回退合成数据
        return []
