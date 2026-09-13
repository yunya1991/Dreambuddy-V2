"""
ShadowRL B+C+D 优化方案 TDD 测试集

B方案: 回测注入历史样本 (_build_l3_state + inject_backtest_samples)
C方案: 有效样本计数 (reward≠0 才计入激活阈值与训练)
D方案: JSONL 持久化 (persist + load_from_disk)

验收点：
  - reward=0 占位样本不计入 effective_count
  - 激活阈值只看 effective_count
  - train_policy 只收到 reward≠0 的有效样本
  - get_stats 返回 effective_sample_count
  - JSONL 落盘 FAIL-OPEN
  - load_from_disk 只加载最后 maxlen 行
  - _build_l3_state 所有值在 [0,1] 范围
  - inject_backtest_samples reward=tanh(pnl/0.02)
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dreambuddy_evolution.core.shadow_rl import ShadowRLTracker
from dreambuddy_evolution.core.shadow_rl_trainer import ShadowRLTrainer


# --------------------------------------------------------------------------------
# C方案: 有效样本计数
# --------------------------------------------------------------------------------
class TestEffectiveSampleCount:
    """reward≠0 的样本才计入 effective_count。"""

    def test_record_increments_effective_count_only_nonzero(self):
        """reward=0 不增 effective；reward≠0 增 1"""
        tracker = ShadowRLTracker()
        assert tracker.effective_sample_count() == 0

        tracker.record("BTC", {"R_up": 0.5}, "long", 0.0, {})
        assert tracker.effective_sample_count() == 0
        assert tracker.sample_count() == 1  # 总数仍计

        tracker.record("BTC", {"R_up": 0.6}, "long", 0.5, {})
        assert tracker.effective_sample_count() == 1
        assert tracker.sample_count() == 2

    def test_maybe_activate_uses_effective_count(self):
        """1999占位 + 1真实 = effective 1 < 2000，不激活；2000真实激活"""
        tracker = ShadowRLTracker()
        # 灌入 1999 条 reward=0 占位样本
        for _ in range(1999):
            tracker.record("BTC", {"R_up": 0.5}, "long", 0.0, {})
        assert tracker.effective_sample_count() == 0
        assert not tracker.is_phase3_activated()

        # 第 2000 条仍是占位，不激活
        tracker.record("BTC", {"R_up": 0.5}, "long", 0.0, {})
        assert not tracker.is_phase3_activated()

        # 需 2000 条有效样本才激活（需 mock enable_shadow_rl_phase3）
        with patch("dreambuddy_evolution.agi_config.is_enabled", return_value=True):
            tracker2 = ShadowRLTracker()
            for _ in range(1999):
                tracker2.record("BTC", {"R_up": 0.5}, "long", 0.1, {})
            assert not tracker2.is_phase3_activated()
            tracker2.record("BTC", {"R_up": 0.5}, "long", 0.1, {})  # 第 2000 条有效
            assert tracker2.is_phase3_activated()

    def test_train_policy_receives_only_effective_samples(self):
        """train_policy 收到的样本列表不含 reward=0"""
        tracker = ShadowRLTracker()
        tracker.trainer = MagicMock(spec=ShadowRLTrainer)
        tracker.trainer.MIN_SAMPLES = 2  # 有效样本阈值降为 2
        tracker.trainer.maybe_activate.return_value = True
        tracker.trainer.train_policy.return_value = {"status": "trained"}

        with patch("dreambuddy_evolution.agi_config.is_enabled", return_value=True):
            # 灌入 2 占位 + 2 有效（effective_count=2 触发激活）
            tracker.record("BTC", {}, "long", 0.0, {})
            tracker.record("BTC", {}, "long", 0.0, {})
            tracker.record("BTC", {}, "long", 0.5, {})   # effective=1
            tracker.record("BTC", {}, "long", -0.3, {})  # effective=2 → 触发激活

        # train_policy 被调用一次
        tracker.trainer.train_policy.assert_called_once()
        called_samples = tracker.trainer.train_policy.call_args[0][0]
        assert len(called_samples) == 2  # 只收到 2 条有效样本（占位被过滤）
        assert all(s["reward"] != 0.0 for s in called_samples)

    def test_get_stats_includes_effective_field(self):
        """get_stats 返回含 effective_sample_count 键"""
        tracker = ShadowRLTracker()
        tracker.record("BTC", {}, "long", 0.0, {})
        tracker.record("BTC", {}, "long", 0.5, {})
        stats = tracker.get_stats()
        assert "effective_sample_count" in stats
        assert stats["effective_sample_count"] == 1
        assert stats["sample_count"] == 2


# --------------------------------------------------------------------------------
# D方案: JSONL 持久化
# --------------------------------------------------------------------------------
class TestPersistence:
    """JSONL 落盘与加载。"""

    def test_persist_appends_jsonl(self, tmp_path):
        """record 3 次 → 文件 3 行"""
        path = tmp_path / "samples.jsonl"
        tracker = ShadowRLTracker(persist_path=path)
        tracker.record("BTC", {"R_up": 0.5}, "long", 0.1, {})
        tracker.record("ETH", {"R_up": 0.6}, "short", -0.2, {})
        tracker.record("BTC", {"R_up": 0.7}, "long", 0.0, {})  # 占位也落盘

        assert path.exists()
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 3
        s1 = json.loads(lines[0])
        assert s1["symbol"] == "BTC"
        assert s1["reward"] == 0.1

    def test_load_from_disk_restores_deque(self, tmp_path):
        """预写 5 行 JSONL，load 后 sample_count()==5"""
        path = tmp_path / "samples.jsonl"
        for i in range(5):
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "symbol": "BTC", "state": {"R_up": i * 0.1},
                    "action": "long", "reward": 0.1 * (i + 1),
                    "next_state": {},
                }) + "\n")

        tracker = ShadowRLTracker(persist_path=path)
        tracker.load_from_disk()
        assert tracker.sample_count() == 5
        assert tracker.effective_sample_count() == 5  # 全部 reward≠0

    def test_load_truncates_to_maxlen(self, tmp_path):
        """预写 10005 行，load 后 sample_count()==10000"""
        path = tmp_path / "big.jsonl"
        for i in range(10005):
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "symbol": "BTC", "state": {"i": i},
                    "action": "long", "reward": 0.1,
                    "next_state": {},
                }) + "\n")

        tracker = ShadowRLTracker(max_samples=10000, persist_path=path)
        tracker.load_from_disk()
        assert tracker.sample_count() == 10000  # 截断到 maxlen

    def test_persist_fail_open(self, tmp_path):
        """persist_path 只读目录，record 不抛异常"""
        ro_dir = tmp_path / "readonly"
        ro_dir.mkdir()
        ro_dir.chmod(0o444)  # 只读
        path = ro_dir / "samples.jsonl"

        tracker = ShadowRLTracker(persist_path=path)
        # 不应抛异常
        tracker.record("BTC", {}, "long", 0.5, {})
        assert tracker.sample_count() == 1  # 内存仍正常


# --------------------------------------------------------------------------------
# B方案: 回测注入
# --------------------------------------------------------------------------------
class TestBacktestInject:
    """_build_l3_state 与 inject_backtest_samples。"""

    def _get_shadow_backtest_module(self):
        """导入 shadow_backtest 模块（需添加 scripts 到 sys.path）"""
        scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        import shadow_backtest
        return shadow_backtest

    def test_build_l3_state_range_clamped(self):
        """极端 bar 指标 → state 值在 [0,1]"""
        mod = self._get_shadow_backtest_module()
        # 极端值
        bar_extreme = {
            "rsi_2": 200,      # 超出 100
            "adx_14": 999,     # 超出 50
            "vol_ratio": 10,   # 超出 3
            "zscore_vwap": 10, # 超出 3
            "vol_quantile": 2, # 超出 1
        }
        state = mod._build_l3_state(bar_extreme, [], 0)
        for key, val in state.items():
            assert 0.0 <= val <= 1.0, f"{key}={val} 超出 [0,1]"

        # 负值
        bar_neg = {
            "rsi_2": -50,
            "adx_14": -10,
            "vol_ratio": -1,
            "zscore_vwap": -10,
            "vol_quantile": -0.5,
        }
        state = mod._build_l3_state(bar_neg, [], 0)
        for key, val in state.items():
            assert 0.0 <= val <= 1.0, f"{key}={val} 超出 [0,1]"

    def test_build_l3_state_fields_present(self):
        """state 包含所有 6 个必需字段"""
        mod = self._get_shadow_backtest_module()
        bar = {"rsi_2": 50, "adx_14": 25, "vol_ratio": 1.5,
               "zscore_vwap": 0, "vol_quantile": 0.5}
        state = mod._build_l3_state(bar, [], 0)
        required = {"R_up", "R_down", "R_smooth", "R_flow", "R_reflexivity", "quality_score"}
        assert required.issubset(set(state.keys()))

    def test_inject_backtest_samples_reward_tanh(self):
        """注入后 reward=tanh(pnl/0.02)，|reward|<1"""
        mod = self._get_shadow_backtest_module()
        tracker = MagicMock(spec=ShadowRLTracker)

        # 构造最小 K 线数据（LOOKBACK=20, HOLD_BARS=12）
        klines = []
        for i in range(40):
            klines.append({
                "timestamp": str(i),
                "open": 100.0 + i, "high": 101.0 + i,
                "low": 99.0 + i, "close": 100.5 + i,
                "volume": 1000.0,
            })

        # mock calc_indicators 返回带指标的 bar
        with patch.object(mod, "eval_gene_with_direction", return_value=(True, "long")):
            with patch.object(mod, "simulate_trade", return_value={
                "pnl_pct": 0.05, "entry_price": 100, "exit_price": 105,
            }):
                result = mod.inject_backtest_samples(tracker, klines, gene_ids=["TEST-GENE"])

        # record 被调用
        assert tracker.record.call_count > 0
        for call in tracker.record.call_args_list:
            kwargs = call.kwargs
            assert "reward" in kwargs
            assert abs(kwargs["reward"]) < 1.0  # tanh 输出在 (-1, 1)
            expected_reward = math.tanh(0.05 / 0.02)
            assert abs(kwargs["reward"] - expected_reward) < 1e-9
