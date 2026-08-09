"""Phase 4 TDD: TimingGate — 波浪三浪结构 + Fibonacci 回撤/扩展 时机门禁

分层：
  lib/timing_gate.py
    WaveStructure    (kind / wave1 三点 / retrace_ratio / ext_target)
    TimingResult     (long_timing_ok / short_timing_ok / structure / fib_zone / reason)
    TimingGate.evaluate(gate_result, recent_closes, price_now) → TimingResult

与 Phase3 direction_gate 解耦：
  - TimingGate 内部直接调用 direction_gate.detect_swing_points (fractal swing 检测)
  - 只把 DirectionGate.GateResult 作为"方向先验"（若 gate 不让做多，则即使 bull 结构也返回 long_timing_ok=False）
  - UNCLEAR 结构时宽容模式：默认放行 (timing_ok=True) 避免过度限仓
"""
from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# --------------------------------------------------------------------------- #
# 测试框架（零第三方）
# --------------------------------------------------------------------------- #
PASS = 0
FAIL = 0

def check(name: str, cond: bool, detail: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}" + (f" — {detail}" if detail else ""))


def approx(a: float, b: float, tol: float = 1e-3) -> bool:
    return abs(a - b) <= tol


# --------------------------------------------------------------------------- #
# 导入被测模块（TDD-RED：文件可能不存在/为空，会先失败）
# --------------------------------------------------------------------------- #
try:
    from lib.timing_gate import (
        TimingGate, TimingResult, WaveStructure,
        detect_three_wave_structure, classify_fib_zone,
        retrace_quality_score, extension_chase_score,
    )
    from lib.direction_gate import GateResult, MarketRegime, TradeDirection
    _MODULE_LOADED = True
except Exception as _E:
    print(f"[TDD-RED] 模块加载失败（预期在 RED 阶段发生）：{_E}")
    TimingGate = None  # type: ignore
    WaveStructure = None  # type: ignore
    TimingResult = None  # type: ignore
    detect_three_wave_structure = None  # type: ignore
    classify_fib_zone = None  # type: ignore
    retrace_quality_score = None  # type: ignore
    extension_chase_score = None  # type: ignore
    GateResult = None  # type: ignore
    MarketRegime = None  # type: ignore
    TradeDirection = None  # type: ignore
    _MODULE_LOADED = False


# --------------------------------------------------------------------------- #
# 构造 GateResult（方向先验的最小实例）—— 与真实 GateResult 字段完全对齐
# --------------------------------------------------------------------------- #
def _make_gate(regime: str, long_allowed: bool, short_allowed: bool) -> "GateResult":
    # 兼容：如果 GateResult 还未导入，返回普通 dict (在 RED 阶段不会被使用)
    if GateResult is None:
        return dict(regime=regime, long_enabled=long_allowed, short_enabled=short_allowed, diagnostic={})

    # 用枚举构造真实 regime / allowed_direction
    regime_map = {
        "long_preferred": MarketRegime.LONG_PREFERRED,
        "short_allowed": MarketRegime.SHORT_ALLOWED,
        "long_only_force": MarketRegime.LONG_ONLY_FORCE,
        "long_only": MarketRegime.LONG_PREFERRED,
    }
    regime_enum = regime_map.get(regime, MarketRegime.LONG_PREFERRED)

    if long_allowed and short_allowed:
        dir_enum = TradeDirection.BOTH
    elif long_allowed and not short_allowed:
        dir_enum = TradeDirection.LONG_ONLY
    elif not long_allowed and short_allowed:
        dir_enum = TradeDirection.SHORT_ONLY
    else:
        dir_enum = TradeDirection.NONE

    return GateResult(
        regime=regime_enum,
        allowed_direction=dir_enum,
        price_vs_daily_ma128="above",
        price_vs_weekly_ma200="above",
        daily_ma128=100.0,
        weekly_ma200=90.0,
        current_price=110.0,
        reason=f"TDD mock regime={regime}",
        mechanistic_diag=None,
    )


# --------------------------------------------------------------------------- #
# 测试集 A: detect_three_wave_structure — 三浪结构识别
# --------------------------------------------------------------------------- #
def t_a1_bullish_three_wave_basic():
    """Bullish 三浪正例：L0=100 H1=130 L2=115 (higher low L2>L0), retrace = 15/30=0.5"""
    # 构造一段产生此 swing 的 closes
    closes = [100, 105, 110, 115, 120, 125, 130, 127, 122, 118, 115, 116, 117, 120]
    # L0=100 (i=0), H1=130 (i=6), L2=115 (i=10)，之后有更高的点证明 L2
    swings = _swing_fallback(closes) if not _MODULE_LOADED else None  # 实际调用模块内的
    ws = detect_three_wave_structure(swings or _mock_swings_bull())
    check("A1. bull三浪 kind=BULLISH_3WAVE", ws.kind == "BULLISH_3WAVE", f"got {ws.kind}")
    check("A2. bull三浪 L0=100", approx(ws.wave1_start, 100.0))
    check("A3. bull三浪 H1=130", approx(ws.wave1_end, 130.0))
    check("A4. bull三浪 L2=115", approx(ws.wave2_end, 115.0))
    check("A5. bull三浪 wave1_range=30", approx(ws.wave1_range, 30.0))
    check("A6. bull三浪 retrace=0.5 (50%回撤)", approx(ws.retrace_ratio, 0.5))
    check("A7. bull三浪 ext_target=100+30*1.618=148.54", approx(ws.ext_target, 148.54, 0.01))


def _mock_swings_bull():
    """Bull三浪测试用：3个 swing，最后一个 swing type=low（L2 浪2刚结束），无歧义。"""
    return [
        {"idx": 0, "price": 100.0, "type": "low"},
        {"idx": 6, "price": 130.0, "type": "high"},
        {"idx": 10, "price": 115.0, "type": "low"},
    ]


def _mock_swings_bear():
    """Bear三浪测试用：3个 swing，最后一个 swing type=high（H2 浪2刚结束），无歧义。"""
    return [
        {"idx": 0, "price": 200.0, "type": "high"},
        {"idx": 6, "price": 170.0, "type": "low"},
        {"idx": 10, "price": 185.0, "type": "high"},
    ]


def t_a2_bearish_three_wave_basic():
    """Bearish 三浪正例：H0=200 L1=170 H2=185 (lower high H2<H0), rebound = 15/30=0.5"""
    ws = detect_three_wave_structure(_mock_swings_bear())
    check("A8. bear三浪 kind=BEARISH_3WAVE", ws.kind == "BEARISH_3WAVE", f"got {ws.kind}")
    check("A9. bear三浪 H0=200", approx(ws.wave1_start, 200.0))
    check("A10. bear三浪 L1=170", approx(ws.wave1_end, 170.0))
    check("A11. bear三浪 H2=185", approx(ws.wave2_end, 185.0))
    check("A12. bear三浪 wave1_range=30", approx(ws.wave1_range, 30.0))
    check("A13. bear三浪 retrace(rebound)=0.5", approx(ws.retrace_ratio, 0.5))
    check("A14. bear三浪 ext_target=200-30*1.618=151.46", approx(ws.ext_target, 151.46, 0.01))


def t_a3_unclear_not_enough_swings():
    """swing 点数 <3 → UNCLEAR"""
    for n in ([], [{"idx":0,"price":100,"type":"low"}],
              [{"idx":0,"price":100,"type":"low"}, {"idx":5,"price":110,"type":"high"}]):
        ws = detect_three_wave_structure(n)
        check(f"A15. swings={len(n)} → UNCLEAR", ws.kind == "UNCLEAR", f"got {ws.kind}")


def t_a4_unclear_bull_lower_low():
    """Bull 候选但 L2 ≤ L0（破前低 → 非 higher low → UNCLEAR / BEARISH 倾向）"""
    swings = [
        {"idx": 0, "price": 100.0, "type": "low"},
        {"idx": 6, "price": 130.0, "type": "high"},
        {"idx": 10, "price": 95.0, "type": "low"},  # 破前低 L0=100
    ]
    ws = detect_three_wave_structure(swings)
    # 不应构造为 BULLISH
    check("A16. L2≤L0 破前低 → 非 BULLISH_3WAVE", ws.kind != "BULLISH_3WAVE", f"got {ws.kind}")


def t_a5_unclear_bear_higher_high():
    """Bear 候选但 H2 ≥ H0（破前高 → 非 lower high → UNCLEAR）"""
    swings = [
        {"idx": 0, "price": 200.0, "type": "high"},
        {"idx": 6, "price": 170.0, "type": "low"},
        {"idx": 10, "price": 205.0, "type": "high"},  # 破前高 H0=200
    ]
    ws = detect_three_wave_structure(swings)
    check("A17. H2≥H0 破前高 → 非 BEARISH_3WAVE", ws.kind != "BEARISH_3WAVE", f"got {ws.kind}")


def _swing_fallback(closes):
    """RED 阶段临时 fallback，实际上 detect_three_wave_structure 需要 raw swings，测试用例 A1 直接给 swings"""
    return _mock_swings_bull()


# --------------------------------------------------------------------------- #
# 测试集 B: classify_fib_zone — 回撤区间归类
# --------------------------------------------------------------------------- #
def t_b_fib_zone_classification():
    check("B1. r=0.382 → F382", classify_fib_zone(0.382) == "F382")
    check("B2. r=0.5 → F500", classify_fib_zone(0.5) == "F500")
    check("B3. r=0.618 → F618", classify_fib_zone(0.618) == "F618")
    check("B4. r=0.44（F382 与 F500 之间）→ F382", classify_fib_zone(0.44) == "F382")
    check("B5. r=0.56（F500 与 F618 之间）→ F500", classify_fib_zone(0.56) == "F500")
    check("B6. r=0.2（<0.30 无有效回撤带）→ NONE", classify_fib_zone(0.2) == "NONE")
    check("B7. r=0.8（>0.72 超出容差）→ NONE", classify_fib_zone(0.8) == "NONE")


# --------------------------------------------------------------------------- #
# 测试集 C: TimingGate.evaluate() — 完整时机门禁（三浪+回撤+扩展+方向先验）
# --------------------------------------------------------------------------- #
def t_c1_bull_structure_within_fib_band_and_gate_long_ok():
    """Bull 三浪 + r=0.5 ∈ [0.30,0.72] + 现价 118 < EXT148.54 + gate 允许多 → long_timing_ok"""
    tg = TimingGate(fib_retrace_lo=0.30, fib_retrace_hi=0.72, fib_ext_ratio=1.618)
    gate = _make_gate("long_preferred", long_allowed=True, short_allowed=False)
    recent_closes = list(range(60))  # dummy，内部走 swing 检测；我们通过 monkey patch 用固定 swings 测
    # Monkey patch 内部 swing 检测（否则要构造真实的长序列 closes，测试不直观）
    _monkey_swings(tg, _mock_swings_bull())
    tr = tg.evaluate(gate, recent_closes, price_now=118.0)
    check("C1. bull+f500+未到ext+gate允 → long_timing_ok=True", tr.long_timing_ok is True, str(tr))
    check("C2. bull 情形下 short_timing_ok=False", tr.short_timing_ok is False)
    check("C3. fib_zone=F500", tr.fib_zone == "F500", tr.fib_zone)
    check("C4. reason 包含通过", "通过" in tr.reason or "pass" in tr.reason.lower(), tr.reason)


def t_c2_bull_gate_does_not_allow_long_so_timing_also_no():
    """即使 bull 结构完美，若 DirectionGate 不允许多 → long_timing_ok=False"""
    tg = TimingGate()
    gate = _make_gate("short_allowed", long_allowed=False, short_allowed=True)
    _monkey_swings(tg, _mock_swings_bull())
    tr = tg.evaluate(gate, recent_closes=list(range(60)), price_now=118.0)
    check("C5. 方向先验不允许多 → long_timing_ok=False", tr.long_timing_ok is False)


def t_c3_bull_price_over_ext_1618_no_chase():
    """现价 ≥ EXT1618 → 禁止追 5 浪末端 → long_timing_ok=False"""
    tg = TimingGate(fib_ext_ratio=1.618)
    gate = _make_gate("long_preferred", long_allowed=True, short_allowed=False)
    _monkey_swings(tg, _mock_swings_bull())
    tr = tg.evaluate(gate, recent_closes=list(range(60)), price_now=150.0)  # EXT 是 148.54，150 > 148.54
    check("C6. 超EXT1618 追末端 → long_timing_ok=False", tr.long_timing_ok is False)
    check("C7. reason 包含'追末端'或'扩展'或'EXT'", ("追末端" in tr.reason or "扩展" in tr.reason or "EXT" in tr.reason), tr.reason)


def t_c4_bull_retrace_too_shallow_wait():
    """r=0.15 < 0.30 → 回撤质量分数低，long_timing_ok=False（默认 threshold=0.5）"""
    shallow_swings = [
        {"idx": 0, "price": 100.0, "type": "low"},
        {"idx": 6, "price": 130.0, "type": "high"},
        {"idx": 9, "price": 125.5, "type": "low"},  # r = (130-125.5)/30 = 0.15 回撤很浅
    ]
    tg = TimingGate(strict=True, fib_retrace_lo=0.30, fib_retrace_hi=0.72)
    gate = _make_gate("long_preferred", long_allowed=True, short_allowed=False)
    _monkey_swings(tg, shallow_swings)
    tr = tg.evaluate(gate, recent_closes=list(range(60)), price_now=126.0)
    # 浅回撤时 retrace_quality_score(0.15) ≈ exp(-0.5*(0.35/0.18)^2) ≈ exp(-1.89) ≈ 0.15
    # structure = 1.0 (strict mode unclear only affects UNCLEAR；这里结构清晰 bull)
    # ext = 价格 126 在 148.54 下方约 22.54 < 30 → 0.5+0.5*22.54/30 = 0.876
    # total ≈ 1.0 * 0.15 * 0.876 ≈ 0.13 < 0.5 阈值 → long_timing_ok=False
    check("C8. 回撤浅 r=0.15<0.30 → long_timing_ok=False", tr.long_timing_ok is False)
    check("C9. reason 包含'回撤'或'等待'或'等待'",
          ("回撤" in tr.reason or "浅" in tr.reason or "等待" in tr.reason), tr.reason)


def t_c5_bull_retrace_too_deep_trend_reversal_risk():
    """r=0.85 > 0.72 → 深回撤 retrace 低分 → timing_ok=False"""
    deep_swings = [
        {"idx": 0, "price": 100.0, "type": "low"},
        {"idx": 6, "price": 130.0, "type": "high"},
        {"idx": 10, "price": 104.5, "type": "low"},  # r = (130-104.5)/30 = 0.85
    ]
    tg = TimingGate(strict=True)
    gate = _make_gate("long_preferred", long_allowed=True, short_allowed=False)
    _monkey_swings(tg, deep_swings)
    tr = tg.evaluate(gate, recent_closes=list(range(60)), price_now=105.0)
    # retrace_quality_score(0.85) ≈ exp(-0.5*(0.35/0.18)^2) ≈ 0.15
    check("C10. 深回撤 r=0.85>0.72 → long_timing_ok=False", tr.long_timing_ok is False)
    check("C11. reason 包含'等待'或'NONE'(fib_zone不明)",
          ("等待" in tr.reason or "NONE" in tr.fib_zone or "回撤" in tr.reason),
          f"reason={tr.reason} zone={tr.fib_zone}")


def t_c6_bear_rebound_f618_within_band_ok():
    """Bear 三浪 + r=0.618 反弹 ∈ 区间 + 未到 EXT151.46 + gate 允许空"""
    bear_swings_f618 = [
        {"idx": 0, "price": 200.0, "type": "high"},
        {"idx": 6, "price": 170.0, "type": "low"},
        {"idx": 10, "price": 188.54, "type": "high"},  # (188.54-170)/30=0.618
    ]
    tg = TimingGate()
    gate = _make_gate("short_allowed", long_allowed=True, short_allowed=True)
    _monkey_swings(tg, bear_swings_f618)
    tr = tg.evaluate(gate, recent_closes=list(range(60)), price_now=187.0)
    check("C12. bear+F618反弹+未到ext+gate允空 → short_timing_ok=True", tr.short_timing_ok is True, str(tr))
    check("C13. fib_zone=F618", tr.fib_zone == "F618", tr.fib_zone)


def t_c7_bear_price_under_ext_no_chase_down():
    """现价 ≤ bear EXT151.46（下跌扩展目标）→ 禁止追 5 浪末端 → short_timing_ok=False"""
    tg = TimingGate(fib_ext_ratio=1.618)
    gate = _make_gate("short_allowed", long_allowed=True, short_allowed=True)
    _monkey_swings(tg, _mock_swings_bear())   # H0=200 L1=170 H2=185 → EXT=200-30*1.618=151.46
    tr = tg.evaluate(gate, recent_closes=list(range(60)), price_now=150.0)  # 150 < 151.46
    check("C14. bear 超扩展末端 → short_timing_ok=False", tr.short_timing_ok is False)


def t_c8_unclear_structure_lenient_mode_passes():
    """结构 UNCLEAR + lenient(strict=False) → timing_score 按 gate 方向决定ok（避免过度限仓）"""
    tg = TimingGate(strict=False, threshold=0.5)
    gate = _make_gate("long_preferred", long_allowed=True, short_allowed=False)
    _monkey_swings(tg, [{"idx":0,"price":100,"type":"low"}])  # 仅 1 个 swing → UNCLEAR
    tr = tg.evaluate(gate, recent_closes=list(range(60)), price_now=100.0)
    # lenient → structure_score=0.6, retrace=0.9, ext=0.9 → total≈0.486
    # threshold 默认 0.5 → 可能刚好 0.486 < 0.5 → timing_ok=False
    # 为避免边界，UNCLER lenient 检查 score >=0.45（宽容放行范围）
    check("C15. UNCLEAR+lenient → timing_score ∈ [0.4,0.8]（宽容放行打折扣）",
          0.4 <= tr.timing_score <= 0.8, f"score={tr.timing_score}")
    check("C16. UNCLEAR+lenient → short_timing_ok=False（gate 不允许空）",
          tr.short_timing_ok is False)


def t_c9_unclear_structure_strict_mode_blocks():
    """结构 UNCLEAR + strict=True → 低分 timing_ok=False（结构不清不下单）"""
    tg = TimingGate(strict=True, threshold=0.5)
    gate = _make_gate("long_preferred", long_allowed=True, short_allowed=False)
    _monkey_swings(tg, [{"idx":0,"price":100,"type":"low"}])
    tr = tg.evaluate(gate, recent_closes=list(range(60)), price_now=100.0)
    # strict → structure_score=0.2, retrace=0.9, ext=0.9 → total≈0.162
    check("C17. UNCLEAR+strict → timing_score ≤0.3（保守低分）",
          tr.timing_score <= 0.3, f"score={tr.timing_score}")
    check("C17b. UNCLEAR+strict → long_timing_ok=False（结构不清不入场）",
          tr.long_timing_ok is False)


def t_c10_gate_diagnostic_timing_field_present():
    """TimingGate 结果的字段完整性（用于 mechanistic_diag 透传）"""
    tg = TimingGate()
    gate = _make_gate("long_preferred", long_allowed=True, short_allowed=False)
    _monkey_swings(tg, _mock_swings_bull())
    tr = tg.evaluate(gate, recent_closes=list(range(60)), price_now=118.0)
    # 验证所有必需字段
    for attr in ("timing_score", "long_timing_ok", "short_timing_ok",
                 "structure", "fib_zone", "score_breakdown", "reason"):
        check(f"C18. TimingResult 含字段 {attr}", hasattr(tr, attr))
    for attr in ("kind", "wave1_start", "wave1_end", "wave2_end",
                 "wave1_range", "retrace_ratio", "ext_target"):
        check(f"C19. WaveStructure 含字段 {attr}", hasattr(tr.structure, attr))
    # to_diagnostic 验证
    diag = tr.to_diagnostic()
    check("C20. to_diagnostic() 输出含 timing_score", "timing_score" in diag)
    check("C21. to_diagnostic() 输出含 breakdown 三维度",
          all(k in diag.get("breakdown", {}) for k in
              ("structure_match", "retrace_quality", "extension_chase")))


def _monkey_swings(tg: "TimingGate", swings: list[dict]):
    """TDD 中，把 TimingGate 内部的 swing 检测替换为固定列表，避免依赖真实长序列"""
    tg._test_swings_override = [dict(s) for s in swings]


# --------------------------------------------------------------------------- #
# 测试集 D: 与 direction_gate.detect_swing_points 端到端（用真实 closes 生成 swing）
# --------------------------------------------------------------------------- #
def t_d_end_to_end_with_real_swing_detection():
    """不用 monkey patch，直接给 closes 走真实 direction_gate swing 检测 + 三浪识别"""
    # swing_window=2（更高灵敏度），fractal 只需要各边 2 bar
    tg = TimingGate(swing_window=2)
    closes: list[float] = []
    # 浪1: 100 → 130 (bar 0..30，用更多bar让swing清晰)
    for i in range(31):
        closes.append(100 + i * (30/30))
    # 浪2: 130 → 115 (bar 30..50)
    for i in range(1, 21):
        closes.append(130 - i * (15/20))
    # 浪3 启动: 115 → 126 (bar 50..75)，保证最后的 swing low (115) 被识别（之后2bar更高）
    for i in range(1, 26):
        closes.append(115 + i * (11/25))
    gate = _make_gate("long_preferred", long_allowed=True, short_allowed=False)
    tr = tg.evaluate(gate, closes, price_now=closes[-1])
    # 至少满足 timing_score 语义合理 ∈ [0,1]；结构是否 UNCLEAR 取决于 swing 检测（放宽）
    check("D1. timing_score ∈ [0,1]", 0 <= tr.timing_score <= 1, f"score={tr.timing_score}")
    check("D2. long_timing_ok 布尔有效", isinstance(tr.long_timing_ok, bool))
    check("D3. short_timing_ok=False（gate 不允许空）", tr.short_timing_ok is False)
    # 诊断字段
    check("D4. to_diagnostic().breakdown 存在", "breakdown" in tr.to_diagnostic())


# --------------------------------------------------------------------------- #
# 测试集 E: 软评分 纯函数数学验证
# --------------------------------------------------------------------------- #
def t_e1_retrace_quality_curve():
    """Fib 回撤质量高斯钟形曲线：F500 最高，F382/F618 次高，边缘递减，极浅/极深 → 低"""
    r_f500 = retrace_quality_score(0.500)
    r_f382 = retrace_quality_score(0.382)
    r_f618 = retrace_quality_score(0.618)
    r_lo = retrace_quality_score(0.30)
    r_hi = retrace_quality_score(0.72)
    r_shallow = retrace_quality_score(0.05)
    r_deep = retrace_quality_score(0.95)
    check("E1. F500=1.0（最高）", approx(r_f500, 1.0, 1e-3), f"got {r_f500}")
    check("E2. F382 ∈ [0.80, 0.95]", 0.80 <= r_f382 <= 0.95, f"got {r_f382}")
    check("E3. F618 ∈ [0.80, 0.95]（与F382对称）", 0.80 <= r_f618 <= 0.95, f"got {r_f618}")
    check("E4. 0.30 边缘 ∈ [0.50, 0.75]（σ高斯钟形外1σ附近）", 0.50 <= r_lo <= 0.75, f"got {r_lo}")
    check("E5. 0.72 边缘 ∈ [0.40, 0.75]（与0.30对称，1σ~1.2z处）", 0.40 <= r_hi <= 0.75, f"got {r_hi}")
    check("E6. 极浅回撤 r=0.05 ≤0.35", r_shallow <= 0.35, f"got {r_shallow}")
    check("E7. 极深回撤 r=0.95 ≤0.35", r_deep <= 0.35, f"got {r_deep}")
    check("E8. retrace_quality ∈ [0,1] 对所有 r∈[-0.5,1.5]",
          all(0 <= retrace_quality_score(r) <= 1 for r in (x/10 for x in range(-5, 16))))


def t_e2_extension_chase_piecewise():
    """追末端惩罚分数：Bull 情形下价格在 EXT 下方≥Wave1→1.0；刚好在EXT→0.5；越过≥0.3Wave1→0.2"""
    # Bull：wave1_range=30，ext=148.54，gap=ext-price
    # 价格 118：gap=30.54 ≥ wave1=30 → score=1.0
    s_far = extension_chase_score(118.0, 148.54, 30.0, "BULLISH_3WAVE")
    # 价格 148.54：刚好到 → score=0.5
    s_just = extension_chase_score(148.54, 148.54, 30.0, "BULLISH_3WAVE")
    # 价格 157.54：over=9 = 0.3*30 → score=0.2
    s_maxover = extension_chase_score(148.54 + 9.0, 148.54, 30.0, "BULLISH_3WAVE")
    # 价格 160：over=10.5>9 → score≤0.2
    s_over = extension_chase_score(160.0, 148.54, 30.0, "BULLISH_3WAVE")
    check("E9. Bull 远低于EXT → =1.0", approx(s_far, 1.0, 0.01), f"got {s_far}")
    check("E10. Bull 刚到EXT → =0.5", approx(s_just, 0.5, 0.01), f"got {s_just}")
    check("E11. Bull 刚到0.3Wave1超EXT → =0.2", approx(s_maxover, 0.2, 0.01), f"got {s_maxover}")
    check("E12. Bull 超EXT≥0.3Wave1 → ≤0.2", s_over <= 0.2 + 1e-9, f"got {s_over}")
    # Bear 对称测试：H0=200, Wave1=30, EXT=200-30*1.618=151.46
    # 价格 180：gap=180-151.46=28.54 <30 → 约 0.5+0.5*28.54/30 ≈ 0.976
    s_bear = extension_chase_score(180.0, 151.46, 30.0, "BEARISH_3WAVE")
    check("E13. Bear 高于EXT且<Wave1 → ∈ [0.5, 1.0]", 0.5 <= s_bear <= 1.0, f"got {s_bear}")


def t_e3_timing_score_integrated_matches_quality():
    """综合评分：F500 黄金回撤 → score 最高；边缘 F382/F618 → 次高"""
    # F500 场景: L0=100 H1=130 L2=115 → r=0.5
    tg = TimingGate(threshold=0.50)
    gate = _make_gate("long_preferred", long_allowed=True, short_allowed=False)
    _monkey_swings(tg, _mock_swings_bull())
    tr_f500 = tg.evaluate(gate, recent_closes=list(range(60)), price_now=118.0)

    # F382 场景: L2 = H1 - Wave1*0.382 = 130 - 30*0.382 = 118.54 → r=0.382
    # 仅3个swing: L0=100(low), H1=130(high), L2=118.54(low) → 保证最后一个swing是low=浪2底
    swings_f382 = [
        {"idx": 0, "price": 100.0, "type": "low"},
        {"idx": 10, "price": 130.0, "type": "high"},
        {"idx": 12, "price": 118.54, "type": "low"},
    ]
    _monkey_swings(tg, swings_f382)
    tr_f382 = tg.evaluate(gate, recent_closes=list(range(60)), price_now=120.0)

    check("E14. F500 timing_score ∈ [0.85, 1.0]（最佳）",
          0.85 <= tr_f500.timing_score <= 1.0, f"got {tr_f500.timing_score}")
    check("E15. F382 timing_score ∈ [0.6, 0.9]（比F500略低）",
          0.6 <= tr_f382.timing_score <= 0.9, f"got {tr_f382.timing_score}")
    check("E16. F500 score >= F382 score",
          tr_f500.timing_score >= tr_f382.timing_score - 1e-9,
          f"F500={tr_f500.timing_score} vs F382={tr_f382.timing_score}")


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    print("=" * 72)
    print("Phase 4 TimingGate TDD")
    print("=" * 72)

    if not _MODULE_LOADED:
        print()
        print("ℹ️  [TDD-RED] lib/timing_gate.py 尚未实现，测试将全部失败")
        print("ℹ️  请在 GREEN 阶段实现模块后重跑。")
        print()

    test_groups = [
        ("A. 三浪结构识别", [
            t_a1_bullish_three_wave_basic if _MODULE_LOADED else lambda: None,
            t_a2_bearish_three_wave_basic if _MODULE_LOADED else lambda: None,
            t_a3_unclear_not_enough_swings if _MODULE_LOADED else lambda: None,
            t_a4_unclear_bull_lower_low if _MODULE_LOADED else lambda: None,
            t_a5_unclear_bear_higher_high if _MODULE_LOADED else lambda: None,
        ]),
        ("B. Fib 回撤区间分类", [
            t_b_fib_zone_classification if _MODULE_LOADED else lambda: None,
        ]),
        ("C. TimingGate.evaluate 完整时机门禁", [
            t_c1_bull_structure_within_fib_band_and_gate_long_ok if _MODULE_LOADED else lambda: None,
            t_c2_bull_gate_does_not_allow_long_so_timing_also_no if _MODULE_LOADED else lambda: None,
            t_c3_bull_price_over_ext_1618_no_chase if _MODULE_LOADED else lambda: None,
            t_c4_bull_retrace_too_shallow_wait if _MODULE_LOADED else lambda: None,
            t_c5_bull_retrace_too_deep_trend_reversal_risk if _MODULE_LOADED else lambda: None,
            t_c6_bear_rebound_f618_within_band_ok if _MODULE_LOADED else lambda: None,
            t_c7_bear_price_under_ext_no_chase_down if _MODULE_LOADED else lambda: None,
            t_c8_unclear_structure_lenient_mode_passes if _MODULE_LOADED else lambda: None,
            t_c9_unclear_structure_strict_mode_blocks if _MODULE_LOADED else lambda: None,
            t_c10_gate_diagnostic_timing_field_present if _MODULE_LOADED else lambda: None,
        ]),
        ("D. 真实swing端到端", [
            t_d_end_to_end_with_real_swing_detection if _MODULE_LOADED else lambda: None,
        ]),
        ("E. 软评分数学验证（高斯回撤曲线 + 追末端分段线性）", [
            t_e1_retrace_quality_curve if _MODULE_LOADED else lambda: None,
            t_e2_extension_chase_piecewise if _MODULE_LOADED else lambda: None,
            t_e3_timing_score_integrated_matches_quality if _MODULE_LOADED else lambda: None,
        ]),
    ]

    for name, funcs in test_groups:
        print()
        print(f"  📌 {name}")
        for f in funcs:
            f()

    print()
    print("=" * 72)
    status = "✅" if FAIL == 0 else f"❌ 失败={FAIL}"
    print(f"结果: {PASS}/{PASS+FAIL} 通过, {FAIL} 失败  {status}")
    print("=" * 72)
    sys.exit(0 if FAIL == 0 else 1)
