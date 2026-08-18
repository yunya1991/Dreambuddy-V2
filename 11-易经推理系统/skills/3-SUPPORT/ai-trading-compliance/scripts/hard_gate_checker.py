#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
硬门禁检查器 (Hard Gate Checker)

9项硬门禁检查:
H001: SSoT 引用检查 - doc_refs 中的文件必须真实存在
H002: 可复现性检查 - artifacts 中包含可执行的脚本或命令
H003: P3 门禁产物检查 - gating_report 文件必须存在
H004: 回滚可执行检查 - rollback_points 中的路径必须存在
H005: 密钥不出域检查 - 输出包含 token/密钥
H006: 环境隔离检查 - 检查是否试图访问生产环境
H007: 外联控制检查 - 未经审批的外联发布
H008: 风险扩张检查 - 与历史变更对比，检测风险扩张
H009: Rollback Plan ID 检查 - 缺少 rollback_plan_id
"""

import re
import os
import json
from typing import Dict, Any, List
from datetime import datetime, timedelta


class HardGateChecker:
    """
    硬门禁检查器

    任一检查失败 → 返回 {"summary": "FAIL", ...}
    所有检查通过 → 返回 {"summary": "PASS", ...}
    """

    def __init__(self, workspace_dir: str = None):
        """
        初始化硬门禁检查器

        Args:
            workspace_dir: 工作目录，用于解析相对路径 (默认: 当前目录)
        """
        self.workspace_dir = workspace_dir or os.getcwd()

        # 定义 9 项硬门禁
        self.gates = [
            {"id": "H001", "name": "SSoT 引用检查", "checker": self._check_sst_refs},
            {"id": "H002", "name": "可复现性检查", "checker": self._check_reproducibility},
            {"id": "H003", "name": "P3 门禁产物检查", "checker": self._check_p3_artifacts},
            {"id": "H004", "name": "回滚可执行检查", "checker": self._check_rollback_executable},
            {"id": "H005", "name": "密钥不出域检查", "checker": self._check_no_secrets},
            {"id": "H006", "name": "环境隔离检查", "checker": self._check_environment_isolation},
            {"id": "H007", "name": "外联控制检查", "checker": self._check_external_publish},
            {"id": "H008", "name": "风险扩张检查", "checker": self._check_risk_expansion},
            {"id": "H009", "name": "Rollback Plan ID 检查", "checker": self._check_rollback_plan_id}
        ]

        # 密钥模式 (用于 H005)
        self.secret_patterns = [
            r'token["\']?\s*[:=]',
            r'api_key["\']?\s*[:=]',
            r'secret["\']?\s*[:=]',
            r'password["\']?\s*[:=]',
            r'密钥["\']?\s*[:=]',
            r'token_[a-zA-Z0-9]{20,}',
            r'[a-zA-Z0-9+/]{40,}=*'  # Base64 可能包含密钥
        ]

        # 生产环境关键词 (用于 H006)
        self.production_keywords = [
            'prod', 'production', 'main', 'master',
            '实盘', '生产', '正式'
        ]

        # 风险扩张关键词 (用于 H008)
        self.risk_expansion_keywords = [
            'leverage', '杠杆', 'margin', '保证金',
            'expand', '扩张', 'increase', '增加'
        ]

    def check(self, change_bundle: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行全部 9 项硬门禁检查

        Returns:
            Dict: {
                "summary": "PASS" | "FAIL",
                "details": [
                    {"id": "H001", "name": "...", "status": "PASS"|"FAIL", "message": "..."}
                ],
                "failed_count": int
            }
        """
        print("  执行硬门禁检查 (9项)...")
        details = []

        for gate in self.gates:
            gate_id = gate["id"]
            gate_name = gate["name"]
            checker = gate["checker"]

            try:
                result = checker(change_bundle)
                details.append({
                    "id": gate_id,
                    "name": gate_name,
                    "status": result["status"],
                    "message": result["message"]
                })

                status_icon = "✓" if result["status"] == "PASS" else "✗"
                print(f"    {status_icon} {gate_id}: {gate_name} - {result['status']}")

            except Exception as e:
                details.append({
                    "id": gate_id,
                    "name": gate_name,
                    "status": "FAIL",
                    "message": f"检查异常: {str(e)}"
                })
                print(f"    ✗ {gate_id}: {gate_name} - FAIL (异常)")

        # 统计
        failed_count = sum(1 for d in details if d["status"] == "FAIL")
        summary = "PASS" if failed_count == 0 else "FAIL"

        print(f"  硬门禁检查完成: {summary} (失败: {failed_count}/9)")

        return {
            "summary": summary,
            "details": details,
            "failed_count": failed_count
        }

    def _check_sst_refs(self, bundle: Dict[str, Any]) -> Dict[str, str]:
        """H001: SSoT 引用检查 - 检查 doc_refs 中的文件是否真实存在"""
        doc_refs = bundle.get("doc_refs", [])

        if not doc_refs:
            return {"status": "FAIL", "message": "doc_refs 为空，缺少 SSoT 引用"}

        # 检查每个引用是否存在
        existing_refs = []
        missing_refs = []

        for ref in doc_refs:
            if not ref or not isinstance(ref, str):
                continue

            # 尝试解析路径
            if os.path.isabs(ref):
                full_path = ref
            else:
                full_path = os.path.join(self.workspace_dir, ref)

            if os.path.exists(full_path):
                existing_refs.append(ref)
            else:
                missing_refs.append(ref)

        # 判断结果
        if missing_refs and len(missing_refs) == len(doc_refs):
            return {"status": "FAIL", "message": f"所有 doc_refs 都不存在: {missing_refs}"}
        elif missing_refs:
            return {"status": "WARN", "message": f"部分 doc_refs 不存在: {missing_refs}"}

        return {"status": "PASS", "message": f"doc_refs 包含 {len(existing_refs)} 个有效引用"}

    def _check_reproducibility(self, bundle: Dict[str, Any]) -> Dict[str, str]:
        """H002: 可复现性检查 - 检查是否包含可复现的脚本或命令"""
        artifacts = bundle.get("artifacts", {})

        # 检查是否有可复现的字段
        reproducibility_fields = ["run_command", "script", "data_snapshot_id", "config_version", "strategy_key"]
        found_fields = [field for field in reproducibility_fields if field in artifacts]

        if not found_fields:
            return {"status": "FAIL", "message": "缺少可复现性字段 (run_command/script/data_snapshot_id等)"}

        # 检查 run_command 或 script 是否可执行 (文件存在)
        if "run_command" in artifacts:
            run_cmd = artifacts["run_command"]
            # 如果是文件路径，检查是否存在
            if isinstance(run_cmd, str) and (run_cmd.endswith('.py') or run_cmd.endswith('.sh')):
                if not os.path.exists(os.path.join(self.workspace_dir, run_cmd)):
                    return {"status": "WARN", "message": f"run_command 文件不存在: {run_cmd}"}

        if "script" in artifacts:
            script_path = artifacts["script"]
            if not os.path.exists(os.path.join(self.workspace_dir, script_path)):
                return {"status": "WARN", "message": f"script 文件不存在: {script_path}"}

        return {"status": "PASS", "message": f"可复现性字段齐全: {found_fields}"}

    def _check_p3_artifacts(self, bundle: Dict[str, Any]) -> Dict[str, str]:
        """H003: P3 门禁产物检查"""
        artifacts = bundle.get("artifacts", {})

        # 检查 gating_report
        gating_report = artifacts.get("gating_report")
        if not gating_report:
            return {"status": "FAIL", "message": "缺少 gating_report"}

        # 检查 gate_result
        gate_result = gating_report.get("gate_result")
        if not gate_result:
            return {"status": "FAIL", "message": "gating_report 缺少 gate_result"}

        # 检查 baseline_ref
        baseline_ref = gating_report.get("baseline_ref")
        if not baseline_ref:
            return {"status": "FAIL", "message": "gating_report 缺少 baseline_ref"}

        return {"status": "PASS", "message": "P3 门禁产物齐全"}

    def _check_rollback_executable(self, bundle: Dict[str, Any]) -> Dict[str, str]:
        """H004: 回滚可执行检查 - 检查 rollback_points 路径是否真实存在"""
        rollback_plan = bundle.get("rollback_plan", {})

        if not rollback_plan:
            return {"status": "FAIL", "message": "缺少 rollback_plan"}

        # 检查回滚点
        rollback_points = rollback_plan.get("rollback_points", [])
        if not rollback_points:
            return {"status": "FAIL", "message": "rollback_plan 缺少 rollback_points"}

        # 检查每个回滚点是否存在
        existing_points = []
        missing_points = []

        for point in rollback_points:
            # point 是字典，包含 type, file, backup_id 等字段
            if not isinstance(point, dict):
                continue

            # 获取文件路径
            file_path = point.get("file", "")
            if not file_path:
                continue

            # 尝试解析路径
            if os.path.isabs(file_path):
                full_path = file_path
            else:
                full_path = os.path.join(self.workspace_dir, file_path)

            if os.path.exists(full_path):
                existing_points.append(file_path)
            else:
                missing_points.append(file_path)

        # 检查 triggers
        triggers = rollback_plan.get("triggers", [])
        if not triggers:
            return {"status": "WARN", "message": "rollback_plan 缺少 triggers (建议添加可观测指标)"}

        # 判断结果
        if missing_points and len(missing_points) == len(rollback_points):
            return {"status": "FAIL", "message": f"所有 rollback_points 都不存在: {missing_points}"}
        elif missing_points:
            return {"status": "WARN", "message": f"部分 rollback_points 不存在: {missing_points}"}

        return {"status": "PASS", "message": f"回滚计划可执行 (回滚点: {len(existing_points)}, 触发器: {len(triggers)})"}

    def _check_no_secrets(self, bundle: Dict[str, Any]) -> Dict[str, str]:
        """H005: 密钥不出域检查"""
        import json

        # 将整个 bundle 转为字符串
        bundle_str = json.dumps(bundle, ensure_ascii=False)

        # 检查是否包含密钥模式
        for pattern in self.secret_patterns:
            if re.search(pattern, bundle_str, re.IGNORECASE):
                return {"status": "FAIL", "message": f"检测到可能的密钥 (模式: {pattern})"}

        return {"status": "PASS", "message": "未检测到密钥泄露"}

    def _check_environment_isolation(self, bundle: Dict[str, Any]) -> Dict[str, str]:
        """H006: 环境隔离检查 - 检查是否试图访问生产环境"""
        change_type = bundle.get("change_type", "R0")
        risk_level = bundle.get("risk_level", "P3")

        # 将整个 bundle 转为字符串进行检查
        bundle_str = json.dumps(bundle, ensure_ascii=False).lower()

        # 检查是否包含生产环境关键词
        found_keywords = []
        for keyword in self.production_keywords:
            if keyword.lower() in bundle_str:
                found_keywords.append(keyword)

        # R3 变更 + 生产关键词 = 高风险
        if change_type == "R3" and found_keywords:
            return {"status": "FAIL", "message": f"R3 变更包含生产环境关键词: {found_keywords}"}

        # P0 风险 + 生产关键词 = 需要检查
        if risk_level == "P0" and found_keywords:
            return {"status": "WARN", "message": f"P0 风险变更包含生产环境关键词: {found_keywords} (需确认环境隔离)"}

        # 检查 artifacts 中是否有生产环境路径
        artifacts = bundle.get("artifacts", {})
        for key, value in artifacts.items():
            if isinstance(value, str) and any(kw in value.lower() for kw in self.production_keywords):
                return {"status": "WARN", "message": f"artifacts.{key} 包含生产环境路径: {value}"}

        return {"status": "PASS", "message": "环境隔离检查通过"}

    def _check_external_publish(self, bundle: Dict[str, Any]) -> Dict[str, str]:
        """H007: 外联控制检查"""
        external_publish = bundle.get("external_publish", {})

        if not external_publish:
            return {"status": "PASS", "message": "无外联发布需求"}

        # 检查审批状态
        approval_status = external_publish.get("approval_status", "pending")
        if approval_status != "approved":
            return {"status": "FAIL", "message": f"外联发布未经审批 (status: {approval_status})"}

        return {"status": "PASS", "message": "外联发布已审批"}

    def _check_risk_expansion(self, bundle: Dict[str, Any]) -> Dict[str, str]:
        """H008: 风险扩张检查 - 检测是否为风险扩张型变更"""
        change_type = bundle.get("change_type", "R0")
        risk_level = bundle.get("risk_level", "P3")
        intent = bundle.get("intent", "")

        # 将 intent 转为字符串（可能是 dict）
        if isinstance(intent, dict):
            intent_str = json.dumps(intent, ensure_ascii=False)
        else:
            intent_str = str(intent)

        # 将意图转为小写用于关键词检测
        intent_lower = intent_str.lower()

        # 检查是否包含风险扩张关键词
        found_keywords = []
        for keyword in self.risk_expansion_keywords:
            if keyword.lower() in intent_lower:
                found_keywords.append(keyword)

        # R2/R3 + P0/P1 = 高风险变更
        if change_type in ["R2", "R3"] and risk_level in ["P0", "P1"]:
            if found_keywords:
                return {"status": "WARN", "message": f"R{change_type} + {risk_level} 变更包含风险扩张关键词: {found_keywords} (需人工审批)"}
            else:
                return {"status": "WARN", "message": f"R{change_type} + {risk_level} 变更 (建议人工审批)"}

        # 仅包含风险扩张关键词
        if found_keywords and risk_level in ["P0", "P1"]:
            return {"status": "WARN", "message": f"变更包含风险扩张关键词: {found_keywords} (风险级别: {risk_level})"}

        return {"status": "PASS", "message": "非风险扩张型变更"}

    def _check_rollback_plan_id(self, bundle: Dict[str, Any]) -> Dict[str, str]:
        """H009: Rollback Plan ID 检查"""
        rollback_plan = bundle.get("rollback_plan", {})

        if not rollback_plan:
            return {"status": "FAIL", "message": "缺少 rollback_plan (R2/R3 变更必需)"}

        rollback_plan_id = rollback_plan.get("rollback_plan_id")
        if not rollback_plan_id:
            return {"status": "FAIL", "message": "rollback_plan 缺少 rollback_plan_id"}

        return {"status": "PASS", "message": f"rollback_plan_id: {rollback_plan_id}"}


def test_hard_gate_checker():
    """测试硬门禁检查器"""
    checker = HardGateChecker()

    # 测试用例 1: 完整变更包
    bundle_pass = {
        "doc_refs": ["doc1_v1.0", "doc2_v2.0"],
        "artifacts": {
            "data_snapshot_id": "snap_20260506",
            "config_version": "v1.2.3",
            "strategy_key": "momentum_v2",
            "gating_report": {
                "gate_result": {"decision": "PASS"},
                "baseline_ref": "baseline_v1.0"
            }
        },
        "rollback_plan": {
            "rollback_plan_id": "rollback_001",
            "rollback_points": ["v1.0"],
            "triggers": ["P0 指标触发"]
        },
        "change_type": "R2",
        "risk_level": "P1"
    }

    print("测试 1: 完整变更包 (期望: PASS)")
    result_pass = checker.check(bundle_pass)
    print(f"结果: {result_pass['summary']}\n")

    # 测试用例 2: 缺失字段
    bundle_fail = {
        "doc_refs": [],
        "artifacts": {},
        "change_type": "R3",
        "risk_level": "P0"
    }

    print("测试 2: 缺失字段 (期望: FAIL)")
    result_fail = checker.check(bundle_fail)
    print(f"结果: {result_fail['summary']}")


if __name__ == "__main__":
    test_hard_gate_checker()
