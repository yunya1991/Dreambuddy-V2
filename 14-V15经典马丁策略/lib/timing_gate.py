"""Phase 4 · TimingGate — 波浪三浪结构 + Fibonacci 回撤/扩展 时机「软评分」评估器

层级位置 (Tier 2):
    DirectionGate (方向判定 Tier 1)
        → TimingGate (时机软调控 Tier 2 · 本模块) 输出 timing_score ∈ [0,1]
            → EntryDecision / v15_decision (入场决策 Tier 3)
                    最终强度 = 技术指标信号强度 × timing_score
                    （仓位、入场金额、杠杆倍率都按比例缩放）

与原"硬门禁"设计的区别：
  ✅ 不再是 long_timing_ok/short_timing_ok 二元开关（虽然保留了兼容字段：score >= threshold 即算ok）
  ✅ 输出 timing_score 0~1 连续值：
       · 1.0  — F500 黄金回撤、三浪结构完美匹配方向、距离 EXT 尚远 → 满仓入场
       · 0.7~0.9 — F382 或 F618 边缘区（仍优秀，但不是最佳）
       · 0.3~0.6 — 回撤过浅 / 过深、结构 UNCLEAR 宽容放行 → 小仓位试探
       · 0~0.2  — 反向结构 或 超 EXT1618 追末端 → 几乎不让入场

概念工程化（避免 Elliott 1-5 浪主观标注，只取可量化的三浪结构）:
  BULLISH_3WAVE = L0(swing low) → H1(swing high) → L2(latest swing low)
        满足: L2 > L0 (higher low，未破前低)
        Wave1 = H1 - L0
        回撤 r = (H1 - L2) / Wave1
        扩展 EXT = L0 + Wave1 × 1.618 （现价越接近 EXT 分数越低）

  BEARISH_3WAVE = H0(swing high) → L1(swing low) → H2(latest swing high)
        满足: H2 < H0 (lower high，未破前高)
        Wave1 = H0 - L1
        反弹 r = (H2 - L1) / Wave1
        扩展 EXT = H0 - Wave1 × 1.618

三个独立维度分数相乘：
    timing_score = structure_match_score × retrace_quality_score × extension_chase_score
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

try:
    from .direction_gate import (
        GateResult,
        MarketRegime,
        SwingPoint,
        TradeDirection,
        detect_swing_points,
    )
except ImportError:
    from direction_gate import (
        SwingPoint,
        detect_swing_points,
    )


# --------------------------------------------------------------------------- #
# 数据结构
# --------------------------------------------------------------------------- #
@dataclass
class WaveStructure:
    """
    三浪结构描述。若 kind=UNCLEAR 则其他数值字段默认 0.0，不应使用。
    """

    kind: str = "UNCLEAR"  # BULLISH_3WAVE / BEARISH_3WAVE / UNCLEAR
    wave1_start: float = 0.0  # Bull:L0, Bear:H0
    wave1_end: float = 0.0  # Bull:H1, Bear:L1
    wave2_end: float = 0.0  # Bull:L2, Bear:H2
    wave1_range: float = 0.0  # abs(wave1_end - wave1_start)
    retrace_ratio: float = 0.0  # Bull: (H1-L2)/Wave1; Bear: (H2-L1)/Wave1
    ext_target: float = 0.0  # Bull: L0 + Wave1*fib_ext; Bear: H0 - Wave1*fib_ext
    raw_swings_used: int = 0  # 参与识别的 swing 点数（诊断用）


@dataclass
class TimingScoreBreakdown:
    """三维度软评分分解（诊断透传用）。所有值 ∈ [0,1]。"""

    structure_match: float = 1.0  # 结构 + DirectionGate 方向匹配程度
    retrace_quality: float = 1.0  # Fib 回撤位质量，黄金点 1.0，边缘递减
    extension_chase: float = 1.0  # 远离 EXT1618 追末端的安全度，越接近 EXT 越小


@dataclass
class TimingResult:
    """TimingGate 最终输出（软评分 + 向后兼容的 bool 阈值）。"""

    timing_score: float  # 核心输出：[0,1]，建议 技术指标强度 × timing_score
    long_timing_ok: bool  # 兼容：long_timing_score >= threshold
    short_timing_ok: bool  # 兼容：short_timing_score >= threshold
    structure: WaveStructure
    fib_zone: str  # F382 / F500 / F618 / EXT1618 / NONE
    score_breakdown: TimingScoreBreakdown
    reason: str  # 人类可读的理由（日志用）

    def to_diagnostic(self) -> Dict[str, Any]:
        """转成 dict，塞进 GateResult.mechanistic_diag["timing"]"""
        return {
            "timing_score": round(self.timing_score, 3),
            "long_timing_ok": self.long_timing_ok,
            "short_timing_ok": self.short_timing_ok,
            "structure": self.structure.kind,
            "fib_zone": self.fib_zone,
            "reason": self.reason,
            "wave1_start": round(self.structure.wave1_start, 4),
            "wave1_end": round(self.structure.wave1_end, 4),
            "wave2_end": round(self.structure.wave2_end, 4),
            "wave1_range": round(self.structure.wave1_range, 4),
            "retrace_ratio": round(self.structure.retrace_ratio, 3),
            "ext_target": round(self.structure.ext_target, 4),
            "breakdown": {
                "structure_match": round(self.score_breakdown.structure_match, 3),
                "retrace_quality": round(self.score_breakdown.retrace_quality, 3),
                "extension_chase": round(self.score_breakdown.extension_chase, 3),
            },
        }


# --------------------------------------------------------------------------- #
# Fib 回撤区间分类
# --------------------------------------------------------------------------- #
def classify_fib_zone(retrace_ratio: float, lo: float = 0.30, hi: float = 0.72) -> str:
    """
    把回撤比率 r（0..1，理论值）映射到最近的斐波那契区标签。
    仅当 r 在 [lo, hi] 范围内才可能命中 F382/F500/F618，否则返回 NONE。
    默认 lo=0.30, hi=0.72 → 边界：[0.30, 0.44]→F382；(0.44, 0.56]→F500；(0.56, 0.72]→F618
    非默认 lo/hi 时：三等分 [lo, hi]，1/3 点= F382/F500 边界，2/3 点= F500/F618 边界。
    """
    if retrace_ratio < lo or retrace_ratio > hi:
        return "NONE"
    span = max(1e-9, hi - lo)
    # [lo, lo+span/3] → F382；(lo+span/3, lo+span*2/3] → F500；否则 → F618
    b1 = lo + span / 3.0
    b2 = lo + span * 2.0 / 3.0
    if retrace_ratio <= b1 + 1e-9:
        return "F382"
    if retrace_ratio <= b2 + 1e-9:
        return "F500"
    return "F618"


def retrace_quality_score(
    r: float, lo: float = 0.30, hi: float = 0.72, mu: float = 0.5, sigma: float = 0.18
) -> float:
    """
    Fib 回撤位质量评分（0~1）。
      · r=0.500 (F500 黄金) → 1.00
      · r=0.382 / 0.618       → ~0.86  (经典强回撤位)
      · r=0.30 或 0.72 (边缘) → ~0.70  (仍允许进入，打 7 折)
      · r=0.10 (极浅)         → ~0.30  (几乎没回调)
      · r=0.90 (极深)         → ~0.30  (几乎把整个浪1吞掉)
    实现：以 mu 为顶点的对称高斯钟形，宽度 σ（默认 mu=0.5 / σ=0.18）
    """
    mu = float(mu)
    sigma = max(1e-6, float(sigma))
    # 在 [lo, hi] 之外额外惩罚（乘以线性衰减），防止 σ 放大时极值仍得高分
    base = max(0.0, min(1.0, math.exp(-0.5 * ((r - mu) / sigma) ** 2)))
    if r < lo:
        # 从 lo → -∞ 线性压到 0（距离 lo 每 0.25 宽度降一半）
        t = max(0.0, min(1.0, (lo - r) / max(0.25, (hi - lo) * 0.8)))
        base *= 1.0 - t
    elif r > hi:
        t = max(0.0, min(1.0, (r - hi) / max(0.25, (hi - lo) * 0.8)))
        base *= 1.0 - t
    return max(0.0, min(1.0, base))


def extension_chase_score(
    price_now: float,
    ext_target: float,
    wave1_range: float,
    structure_kind: str,
) -> float:
    """
    追 EXT 末端惩罚：距离 EXT1618 越近分数越低，越过 EXT 分数≤0.2。

    score = 1.0                                        当现价与 EXT 反向 ≥ Wave1
            线性降为 0.5                                当现价刚好到达 EXT
            线性降为 0.2                                当现价越过 EXT ≥ 0.3*Wave1
    """
    if wave1_range <= 0 or structure_kind == "UNCLEAR":
        return 1.0  # 无法比较时中立
    if structure_kind == "BULLISH_3WAVE":
        gap = ext_target - price_now  # 越大越安全（价格在EXT下方）
    else:  # BEARISH_3WAVE
        gap = price_now - ext_target  # 越大越安全（价格在EXT上方）
    # 基准宽度
    w = max(wave1_range, 1e-9)
    if gap >= w:
        return 1.0
    if gap >= 0:
        # gap/w 从 1 → 0 映射 1.0 → 0.5
        return 0.5 + 0.5 * (gap / w)
    # gap < 0：已越过 EXT，继续线性下降直到 -0.3w → 0.2
    over = -gap
    if over >= 0.3 * w:
        return 0.2
    return 0.5 - 0.3 * (over / (0.3 * w))


# --------------------------------------------------------------------------- #
# 三浪结构识别（纯函数，便于单元测试）
# --------------------------------------------------------------------------- #
def detect_three_wave_structure(
    swings_raw: List[Any], fib_ext_ratio: float = 1.618
) -> WaveStructure:
    """
    根据 swing 点列表构造最可能的三浪结构（只看最近 4 个 swing）。
    参数 swings_raw：接受 List[dict]（含 price/type）或 List[SwingPoint]。
    """
    # 统一转换为 dicts
    swings: List[Dict[str, float]] = []
    for s in swings_raw:
        if isinstance(s, dict):
            swings.append({"price": float(s["price"]), "type": str(s.get("type", "low"))})
        elif isinstance(s, SwingPoint):
            swings.append({"price": float(s.price), "type": str(s.type)})
        elif hasattr(s, "price") and hasattr(s, "type"):
            swings.append({"price": float(s.price), "type": str(s.type)})

    n = len(swings)
    if n < 3:
        return WaveStructure(kind="UNCLEAR", raw_swings_used=n)

    # 只用最近的 4 个 swing 点（更早期的是过时的结构）
    used = swings[-4:] if n >= 4 else swings

    # 辅助：尝试用 (p0, p1, p2) 构造 bull 或 bear
    def _try_bull(triplet: List[Dict[str, float]]) -> Optional[WaveStructure]:
        s0, s1, s2 = triplet
        if s0["type"] != "low" or s1["type"] != "high" or s2["type"] != "low":
            return None
        L0, H1, L2 = s0["price"], s1["price"], s2["price"]
        if not (L0 < H1 and L2 < H1 and L2 > L0):  # higher low
            return None
        wave1 = H1 - L0
        if wave1 <= 0:
            return None
        r = (H1 - L2) / wave1
        ext = L0 + wave1 * fib_ext_ratio
        return WaveStructure(
            kind="BULLISH_3WAVE",
            wave1_start=L0,
            wave1_end=H1,
            wave2_end=L2,
            wave1_range=wave1,
            retrace_ratio=r,
            ext_target=ext,
            raw_swings_used=len(used),
        )

    def _try_bear(triplet: List[Dict[str, float]]) -> Optional[WaveStructure]:
        s0, s1, s2 = triplet
        if s0["type"] != "high" or s1["type"] != "low" or s2["type"] != "high":
            return None
        H0, L1, H2 = s0["price"], s1["price"], s2["price"]
        if not (H0 > L1 and H2 > L1 and H2 < H0):  # lower high
            return None
        wave1 = H0 - L1
        if wave1 <= 0:
            return None
        r = (H2 - L1) / wave1
        ext = H0 - wave1 * fib_ext_ratio
        return WaveStructure(
            kind="BEARISH_3WAVE",
            wave1_start=H0,
            wave1_end=L1,
            wave2_end=H2,
            wave1_range=wave1,
            retrace_ratio=r,
            ext_target=ext,
            raw_swings_used=len(used),
        )

    candidates: List[WaveStructure] = []
    for start in range(max(0, len(used) - 3), len(used) - 2):
        trip = used[start : start + 3]
        ws = _try_bull(trip)
        if ws is not None:
            candidates.append(ws)
        ws2 = _try_bear(trip)
        if ws2 is not None:
            candidates.append(ws2)

    if not candidates:
        return WaveStructure(kind="UNCLEAR", raw_swings_used=len(used))

    last_type = used[-1]["type"]

    def _score(ws: WaveStructure) -> float:
        # 主排序：最后一个 swing type 匹配结构方向；次排序：r 接近 0.5
        match_bull = last_type == "low" and ws.kind == "BULLISH_3WAVE"
        match_bear = last_type == "high" and ws.kind == "BEARISH_3WAVE"
        prio = 0.0 if (match_bull or match_bear) else 1.0
        return prio + abs(ws.retrace_ratio - 0.5) * 0.1

    candidates.sort(key=_score)
    return candidates[0]


# --------------------------------------------------------------------------- #
# TimingGate 主类
# --------------------------------------------------------------------------- #
class TimingGate:
    """
    Tier 2 时机「软评分」评估器：波浪三浪结构 + Fib 回撤质量 + 追末端惩罚。

    最终得分：
        timing_score = structure_match_score × retrace_quality_score × extension_chase_score
        所有维度 ∈ [0,1]

    兼容布尔门禁：long_timing_ok = (score_for_long >= threshold) AND gate.long_enabled

    Args:
        swing_window:     fractal swing 检测半宽（默认 3，BCRM1.0 一致）
        fib_retrace_lo:   回撤区间下沿（默认 0.30）
        fib_retrace_hi:   回撤区间上沿（默认 0.72）
        fib_ext_ratio:    Fib 扩展倍数（默认 1.618）
        threshold:        timing_ok 的判定阈值（默认 0.5）
        lenient_unclear:  UNCLEAR 时的基线分（strict=False，默认 0.60，宽容放行打 6 折）
        strict_unclear_score: strict=True 时 UNCLEAR 基线分（默认 0.20，保守）
        strict:           True→用 strict_unclear_score，False→用 lenient_unclear
        retrace_mu:       Fib 回撤高斯钟形中心（默认 0.5，即 F500 黄金位得分最高）
        retrace_sigma:    Fib 回撤高斯钟形宽度（默认 0.18；越大=F382/F618 边缘也得高分，越宽容）
        unclear_retrace_ext: UNCLEAR 时回撤/追末端的 fallback 分数（默认 0.9；UNCLEAR 视为结构不敏感，基本不做惩罚）
    """

    def __init__(
        self,
        swing_window: int = 3,
        fib_retrace_lo: float = 0.30,
        fib_retrace_hi: float = 0.72,
        fib_ext_ratio: float = 1.618,
        threshold: float = 0.50,
        lenient_unclear: float = 0.60,
        strict_unclear_score: float = 0.20,
        strict: bool = False,
        retrace_mu: float = 0.50,
        retrace_sigma: float = 0.18,
        unclear_retrace_ext: float = 0.90,
        swing_fusion_mode: str = "daily_only",
        intraday_swing_window: int = 3,
    ) -> None:
        self.swing_window = int(swing_window)
        self.fib_retrace_lo = float(fib_retrace_lo)
        self.fib_retrace_hi = float(fib_retrace_hi)
        self.fib_ext_ratio = float(fib_ext_ratio)
        self.threshold = float(threshold)
        self.lenient_unclear = float(lenient_unclear)
        self.strict_unclear_score = float(strict_unclear_score)
        self.strict = bool(strict)
        self.retrace_mu = float(retrace_mu)
        self.retrace_sigma = max(1e-6, float(retrace_sigma))
        self.unclear_retrace_ext = float(unclear_retrace_ext)
        self.swing_fusion_mode = str(swing_fusion_mode).lower()
        self.intraday_swing_window = int(intraday_swing_window)
        # TDD 注入
        self._test_swings_override: Optional[List[Any]] = None

    # ----- 内部辅助 ------------------------------------------------------- #
    def _get_swings(self, recent_closes: List[float], window: int = None) -> List[SwingPoint]:
        if window is None:
            window = self.swing_window
        if self._test_swings_override is not None:
            out: List[SwingPoint] = []
            for s in self._test_swings_override:
                if isinstance(s, SwingPoint):
                    out.append(s)
                elif isinstance(s, dict):
                    out.append(SwingPoint(price=float(s["price"]), type=str(s.get("type", "low"))))
            return out
        try:
            return detect_swing_points(list(recent_closes), window=window)
        except Exception:
            return []

    def _eval_one_tf(
        self,
        closes: List[float],
        price_now: float,
        g_long: bool,
        g_short: bool,
        window: int = None,
    ) -> dict:
        """单时间框架结构评估，返回各维度分数 + 结构信息。"""
        swings = self._get_swings(closes, window=window)
        structure = detect_three_wave_structure(swings, fib_ext_ratio=self.fib_ext_ratio)

        # 维度 1：structure_match_score
        if structure.kind == "UNCLEAR":
            base = self.strict_unclear_score if self.strict else self.lenient_unclear
            structure_score = base
        elif structure.kind == "BULLISH_3WAVE":
            structure_score = 1.0 if g_long else 0.1
        else:  # BEARISH_3WAVE
            structure_score = 1.0 if g_short else 0.1

        # 维度 2/3：fib 回撤质量 + 追末端惩罚
        if structure.kind == "UNCLEAR":
            retrace_score = self.unclear_retrace_ext
            ext_score = self.unclear_retrace_ext
            fib_zone = "NONE"
            r = 0.0
        else:
            r = structure.retrace_ratio
            fib_zone = classify_fib_zone(r, lo=self.fib_retrace_lo, hi=self.fib_retrace_hi)
            retrace_score = retrace_quality_score(
                r,
                lo=self.fib_retrace_lo,
                hi=self.fib_retrace_hi,
                mu=self.retrace_mu,
                sigma=self.retrace_sigma,
            )
            ext_score = extension_chase_score(
                price_now=price_now,
                ext_target=structure.ext_target,
                wave1_range=structure.wave1_range,
                structure_kind=structure.kind,
            )
            if (structure.kind == "BULLISH_3WAVE" and price_now >= structure.ext_target) or (
                structure.kind == "BEARISH_3WAVE" and price_now <= structure.ext_target
            ):
                if math.isclose(self.fib_ext_ratio, 1.618, abs_tol=0.005):
                    fib_zone = "EXT1618"
                else:
                    fib_zone = "EXT%.0f" % (self.fib_ext_ratio * 1000)

        timing_score = max(0.0, min(1.0, structure_score * retrace_score * ext_score))

        return {
            "timing_score": timing_score,
            "structure_score": structure_score,
            "retrace_score": retrace_score,
            "ext_score": ext_score,
            "structure": structure,
            "fib_zone": fib_zone,
            "r": r,
        }

    @staticmethod
    def _extract_direction(gate_result: Any) -> tuple[bool, bool, str]:
        """从 GateResult / dict 解出 long_enabled / short_enabled / regime_str。"""
        if isinstance(gate_result, dict):
            g_long = bool(
                gate_result.get("long_allowed", True) or gate_result.get("long_enabled", True)
            )
            g_short = bool(
                gate_result.get("short_allowed", False) or gate_result.get("short_enabled", False)
            )
            regime = str(gate_result.get("regime", ""))
            return g_long, g_short, regime
        # GateResult dataclass：属性是 .long_enabled / .short_enabled / .regime
        g_long = bool(getattr(gate_result, "long_enabled", True))
        g_short = bool(getattr(gate_result, "short_enabled", False))
        regime_obj = getattr(gate_result, "regime", None)
        regime = str(regime_obj.value) if hasattr(regime_obj, "value") else str(regime_obj or "")
        return g_long, g_short, regime

    # ----- 主接口 --------------------------------------------------------- #
    def evaluate(
        self,
        gate_result: Any,
        recent_closes: List[float],
        price_now: float,
        intraday_closes: Optional[List[float]] = None,
    ) -> TimingResult:
        """
        Args:
            gate_result: DirectionGate 的 GateResult（方向先验）。兼容 TDD 传入的 dict。
            recent_closes: 日线收盘价序列（建议长度 ≥60）
            price_now: 当前价格（用于 EXT 位置评分）
            intraday_closes: 小时级（4h）收盘价序列，用于双周期 swing 融合。
                             仅当 swing_fusion_mode != "daily_only" 且序列足够长时生效。
        """
        g_long, g_short, regime_str = self._extract_direction(gate_result)

        # ---- 日线结构评估 ----
        daily = self._eval_one_tf(
            recent_closes, price_now, g_long, g_short, window=self.swing_window
        )

        # ---- 小时级 swing 融合 ----
        use_intraday = (
            intraday_closes is not None
            and self.swing_fusion_mode != "daily_only"
            and len(intraday_closes) >= 20
        )
        if use_intraday:
            intra = self._eval_one_tf(
                intraday_closes,
                price_now,
                g_long,
                g_short,
                window=self.intraday_swing_window,
            )
            if self.swing_fusion_mode == "or":
                # 取较高的 timing_score（更宽容：任一周期识别到好结构即可）
                if intra["timing_score"] > daily["timing_score"]:
                    best = intra
                    fusion_tag = "intraday"
                else:
                    best = daily
                    fusion_tag = "daily"
            elif self.swing_fusion_mode == "and":
                # 取较低的 timing_score（更严格：两个周期都需认可）
                best = daily
                best["timing_score"] = min(daily["timing_score"], intra["timing_score"])
                fusion_tag = "and(min)"
            else:
                best = daily
                fusion_tag = "daily"
        else:
            best = daily
            fusion_tag = "daily"

        timing_score = max(0.0, min(1.0, best["timing_score"]))
        structure_score = best["structure_score"]
        retrace_score = best["retrace_score"]
        ext_score = best["ext_score"]
        structure = best["structure"]
        fib_zone = best["fib_zone"]
        r = best["r"]

        # ---- 与 Gate 方向做「与」----
        long_score = timing_score if g_long else 0.0
        short_score = timing_score if g_short else 0.0
        long_ok = long_score >= self.threshold
        short_ok = short_score >= self.threshold

        # ---- 生成人类可读 reason ----
        bd = TimingScoreBreakdown(
            structure_match=structure_score,
            retrace_quality=retrace_score,
            extension_chase=ext_score,
        )
        parts: list[str] = []
        if use_intraday:
            parts.append(f"融合模式={self.swing_fusion_mode}({fusion_tag})")
        if structure.kind == "UNCLEAR":
            parts.append("结构未明(UNCLEAR)，基线分=%.2f" % structure_score)
        else:
            parts.append(
                (
                    "多头三浪(BULLISH_3WAVE)"
                    if structure.kind == "BULLISH_3WAVE"
                    else "空头三浪(BEARISH_3WAVE)"
                )
                + f" r={r:.3f}({fib_zone or 'NONE'})"
                + f" EXT={structure.ext_target:.3f}"
            )
        parts.append(
            "score=%.2f = struct×%.2f × retrace×%.2f × ext×%.2f"
            % (
                timing_score,
                structure_score,
                retrace_score,
                ext_score,
            )
        )
        if fib_zone == "EXT1618" or fib_zone.startswith("EXT"):
            parts.append("⚠️ 已达 Fib 扩展位，追末端风险高")
        if long_ok:
            parts.append("✅多时机通过(long_score=%.2f>=%.2f)" % (long_score, self.threshold))
        if short_ok:
            parts.append("✅空时机通过(short_score=%.2f>=%.2f)" % (short_score, self.threshold))
        if not long_ok and not short_ok:
            parts.append("⏳等待(分数<%.2f或方向不匹配)" % self.threshold)
        reason = " | ".join(parts)

        return TimingResult(
            timing_score=timing_score,
            long_timing_ok=long_ok,
            short_timing_ok=short_ok,
            structure=structure,
            fib_zone=fib_zone,
            score_breakdown=bd,
            reason=reason,
        )
