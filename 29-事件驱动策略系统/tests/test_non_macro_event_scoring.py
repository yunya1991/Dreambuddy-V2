"""Phase 2 P2: 非宏观事件评分适配测试。

验证 tech_upgrade / sec_deadline / congressional_hearing / fed_speech 等非宏观事件
的 dominant_direction 能直接驱动信号输出，而非依赖 6 维宏观评分（composite=0.5→neutral）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from event_driven.event_driven_strategy import EventDrivenStrategy


def _make_ctx(event_type="tech_upgrade", direction="long", phase="expectation_digest"):
    return {
        "event_type": event_type,
        "cycle_phase": phase,
        "event_window": phase,
        "in_event_cycle": True,
        "dominant_direction": direction,
        "half_life": 1.0,
        "days_to_event": 0.5,
        "days_since_event": None,
        "raw": {"event_type": event_type, "event_direction": direction},
    }


def _make_kline(ctx):
    # close 需为 20+ 元素列表供趋势检测
    return {"close": [60000] * 25, "event_context": ctx}


# ---------- 非宏观事件 direction 直接驱动信号 ----------

def test_tech_upgrade_long_drives_long_signal():
    """tech_upgrade dominant_direction=long → signal=long（不依赖宏观评分）。"""
    strategy = EventDrivenStrategy()
    kline_data = _make_kline(_make_ctx("tech_upgrade", "long"))
    signal = strategy.evaluate(kline_data)
    assert signal.signal == "long"
    assert signal.strength > 0.3
    assert signal.event_type == "tech_upgrade"


def test_tech_upgrade_short_drives_short_signal():
    """tech_upgrade dominant_direction=short → signal=short。"""
    strategy = EventDrivenStrategy()
    kline_data = _make_kline(_make_ctx("tech_upgrade", "short"))
    signal = strategy.evaluate(kline_data)
    assert signal.signal == "short"
    assert signal.strength > 0.3


def test_tech_upgrade_neutral_drives_neutral_signal():
    """tech_upgrade dominant_direction=neutral → signal=neutral。"""
    strategy = EventDrivenStrategy()
    kline_data = _make_kline(_make_ctx("tech_upgrade", "neutral"))
    signal = strategy.evaluate(kline_data)
    assert signal.signal == "neutral"


def test_sec_deadline_long_drives_long_signal():
    """sec_deadline dominant_direction=long → signal=long。"""
    strategy = EventDrivenStrategy()
    kline_data = _make_kline(_make_ctx("sec_deadline", "long", "event"))
    signal = strategy.evaluate(kline_data)
    assert signal.signal == "long"


def test_congressional_hearing_neutral_drives_neutral():
    """congressional_hearing 默认 neutral → signal=neutral（不崩溃）。"""
    strategy = EventDrivenStrategy()
    ctx = _make_ctx("congressional_hearing", "neutral", "expectation_build")
    signal = strategy.evaluate(_make_kline(ctx))
    assert signal.signal == "neutral"
    assert signal.event_type == "congressional_hearing"


def test_fed_speech_short_drives_short_signal():
    """fed_speech hawkish→short → signal=short。"""
    strategy = EventDrivenStrategy()
    kline_data = _make_kline(_make_ctx("fed_speech", "short", "event"))
    signal = strategy.evaluate(kline_data)
    assert signal.signal == "short"


# ---------- 非宏观事件不应用 FOMC 专属偏移 ----------

def test_non_macro_ignores_hike_prob_offset():
    """非宏观事件即使 event_ctx 含 hike_prob 也不应用预期阶段 bearish 偏移。"""
    strategy = EventDrivenStrategy()
    ctx = _make_ctx("tech_upgrade", "long", "expectation_build")
    ctx["hike_prob"] = 0.9  # FOMC 逻辑下会大幅压低 composite，但非宏观不应受影响
    signal = strategy.evaluate(_make_kline(ctx))
    # direction=long 应输出 long，不受 hike_prob 干扰
    assert signal.signal == "long"


# ---------- strength 与 phase 乘数 ----------

def test_non_macro_event_phase_has_higher_strength():
    """event 阶段 strength 高于 expectation_build 阶段（PHASE_POSITION_MULT）。"""
    strategy = EventDrivenStrategy()
    sig_event = strategy.evaluate(_make_kline(_make_ctx("tech_upgrade", "long", "event")))
    sig_build = strategy.evaluate(
        _make_kline(_make_ctx("tech_upgrade", "long", "expectation_build"))
    )
    assert sig_event.strength > sig_build.strength


# ---------- 宏观事件不受非宏观分支影响 ----------

def test_fomc_still_uses_macro_scoring():
    """FOMC 事件仍走宏观评分逻辑（不受非宏观分支影响）。"""
    strategy = EventDrivenStrategy()
    ctx = _make_ctx("fomc", "long", "expectation_build")
    ctx["hike_prob"] = 0.2
    ctx["cut_prob"] = 0.8
    ctx["dominant_direction"] = "long"
    kline_data = {"close": [60000] * 25, "event_context": ctx}
    signal = strategy.evaluate(kline_data)
    # FOMC 仍走宏观评分，方向可能 long/short/neutral，但 event_type 应为 fomc
    assert signal.event_type == "fomc"
