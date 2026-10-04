"""EventDominanceController 测试 — 硬/软/无过滤 + FAIL-OPEN。"""
from event_driven.event_dominance_controller import EventDominanceController


def test_hard_filter_high_conviction():
    edc = EventDominanceController()
    d = edc.decide(conviction=0.92, macro_direction="long")
    assert d.filter_level == "hard"
    assert d.override_subsystems is True
    assert d.modifier == 0.15
    assert d.active is True


def test_soft_filter_mid_conviction():
    edc = EventDominanceController()
    d = edc.decide(conviction=0.78, macro_direction="short")
    assert d.filter_level == "soft"
    assert d.override_subsystems is False
    assert d.modifier == -0.10
    assert d.active is True


def test_no_filter_low_conviction():
    edc = EventDominanceController()
    d = edc.decide(conviction=0.55, macro_direction="long")
    assert d.filter_level == "none"
    assert d.active is False
    assert d.modifier == 0.0


def test_fail_open_not_in_cycle():
    edc = EventDominanceController()
    d = edc.decide(conviction=0.95, macro_direction="long", in_fomc_cycle=False)
    assert d.filter_level == "none"
    assert d.active is False


def test_fail_open_neutral_direction():
    edc = EventDominanceController()
    d = edc.decide(conviction=0.95, macro_direction="neutral")
    assert d.filter_level == "none"


def test_fail_open_low_data_quality():
    edc = EventDominanceController()
    d = edc.decide(conviction=0.95, macro_direction="long", data_quality=0.2)
    assert d.filter_level == "none"
    assert "FAIL-OPEN" in d.reason


def test_manual_override():
    edc = EventDominanceController(manual_override="hard")
    d = edc.decide(conviction=0.30, macro_direction="long")
    assert d.filter_level == "hard"  # 手动覆盖生效


def test_apply_filter_hard_override():
    edc = EventDominanceController()
    d = edc.decide(conviction=0.92, macro_direction="short")
    sub = {"direction": "long", "confidence": 0.6}
    out = edc.apply_filter(sub, d)
    assert out["direction"] == "short"
    assert out["macro_override"] is True


def test_apply_filter_soft_modifier():
    edc = EventDominanceController()
    d = edc.decide(conviction=0.78, macro_direction="long")
    sub = {"direction": "long", "confidence": 0.6}
    out = edc.apply_filter(sub, d)
    assert out["direction"] == "long"  # 软过滤不改方向
    assert abs(out["confidence"] - 0.70) < 1e-6  # 0.6 + 0.10
    assert out["macro_filter_level"] == "soft"


def test_apply_filter_inactive_unchanged():
    edc = EventDominanceController()
    d = edc.decide(conviction=0.30, macro_direction="long")
    sub = {"direction": "long", "confidence": 0.6}
    out = edc.apply_filter(sub, d)
    assert out == sub  # 不激活时原样返回


# ============================================================================
# P0-1 连续 3 笔亏损自动降档（SPEC §4.7.4 安全机制表）
#   过滤模式下连续 3 笔亏损 → 自动从 hard 降为 soft，再连续亏损则 pass_through
# ============================================================================


class TestLossStreakDowngrade:
    """P0-1: 连续亏损降档状态机。"""

    def test_record_outcome_method_exists(self):
        """record_outcome 方法存在且可调用（RED: AttributeError 预期）。"""
        edc = EventDominanceController()
        assert hasattr(edc, "record_outcome"), "EventDominanceController 缺少 record_outcome 方法"

    def test_initial_state_no_downgrade(self):
        """新实例默认无降档，decide() 行为与基线一致。"""
        edc = EventDominanceController()
        d = edc.decide(conviction=0.92, macro_direction="long")
        assert d.filter_level == "hard"  # 高置信度仍为 hard

    def test_three_consecutive_losses_downgrade_hard_to_soft(self):
        """hard 过滤下连续 3 笔 SL → 降级为 soft。"""
        edc = EventDominanceController()
        # 起始 hard
        assert edc.decide(conviction=0.92, macro_direction="long").filter_level == "hard"
        # 连续 3 笔亏损
        for _ in range(3):
            edc.record_outcome("SL")
        # 降级后应为 soft
        d = edc.decide(conviction=0.92, macro_direction="long")
        assert d.filter_level == "soft", f"连续3笔亏损后应降级 hard→soft，实际={d.filter_level}"
        assert "降档" in d.reason or "downgrade" in d.reason.lower()

    def test_six_consecutive_losses_downgrade_hard_to_pass_through(self):
        """hard 过滤下累计 6 笔 SL → 降级两次到 pass_through（none）。"""
        edc = EventDominanceController()
        # 前 3 笔：hard → soft
        for _ in range(3):
            edc.record_outcome("SL")
        assert edc.decide(conviction=0.92, macro_direction="long").filter_level == "soft"
        # 再 3 笔：soft → pass_through
        for _ in range(3):
            edc.record_outcome("SL")
        d = edc.decide(conviction=0.92, macro_direction="long")
        assert d.filter_level == "none", f"累计6笔亏损后应降级 soft→pass_through，实际={d.filter_level}"

    def test_tp_resets_loss_streak_but_no_recovery(self):
        """TP 重置连续亏损计数，但不自动恢复已降档的级别（需人工重置）。"""
        edc = EventDominanceController()
        # 2 笔 SL（未达阈值）
        edc.record_outcome("SL")
        edc.record_outcome("SL")
        # TP 重置计数
        edc.record_outcome("TP")
        # 再 2 笔 SL 仍不应降档（计数已被重置）
        edc.record_outcome("SL")
        edc.record_outcome("SL")
        d = edc.decide(conviction=0.92, macro_direction="long")
        assert d.filter_level == "hard", "TP 重置后累计2笔不应降档"

    def test_downgrade_level_field_exposed(self):
        """降档后 decide() 返回的 DominanceDecision 应暴露 downgrade 字段。"""
        edc = EventDominanceController()
        for _ in range(3):
            edc.record_outcome("SL")
        d = edc.decide(conviction=0.92, macro_direction="long")
        assert hasattr(d, "downgrade") or "downgrade" in d.raw, "应暴露当前降档状态供审计"


# ============================================================================
# P0-2 1 小时置信度漂移 >0.15 立即降档（SPEC §4.7.4 安全机制表）
#   conviction 1 小时内下降 >0.15 → 立即降档（hard→soft→pass_through）
# ============================================================================


class TestConvictionDriftDowngrade:
    """P0-2: 置信度漂移监控降档。"""

    def test_drift_detection_method_exists(self):
        """_check_conviction_drift 方法存在（RED: AttributeError 预期）。"""
        edc = EventDominanceController()
        assert hasattr(edc, "_check_conviction_drift"), "缺少 _check_conviction_drift 方法"

    def test_no_drift_when_conviction_stable(self):
        """1 小时内 conviction 平稳（漂移<0.15）→ 不降档。"""
        edc = EventDominanceController()
        import time
        t0 = time.time()
        # 记录高置信度
        edc.decide(conviction=0.90, macro_direction="long")
        # 30 分钟后轻微下降 0.10
        import time as _t
        drift_triggered = edc._check_conviction_drift(0.80, now=_t.time() + 1800)
        assert drift_triggered is False, "漂移 0.10 不应触发降档"

    def test_drift_gt_015_triggers_downgrade(self):
        """1 小时内 conviction 下降 >0.15 → 触发降档。"""
        edc = EventDominanceController()
        import time
        t0 = time.time()
        # 初始高置信度
        edc.decide(conviction=0.90, macro_direction="long")
        # 30 分钟后 conviction 下降到 0.70（漂移 0.20 > 0.15）
        triggered = edc._check_conviction_drift(0.70, now=t0 + 1800)
        assert triggered is True, "30 分钟内 conviction 下降 0.20 应触发降档"

    def test_drift_outside_1h_window_ignored(self):
        """超过 1 小时窗口的 conviction 记录不参与漂移计算。"""
        edc = EventDominanceController()
        import time
        t0 = time.time()
        # 初始高置信度
        edc.decide(conviction=0.90, macro_direction="long")
        # 2 小时后 conviction 下降到 0.50（漂移 0.40 但超出窗口）
        triggered = edc._check_conviction_drift(0.50, now=t0 + 7200)
        assert triggered is False, "超出 1 小时窗口的记录不应触发降档"

    def test_drift_downgrade_hard_to_soft(self):
        """hard 过滤下 conviction 漂移触发 → 立即降级为 soft。"""
        edc = EventDominanceController()
        import time
        t0 = time.time()
        # 第一次高置信度
        d1 = edc.decide(conviction=0.90, macro_direction="long")
        assert d1.filter_level == "hard"
        # 30 分钟后置信度骤降（漂移 0.20）
        d2 = edc.decide(
            conviction=0.70,
            macro_direction="long",
            now=t0 + 1800,
        )
        assert d2.filter_level == "soft", f"漂移触发后应降级 hard→soft，实际={d2.filter_level}"

    def test_drift_does_not_affect_low_conviction(self):
        """低置信度（none）漂移触发不产生额外降级（已为最低档）。"""
        edc = EventDominanceController()
        import time
        t0 = time.time()
        edc.decide(conviction=0.50, macro_direction="long")  # none
        d = edc.decide(conviction=0.30, macro_direction="long", now=t0 + 1800)
        assert d.filter_level == "none", "低置信度漂移后仍应为 none"

    def test_reset_downgrade_method_exists(self):
        """人工重置降档的方法存在（恢复子系统自主权）。"""
        edc = EventDominanceController()
        for _ in range(3):
            edc.record_outcome("SL")
        # 降档后应可通过人工重置恢复
        assert hasattr(edc, "reset_downgrade"), "缺少 reset_downgrade 人工重置方法"
        edc.reset_downgrade()
        d = edc.decide(conviction=0.92, macro_direction="long")
        assert d.filter_level == "hard", "reset_downgrade 后应恢复到静态阈值判定"


# ============================================================================
# P1-1 过滤决策日志持久化（SPEC §4.7.4 日志审计）
#   每次过滤决策记录 signal + event_ctx + filter_result 供回测分析
# ============================================================================


class TestFilterDecisionAudit:
    """P1-1: 过滤决策日志持久化审计。"""

    def test_add_filter_decision_method_exists(self):
        """EventCaseLibrary 有 add_filter_decision 方法（RED: AttributeError 预期）。"""
        from event_driven.event_case_library import EventCaseLibrary
        lib = EventCaseLibrary(storage_path="/tmp/_test_edc_filter_empty.json")
        assert hasattr(lib, "add_filter_decision"), "EventCaseLibrary 缺少 add_filter_decision 方法"

    def test_apply_filter_accepts_case_library_param(self):
        """apply_filter 接受 case_library 参数并记录过滤决策。"""
        edc = EventDominanceController()
        d = edc.decide(conviction=0.92, macro_direction="short")
        sub = {"direction": "long", "confidence": 0.6}
        recorded = []

        class _FakeLib:
            def add_filter_decision(self, record):
                recorded.append(record)

        out = edc.apply_filter(
            sub, d,
            case_library=_FakeLib(),
            event_ctx={"cycle_phase": "event", "hike_prob": 0.7},
        )
        assert len(recorded) == 1, "应记录一条过滤决策"
        rec = recorded[0]
        # SPEC §4.7.4: 记录 signal + event_ctx + filter_result
        assert rec["filter_level"] == "hard"
        assert rec["subsystem_signal"]["direction"] == "long"
        assert rec["filter_result"]["direction"] == "short"
        assert rec["event_ctx"]["cycle_phase"] == "event"
        assert "timestamp" in rec, "应包含时间戳供回测时序分析"

    def test_apply_filter_without_case_library_backward_compat(self):
        """不传 case_library 时 apply_filter 行为不变（向后兼容）。"""
        edc = EventDominanceController()
        d = edc.decide(conviction=0.92, macro_direction="short")
        sub = {"direction": "long", "confidence": 0.6}
        out = edc.apply_filter(sub, d)  # 不传 case_library
        assert out["direction"] == "short"  # 硬过滤仍生效
        assert out["macro_override"] is True

    def test_add_filter_decision_persists_to_file(self, tmp_path):
        """add_filter_decision 持久化到 filter_decisions.json 文件。"""
        from event_driven.event_case_library import EventCaseLibrary
        import json
        storage = tmp_path / "filter_decisions.json"
        lib = EventCaseLibrary(storage_path=str(tmp_path / "cases.json"))
        lib.add_filter_decision({
            "filter_level": "hard",
            "conviction": 0.92,
            "macro_direction": "short",
            "subsystem_signal": {"direction": "long"},
            "filter_result": {"direction": "short"},
            "event_ctx": {"cycle_phase": "event"},
            "reason": "test",
        })
        # 重新加载验证持久化
        assert storage.exists() or (tmp_path / "filter_decisions.json").exists()
        data = json.loads(storage.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["filter_level"] == "hard"

    def test_query_filter_decisions_method_exists(self):
        """EventCaseLibrary 有 query_filter_decisions 方法供回测检索。"""
        from event_driven.event_case_library import EventCaseLibrary
        lib = EventCaseLibrary(storage_path="/tmp/_test_edc_query_empty.json")
        assert hasattr(lib, "query_filter_decisions"), "缺少 query_filter_decisions 方法"


# ============================================================================
# P1-2 EventDominanceController 独立开关门控（硬约束双层门控模式）
#   enable_contradiction_driven_layer + enable_event_dominance 双层门控
# ============================================================================


class TestEventDominanceSwitchGate:
    """P1-2: EventDominanceController 独立开关门控。"""

    def test_enable_event_dominance_switch_in_agi_config(self):
        """agi_config.py 含 enable_event_dominance 开关（RED: KeyError 预期）。"""
        from dreambuddy_evolution.agi_config import AGI_SWITCHES
        assert "enable_event_dominance" in AGI_SWITCHES, "AGI_SWITCHES 缺少 enable_event_dominance 开关"

    def test_is_enabled_classmethod_exists(self):
        """EventDominanceController 有 is_enabled() 类方法（RED: AttributeError 预期）。"""
        assert hasattr(EventDominanceController, "is_enabled"), "缺少 is_enabled 类方法"

    def test_is_enabled_returns_true_when_both_switches_on(self):
        """总开关 + 子开关都开启时 is_enabled() 返回 True。"""
        from dreambuddy_evolution.agi_config import set_switch
        set_switch("enable_agi_core", True)
        set_switch("enable_contradiction_driven_layer", True)
        set_switch("enable_event_dominance", True)
        assert EventDominanceController.is_enabled() is True

    def test_is_enabled_false_when_subswitch_off(self):
        """子开关 enable_event_dominance=False 时 is_enabled() 返回 False。"""
        from dreambuddy_evolution.agi_config import set_switch
        set_switch("enable_agi_core", True)
        set_switch("enable_contradiction_driven_layer", True)
        set_switch("enable_event_dominance", False)
        assert EventDominanceController.is_enabled() is False

    def test_is_enabled_false_when_master_off(self):
        """总开关 enable_contradiction_driven_layer=False 时 is_enabled() 返回 False。"""
        from dreambuddy_evolution.agi_config import set_switch
        set_switch("enable_contradiction_driven_layer", False)
        set_switch("enable_event_dominance", True)
        assert EventDominanceController.is_enabled() is False

    def test_is_enabled_failopen_on_exception(self):
        """is_enabled 异常时 FAIL-OPEN 返回 False（安全默认）。"""
        # 通过 monkeypatch agi_config 模块引发异常
        import sys
        original = sys.modules.get("dreambuddy_evolution.agi_config")
        try:
            class _BrokenMod:
                @staticmethod
                def is_enabled(name):
                    raise RuntimeError("simulated")
            sys.modules["dreambuddy_evolution.agi_config"] = _BrokenMod()
            assert EventDominanceController.is_enabled() is False
        finally:
            if original is not None:
                sys.modules["dreambuddy_evolution.agi_config"] = original
