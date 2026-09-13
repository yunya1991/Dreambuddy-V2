"""样本生成器测试 — 验证 backtest 样本扩充管线
"""
import json
import os
import tempfile
from pathlib import Path

import numpy as np
import pytest


class TestNormalizeState:
    """状态归一化测试"""

    def test_normalize_state_range(self):
        """归一化后所有维度应在 [0, 1] 范围内"""
        from dreambuddy_evolution.core.exit_rl_policy import normalize_state
        # 原始状态：各种尺度
        state = np.array([0.05, 1200.0, 0.02, 50.0, 0.6, 0.3, 1.0, 1], dtype=np.float32)
        norm = normalize_state(state)
        assert norm.shape == (8,)
        assert np.all(norm >= 0.0) and np.all(norm <= 1.0)

    def test_normalize_state_clip(self):
        """超出范围的值被 clip"""
        from dreambuddy_evolution.core.exit_rl_policy import normalize_state
        # upl_ratio=1.0（超过 0.40 上限）→ 应被 clip
        state = np.array([1.0, 5000.0, 0.1, 120.0, 1.5, 2.0, 5.0, 3.0], dtype=np.float32)
        norm = normalize_state(state)
        assert norm[0] <= 1.0  # upl_ratio 被 clip
        assert norm[1] <= 1.0  # age_min 被 clip

    def test_normalize_state_zero(self):
        """零向量归一化"""
        from dreambuddy_evolution.core.exit_rl_policy import normalize_state
        state = np.zeros(8, dtype=np.float32)
        norm = normalize_state(state)
        assert np.all(norm >= 0.0)


class TestExitSampleGenerator:
    """样本生成器测试"""

    @pytest.fixture
    def trades_file(self, tmp_path):
        """创建测试用交易文件"""
        trades = [
            {
                "trade_id": "test_001",
                "coin": "BTC",
                "inst_id": "BTC-USDT-SWAP",
                "direction": "long",
                "entry_price": 100000.0,
                "exit_price": 103000.0,
                "entry_time": "2026-08-01T00:00:00+00:00",
                "exit_time": "2026-08-01T10:00:00+00:00",
                "pnl": 3.0,
                "pnl_pct": 0.03,
                "exit_reason": "tp_hit",
                "confidence": 0.85,
                "market_snapshot": {"price": 100000.0, "volatility": 0.02},
                "contradiction_list": [],
                "strategy_source": "bcrm",
                "enhance_info": {},
                "reduce_count": 0,
            },
            {
                "trade_id": "test_002",
                "coin": "ETH",
                "inst_id": "ETH-USDT-SWAP",
                "direction": "long",
                "entry_price": 3000.0,
                "exit_price": 2910.0,
                "entry_time": "2026-08-05T00:00:00+00:00",
                "exit_time": "2026-08-05T08:00:00+00:00",
                "pnl": -0.9,
                "pnl_pct": -0.03,
                "exit_reason": "sl_hit",
                "confidence": 0.7,
                "market_snapshot": {"price": 3000.0, "volatility": 0.03},
                "contradiction_list": [],
                "strategy_source": "bcrm",
                "enhance_info": {},
                "reduce_count": 0,
            },
        ]
        path = tmp_path / "trades.jsonl"
        with open(path, "w") as f:
            for t in trades:
                f.write(json.dumps(t) + "\n")
        return str(path)

    def test_generator_creates_samples(self, trades_file, tmp_path):
        """生成器应创建样本文件"""
        from dreambuddy_evolution.core.exit_sample_generator import ExitSampleGenerator
        output = str(tmp_path / "samples.jsonl")
        gen = ExitSampleGenerator(
            trades_path=trades_file,
            output_path=output,
            target_samples=100,
        )
        count = gen.generate()
        assert count > 0
        assert os.path.exists(output)

    def test_sample_format(self, trades_file, tmp_path):
        """每条样本应包含 state/action/reward/next_state/done"""
        from dreambuddy_evolution.core.exit_sample_generator import ExitSampleGenerator
        output = str(tmp_path / "samples.jsonl")
        gen = ExitSampleGenerator(
            trades_path=trades_file,
            output_path=output,
            target_samples=50,
        )
        gen.generate()
        with open(output) as f:
            for line in f:
                s = json.loads(line)
                assert "state" in s and len(s["state"]) == 8
                assert "action" in s and 0 <= s["action"] <= 4
                assert "reward" in s and isinstance(s["reward"], (int, float))
                assert "next_state" in s and len(s["next_state"]) == 8
                assert "done" in s

    def test_target_sample_count(self, trades_file, tmp_path):
        """生成的样本数应接近目标值"""
        from dreambuddy_evolution.core.exit_sample_generator import ExitSampleGenerator
        output = str(tmp_path / "samples.jsonl")
        target = 200
        gen = ExitSampleGenerator(
            trades_path=trades_file,
            output_path=output,
            target_samples=target,
        )
        count = gen.generate()
        assert count == target

    def test_action_distribution(self, trades_file, tmp_path):
        """应包含多种动作（不全是 hold）"""
        from dreambuddy_evolution.core.exit_sample_generator import ExitSampleGenerator
        output = str(tmp_path / "samples.jsonl")
        gen = ExitSampleGenerator(
            trades_path=trades_file,
            output_path=output,
            target_samples=200,
        )
        gen.generate()
        actions = set()
        with open(output) as f:
            for line in f:
                s = json.loads(line)
                actions.add(s["action"])
        # 至少有 2 种不同动作
        assert len(actions) >= 2
