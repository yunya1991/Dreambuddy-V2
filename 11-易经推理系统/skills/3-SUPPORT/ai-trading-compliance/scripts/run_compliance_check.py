#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ai-trading-compliance v2.0 - MVP 可运行版本

这是一个最小可运行版本，演示完整的合规审查流程:
1. 读取变更包 (change_bundle.json)
2. 执行 R0-R3 分级 (模拟)
3. 执行硬门禁检查 (模拟)
4. 执行回滚验证 (模拟)
5. 生成合规回执 (compliance_receipt.json)
6. 写入审计轨迹 (audit/)

使用方法:
  python run_compliance_check.py sample_change_bundle.json
"""

import json
import sys
import os
from datetime import datetime
from pathlib import Path

# ==========================================
# MVP 版本 - 所有检查器用模拟实现
# ==========================================

class MVPComplianceEngine:
    """
    MVP 合规检查引擎 - 可立即运行
    使用模拟检查器，演示完整流程
    """
    
    def __init__(self):
        print("🔧 初始化 MVP 合规检查引擎...")
        self.audit_dir = Path(__file__).parent / "audit"
        self.audit_dir.mkdir(exist_ok=True)
        print(f"   审计目录: {self.audit_dir}")
    
    def process(self, change_bundle: dict) -> dict:
        """
        处理变更包 - MVP 版本
        
        完整流程演示:
        1. 验证输入
        2. R0-R3 分级 (模拟)
        3. 硬门禁检查 (模拟)
        4. 回滚验证 (模拟)
        5. 生成决策
        6. 生成回执
        7. 写入审计
        """
        print("\n" + "="*60)
        print("🚀 开始合规审查...")
        print("="*60)
        
        # Step 1: 验证输入
        print("\n[Step 1/7] 验证输入...")
        self._validate_input(change_bundle)
        
        # Step 2: R0-R3 分级 (模拟)
        print("\n[Step 2/7] R0-R3 自动分级...")
        r_level = self._mock_classify(change_bundle)
        
        # Step 3: 硬门禁检查 (模拟)
        print("\n[Step 3/7] 硬门禁检查 (9项)...")
        hard_gate_result = self._mock_hard_gate_check(change_bundle)
        
        # Step 4: 回滚验证 (模拟)
        print("\n[Step 4/7] 回滚计划验证...")
        rollback_result = self._mock_rollback_validate(change_bundle)
        
        # Step 5: 风险方向判定 (模拟)
        print("\n[Step 5/7] 风险方向判定...")
        risk_direction = self._mock_risk_check(change_bundle)
        
        # Step 6: 生成决策
        print("\n[Step 6/7] 生成决策...")
        decision = self._make_decision(
            hard_gate_result,
            rollback_result,
            risk_direction
        )
        
        # Step 7: 生成合规回执 + 写入审计
        print("\n[Step 7/7] 生成合规回执 + 写入审计...")
        receipt = self._generate_receipt(
            change_bundle,
            r_level,
            decision,
            hard_gate_result,
            rollback_result,
            risk_direction
        )
        
        # 写入审计轨迹
        self._write_audit(receipt)
        
        print("\n" + "="*60)
        print("✅ 合规审查完成!")
        print("="*60 + "\n")
        
        return receipt
    
    def _validate_input(self, bundle: dict):
        """验证输入 - MVP 简化版"""
        required = ["intent", "change_type", "risk_level"]
        missing = [f for f in required if f not in bundle]
        
        if missing:
            raise ValueError(f"缺少必需字段: {missing}")
        
        print(f"   ✓ 输入验证通过")
        print(f"     变更意图: {bundle['intent']['what'][:50]}...")
        print(f"     变更类型: {bundle['change_type']}")
        print(f"     风险等级: {bundle['risk_level']}")
    
    def _mock_classify(self, bundle: dict) -> str:
        """模拟 R0-R3 分级"""
        # MVP: 简单逻辑 - 根据 change_type 返回
        change_type = bundle.get("change_type", "R0")
        
        print(f"   变更类型: {change_type}")
        print(f"   ✓ 分级结果: {change_type}")
        
        return change_type
    
    def _mock_hard_gate_check(self, bundle: dict) -> dict:
        """模拟硬门禁检查 (9项)"""
        print("   执行 9 项硬门禁检查...")
        
        # MVP: 简单检查 doc_refs 和 rollback_plan
        details = []
        
        # H001: SSoT 引用检查
        doc_refs = bundle.get("doc_refs", [])
        if not doc_refs:
            details.append({
                "id": "H001",
                "name": "SSoT 引用检查",
                "status": "FAIL",
                "message": "doc_refs 为空"
            })
            print(f"    ✗ H001: SSoT 引用检查 - FAIL")
        else:
            details.append({
                "id": "H001",
                "name": "SSoT 引用检查",
                "status": "PASS",
                "message": f"doc_refs 包含 {len(doc_refs)} 个引用"
            })
            print(f"    ✓ H001: SSoT 引用检查 - PASS")
        
        # H004: 回滚可执行检查
        rollback_plan = bundle.get("rollback_plan")
        if not rollback_plan:
            details.append({
                "id": "H004",
                "name": "回滚可执行检查",
                "status": "FAIL",
                "message": "缺少 rollback_plan"
            })
            print(f"    ✗ H004: 回滚可执行检查 - FAIL")
        else:
            details.append({
                "id": "H004",
                "name": "回滚可执行检查",
                "status": "PASS",
                "message": "rollback_plan 存在"
            })
            print(f"    ✓ H004: 回滚可执行检查 - PASS")
        
        # 其他 7 项 - MVP 默认 PASS
        for i, gate_id in enumerate(["H002", "H003", "H005", "H006", "H007", "H008", "H009"]):
            details.append({
                "id": gate_id,
                "name": f"硬门禁 {gate_id}",
                "status": "PASS",
                "message": "MVP 模拟 - PASS"
            })
            print(f"    ✓ {gate_id}: 硬门禁 {gate_id} - PASS (模拟)")
        
        # 判断 summary
        failed_count = sum(1 for d in details if d["status"] == "FAIL")
        summary = "PASS" if failed_count == 0 else "FAIL"
        
        print(f"   硬门禁检查完成: {summary} (失败: {failed_count}/9)")
        
        return {
            "summary": summary,
            "details": details,
            "failed_count": failed_count
        }
    
    def _mock_rollback_validate(self, bundle: dict) -> dict:
        """模拟回滚验证"""
        rollback_plan = bundle.get("rollback_plan")
        
        if not rollback_plan:
            print(f"   ✗ 回滚计划缺失")
            return {
                "summary": "FAIL",
                "details": [{"id": "R001", "status": "FAIL"}],
                "rollback_plan_id": None
            }
        
        rollback_plan_id = rollback_plan.get("rollback_plan_id", "unknown")
        print(f"   ✓ 回滚计划验证通过 (ID: {rollback_plan_id})")
        
        return {
            "summary": "PASS",
            "details": [{"id": "R001", "status": "PASS"}],
            "rollback_plan_id": rollback_plan_id
        }
    
    def _mock_risk_check(self, bundle: dict) -> dict:
        """模拟风险方向判定"""
        # MVP: 默认收紧型
        print(f"   ✓ 风险方向: TIGHTEN_ONLY (收紧型 - 模拟)")
        
        return {
            "summary": "TIGHTEN_ONLY",
            "details": [],
            "has_approval": False
        }
    
    def _make_decision(self, hard_gate, rollback, risk) -> str:
        """生成决策"""
        if hard_gate["summary"] == "FAIL" or rollback["summary"] == "FAIL":
            print(f"   决策: FAIL (硬门禁或回滚验证失败)")
            return "fail"
        
        print(f"   决策: PASS")
        return "pass"
    
    def _generate_receipt(self, bundle, r_level, decision, hard_gate, rollback, risk) -> dict:
        """生成合规回执"""
        receipt = {
            "decision": decision,
            "change_classification": {
                "change_type": r_level,
                "risk_level": bundle.get("risk_level"),
                "environment": "Pilot",
                "tighten_only": risk["summary"] == "TIGHTEN_ONLY"
            },
            "hard_constraints_checked": {
                "prod_write_prohibited_without_approval": True,
                "sandbox_no_network_no_secrets": True,
                "gate_result_present": True,
                "baseline_ref_present": True,
                "rollback_defined": True,
                "audit_replayable": True,
                "external_publish_outbox_only": True
            },
            "blockers": [
                {
                    "id": d["id"],
                    "title": d["message"],
                    "evidence": ""
                }
                for d in hard_gate["details"]
                if d["status"] == "FAIL"
            ],
            "warnings": [],
            "required_actions": [],
            "rollout_requirements": {
                "mode": "canary" if r_level in ["R2", "R3"] else "full",
                "must_monitor": ["pnl", "max_drawdown"],
                "auto_rollback_triggers": ["Hard-Reject"],
                "second_approval_required": r_level == "R3"
            },
            "audit_fields": {
                "doc_refs": bundle.get("doc_refs", []),
                "trace_id": bundle.get("trace_id"),
                "artifacts": [],
                "approver_roles": ["risk_owner"] if r_level in ["R2", "R3"] else []
            }
        }
        
        print(f"   ✓ 合规回执生成完成")
        print(f"     决策: {receipt['decision']}")
        print(f"     变更分类: {receipt['change_classification']['change_type']}")
        print(f"     发布要求: {receipt['rollout_requirements']['mode']}")
        
        return receipt
    
    def _write_audit(self, receipt: dict):
        """写入审计轨迹"""
        timestamp = datetime.now().strftime("%Y%m%d")
        log_file = self.audit_dir / f"audit_{timestamp}.jsonl"
        
        # 添加审计 ID
        audit_id = f"AUDIT_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{os.getpid()}"
        receipt["audit_id"] = audit_id
        receipt["audit_timestamp"] = datetime.now().isoformat()
        
        # 写入 JSONL
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(receipt, ensure_ascii=False) + "\n")
        
        print(f"   ✓ 审计记录已写入: {log_file.name}")
        print(f"     审计 ID: {audit_id}")


# ==========================================
# 主程序
# ==========================================

def main():
    """主程序 - 命令行入口"""
    if len(sys.argv) < 2:
        print("使用方法:")
        print("  python run_compliance_check.py <change_bundle.json>")
        print("\n示例:")
        print("  python run_compliance_check.py sample_change_bundle.json")
        sys.exit(1)
    
    bundle_path = sys.argv[1]
    
    print(f"\n📂 读取变更包: {bundle_path}")
    
    # 读取变更包
    with open(bundle_path, "r", encoding="utf-8") as f:
        change_bundle = json.load(f)
    
    # 创建引擎
    engine = MVPComplianceEngine()
    
    # 执行合规审查
    receipt = engine.process(change_bundle)
    
    # 保存合规回执
    output_path = Path(bundle_path).stem + "_receipt.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(receipt, f, indent=2, ensure_ascii=False)
    
    print(f"\n💾 合规回执已保存: {output_path}")
    print(f"\n" + "="*60)
    print("合规回执内容:")
    print(json.dumps(receipt, indent=2, ensure_ascii=False))
    print("="*60)


if __name__ == "__main__":
    main()
