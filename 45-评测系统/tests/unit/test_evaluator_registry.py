# -*- coding: utf-8 -*-
"""test_evaluator_registry.py — P2-9 评测器注册与版本锁定。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from evaluators.registry import (  # noqa: E402
    EvaluatorNotFoundError,
    EvaluatorRef,
    EvaluatorRegistry,
    RegistryError,
    load_defaults,
)


def test_register_and_resolve_exact_version():
    registry = EvaluatorRegistry()
    marker = object()
    registry.register("demo", "1.0.0", marker)
    assert registry.resolve("demo", "1.0.0") is marker


def test_resolve_latest_when_version_omitted():
    registry = EvaluatorRegistry()
    old, new = object(), object()
    registry.register("demo", "1.9.0", old)
    registry.register("demo", "1.10.0", new)
    assert registry.resolve("demo") is new


def test_unregistered_evaluator_is_rejected():
    registry = EvaluatorRegistry()
    with pytest.raises(EvaluatorNotFoundError):
        registry.resolve("not-registered", "1.0.0")


def test_wrong_version_is_rejected():
    registry = EvaluatorRegistry()
    registry.register("demo", "1.0.0", object())
    with pytest.raises(EvaluatorNotFoundError):
        registry.resolve("demo", "2.0.0")


def test_duplicate_registration_rejected():
    registry = EvaluatorRegistry()
    registry.register("demo", "1.0.0", object())
    with pytest.raises(RegistryError):
        registry.register("demo", "1.0.0", object())


@pytest.mark.parametrize("version", ["1.0", "v1", "1.0.0-beta", ""])
def test_invalid_version_rejected(version):
    with pytest.raises(RegistryError):
        EvaluatorRegistry().register("demo", version, object())


def test_lock_pins_version_even_after_newer_registered():
    registry = EvaluatorRegistry()
    old, new = object(), object()
    registry.register("demo", "1.0.0", old)
    locked = registry.lock("demo")
    assert locked == EvaluatorRef(name="demo", version="1.0.0")
    registry.register("demo", "1.1.0", new)
    assert registry.resolve(locked.name, locked.version) is old


def test_names_and_versions_sorted():
    registry = EvaluatorRegistry()
    registry.register("b", "1.0.0", object())
    registry.register("a", "2.0.0", object())
    registry.register("a", "1.0.0", object())
    assert registry.names() == ("a", "b")
    assert registry.versions("a") == ("1.0.0", "2.0.0")


def test_load_defaults_registers_all_p2_evaluators():
    registry = load_defaults()
    expected = {
        "e3",
        "finance-availability",
        "finance-backtest-stats",
        "ai-judge-calibration",
        "ai-stress",
        "engineering-scan",
        "engineering-tests",
    }
    assert set(registry.names()) == expected
    for name in expected:
        assert registry.resolve(name) is not None


def test_defaults_versions_are_locked():
    registry = load_defaults()
    for name in registry.names():
        assert set(registry.versions(name)) == {"1.0.0"}
        assert registry.lock(name).version == "1.0.0"
