"""test_bellman_persistence.py — Bellman V(s) 持久化单元测试（D2: ds4 KV Cache 持久化借鉴）

SPEC: SPEC-ds4架构借鉴与系统增强.md §3.2 Dimension 2
硬约束: HC-DS4-03（持久化失败→内存继续工作）、HC-DS4-09（持久化频率≤每100次更新）

覆盖:
  - save/load 基本功能（一维 + 二维 V 值）
  - 构造时自动 load（persist_path 存在时恢复）
  - FAIL-OPEN: 持久化失败不影响内存 V 值
  - FAIL-OPEN: 加载失败从空 dict 开始（向后兼容）
  - persist_path=None 时不持久化（向后兼容）
  - 持久化频率控制（每 N 次更新）
  - 数据损坏时降级
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from dreambuddy_evolution.core.bellman_tracker import BellmanVTracker


# ==============================================================================
# 1. 基本 save/load 功能
# ==============================================================================
class TestBellmanPersistenceBasic:
    """D2: save/load 基本功能验证"""

    def test_save_then_load_restores_1d_v(self, tmp_path):
        """一维 V(s) 保存后重新加载，值完全恢复"""
        tracker = BellmanVTracker(alpha=0.1, gamma=0.95)
        tracker.td_update("BTC", reward=0.05, next_symbol="ETH")
        tracker.td_update("ETH", reward=-0.02, next_symbol="BTC")
        v_btc_before = tracker.get_v("BTC")
        v_eth_before = tracker.get_v("ETH")

        persist = tmp_path / "bellman_v.json"
        tracker.save(persist)
        assert persist.exists()

        # 新实例加载
        tracker2 = BellmanVTracker(alpha=0.1, gamma=0.95)
        tracker2.load(persist)

        assert tracker2.get_v("BTC") == pytest.approx(v_btc_before)
        assert tracker2.get_v("ETH") == pytest.approx(v_eth_before)

    def test_save_then_load_restores_2d_v(self, tmp_path):
        """二维 (symbol, regime) V(s) 保存后重新加载，值完全恢复"""
        tracker = BellmanVTracker(alpha=0.1, gamma=0.95)
        tracker.td_update("BTC", reward=0.05, next_symbol="ETH",
                          regime="trend", next_regime="range")
        v_btc_trend_before = tracker.get_v("BTC", regime="trend")

        persist = tmp_path / "bellman_v.json"
        tracker.save(persist)

        tracker2 = BellmanVTracker(alpha=0.1, gamma=0.95)
        tracker2.load(persist)

        assert tracker2.get_v("BTC", regime="trend") == pytest.approx(v_btc_trend_before)
        # 一维也应同步
        assert tracker2.get_v("BTC") == pytest.approx(v_btc_trend_before)

    def test_load_without_persist_path_is_noop(self, tmp_path):
        """persist_path=None 时 load 不报错，V 值保持空"""
        tracker = BellmanVTracker()
        # 不应抛异常
        tracker.load(None)  # type: ignore[arg-type]
        assert tracker.get_v("BTC") == 0.0

    def test_load_nonexistent_file_is_noop(self, tmp_path):
        """加载不存在的文件不报错，从空 dict 开始（FAIL-OPEN）"""
        tracker = BellmanVTracker()
        tracker.load(tmp_path / "not_exist.json")
        assert tracker.get_v("BTC") == 0.0


# ==============================================================================
# 2. 构造时自动 load
# ==============================================================================
class TestBellmanAutoLoad:
    """D2: 构造时传入 persist_path 自动恢复"""

    def test_init_with_persist_path_autoloads(self, tmp_path):
        """构造时传入 persist_path，自动从磁盘恢复 V 值"""
        # 先保存
        tracker1 = BellmanVTracker(alpha=0.1, gamma=0.95)
        tracker1.td_update("BTC", reward=0.05, next_symbol="ETH")
        persist = tmp_path / "bellman_v.json"
        tracker1.save(persist)
        v_before = tracker1.get_v("BTC")

        # 新实例用 persist_path 构造，应自动加载
        tracker2 = BellmanVTracker(alpha=0.1, gamma=0.95, persist_path=persist)
        assert tracker2.get_v("BTC") == pytest.approx(v_before)

    def test_init_with_persist_path_none_no_autoload(self):
        """persist_path=None 时不自动加载（向后兼容）"""
        tracker = BellmanVTracker(alpha=0.1, gamma=0.95, persist_path=None)
        assert tracker.get_v("BTC") == 0.0


# ==============================================================================
# 3. FAIL-OPEN: 持久化失败不影响内存
# ==============================================================================
class TestBellmanPersistenceFailOpen:
    """D2: FAIL-OPEN 行为验证"""

    def test_save_to_invalid_path_does_not_affect_memory(self, tmp_path):
        """保存到无效路径不抛异常，内存 V 值不受影响"""
        tracker = BellmanVTracker(alpha=0.1, gamma=0.95)
        tracker.td_update("BTC", reward=0.05, next_symbol="ETH")
        v_before = tracker.get_v("BTC")

        # 保存到目录路径（无效，应 FAIL-OPEN）
        invalid_path = tmp_path  # 目录而非文件
        tracker.save(invalid_path)

        # 内存值不变
        assert tracker.get_v("BTC") == pytest.approx(v_before)

    def test_load_corrupted_file_starts_empty(self, tmp_path):
        """加载损坏的 JSON 文件不抛异常，从空 dict 开始"""
        corrupted = tmp_path / "corrupted.json"
        corrupted.write_text("{not valid json", encoding="utf-8")

        tracker = BellmanVTracker(alpha=0.1, gamma=0.95)
        tracker.load(corrupted)

        # 从空开始（FAIL-OPEN）
        assert tracker.get_v("BTC") == 0.0

    def test_load_missing_keys_starts_empty(self, tmp_path):
        """加载缺少必要 key 的 JSON 不抛异常，从空 dict 开始"""
        bad_json = tmp_path / "bad.json"
        bad_json.write_text(json.dumps({"unexpected_key": {}}), encoding="utf-8")

        tracker = BellmanVTracker(alpha=0.1, gamma=0.95)
        tracker.load(bad_json)

        assert tracker.get_v("BTC") == 0.0


# ==============================================================================
# 4. 持久化频率控制
# ==============================================================================
class TestBellmanPersistenceFrequency:
    """HC-DS4-09: 持久化频率 ≤ 每 100 次更新"""

    def test_save_every_n_updates(self, tmp_path, monkeypatch):
        """设置 save_every=10 时，每 10 次更新自动 save"""
        persist = tmp_path / "bellman_v.json"
        tracker = BellmanVTracker(alpha=0.1, gamma=0.95,
                                  persist_path=persist, save_every=10)

        # 前 9 次更新不应触发 save
        for i in range(9):
            tracker.td_update("BTC", reward=0.01, next_symbol="BTC")
        assert not persist.exists()

        # 第 10 次更新触发 save
        tracker.td_update("BTC", reward=0.01, next_symbol="BTC")
        assert persist.exists()

    def test_save_every_default_100(self, tmp_path):
        """默认 save_every=100（HC-DS4-09）"""
        persist = tmp_path / "bellman_v.json"
        tracker = BellmanVTracker(alpha=0.1, gamma=0.95, persist_path=persist)
        assert tracker._save_every == 100  # type: ignore[attr-defined]


# ==============================================================================
# 5. 持久化格式验证
# ==============================================================================
class TestBellmanPersistenceFormat:
    """D2: 持久化 JSON 格式验证"""

    def test_persist_format_contains_v_and_v_regime(self, tmp_path):
        """持久化文件包含 v 和 v_regime 两个 key"""
        tracker = BellmanVTracker(alpha=0.1, gamma=0.95)
        tracker.td_update("BTC", reward=0.05, next_symbol="ETH",
                          regime="trend", next_regime="range")
        persist = tmp_path / "bellman_v.json"
        tracker.save(persist)

        data = json.loads(persist.read_text(encoding="utf-8"))
        assert "v" in data
        assert "v_regime" in data
        assert isinstance(data["v"], dict)
        assert isinstance(data["v_regime"], dict)

    def test_v_regime_keys_are_symbol_regime_pairs(self, tmp_path):
        """v_regime 的 key 是 symbol|regime 格式"""
        tracker = BellmanVTracker(alpha=0.1, gamma=0.95)
        tracker.td_update("BTC", reward=0.05, next_symbol="ETH",
                          regime="trend", next_regime="range")
        persist = tmp_path / "bellman_v.json"
        tracker.save(persist)

        data = json.loads(persist.read_text(encoding="utf-8"))
        regime_keys = list(data["v_regime"].keys())
        assert any("|" in k for k in regime_keys)
