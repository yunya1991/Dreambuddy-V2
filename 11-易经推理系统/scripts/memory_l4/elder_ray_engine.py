# ================================================================
# Elder-ray 日线观察器（Alexander Elder 1993 原典实现）
#
# Spec §三：架构定位 / 三重结构 / 五级判定 / 3×5 决策矩阵 / F1-F5 铁则
# Phase1 约束（G5 红线）：multiplier_actual 恒=1.00，仅把预测值记录到日志/增强信息，
#                       绝不实际介入仓位乘法链（零侵入）。
# 缓存（G4 红线）：日线 EMA 计算 TTL=86400s（24h），同 symbol 4H 主周期内
#                  绝不重复请求 OKX 日线 K 线。
# Fail-open（G2 / Spec F5 / E2）：任何异常 → 返回 NEUTRAL + 1.00，不阻塞主流程。
# ================================================================
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


EMA13_ALPHA = 2.0 / (13 + 1)        # ≈ 0.142857（Elder 原典固定，不允许配置化修改）
SLOPE_NOISE_BPS_PCT = 0.003         # 0.3%/日 防噪阈值（Spec §三.2.1 保留 v1.1）
CACHE_TTL_MS = 86400 * 1000         # 24h（Spec E3 ≥12h 建议上限）

# ──────── 3×5 决策矩阵（Spec §3.3 表）────────
# 行：P1 输出（"STANDARD" / "WEAK" / "BLOCK"）
# 列：Elder 五级判定（ALIGN_FULL ~ DIVERGE_SEVERE）
# 值：Tuple[multiplier_predicted: Optional[float], action_tag: str]
#   None multiplier = 矩阵建议 BLOCK（仅 F3 唯一场景：WEAK + DIVERGE_SEVERE）
DECISION_MATRIX_3X5: Dict[str, Dict[str, Tuple[Optional[float], str]]] = {
    "STANDARD": {
        "ALIGN_FULL":       (1.15, "PREMIUM +15% (Full alignment)"),
        "ALIGN_BASIC":      (1.00, "HOLD"),
        "NEUTRAL":          (1.00, "HOLD"),
        "DIVERGE_BASIC":    (0.70, "DOWNGRADE -30% (weak counter-signal)"),
        "DIVERGE_SEVERE":   (0.55, "STRONG_DOWNGRADE -45% (severe counter)"),
    },
    "WEAK": {
        "ALIGN_FULL":       (0.80, "UPGRADE → HALF_STANDARD ×0.80 (≠1.0, F2 safety)"),
        "ALIGN_BASIC":      (0.40, "HOLD (original WEAK size)"),
        "NEUTRAL":          (0.40, "HOLD (original WEAK size)"),
        "DIVERGE_BASIC":    (0.30, "FURTHER_SHRINK_25% (from 0.40 → 0.30)"),
        "DIVERGE_SEVERE":   (None, "DOWNGRADE_TO_BLOCK (F3 UNIQUE SCENARIO)"),
    },
    # BLOCK: F1 铁则，永远不推翻。此表用于 BLOCK 时，调用方应直接 BLOCK，不经过 Elder。
    #        此处作为 fail-safe fallback，全标记 F1_RESPECT_BLOCK。
    "BLOCK": {
        "ALIGN_FULL":       (None, "F1_RESPECT_BLOCK"),
        "ALIGN_BASIC":      (None, "F1_RESPECT_BLOCK"),
        "NEUTRAL":          (None, "F1_RESPECT_BLOCK"),
        "DIVERGE_BASIC":    (None, "F1_RESPECT_BLOCK"),
        "DIVERGE_SEVERE":   (None, "F1_RESPECT_BLOCK"),
    },
}


@dataclass
class ElderRayResult:
    """Elder-ray 计算结果。

    注意 Phase1 语义约束：`multiplier_actual` 永远 = 1.00（G5 红线）；
    `multiplier_predicted` 仅做预测记录供 Phase2 回测校准对比，绝不进入实盘仓位乘法。
    """
    slope_ema13_pct: float              # (EMA_today - EMA_yesterday) / EMA_yesterday 原始百分比/日
    bull_power: float                   # High - EMA13（多头力量，正值=买方把价格推到共识之上）
    bear_power: float                   # Low - EMA13（空头力量，负值=卖方把价格压到共识之下）
    slope_state: str                    # "SLOPE_UP" / "SLOPE_DOWN" / "SLOPE_NEUTRAL"（防噪后）
    judge_level: str                    # ALIGN_FULL / ALIGN_BASIC / NEUTRAL / DIVERGE_BASIC / DIVERGE_SEVERE
    multiplier_predicted: float         # 3×5 矩阵预测值（仅记录；None=建议 BLOCK，此处占位 1.0）
    multiplier_actual: float            # Phase1 = 1.00（强制 G5），Phase2 才会介入乘法链
    action_tag: str                     # 人类友好动作标签（日志可读）
    # 三个持仓预警标签（仅供记录/离场层参考，Phase1 不触发任何动作=Spec F4/E6 铁则）：
    bull_loss_control: bool = False     # 做空持仓：Bull<0 → 多头失控（对手完全凌驾）
    bear_loss_control: bool = False     # 做多持仓：Bear>0 → 空头失控（对手完全凌驾）
    both_weakening: bool = False        # 双方减弱：Bull>0 连降3日 & Bear<0 连升3日 → 即将变盘
    fail_open_triggered: bool = False   # True = 本次结果为 fail-open 中性兜底


class ElderRayEngine:
    """Elder-ray 日线观察器。Phase1: fail-open + 24h TTL cache + G5 恒 1.00。"""

    def __init__(self, enable: bool = False):
        self.enable = bool(enable)
        # 缓存 key = f"{symbol}::{YYYYMMDD}"，避免跨日重复计算；value = (cache_ts_ms, result)
        self._cache: Dict[str, Tuple[int, ElderRayResult]] = {}

    # ──────── fail-open neutral（Spec F5 / E2 红线）────────
    def _neutral_result(self, reason: str = "") -> ElderRayResult:
        return ElderRayResult(
            slope_ema13_pct=0.0,
            bull_power=0.0,
            bear_power=0.0,
            slope_state="SLOPE_NEUTRAL",
            judge_level="NEUTRAL",
            multiplier_predicted=1.0,
            multiplier_actual=1.0,
            action_tag=f"FAIL_OPEN_NEUTRAL: {reason}",
            fail_open_triggered=True,
        )

    # ──────── 核心数值计算（三指标：EMA13/Bull/Bear，原典公式）────────
    @staticmethod
    def _calc_ema_bull_bear(daily_klines: List[Dict[str, float]]) -> Tuple[float, float, float, float]:
        """从 daily_klines（≥30 根，oldest first）返回 (ema13_curr, ema13_prev_day, bull, bear).

        抛出 ValueError 如果样本不足 30 → 调用方捕获 → fail-open neutral。
        计算策略：首值 S_0 = closes[-30]（EMA burn-in 起点），
        前 27 步 warmup 收敛到 bar index=-3，再 2 步真实迭代（-2→-1）得到
        前一日 EMA（prev_day = closes[-2] 对应）与今日 EMA（curr = closes[-1] 对应）。
        """
        n = len(daily_klines)
        if n < 30:
            raise ValueError(f"[ElderRay] need >=30 daily bars for stable EMA13, got {n}")
        closes: List[float] = [float(k["c"]) for k in daily_klines]
        # ── 28 步 warmup（索引 -30 … -3）──
        ema = closes[-30]
        for i in range(-29, -2):  # = 27 steps → i 到 -3
            ema = EMA13_ALPHA * closes[i] + (1.0 - EMA13_ALPHA) * ema
        # ── bar [-2] → 昨日 EMA ──
        ema = EMA13_ALPHA * closes[-2] + (1.0 - EMA13_ALPHA) * ema
        ema_prev_day = ema
        # ── bar [-1] → 今日 EMA ──
        ema_curr = EMA13_ALPHA * closes[-1] + (1.0 - EMA13_ALPHA) * ema
        bull = float(daily_klines[-1]["h"]) - ema_curr
        bear = float(daily_klines[-1]["l"]) - ema_curr
        return ema_curr, ema_prev_day, bull, bear

    @staticmethod
    def _slope_state(slope_pct: float) -> str:
        if slope_pct >= SLOPE_NOISE_BPS_PCT:
            return "SLOPE_UP"
        if slope_pct <= -SLOPE_NOISE_BPS_PCT:
            return "SLOPE_DOWN"
        return "SLOPE_NEUTRAL"

    @staticmethod
    def _detect_divergence_last_5(daily_klines: List[Dict[str, float]],
                                  bull_latest: float, bear_latest: float,
                                  ema_latest: float) -> Dict[str, bool]:
        """5 日滚动窗口（Spec §3.2.3）：看跌背离 / 看涨背离 / 双方减弱 3 日趋势。

        返回 dict：bearish, bullish, bull_desc_3d, bear_asc_3d。
        用 EMA_latest 近似前 4 日 EMA 相对判断（误差不影响 5 日相对方向判断，
        Elder 原典中背离判断本质是相对结构而非精确数值）。
        """
        if len(daily_klines) < 5:
            return {"bearish": False, "bullish": False,
                    "bull_desc_3d": False, "bear_asc_3d": False}
        last5 = daily_klines[-5:]
        highs = [float(k["h"]) for k in last5]
        lows = [float(k["l"]) for k in last5]
        # 近似 Bull/Bear 序列（用于 5 日相对结构）
        bulls = [h - ema_latest for h in highs]
        bears = [l - ema_latest for l in lows]

        # 看跌背离：最新 High 创 5 日新高，但 Bull 没创新高（价格新高无能量新高）
        bearish = (highs[-1] >= max(highs[:-1])) and (bulls[-1] < max(bulls[:-1]))
        # 看涨背离：最新 Low 创 5 日新低，但 Bear 没创新低（价格新低无能量新低）
        bullish = (lows[-1] <= min(lows[:-1])) and (bears[-1] > min(bears[:-1]))

        # 双方减弱：Bull>0 连续 3 日下降；Bear<0 连续 3 日上升
        def _desc3_positive(vals: List[float]) -> bool:
            return (len(vals) >= 3 and vals[-1] < vals[-2] < vals[-3]
                    and all(v > 0 for v in vals[-3:]))
        def _asc3_negative(vals: List[float]) -> bool:
            return (len(vals) >= 3 and vals[-1] > vals[-2] > vals[-3]
                    and all(v < 0 for v in vals[-3:]))
        return {
            "bearish": bool(bearish),
            "bullish": bool(bullish),
            "bull_desc_3d": _desc3_positive(bulls),
            "bear_asc_3d": _asc3_negative(bears),
        }

    @staticmethod
    def _judge_5level(decision: str, slope_state: str, bull: float, bear: float,
                      div: Dict[str, bool]) -> str:
        """五级判定（Spec §3.2.4）。decision: "LONG" / "SHORT"。

        判定优先级（从高到低，先判反信极端，再判前提，再判一致）：
          ① DIVERGE_SEVERE：斜率反 + 对手力量负值/正值（失控）
          ② 斜率前提不满足 → 最高仅 ALIGN_BASIC（原典规则），或 DIVERGE_BASIC / NEUTRAL
          ③ 斜率前提满足 → ALIGN_FULL（含背离）/ ALIGN_BASIC / DIVERGE_BASIC / NEUTRAL
        """
        direction = str(decision).upper()[:1]  # L / S
        if direction == "L":
            prem_ok = (slope_state == "SLOPE_UP")
            align_basic = (bear < 0) and (bull > 0)
            align_full_cond = prem_ok and align_basic and bool(div.get("bullish"))
            severe = (slope_state == "SLOPE_DOWN") and (bear > 0)  # 空头完全凌驾
        else:  # SHORT（或未知，保守按 SHORT 对称）
            prem_ok = (slope_state == "SLOPE_DOWN")
            align_basic = (bull > 0) and (bear < 0)
            align_full_cond = prem_ok and align_basic and bool(div.get("bearish"))
            severe = (slope_state == "SLOPE_UP") and (bull < 0)  # 多头完全凌驾

        if severe:
            return "DIVERGE_SEVERE"
        if not prem_ok:
            # 原典前提不满足：最高只能到 ALIGN_BASIC（若结构仍有一致）
            if align_basic:
                return "ALIGN_BASIC"
            # 前提反 + 对手也没失控 → 基本反信 or 中性
            if (direction == "L" and bull < 0) or (direction == "S" and bear > 0):
                return "DIVERGE_BASIC"
            return "NEUTRAL"
        # 前提 OK（L→SLOPE_UP，S→SLOPE_DOWN）
        if align_full_cond:
            return "ALIGN_FULL"
        if align_basic:
            return "ALIGN_BASIC"
        if (direction == "L" and bull < 0) or (direction == "S" and bear > 0):
            return "DIVERGE_BASIC"
        return "NEUTRAL"

    # ──────── 外部主入口（供 polling_trader 调用）────────
    def calc_and_record(self, symbol: str, decision: str, p1_output: str,
                        daily_klines: Optional[List[Dict[str, float]]]) -> ElderRayResult:
        """计算 Elder-ray + 矩阵映射 + Phase1 G5 恒 1.00 旁路。

        Parameters
        ----------
        symbol : 交易对（用于缓存 key，内部只取 {symbol}::{today}）
        decision : "LONG" / "SHORT"（来自 BCRM 核心层方向）
        p1_output : "STANDARD" / "WEAK" / "BLOCK"（P1 大周期过滤输出）
            BLOCK → 立即 fail-open neutral（F1 铁则：永远不推翻 BLOCK）
        daily_klines : OKX 日线 K 线（≥30 根，oldest first）。None / <30 → fail-open。
        """
        # ── 快速路径（关断 / F1 BLOCK）────────
        if not self.enable:
            r = self._neutral_result("ENGINE_DISABLED_BYPASS")
            r.action_tag = "DISABLED → 1.00（Phase1 G1 字节等价）"
            return r
        p1 = str(p1_output).upper()
        if p1 == "BLOCK":
            return self._neutral_result("F1_P1_BLOCK_RESPECTED")

        # ── 24h TTL cache（G4）────────
        now_ms = int(time.time() * 1000)
        today_tag = time.strftime("%Y%m%d", time.localtime(now_ms / 1000))
        cache_key = f"{symbol}::{today_tag}"
        cached = self._cache.get(cache_key)
        if cached is not None and (now_ms - cached[0]) < CACHE_TTL_MS:
            return cached[1]

        # ── 日线不足 / 缺失 → fail-open（Spec E2）────────
        if daily_klines is None or len(daily_klines) < 30:
            r = self._neutral_result("NO_DAILY_KLINES_OR_TOO_SHORT")
        else:
            try:
                ema_curr, ema_prev_day, bull, bear = self._calc_ema_bull_bear(daily_klines)
                eps = 1e-12
                slope_pct = (ema_curr - ema_prev_day) / (abs(ema_prev_day) + eps)
                sst = self._slope_state(slope_pct)
                div = self._detect_divergence_last_5(daily_klines, bull, bear, ema_curr)
                level = self._judge_5level(decision, sst, bull, bear, div)
                # 3×5 矩阵查找
                row = DECISION_MATRIX_3X5.get(p1, DECISION_MATRIX_3X5["STANDARD"])
                mat = row.get(level, (1.0, f"UNKNOWN_LEVEL_FALLBACK({level})"))
                mult_pred, tag = mat
                if mult_pred is None:
                    # F3 唯一场景（WEAK+DIVERGE_SEVERE）→ 预测器建议 BLOCK，这里用 1.0 占位，
                    # 调用方应看 tag == "DOWNGRADE_TO_BLOCK" 决定（Phase1 仍强制 actual=1.0）
                    mult_pred = 1.0
                r = ElderRayResult(
                    slope_ema13_pct=round(slope_pct, 6),
                    bull_power=round(bull, 4),
                    bear_power=round(bear, 4),
                    slope_state=sst,
                    judge_level=level,
                    multiplier_predicted=float(mult_pred),
                    multiplier_actual=1.0,  # Phase1 G5 红线：恒=1.00（零侵入）
                    action_tag=tag,
                    bull_loss_control=(bull < 0),
                    bear_loss_control=(bear > 0),
                    both_weakening=bool(div.get("bull_desc_3d") and div.get("bear_asc_3d")),
                    fail_open_triggered=False,
                )
            except Exception as _e:  # noqa: BLE001（G2：任何异常 fail-open neutral）
                r = self._neutral_result(f"CALC_EXCEPTION:{type(_e).__name__}")

        self._cache[cache_key] = (now_ms, r)
        return r
