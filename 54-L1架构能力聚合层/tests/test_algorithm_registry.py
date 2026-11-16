# -*- coding: utf-8 -*-
"""算法注册表校验单测（TASKS-20261116 T3-5）。"""

from __future__ import annotations

import copy
import os
import sys

import pytest

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
for _path in (_MODULE_ROOT, os.path.join(_MODULE_ROOT, "scripts")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from validate_algorithm_registry import (  # noqa: E402
    REGISTRY_PATH,
    SPACE_PATH,
    _load,
    validate,
)


@pytest.fixture(scope="module")
def fixtures():
    return _load(REGISTRY_PATH), _load(SPACE_PATH)


def test_real_registry_is_valid(fixtures):
    registry, space = fixtures
    assert validate(registry, space) == []


def test_all_space_methods_are_mapped(fixtures):
    registry, space = fixtures
    roles = registry["method_roles"]
    assert set(roles) == set(space["methods"])
    assert len(space["methods"]) == 20


def test_unknown_method_rejected(fixtures):
    registry, space = fixtures
    broken = copy.deepcopy(registry)
    broken["packages"][0]["methods"].append("ZZ99")
    errors = validate(broken, space)
    assert any("ZZ99" in item for item in errors)


def test_horizon_outside_space_rejected(fixtures):
    registry, space = fixtures
    broken = copy.deepcopy(registry)
    broken["packages"][0]["horizons"] = [3]
    errors = validate(broken, space)
    assert any("期限 3" in item for item in errors)


def test_r6_package_rejected_while_disabled(fixtures):
    registry, space = fixtures
    broken = copy.deepcopy(registry)
    broken["packages"].append(
        {
            "id": "ALG-R6-999",
            "relation_type": "R6",
            "name": "越界包",
            "methods": ["B14"],
            "transforms": ["raw"],
            "horizons": [5],
            "min_n": 250,
            "status": "enabled",
        }
    )
    errors = validate(broken, space)
    assert any("R6" in item and "unused" not in item for item in errors)


def test_space_version_mismatch_rejected(fixtures):
    registry, space = fixtures
    broken = copy.deepcopy(registry)
    broken["source"]["space_version"] = 99
    errors = validate(broken, space)
    assert any("space_version" in item for item in errors)


def test_min_n_floor_enforced(fixtures):
    registry, space = fixtures
    broken = copy.deepcopy(registry)
    broken["packages"][0]["min_n"] = 100
    errors = validate(broken, space)
    assert any("min_n" in item for item in errors)


def test_missing_method_role_rejected(fixtures):
    registry, space = fixtures
    broken = copy.deepcopy(registry)
    broken["method_roles"].pop("B14")
    errors = validate(broken, space)
    assert any("B14" in item for item in errors)
