"""美股基本面四信号模块 — CoinFundamentalStock。

四个信号：
  1. Earnings Stability：4Q 盈利 Sharpe → 稳定→正
  2. PE Mean Reversion：trailingPE → 高估值→负
  3. Revenue Growth：营收 YoY → 增长→正
  4. Profitability Quality：利润率×ROE → 高质量→正

数据来源：data_center.db
  - yfinance stock_info（sub_category=stock_info_{symbol}）
  - yfinance stock_financials（sub_category=stock_financials_{symbol}）

FAIL-OPEN：任何异常 → 0.0。
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import sys
from statistics import mean, stdev
from typing import Dict

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from force_vector.coin_fundamental_ranker import get_yfinance_symbol

_REPO = os.path.normpath(os.path.join(_THIS_DIR, "..", "..", "..", ".."))
_DATA_CENTER_ROOT = os.path.join(_REPO, "18-数据获取中心")
DEFAULT_DB_PATH = os.path.join(_DATA_CENTER_ROOT, "data_center.db")


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


def _fetch_stock_info(db_path: str, symbol: str) -> dict:
    if not symbol or not os.path.exists(db_path):
        return {}
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT metrics FROM records "
            "WHERE source='yfinance' AND category='finance' "
            f"AND sub_category='stock_info_{symbol}' "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        return _safe_json(row["metrics"]) if row else {}
    except Exception:
        return {}


def _fetch_stock_financials(db_path: str, symbol: str) -> dict:
    if not symbol or not os.path.exists(db_path):
        return {}
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT timeseries FROM records "
            "WHERE source='yfinance' AND category='finance' "
            f"AND sub_category='stock_financials_{symbol}' "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        if not row:
            return {}
        ts = _safe_json(row["timeseries"])
        return {"timeseries": ts if isinstance(ts, list) else []}
    except Exception:
        return {}


# ── 纯计算 ──

def compute_earnings_stability(earnings_ts: list) -> float:
    """4Q 盈利 Sharpe → 稳定→正。"""
    if not earnings_ts or len(earnings_ts) < 3:
        return 0.0
    values = []
    for item in earnings_ts:
        try:
            v = float(item.get("net_income", 0))
            if v > 0:
                values.append(v)
        except (TypeError, ValueError):
            continue
    if len(values) < 3:
        return 0.0
    avg = mean(values)
    sd = stdev(values)
    if avg == 0:
        return 0.0
    if sd == 0:
        return 1.0
    sharpe = avg / sd
    return max(-1.0, min(1.0, math.tanh((sharpe - 1.5) / 1.5)))


def compute_pe_mean_reversion(trailing_pe: float) -> float:
    """PE 比率 → 高估值→负。中位数约 20。"""
    if trailing_pe <= 0:
        return 0.0
    # log scale，中位数 log10(20)≈1.3
    log_pe = math.log10(trailing_pe)
    deviation = (log_pe - 1.3) / 0.3
    return max(-1.0, min(1.0, -math.tanh(deviation)))


def compute_revenue_growth(revenue_growth: float) -> float:
    """营收 YoY → 增长→正。"""
    if revenue_growth == 0:
        return 0.0
    # 20% 增长 → tanh(1.0) ≈ 0.76
    return max(-1.0, min(1.0, math.tanh(revenue_growth / 0.2)))


def compute_profitability_quality(operating_margins: float, return_on_equity: float) -> float:
    """利润率×ROE → 高质量→正。"""
    if operating_margins <= 0:
        return 0.0
    quality = operating_margins * return_on_equity
    # 中性点 0.1（如 10% margin × 100% ROE = 0.1，或 20% × 50% = 0.1）
    return max(-1.0, min(1.0, math.tanh((quality - 0.1) / 0.1)))


def compute_all(coin: str, db_path: str = DEFAULT_DB_PATH) -> Dict[str, float]:
    result = {
        "earnings_stability": 0.0,
        "pe_mean_reversion": 0.0,
        "revenue_growth": 0.0,
        "profitability_quality": 0.0,
    }
    try:
        symbol = get_yfinance_symbol(coin)
        if not symbol:
            return result

        info = _fetch_stock_info(db_path, symbol)
        fin = _fetch_stock_financials(db_path, symbol)

        result["earnings_stability"] = compute_earnings_stability(fin.get("timeseries", []))
        result["pe_mean_reversion"] = compute_pe_mean_reversion(float(info.get("trailingPE", 0)))
        result["revenue_growth"] = compute_revenue_growth(float(info.get("revenueGrowth", 0)))
        result["profitability_quality"] = compute_profitability_quality(
            float(info.get("operatingMargins", 0)),
            float(info.get("returnOnEquity", 0)),
        )
    except Exception:
        pass
    return result
