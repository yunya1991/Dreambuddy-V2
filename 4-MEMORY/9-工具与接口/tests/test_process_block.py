#!/usr/bin/env python3
"""WorkingMemory process_block 单测（设计节 3.2）。

Task 15: process_block 只读分区 + load_process_block + get_prompt_context 追加流程段。
"""
import sys
from pathlib import Path

import pytest

_SCRIPT_DIR = Path(__file__).parent
_PARENT = _SCRIPT_DIR.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))

from working_memory_manager import WorkingMemoryManager


def test_process_block_in_default_budgets():
    wm = WorkingMemoryManager()
    assert "process" in wm.DEFAULT_BUDGETS
    assert wm.DEFAULT_BUDGETS["process"] == 3000


def test_process_block_initialized_and_readonly():
    wm = WorkingMemoryManager()
    assert hasattr(wm, "process_block")
    assert getattr(wm.process_block, "_readonly", False) is True


def test_load_process_block_writes_markdown():
    wm = WorkingMemoryManager()
    md = "## 🎯 流程建议\n### [元认知] test-driven-development\nHARD-GATE: ..."
    wm.load_process_block(md)
    stored = wm.process_block.get("markdown", "")
    assert "🎯" in stored or md in stored


def test_get_prompt_context_includes_process_section():
    wm = WorkingMemoryManager()
    wm.set_task("测试任务", goal="验证")
    wm.load_process_block("## 🎯 流程建议\n### test-driven-development")
    ctx = wm.get_prompt_context()
    assert "🎯" in ctx or "流程建议" in ctx
    assert "test-driven-development" in ctx


def test_process_block_token_counted_in_total():
    wm = WorkingMemoryManager()
    wm.load_process_block("## 流程建议\n" + "x" * 400)
    usage = wm.get_token_usage()
    assert "process" in usage
    assert usage["process"] > 0
