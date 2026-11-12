# -*- coding: utf-8 -*-
"""W3：8 角色白名单与 G2 连接聚合校验。"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.worker_roles import (  # noqa: E402
    MAX_TOOLS_PER_ROLE,
    WRITE_TOOLS,
    RolePolicy,
    g2_summary,
    load_worker_roles,
)


def test_registry_has_eight_readonly_roles():
    roles = load_worker_roles()
    assert len(roles) == 8
    assert RolePolicy(roles).validate() == []
    for role, cfg in roles.items():
        assert 1 <= len(cfg["tools"]) <= MAX_TOOLS_PER_ROLE, role
        assert not (set(cfg["tools"]) & WRITE_TOOLS), role


def test_forbidden_tool_anchors():
    roles = load_worker_roles()
    assert "eval_analyze" not in roles["engineer"]["tools"]
    assert "record" not in roles["lobehub_frontend"]["tools"]
    assert {"place_order", "cancel_order", "ingest_signal", "forward_signal"} & set(
        roles["executor"]["tools"]
    ) == set()


def test_unknown_role_and_tool_scope():
    policy = RolePolicy({"research": {"tools": ["recall", "unified_search"], "shells": ["x"]}})

    assert policy.check("research") is None
    assert policy.check("research", ["recall", "unified_search"]) is None
    assert "not allowed" in policy.check("research", ["eval_analyze"])
    assert "not allowed" in policy.check("research", ["recall", "place_order"])
    assert "whitelist" in policy.check("verifier")
    assert policy.check("research", []) is None


def test_validate_reports_registry_violations():
    policy = RolePolicy(
        {
            "bad": {"tools": ["a", "record"], "shells": []},
            "too_many": {
                "tools": ["t%d" % i for i in range(MAX_TOOLS_PER_ROLE + 1)],
                "shells": ["s"],
            },
            "dup": {"tools": ["a", "a"], "shells": ["s"]},
            "empty": {"tools": [], "shells": ["s"]},
        }
    )
    problems = policy.validate()

    assert any("write tools forbidden" in p for p in problems)
    assert any("empty shells" in p for p in problems)
    assert any("> max" in p for p in problems)
    assert any("duplicate tools" in p for p in problems)
    assert any("empty tool set" in p for p in problems)


def test_g2_role_gateways_share_one_entrypoint():
    summary = g2_summary()

    assert summary["connections_independent_of_roles"] is True
    assert len(summary["role_scoped_entrypoints"]) == 1
    # 角色网关多个 profile 共用同一入口 → 连接数不随 Worker 数增长
    assert len(summary["role_scoped_profiles"]) > len(summary["role_scoped_entrypoints"])
