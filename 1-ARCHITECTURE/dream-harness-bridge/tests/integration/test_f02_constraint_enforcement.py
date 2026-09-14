#!/usr/bin/env python3
"""F-02: 协议级不变式强制硬约束 — Python 侧测试

测试目标:
1. 交易路径硬约束检查正确
2. BDSM direction_constraint 拦截
3. MAX_TRIAL_POSITIONS 拦截
4. 非交易路径不需要 constraint_passed

来源: SPEC v0.3 七补.1 F-02
"""

import json
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "packages", "python-server"))

from sdk.protocol_server import create_protocol_server
from server import check_hard_constraints


class TestF02TradingMethod:
    """F-02: 交易路径识别"""

    def test_execute_node_is_trading(self):
        result = check_hard_constraints("execute_node", {})
        assert result["is_trading"] is True

    def test_open_position_is_trading(self):
        result = check_hard_constraints("open_position", {})
        assert result["is_trading"] is True

    def test_close_position_is_trading(self):
        result = check_hard_constraints("close_position", {})
        assert result["is_trading"] is True

    def test_modify_position_is_trading(self):
        result = check_hard_constraints("modify_position", {})
        assert result["is_trading"] is True

    def test_ping_not_trading(self):
        result = check_hard_constraints("ping", {})
        assert result["is_trading"] is False

    def test_memory_recall_not_trading(self):
        result = check_hard_constraints("memory_recall", {})
        assert result["is_trading"] is False


class TestF02BDSMDirectionConstraint:
    """F-02: BDSM direction_constraint 硬约束"""

    def test_long_only_blocks_short(self):
        result = check_hard_constraints("execute_node", {
            "direction_constraint": "LONG_ONLY",
            "direction": "SHORT",
        })
        assert result["passed"] is False
        assert any("LONG_ONLY" in v for v in result["violations"])

    def test_short_only_blocks_long(self):
        result = check_hard_constraints("execute_node", {
            "direction_constraint": "SHORT_ONLY",
            "direction": "LONG",
        })
        assert result["passed"] is False
        assert any("SHORT_ONLY" in v for v in result["violations"])

    def test_long_only_allows_long(self):
        result = check_hard_constraints("execute_node", {
            "direction_constraint": "LONG_ONLY",
            "direction": "LONG",
        })
        assert result["passed"] is True

    def test_neutral_allows_both(self):
        result_long = check_hard_constraints("execute_node", {
            "direction_constraint": "NEUTRAL",
            "direction": "LONG",
        })
        result_short = check_hard_constraints("execute_node", {
            "direction_constraint": "NEUTRAL",
            "direction": "SHORT",
        })
        assert result_long["passed"] is True
        assert result_short["passed"] is True


class TestF02MaxTrialPositions:
    """F-02: BCRM2.0 MAX_TRIAL_POSITIONS = 2 硬约束"""

    def test_third_trial_position_blocked(self):
        result = check_hard_constraints("execute_node", {
            "check": "MAX_TRIAL_POSITIONS",
            "trial_count": 2,
        })
        assert result["passed"] is False
        assert any("MAX_TRIAL_POSITIONS" in v for v in result["violations"])

    def test_second_trial_position_allowed(self):
        result = check_hard_constraints("execute_node", {
            "check": "MAX_TRIAL_POSITIONS",
            "trial_count": 1,
        })
        assert result["passed"] is True


class TestF02NonTradingPath:
    """F-02: 非交易路径不需要 constraint_passed"""

    def test_ping_no_constraint_check(self):
        result = check_hard_constraints("ping", {})
        assert result["passed"] is True
        assert result["is_trading"] is False

    def test_memory_recall_no_constraint_check(self):
        result = check_hard_constraints("memory_recall", {})
        assert result["passed"] is True
        assert result["is_trading"] is False


class TestF02ConstraintPassedInResponse:
    """F-02: 交易路径响应包含 constraint_passed"""

    def test_trading_response_has_constraint_passed(self):
        server = create_protocol_server()
        resp = server.build_response(
            ok=True,
            result={"echo": {"method": "execute_node", "params": {}}},
            opts={"constraint_passed": True},
        )
        assert resp.get("constraint_passed") is True

    def test_non_trading_response_no_constraint_passed(self):
        server = create_protocol_server()
        resp = server.build_response(
            ok=True,
            result={"data": "recall"},
        )
        assert resp.get("constraint_passed") is None
