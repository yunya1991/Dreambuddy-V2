"""Gap3 TDD：A级引擎（A6 least_resistance / A7 SignalEngine）Shadow 审计真实数据通路。

Spec: 当前 _fd7_shadow_compute 调用 _fd_A_dao_boost / _fd_A_tian_boost 时，
system_state 和 coin_data 中不含 r3d/signal 字段 → A 级返回 0.0 → reason=FD7_NO_DATA。
目标：从已有生产数据（result dao 评分 + system_state win_rate/profit_factor）构造
A 级 shadow 审计输入，使 fd_A_dao_mean 和 fd_A_tian_mean 非 0。

关键约束：只影响 Shadow 审计（只读），绝对不修改 result / 不影响生产注入红线。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

THIS_DIR = Path(__file__).resolve().parent
_REPO = THIS_DIR.parent
_COMPUTER_ROOT = _REPO / "scripts" / "memory_l4"
_FUND_ROOT = _REPO.parent / "9-基本面分析"
_FUND_ENGINES = _FUND_ROOT / "engines"

if str(_COMPUTER_ROOT) not in sys.path:
    sys.path.insert(0, str(_COMPUTER_ROOT))
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
if str(_FUND_ENGINES) not in sys.path:
    sys.path.insert(0, str(_FUND_ENGINES))


def _get_computer_cls():
    from five_domain_feature_computer import FiveDomainFeatureComputer
    return FiveDomainFeatureComputer


def _make_computer_with_shadow(tmp_path: Path, monkeypatch):
    """构造一个 Shadow 开启、JSONL 写入 tmp_path 的 computer 实例。"""
    monkeypatch.setenv("ODAILY_ENGINE_BOOST", "1")
    monkeypatch.setenv("FUND_7ENGINES_BOOST", "1")
    Cls = _get_computer_cls()
    c = Cls()
    # JSONL 写入临时路径
    jsonl_path = str(tmp_path / "fd7_shadow_test.jsonl")
    c._fd7_shadow_jsonl_path = jsonl_path
    c._od_shadow_jsonl_path = str(tmp_path / "od_shadow_test.jsonl")
    # 避免 news_list 依赖真实 SQLite
    monkeypatch.setattr(c, "_fetch_news_72h_limit200", lambda *a, **kw: [])
    return c


def _read_shadow_jsonl(path: str) -> list:
    """读取 Shadow JSONL 全部记录。"""
    try:
        with open(path, "r") as f:
            return [json.loads(line) for line in f if line.strip()]
    except FileNotFoundError:
        return []


class TestGap3AEngineShadowFromResult:
    """Gap3 核心：从 result dao 评分 + system_state 构造 A 级 shadow 审计数据。"""

    def test_a_dao_mean_nonzero_from_result_dao_scores(self, tmp_path, monkeypatch):
        """传入含 dao 评分的 result + 不含 r3d 的 system_state → fd_A_dao_mean != 0。"""
        c = _make_computer_with_shadow(tmp_path, monkeypatch)
        # 构造生产数据：3 资产类 dao 评分
        result = {
            "crypto_usdt": {"dao": 72, "tian": 65, "di": 60, "jiang": 70, "fa": 68},
            "us_stock":    {"dao": 58, "tian": 55, "di": 50, "jiang": 60, "fa": 55},
            "precious_metal": {"dao": 66, "tian": 60, "di": 58, "jiang": 65, "fa": 62},
        }
        system_state = {"win_rate": 0.62, "profit_factor": 1.8}
        coin_data = None
        # 调用 shadow（不依赖 news_list，已 mock 为空）
        c._fd7_shadow_compute(coin_data, system_state, result)
        records = _read_shadow_jsonl(c._fd7_shadow_jsonl_path)
        assert len(records) >= 1, "Shadow JSONL 应写入至少 1 条"
        rec = records[-1]
        # A 级 dao 应非 0（从 result dao 评分构造 r3d 后计算）
        assert rec["fd_A_dao_mean"] != 0.0, (
            f"fd_A_dao_mean 应非 0（从 result dao 评分构造 r3d 后计算），实际={rec['fd_A_dao_mean']}"
        )
        assert abs(rec["fd_A_dao_mean"]) <= 0.05, f"A 级 clamp ±0.05 越界: {rec['fd_A_dao_mean']}"

    def test_a_tian_mean_nonzero_from_system_state_win_rate(self, tmp_path, monkeypatch):
        """传入含 win_rate 的 system_state + 不含 signal 的 coin_data → fd_A_tian_mean != 0。"""
        c = _make_computer_with_shadow(tmp_path, monkeypatch)
        result = {
            "crypto_usdt": {"dao": 70, "tian": 65, "di": 60, "jiang": 70, "fa": 68},
        }
        system_state = {"win_rate": 0.65, "profit_factor": 1.9}
        coin_data = None
        c._fd7_shadow_compute(coin_data, system_state, result)
        records = _read_shadow_jsonl(c._fd7_shadow_jsonl_path)
        assert len(records) >= 1
        rec = records[-1]
        assert rec["fd_A_tian_mean"] != 0.0, (
            f"fd_A_tian_mean 应非 0（从 win_rate/profit_factor 构造 signal），实际={rec['fd_A_tian_mean']}"
        )
        assert abs(rec["fd_A_tian_mean"]) <= 0.05, f"A 级 clamp ±0.05 越界: {rec['fd_A_tian_mean']}"

    def test_reason_code_not_fd7_no_data_when_both_a_engines_active(self, tmp_path, monkeypatch):
        """S 级有 news + A 级有数据 → reason_code 应为 FD7_OK（不再 FD7_NO_DATA）。"""
        c = _make_computer_with_shadow(tmp_path, monkeypatch)
        # 让 news_list 非空
        monkeypatch.setattr(c, "_fetch_news_72h_limit200", lambda *a, **kw: [
            {"source": "odaily", "category": "news", "sub_category": "x",
             "title": "BTC涨", "content": "BTC突破", "timestamp_ms": 1700000000000}
        ])
        result = {
            "crypto_usdt": {"dao": 72, "tian": 65, "di": 60, "jiang": 70, "fa": 68},
        }
        system_state = {"win_rate": 0.62, "profit_factor": 1.8}
        c._fd7_shadow_compute(None, system_state, result)
        records = _read_shadow_jsonl(c._fd7_shadow_jsonl_path)
        assert len(records) >= 1
        rec = records[-1]
        assert rec["shadow_reason_code"] == "FD7_OK", (
            f"有 news + A 级有数据 → reason 应 FD7_OK，实际={rec['shadow_reason_code']}"
        )

    def test_shadow_does_not_modify_result(self, tmp_path, monkeypatch):
        """Shadow 调用后 result 不变（只读铁律）。"""
        c = _make_computer_with_shadow(tmp_path, monkeypatch)
        result = {
            "crypto_usdt": {"dao": 72, "tian": 65, "di": 60, "jiang": 70, "fa": 68},
        }
        result_before = json.loads(json.dumps(result))
        c._fd7_shadow_compute(None, {"win_rate": 0.6}, result)
        assert result == result_before, "Shadow 不应修改 result（只读铁律）"

    def test_a_engine_zero_when_result_empty(self, tmp_path, monkeypatch):
        """result 为空 dict → A 级无数据来源 → fd_A_dao_mean=0（fail-open）。"""
        c = _make_computer_with_shadow(tmp_path, monkeypatch)
        c._fd7_shadow_compute(None, {"win_rate": 0.5}, {})
        records = _read_shadow_jsonl(c._fd7_shadow_jsonl_path)
        assert len(records) >= 1
        rec = records[-1]
        # result 为空 → 无 dao 评分 → r3d 无法构造 → A_dao=0
        # 但 win_rate=0.5 → effective_weight=1.0 → w_ratio=1.0 → (1-1)*0.03=0 → A_tian 也=0
        # 这是正确的 fail-open 行为
        assert rec["fd_A_dao_mean"] == 0.0, "result 空 → A_dao 应 0（fail-open）"
