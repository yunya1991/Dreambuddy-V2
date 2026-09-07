"""
ftc_backtest — FTC 回测引擎

复用 v3_backtest 的合成 K 线生成器，对每条 FTC 跑回测:
  H = 胜率 (方向正确的交易数 / 总交易数)
  S = 结构稳健度 (方向一致性: 1 - |多空比例 - 0.5| * 2)
  N = 交易样本数
  ESS = 0.4*H + 0.4*S + 0.2*sqrt(N/500)  （复用 strategy_gene.calculate_ess）

FAIL-OPEN: 任何异常返回 0 分，不抛异常。
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

from .ftc_schema import FTC
from .ftc_executor import evaluate_ftc

try:
    from dreambuddy_evolution.core.strategy_gene import calculate_ess
    _ESS_AVAILABLE = True
except ImportError:
    _ESS_AVAILABLE = False
    calculate_ess = None

try:
    from dreambuddy_evolution.tests.v3_backtest import _generate_synthetic_klines
    _SYNTH_AVAILABLE = True
except ImportError:
    _SYNTH_AVAILABLE = False

logger = logging.getLogger(__name__)


# 回测参数
BACKTEST_BARS = 200
DIRECTION_THRESHOLD = 0.003  # 0.3% 算明确方向


def backtest_ftc(ftc: FTC, symbol: str = "BTC", n_bars: int = BACKTEST_BARS) -> dict[str, Any]:
    """
    对单条 FTC 跑回测，返回 ESS 和明细。

    Returns:
        {
            "ftc_id": str,
            "H": float,           # 胜率
            "S": float,           # 结构稳健度
            "N": int,             # 交易样本数
            "ess": float,         # ESS = 0.4H + 0.4S + 0.2*sqrt(N/500)
            "long_signals": int,
            "short_signals": int,
            "wait_signals": int,
            "correct": int,
        }
    """
    if not _SYNTH_AVAILABLE:
        logger.warning("synthetic kline generator not available")
        return _empty_result(ftc.ftc_id)

    try:
        klines = _generate_synthetic_klines(symbol, n_bars + 1)
    except Exception as e:
        logger.warning(f"[FO] kline generation failed: {e}")
        return _empty_result(ftc.ftc_id)

    correct = 0
    total = 0
    long_sigs = 0
    short_sigs = 0
    wait_sigs = 0
    window = 30

    for i in range(window, len(klines) - 1):
        kline_data = _build_kline_data(klines, i, window, symbol)
        result = evaluate_ftc(ftc, kline_data)
        signal = result["signal"]

        if signal == "WAIT":
            wait_sigs += 1
            continue

        # 获取实际方向
        actual = _get_actual_direction(klines, i)
        if actual == "WAIT":
            continue

        total += 1
        # 计数: rotation/follow → long桶; contrarian → short桶
        if signal in ("long", "follow", "rotation"):
            long_sigs += 1
        elif signal in ("short", "contrarian"):
            short_sigs += 1

        # 判断正确
        if signal in ("long", "follow", "rotation") and actual == "long":
            correct += 1
        elif signal in ("short", "contrarian") and actual == "short":
            correct += 1

    H = correct / max(1, total)
    # S = 结构稳健度 (Wyckoff 供需结构): 方向越一致越高
    # 全多/全空 → S=1.0 (结构明确), 多空各半 → S=0.5 (结构模糊)
    if total > 0:
        long_ratio = long_sigs / total
        S = max(long_ratio, 1.0 - long_ratio)
    else:
        S = 0.0
    N = total

    # 复用 strategy_gene.calculate_ess（硬约束：不重写）
    if _ESS_AVAILABLE and calculate_ess is not None:
        ess = calculate_ess({"H": H, "S": S, "N": N})
    else:
        # 降级: 手动计算（公式与 strategy_gene 一致）
        import math
        n_term = min(1.0, math.sqrt(max(N, 0) / 500.0))
        ess = 0.4 * H + 0.4 * S + 0.2 * n_term
        ess = max(0.0, min(1.0, ess))

    return {
        "ftc_id": ftc.ftc_id,
        "H": round(H, 4),
        "S": round(S, 4),
        "N": N,
        "ess": round(ess, 4),
        "long_signals": long_sigs,
        "short_signals": short_sigs,
        "wait_signals": wait_sigs,
        "correct": correct,
    }


def backtest_ftc_list(ftcs: list[FTC], symbol: str = "BTC") -> list[dict[str, Any]]:
    """批量回测多条 FTC，按 ESS 降序返回"""
    results = []
    for ftc in ftcs:
        try:
            r = backtest_ftc(ftc, symbol)
            results.append(r)
        except Exception as e:
            logger.warning(f"[FO] backtest {ftc.ftc_id} failed: {e}")
            results.append(_empty_result(ftc.ftc_id))
    results.sort(key=lambda x: x["ess"], reverse=True)
    return results


def _build_kline_data(klines: list[dict], idx: int, window: int, symbol: str = "BTC") -> dict[str, Any]:
    """从合成 K 线构建 kline_data（供 FTC condition 检查用）"""
    start = max(0, idx - window + 1)
    w = klines[start:idx + 1]
    closes = [k["close"] for k in w]
    vols = [k["volume"] for k in w]

    cur = klines[idx]
    vol_5 = sum(vols[-5:]) / min(5, len(vols))
    vol_20 = sum(vols[-20:]) / min(20, len(vols))
    base_vol_ratio = vol_5 / max(vol_20, 1e-9)

    # 周期性放量: 每 25 根 K 线放量一次 (模拟事件驱动)
    is_surge = (idx % 25 == 0)
    vol_ratio = base_vol_ratio * (1.8 if is_surge else 1.0)

    # 合成数据带趋势，根据 trend_phase 生成额外特征
    trend_phase = cur.get("trend_phase", 0)
    # 周期性加入震荡段 (每 40 根中后 10 根为震荡)
    is_ranging = (idx % 40) in range(30, 40)
    regime = "ranging" if is_ranging else ("trend_up" if trend_phase == 0 else "trend_down")

    # 动量/趋势特征
    ma20 = sum(closes[-20:]) / min(20, len(closes))
    adx = 15.0 if is_ranging else (30.0 if trend_phase == 0 else 25.0)
    capital_rotation = 0.0 if is_ranging else (0.3 if trend_phase == 0 else -0.3)
    capital_flow = 0.0 if is_ranging else (0.2 if trend_phase == 0 else -0.2)
    oi_change_pct = 0.0 if is_ranging else (0.06 if trend_phase == 0 else -0.06)
    funding_rate = 0.0 if is_ranging else (0.0005 if trend_phase == 0 else -0.0005)
    sentiment = 0.0 if is_ranging else (0.5 if trend_phase == 0 else -0.5)

    # z_score: 震荡时偶尔极端
    if is_ranging and idx % 8 == 0:
        z_score = 2.5 if trend_phase == 0 else -2.5
    else:
        z_score = 0.0

    return {
        "symbol": f"{symbol}-USDT-SWAP",
        "close": closes,
        "vol_5": vol_5,
        "vol_20": vol_20,
        "vol_ratio": round(min(vol_ratio, 3.0), 4),
        "regime": regime,
        "ma20": ma20,
        "adx": adx,
        "capital_rotation": capital_rotation,
        "capital_flow": capital_flow,
        "oi_change_pct": oi_change_pct,
        "funding_rate": funding_rate,
        "sentiment": sentiment,
        "z_score": z_score,
    }


def _get_actual_direction(klines: list[dict], idx: int) -> str:
    """下一根 K 线的实际方向"""
    if idx + 1 >= len(klines):
        return "WAIT"
    ret = (klines[idx + 1]["close"] - klines[idx]["close"]) / klines[idx]["close"]
    if ret > DIRECTION_THRESHOLD:
        return "long"
    elif ret < -DIRECTION_THRESHOLD:
        return "short"
    return "WAIT"


def _empty_result(ftc_id: str) -> dict[str, Any]:
    return {
        "ftc_id": ftc_id,
        "H": 0.0, "S": 0.0, "N": 0, "ess": 0.0,
        "long_signals": 0, "short_signals": 0, "wait_signals": 0, "correct": 0,
    }
