"""事件 reaction 计算 + 行情反查 — SPEC-D1 §2.4 / §3.2。

compute_reaction：事件研究简化版——以 trigger 日收盘为基准，T+24h/T+7d 窗口收益。
  - 深度文章回填的事件统一"日"粒度（ts_precision=day），只用 T+24h/T+7d
  - 数据不足的窗口缺席，不硬填

detect_kline_anomalies：3σ 异常波动检测（行情反查路径，复用 48 E1
  anomaly_probe 思路）。产出候选事件（attribution=weak，需新闻归因确认）。

全部 FAIL-OPEN。
"""

from __future__ import annotations

import logging
import math
from typing import Any

logger = logging.getLogger("data_center.processing.event_reaction")

DAY = 86400
_MIN_SERIES = 3


def _clean_series(prices: Any) -> list[tuple[float, float]]:
    """[(ts, close), ...] 规范化：滤非法点、按 ts 排序。"""
    out = []
    if not isinstance(prices, (list, tuple)):
        return out
    for p in prices:
        try:
            ts, c = float(p[0]), float(p[1])
            if math.isfinite(ts) and math.isfinite(c) and c > 0:
                out.append((ts, c))
        except (TypeError, ValueError, IndexError):
            continue
    out.sort(key=lambda x: x[0])
    return out


def _close_at_or_before(series: list[tuple[float, float]], ts: float):
    """≤ ts 的最近收盘价（事件日对齐，24/7 市场容差）。"""
    val = None
    for t, c in series:
        if t <= ts:
            val = c
        else:
            break
    return val


def _close_at_or_after(series: list[tuple[float, float]], ts: float):
    for t, c in series:
        if t >= ts:
            return c
    return None


def compute_reaction(prices: Any, trigger_ts: Any) -> dict:
    """{T+24h: r, T+7d: r}；基准为 ≤trigger_ts 最近收盘。FAIL-OPEN → {}。"""
    try:
        series = _clean_series(prices)
        ts = float(trigger_ts)
        if len(series) < 2:
            return {}
        base = _close_at_or_before(series, ts)
        if base is None:
            return {}
        out = {}
        for label, delta in (("T+24h", DAY), ("T+7d", 7 * DAY)):
            fwd = _close_at_or_after(series, ts + delta)
            if fwd is not None:
                out[label] = fwd / base - 1.0
        return out
    except Exception as e:  # noqa: BLE003
        logger.warning("[FAIL-OPEN] compute_reaction 异常 %s: %s", type(e).__name__, str(e)[:200])
        return {}


def detect_kline_anomalies(prices: Any, sigma: float = 3.0) -> list[dict]:
    """日收益 3σ 突刺检测。返回 [{ts, direction, ret, attribution}]。"""
    try:
        series = _clean_series(prices)
        if len(series) < _MIN_SERIES:
            return []
        rets = []
        for i in range(1, len(series)):
            r = series[i][1] / series[i - 1][1] - 1.0
            rets.append((series[i][0], r))
        # 稳健 z：median/MAD（均值/标准差会被突刺自身抬高，产生掩蔽）
        rs = sorted(r for _, r in rets)
        n = len(rs)
        median = rs[n // 2] if n % 2 else (rs[n // 2 - 1] + rs[n // 2]) / 2
        devs = sorted(abs(r - median) for r in rs)
        mad = devs[n // 2] if n % 2 else (devs[n // 2 - 1] + devs[n // 2]) / 2
        if mad <= 0:
            return []  # 零离散护栏（除零）
        out = []
        for ts, r in rets:
            z = 0.6745 * (r - median) / mad
            if abs(z) >= sigma:
                out.append(
                    {
                        "ts": int(ts),
                        "direction": "up" if r > 0 else "down",
                        "ret": r,
                        "z_score": round(z, 3),
                        "attribution": "weak",
                    }
                )
        return out
    except Exception as e:  # noqa: BLE003
        logger.warning(
            "[FAIL-OPEN] detect_kline_anomalies 异常 %s: %s", type(e).__name__, str(e)[:200]
        )
        return []
