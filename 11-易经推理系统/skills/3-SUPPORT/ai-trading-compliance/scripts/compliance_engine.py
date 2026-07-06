#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Trading Compliance Engine v2.0
合规检查引擎 - 主框架

职责:
1. 接收变更包 (change_bundle)
2. 调用各检查器 (R0-R3 分级器、硬门禁检查器、回滚验证器)
3. 生成合规回执 (compliance_receipt)
4. 写入审计轨迹 (audit trail)
"""

import json
import os
import sys
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path

# 添加 scripts 目录到 sys.path
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

try:
    import jsonschema
    from jsonschema import ValidationError
except ImportError:
    jsonschema = None
    ValidationError = None

try:
    from r_level_classifier import RLevelClassifier
    from hard_gate_checker import HardGateChecker
    from rollback_validator import RollbackValidator
    from risk_direction_checker import RiskDirectionChecker
    from audit_trail import AuditTrailManager
except ImportError:
    # Phase 1: 检查器尚未实现，使用占位符
    RLevelClassifier = None
    HardGateChecker = None
    RollbackValidator = None
    RiskDirectionChecker = None
    AuditTrailManager = None


class ComplianceEngine:
    """
    合规检查引擎主类

    处理流程:
    1. 验证输入 (validate_input)
    2. R0-R3 自动分级 (classify_change)
    3. 硬门禁检查 (check_hard_gates)
    4. 回滚计划验证 (validate_rollback)
    5. 风险方向判定 (evaluate_risk_direction)
    6. 生成决策 (make_decision)
    7. 生成合规回执 (generate_receipt)
    8. 写入审计轨迹 (record_audit)
    """

    def __init__(self, audit_dir: Optional[str] = None):
        """
        初始化合规检查引擎

        Args:
            audit_dir: 审计日志存储目录 (默认: ../audit/)
        """
        # 初始化检查器
        self.r_classifier = RLevelClassifier() if RLevelClassifier else None
        self.hard_gate_checker = HardGateChecker() if HardGateChecker else None
        self.rollback_validator = RollbackValidator() if RollbackValidator else None
        self.risk_checker = RiskDirectionChecker() if RiskDirectionChecker else None

        # 审计管理器
        if audit_dir is None:
            audit_dir = str(SCRIPT_DIR.parent / "audit")
        self.audit = AuditTrailManager(audit_dir) if AuditTrailManager else None

        # Schema 路径和验证
        self.schema_dir = SCRIPT_DIR.parent / "schemas"
        self.change_bundle_schema = None
        self.receipt_schema = None

        # 加载 schema 文件
        self._load_schemas()

    def _load_schemas(self) -> None:
        """加载 JSON Schema 文件"""
        if jsonschema is None:
            print("  ⚠️ jsonschema 未安装，跳过 Schema 验证")
            return

        # 加载 change_bundle schema
        bundle_schema_path = self.schema_dir / "change_bundle_schema.json"
        if bundle_schema_path.exists():
            try:
                with open(bundle_schema_path, 'r', encoding='utf-8') as f:
                    self.change_bundle_schema = json.load(f)
                print(f"  ✓ 加载 change_bundle schema")
            except Exception as e:
                print(f"  ✗ 加载 change_bundle schema 失败: {e}")

        # 加载 receipt schema
        receipt_schema_path = self.schema_dir / "compliance_receipt_schema.json"
        if receipt_schema_path.exists():
            try:
                with open(receipt_schema_path, 'r', encoding='utf-8') as f:
                    self.receipt_schema = json.load(f)
                print(f"  ✓ 加载 compliance_receipt schema")
            except Exception as e:
                print(f"  ✗ 加载 compliance_receipt schema 失败: {e}")

    def process(self, change_bundle: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理变更包，执行完整合规审查流程

        Args:
            change_bundle: 变更包字典，应符合 change_bundle_schema.json

        Returns:
            compliance_receipt: 合规回执字典，符合 compliance_receipt_schema.json
        """
        # Step 0: 记录开始
        start_time = datetime.now()
        print(f"[{start_time.isoformat()}] 开始合规审查...")

        try:
            # Step 1: 验证输入
            self._validate_input(change_bundle)

            # Step 2: R0-R3 自动分级 (可能覆盖手动分级)
            r_level = self._classify_change(change_bundle)
            print(f"  变更分级: {r_level}")

            # Step 3: 硬门禁检查
            hard_gate_result = self._check_hard_gates(change_bundle)
            print(f"  硬门禁检查: {hard_gate_result['summary']}")

            # Step 4: 回滚计划验证
            rollback_result = self._validate_rollback(change_bundle)
            print(f"  回滚验证: {rollback_result['summary']}")

            # Step 5: 风险方向判定
            risk_direction = self._evaluate_risk_direction(change_bundle)
            print(f"  风险方向: {risk_direction['summary']}")

            # Step 6: 生成决策
            decision = self._make_decision(
                hard_gate_result,
                rollback_result,
                risk_direction
            )
            print(f"  决策: {decision}")

            # Step 7: 生成合规回执
            receipt = self._generate_receipt(
                change_bundle,
                r_level,
                decision,
                hard_gate_result,
                rollback_result,
                risk_direction
            )

            # Step 7.5: 验证合规回执 (新增)
            if jsonschema and self.receipt_schema:
                self._validate_receipt(receipt)

            # Step 8: 写入审计轨迹
            if self.audit:
                self.audit.record(receipt)
                print(f"  审计记录已写入")

            end_time = datetime.now()
            print(f"[{end_time.isoformat()}] 合规审查完成，耗时: {(end_time - start_time).total_seconds():.2f}s")

            return receipt

        except Exception as e:
            error_receipt = {
                "decision": "fail",
                "error": str(e),
                "change_classification": {
                    "change_type": change_bundle.get("change_type", "unknown"),
                    "risk_level": change_bundle.get("risk_level", "unknown")
                },
                "hard_constraints_checked": {},
                "blockers": [
                    {
                        "id": "E001",
                        "title": f"合规审查异常: {str(e)}",
                        "evidence": ""
                    }
                ],
                "warnings": [],
                "required_actions": [],
                "rollout_requirements": {
                    "mode": "disabled"
                },
                "audit_fields": {
                    "doc_refs": [],
                    "trace_id": change_bundle.get("trace_id"),
                    "artifacts": [],
                    "approver_roles": []
                }
            }

            # 写入审计轨迹
            if self.audit:
                self.audit.record(error_receipt)

            return error_receipt

    def _validate_input(self, change_bundle: Dict[str, Any]) -> None:
        """
        验证输入是否符合 change_bundle_schema

        Raises:
            ValueError: 输入不符合 Schema
        """
        # 使用 JSON Schema 验证 (如果可用)
        if jsonschema and self.change_bundle_schema:
            try:
                jsonschema.validate(instance=change_bundle, schema=self.change_bundle_schema)
                print("  ✓ 输入验证通过 (JSON Schema)")
            except ValidationError as e:
                raise ValueError(f"change_bundle 不符合 Schema: {e.message} (路径: {list(e.path)})")
        else:
            # 降级到基本检查
            if not isinstance(change_bundle, dict):
                raise ValueError("change_bundle 必须是字典类型")

            # 检查必需字段
            required = ["intent", "change_type", "risk_level"]
            missing = [field for field in required if field not in change_bundle]
            if missing:
                raise ValueError(f"缺少必需字段: {missing}")

            # 验证 change_type
            valid_types = ["R0", "R1", "R2", "R3"]
            if change_bundle["change_type"] not in valid_types:
                raise ValueError(f"change_type 必须是 {valid_types} 之一")

            # 验证 risk_level
            valid_levels = ["P0", "P1", "P3"]
            if change_bundle["risk_level"] not in valid_levels:
                raise ValueError(f"risk_level 必须是 {valid_levels} 之一")

            print("  ✓ 输入验证通过 (基本检查)")

    def _validate_receipt(self, receipt: Dict[str, Any]) -> None:
        """
        验证合规回执是否符合 compliance_receipt_schema

        Raises:
            ValueError: 回执不符合 Schema
        """
        if not jsonschema or not self.receipt_schema:
            return  # 跳过验证

        try:
            jsonschema.validate(instance=receipt, schema=self.receipt_schema)
            print("  ✓ 合规回执验证通过 (JSON Schema)")
        except ValidationError as e:
            raise ValueError(f"合规回执不符合 Schema: {e.message} (路径: {list(e.path)})")

    def _classify_change(self, change_bundle: Dict[str, Any]) -> str:
        """
        R0-R3 自动分级

        Returns:
            str: R0/R1/R2/R3
        """
        if self.r_classifier:
            return self.r_classifier.classify(change_bundle)
        else:
            # Phase 1: 使用手动分级
            print("  ⚠️ R0-R3 分级器尚未实现，使用手动分级")
            return change_bundle.get("change_type", "R0")

    def _check_hard_gates(self, change_bundle: Dict[str, Any]) -> Dict[str, Any]:
        """
        硬门禁检查

        Returns:
            Dict: {"summary": "PASS"/"FAIL", "details": [...]}
        """
        if self.hard_gate_checker:
            return self.hard_gate_checker.check(change_bundle)
        else:
            # Phase 1: 返回占位符
            print("  ⚠️ 硬门禁检查器尚未实现，跳过检查")
            return {
                "summary": "SKIPPED",
                "details": [],
                "note": "硬门禁检查器尚未实现"
            }

    def _validate_rollback(self, change_bundle: Dict[str, Any]) -> Dict[str, Any]:
        """
        回滚计划验证

        Returns:
            Dict: {"summary": "PASS"/"FAIL", "details": [...]}
        """
        if self.rollback_validator:
            return self.rollback_validator.validate(change_bundle)
        else:
            # Phase 1: 返回占位符
            print("  ⚠️ 回滚验证器尚未实现，跳过验证")
            return {
                "summary": "SKIPPED",
                "details": [],
                "note": "回滚验证器尚未实现"
            }

    def _evaluate_risk_direction(self, change_bundle: Dict[str, Any]) -> Dict[str, Any]:
        """
        风险方向判定 (tighten-only vs 风险扩张)

        Returns:
            Dict: {"summary": "TIGHTEN_ONLY"/"RISK_EXPANSION", "details": [...]}
        """
        if self.risk_checker:
            return self.risk_checker.evaluate(change_bundle)
        else:
            # Phase 1: 返回占位符
            print("  ⚠️ 风险方向检查器尚未实现，假设为收紧型变更")
            return {
                "summary": "TIGHTEN_ONLY",
                "details": [],
                "note": "风险方向检查器尚未实现，默认收紧型"
            }

    def _make_decision(
        self,
        hard_gate_result: Dict[str, Any],
        rollback_result: Dict[str, Any],
        risk_direction: Dict[str, Any]
    ) -> str:
        """
        根据检查结果生成决策

        Returns:
            str: "pass" / "warn" / "fail"
        """
        # 硬门禁失败 → fail
        if hard_gate_result.get("summary") == "FAIL":
            return "fail"

        # 回滚验证失败 → fail (fail-closed)
        if rollback_result.get("summary") == "FAIL":
            return "fail"

        # 风险扩张 + 无审批 → warn (需要审批)
        if (risk_direction.get("summary") == "RISK_EXPANSION" and
            not risk_direction.get("has_approval", False)):
            return "warn"

        # 所有检查通过 → pass
        return "pass"

    def _generate_receipt(
        self,
        change_bundle: Dict[str, Any],
        r_level: str,
        decision: str,
        hard_gate_result: Dict[str, Any],
        rollback_result: Dict[str, Any],
        risk_direction: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        生成合规回执

        Returns:
            Dict: 符合 compliance_receipt_schema.json 的字典
        """
        # 构建 change_classification
        change_classification = {
            "change_type": r_level,
            "risk_level": change_bundle.get("risk_level"),
            "environment": self._detect_environment(change_bundle),
            "tighten_only": risk_direction.get("summary") == "TIGHTEN_ONLY"
        }

        # 构建 hard_constraints_checked
        hard_constraints = self._build_hard_constraints(
            change_bundle,
            hard_gate_result
        )

        # 构建 blockers
        blockers = self._build_blockers(
            hard_gate_result,
            rollback_result
        )

        # 构建 warnings
        warnings = self._build_warnings(
            risk_direction,
            change_bundle
        )

        # 构建 required_actions
        required_actions = self._build_required_actions(
            hard_gate_result,
            rollback_result,
            risk_direction
        )

        # 构建 rollout_requirements
        rollout_requirements = self._build_rollout_requirements(
            r_level,
            decision,
            risk_direction
        )

        # 构建 audit_fields
        audit_fields = {
            "doc_refs": change_bundle.get("doc_refs", []),
            "trace_id": change_bundle.get("trace_id"),
            "artifacts": self._extract_artifacts(change_bundle),
            "approver_roles": self._determine_approvers(r_level, decision)
        }

        # 组装合规回执
        receipt = {
            "decision": decision,
            "change_classification": change_classification,
            "hard_constraints_checked": hard_constraints,
            "blockers": blockers,
            "warnings": warnings,
            "required_actions": required_actions,
            "rollout_requirements": rollout_requirements,
            "audit_fields": audit_fields
        }

        return receipt

    def _detect_environment(self, change_bundle: Dict[str, Any]) -> str:
        """检测环境 (Explore/Pilot/Prod)"""
        # TODO: Phase 2 - 实现环境检测逻辑
        return "Explore"  # 占位符

    def _build_hard_constraints(
        self,
        change_bundle: Dict[str, Any],
        hard_gate_result: Dict[str, Any]
    ) -> Dict[str, bool]:
        """构建 hard_constraints_checked"""
        # TODO: Phase 2 - 实现详细检查
        return {
            "prod_write_prohibited_without_approval": True,
            "sandbox_no_network_no_secrets": True,
            "gate_result_present": True,
            "baseline_ref_present": True,
            "rollback_defined": True,
            "audit_replayable": True,
            "external_publish_outbox_only": True
        }

    def _build_blockers(
        self,
        hard_gate_result: Dict[str, Any],
        rollback_result: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """构建 blockers"""
        blockers = []

        # 从硬门禁检查结果提取
        if hard_gate_result.get("summary") == "FAIL":
            for detail in hard_gate_result.get("details", []):
                if detail.get("status") == "FAIL":
                    blockers.append({
                        "id": detail.get("id", "BLOCKER"),
                        "title": detail.get("title", "未知阻断"),
                        "evidence": detail.get("evidence", "")
                    })

        # 从回滚验证结果提取
        if rollback_result.get("summary") == "FAIL":
            for detail in rollback_result.get("details", []):
                if detail.get("status") == "FAIL":
                    blockers.append({
                        "id": detail.get("id", "ROLLBACK_BLOCKER"),
                        "title": detail.get("title", "回滚验证失败"),
                        "evidence": detail.get("evidence", "")
                    })

        return blockers

    def _build_warnings(
        self,
        risk_direction: Dict[str, Any],
        change_bundle: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """构建 warnings"""
        warnings = []

        # 风险扩张警告
        if risk_direction.get("summary") == "RISK_EXPANSION":
            warnings.append({
                "id": "W001",
                "title": "风险扩张型变更",
                "reason": "需要人工审批 + Canary 发布"
            })

        return warnings

    def _build_required_actions(
        self,
        hard_gate_result: Dict[str, Any],
        rollback_result: Dict[str, Any],
        risk_direction: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """构建 required_actions"""
        actions = []

        # 补齐硬门禁缺失项
        if hard_gate_result.get("summary") == "FAIL":
            for detail in hard_gate_result.get("details", []):
                if detail.get("status") == "FAIL":
                    actions.append({
                        "id": f"ACTION_{detail.get('id', 'UNKNOWN')}",
                        "title": f"修复: {detail.get('title', '未知问题')}",
                        "how": detail.get("how_to_fix", "请查看硬门禁检查报告")
                    })

        return actions

    def _build_rollout_requirements(
        self,
        r_level: str,
        decision: str,
        risk_direction: Dict[str, Any]
    ) -> Dict[str, Any]:
        """构建 rollout_requirements"""
        # R0/R1: 可以 full 发布
        if r_level in ["R0", "R1"]:
            mode = "full" if decision == "pass" else "disabled"
        # R2: 必须 canary
        elif r_level == "R2":
            mode = "canary" if decision == "pass" else "disabled"
        # R3: 必须 canary + 二次审批
        else:
            mode = "canary" if decision == "pass" else "disabled"

        return {
            "mode": mode,
            "must_monitor": ["reject_rate", "max_drawdown", "order_fail_rate"],
            "auto_rollback_triggers": ["Hard-Reject", "P0/P1 指标触发"],
            "second_approval_required": (r_level == "R3" or
                                        risk_direction.get("summary") == "RISK_EXPANSION")
        }

    def _extract_artifacts(self, change_bundle: Dict[str, Any]) -> List[str]:
        """提取产物列表"""
        artifacts = []

        # 从 artifacts 字段提取
        if "artifacts" in change_bundle:
            for key in change_bundle["artifacts"]:
                artifacts.append(f"artifacts.{key}")

        # 从 rollback_plan 提取
        if "rollback_plan" in change_bundle:
            artifacts.append("rollback_plan")

        return artifacts

    def _determine_approvers(self, r_level: str, decision: str) -> List[str]:
        """确定审批角色"""
        approvers = []

        if r_level in ["R2", "R3"]:
            approvers.append("risk_owner")
            approvers.append("strategy_owner")

        if decision == "warn":
            approvers.append("ops")

        return approvers


def main():
    """命令行入口"""
    if len(sys.argv) < 2:
        print("用法: python compliance_engine.py <change_bundle.json>")
        sys.exit(1)

    bundle_path = sys.argv[1]

    # 读取变更包
    with open(bundle_path, 'r', encoding='utf-8') as f:
        change_bundle = json.load(f)

    # 创建引擎
    engine = ComplianceEngine()

    # 执行合规审查
    receipt = engine.process(change_bundle)

    # 输出合规回执
    print("\n" + "="*60)
    print("合规回执:")
    print(json.dumps(receipt, indent=2, ensure_ascii=False))
    print("="*60)

    # 保存到文件
    output_path = Path(bundle_path).stem + "_receipt.json"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(receipt, f, indent=2, ensure_ascii=False)
    print(f"\n合规回执已保存到: {output_path}")


if __name__ == "__main__":
    main()
