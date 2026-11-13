# -*- coding: utf-8 -*-
"""DimensionForceEvaluator — 各维度矛盾力量计算（真实市场维度）.

SPEC-各维度矛盾计算重建 v0.3 T3 实现。

维度体系（v2.0）:
  D1 宏观利率: CPI surprise + fedwatch 加息概率 → 风险资产多空力量
  D2 资金流:   多空比 + 资金费率 → 拥挤度/外流力量
  D3 技术:     由调用方传入（现有路径共振），本评估器不计算
  D4 市场情绪: 恐惧贪婪指数 → 极端情绪反转力量

设计要点:
  • 只读 19 DAL 通用指标表 mm_metrics（不写库）
  • z-score 标准化（窗口: D1 24 个月 / D2 30 天 / D4 90 天）
  • 数据不足降级链: 缺失/陈旧(>7 天) → neutral/0.0 不参与裁决（FAIL-OPEN）
  • 输出: {dim: {direction, strength, raw_z, degraded}}

硬约束: HC-AGI-02（异常→中性兜底）、FAIL-OPEN 铁律。
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 数据陈旧阈值（秒）: 超过视为降级
_STALE_SEC = 7 * 24 * 3600


class DimensionForceEvaluator:
    """各维度矛盾力量评估器（只读 DAL）."""

    # z-score 窗口（秒）
    WINDOW_D1 = 24 * 30 * 24 * 3600  # 24 个月
    WINDOW_D2 = 30 * 24 * 3600  # 30 天
    WINDOW_D4 = 90 * 24 * 3600  # 90 天
    # 窗口最小样本数（不足降级 percentile→再不足降级 neutral）
    MIN_SAMPLES_D1 = 8
    MIN_SAMPLES_D2 = 30
    MIN_SAMPLES_D4 = 30

    def __init__(self, db_path: str | None = None) -> None:
        if db_path is None:
            # 路径: 本文件位于 <root>/23-.../dreambuddy_evolution/core/ → parents[3] = 项目根
            db_path = str(
                Path(__file__).resolve().parents[3]
                / "19-数据访问层"
                / "data"
                / "dreambuddy_core.db"
            )
        self._db_path = db_path

    # ------------------------------------------------------------------
    # DAL 读取原语
    # ------------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        """连接 DAL 库: 普通连接优先（WAL 兼容），失败降级只读 URI."""
        try:
            return sqlite3.connect(self._db_path, timeout=5)
        except Exception:
            return sqlite3.connect(f"file:{self._db_path}?mode=ro", uri=True, timeout=5)

    def _query_latest(self, sub_category: str, metric_name: str) -> tuple[float, int] | None:
        """读 mm_metrics 最新一条 (value, unix_ts)."""
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT metric_value, timestamp FROM mm_metrics "
                    "WHERE sub_category=? AND metric_name=? ORDER BY timestamp DESC LIMIT 1",
                    (sub_category, metric_name),
                ).fetchone()
            if row is None or row[0] is None:
                return None
            return float(row[0]), int(row[1])
        except Exception:
            return None

    def _query_history(
        self, sub_category: str, metric_name: str, window_sec: int
    ) -> list[tuple[float, int]]:
        """读窗口内历史序列 [(value, unix_ts), ...]."""
        cutoff = int(time.time()) - window_sec
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT metric_value, timestamp FROM mm_metrics "
                    "WHERE sub_category=? AND metric_name=? AND timestamp>=? "
                    "ORDER BY timestamp ASC",
                    (sub_category, metric_name, cutoff),
                ).fetchall()
            return [(float(r[0]), int(r[1])) for r in rows if r[0] is not None]
        except Exception:
            return []

    def _query_funding_rate_annualized(self) -> tuple[float | None, int | None]:
        """读取资金费率年化(%)，兼容多数据源多口径（按优先级 fallback）.

        数据源口径（按优先级）:
          1. sub_category='funding_rate'      (Binance Futures)
          2. sub_category='okx_derivatives'   (OKX 衍生品，免 Key 公开 API)
        metric_name 口径:
          - funding_rate               → 小数费率(如 0.0001=0.01%/8h)
          - funding_rate_annualized_pct → 已年化百分比(如 10.95)
          - funding_rate_pct           → 每 8h 百分比(如 0.01=0.01%)
        陈旧(>7天)数据自动跳过，尝试下一候选。
        返回 (annualized_pct, unix_ts)；均不可用返回 (None, None)。
        """
        now = int(time.time())
        # (sub_category, metric_name, to_annualized_pct)
        candidates = [
            ("funding_rate", "funding_rate", lambda v: v * 3 * 365 * 100),
            ("funding_rate", "funding_rate_annualized_pct", lambda v: v),
            ("funding_rate", "funding_rate_pct", lambda v: v * 3 * 365),
            ("okx_derivatives", "funding_rate_annualized_pct", lambda v: v),
            ("okx_derivatives", "funding_rate_pct", lambda v: v * 3 * 365),
        ]
        for sub_cat, metric, conv in candidates:
            fr = self._query_latest(sub_cat, metric)
            if fr is None:
                continue
            val, ts = fr
            if now - ts > _STALE_SEC:
                continue  # 陈旧 → 跳过，尝试下一候选
            return conv(val), ts
        return None, None

    @staticmethod
    def _zscore(value: float, history: list[float]) -> float:
        """z-score; 样本<30 降级 percentile 排名映射到 [-2,2]."""
        if len(history) >= 30:
            import math

            mu = sum(history) / len(history)
            var = sum((x - mu) ** 2 for x in history) / len(history)
            sd = math.sqrt(var) if var > 0 else 0.0
            return (value - mu) / sd if sd > 0 else 0.0
        if len(history) >= 2:
            below = sum(1 for x in history if x <= value)
            pct = below / len(history)
            return (pct - 0.5) * 4.0  # percentile → [-2, 2]
        return 0.0

    @staticmethod
    def _clamp01(x: float) -> float:
        return max(0.0, min(1.0, x))

    @staticmethod
    def _neutral(reason: str) -> dict[str, Any]:
        return {"direction": "neutral", "strength": 0.0, "raw_z": 0.0, "degraded": reason}

    # ------------------------------------------------------------------
    # B-06: OI / 清算读取（19-DAL 新表）
    # ------------------------------------------------------------------
    def _query_open_interest(self, symbol: str) -> dict[str, Any] | None:
        """读取最新 OI + 24h 变化率；优先预计算列，缺失时用最近两行推算."""
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT open_interest, oi_change_pct_24h, timestamp "
                    "FROM mm_open_interest WHERE symbol=? "
                    "ORDER BY timestamp DESC LIMIT 2",
                    (symbol,),
                ).fetchall()
        except Exception:
            return None
        if not rows:
            return None
        latest = rows[0]
        oi = float(latest[0]) if latest[0] is not None else None
        change = latest[1]
        if change is not None:
            try:
                change = float(change)
            except (TypeError, ValueError):
                change = None
        if change is None and oi is not None and len(rows) > 1 and rows[1][0]:
            try:
                prev = float(rows[1][0])
                change = (oi - prev) / prev if prev > 0 else None
            except (TypeError, ValueError, ZeroDivisionError):
                change = None
        return {
            "open_interest": oi,
            "change_pct_24h": change,
            "timestamp": int(latest[2]),
        }

    def _query_liquidation_24h(self, symbol: str) -> dict[str, float] | None:
        """汇总最近 24h 多/空爆仓 USDT."""
        cutoff = int(time.time()) - 86400
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT SUM(liq_long_usdt), SUM(liq_short_usdt), SUM(liq_total_usdt) "
                    "FROM mm_liquidation WHERE symbol=? AND timestamp>=?",
                    (symbol, cutoff),
                ).fetchone()
        except Exception:
            return None
        if not row or all(value is None for value in row):
            return None
        liq_long = float(row[0] or 0.0)
        liq_short = float(row[1] or 0.0)
        total = float(row[2]) if row[2] is not None else liq_long + liq_short
        return {"liq_long": liq_long, "liq_short": liq_short, "liq_total": total}

    # ------------------------------------------------------------------
    # D1 宏观利率维度
    # ------------------------------------------------------------------
    def evaluate_d1(self) -> dict[str, Any]:
        """CPI surprise + fedwatch 加息概率 → 风险资产多空力量.

        逻辑: surprise>0（鹰派超预期）/ hike_prob 高 → 加息预期↑ → 风险资产空头力量↑
              surprise<0（鸽派）/ hike_prob 低 → 空头力量↓（甚至利多）
        """
        try:
            surprise = self._query_latest("cpi", "surprise")
            hike = self._query_latest("fedwatch", "hike_prob")
            if surprise is None and hike is None:
                return self._neutral("no-macro-data")
            # 陈旧检查（宏观数据允许 35 天陈旧——CPI 月度发布）
            now = int(time.time())
            # 方向由 surprise 符号决定（事件驱动）:
            #   surprise > 0 超预期鹰派 → 加息预期↑ → 风险资产空头力量
            #   surprise < 0 不及预期鸽派 → 空头力量减弱（利多）
            # z-score 仅调制强度（相对历史 surprise 分布的异常程度），不决定方向
            raw = 0.0
            weight_sum = 0.0
            if surprise is not None and now - surprise[1] < 35 * 24 * 3600:
                hist = [v for v, _ in self._query_history("cpi", "surprise", self.WINDOW_D1)]
                z_s = abs(self._zscore(surprise[0], hist))  # 异常程度（无符号）
                # 方向: 符号；强度: |surprise| 归一 + z 异常度加权
                sign = 1.0 if surprise[0] > 0 else (-1.0 if surprise[0] < 0 else 0.0)
                mag = self._clamp01(abs(surprise[0]) / 1.0)  # |surprise|≥1 满强度
                z_mag = self._clamp01(z_s / 2.0)
                s_force = sign * max(mag, z_mag * 0.8)  # 取幅度与异常度较大者
                raw += s_force * 0.7  # surprise 主导 70%
                weight_sum += 0.7
            if hike is not None and now - hike[1] < _STALE_SEC:
                # hike_prob 辅助 30%: >0.5 增强空头, <0.5 减弱
                raw += (float(hike[0]) - 0.5) * 2.0 * 0.3
                weight_sum += 0.3
            if weight_sum <= 0:
                return self._neutral("macro-stale")
            raw = raw / weight_sum  # 归一 [-1,1]
            direction = "short" if raw > 0.15 else ("long" if raw < -0.15 else "neutral")
            strength = self._clamp01(abs(raw))
            return {
                "direction": direction,
                "strength": round(strength, 3),
                "raw_z": round(raw, 3),
                "degraded": None,
            }
        except Exception as e:
            logger.debug("[DimensionForce] D1 fail: %s", e)
            return self._neutral("d1-error")

    # ------------------------------------------------------------------
    # D2 资金流维度
    # ------------------------------------------------------------------
    def evaluate_d2(self, symbol: str | None = None) -> dict[str, Any]:
        """多空比 + 资金费率 + OI + 清算 → 资金流力量.

        逻辑: 多空比高（多头拥挤）→ 反转空头力量; 资金费率正高 → 多头付费拥挤 → 空头力量
              多空比低（空头拥挤）→ 反转多头力量
        OI/清算仅当 `enable_d2_oi_liq=True` 时参与合成；默认关闭，保持 shadow。
        """
        symbol = symbol or os.environ.get("DIMENSION_FORCE_SYMBOL", "BTC")
        try:
            now = int(time.time())
            components: dict[str, Any] = {}
            ls_part: float | None = None
            fr_part: float | None = None
            taker_part: float | None = None
            oi_part: float | None = None
            liq_part: float | None = None
            ls_value: float | None = None
            oi_available = False

            ls = self._query_latest("long_short_ratio", "long_short_ratio")
            if ls is not None and now - ls[1] < _STALE_SEC:
                ls_value = float(ls[0])
                hist = [
                    v
                    for v, _ in self._query_history(
                        "long_short_ratio", "long_short_ratio", self.WINDOW_D2
                    )
                ]
                z_ls = self._zscore(ls[0], hist)
                # 多头拥挤（z 高）→ 空头力量; z 低 → 多头力量
                ls_part = max(-1.0, min(1.0, z_ls / 2.0))
                components["long_short_ratio"] = {
                    "value": round(ls_value, 6),
                    "z": round(z_ls, 3),
                    "part": round(ls_part, 3),
                }

            fr_annual, fr_ts = self._query_funding_rate_annualized()
            if fr_annual is not None and fr_ts is not None and now - fr_ts < _STALE_SEC:
                # 资金费率年化(%); 正高拥挤 → 空头力量
                fr_part = max(-1.0, min(1.0, fr_annual / 30.0))
                components["funding_rate"] = {
                    "annual_pct": round(fr_annual, 3),
                    "part": round(fr_part, 3),
                }

            # ── 主动买卖比（OKX taker_volume）──
            taker = self._query_latest("okx_derivatives", "taker_buy_sell_ratio")
            if taker is not None and now - taker[1] < _STALE_SEC:
                ratio = float(taker[0])
                # ratio > 1 → 主动买入占优 → 多头力量(负); < 1 → 主动卖出 → 空头(正)
                taker_part = max(-1.0, min(1.0, -(ratio - 1.0) / 1.0))
                components["taker_buy_sell_ratio"] = {
                    "ratio": round(ratio, 4),
                    "part": round(taker_part, 3),
                }
            else:
                taker_part = None

            oi = self._query_open_interest(symbol)
            if (
                oi is not None
                and now - oi["timestamp"] < _STALE_SEC
                and oi["change_pct_24h"] is not None
            ):
                oi_available = True
                crowding_sign = 0.0
                if ls_value is not None:
                    crowding_sign = 1.0 if ls_value > 1.05 else (-1.0 if ls_value < 0.95 else 0.0)
                elif fr_part is not None:
                    crowding_sign = 1.0 if fr_part > 0 else (-1.0 if fr_part < 0 else 0.0)
                if crowding_sign != 0.0:
                    oi_part = crowding_sign * self._clamp01(abs(float(oi["change_pct_24h"])) / 0.20)
                components["open_interest"] = {
                    "open_interest": oi["open_interest"],
                    "change_pct_24h": round(float(oi["change_pct_24h"]), 6),
                    "part": round(oi_part, 3) if oi_part is not None else None,
                }

            liq = self._query_liquidation_24h(symbol)
            if liq is not None and liq["liq_total"] > 0:
                liq_part = (liq["liq_long"] - liq["liq_short"]) / liq["liq_total"]
                components["liquidation"] = {
                    "liq_long": liq["liq_long"],
                    "liq_short": liq["liq_short"],
                    "liq_total": liq["liq_total"],
                    "part": round(liq_part, 3),
                }

            coverage = round(
                sum(
                    (
                        ls_part is not None,
                        fr_part is not None,
                        taker_part is not None,
                        oi_available,
                        liq_part is not None,
                    )
                )
                / 5.0,
                3,
            )

            from dreambuddy_evolution.agi_config import get_switch

            if get_switch("enable_d2_oi_liq", False):
                weighted = []
                for part, weight in (
                    (ls_part, 0.30),
                    (fr_part, 0.20),
                    (taker_part, 0.15),
                    (oi_part, 0.20),
                    (liq_part, 0.15),
                ):
                    if part is not None:
                        weighted.append((part, weight))
                raw = (
                    sum(part * weight for part, weight in weighted)
                    / sum(weight for _, weight in weighted)
                    if weighted
                    else None
                )
            else:
                legacy = [part for part in (ls_part, fr_part, taker_part) if part is not None]
                raw = sum(legacy) / len(legacy) if legacy else None

            if raw is None:
                out = self._neutral("flow-stale-or-missing")
                out.update({"coverage": coverage, "components": components, "symbol": symbol})
                return out

            direction = "short" if raw > 0.15 else ("long" if raw < -0.15 else "neutral")
            strength = self._clamp01(abs(raw))
            return {
                "direction": direction,
                "strength": round(strength, 3),
                "raw_z": round(raw, 3),
                "degraded": None,
                "coverage": coverage,
                "components": components,
                "symbol": symbol,
            }
        except Exception as e:
            logger.debug("[DimensionForce] D2 fail: %s", e)
            out = self._neutral("d2-error")
            out.update({"coverage": 0.0, "components": {}, "symbol": symbol})
            return out

    def d2_coverage(self, symbol: str | None = None) -> dict[str, Any]:
        """D2 数据覆盖状态（只读监控）."""
        out = self.evaluate_d2(symbol)
        return {
            "symbol": out.get("symbol"),
            "coverage": out.get("coverage", 0.0),
            "components": out.get("components", {}),
        }

    # ------------------------------------------------------------------
    # D4 市场情绪维度
    # ------------------------------------------------------------------
    def evaluate_d4(self) -> dict[str, Any]:
        """市场情绪 → 极端情绪反转力量.

        主信号: 恐惧贪婪指数（<25 极度恐惧→多头反转; >75 极度贪婪→空头回调）.
        增强: 恐惧贪婪处于中性区间(25-75)时，用期权 put/call ratio 提供方向:
          PCR > 1 → 看跌期权占优 → 空头; PCR < 1 → 看涨占优 → 多头.
        """
        try:
            now = int(time.time())
            fg = self._query_latest("crypto_fear_greed", "value")
            if fg is None or now - fg[1] > _STALE_SEC:
                # 恐惧贪婪缺失时，尝试 put/call ratio 独立提供方向
                return self._d4_from_put_call()
            v = fg[0]  # 0-100
            if v < 25:
                raw = (25 - v) / 25.0
                return {
                    "direction": "long",
                    "strength": round(self._clamp01(abs(raw)), 3),
                    "raw_z": round(-raw, 3),
                    "degraded": None,
                }
            if v > 75:
                raw = (v - 75) / 25.0
                return {
                    "direction": "short",
                    "strength": round(self._clamp01(raw), 3),
                    "raw_z": round(raw, 3),
                    "degraded": None,
                }
            # 中性区间 → 用 put/call ratio 提供方向
            return self._d4_from_put_call(fallback_degraded="fear-greed-mid-range")
        except Exception as e:
            logger.debug("[DimensionForce] D4 fail: %s", e)
            return self._neutral("d4-error")

    def _d4_from_put_call(self, fallback_degraded: str = "put-call-ratio") -> dict[str, Any]:
        """从期权 put/call ratio 推导情绪方向（D4 中性区间增强）."""
        try:
            now = int(time.time())
            pcr = self._query_latest("options", "put_call_ratio")
            if pcr is None or now - pcr[1] > _STALE_SEC:
                return self._neutral(fallback_degraded)
            ratio = float(pcr[0])
            # PCR > 1 → 看跌期权多 → 空头; < 1 → 看涨多 → 多头
            # 以 1.0 为中性轴，±0.5 映射到 ±1
            raw = max(-1.0, min(1.0, (ratio - 1.0) / 0.5))
            direction = "short" if raw > 0.1 else ("long" if raw < -0.1 else "neutral")
            return {
                "direction": direction,
                "strength": round(self._clamp01(abs(raw)), 3),
                "raw_z": round(raw, 3),
                "put_call_ratio": round(ratio, 4),
                "degraded": fallback_degraded,
            }
        except Exception:
            return self._neutral(fallback_degraded)

    # ------------------------------------------------------------------
    # C6 估值维度（第二阶段扩展）
    # ------------------------------------------------------------------
    def evaluate_c6(self) -> dict[str, Any]:
        """BTC 市值 z-score → 估值维度力量.

        逻辑: 市值处于历史高位（z 高）→ 估值贵 → 回调空头力量;
              市值处于历史低位（z 低）→ 估值便宜 → 配置多头力量.
        """
        try:
            now = int(time.time())
            mc = self._query_latest("bitcoin", "market_cap_usd")
            if mc is None or now - mc[1] > _STALE_SEC:
                return self._neutral("valuation-stale-or-missing")
            hist = [v for v, _ in self._query_history("bitcoin", "market_cap_usd", self.WINDOW_D4)]
            if len(hist) < 10:
                return self._neutral("valuation-insufficient-history")
            z = self._zscore(mc[0], hist)
            raw = max(-1.0, min(1.0, z / 2.0))  # z 高 → 估值贵 → 空头
            direction = "short" if raw > 0.15 else ("long" if raw < -0.15 else "neutral")
            return {
                "direction": direction,
                "strength": round(self._clamp01(abs(raw)), 3),
                "raw_z": round(raw, 3),
                "degraded": None,
            }
        except Exception as e:
            logger.debug("[DimensionForce] C6 fail: %s", e)
            return self._neutral("c6-error")

    # ------------------------------------------------------------------
    # C7 叙事维度（第二阶段扩展）
    # ------------------------------------------------------------------
    def evaluate_c7(self) -> dict[str, Any]:
        """隐性资金流/广度力量.

        信号1（稳定币）: USDT+USDC 流通量 7 日变化率.
          总量上升 → 场外资金入场 → 多头; 下降 → 离场 → 空头.
        信号2（交易所BTC余额）: 交易所 BTC 余额 30 日变化率.
          余额下降 → 囤积(提币离场) → 多头; 上升 → 抛售压力 → 空头.
        两信号等权合成.
        """
        try:
            now = int(time.time())
            parts: list[float] = []
            components: dict[str, Any] = {}

            # ── 信号1: 稳定币流通量 7d 变化 ──
            usdt = self._query_latest("stablecoin_hist_usdt", "circulating_usd_bln")
            usdc = self._query_latest("stablecoin_hist_usdc", "circulating_usd_bln")
            if (
                usdt is not None
                and usdc is not None
                and now - usdt[1] < _STALE_SEC
                and now - usdc[1] < _STALE_SEC
            ):
                total_now = usdt[0] + usdc[0]
                cutoff = now - 7 * 24 * 3600
                hist_usdt = [
                    (v, t)
                    for v, t in self._query_history(
                        "stablecoin_hist_usdt", "circulating_usd_bln", 30 * 24 * 3600
                    )
                    if t <= cutoff
                ]
                hist_usdc = [
                    (v, t)
                    for v, t in self._query_history(
                        "stablecoin_hist_usdc", "circulating_usd_bln", 30 * 24 * 3600
                    )
                    if t <= cutoff
                ]
                if hist_usdt and hist_usdc and total_now > 0:
                    total_7d_ago = hist_usdt[-1][0] + hist_usdc[-1][0]
                    if total_7d_ago > 0:
                        chg_pct = (total_now / total_7d_ago - 1.0) * 100
                        sc_part = max(-1.0, min(1.0, chg_pct / 1.0))
                        parts.append(sc_part)
                        components["stablecoin_supply_7d"] = {
                            "chg_pct": round(chg_pct, 3),
                            "part": round(sc_part, 3),
                        }

            # ── 信号2: 交易所 BTC 余额 30d 变化 ──
            ex_chg = self._query_latest("exchanges_whales", "ex_bal_BTC_chg30d_pct")
            if ex_chg is not None and now - ex_chg[1] < _STALE_SEC:
                chg = float(ex_chg[0])
                # 余额下降 = 囤积 = 多头(正); 上升 = 抛售 = 空头(负)
                ex_part = max(-1.0, min(1.0, -chg / 2.0))
                parts.append(ex_part)
                components["exchange_btc_balance_30d"] = {
                    "chg_pct": round(chg, 3),
                    "part": round(ex_part, 3),
                }

            if not parts:
                return self._neutral("c7-insufficient-data")

            raw = sum(parts) / len(parts)
            direction = "long" if raw > 0.1 else ("short" if raw < -0.1 else "neutral")
            return {
                "direction": direction,
                "strength": round(self._clamp01(abs(raw)), 3),
                "raw_z": round(raw, 3),
                "degraded": None,
                "components": components,
            }
        except Exception as e:
            logger.debug("[DimensionForce] C7 fail: %s", e)
            return self._neutral("c7-error")

    # ------------------------------------------------------------------
    # C8 宏观交叉维度（40 域跨市场信号 + VIX fallback）
    # ------------------------------------------------------------------
    def _load_40_cross_asset_matrix(self) -> dict | None:
        """读取 40 域 cross_asset_matrix.json（跨市场动量/相关性）."""
        import json

        path = (
            Path(__file__).resolve().parents[3] / "40-周期神经网络系统" / "cross_asset_matrix.json"
        )
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            # 新鲜度校验: generated_at 超过 7 天视为陈旧
            gen_at = data.get("generated_at")
            if gen_at:
                from datetime import datetime

                try:
                    ts = int(datetime.fromisoformat(gen_at.replace("Z", "+00:00")).timestamp())
                    if int(time.time()) - ts > _STALE_SEC:
                        return None
                except Exception:
                    pass
            return data
        except Exception:
            return None

    def evaluate_c8(self) -> dict[str, Any]:
        """宏观交叉 → 跨市场风险偏好力量.

        主信号（40 域 cross_asset_matrix）:
          取 BTC 之外宏观资产（XAU/CL/US500/JP225/TLT）的 3M 动量，
          按其与 BTC 的 corr0 加权求和 → 宏观动量信号:
            正（宏观资产集体走强且与 BTC 同向）→ 风险偏好充裕 → 多头;
            负（宏观资产集体走弱）→ 风险偏好收缩 → 空头.
          MA200 上下比例作趋势确认（30% 权重）。

        Fallback: VIX z-score（VIX 高→恐慌→空头）。
        """
        try:
            now = int(time.time())
            matrix = self._load_40_cross_asset_matrix()
            if matrix is not None:
                assets = matrix.get("assets", {})
                weighted_momentum = 0.0
                weight_sum = 0.0
                above = below = 0
                for name, a in assets.items():
                    if name == "BTC":
                        continue
                    mom = a.get("momentum_3m_pct")
                    corr = a.get("corr0")
                    if mom is None or corr is None:
                        continue
                    w = abs(corr)
                    weighted_momentum += mom * corr  # corr 带符号: 正相关同向, 负相关反向
                    weight_sum += w
                    ma = a.get("above_ma200")
                    if ma is True:
                        above += 1
                    elif ma is False:
                        below += 1

                if weight_sum > 0:
                    macro_mom = weighted_momentum / weight_sum
                    raw = max(-1.0, min(1.0, macro_mom / 10.0))  # ±10% 动量 → ±1
                    n_ma = above + below
                    if n_ma > 0:
                        ma_ratio = (above - below) / n_ma  # [-1, 1]
                        raw = raw * 0.7 + ma_ratio * 0.3  # 动量 70%, 趋势 30%
                    direction = "short" if raw < -0.1 else ("long" if raw > 0.1 else "neutral")
                    return {
                        "direction": direction,
                        "strength": round(self._clamp01(abs(raw)), 3),
                        "raw_z": round(raw, 3),
                        "macro_momentum_pct": round(macro_mom, 2),
                        "n_macro_assets": round(weight_sum, 3),
                        "degraded": None,
                    }
                # matrix 存在但无有效资产 → 降级到 VIX
                logger.debug("[DimensionForce] C8 matrix no valid assets, fallback to VIX")

            # ── Fallback: VIX z-score ──
            vix = self._query_latest("^VIX", "value")
            if vix is None or now - vix[1] > _STALE_SEC:
                return self._neutral("c8-stale-or-missing")
            hist = [v for v, _ in self._query_history("^VIX", "value", self.WINDOW_D4)]
            if len(hist) < 10:
                return self._neutral("c8-vix-insufficient-history")
            z = self._zscore(vix[0], hist)
            raw = max(-1.0, min(1.0, z / 2.0))
            direction = "short" if raw > 0.15 else ("long" if raw < -0.15 else "neutral")
            return {
                "direction": direction,
                "strength": round(self._clamp01(abs(raw)), 3),
                "raw_z": round(raw, 3),
                "degraded": "vix-fallback",
            }
        except Exception as e:
            logger.debug("[DimensionForce] C8 fail: %s", e)
            return self._neutral("c8-error")

    # ------------------------------------------------------------------
    # news 信息面维度（第二阶段扩展）
    # ------------------------------------------------------------------
    def evaluate_news(self) -> dict[str, Any]:
        """快讯频率 z-score → 信息流强度（事件驱动代理）.

        逻辑: 快讯频率激增（z 高）→ 重大事件期 → 波动放大 → 谨慎（空头偏向）;
              快讯频率正常 → 无事件 → 中性.
        """
        try:
            now = int(time.time())
            day_sec = 24 * 3600
            # 近 24h 快讯数 vs 前 7 日日均
            with self._connect() as conn:
                cnt_24h = conn.execute(
                    "SELECT COUNT(DISTINCT sub_category) FROM mm_metrics "
                    "WHERE source='odaily_newsflash' AND timestamp > ?",
                    (now - day_sec,),
                ).fetchone()[0]
                cnt_7d = conn.execute(
                    "SELECT COUNT(DISTINCT sub_category) FROM mm_metrics "
                    "WHERE source='odaily_newsflash' AND timestamp > ? AND timestamp <= ?",
                    (now - 8 * day_sec, now - day_sec),
                ).fetchone()[0]
            if cnt_7d <= 0:
                return self._neutral("news-no-baseline")
            daily_avg = cnt_7d / 7.0
            if daily_avg < 1:
                return self._neutral("news-low-baseline")
            ratio = cnt_24h / daily_avg
            raw = max(-1.0, min(1.0, (ratio - 1.0) / 1.0))  # 频率翻倍 → 满强度
            direction = "short" if raw > 0.3 else "neutral"  # 信息激增 → 谨慎偏向
            return {
                "direction": direction,
                "strength": round(self._clamp01(abs(raw)), 3),
                "raw_z": round(raw, 3),
                "degraded": None,
            }
        except Exception as e:
            logger.debug("[DimensionForce] news fail: %s", e)
            return self._neutral("news-error")

    # ------------------------------------------------------------------
    # 双源交叉校验（P1: 本地基本面模块第二数据源）
    # ------------------------------------------------------------------
    def _get_fundamental_provider(self) -> Any:
        """懒加载本地基本面分析模块的 DalSnapshotProvider（第二数据源）."""
        provider = getattr(self, "_fundamental_provider", None)
        if provider is not None:
            return provider if provider is not False else None
        try:
            import sys
            from pathlib import Path

            fb_dir = Path(__file__).resolve().parents[3] / "9-基本面分析"
            if str(fb_dir) not in sys.path:
                sys.path.insert(0, str(fb_dir))
            from dal_snapshot_provider import DalSnapshotProvider

            provider = DalSnapshotProvider()
            self._fundamental_provider = provider
            return provider
        except Exception as e:
            logger.debug("[DimensionForce] fundamental provider init fail: %s", e)
            self._fundamental_provider = False
            return None

    def cross_check_fundamental(self, forces: dict[str, dict[str, Any]]) -> dict[str, Any]:
        """用本地基本面模块的 sentiment 分数交叉校验各维度方向.

        本地基本面模块（9-基本面分析）的 10 个采集方法各自输出标准化
        sentiment ∈ [-1,1]，与八维矛盾体系一一对应。此方法将两源对比，
        输出一致/分歧标记，供影子期观察两源收敛性。
        """
        provider = self._get_fundamental_provider()
        if provider is None:
            return {"available": False, "note": "fundamental-provider-unavailable"}
        # 维度 → 基本面模块采集方法映射
        dim_to_collector = {
            "D1": "collect_macro",  # C4 宏观
            "D2": "collect_flow",  # C1 资金面
            "D3": "collect_onchain",  # C3 技术面(链上)
            "D4": "collect_sentiment",  # C2 情绪面
            "C6": "collect_valuation",  # C6 估值
            "C7": "collect_breadth",  # C7 隐性/广度
            "C8": "collect_intermarket",  # C8 宏观交叉
            "NEWS": "collect_news",  # news 信息面
        }
        result: dict[str, Any] = {"available": True}
        for dim, collector_name in dim_to_collector.items():
            try:
                method = getattr(provider, collector_name, None)
                if method is None:
                    result[dim] = {"fund_sentiment": None, "agree": None}
                    continue
                data = method()
                if not isinstance(data, dict):
                    result[dim] = {"fund_sentiment": None, "agree": None}
                    continue
                # 提取 events 中的 sentiment（各采集方法的标准化输出）
                events = data.get("events") or []
                sentiments = [
                    float(e.get("sentiment", 0.0))
                    for e in events
                    if isinstance(e, dict) and e.get("sentiment") is not None
                ]
                fund_sent = sum(sentiments) / len(sentiments) if sentiments else None
                # 与主源对比
                my_force = forces.get(dim) or {}
                my_dir = my_force.get("direction", "neutral")
                my_strength = float(my_force.get("strength", 0.0))
                if fund_sent is None or abs(fund_sent) < 0.05 or my_strength < 0.05:
                    agree = None  # 任一源中性，无法判定一致性
                else:
                    fund_dir = "long" if fund_sent > 0 else "short"
                    agree = fund_dir == my_dir
                result[dim] = {
                    "fund_sentiment": round(fund_sent, 3) if fund_sent is not None else None,
                    "my_direction": my_dir,
                    "my_strength": round(my_strength, 3),
                    "agree": agree,
                }
            except Exception as e:
                logger.debug("[DimensionForce] cross_check %s fail: %s", dim, e)
                result[dim] = {"fund_sentiment": None, "agree": None, "error": str(e)[:50]}
        return result

    def format_cross_check_log(self, cross: dict[str, Any]) -> str:
        """[DimensionForce-XCheck] 交叉校验日志行."""
        if not cross.get("available"):
            return "[DimensionForce-XCheck] fundamental-provider-unavailable"
        parts = []
        for dim in ("D1", "D2", "D3", "D4", "C6", "C7", "C8", "NEWS"):
            info = cross.get(dim) or {}
            fs = info.get("fund_sentiment")
            agree = info.get("agree")
            agree_str = {True: "✓", False: "✗", None: "-"}.get(agree, "-")
            fs_str = f"{fs:+.2f}" if fs is not None else "n/a"
            parts.append(f"{dim}:{fs_str}{agree_str}")
        return "[DimensionForce-XCheck] " + " ".join(parts)

    # ------------------------------------------------------------------
    # 总入口
    # ------------------------------------------------------------------
    def evaluate(
        self,
        d3: dict[str, Any] | None = None,
        symbol: str | None = None,
    ) -> dict[str, dict[str, Any]]:
        """评估全部维度（8 维完整体系）. d3 由调用方传入（现有路径共振结果）."""
        result = {
            "D1": self.evaluate_d1(),  # C4 宏观
            "D2": self.evaluate_d2(symbol),  # C1 资金面
            "D4": self.evaluate_d4(),  # C2 情绪面
            "C6": self.evaluate_c6(),  # C6 估值
            "C7": self.evaluate_c7(),  # C7 叙事（稳定币）
            "C8": self.evaluate_c8(),  # C8 宏观交叉（40域跨市场信号+VIX fallback）
            "NEWS": self.evaluate_news(),  # news 信息面
        }
        result["D3"] = d3 or self._neutral("d3-not-provided")  # C3 技术面
        return result

    def format_log(self, forces: dict[str, dict[str, Any]]) -> str:
        """[DimensionForce] 日志行（8 维完整）."""
        parts = []
        for dim in ("D1", "D2", "D3", "D4", "C6", "C7", "C8", "NEWS"):
            f = forces.get(dim) or {}
            parts.append(f"{dim}={f.get('direction', '?')}:{f.get('strength', 0):.2f}")
        return "[DimensionForce] " + " ".join(parts)
