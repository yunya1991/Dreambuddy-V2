"""Phase 3: 双保险 L1/L2/L3 RED 测试。

L1 = 审计标签（强制开启，写入 trades_table 2 列 war_state + overlap_pct）
L2 = 同向放大抑制（默认开，war_state=COOLDOWN/FREEZE 且 pos>0.5 且 overlap>0.40 → cap 0.40）
L3 = 反向熔断（默认关，war_state 防守档 + BCRM2 连续 3 笔 30%+仓位亏损 → pause 4h）
"""
import pandas as pd
import pytest
from datetime import datetime, timezone, timedelta


@pytest.fixture
def guard_default_config():
    return {
        "enable_l1_audit_tag": True,
        "enable_l2_same_direction_suppression": True,
        "enable_l3_conflict_circuit_breaker": False,
        "l2_war_state_threshold": "COOLDOWN",
        "l2_position_cap_before": 0.50,
        "l2_position_cap_after": 0.40,
        "l2_overlap_pct_threshold": 0.40,
        "l3_consecutive_losses": 3,
        "l3_pause_duration_hours": 4,
    }


class TestDualGuardL1AuditTag:
    """L1 强制审计标签。"""

    def test_guard_constants_config_switch_exists(self):
        """screen_engine（或等价 BCRM2 config 对象）含 FEATURE_INTEGRATION_GUARD。"""
        try:
            from scripts.memory_l4.bcrm2 import screen_engine as se
            assert hasattr(se, "FEATURE_INTEGRATION_GUARD") or hasattr(se.Bcrm2Config, "FEATURE_INTEGRATION_GUARD")
        except (ImportError, AttributeError):
            # screen_engine 可能在 experiments 模块。两个入口都需要检查。
            import importlib
            ok = False
            for mod in ["experiments.ab-trading.screen_engine",
                        "experiments.ab_trading.screen_engine"]:
                try:
                    m = importlib.import_module(mod)
                    ok = hasattr(m, "FEATURE_INTEGRATION_GUARD")
                    if ok:
                        break
                except Exception:
                    pass
            if not ok:
                # 最后兜底：在 screen_engine.py 同级或 config 同级定义
                raise AssertionError("FEATURE_INTEGRATION_GUARD 配置未定义（FAIL-RED）")

    def test_feature_guard_definition_exists(self, guard_default_config):
        """feature_integration_guard.py 或 screen_engine.py 中应有 get_feature_integration_guard()。"""
        # 先看 screen_engine
        try:
            from experiments.ab_trading.screen_engine import (
                get_feature_integration_guard, FEATURE_INTEGRATION_GUARD
            )
            g = get_feature_integration_guard()
            for k in guard_default_config:
                assert k in g, f"缺配置项 {k}"
        except Exception:
            from scripts.memory_l4.bcrm2.screen_engine import (
                get_feature_integration_guard, FEATURE_INTEGRATION_GUARD
            )
            g = get_feature_integration_guard()
            for k in guard_default_config:
                assert k in g, f"缺配置项 {k}"

    def test_l1_audit_attach_adds_two_columns(self):
        """attach_l1_audit(trade_dict, war_state, overlap_pct) → dict 加 2 字段。"""
        # 该函数应放 BCRM2 决策入口附近或独立 guard 模块
        try:
            from experiments.ab_trading.screen_engine import attach_l1_audit
        except Exception:
            from scripts.memory_l4.bcrm2.screen_engine import attach_l1_audit
        trade = {"trade_id": "T1", "pnl": 10}
        out = attach_l1_audit(trade, "COOLDOWN", 0.18)
        assert out["strategic_war_state"] == "COOLDOWN"
        assert out["feature_overlap_pct"] == 0.18

    def test_overlap_pct_compute_fn(self):
        """compute_source_overlap_pct(lstar_sources, strategic_sources) 计算来源重叠率。
        示例: L* 用了 {pn_us_vix, treasury_btc, whale_netflow} (3)
              战略层用了 {pn_us_vix, pn_us_fedfunds, pn_btc_dominance, treasury_btc, stablecoin} (5)
              重叠 2 个 → overlap = 2 / min(3,5) = 0.667
        """
        try:
            from experiments.ab_trading.screen_engine import compute_source_overlap_pct
        except Exception:
            from scripts.memory_l4.bcrm2.screen_engine import compute_source_overlap_pct
        pct = compute_source_overlap_pct(
            {"pn_us_vix", "treasury_btc", "whale_netflow"},
            {"pn_us_vix", "pn_us_fedfunds", "pn_btc_dominance", "treasury_btc", "stablecoin"},
        )
        assert abs(pct - 0.667) < 0.01
        # 无重叠 → 0
        assert compute_source_overlap_pct({"a", "b"}, {"c", "d", "e"}) == 0.0


class TestDualGuardL2SameDirectionSuppression:
    """L2 同向放大抑制。"""

    def test_l2_triggers_and_caps(self, guard_default_config):
        """apply_l2_if_needed(position_pct=0.62, war_state='FREEZE', overlap_pct=0.46, guard_cfg) → 0.40。"""
        try:
            from experiments.ab_trading.screen_engine import apply_l2_if_needed
        except Exception:
            from scripts.memory_l4.bcrm2.screen_engine import apply_l2_if_needed
        new_pos, log_line = apply_l2_if_needed(
            position_pct=0.62, war_state="FREEZE", overlap_pct=0.46,
            guard_cfg=guard_default_config, trade_id="T1",
        )
        assert abs(new_pos - 0.40) < 1e-9, f"未 cap 到 0.40，得到 {new_pos}"
        assert "[L2-SUPPRESS]" in log_line
        assert "FREEZE" in log_line and "0.62→0.40" in log_line

    def test_l2_not_trigger_overlap_low(self, guard_default_config):
        """overlap_pct = 0.18 (<0.40) → 不触发，保留 0.62。"""
        try:
            from experiments.ab_trading.screen_engine import apply_l2_if_needed
        except Exception:
            from scripts.memory_l4.bcrm2.screen_engine import apply_l2_if_needed
        new_pos, log_line = apply_l2_if_needed(
            position_pct=0.62, war_state="FREEZE", overlap_pct=0.18,
            guard_cfg=guard_default_config, trade_id="T1",
        )
        assert new_pos == 0.62

    def test_l2_not_trigger_war_state_below(self, guard_default_config):
        """war_state='ALLOW'（低于 COOLDOWN 阈值）→ 不触发。"""
        try:
            from experiments.ab_trading.screen_engine import apply_l2_if_needed
        except Exception:
            from scripts.memory_l4.bcrm2.screen_engine import apply_l2_if_needed
        new_pos, _ = apply_l2_if_needed(
            position_pct=0.62, war_state="ALLOW", overlap_pct=0.46,
            guard_cfg=guard_default_config, trade_id="T1",
        )
        assert new_pos == 0.62

    def test_l2_switch_disabled_bypasses(self, guard_default_config):
        """enable_l2=False → 直接原 pos。"""
        try:
            from experiments.ab_trading.screen_engine import apply_l2_if_needed
        except Exception:
            from scripts.memory_l4.bcrm2.screen_engine import apply_l2_if_needed
        cfg = dict(guard_default_config)
        cfg["enable_l2_same_direction_suppression"] = False
        new_pos, _ = apply_l2_if_needed(
            position_pct=0.62, war_state="FREEZE", overlap_pct=0.46,
            guard_cfg=cfg, trade_id="T1",
        )
        assert new_pos == 0.62


class TestDualGuardL3ReverseCircuitBreaker:
    """L3 反向冲突熔断（默认关）。"""

    def test_l3_default_disabled(self, guard_default_config):
        """L3 默认开关关闭，即使满足连续亏损也不暂停。check_l3_and_maybe_pause 返回 (False, None, None)。"""
        try:
            from experiments.ab_trading.screen_engine import check_l3_and_maybe_pause
        except Exception:
            from scripts.memory_l4.bcrm2.screen_engine import check_l3_and_maybe_pause
        recent = [
            {"trade_id": f"T{i}", "position_pct": 0.40, "pnl": -10.0, "war_state": "COOLDOWN"}
            for i in range(3)
        ]
        paused, until_ts, log_line = check_l3_and_maybe_pause(
            recent, guard_cfg=guard_default_config, now=pd.Timestamp("2026-01-01 12:00", tz="UTC"),
        )
        assert paused is False

    def test_l3_enabled_and_triggers(self, guard_default_config):
        """L3 开启 + 连续 3 笔 ≥30% 仓位亏损 + war_state 防守档 → pause 4h，打 [L3-CIRCUIT] 日志。"""
        try:
            from experiments.ab_trading.screen_engine import check_l3_and_maybe_pause
        except Exception:
            from scripts.memory_l4.bcrm2.screen_engine import check_l3_and_maybe_pause
        cfg = dict(guard_default_config)
        cfg["enable_l3_conflict_circuit_breaker"] = True
        recent = [
            {"trade_id": f"T{i}", "position_pct": 0.40, "pnl": -10.0, "war_state": "COOLDOWN"}
            for i in range(3)
        ]
        now = pd.Timestamp("2026-01-01 12:00", tz="UTC")
        paused, until_ts, log_line = check_l3_and_maybe_pause(recent, guard_cfg=cfg, now=now)
        assert paused is True
        assert until_ts == now + pd.Timedelta(hours=4)
        assert "[L3-CIRCUIT]" in log_line
        assert "streak=3" in log_line and "pause=4h" in log_line

    def test_l3_needs_defensive_war_state(self, guard_default_config):
        """war_state=ALLOW（非防守档）即使 3 连亏也不触发。"""
        try:
            from experiments.ab_trading.screen_engine import check_l3_and_maybe_pause
        except Exception:
            from scripts.memory_l4.bcrm2.screen_engine import check_l3_and_maybe_pause
        cfg = dict(guard_default_config)
        cfg["enable_l3_conflict_circuit_breaker"] = True
        recent = [
            {"trade_id": f"T{i}", "position_pct": 0.40, "pnl": -10.0, "war_state": "ALLOW"}
            for i in range(3)
        ]
        paused, _, _ = check_l3_and_maybe_pause(
            recent, guard_cfg=cfg, now=pd.Timestamp("2026-01-01", tz="UTC"),
        )
        assert paused is False

    def test_l3_needs_high_position_losses(self, guard_default_config):
        """1 笔是 10% 仓位（<30% 阈值）→ streak 计数不累加 → 不触发。"""
        try:
            from experiments.ab_trading.screen_engine import check_l3_and_maybe_pause
        except Exception:
            from scripts.memory_l4.bcrm2.screen_engine import check_l3_and_maybe_pause
        cfg = dict(guard_default_config)
        cfg["enable_l3_conflict_circuit_breaker"] = True
        recent = [
            {"trade_id": "T0", "position_pct": 0.10, "pnl": -10.0, "war_state": "COOLDOWN"},  # <30% 忽略
            {"trade_id": "T1", "position_pct": 0.40, "pnl": -10.0, "war_state": "COOLDOWN"},
            {"trade_id": "T2", "position_pct": 0.40, "pnl": -10.0, "war_state": "COOLDOWN"},
        ]
        paused, _, _ = check_l3_and_maybe_pause(
            recent, guard_cfg=cfg, now=pd.Timestamp("2026-01-01", tz="UTC"),
        )
        assert paused is False
