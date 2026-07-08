#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回滚计划验证器 (Rollback Validator)

验证项:
1. 回滚点存在且可执行
2. 触发条件可观测 (来自指标/告警/执行失败)
3. 回滚动作已定义且幂等
4. 与 hermes-rollback-actuator 格式兼容
"""

import os
from typing import Dict, Any, List
from pathlib import Path


class RollbackValidator:
    """
    回滚计划验证器

    验证流程:
    1. 检查 rollback_plan 是否存在
    2. 验证 rollback_points 存在且可执行
    3. 验证 triggers 可观测
    4. 验证 actions 已定义且幂等
    5. 验证与 hermes-rollback-actuator 兼容性
    """

    def __init__(self, workspace_dir: str = None):
        """
        初始化回滚验证器

        Args:
            workspace_dir: 工作目录，用于解析相对路径 (默认: 当前目录)
        """
        self.workspace_dir = workspace_dir or os.getcwd()

        # hermes-rollback-actuator 兼容字段
        self.compatible_fields = [
            "rollback_plan_id",
            "rollback_points",
            "triggers",
            "actions",
            "manual_trigger"
        ]

        # 可观测指标 (用于 triggers)
        self.observable_metrics = [
            "pnl", "max_drawdown", "sharpe",
            "trade_count", "skip_rate", "slippage_sensitivity",
            "reject_rate", "order_fail_rate", "equity", "balance",
            "win_rate", "loss_streak", "drawdown_duration"
        ]

        # 幂等操作列表
        self.idempotent_actions = [
            "restore_config", "restore_version", "revert_commit",
            "disable_feature", "enable_fallback", "stop_bot",
            "close_all_positions", "cancel_all_orders", "reset_to_default"
        ]

        # 非幂等/危险操作 (会警告)
        self.dangerous_actions = [
            "delete", "remove", "drop", "truncate",
            "rm", "del", "purge", "format"
        ]

    def validate(self, change_bundle: Dict[str, Any]) -> Dict[str, Any]:
        """
        验证回滚计划

        Returns:
            Dict: {
                "summary": "PASS" | "FAIL" | "WARN",
                "details": [...],
                "rollback_plan_id": str | None
            }
        """
        print("  验证回滚计划...")

        details = []
        has_error = False
        has_warn = False

        # 检查 1: rollback_plan 是否存在
        rollback_plan = change_bundle.get("rollback_plan")
        if not rollback_plan:
            details.append({
                "id": "R001",
                "check": "rollback_plan 存在性",
                "status": "FAIL",
                "message": "缺少 rollback_plan"
            })
            has_error = True
            print("    ✗ R001: 缺少 rollback_plan")
        else:
            # 检查 1 通过
            details.append({
                "id": "R001",
                "check": "rollback_plan 存在性",
                "status": "PASS",
                "message": "rollback_plan 存在"
            })
            print("    ✓ R001: rollback_plan 存在")

            # 检查 2: rollback_points 存在且可执行
            result_rollback_points = self._validate_rollback_points(rollback_plan)
            details.extend(result_rollback_points["details"])
            if result_rollback_points["has_error"]:
                has_error = True
            if result_rollback_points["has_warn"]:
                has_warn = True

            # 检查 3: triggers 可观测
            result_triggers = self._validate_triggers(rollback_plan)
            details.extend(result_triggers["details"])
            if result_triggers["has_error"]:
                has_error = True
            if result_triggers["has_warn"]:
                has_warn = True

            # 检查 4: actions 已定义且幂等
            result_actions = self._validate_actions(rollback_plan)
            details.extend(result_actions["details"])
            if result_actions["has_error"]:
                has_error = True
            if result_actions["has_warn"]:
                has_warn = True

            # 检查 5: 与 hermes-rollback-actuator 兼容性
            result_compat = self._validate_hermes_compatibility(rollback_plan)
            details.extend(result_compat["details"])
            if result_compat["has_error"]:
                has_error = True
            if result_compat["has_warn"]:
                has_warn = True

        # 确定 summary
        if has_error:
            summary = "FAIL"
        elif has_warn:
            summary = "WARN"
        else:
            summary = "PASS"

        # 提取 rollback_plan_id
        rollback_plan_id = None
        if rollback_plan and isinstance(rollback_plan, dict):
            rollback_plan_id = rollback_plan.get("rollback_plan_id")

        print(f"  回滚验证完成: {summary}")

        return {
            "summary": summary,
            "details": details,
            "rollback_plan_id": rollback_plan_id
        }

    def _validate_rollback_points(self, rollback_plan: Dict[str, Any]) -> Dict[str, Any]:
        """验证回滚点 - 检查路径是否真实存在"""
        details = []
        has_error = False
        has_warn = False

        rollback_points = rollback_plan.get("rollback_points", [])

        if not rollback_points:
            details.append({
                "id": "R002",
                "check": "回滚点存在性",
                "status": "FAIL",
                "message": "rollback_points 为空"
            })
            has_error = True
            print("    ✗ R002: rollback_points 为空")
        else:
            # 检查回滚点是否真实存在
            existing_points = []
            missing_points = []

            for i, point in enumerate(rollback_points):
                if not point or not isinstance(point, str):
                    details.append({
                        "id": f"R002-{i+1}",
                        "check": f"回滚点 {i+1} 格式",
                        "status": "WARN",
                        "message": f"回滚点格式异常: {point}"
                    })
                    has_warn = True
                    continue

                # 尝试解析路径
                if os.path.isabs(point):
                    full_path = point
                else:
                    full_path = os.path.join(self.workspace_dir, point)

                if os.path.exists(full_path):
                    existing_points.append(point)
                else:
                    missing_points.append(point)

            # 判断结果
            if missing_points and len(missing_points) == len(rollback_points):
                details.append({
                    "id": "R002",
                    "check": "回滚点存在性",
                    "status": "FAIL",
                    "message": f"所有回滚点都不存在: {missing_points}"
                })
                has_error = True
                print(f"    ✗ R002: 所有回滚点都不存在")
            elif missing_points:
                details.append({
                    "id": "R002",
                    "check": "回滚点存在性",
                    "status": "WARN",
                    "message": f"{len(missing_points)} 个回滚点不存在: {missing_points}"
                })
                has_warn = True
                print(f"    ⚠ R002: {len(missing_points)} 个回滚点不存在")
            else:
                details.append({
                    "id": "R002",
                    "check": "回滚点存在性",
                    "status": "PASS",
                    "message": f"所有 {len(existing_points)} 个回滚点均存在"
                })
                print(f"    ✓ R002: 所有回滚点存在")

        return {"details": details, "has_error": has_error, "has_warn": has_warn}

        return {"details": details, "has_error": has_error, "has_warn": has_warn}

    def _validate_triggers(self, rollback_plan: Dict[str, Any]) -> Dict[str, Any]:
        """验证触发条件可观测"""
        details = []
        has_error = False
        has_warn = False

        triggers = rollback_plan.get("triggers", [])

        if not triggers:
            details.append({
                "id": "R003",
                "check": "触发条件存在性",
                "status": "FAIL",
                "message": "triggers 为空，缺少自动触发条件"
            })
            has_error = True
            print("    ✗ R003: triggers 为空")
        else:
            # 检查触发条件是否可观测
            observable_count = 0
            for i, trigger in enumerate(triggers):
                if isinstance(trigger, str):
                    # 检查是否包含可观测指标
                    is_observable = any(metric in trigger.lower()
                                          for metric in self.observable_metrics)
                    if is_observable:
                        observable_count += 1
                    else:
                        details.append({
                            "id": f"R003-{i+1}",
                            "check": f"触发条件 {i+1} 可观测性",
                            "status": "WARN",
                            "message": f"触发条件可能不可观测: {trigger[:50]}..."
                        })
                        has_warn = True

            if observable_count == len(triggers):
                details.append({
                    "id": "R003",
                    "check": "触发条件可观测性",
                    "status": "PASS",
                    "message": f"所有 {len(triggers)} 个触发条件均可观测"
                })
                print(f"    ✓ R003: 所有触发条件可观测")
            else:
                details.append({
                    "id": "R003",
                    "check": "触发条件可观测性",
                    "status": "WARN",
                    "message": f"{observable_count}/{len(triggers)} 个触发条件可观测"
                })
                has_warn = True
                print(f"    ⚠ R003: {observable_count}/{len(triggers)} 个触发条件可观测")

        return {"details": details, "has_error": has_error, "has_warn": has_warn}

    def _validate_actions(self, rollback_plan: Dict[str, Any]) -> Dict[str, Any]:
        """验证回滚动作已定义且幂等 - 区分安全/警告/危险"""
        details = []
        has_error = False
        has_warn = False

        actions = rollback_plan.get("actions", [])

        if not actions:
            details.append({
                "id": "R004",
                "check": "回滚动作存在性",
                "status": "FAIL",
                "message": "actions 为空，缺少回滚动作定义"
            })
            has_error = True
            print("    ✗ R004: actions 为空")
        else:
            # 检查动作类型
            idempotent_count = 0
            dangerous_count = 0
            unknown_count = 0

            for i, action in enumerate(actions):
                if not isinstance(action, str):
                    unknown_count += 1
                    continue

                action_lower = action.lower()

                # 检查是否是幂等操作
                is_idempotent = any(idem in action_lower
                                          for idem in self.idempotent_actions)

                # 检查是否是危险操作
                is_dangerous = any(danger in action_lower
                                          for danger in self.dangerous_actions)

                if is_dangerous:
                    dangerous_count += 1
                    details.append({
                        "id": f"R004-{i+1}",
                        "check": f"回滚动作 {i+1} 安全性",
                        "status": "FAIL",
                        "message": f"回滚动作包含危险操作: {action[:50]}..."
                    })
                    has_error = True
                elif is_idempotent:
                    idempotent_count += 1
                else:
                    unknown_count += 1
                    details.append({
                        "id": f"R004-{i+1}",
                        "check": f"回滚动作 {i+1} 幂等性",
                        "status": "WARN",
                        "message": f"回滚动作可能不是幂等的: {action[:50]}..."
                    })
                    has_warn = True

            # 总结
            if dangerous_count > 0:
                details.append({
                    "id": "R004",
                    "check": "回滚动作安全性",
                    "status": "FAIL",
                    "message": f"包含 {dangerous_count} 个危险操作"
                })
                has_error = True
                print(f"    ✗ R004: 包含 {dangerous_count} 个危险操作")
            elif idempotent_count == len(actions):
                details.append({
                    "id": "R004",
                    "check": "回滚动作幂等性",
                    "status": "PASS",
                    "message": f"所有 {len(actions)} 个回滚动作均幂等"
                })
                print(f"    ✓ R004: 所有回滚动作幂等")
            else:
                details.append({
                    "id": "R004",
                    "check": "回滚动作幂等性",
                    "status": "WARN",
                    "message": f"幂等: {idempotent_count}, 未知: {unknown_count}, 总计: {len(actions)}"
                })
                has_warn = True
                print(f"    ⚠ R004: 部分回滚动作可能不是幂等的")

        return {"details": details, "has_error": has_error, "has_warn": has_warn}

    def _validate_hermes_compatibility(self, rollback_plan: Dict[str, Any]) -> Dict[str, Any]:
        """验证与 hermes-rollback-actuator 兼容性"""
        details = []
        has_error = False
        has_warn = False

        # 检查兼容字段
        missing_fields = [field for field in self.compatible_fields
                         if field not in rollback_plan]

        if not missing_fields:
            details.append({
                "id": "R005",
                "check": "hermes 兼容性",
                "status": "PASS",
                "message": "所有兼容字段齐全"
            })
            print("    ✓ R005: hermes 兼容性检查通过")
        else:
            # 部分字段缺失，只警告
            details.append({
                "id": "R005",
                "check": "hermes 兼容性",
                "status": "WARN",
                "message": f"缺少兼容字段: {missing_fields}"
            })
            has_warn = True
            print(f"    ⚠ R005: 缺少兼容字段: {missing_fields}")

        return {"details": details, "has_error": has_error, "has_warn": has_warn}


def test_rollback_validator():
    """测试回滚验证器"""
    validator = RollbackValidator()

    # 测试 1: 完整回滚计划
    bundle_pass = {
        "rollback_plan": {
            "rollback_plan_id": "rollback_001",
            "rollback_points": ["v1.0", "snap_20260506"],
            "triggers": ["max_drawdown > 0.05", "pnl < -100"],
            "actions": ["restore_config", "disable_feature"],
            "manual_trigger": "人工确认"
        }
    }

    print("测试 1: 完整回滚计划 (期望: PASS)")
    result_pass = validator.validate(bundle_pass)
    print(f"结果: {result_pass['summary']}\n")

    # 测试 2: 缺失字段
    bundle_fail = {
        "rollback_plan": {
            "rollback_plan_id": "rollback_002"
        }
    }

    print("测试 2: 缺失字段 (期望: FAIL)")
    result_fail = validator.validate(bundle_fail)
    print(f"结果: {result_fail['summary']}")


if __name__ == "__main__":
    test_rollback_validator()
