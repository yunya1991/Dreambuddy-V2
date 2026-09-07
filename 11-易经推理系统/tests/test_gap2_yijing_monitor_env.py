"""Gap2 TDD：yijing_monitor run_polling_trader() Popen env 注入。

Spec: 当 yijing_monitor 从 launchd 自动触发时，父进程没有 ODAILY_ENGINE_BOOST / FUND_7ENGINES_BOOST，
Popen 启动的 polling_trader 子进程也不继承。需要显式构造 env 传给 Popen。

方案：提取辅助函数 _build_popen_env()，在 run_polling_trader() 的 Popen 调用中使用。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

THIS_DIR = Path(__file__).resolve().parent
_REPO = THIS_DIR.parent

if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
if str(_REPO / "scripts" / "memory_l4") not in sys.path:
    sys.path.insert(0, str(_REPO / "scripts" / "memory_l4"))


def _get_build_popen_env():
    from yijing_monitor import _build_popen_env
    return _build_popen_env


class TestGap2PopenEnv:
    def test_env_contains_both_boost_vars_when_absent(self, monkeypatch):
        """env 不存在时 → setdefault 注入 1。"""
        monkeypatch.delenv("ODAILY_ENGINE_BOOST", raising=False)
        monkeypatch.delenv("FUND_7ENGINES_BOOST", raising=False)
        fn = _get_build_popen_env()
        env = fn()
        assert env.get("ODAILY_ENGINE_BOOST") == "1", "ODAILY_ENGINE_BOOST 应被 setdefault 为 1"
        assert env.get("FUND_7ENGINES_BOOST") == "1", "FUND_7ENGINES_BOOST 应被 setdefault 为 1"

    def test_env_preserves_existing_values(self, monkeypatch):
        """env 已存在时不覆盖（setdefault 语义）。"""
        monkeypatch.setenv("ODAILY_ENGINE_BOOST", "0")
        monkeypatch.setenv("FUND_7ENGINES_BOOST", "false")
        fn = _get_build_popen_env()
        env = fn()
        assert env.get("ODAILY_ENGINE_BOOST") == "0", "已存在值不应被覆盖"
        assert env.get("FUND_7ENGINES_BOOST") == "false", "已存在值不应被覆盖"

    def test_env_inherits_parent_vars(self, monkeypatch):
        """env 应继承父进程其他变量（PATH 等）。"""
        monkeypatch.delenv("ODAILY_ENGINE_BOOST", raising=False)
        monkeypatch.delenv("FUND_7ENGINES_BOOST", raising=False)
        fn = _get_build_popen_env()
        env = fn()
        assert "PATH" in env, "PATH 应从父进程继承"
