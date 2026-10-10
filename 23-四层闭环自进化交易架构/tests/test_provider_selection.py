"""RED 测试：Provider 确定性选择 — explicit 模式 ambiguous 报错。

借鉴 REA 的 Provider 确定性选择设计：多路径时不自动选，报 ambiguous + 列候选。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "dreambuddy_evolution" / "core"))
sys.path.insert(0, str(Path(__file__).parent.parent / "dreambuddy_evolution"))

from contradiction_identifier import PrimaryContradictionIdentifier


def _make_paths(n: int = 2) -> list[dict]:
    """构造 n 条不同 source 的 paths。"""
    sources = ["bdsm", "bcrm", "strategic", "deep_reasoning"]
    return [
        {"source": sources[i % len(sources)], "direction": 1 if i % 2 == 0 else -1,
         "confidence": 0.6, "strength": 0.5}
        for i in range(n)
    ]


def test_explicit_mode_returns_ambiguous_when_multiple_candidates():
    """RED: explicit 模式下，多候选应返回 ambiguous 而非自动选择。"""
    ci = PrimaryContradictionIdentifier(selection_policy="explicit")
    result = ci.identify(_make_paths(3))

    assert result["status"] == "ambiguous"
    assert len(result["candidates"]) >= 2
    assert "message" in result


def test_auto_mode_unchanged_behavior():
    """RED: auto 模式（默认）应保持现有三步法行为，不返回 ambiguous。"""
    ci = PrimaryContradictionIdentifier(selection_policy="auto")
    result = ci.identify(_make_paths(3))

    assert result.get("status") != "ambiguous"


def test_explicit_mode_after_select_path_does_not_return_ambiguous():
    """RED: explicit 模式下显式选择路径后，不应再返回 ambiguous。"""
    ci = PrimaryContradictionIdentifier(selection_policy="explicit")
    ci.select_path_explicit("bdsm")
    result = ci.identify(_make_paths(3))

    assert result.get("status") != "ambiguous"


def test_invalid_selection_policy_falls_back_to_auto():
    """RED: selection_policy 非法值 FAIL-OPEN 回退到 auto。"""
    ci = PrimaryContradictionIdentifier(selection_policy="invalid")
    assert ci.selection_policy == "auto"
