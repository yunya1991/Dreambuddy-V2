"""超时换仓信号扫描 TDD 测试

核心改动：超时评估从「单向更强信号」改为「全池多空相对强弱」。

背景（用户洞察，2026-09-10）：
  当前 has_stronger_signal 只检查同方向（多头只看更强多头），
  但市场空头格局明显时，空头信号更强，应平掉浮盈多头换空。
  例：MU多头超时浮盈，但COIN空头conf=0.98更强 → 应平MU开COIN空。

扫描范围：
  - evolution 信号池（_last_evolution_kline_by_coin）
  - BCRM2.0 信号池（_latest_bcrm_inference）
  - 所有币种、所有方向（long/short）
  - 排除当前持仓币种自身

阈值：
  - confidence > 当前持仓 confidence + 0.15
  - confidence >= 0.65（建仓最低门槛）
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


class TestFindStrongestRotationSignal:
    """全池多空最强换仓信号扫描"""

    def test_same_direction_stronger_signal_detected(self):
        """同方向更强信号 → 检测到（保留原行为）"""
        from dreambuddy_evolution.engines.entry_signal_governor import (
            find_strongest_rotation_signal,
        )
        evo_signals = {
            "COIN": {"top_path_confidence": 0.90, "top_path_direction": "long"},
        }
        bcrm_signals = {}
        result = find_strongest_rotation_signal(
            evo_signals=evo_signals,
            bcrm_signals=bcrm_signals,
            exclude_coin="ETH",
            cur_confidence=0.70,
            cur_direction="long",
        )
        assert result is not None
        assert result["coin"] == "COIN"
        assert result["direction"] == "long"
        assert result["confidence"] == pytest.approx(0.90)
        assert result["is_opposite"] is False

    def test_opposite_direction_stronger_signal_detected(self):
        """反向更强信号 → 检测到（核心新增）"""
        from dreambuddy_evolution.engines.entry_signal_governor import (
            find_strongest_rotation_signal,
        )
        evo_signals = {}
        bcrm_signals = {
            "COIN": {"direction": "DOWN", "confidence": 0.98},
        }
        result = find_strongest_rotation_signal(
            evo_signals=evo_signals,
            bcrm_signals=bcrm_signals,
            exclude_coin="MU",
            cur_confidence=0.82,
            cur_direction="long",
        )
        assert result is not None
        assert result["coin"] == "COIN"
        assert result["direction"] == "short"
        assert result["is_opposite"] is True
        assert result["source"] == "bcrm"

    def test_exclude_current_coin(self):
        """排除当前持仓币种自身"""
        from dreambuddy_evolution.engines.entry_signal_governor import (
            find_strongest_rotation_signal,
        )
        evo_signals = {
            "ETH": {"top_path_confidence": 0.99, "top_path_direction": "long"},
            "COIN": {"top_path_confidence": 0.90, "top_path_direction": "long"},
        }
        bcrm_signals = {}
        result = find_strongest_rotation_signal(
            evo_signals=evo_signals,
            bcrm_signals=bcrm_signals,
            exclude_coin="ETH",  # 排除 ETH 自身
            cur_confidence=0.70,
            cur_direction="long",
        )
        assert result is not None
        assert result["coin"] == "COIN"  # 不应返回 ETH

    def test_no_signal_meets_threshold(self):
        """无信号达到阈值 → 返回 None"""
        from dreambuddy_evolution.engines.entry_signal_governor import (
            find_strongest_rotation_signal,
        )
        evo_signals = {
            "COIN": {"top_path_confidence": 0.80, "top_path_direction": "long"},
        }
        bcrm_signals = {}
        result = find_strongest_rotation_signal(
            evo_signals=evo_signals,
            bcrm_signals=bcrm_signals,
            exclude_coin="ETH",
            cur_confidence=0.82,  # 0.82+0.15=0.97 > 0.80
            cur_direction="long",
        )
        assert result is None

    def test_confidence_below_absolute_floor(self):
        """信号置信度 < 0.65 绝对门槛 → 即使满足 +0.15 也不选"""
        from dreambuddy_evolution.engines.entry_signal_governor import (
            find_strongest_rotation_signal,
        )
        evo_signals = {
            "COIN": {"top_path_confidence": 0.60, "top_path_direction": "short"},
        }
        bcrm_signals = {}
        result = find_strongest_rotation_signal(
            evo_signals=evo_signals,
            bcrm_signals=bcrm_signals,
            exclude_coin="ETH",
            cur_confidence=0.40,  # 0.40+0.15=0.55 < 0.60，但 0.60 < 0.65 门槛
            cur_direction="long",
        )
        assert result is None

    def test_pick_strongest_across_both_pools(self):
        """跨 evolution + BCRM 池选最强"""
        from dreambuddy_evolution.engines.entry_signal_governor import (
            find_strongest_rotation_signal,
        )
        evo_signals = {
            "ARB": {"top_path_confidence": 0.88, "top_path_direction": "long"},
        }
        bcrm_signals = {
            "COIN": {"direction": "DOWN", "confidence": 0.98},
        }
        result = find_strongest_rotation_signal(
            evo_signals=evo_signals,
            bcrm_signals=bcrm_signals,
            exclude_coin="MU",
            cur_confidence=0.80,
            cur_direction="long",
        )
        assert result is not None
        assert result["coin"] == "COIN"
        assert result["confidence"] == pytest.approx(0.98)

    def test_empty_pools_return_none(self):
        """空信号池 → None"""
        from dreambuddy_evolution.engines.entry_signal_governor import (
            find_strongest_rotation_signal,
        )
        result = find_strongest_rotation_signal(
            evo_signals={},
            bcrm_signals={},
            exclude_coin="ETH",
            cur_confidence=0.70,
            cur_direction="long",
        )
        assert result is None
