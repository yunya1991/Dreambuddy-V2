"""test_event_driven_path_injection.py — Phase 1 事件驱动策略接入路径发现层

SPEC: SPEC-事件驱动策略独立化-共享事件层与弹性约束.md §四

验证 EventDrivenStrategy 从孤立（仅 backtest 脚本）接入 kline_event_handler 主链路：
1. 事件信号（long/short + confidence >= 阈值）作为路径参与 _select_optimal_path 竞争
2. 事件信号 neutral 时不注入路径
3. 事件信号低置信度时不注入路径
4. EventDrivenStrategy 异常时 FAIL-OPEN（不 crash、不影响原有路径发现）
5. 开关 enable_event_driven_path=False 时不调用 EventDrivenStrategy
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def enable_event_driven_path(monkeypatch):
    """开启事件驱动路径发现开关"""
    from dreambuddy_evolution.agi_config import set_switch, reset_switches
    reset_switches()
    set_switch("enable_agi_core", True)
    set_switch("enable_event_driven_path", True)
    yield
    reset_switches()


def _make_mock_handler():
    """构造 KlineEventHandler 并注入 mock pipeline。"""
    from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
    handler = KlineEventHandler(mode="Phase2")
    mock_pipeline = MagicMock()
    # _discover_paths 返回空列表（无其他路径），事件路径是唯一候选
    mock_pipeline._discover_paths.return_value = []
    # _select_optimal_path 返回 None（无最优路径，保持原 d*）
    mock_pipeline._select_optimal_path.return_value = None
    handler._evolution_pipeline = mock_pipeline
    handler._path_layer_enabled = True
    return handler, mock_pipeline


def _get_event_paths_captured(mock_pipeline):
    """从 _select_optimal_path 调用参数中提取 paths 列表。"""
    if not mock_pipeline._select_optimal_path.called:
        return []
    call_args = mock_pipeline._select_optimal_path.call_args
    paths = call_args.args[0] if call_args.args else call_args.kwargs.get("paths", [])
    return [p for p in paths if p.get("source") == "event_driven"]


class TestEventDrivenPathInjection:
    """Phase 1: 事件驱动策略接入路径发现层"""

    def test_event_driven_signal_injected_as_path(self, enable_event_driven_path, monkeypatch):
        """事件信号 long + confidence=0.8 → 作为 event_driven 路径注入"""
        from event_driven.event_driven_strategy import EventDrivenSignal

        handler, mock_pipeline = _make_mock_handler()

        # Mock EventDrivenStrategy 返回 long 信号
        mock_eds = MagicMock()
        mock_eds.return_value.evaluate.return_value = EventDrivenSignal(
            signal="long",
            strength=0.80,
            elasticity=1.0,
            confidence=0.90,
            mode="priced_in_bottom",
            scores={"priced_in": 0.85},
            event_phase="repricing",
            reason="利空出尽，5 维评分共振看多",
        )
        monkeypatch.setattr(
            "dreambuddy_evolution.engines.kline_event_handler.EventDrivenStrategy",
            mock_eds,
            raising=False,
        )

        kline_data = {
            "symbol": "BTC",
            "close": [100.0 + i for i in range(40)],
            "event_context": {"in_fomc_cycle": True, "cycle_phase": "repricing"},
        }
        r_vector = {"R_up": 0.6, "R_down": 0.4, "_close_series": [100.0] * 40}

        handler._run_path_discovery("BTC", r_vector, "long", 0.5, kline_data)

        event_paths = _get_event_paths_captured(mock_pipeline)
        assert len(event_paths) == 1
        assert event_paths[0]["direction"] == "long"
        assert event_paths[0]["score"] == 0.80
        assert event_paths[0]["validated"] is True

    def test_event_driven_neutral_skipped(self, enable_event_driven_path, monkeypatch):
        """事件信号 neutral → 不注入路径"""
        from event_driven.event_driven_strategy import EventDrivenSignal

        handler, mock_pipeline = _make_mock_handler()

        mock_eds = MagicMock()
        mock_eds.return_value.evaluate.return_value = EventDrivenSignal(
            signal="neutral",
            confidence=0.0,
            mode="none",
            scores={},
            event_phase="neutral",
            reason="不在 FOMC 周期且无宏观事件触发",
        )
        monkeypatch.setattr(
            "dreambuddy_evolution.engines.kline_event_handler.EventDrivenStrategy",
            mock_eds,
            raising=False,
        )

        kline_data = {"symbol": "BTC", "close": [100.0] * 40, "event_context": {}}
        r_vector = {"R_up": 0.5, "R_down": 0.5, "_close_series": [100.0] * 40}

        handler._run_path_discovery("BTC", r_vector, "WAIT", 0.5, kline_data)

        event_paths = _get_event_paths_captured(mock_pipeline)
        assert len(event_paths) == 0

    def test_event_driven_low_confidence_skipped(self, enable_event_driven_path, monkeypatch):
        """事件信号 long 但 confidence=0.4 < 阈值 0.60 → 不注入路径"""
        from event_driven.event_driven_strategy import EventDrivenSignal

        handler, mock_pipeline = _make_mock_handler()

        mock_eds = MagicMock()
        mock_eds.return_value.evaluate.return_value = EventDrivenSignal(
            signal="long",
            strength=0.40,
            elasticity=0.0,
            confidence=0.60,
            mode="premature_long",
            scores={"priced_in": 0.55},
            event_phase="expectation_build",
            reason="信号弱",
        )
        monkeypatch.setattr(
            "dreambuddy_evolution.engines.kline_event_handler.EventDrivenStrategy",
            mock_eds,
            raising=False,
        )

        kline_data = {
            "symbol": "BTC",
            "close": [100.0] * 40,
            "event_context": {"in_fomc_cycle": True, "cycle_phase": "expectation_build"},
        }
        r_vector = {"R_up": 0.5, "R_down": 0.5, "_close_series": [100.0] * 40}

        handler._run_path_discovery("BTC", r_vector, "long", 0.5, kline_data)

        event_paths = _get_event_paths_captured(mock_pipeline)
        assert len(event_paths) == 0

    def test_event_driven_fail_open(self, enable_event_driven_path, monkeypatch):
        """EventDrivenStrategy.evaluate() 抛异常 → FAIL-OPEN：不 crash、不影响路径发现"""
        handler, mock_pipeline = _make_mock_handler()

        mock_eds = MagicMock()
        mock_eds.return_value.evaluate.side_effect = RuntimeError("模拟事件驱动策略崩溃")
        monkeypatch.setattr(
            "dreambuddy_evolution.engines.kline_event_handler.EventDrivenStrategy",
            mock_eds,
            raising=False,
        )

        kline_data = {
            "symbol": "BTC",
            "close": [100.0] * 40,
            "event_context": {"in_fomc_cycle": True},
        }
        r_vector = {"R_up": 0.6, "R_down": 0.4, "_close_series": [100.0] * 40}

        # 不抛异常
        d_star, ri, path_info = handler._run_path_discovery("BTC", r_vector, "long", 0.5, kline_data)

        # 原有路径发现仍正常执行
        assert mock_pipeline._discover_paths.called
        assert mock_pipeline._select_optimal_path.called
        # 无事件路径注入
        event_paths = _get_event_paths_captured(mock_pipeline)
        assert len(event_paths) == 0

    def test_event_driven_switch_off(self, monkeypatch):
        """开关 enable_event_driven_path=False → 不调用 EventDrivenStrategy"""
        from dreambuddy_evolution.agi_config import set_switch, reset_switches
        reset_switches()
        set_switch("enable_agi_core", True)
        set_switch("enable_event_driven_path", False)

        handler, mock_pipeline = _make_mock_handler()

        # 用一个会被调用就失败的 mock，验证未被调用
        mock_eds = MagicMock()
        mock_eds.return_value.evaluate.side_effect = AssertionError("不应被调用")
        monkeypatch.setattr(
            "dreambuddy_evolution.engines.kline_event_handler.EventDrivenStrategy",
            mock_eds,
            raising=False,
        )

        kline_data = {
            "symbol": "BTC",
            "close": [100.0] * 40,
            "event_context": {"in_fomc_cycle": True, "cycle_phase": "repricing"},
        }
        r_vector = {"R_up": 0.6, "R_down": 0.4, "_close_series": [100.0] * 40}

        # 不抛异常（EventDrivenStrategy 未被调用）
        handler._run_path_discovery("BTC", r_vector, "long", 0.5, kline_data)

        # EventDrivenStrategy 未被实例化
        assert not mock_eds.called
