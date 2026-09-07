"""贵金属基本面四信号模块 — CoinFundamentalMetal。

基于 Artemis Fundamentals 架构的四个近正交信号，针对贵金属特性设计：
  1. Rate Reversion：联邦基金利率 → 低利率→正（黄金不生息，低利率=低持有成本）
  2. Liquidity Expansion：M2 同比扩张 → 高扩张→正（货币贬值→黄金升值）
  3. Inflation Pressure：CPI 同比 → 高通胀→正（抗通胀属性）
  4. Risk Hedging Premium：VIX → 高波动→正（避险溢价）

数据来源：data_center.db SQLite records 表
  - FRED FEDFUNDS（source=fred, category=macro, sub_category=FEDFUNDS）
  - FRED M2NS（source=fred, category=macro, sub_category=M2NS）
  - FRED CPIAUCSL（source=fred, category=macro, sub_category=CPIAUCSL）
  - yfinance ^VIX（source=yfinance, category=finance, sub_category=^VIX）

FAIL-OPEN：任何异常 → 对应信号返回 0.0，不阻塞整体。
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import sys
from typing import Dict, Optional

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from force_vector.coin_fundamental_ranker import classify_asset_class

# data_center.db 默认路径：dreambuddy-v2/18-数据获取中心/data_center.db
# force_vector → memory_l4 → scripts → 11-易经推理系统 → dreambuddy-v2（4级）
_REPO = os.path.normpath(os.path.join(_THIS_DIR, "..", "..", "..", ".."))
_DATA_CENTER_ROOT = os.path.join(_REPO, "18-数据获取中心")
DEFAULT_DB_PATH = os.path.join(_DATA_CENTER_ROOT, "data_center.db")


# ===========================================================================
# 数据读取（SQLite）
# ===========================================================================

def _safe_json(text) -> any:
    if isinstance(text, dict):
        return text
    if not isinstance(text, str):
        return {}
    try:
        v = json.loads(text)
        return v if isinstance(v, (dict, list)) else {}
    except Exception:
        return {}


def _fetch_fred_series(db_path: str, series_id: str) -> dict:
    """从 SQLite 读取 FRED series 的历史数据。

    跨多次采集记录拼接历史序列（同 date 去重取最新 id）。

    Returns:
        {"value": 最新值, "timeseries": [{"date": str, "value": float}, ...]}
    """
    if not series_id or not os.path.exists(db_path):
        return {}
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT metrics FROM records "
            "WHERE source='fred' AND category='macro' "
            f"AND sub_category='{series_id}' "
            "ORDER BY id ASC"
        ).fetchall()
        conn.close()
        if not rows:
            return {}
        # 拼接历史序列，同 date 去重（后写入的覆盖先写入的）
        date_value: dict[str, float] = {}
        ordered_dates: list[str] = []
        for row in rows:
            m = _safe_json(row["metrics"])
            val = m.get("value")
            date = m.get("date", "")
            if val is None or not date:
                continue
            try:
                fv = float(val)
            except (TypeError, ValueError):
                continue
            if date not in date_value:
                ordered_dates.append(date)
            date_value[date] = fv
        ts = [{"date": d, "value": date_value[d]} for d in ordered_dates]
        latest_val = ts[-1]["value"] if ts else 0.0
        return {"value": latest_val, "timeseries": ts}
    except Exception:
        return {}


def _fetch_vix(db_path: str) -> float:
    """从 SQLite 读取 yfinance ^VIX 最新值。"""
    if not os.path.exists(db_path):
        return 0.0
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT metrics FROM records "
            "WHERE source='yfinance' AND category='finance' "
            "AND sub_category='^VIX' "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        if not row:
            return 0.0
        m = _safe_json(row["metrics"])
        return float(m.get("price", 0))
    except Exception:
        return 0.0


# ===========================================================================
# 纯计算函数
# ===========================================================================

def compute_rate_reversion(fed_funds_rate: float) -> float:
    """联邦基金利率 → 低利率→正信号。

    黄金为不生息资产，低利率环境=低持有成本→资金流向黄金。
    中性点 2.0%，低于→正，高于→负。

    Returns:
        [-1.0, +1.0]，低利率→正
    """
    if fed_funds_rate <= 0:
        return 0.0
    # 中性点 2.0%，偏离 2.0% 为一个标准差
    deviation = (2.0 - fed_funds_rate) / 2.0
    return max(-1.0, min(1.0, math.tanh(deviation)))


def compute_liquidity_expansion(m2_yoy: float) -> float:
    """M2 同比扩张率(%) → 高扩张→正信号。

    货币供应量扩张→法定货币贬值→黄金升值。
    中性点 0%，高于→正，低于→负。

    Returns:
        [-1.0, +1.0]，高扩张→正
    """
    if m2_yoy == 0:
        return 0.0
    # 7.5% 同比增长 → tanh(1.0) ≈ 0.76
    return max(-1.0, min(1.0, math.tanh(m2_yoy / 7.5)))


def compute_inflation_pressure(cpi_yoy: float) -> float:
    """CPI 同比(%) → 高通胀→正信号。

    黄金具有抗通胀属性，高通胀→黄金需求上升。
    中性点 2.0%（美联储目标），高于→正，低于→负。

    Returns:
        [-1.0, +1.0]，高通胀→正
    """
    # 中性点 2.0%（美联储目标），偏离 2.0% 为一个标准差
    deviation = (cpi_yoy - 2.0) / 2.0
    return max(-1.0, min(1.0, math.tanh(deviation)))


def compute_risk_hedging_premium(vix: float) -> float:
    """VIX → 高波动→正信号（避险溢价）。

    黄金具有避险属性，高恐慌→避险需求上升→正信号。
    中性点 20（长期均值），高于→正，低于→负。

    Returns:
        [-1.0, +1.0]，高波动→正
    """
    if vix <= 0:
        return 0.0
    # 中性点 20，偏离 10 为一个标准差
    deviation = (vix - 20.0) / 10.0
    return max(-1.0, min(1.0, math.tanh(deviation)))


# ===========================================================================
# 辅助计算
# ===========================================================================

def _compute_yoy(timeseries: list) -> Optional[float]:
    """从 timeseries 计算同比变化率(%)。

    取最新值与最早可用值计算变化率。
    若 timeseries 不足 2 条 → 返回 None（区分"数据缺失"与"0% 同比"）。
    """
    if not timeseries or len(timeseries) < 2:
        return None
    try:
        latest = float(timeseries[-1].get("value", 0))
        earliest = float(timeseries[0].get("value", 0))
    except (TypeError, ValueError):
        return None
    if earliest <= 0:
        return None
    return (latest - earliest) / earliest * 100.0


# ===========================================================================
# 组合函数
# ===========================================================================

def compute_all(coin: str, db_path: str = DEFAULT_DB_PATH) -> Dict[str, float]:
    """计算指定贵金属的四个基本面信号。

    FAIL-OPEN：任何异常 → 对应信号返回 0.0。
    """
    result = {
        "rate_reversion": 0.0,
        "liquidity_expansion": 0.0,
        "inflation_pressure": 0.0,
        "risk_hedging_premium": 0.0,
    }
    try:
        if classify_asset_class(coin) != "precious_metal":
            return result

        # 读取数据
        fed_data = _fetch_fred_series(db_path, "FEDFUNDS")
        m2_data = _fetch_fred_series(db_path, "M2NS")
        cpi_data = _fetch_fred_series(db_path, "CPIAUCSL")
        vix_val = _fetch_vix(db_path)

        # 1. Rate Reversion
        fed_rate = float(fed_data.get("value", 0))
        result["rate_reversion"] = compute_rate_reversion(fed_rate)

        # 2. Liquidity Expansion（M2 同比）— None 表示数据不足，信号为 0
        m2_yoy = _compute_yoy(m2_data.get("timeseries", []))
        result["liquidity_expansion"] = compute_liquidity_expansion(m2_yoy) if m2_yoy is not None else 0.0

        # 3. Inflation Pressure（CPI 同比）— None 表示数据不足，信号为 0
        cpi_yoy = _compute_yoy(cpi_data.get("timeseries", []))
        result["inflation_pressure"] = compute_inflation_pressure(cpi_yoy) if cpi_yoy is not None else 0.0

        # 4. Risk Hedging Premium
        result["risk_hedging_premium"] = compute_risk_hedging_premium(vix_val)

    except Exception:
        pass  # FAIL-OPEN：全部保持 0.0

    return result
