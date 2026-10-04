"""三屏策略信号生成（纯函数）。

从单体提取 three_screen 信号决策逻辑：
- 日线方向判断（趋势方向）
- 5m 确认（BOS 突破 / EMA 拐点 / RSI TEMA）
- 最终决策（direction, confidence, strategy, reject_reason）

所有函数为纯函数：输入 DataFrame + config，输出 dict。
不依赖全局状态，可独立测试。
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from classic_pipeline.core.utils import _clip


# ---------------------------------------------------------------------------
# 内部工具函数
# ---------------------------------------------------------------------------

def _ema(values: List[float], period: int) -> List[float]:
    """指数移动平均（纯 Python 实现，避免外部依赖）。"""
    if not values or period <= 0:
        return []
    alpha = 2.0 / (period + 1.0)
    out: List[float] = []
    prev = float(values[0])
    out.append(prev)
    for v in values[1:]:
        prev = alpha * float(v) + (1.0 - alpha) * prev
        out.append(prev)
    return out


# ---------------------------------------------------------------------------
# 5m 信号确认门
# ---------------------------------------------------------------------------

def confirm_gate(
    df: pd.DataFrame,
    carry_side: str,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """5 分钟信号确认门。

    从单体 _three_screen_5m_confirm_gate 提取的纯函数版本。

    Args:
        df: OHLCV DataFrame（5m 周期）
        carry_side: 持仓方向 "long" / "short"
        config: 配置字典（替代全局 CONFIG）

    Returns:
        {ok, tag, confirm_tags, details}
    """
    cfg = config or {}
    if df is None or len(df) < 30:
        return {"ok": True, "tag": "insufficient", "confirm_tags": [], "details": {}}

    side = str(carry_side or "").strip().lower()
    if side not in ("long", "short"):
        return {"ok": True, "tag": "unknown_side", "confirm_tags": [], "details": {}}

    enable_raw = cfg.get("confirm_set", ["bos", "ema_turn", "rsi_tema"])
    if isinstance(enable_raw, str):
        enable = [s.strip().lower() for s in enable_raw.split(",") if str(s).strip()]
    elif isinstance(enable_raw, list):
        enable = [str(s).strip().lower() for s in enable_raw if str(s).strip()]
    else:
        enable = ["bos", "ema_turn", "rsi_tema"]
    enable_set = set(enable)

    closes = pd.to_numeric(df["close"], errors="coerce").tolist()
    highs = pd.to_numeric(df["high"], errors="coerce").tolist()
    lows = pd.to_numeric(df["low"], errors="coerce").tolist()
    vols = pd.to_numeric(df["volume"], errors="coerce").tolist()

    if not closes or not highs or not lows:
        return {"ok": True, "tag": "insufficient", "confirm_tags": [], "details": {}}

    confirm_tags: List[str] = []
    details: Dict[str, Any] = {}

    # --- BOS (Break of Structure) ---
    if "bos" in enable_set:
        n = int(cfg.get("bos_lookback_bars", 8))
        n = int(max(2, min(50, n)))
        bos = False
        prev_high = None
        prev_low = None
        last_close = None
        if len(highs) >= (n + 2) and len(lows) >= (n + 2):
            try:
                prev_high = max(highs[-(n + 2): -1])
                prev_low = min(lows[-(n + 2): -1])
                last_close = float(closes[-1])
                if side == "long":
                    bos = float(last_close) > float(prev_high)
                else:
                    bos = float(last_close) < float(prev_low)
            except Exception:
                bos = False
        if bos:
            confirm_tags.append("confirm_bos")
        details["confirm_bos"] = bool(bos)
        details["confirm_bos_prev_high"] = prev_high
        details["confirm_bos_prev_low"] = prev_low
        details["confirm_bos_close"] = last_close

    # --- EMA Turn ---
    if "ema_turn" in enable_set:
        fast = int(cfg.get("ema_turn_fast", 9))
        slow = int(cfg.get("ema_turn_slow", 21))
        fast = int(max(3, min(50, fast)))
        slow = int(max(fast + 1, min(200, slow)))

        turn = False
        vol_ok = True
        atr_ok = True

        if len(closes) >= (slow + 3):
            efast = _ema(closes, fast)
            eslow = _ema(closes, slow)
            try:
                s_now = float(efast[-1]) - float(efast[-2])
                s_prev = float(efast[-2]) - float(efast[-3])
                if side == "long":
                    turn = (s_now > 0.0) and (s_prev <= 0.0) and (float(efast[-1]) > float(eslow[-1]))
                else:
                    turn = (s_now < 0.0) and (s_prev >= 0.0) and (float(efast[-1]) < float(eslow[-1]))
            except Exception:
                turn = False

        # 成交量过滤
        vol_mean = 0.0
        try:
            recent_vols = vols[-20:] if len(vols) >= 20 else vols
            vol_mean = sum(recent_vols) / float(len(recent_vols)) if recent_vols else 0.0
        except Exception:
            vol_mean = 0.0
        vol_mult = float(cfg.get("confirm_vol_mult", 0.60))
        vol_mult = float(max(0.0, min(5.0, vol_mult)))
        if vol_mean > 0.0:
            vol_ok = float(vols[-1] or 0.0) >= vol_mean * vol_mult

        # ATR 过滤
        atr_pct = None
        if len(closes) >= 15:
            trs: List[float] = []
            for i in range(1, min(len(closes), 15)):
                h = float(highs[-i])
                l = float(lows[-i])
                pc = float(closes[-i - 1])
                tr = max(h - l, abs(h - pc), abs(l - pc))
                trs.append(float(tr))
            try:
                atr = sum(trs) / float(len(trs)) if trs else 0.0
                atr_pct = float(atr) / float(closes[-1]) if float(closes[-1]) > 0.0 else None
            except Exception:
                atr_pct = None
        atr_max = float(cfg.get("confirm_atr_pct_max", 0.020))
        atr_max = float(max(0.0, min(0.20, atr_max)))
        if atr_pct is not None and math.isfinite(float(atr_pct)):
            atr_ok = float(atr_pct) <= atr_max

        details["confirm_ema_turn"] = bool(turn)
        details["confirm_ema_turn_vol_ok"] = bool(vol_ok)
        details["confirm_ema_turn_atr_ok"] = bool(atr_ok)
        if atr_pct is not None and math.isfinite(float(atr_pct)):
            details["confirm_ema_turn_atr_pct"] = float(atr_pct)
        if turn and vol_ok and atr_ok:
            confirm_tags.append("confirm_ema_turn")

    if confirm_tags:
        return {
            "ok": True,
            "tag": str(confirm_tags[0]),
            "confirm_tags": confirm_tags,
            "details": details,
        }
    return {"ok": False, "tag": "no_confirm", "confirm_tags": [], "details": details}


# ---------------------------------------------------------------------------
# 日线方向判断
# ---------------------------------------------------------------------------

def daily_direction(df_daily: pd.DataFrame, config: Optional[Dict[str, Any]] = None) -> str:
    """判断日线趋势方向。

    基于 EMA20 斜率和价格位置。
    """
    if df_daily is None or len(df_daily) < 20:
        return "neutral"
    try:
        closes = pd.to_numeric(df_daily["close"], errors="coerce").tolist()
        ema20 = _ema(closes, 20)
        if len(ema20) < 3:
            return "neutral"
        slope = float(ema20[-1]) - float(ema20[-3])
        last_close = float(closes[-1])
        last_ema = float(ema20[-1])
        if slope > 0 and last_close > last_ema:
            return "long"
        elif slope < 0 and last_close < last_ema:
            return "short"
        return "neutral"
    except Exception:
        return "neutral"


# ---------------------------------------------------------------------------
# 最终信号计算
# ---------------------------------------------------------------------------

def compute(
    df_5m: Optional[pd.DataFrame],
    df_daily: Optional[pd.DataFrame],
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """三屏策略最终信号计算。

    Args:
        df_5m: 5m OHLCV DataFrame
        df_daily: 日线 OHLCV DataFrame
        config: 配置字典

    Returns:
        {direction, confidence, strategy, reject_reason, details}
    """
    cfg = config or {}
    # FAIL-OPEN: 数据异常时返回中性
    if df_5m is None or df_daily is None or len(df_5m) < 30 or len(df_daily) < 20:
        return {
            "direction": "neutral",
            "confidence": 0.0,
            "strategy": "three_screen",
            "reject_reason": "insufficient_data",
            "details": {},
        }

    try:
        # 1. 日线方向
        daily_dir = daily_direction(df_daily, cfg)

        # 2. 是否要求日线对齐
        require_align = bool(cfg.get("require_daily_alignment", True))

        # 3. 5m 确认
        gate = confirm_gate(df_5m, carry_side=daily_dir, config=cfg)

        # 4. 最终决策
        direction = "neutral"
        confidence = 0.0
        reject_reason = ""

        if require_align and daily_dir not in ("long", "short"):
            reject_reason = "no_daily_trend"
        elif not gate["ok"]:
            reject_reason = gate.get("tag", "no_confirm")
        elif require_align and daily_dir not in ("long", "short"):
            reject_reason = "daily_not_aligned"
        else:
            direction = daily_dir
            # 置信度基于确认类型
            tag = str(gate.get("tag") or "").lower()
            if "deep" in tag or "confirm_bos" in tag:
                confidence = 0.80
            elif "mild" in tag or "confirm_ema_turn" in tag:
                confidence = 0.68
            else:
                confidence = 0.62
            confidence = _clip(confidence, 0.0, 1.0)

        return {
            "direction": direction,
            "confidence": confidence,
            "strategy": "three_screen",
            "reject_reason": reject_reason,
            "details": gate.get("details", {}),
        }
    except Exception:
        # FAIL-OPEN
        return {
            "direction": "neutral",
            "confidence": 0.0,
            "strategy": "three_screen",
            "reject_reason": "error",
            "details": {},
        }
