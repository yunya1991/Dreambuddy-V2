"""
端到端测试：auto_exit_system.py 步骤 1.5 挂载、资金调控报告产物生成。

运行方式::

    cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
    python -m pytest 16-调控系统/tests/capital_control/test_e2e.py -v
"""

import sys
import os
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

_PROJECT = Path(__file__).resolve().parents[3]
_CORE = _PROJECT / "16-调控系统" / "core"
_SCRIPTS = _PROJECT / "16-调控系统" / "scripts"
_RISK = _PROJECT / "13-通用风控模块"
_RISK_CORE = _RISK / "core"
for _p in (_CORE, _SCRIPTS, _RISK, _RISK_CORE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pytest


def _mock_positions_data(positions=None, equity_map=None):
    """构造 mock fetch_all_positions 返回值"""
    equity_map = equity_map or {}
    systems = {}
    for sys_name, eq in equity_map.items():
        acct_map = {
            "v15_martin": "okx_live",
            "yijing_bcrm": "okx_simulated",
            "agent_a": "hyperliquid",
            "agent_b": "hyperliquid",
            "agent_c_memory": "hyperliquid",
            "three_screen": "aster",
        }
        systems[sys_name] = {
            "equity": eq,
            "extra": {"avail_balance": eq, "used_margin": 0.0, "account_type": acct_map.get(sys_name, "unknown")},
        }
    return {
        "version": "1.1",
        "total_equity": sum(equity_map.values()),
        "equity_by_system": equity_map,
        "systems": systems,
        "positions": positions or [],
        "total_systems": len(systems),
    }


# =========================================================================
# _write_capital_report 测试
# =========================================================================


class TestWriteCapitalReport:
    def test_report_generation(self, tmp_path):
        """测试资金调控报告 JSON 产物结构"""
        from capital_control.types import (
            AccountType,
            CapitalMode, CapitalResult, CapitalSnapshot, HealthLevel, now_iso,
        )

        # 构造 mock snapshot
        r = CapitalResult(
            system="v15_martin",
            account_type=AccountType.OKX_LIVE,
            mode=CapitalMode.DYNAMIC,
            total_eq=260.5,
            avail_balance=180.3,
            used_margin=80.2,
            used_pct=30.79,
        )
        snap = CapitalSnapshot(
            timestamp=now_iso(),
            mode=CapitalMode.DYNAMIC,
            by_system={"v15_martin": r},
            total_equity=260.5,
            total_avail=180.3,
            total_used=80.2,
            overall_used_pct=30.79,
            health=HealthLevel.HEALTHY,
        )

        # 调用 _write_capital_report
        import auto_exit_system
        # mock BASE_DIR 为 tmp_path
        original_base = auto_exit_system.BASE_DIR
        auto_exit_system.BASE_DIR = tmp_path
        try:
            report_path = auto_exit_system._write_capital_report(
                snap, _mock_positions_data(equity_map={"v15_martin": 260.5})
            )
        finally:
            auto_exit_system.BASE_DIR = original_base

        assert report_path.exists()
        with open(report_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["mode"] == "dynamic"
        assert data["health"] == "HEALTHY"
        assert "by_system" in data
        assert "by_account" in data
        assert "totals" in data
        assert data["totals"]["total_equity"] == 260.5
        assert "positions_summary" in data


# =========================================================================
# auto_exit_system 步骤 1.5 挂载测试
# =========================================================================


class TestAutoExitSystemStep15:
    def test_step_15_executes(self):
        """步骤 1.5 资金调控在 run_exit_evaluation_cycle 中执行"""
        import auto_exit_system

        mock_data = _mock_positions_data(
            positions=[],
            equity_map={
                "v15_martin": 260.0,
                "yijing_bcrm": 150.0,
                "agent_a": 60.0,
                "agent_b": 60.0,
                "agent_c_memory": 60.0,
                "three_screen": 200.0,
            },
        )

        with patch("unified_position_query.fetch_all_positions", return_value=mock_data):
            result = auto_exit_system.run_exit_evaluation_cycle()

        # 无持仓时应返回 success
        assert result["status"] == "success"
        assert result["reason"] == "no_positions"

    def test_capital_report_artifact_generated(self):
        """步骤 1.5 生成 capital-reports 产物"""
        import auto_exit_system

        mock_data = _mock_positions_data(
            positions=[],
            equity_map={"v15_martin": 260.0, "yijing_bcrm": 150.0},
        )

        with patch("unified_position_query.fetch_all_positions", return_value=mock_data):
            auto_exit_system.run_exit_evaluation_cycle()

        # 检查产物目录
        reports_dir = auto_exit_system.BASE_DIR / "artifacts" / "capital-reports"
        reports = list(reports_dir.glob("capital_*.json"))
        assert len(reports) >= 1

        # 验证最新产物
        latest = max(reports, key=lambda p: p.stat().st_mtime)
        with open(latest, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert "mode" in data
        assert "health" in data
        assert "by_system" in data
        assert "totals" in data

    def test_capital_failure_doesnt_crash_main(self):
        """资金调控失败不影响主流程"""
        import auto_exit_system
        import capital_control

        mock_data = _mock_positions_data(positions=[])

        with patch("unified_position_query.fetch_all_positions", return_value=mock_data):
            # mock CapitalControlComponent 构造抛异常
            with patch.object(capital_control, "CapitalControlComponent", side_effect=Exception("mock failure")):
                result = auto_exit_system.run_exit_evaluation_cycle()

        # 即使 capital_control 失败，主流程仍应正常（WARN 日志）
        assert result["status"] == "success"


# =========================================================================
# 配置文件验证测试
# =========================================================================


class TestConfigFile:
    def test_config_json_valid(self):
        """capital_control.json 可被 json.load 解析"""
        config_path = _CORE.parent / "config" / "capital_control.json"
        assert config_path.exists()
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        assert "mode" in cfg
        assert "enabled_systems" in cfg
        assert "fallback_static_budget" in cfg
        assert "phase2" in cfg
        assert cfg["phase2"]["enabled"] is False

    def test_example_config_exists(self):
        config_path = _CORE.parent / "config" / "capital_control.example.json"
        assert config_path.exists()
