# -*- coding: utf-8 -*-
"""BDSM 每日快照生成器 — Phase 0 核心脚本。

职责（对应 Spec §2-3）：
  1. neutral_snapshot(reason) → FAIL-OPEN 中性兜底，字节等价 BDSM 不存在
  2. write_snapshot(out_dir, dry_run_read_coin_data_from_db=True/False)
     → 遍历 BDSM_COINS，依次调用 compute_all + classify_phase → 计算
        direction_constraint / cap_multiplier / exit_action → 写 JSON

每日调度（Spec §7）：由 cron 或 polling_trader 在 23:50 UTC+8 运行 1 次。
路径（默认）：11-易经推理系统/.workbuddy/bdsm/bdsm_snapshot_{YYYYMMDD}.json

开关：
  enable_buffett_discount（默认 False，Phase 3 开启）— score × 0.7 折扣
  enable_e7_negative_bias（默认 False，Phase 3 开启）— E7 负值 1.3× 放大

TDD 驱动：见 11-易经推理系统/tests/test_bdsm_phase0_snapshot.py
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional

# 保证 force_vector 包可被正确 import（作为脚本直接运行时 sys.path 不含父目录）
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_MEM_L4_DIR = os.path.normpath(os.path.join(_THIS_DIR, ".."))
_REPO_11_ABS = os.path.normpath(os.path.join(_MEM_L4_DIR, "..", ".."))
for _p in (_MEM_L4_DIR, _REPO_11_ABS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ---------------------------------------------------------------------- BDSM_COINS
# 与 polling_trader.py L655-674 完全等价的双路径 __import__ + 8 币 静态兜底。
# 兄弟子包模式 `-m scripts.memory_l4.polling_trader` 下顶层 `force_vector`
# 包 不存在（只有 scripts.memory_l4.force_vector），因此两个路径都试。
# 同时作为独立脚本 运行（顶层包 force_vector 直接可用），第二个路径成功。
# 最终兜底 为 8 币 常量，保证 FAIL-OPEN 字节等价 neutral。
_BDSM_FALLBACK_COINS = frozenset({"UNI", "PUMP", "HYPE", "AAVE", "SOL", "CRCL", "ETH", "BTC", "ZEC", "ARB"})

_BDSM_COINS_IMP = None  # type: "frozenset[str] | None"
for _bdsm_mod_path in (
    "scripts.memory_l4.force_vector.coin_fundamental_ranker",
    "force_vector.coin_fundamental_ranker",
):
    try:
        _bdsm_mod = __import__(_bdsm_mod_path, fromlist=["BDSM_COINS"])
        _BDSM_COINS_IMP = getattr(_bdsm_mod, "BDSM_COINS", None)
        if _BDSM_COINS_IMP:
            break
    except Exception:  # pragma: no cover - 失败 跳过
        continue
BDSM_COINS = _BDSM_COINS_IMP or _BDSM_FALLBACK_COINS  # noqa: N816
# ---------------------------------------------------------------------------- END

# 相对路径：force_vector/ → memory_l4/ → scripts → 11-易经推理系统/.workbuddy/bdsm
_REPO_11 = os.path.normpath(os.path.join(_THIS_DIR, "..", "..", ".."))
_DEFAULT_SNAPSHOT_DIR = os.path.join(_REPO_11, ".workbuddy", "bdsm")
# PollingTrader lazy import 的兼容别名（历史 UT / audit 脚本 也依赖 DEFAULT_BDSM_DIR 名字）
DEFAULT_BDSM_DIR = _DEFAULT_SNAPSHOT_DIR  # noqa: N816

_SCHEMA_VERSION = "1.0"
_RANK_ORDER = {"S": 4, "A": 3, "B": 2, "C": 1}
_HISTORY_DAYS_FOR_EXIT_TRIGGERS = 4  # B1~B5 需要读取最近 4 天快照对比
MA_LONG_DEFAULT = 200  # P0-A1: 写回 Phase 0 使用的 MA 周期
_KLINE_FETCH_LIMIT = 290  # MA200 + 90 日窗口余量
_SNAPSHOT_PROXY = os.environ.get("HTTP_PROXY", "http://127.0.0.1:7890")

# Phase 0 OKX K线结果缓存（避免 7 币 重复请求）
_KLINE_CACHE: Dict[str, list] = {}

# 开关 — 默认全关（Phase 0/1 Shadow 模式）
ENABLE_BUFFETT_DISCOUNT = os.environ.get("ENABLE_BUFFETT_DISCOUNT", "").lower() in ("1", "true")
ENABLE_E7_NEGATIVE_BIAS = os.environ.get("ENABLE_E7_NEGATIVE_BIAS", "").lower() in ("1", "true")
_BUFFETT_DISCOUNT_FACTOR = 0.7
_E7_NEGATIVE_BIAS_MULTIPLIER = 1.3

logger = logging.getLogger("bdsm_snapshot")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


def _fetch_snapshot_klines(coin: str) -> list:
    """P0-A1: 从 OKX 拉取 1D K 线用于 Phase 0 计算。FAIL-OPEN → []。

    带进程内缓存（7 币单次 write_snapshot 内复用，不重复 HTTP 请求）。
    分页拉取：OKX history-candles 单次 limit 上限 100，需用 before 参数翻页
    直到凑齐 ≥200 根（满足 MA200 计算）。
    """
    cache_key = (coin or "").upper()
    if cache_key in _KLINE_CACHE:
        return _KLINE_CACHE[cache_key]
    try:
        import requests  # noqa: WPS433
    except Exception as _e:
        logger.warning("BDSM requests 模块缺失 coin=%s: %s", coin, _e)
        return []
    inst_id = f"{cache_key}-USDT-SWAP"
    url = "https://www.okx.com/api/v5/market/history-candles"
    proxies = {"http": _SNAPSHOT_PROXY, "https": _SNAPSHOT_PROXY}
    target = max(_KLINE_FETCH_LIMIT, 200)  # 确保 ≥ MA200 所需
    all_klines: list = []
    before_ts: Optional[int] = None
    try:
        while len(all_klines) < target:
            params = {"instId": inst_id, "bar": "1D", "limit": "100"}
            if before_ts is not None:
                params["before"] = str(before_ts)
            r = requests.get(url, params=params, proxies=proxies, timeout=12)
            data = r.json()
            if data.get("code") != "0":
                break
            raw = data.get("data", []) or []
            if not raw:
                break
            # OKX 返回按时间降序（最新在前），反转为升序后追加
            for k in reversed(raw):
                all_klines.append({
                    "ts": int(k[0]),
                    "o": float(k[1]),
                    "h": float(k[2]),
                    "l": float(k[3]),
                    "c": float(k[4]),
                    "v": float(k[5]),
                })
            before_ts = int(raw[-1][0])  # 用本批最早一根 ts 作为下页 before
        all_klines.sort(key=lambda x: x["ts"])  # 最终按时间升序
        _KLINE_CACHE[cache_key] = all_klines
        return all_klines
    except Exception as _exc:
        logger.warning("BDSM K线拉取失败 coin=%s: %s", coin, _exc)
        return []


# =========================================================================
# §3.3 FAIL-OPEN 中性快照（R3 落地）
# =========================================================================

def _neutral_coin_entry(reason: str = "insufficient_data") -> Dict[str, Any]:
    """单币中性兜底：字节等价「BDSM 不存在」。"""
    ta = {
        "rsi_14": 50.0,
        "ma200_deviation": 0.0,
        "ma200_slope": 0.0,
        "volume_ratio": 1.0,
        "atr_pct": 0.0,
        "ts_score": 0.0,
    }
    trend_stop = {
        "ma200_price": 0.0,
        "ma128_price": 0.0,
        "below_ma200_days": 0,
        "ma200_slope_negative": False,
        "death_cross": False,
        "action": "none",
    }
    value_exit = {
        "pf_percentile": 50.0,
        "pf_overvalued": False,
        "pf_bubble": False,
        "e8_cross_sector": None,
        "action": "none",
    }
    scaling_plan = {
        "target_notional_usdt": 167.0,
        "remaining_budget": 167.0,
        "accumulated_notional": 0.0,
        "accumulated_margin": 0.0,
        "completed": False,
        "avg_entry_price": 0.0,
    }
    return {
        "available": False,
        "data_quality": "insufficient",
        "confidence": 0.0,
        "score": 0.0,
        "score_raw": 0.0,
        "rank": "B",
        "e5": 0.0,
        "e6": 0.0,
        "e7": 0.0,
        "e8_cross_sector_valuation": 0.0,
        "tactical_position_eligibility": False,
        "bds_score": 0.0,
        "phase": "P2_REVENUE_EXPANSION",
        "phase_confidence": 0.0,
        "valuation_percentile": 50.0,
        "direction_constraint": "NEUTRAL",
        "cap_multiplier": 1.0,
        "exit_action": "NONE",
        "exit_triggers": [],
        "buffett_discount_applied": False,
        # v1.3 Phase 0 字段
        "technical_assessment": ta,
        "ts_score": ta["ts_score"],          # P0-A1: 顶层 alias（PollingTrader 直接 .get）
        "cvs": 0.0,
        "cvs_ratio": 0.0,
        "scaling_plan": scaling_plan,
        "trend_stop": trend_stop,
        "value_exit": value_exit,
        "_unavailable_reason": reason,
    }


def neutral_snapshot(reason: str = "generic_fallback") -> Dict[str, Any]:
    """整体 FAIL-OPEN 中性快照（R3）。"""
    snapshot_date = date.today().isoformat()
    return {
        "snapshot_date": snapshot_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "version": _SCHEMA_VERSION,
        "neutral_fallback_reason": reason,
        "coins": {coin: _neutral_coin_entry("global_neutral_fallback") for coin in BDSM_COINS},
    }


# =========================================================================
# §4.1 方向约束 + §4.2 仓位上限系数
# =========================================================================

def _compute_direction(score: float, data_quality: str) -> str:
    """§4.1 方向硬约束公式。

    data_quality=insufficient 强制 NEUTRAL（即使 score 阈值触发也不生效）。
    """
    if data_quality == "insufficient":
        return "NEUTRAL"
    if score > 0.3:
        return "LONG_ONLY"
    if score < -0.3:
        return "SHORT_ONLY"
    return "NEUTRAL"


# ── §4.1.2 三层矛盾感知方向约束（v2）──────────────────────────────────
# 修复旧 _compute_direction 只看 ±0.3 硬阈值忽略 confidence / value_exit /
# valuation_percentile 三个联动信号造成的"矛盾带"（SOL 实证 88.9% 失败率）。
# 新算法三层递进：L1 置信度加权阈值 → L2 价值退出否决 → L3 估值-BDS 矛盾。
# 优先级：L1 > L2 > L3；L2/L3 输出 LONG_BLOCKED 中间档（禁做多不强制做空）。
# 开关 enable_contradiction_aware_constraint 默认 True，False 走旧逻辑字节等价。
# 阈值参数 0.3 / 0.5 / 0.70 / 85 为初始值，待回测调参（见 VM-1789302387464）。


def _compute_direction_v2(
    bds_score: float,
    confidence: float,
    data_quality: str,
    value_exit_action: str = "none",
    valuation_percentile: float = 50.0,
    enable_contradiction_aware_constraint: bool = True,
) -> str:
    """§4.1.2 三层矛盾感知方向约束（v2）。

    L1 置信度加权阈值（借鉴 Black-Litterman 连续加权）:
        effective_threshold = 0.3 × (1 - 0.5 × confidence)
        conf=0.875 → 0.169；conf=1.0 → 0.15；conf=0.40 → 0.24
        bds > +effective_threshold → LONG_ONLY
        bds < -effective_threshold → SHORT_ONLY（最强制约，优先于 L2/L3）

    L2 价值退出否决（矛盾论对抗性矛盾 + LUNA 案例 + 尾部约束）:
        value_exit=="full_exit" AND bds<0 AND confidence>=0.70 → LONG_BLOCKED

    L3 估值-BDS 矛盾（2008 案例镜像，L2 未触发时的补充防线）:
        val_pct>85 AND bds<0 AND data_quality=="sufficient" → LONG_BLOCKED

    LONG_BLOCKED 语义：禁做多（拦截 UP），允许做空（放行 DOWN），
    cap_multiplier 保持原值不放大（比 SHORT_ONLY 温和）。

    data_quality=insufficient → 强制 NEUTRAL（FAIL-OPEN，信号不可靠不强拦）。
    """
    # data_quality 门禁：不足强制 NEUTRAL（FAIL-OPEN 铁律）
    if data_quality == "insufficient":
        return "NEUTRAL"

    # 开关关断 → 走旧 _compute_direction 逻辑字节等价
    if not enable_contradiction_aware_constraint:
        return _compute_direction(bds_score, data_quality)

    # L1 置信度加权阈值（最强制约，优先于 L2/L3）
    effective_threshold = 0.3 * (1.0 - 0.5 * confidence)
    if bds_score > effective_threshold:
        return "LONG_ONLY"
    if bds_score < -effective_threshold:
        return "SHORT_ONLY"

    # L2 价值退出否决 → LONG_BLOCKED
    if (
        value_exit_action == "full_exit"
        and bds_score < 0.0
        and confidence >= 0.70
    ):
        return "LONG_BLOCKED"

    # L3 估值-BDS 矛盾 → LONG_BLOCKED（L2 未触发时的补充防线）
    if (
        valuation_percentile > 85.0
        and bds_score < 0.0
        and data_quality == "sufficient"
    ):
        return "LONG_BLOCKED"

    return "NEUTRAL"


def _compute_cap_multiplier(rank: str, score: float, data_quality: str) -> float:
    """§4.2 仓位上限系数 = score_cap × rank_cap × dq_cap，夹到 [0,1]。"""
    # score_cap
    if score > 0.6:
        sc = 1.0
    elif score > 0.3:
        sc = 0.8
    elif score >= 0.0:
        sc = 0.5
    elif score >= -0.3:
        sc = 0.2
    else:
        sc = 0.0
    # rank_cap
    rc_map = {"S": 1.0, "A": 0.8, "B": 0.5, "C": 0.2}
    rc = rc_map.get(rank, 0.0)
    # dq_cap
    dq_map = {"sufficient": 1.0, "partial": 0.7, "insufficient": 0.0}
    dc = dq_map.get(data_quality, 0.0)
    return max(0.0, min(1.0, round(sc * rc * dc, 4)))


# =========================================================================
# §3.2.1 技术面评估器（v1.3 新增）— RSI / MA200 / 成交量 / ATR
# =========================================================================

def _compute_rsi(closes: list, period: int = 14) -> float:
    """RSI(14) — Wilder's smoothing 法。"""
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def _compute_atr_pct(highs: list, lows: list, closes: list, period: int = 14) -> float:
    """ATR(14) / Price × 100。"""
    if len(closes) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    atr = sum(trs[-period:]) / period
    price = closes[-1]
    return (atr / price * 100.0) if price > 0 else 0.0


def _compute_technical_assessment(
    coin: str,
    klines: list,
    ma_long: int = 200,
    ma_short: int = 128,
) -> Dict[str, Any]:
    """§3.2.1 技术面评估器。

    FAIL-OPEN：空K线或不足 → 全部中性值，不抛异常。
    """
    if not klines or len(klines) < ma_long:
        return {
            "rsi_14": 50.0,
            "ma200_deviation": 0.0,
            "ma200_slope": 0.0,
            "volume_ratio": 1.0,
            "atr_pct": 0.0,
            "ts_score": 0.0,
        }

    closes = [k["c"] for k in klines]
    highs = [k["h"] for k in klines]
    lows = [k["l"] for k in klines]
    volumes = [k["v"] for k in klines]

    # RSI(14)
    rsi = _compute_rsi(closes, 14)

    # MA200 偏离度 + 斜率
    ma_long_val = sum(closes[-ma_long:]) / ma_long
    current_price = closes[-1]
    ma200_deviation = (current_price - ma_long_val) / ma_long_val * 100.0

    if len(closes) >= ma_long + 1:
        ma_long_prev = sum(closes[-ma_long - 1:-1]) / ma_long
        ma200_slope = (ma_long_val - ma_long_prev) / ma_long_prev * 100.0 if ma_long_prev > 0 else 0.0
    else:
        ma200_slope = 0.0

    # 成交量比（当前 / 20日均量）
    vol_window = volumes[-20:] if len(volumes) >= 20 else volumes
    avg_vol = sum(vol_window) / len(vol_window) if vol_window else 1.0
    volume_ratio = volumes[-1] / avg_vol if avg_vol > 0 else 1.0

    # ATR(14) / Price
    atr_pct = _compute_atr_pct(highs, lows, closes, 14)

    # TS 综合分（归一化 0~1）
    ts_score = 0.0
    if rsi < 20:
        ts_score += 1.0
    elif rsi < 30:
        ts_score += 0.6
    if ma200_deviation < -30:
        ts_score += 1.0
    elif ma200_deviation < -15:
        ts_score += 0.6
    if volume_ratio > 2.0:
        ts_score += 0.4
    if atr_pct > 5.0:
        ts_score += 0.3
    ts_score = min(1.0, ts_score / 2.0)

    return {
        "rsi_14": round(rsi, 2),
        "ma200_deviation": round(ma200_deviation, 2),
        "ma200_slope": round(ma200_slope, 2),
        "volume_ratio": round(volume_ratio, 2),
        "atr_pct": round(atr_pct, 2),
        "ts_score": round(ts_score, 4),
    }


# =========================================================================
# §3.2.2 综合估值分（CVS）
# =========================================================================

def _compute_cvs(bds_score: float, ts_score: float) -> tuple:
    """§3.2.2 CVS = BDS×0.6 + TS×0.4，映射 ratio。"""
    cvs = round(bds_score * 0.6 + ts_score * 0.4, 4)
    if cvs >= 0.8:
        ratio = 1.0
    elif cvs >= 0.6:
        ratio = 0.5
    elif cvs >= 0.3:
        ratio = 0.3
    else:
        ratio = 0.0
    return cvs, ratio


# =========================================================================
# §3.3.1 趋势止损（MA200 / MA128 破位）
# =========================================================================

def _compute_trend_stop(
    coin: str,
    klines: list,
    ma_long: int = 200,
    ma_short: int = 128,
) -> Dict[str, Any]:
    """§3.3.1 MA200/MA128 趋势止损。

    FAIL-OPEN：空K线或不足 → action=none。
    """
    if not klines or len(klines) < ma_long + 1:
        return {
            "ma200_price": 0.0,
            "ma128_price": 0.0,
            "below_ma200_days": 0,
            "ma200_slope_negative": False,
            "death_cross": False,
            "action": "none",
        }

    closes = [k["c"] for k in klines]

    # MA200 和 MA128
    ma_long_val = sum(closes[-ma_long:]) / ma_long
    ma_short_val = sum(closes[-ma_short:]) / ma_short

    # MA200 斜率
    ma_long_prev = sum(closes[-ma_long - 1:-1]) / ma_long
    ma200_slope = (ma_long_val - ma_long_prev) / ma_long_prev * 100.0 if ma_long_prev > 0 else 0.0
    ma200_slope_negative = ma200_slope < 0

    # 连续收盘低于 MA200 的天数（从最后一天向前数）
    below_days = 0
    for i in range(len(closes) - 1, -1, -1):
        if i >= ma_long - 1:
            ma_at_i = sum(closes[i - ma_long + 1:i + 1]) / ma_long
            if closes[i] < ma_at_i:
                below_days += 1
            else:
                break

    # 死叉：MA128 < MA200
    death_cross = ma_short_val < ma_long_val

    # 动作判定（优先级：full_exit > reduce50 > reduce30 > none）
    # Fix-I(2026-09-03): death_cross → reduce30 假信号收紧：
    #   原条件：只要 MA128 < MA200 就 reduce30
    #   新条件：death_cross AND below_days >= 2 AND MA200 斜率负 → reduce30
    #   缺少任一条件 → 死叉判定为短期回调/斜率尚未确立 → 忽略不触发
    action = "none"
    if below_days >= 5 and ma200_slope_negative:
        action = "full_exit"
    elif below_days >= 3 and ma200_slope_negative:
        action = "reduce50"
    elif death_cross and below_days >= 2 and ma200_slope_negative:
        action = "reduce30"

    return {
        "ma200_price": round(ma_long_val, 4),
        "ma128_price": round(ma_short_val, 4),
        "below_ma200_days": below_days,
        "ma200_slope_negative": ma200_slope_negative,
        "death_cross": death_cross,
        "action": action,
    }


# =========================================================================
# §3.4.2 价值发现止盈
# =========================================================================

def _compute_value_exit(
    bds_score: float,
    valuation_percentile: float,
    e8_cross_sector: Optional[float] = None,
) -> Dict[str, Any]:
    """§3.4.2 价值发现止盈：P/F 高估 / BDS 恶化。

    valuation_percentile 用作 P/F 估值分位的代理（0~100，越高越贵）。

    E8 双门控（2026-09-06 新增）：
      当纵向 pf_bubble（>90）但横向 E8 > 0（板块中相对便宜）时，
      判定为「板块共振高估」而非「自身泡沫」，从 full_exit 降级为 reduce30。
      e8_cross_sector=None 时走原逻辑（兼容旧调用）。
    """
    pf_overvalued = valuation_percentile > 80.0
    pf_bubble = valuation_percentile > 90.0
    bds_collapse = bds_score < 0.0

    # E8 交叉验证：纵向泡沫但横向不贵 → 降级为 reduce30
    if pf_bubble and e8_cross_sector is not None and e8_cross_sector > 0.0:
        pf_bubble = False
        pf_overvalued = True

    action = "none"
    if pf_bubble or bds_collapse:
        action = "full_exit"
    elif pf_overvalued:
        action = "reduce30"

    return {
        "pf_percentile": round(valuation_percentile, 2),
        "pf_overvalued": pf_overvalued,
        "pf_bubble": pf_bubble,
        "e8_cross_sector": round(e8_cross_sector, 4) if e8_cross_sector is not None else None,
        "action": action,
    }


# =========================================================================
# §4.3 B1~B5 基本面出场触发（需要最近 N 日历史快照对比）
# =========================================================================

def _load_history_snapshots(out_dir: str, today_str: str, days: int = _HISTORY_DAYS_FOR_EXIT_TRIGGERS) -> Dict[str, Dict[str, Any]]:
    """加载最近 days 天的历史快照（不含今日），返回 {YYYY-MM-DD: snapshot_dict}。"""
    history: Dict[str, Dict[str, Any]] = {}
    # 尝试倒推 days 天，每个对应日期读文件；读不到跳过（FAIL-OPEN：历史缺失不影响今日结论）
    try:
        today_d = date.fromisoformat(today_str)
    except ValueError:
        return history
    from datetime import timedelta
    for i in range(1, days + 1):
        d = today_d - timedelta(days=i)
        ds = d.isoformat()
        fname = f"bdsm_snapshot_{ds.replace('-', '')}.json"
        fpath = os.path.join(out_dir, fname)
        if not os.path.exists(fpath):
            continue
        try:
            with open(fpath) as f:
                history[ds] = json.load(f)
        except Exception:
            continue
    return history


def _detect_exit_action(coin: str, today_entry: Dict[str, Any], history: Dict[str, Dict[str, Any]]) -> tuple[str, list[str]]:
    """§4.3 B1~B5 出场触发检测。返回 (action, triggers)。

    优先级：CLOSE_ALL > REDUCE_80 > REDUCE_50 > NONE。
    history 为空（无历史快照可用）→ 无法对比 → 返回 NONE。
    """
    if not history:
        return "NONE", []
    triggers: list[str] = []
    # 按日期排序（升序），[-1] = 昨日, [-2] = 前日, [-3] = 大前日
    sorted_dates = sorted(history.keys())
    y = history[sorted_dates[-1]]["coins"].get(coin, {}) if sorted_dates else {}
    by = history[sorted_dates[-2]]["coins"].get(coin, {}) if len(sorted_dates) >= 2 else {}
    tby = history[sorted_dates[-3]]["coins"].get(coin, {}) if len(sorted_dates) >= 3 else {}

    # B4 (Highest): E7 前日 > 0 今日 <= 0 → REDUCE_80
    if y.get("available", False) and today_entry["available"]:
        if y.get("e7", 0) > 0 and today_entry.get("e7", 0) <= 0:
            triggers.append("B4_e7_collapse")
            action = "REDUCE_80"
            # B2 / B5 CLOSE_ALL 覆盖 B4（检测更高优先级）
            if _phase_degraded(y, today_entry) or _rank_tumbling([tby, by, y, today_entry]):
                triggers += _b2_triggers(y, today_entry)
                if _rank_tumbling([tby, by, y, today_entry]):
                    triggers.append("B5_rank_tumbling")
                return "CLOSE_ALL", triggers
            return action, triggers

    # B2 + B5 CLOSE_ALL（其次）
    closed = False
    if _phase_degraded(y, today_entry):
        triggers += _b2_triggers(y, today_entry)
        closed = True
    if _rank_tumbling([tby, by, y, today_entry]):
        triggers.append("B5_rank_tumbling")
        closed = True
    if closed:
        return "CLOSE_ALL", triggers

    # B1 + B3 REDUCE_50（最低优先级，互不覆盖，同时触发 action 仍是 REDUCE_50）
    if _b1_p2_to_p3(y, today_entry):
        triggers.append("B1_p2_to_p3")
    if _b3_score_break([by, y, today_entry]):
        triggers.append("B3_score_deterioration")
    if triggers:
        return "REDUCE_50", triggers
    return "NONE", []


def _phase_degraded(y: Dict[str, Any], t: Dict[str, Any]) -> bool:
    """B2: Phase 退化为中性/回 P1 且 bds<0（逻辑失效）。"""
    y_phase = y.get("phase")
    t_phase = t.get("phase")
    if not y.get("available") or not t.get("available"):
        return False
    was_active = y_phase in ("P2_REVENUE_EXPANSION", "P3_VALUATION_RECOVERY")
    # 从活跃阶段转 P1 且 bds < 0 → 全出
    if was_active and t_phase == "P1_EXPECTATION" and t.get("bds_score", 0) < 0:
        return True
    # 默认中性（phase_confidence<0.3 且 P2 默认中性）
    if was_active and t.get("phase_confidence", 1) < 0.3 and t_phase == "P2_REVENUE_EXPANSION":
        # 认为已退化至无法识别 → 全出
        return True
    return False


def _b2_triggers(y: Dict[str, Any], t: Dict[str, Any]) -> list[str]:
    out = []
    if t.get("phase") == "P1_EXPECTATION" and t.get("bds_score", 0) < 0:
        out.append("B2_phase_reverted_to_p1")
    if t.get("phase_confidence", 1) < 0.3:
        out.append("B2_phase_default_neutral_confidence_collapse")
    return out


def _rank_tumbling(window: list[Dict[str, Any]]) -> bool:
    """B5: 3 天内 ≥ 2 级下降（S→B 或 A→C），或最近 ≥ 3 天 rank=C。"""
    rank_series = [_RANK_ORDER.get(d.get("rank", "B"), 2) for d in window if d.get("available", False)]
    if len(rank_series) < 3:
        return False
    first, last = rank_series[0], rank_series[-1]
    if first - last >= 2:
        return True
    # 最近连续 ≥ 3 C
    if len(rank_series) >= 3 and all(r == _RANK_ORDER["C"] for r in rank_series[-3:]):
        return True
    return False


def _b1_p2_to_p3(y: Dict[str, Any], t: Dict[str, Any]) -> bool:
    """B1: P2 → P3 且 估值 > 80 分位 且 bds ≥ 0。"""
    if not y.get("available") or not t.get("available"):
        return False
    return (
        y.get("phase") == "P2_REVENUE_EXPANSION"
        and t.get("phase") == "P3_VALUATION_RECOVERY"
        and t.get("valuation_percentile", 0) > 80
        and t.get("bds_score", 0) >= 0
    )


def _b3_score_break(window: list[Dict[str, Any]]) -> bool:
    """B3: 连续 2 日 score 从 >0.3 跌破 0，或单日 score_raw 跌幅 >= 0.4。"""
    usable = [d for d in window if d.get("available", False)]
    if len(usable) < 3:
        return False
    by, y, t = usable[-3], usable[-2], usable[-1]
    # 连续 2 日跌破
    if by.get("score", 0) > 0.3 and y.get("score", 0) <= 0 and t.get("score", 0) <= 0:
        return True
    # 单日暴跌 0.4
    if abs(y.get("score_raw", 0) - t.get("score_raw", 0)) >= 0.4:
        return True
    return False


# =========================================================================
# Phase 3 巴菲特要素（开关保护）
# =========================================================================

def _maybe_apply_buffett_discount(score_raw: float) -> tuple[float, bool]:
    """Phase 3 可选：score × 0.7 安全边际折扣。"""
    if not ENABLE_BUFFETT_DISCOUNT:
        return score_raw, False
    # 负值进一步打折更负（正确行为），但需夹到 [-1,1]
    return max(-1.0, min(1.0, score_raw * _BUFFETT_DISCOUNT_FACTOR)), True


def _maybe_apply_e7_bias(e7: float) -> float:
    """Phase 3 可选：E7 负值 1.3× 放大。"""
    if not ENABLE_E7_NEGATIVE_BIAS or e7 >= 0:
        return e7
    return max(-1.0, e7 * _E7_NEGATIVE_BIAS_MULTIPLIER)


# =========================================================================
# 真实快照生成（逐币 compute_all + classify_phase）
# =========================================================================

def _build_coin_entry(coin: str, db_path: str | None = None) -> Dict[str, Any]:
    """对单个币种执行 compute_signal → 计算约束。

    coin_fundamental_ranker.compute_signal(coin, db_path) 返回 CoinFundamentalSignal
    dataclass，内部已经调用 compute_all、_synthesize_score（分层加权七信号）、
    并计算 fundamental_score / rank / confidence / sub_signals / data_quality。
    FAIL-OPEN：任何异常返回 neutral_coin_entry，绝不抛出。
    """
    try:
        # 延迟 import，避免模块未装就崩溃
        from force_vector.coin_fundamental_ranker import compute_signal  # noqa: WPS433
    except Exception as exc:  # pragma: no cover
        logger.warning("BDSM import compute_signal 失败 coin=%s: %s", coin, exc)
        return _neutral_coin_entry("import_compute_signal_failure")

    try:
        if db_path:
            sig = compute_signal(coin, db_path=db_path)
        else:
            sig = compute_signal(coin)
    except Exception as exc:
        logger.warning("BDSM compute_signal 失败 coin=%s: %s", coin, exc)
        return _neutral_coin_entry("compute_signal_failed")

    if getattr(sig, "error", None):
        return _neutral_coin_entry(f"ranker_error:{sig.error}")

    sub_signals = getattr(sig, "sub_signals", {}) or {}
    score_raw = float(getattr(sig, "fundamental_score", 0.0))
    e5 = float(sub_signals.get("supply_shrinkage_intensity", 0.0))
    e6 = float(sub_signals.get("value_capture_delta", 0.0))
    e7_raw = float(sub_signals.get("revenue_sustainability", 0.0))
    e7 = _maybe_apply_e7_bias(e7_raw)
    e8_cross_sector = float(sub_signals.get("e8_cross_sector_valuation", 0.0) or 0.0)
    bds_score = round(e7 * 0.4 + e6 * 0.3 + e5 * 0.3, 4)
    score, discount_applied = _maybe_apply_buffett_discount(score_raw)
    rank = str(getattr(sig, "rank", "B"))
    if rank not in _RANK_ORDER:
        rank = "B"
    confidence = float(getattr(sig, "confidence", 0.0))

    # data_quality 本地重算：7 信号覆盖率 + confidence 一致性
    # 原 ranker.data_quality 仅统计 Artemis 四信号（DeFiLlama 数据），对 BDSM 三信号(E5/E6/E7)
    # 覆盖率有数据时也应算入，否则所有 BDSM 币因 Artemis 数据缺而永久 insufficient → cap=0 不开仓。
    covered = 0
    total_signals = (
        "revenue_stability",
        "mc_fees_mean_reversion",
        "tvl_growth_momentum",
        "revenue_quality",
        "supply_shrinkage_intensity",
        "value_capture_delta",
        "revenue_sustainability",
    )
    for k in total_signals:
        v = sub_signals.get(k)
        if v is not None and abs(float(v)) > 1e-9:
            covered += 1
    coverage_ratio = covered / len(total_signals)  # 0~1
    # 综合 coverage + confidence
    if coverage_ratio >= 5 / 7 and confidence >= 0.70:
        data_quality = "sufficient"
    elif coverage_ratio >= 3 / 7 and confidence >= 0.35:
        data_quality = "partial"
    elif coverage_ratio >= 1 / 7:
        data_quality = "partial"  # 至少部分信号真实
    else:
        data_quality = "insufficient"
    # 沿用 ranker 给的 confidence，不改值本身

    # Phase 识别 — 签名：classify_phase(coin, sub_signals:Dict, valuation_percentile:float)
    try:
        from force_vector.coin_fundamental_phase_classifier import classify_phase  # noqa: WPS433
        val_pct_input = float(sub_signals.get("valuation_percentile", 50.0))
        phase_obj = classify_phase(
            coin, sub_signals=dict(sub_signals), valuation_percentile=val_pct_input
        )
        if phase_obj is None:
            phase = "P2_REVENUE_EXPANSION"
            phase_conf = 0.0
            val_pct = val_pct_input
        else:
            phase = getattr(phase_obj, "current_phase", "P2_REVENUE_EXPANSION")
            phase_conf = float(getattr(phase_obj, "phase_confidence", 0.0))
            evidence = getattr(phase_obj, "evidence", {}) or {}
            if isinstance(evidence, dict) and "valuation_percentile" in evidence:
                val_pct = float(evidence["valuation_percentile"])
            else:
                val_pct = val_pct_input
    except Exception as exc:
        logger.warning("BDSM classify_phase 失败 coin=%s: %s", coin, exc)
        phase, phase_conf, val_pct = "P2_REVENUE_EXPANSION", 0.0, 50.0

    direction = _compute_direction(score, data_quality)
    cap = _compute_cap_multiplier(rank, score, data_quality)
    # direction_v2 初始占位（Phase 0 写回 value_exit 后用 v2 覆盖）
    direction_v2 = direction

    entry = {
        "available": True,
        "data_quality": data_quality,
        "confidence": confidence,
        "score": round(score, 4),
        "score_raw": round(score_raw, 4),
        "rank": rank,
        "e5": round(e5, 4),
        "e6": round(e6, 4),
        "e7": round(e7, 4),
        "e8_cross_sector_valuation": round(e8_cross_sector, 4),
        "bds_score": bds_score,
        "phase": phase,
        "phase_confidence": round(phase_conf, 4),
        "valuation_percentile": round(val_pct, 2),
        "direction_constraint": direction,
        "cap_multiplier": cap,
        "exit_action": "NONE",  # 由外层在 _detect_exit_action 里统一填充（需要历史）
        "exit_triggers": [],
        "buffett_discount_applied": discount_applied,
    }

    # ── P0-A1: Phase 0 真实值写回（技术面/趋势/估值三维 → CVS）──────────────
    # spec §3.2: CVS = BDS×0.6 + TS×0.4 动态分批建仓
    # spec §3.3: 趋势止损 MA200/MA128
    # spec §3.4: 价值发现止盈 P/F 高估 / BDS 恶化
    # FAIL-OPEN：缺 K 线 / import 失败 / 计算异常 → 用 neutral 默认值（不抛出）
    try:
        _klines = _fetch_snapshot_klines(coin)
        if _klines and len(_klines) >= MA_LONG_DEFAULT:
            _ta = _compute_technical_assessment(coin, _klines, ma_long=MA_LONG_DEFAULT, ma_short=128)
            _ts_score = float(_ta.get("ts_score", 0.0) or 0.0)
            _cvs, _cvs_ratio = _compute_cvs(bds_score, _ts_score)
            _trend_stop = _compute_trend_stop(coin, _klines, ma_long=MA_LONG_DEFAULT, ma_short=128)
            # 用 BUG-4 正方向代理公式（MA200_dev×2+50）从 technical_assessment 推导估值分位替代值
            _ma_dev = float(_ta.get("ma200_deviation", 0.0) or 0.0)
            _val_pct_ta = min(100.0, max(0.0, _ma_dev * 2.0 + 50.0))
            # 与 classify_phase 的估值分位合并：取 max(基本面分位, 技术代理分位) — 取高估一侧保守
            _val_merged = max(float(entry.get("valuation_percentile", 50.0) or 50.0), _val_pct_ta)
            _ve = _compute_value_exit(bds_score, _val_merged, e8_cross_sector=e8_cross_sector)

            entry["technical_assessment"] = {
                "rsi_14": float(_ta.get("rsi_14", 50.0) or 50.0),
                "ma200_deviation": _ma_dev,
                "ma200_slope": float(_ta.get("ma200_slope", 0.0) or 0.0),
                "volume_ratio": float(_ta.get("volume_ratio", 1.0) or 1.0),
                "atr_pct": float(_ta.get("atr_pct", 0.0) or 0.0),
                "ts_score": _ts_score,
            }
            entry["ts_score"] = _ts_score
            entry["cvs"] = round(_cvs, 4)
            entry["cvs_ratio"] = round(_cvs_ratio, 4)
            entry["scaling_plan"] = {
                "target_notional_usdt": 167.0,
                "remaining_budget": 167.0,
                "accumulated_notional": 0.0,
                "accumulated_margin": 0.0,
                "completed": False,
                "avg_entry_price": 0.0,
            }
            entry["trend_stop"] = dict(_trend_stop) if isinstance(_trend_stop, dict) else {"action": "none"}
            entry["value_exit"] = dict(_ve) if isinstance(_ve, dict) else {"action": "none"}
            entry["valuation_percentile"] = round(_val_merged, 2)
        else:
            # K线不足 → 复用 neutral 里 Phase 0 字段（FAIL-OPEN）
            _neutral = _neutral_coin_entry(f"kline_insufficient:{len(_klines or [])}")
            entry["technical_assessment"] = _neutral["technical_assessment"]
            entry["ts_score"] = _neutral["ts_score"]
            entry["cvs"] = _neutral["cvs"]
            entry["cvs_ratio"] = _neutral["cvs_ratio"]
            entry["scaling_plan"] = _neutral["scaling_plan"]
            entry["trend_stop"] = _neutral["trend_stop"]
            entry["value_exit"] = _neutral["value_exit"]
    except Exception as _exc:
        logger.warning("BDSM Phase0 写回失败 coin=%s: %s", coin, _exc)
        _neutral = _neutral_coin_entry(f"phase0_writeback_error:{_exc}")
        entry["technical_assessment"] = _neutral["technical_assessment"]
        entry["ts_score"] = _neutral["ts_score"]
        entry["cvs"] = _neutral["cvs"]
        entry["cvs_ratio"] = _neutral["cvs_ratio"]
        entry["scaling_plan"] = _neutral["scaling_plan"]
        entry["trend_stop"] = _neutral["trend_stop"]
        entry["value_exit"] = _neutral["value_exit"]

    # ── §4.1.2 三层矛盾感知方向约束（v2）覆盖 ──
    # Phase 0 写回 value_exit / valuation_percentile 后，用 v2 重新计算 direction_constraint。
    # 修复旧 _compute_direction 只看 ±0.3 忽略 confidence / value_exit / val_pct 矛盾带。
    try:
        _ve_action = "none"
        if isinstance(entry.get("value_exit"), dict):
            _ve_action = str(entry["value_exit"].get("action", "none") or "none")
        _val_pct_final = float(entry.get("valuation_percentile", 50.0) or 50.0)
        direction_v2 = _compute_direction_v2(
            bds_score=bds_score,
            confidence=confidence,
            data_quality=data_quality,
            value_exit_action=_ve_action,
            valuation_percentile=_val_pct_final,
        )
        entry["direction_constraint"] = direction_v2
    except Exception as _exc_v2:
        logger.warning("BDSM direction_v2 覆盖失败 coin=%s: %s", coin, _exc_v2)
        # FAIL-OPEN：覆盖失败保留旧 direction（entry["direction_constraint"] 已是旧值）

    # ── 战术小仓资格（2026-09-06 Phase 1）────────────────────────────
    try:
        from force_vector.bdsm_tactical_position import tactical_entry_check
        entry["tactical_position_eligibility"] = bool(tactical_entry_check(entry))
    except Exception:
        entry["tactical_position_eligibility"] = False  # FAIL-OPEN

    return entry


# =========================================================================
# 对外主入口：write_snapshot
# =========================================================================

def write_snapshot(
    out_dir: str | None = None,
    dry_run_read_coin_data_from_db: bool = True,
    db_path: str | None = None,
    target_date: str | None = None,
) -> str:
    """生成并写入 bdsm_snapshot_{YYYYMMDD}.json，返回绝对文件路径。

    Args:
        out_dir: 输出目录；None → 默认 11-易经推理系统/.workbuddy/bdsm
        dry_run_read_coin_data_from_db: True（默认）→ 真实读 data_center.db 跑 compute_all
                                        False → 全部填 neutral_coin_entry，仅用于单元测试/结构验证
        db_path: data_center.db 路径；None → 走 coin_fundamental_crypto.DEFAULT_DB_PATH
        target_date: 目标日期 'YYYY-MM-DD'；None → date.today()。用于 --backfill 模式
                     或 cron 每日调用。注意：data_center.db 只有当前快照数据，
                     过去日期的快照仍使用当前 DB 数据（基本面日变化极小可接受）。
    """
    actual_dir = out_dir or _DEFAULT_SNAPSHOT_DIR
    os.makedirs(actual_dir, exist_ok=True)
    today_str = target_date or date.today().isoformat()
    filename = f"bdsm_snapshot_{today_str.replace('-', '')}.json"
    output_path = os.path.abspath(os.path.join(actual_dir, filename))

    coins_data: Dict[str, Dict[str, Any]] = {}
    if dry_run_read_coin_data_from_db:
        for coin in BDSM_COINS:
            coins_data[coin] = _build_coin_entry(coin, db_path=db_path)
    else:
        # 纯结构骨架：每币 neutral，但保留字段齐全
        for coin in BDSM_COINS:
            coins_data[coin] = _neutral_coin_entry("dry_run_db_read_disabled")

    # 加载最近 4 日快照 → 计算 B1~B5 出场触发
    history = _load_history_snapshots(actual_dir, today_str) if dry_run_read_coin_data_from_db else {}
    for coin, entry in coins_data.items():
        if not entry["available"]:
            continue  # 数据不可靠不出场
        action, triggers = _detect_exit_action(coin, entry, history)
        entry["exit_action"] = action
        entry["exit_triggers"] = triggers

    snapshot: Dict[str, Any] = {
        "snapshot_date": today_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "version": _SCHEMA_VERSION,
        "neutral_fallback_reason": "",
        "coins": coins_data,
    }

    # 原子写入（先写 tmp 再 rename）
    tmp_path = f"{output_path}.tmp"
    try:
        with open(tmp_path, "w") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, output_path)
    except Exception as exc:
        logger.error("BDSM 快照写入失败 path=%s: %s", output_path, exc)
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise

    logger.info("BDSM 快照已写入: %s (%d coins)", output_path, len(coins_data))
    return output_path


# =========================================================================
# BCRM 侧读取入口：读取今日快照，FAIL-OPEN 中性兜底
# =========================================================================

def load_today_snapshot(out_dir: str | None = None) -> Dict[str, Any]:
    """BCRM 每 K 线周期调用：读当日快照，任何异常返回 neutral_snapshot()。

    外部调用方（PollingTrader.run_tick()、出场巡检逻辑等）只应通过此函数读取，
    避免重复实现 FAIL-OPEN 兜底。
    """
    actual_dir = out_dir or _DEFAULT_SNAPSHOT_DIR
    today_str = date.today().isoformat().replace("-", "")
    fpath = os.path.join(actual_dir, f"bdsm_snapshot_{today_str}.json")
    if not os.path.exists(fpath):
        return neutral_snapshot(reason=f"snapshot_file_missing:{fpath}")
    try:
        with open(fpath) as f:
            snap = json.load(f)
        # 基本校验
        if not isinstance(snap, dict) or "coins" not in snap:
            return neutral_snapshot(reason="snapshot_schema_invalid")
        # 确保今日快照版本字段有值（防止旧格式）
        snap.setdefault("version", _SCHEMA_VERSION)
        return snap
    except Exception as exc:
        logger.warning("BDSM load_today_snapshot 失败，走中性: %s", exc)
        return neutral_snapshot(reason=f"snapshot_load_error:{type(exc).__name__}")


# =========================================================================
# CLI 入口：python bdsm_snapshot_writer.py [--no-db] [--out-dir DIR] [--target-date YYYY-MM-DD]
# =========================================================================

def _cli_main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="BDSM 每日快照生成")
    parser.add_argument("--out-dir", default=None, help="输出目录（默认 .workbuddy/bdsm）")
    parser.add_argument("--no-db", action="store_true", help="不读 DB，全填充中性骨架（仅做结构/写入测试）")
    parser.add_argument("--target-date", default=None,
                        help="目标日期 YYYY-MM-DD（用于 --backfill 模式或指定日期生成快照）")
    args = parser.parse_args()
    try:
        write_snapshot(
            out_dir=args.out_dir,
            dry_run_read_coin_data_from_db=(not args.no_db),
            target_date=args.target_date,
        )
    except Exception as exc:
        logger.exception("BDSM 快照生成异常: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli_main())
