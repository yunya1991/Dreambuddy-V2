"""EventDrivenStrategy 测试 — 买预期卖事实 + 实际利率 5 维评分。"""
from event_driven.event_driven_strategy import EventDrivenStrategy


def _make_kline(overrides=None):
    base = {
        "event_context": {
            "cycle_phase": "expectation_jump",
            "event_window": "pre_event",
            "in_fomc_cycle": True,
            "hike_prob": 0.88,
            "probability_trend": "stable",
        },
        "cpi_surprise": 0.2,
        "close": [100.0, 99.0, 99.5, 99.8],
        "high": [101.0, 100.0, 100.2, 100.1],
        "low": [98.0, 98.5, 99.0, 99.3],
        "open": [100.5, 99.2, 99.4, 99.6],
        "gold_change_pct": 0.005,
        "us10y_change_bp": -3.0,
        "dxy_change_pct": -0.003,
    }
    if overrides:
        base.update(overrides)
    return base


def test_not_in_fomc_cycle_returns_neutral():
    """非 FOMC 周期 + 无 CESI + 无 event_type → 仍返回 neutral（保留原行为）。"""
    strat = EventDrivenStrategy()
    kd = _make_kline()
    kd["event_context"]["in_fomc_cycle"] = False
    sig = strat.evaluate(kd)
    assert sig.signal == "neutral"
    assert sig.mode == "none"


# ================================================================
# T4 P0 盲区修复：解除 in_fomc_cycle 硬限制（SPEC §3.2.1）
# 非农/CPI/PPI 虽不在 FOMC 议息周期，但实质影响加息预期，必须激活策略
# ================================================================

def test_not_in_fomc_but_cesi_trigger_activates_strategy():
    """非 FOMC 周期 + CESI ≥ +1.5σ → 不再返回 mode='none'（CESI 触发激活）。"""
    strat = EventDrivenStrategy()
    kd = _make_kline()
    kd["event_context"]["in_fomc_cycle"] = False
    kd["event_context"]["event_type"] = "cpi"
    kd["cesi"] = 2.0  # 强于 1.5σ 阈值
    sig = strat.evaluate(kd)
    assert sig.mode != "none", f"CESI 触发应激活策略，但返回 mode={sig.mode}, reason={sig.reason}"


def test_not_in_fomc_but_negative_cesi_trigger_activates_strategy():
    """非 FOMC 周期 + CESI ≤ -1.5σ（数据远低于预期）→ 不再返回 mode='none'。"""
    strat = EventDrivenStrategy()
    kd = _make_kline()
    kd["event_context"]["in_fomc_cycle"] = False
    kd["event_context"]["event_type"] = "nfp"
    kd["cesi"] = -1.8  # 负向强超预期
    sig = strat.evaluate(kd)
    assert sig.mode != "none", f"负向 CESI 触发应激活策略，但返回 mode={sig.mode}"


def test_not_in_fomc_but_nfp_event_type_activates_strategy():
    """非 FOMC 周期 + event_type='nfp' → 强制激活（事件窗口内不计 CESI）。"""
    strat = EventDrivenStrategy()
    kd = _make_kline()
    kd["event_context"]["in_fomc_cycle"] = False
    kd["event_context"]["event_type"] = "nfp"
    # 故意不给 cesi，验证 event_type 单独足够激活
    sig = strat.evaluate(kd)
    assert sig.mode != "none", f"nfp 事件类型应强制激活，但返回 mode={sig.mode}"


def test_not_in_fomc_but_cpi_event_type_activates_strategy():
    """非 FOMC 周期 + event_type='cpi' → 强制激活。"""
    strat = EventDrivenStrategy()
    kd = _make_kline()
    kd["event_context"]["in_fomc_cycle"] = False
    kd["event_context"]["event_type"] = "cpi"
    sig = strat.evaluate(kd)
    assert sig.mode != "none", f"cpi 事件类型应强制激活，但返回 mode={sig.mode}"


def test_not_in_fomc_but_ppi_event_type_activates_strategy():
    """非 FOMC 周期 + event_type='ppi' → 强制激活。"""
    strat = EventDrivenStrategy()
    kd = _make_kline()
    kd["event_context"]["in_fomc_cycle"] = False
    kd["event_context"]["event_type"] = "ppi"
    sig = strat.evaluate(kd)
    assert sig.mode != "none", f"ppi 事件类型应强制激活，但返回 mode={sig.mode}"


def test_not_in_fomc_cesi_below_threshold_returns_neutral():
    """非 FOMC 周期 + CESI 未达 ±1.5σ 阈值 + 无 event_type → 仍返回 neutral。"""
    strat = EventDrivenStrategy()
    kd = _make_kline()
    kd["event_context"]["in_fomc_cycle"] = False
    kd["cesi"] = 0.8  # 弱于 1.5σ 阈值
    sig = strat.evaluate(kd)
    assert sig.signal == "neutral"
    assert sig.mode == "none"


def test_not_in_fomc_unknown_event_type_returns_neutral():
    """非 FOMC 周期 + event_type='unknown'（非 nfp/cpi/ppi）+ 无 CESI → 仍返回 neutral。"""
    strat = EventDrivenStrategy()
    kd = _make_kline()
    kd["event_context"]["in_fomc_cycle"] = False
    kd["event_context"]["event_type"] = "unknown"
    sig = strat.evaluate(kd)
    assert sig.signal == "neutral"
    assert sig.mode == "none"


# ================================================================
# T6 P0 盲区修复：注入 cme-fedwatch 真实 hike_prob + effr 替代兜底（SPEC §3.2.3）
# 当 hike_prob=0/None 时从 kline_data["fedwatch"] 读取真实概率
# _score_real_rate 用 fedwatch.effr 替代 BASE_RATE_MIDPOINT=3.625 硬编码
# ================================================================

def test_assess_forward_guidance_uses_fedwatch_real_hike_prob():
    """event_ctx.hike_prob=0 + fedwatch.hike_prob=0.85 → 应识别为 hawkish（用真实概率）。"""
    strat = EventDrivenStrategy()
    kd = _make_kline()
    kd["event_context"]["hike_prob"] = 0  # 占位，应被 fedwatch 覆盖
    kd["fedwatch"] = {"hike_prob": 0.85, "effr": 4.0, "meeting_date": "2026-10-28"}
    fg = strat._assess_forward_guidance(kd, kd["event_context"])
    assert fg == "hawkish", f"应使用 fedwatch 真实概率 0.85 识别为 hawkish，但返回 {fg}"


def test_assess_forward_guidance_uses_fedwatch_low_hike_prob():
    """event_ctx.hike_prob=0 + fedwatch.hike_prob=0.15 → 应识别为 dovish。"""
    strat = EventDrivenStrategy()
    kd = _make_kline()
    kd["event_context"]["hike_prob"] = 0
    kd["fedwatch"] = {"hike_prob": 0.15, "effr": 4.0}
    fg = strat._assess_forward_guidance(kd, kd["event_context"])
    assert fg == "dovish", f"应使用 fedwatch 真实概率 0.15 识别为 dovish，但返回 {fg}"


def test_assess_forward_guidance_high_effr_returns_dovish():
    """无 hike_prob + fedwatch.effr=5.0（高利率环境，加息空间有限）→ dovish。"""
    strat = EventDrivenStrategy()
    kd = _make_kline()
    kd["event_context"]["hike_prob"] = None
    kd["fedwatch"] = {"effr": 5.0}  # 高利率环境
    fg = strat._assess_forward_guidance(kd, kd["event_context"])
    assert fg == "dovish", f"高 effr=5.0 应识别为 dovish，但返回 {fg}"


def test_assess_forward_guidance_low_effr_returns_hawkish():
    """无 hike_prob + fedwatch.effr=2.0（低利率环境，加息空间大）→ hawkish。"""
    strat = EventDrivenStrategy()
    kd = _make_kline()
    kd["event_context"]["hike_prob"] = None
    kd["fedwatch"] = {"effr": 2.0}  # 低利率环境
    fg = strat._assess_forward_guidance(kd, kd["event_context"])
    assert fg == "hawkish", f"低 effr=2.0 应识别为 hawkish，但返回 {fg}"


def test_assess_forward_guidance_no_data_returns_empty():
    """无 hike_prob + 无 fedwatch → 返回空字符串（不评估）。"""
    strat = EventDrivenStrategy()
    kd = _make_kline()
    kd["event_context"]["hike_prob"] = None
    # 故意不注入 fedwatch
    fg = strat._assess_forward_guidance(kd, kd["event_context"])
    assert fg == "", f"无数据应返回空字符串，但返回 {fg!r}"


def test_score_real_rate_uses_fedwatch_effr_not_hardcoded():
    """_score_real_rate 应使用 fedwatch.effr 而非硬编码 BASE_RATE_MIDPOINT=3.625。

    场景：cpi_actual=4.5, fomc_decision.rate_change=0, fedwatch.effr=5.0
      effr 路径: nominal_rate = 5.0, real_rate = 5.0 - 4.5 = 0.5 → 0.65（< 1.0 区间）
      硬编码路径: nominal_rate = 3.625 + 0 = 3.625, real_rate = 3.625 - 4.5 = -0.875 → 0.90（< 0 区间）

    两者结果不同，断言应使用 fedwatch.effr 路径。
    """
    strat = EventDrivenStrategy()
    kd = _make_kline()
    kd["cpi_actual"] = 4.5
    kd["fomc_decision"] = {"rate_change": 0, "decision": "hold"}
    kd["fedwatch"] = {"effr": 5.0}
    ctx = kd["event_context"]
    ctx["cycle_phase"] = "expectation_jump"  # 触发 is_pre_event
    ctx["hike_prob"] = 0  # 0 * 0.25 = 0，不影响 nominal_rate
    s = strat._score_real_rate(kd, ctx)
    # 5.0 - 4.5 = 0.5 → 落入 < 1.0 区间 → 0.65
    assert s == 0.65, f"应使用 fedwatch.effr=5.0 计算 real_rate=0.5 → 0.65，但返回 {s}（可能仍用硬编码 3.625）"


# ================================================================
# 买预期卖事实 核心逻辑测试
# ================================================================

def test_buy_expectation_short_signal():
    """买预期阶段：高加息概率 + 价格下跌 → SHORT（利空正在被定价）。"""
    strat = EventDrivenStrategy()
    kd = _make_kline()
    kd["event_context"]["cycle_phase"] = "expectation_jump"
    kd["event_context"]["hike_prob"] = 0.88
    kd["close"] = [100.0, 97.0, 95.0, 93.0]  # 大跌
    kd["gold_change_pct"] = -0.02
    sig = strat.evaluate(kd)
    assert sig.signal == "short"
    assert sig.mode == "expectation_short"


def test_sell_fact_long_signal():
    """卖事实阶段：事件落地后 + 利空出尽 → LONG（资金反手买入）。"""
    strat = EventDrivenStrategy()
    kd = _make_kline()
    kd["event_context"]["cycle_phase"] = "repricing"
    kd["event_context"]["event_window"] = "post_event"
    kd["event_context"]["hike_prob"] = 0.10  # 加息已落地，概率下降
    kd["close"] = [93.0, 94.0, 95.5, 96.0]  # 反弹
    kd["gold_change_pct"] = 0.015
    sig = strat.evaluate(kd)
    assert sig.signal == "long"
    assert sig.mode == "priced_in_bottom"


def test_event_day_long_signal():
    """事件当天 → LONG（利空出尽）。"""
    strat = EventDrivenStrategy()
    kd = _make_kline()
    kd["event_context"]["cycle_phase"] = "event"
    kd["event_context"]["event_window"] = "event"
    kd["close"] = [93.0, 94.0, 95.0, 96.0]
    kd["gold_change_pct"] = 0.012
    sig = strat.evaluate(kd)
    assert sig.signal == "long"


# ================================================================
# 实际利率维度测试
# ================================================================

def test_real_rate_negative_bullish():
    """实际利率为负（CPI > 名义利率）→ 强烈利好黄金。"""
    strat = EventDrivenStrategy()
    kd = _make_kline()
    kd["cpi_actual"] = 6.0  # 通胀 6%
    kd["fomc_decision"] = {"rate_change": 0.25, "decision": "hike"}  # 名义利率 ~5.5%
    ctx = kd["event_context"]
    s = strat._score_real_rate(kd, ctx)
    assert s >= 0.85  # 实际利率 = 5.5 - 6.0 = -0.5 → 看多


def test_real_rate_high_bearish():
    """实际利率高（CPI 低 + 高利率）→ 利空黄金。"""
    strat = EventDrivenStrategy()
    kd = _make_kline()
    kd["cpi_actual"] = 2.0  # 通胀 2%
    kd["fomc_decision"] = {"rate_change": 0.25, "decision": "hike"}  # 名义利率 ~5.5%
    ctx = kd["event_context"]
    s = strat._score_real_rate(kd, ctx)
    assert s <= 0.35  # 实际利率 = 5.5 - 2.0 = 3.5 → 看空


def test_real_rate_no_data_returns_neutral():
    """无 CPI/利率数据 → 中性。"""
    strat = EventDrivenStrategy()
    kd = _make_kline()
    ctx = kd["event_context"]
    s = strat._score_real_rate(kd, ctx)
    assert s == 0.5


# ================================================================
# 前瞻指引测试
# ================================================================

def test_forward_guidance_hawkish_dot_plot():
    """点阵图偏鹰（暗示更多加息）→ composite 折扣。"""
    strat = EventDrivenStrategy()
    kd = _make_kline()
    kd["event_context"]["cycle_phase"] = "repricing"
    kd["event_context"]["event_window"] = "post_event"
    kd["fomc_decision"] = {"rate_change": 0.25, "decision": "hike", "dot_plot_median": 0.5}
    kd["close"] = [93.0, 94.0, 95.5, 96.0]
    sig = strat.evaluate(kd)
    assert sig.forward_guidance == "hawkish"


def test_forward_guidance_dovish():
    """鸽派前瞻指引 → 增强多头信号。"""
    strat = EventDrivenStrategy()
    kd = _make_kline()
    kd["event_context"]["cycle_phase"] = "repricing"
    kd["event_context"]["event_window"] = "post_event"
    kd["fomc_decision"] = {"rate_change": 0.25, "decision": "hike", "dot_plot_median": -0.5}
    kd["close"] = [93.0, 94.0, 95.5, 96.0]
    sig = strat.evaluate(kd)
    assert sig.forward_guidance == "dovish"


# ================================================================
# 原有维度测试（保持）
# ================================================================

def test_resilience_score_cpi_surprise_no_drop():
    """CPI 超预期但价格没跌 → 高抗跌分。"""
    strat = EventDrivenStrategy()
    kd = _make_kline()
    kd["close"] = [100.0, 100.5, 101.0, 100.8]
    s = strat._score_resilience(kd)
    assert s >= 0.85


def test_resilience_score_cpi_surprise_big_drop():
    """CPI 超预期且大跌 → 低抗跌分。"""
    strat = EventDrivenStrategy()
    kd = _make_kline()
    kd["close"] = [100.0, 97.0, 96.0, 95.0]
    s = strat._score_resilience(kd)
    assert s <= 0.30


def test_lower_shadow_score_long_shadow():
    """长下影线 → 高分。"""
    strat = EventDrivenStrategy()
    kd = _make_kline()
    kd["high"] = [101.0, 100.5, 100.3]
    kd["low"] = [95.0, 95.5, 95.8]
    kd["open"] = [100.0, 100.0, 100.0]
    kd["close"] = [100.5, 100.2, 100.1]
    s = strat._score_lower_shadow(kd)
    assert s > 0.6


def test_cross_asset_score_all_bullish():
    """黄金涨 + 美债收益率降 + 美元弱 → 高分。"""
    strat = EventDrivenStrategy()
    kd = _make_kline()
    s = strat._score_cross_asset(kd)
    assert s > 0.7


def test_cross_asset_score_no_data_returns_neutral():
    """无跨资产数据 → 0.5。"""
    strat = EventDrivenStrategy()
    kd = _make_kline()
    for k in ("gold_change_pct", "us10y_change_bp", "dxy_change_pct"):
        kd.pop(k, None)
    s = strat._score_cross_asset(kd)
    assert s == 0.5


def test_priced_in_score_high_prob_expectation_phase():
    """预期阶段高 hike_prob → 低分（空头偏向，利空正在被定价）。"""
    strat = EventDrivenStrategy()
    ctx = {"hike_prob": 0.92, "probability_trend": "stable", "cycle_phase": "expectation_jump"}
    s = strat._score_priced_in({}, ctx)
    assert s < 0.2  # 1.0 - 0.92 = 0.08


def test_priced_in_score_post_event():
    """事件落地后 → 高分（利空出尽）。"""
    strat = EventDrivenStrategy()
    ctx = {"hike_prob": 0.10, "probability_trend": "falling", "cycle_phase": "repricing"}
    s = strat._score_priced_in({}, ctx)
    assert s == 0.85


def test_priced_in_score_digest_stable():
    """expectation_digest + 概率稳定 → 预期消化充分，偏中上。"""
    strat = EventDrivenStrategy()
    ctx = {"hike_prob": 0.90, "probability_trend": "stable", "cycle_phase": "expectation_digest"}
    s = strat._score_priced_in({}, ctx)
    # 1.0 - 0.90 = 0.10 + 0.25 = 0.35
    assert 0.30 <= s <= 0.45


def test_short_signal_high_prob_expectation():
    """高加息概率 + 大跌 → SHORT（买预期阶段）。"""
    strat = EventDrivenStrategy()
    kd = _make_kline()
    kd["event_context"]["hike_prob"] = 0.92
    kd["event_context"]["cycle_phase"] = "expectation_jump"
    kd["close"] = [100.0, 97.0, 95.0, 93.0]
    kd["gold_change_pct"] = -0.02
    sig = strat.evaluate(kd)
    assert sig.signal == "short"
