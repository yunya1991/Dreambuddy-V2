#!/usr/bin/env python3
"""
ai-trading-compliance v2.0 MVP 测试脚本 (最小可用版本)
只测试核心功能，确保基本流程可用
"""

import sys
import os
import json
from pathlib import Path
from datetime import datetime

# 添加脚本目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from compliance_engine import ComplianceEngine
from r_level_classifier import RLevelClassifier
from hard_gate_checker import HardGateChecker
from audit_trail import AuditTrailManager


class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'
    BOLD = '\033[1m'


def print_header(title: str):
    """打印测试标题"""
    print(f"\n{Colors.BLUE}{Colors.BOLD}{'='*60}{Colors.RESET}")
    print(f"{Colors.BLUE}{Colors.BOLD}  {title}{Colors.RESET}")
    print(f"{Colors.BLUE}{Colors.BOLD}{'='*60}{Colors.RESET}\n")


def print_test(name: str, passed: bool, detail: str = ""):
    """打印测试结果"""
    status = f"{Colors.GREEN}✓ PASS{Colors.RESET}" if passed else f"{Colors.RED}✗ FAIL{Colors.RESET}"
    print(f"  {status} {name}")
    if detail:
        print(f"         {Colors.YELLOW}→ {detail}{Colors.RESET}")


def test_hard_gate_checker():
    """测试硬门禁检查器 - 基础功能"""
    print_header("测试1: 硬门禁检查器 (HardGateChecker)")
    
    checker = HardGateChecker()
    passed_count = 0
    
    # 测试1: 检查器能正常运行 (空bundle - 应该返回 FAIL)
    print(f"\n  {Colors.BOLD}场景1: 空bundle检测{Colors.RESET}")
    bundle_empty = {"change_id": "TEST-001"}
    result = checker.check(bundle_empty)
    passed1 = "summary" in result and "details" in result
    print_test("检查器正常运行", passed1, f"Keys: {list(result.keys())}")
    if passed1:
        passed_count += 1
    
    # 测试2: H001检测 (SSoT引用缺失)
    print(f"\n  {Colors.BOLD}场景2: H001 - SSoT引用缺失{Colors.RESET}")
    bundle_h001 = {"doc_refs": [], "change_id": "TEST-002"}
    result = checker.check(bundle_h001)
    passed2 = result["summary"] == "FAIL" and any(h["id"] == "H001" and h["status"] == "FAIL" for h in result["details"])
    print_test("H001 检测引用缺失", passed2)
    if passed2:
        passed_count += 1
    
    # 测试3: H005检测 (密钥泄露)
    print(f"\n  {Colors.BOLD}场景3: H005 - 密钥泄露{Colors.RESET}")
    bundle_h005 = {
        "output": {"config": {"api_key": "secret-123"}},
        "change_id": "TEST-003"
    }
    result = checker.check(bundle_h005)
    passed3 = result["summary"] == "FAIL" and any(h["id"] == "H005" and h["status"] == "FAIL" for h in result["details"])
    print_test("H005 检测密钥泄露", passed3)
    if passed3:
        passed_count += 1
    
    print(f"\n  {Colors.BOLD}结果: {passed_count}/3 通过{Colors.RESET}")
    return passed_count == 3


def test_r_level_classifier():
    """测试R0-R3分级器"""
    print_header("测试2: R0-R3 分级器 (RLevelClassifier)")
    
    classifier = RLevelClassifier()
    passed_count = 0
    
    # 测试1: 返回有效级别
    print(f"\n  {Colors.BOLD}场景1: 返回有效级别{Colors.RESET}")
    bundle = {"change_type": "R1"}
    result = classifier.classify(bundle)
    passed1 = result in ["R0", "R1", "R2", "R3"]
    print_test("返回有效级别 (R0-R3)", passed1, f"Got: {result}")
    if passed1:
        passed_count += 1
    
    # 测试2: 手动分级 R3
    print(f"\n  {Colors.BOLD}场景2: 手动分级 R3{Colors.RESET}")
    bundle_r3 = {"change_type": "R3"}
    result = classifier.classify(bundle_r3)
    passed2 = result == "R3"
    print_test("手动分级 R3", passed2, f"Got: {result}")
    if passed2:
        passed_count += 1
    
    # 测试3: 无change_type (使用自动分级)
    print(f"\n  {Colors.BOLD}场景3: 自动分级 (无change_type){Colors.RESET}")
    bundle_auto = {"intent": {"what": "read_only report"}}
    result = classifier.classify(bundle_auto)
    passed3 = result in ["R0", "R1", "R2", "R3"]
    print_test("自动分级返回有效级别", passed3, f"Got: {result}")
    if passed3:
        passed_count += 1
    
    print(f"\n  {Colors.BOLD}结果: {passed_count}/3 通过{Colors.RESET}")
    return passed_count == 3


def test_compliance_engine():
    """测试合规引擎"""
    print_header("测试3: 合规引擎 (ComplianceEngine)")
    
    # 创建审计目录
    audit_dir = "/tmp/test_compliance_audit"
    os.makedirs(audit_dir, exist_ok=True)
    
    engine = ComplianceEngine(audit_dir=audit_dir)
    passed_count = 0
    
    # 测试1: 处理完整变更包 (应该 pass 或 warn)
    print(f"\n  {Colors.BOLD}场景1: 完整变更包{Colors.RESET}")
    
    bundle_valid = {
        "change_id": "TEST-ENGINE-001",
        "change_type": "R1",
        "doc_refs": [],  # 故意简化，让硬门禁失败
        "output": {"config": {"enabled": True}},
        "execution": {"sandbox": True}
    }
    
    receipt = engine.process(bundle_valid)
    passed1 = "decision" in receipt
    print_test("生成合规回执", passed1, f"Decision: {receipt.get('decision', 'N/A')}")
    if passed1:
        passed_count += 1
        # 保存 receipt 供后续测试使用
        with open("/tmp/test_receipt.json", "w") as f:
            json.dump(receipt, f)
    
    # 测试2: 回执包含必要字段
    print(f"\n  {Colors.BOLD}场景2: 回执结构检查{Colors.RESET}")
    if os.path.exists("/tmp/test_receipt.json"):
        with open("/tmp/test_receipt.json", "r") as f:
            receipt = json.load(f)
        
        required_fields = ["decision"]  # 最小必要字段
        missing = [f for f in required_fields if f not in receipt]
        passed2 = len(missing) == 0
        print_test("回执包含必要字段", passed2, f"Missing: {missing}" if missing else "OK")
        if passed2:
            passed_count += 1
    else:
        print_test("回执文件不存在", False)
    
    print(f"\n  {Colors.BOLD}结果: {passed_count}/2 通过{Colors.RESET}")
    return passed_count == 2


def test_audit_trail():
    """测试审计轨迹管理器"""
    print_header("测试4: 审计轨迹 (AuditTrailManager)")
    
    audit_dir = "/tmp/test_compliance_audit"
    manager = AuditTrailManager(audit_dir=audit_dir)
    passed_count = 0
    
    # 测试1: 记录事件
    print(f"\n  {Colors.BOLD}场景1: 记录审计事件{Colors.RESET}")
    event = {
        "change_id": "TEST-AUDIT-001",
        "receipt_id": "RCPT-TEST-001",
        "r_level": "R1",
        "decision": "pass",
        "hard_gates": [],
        "warnings": [],
        "approvals": [],
        "triggered_by": "test"
    }
    
    try:
        manager.record(event)
        passed1 = True
        print_test("记录事件成功", passed1)
    except Exception as e:
        passed1 = False
        print_test("记录事件失败", passed1, str(e))
    if passed1:
        passed_count += 1
    
    # 测试2: 查询事件
    print(f"\n  {Colors.BOLD}场景2: 查询审计事件{Colors.RESET}")
    try:
        # 查询所有事件 (不指定 trace_id)
        events = manager.query()
        passed2 = isinstance(events, list)
        print_test("查询事件成功", passed2, f"Found {len(events)} events")
    except Exception as e:
        passed2 = False
        print_test("查询事件失败", passed2, str(e))
    if passed2:
        passed_count += 1
    
    print(f"\n  {Colors.BOLD}结果: {passed_count}/2 通过{Colors.RESET}")
    return passed_count == 2


def main():
    """主测试流程"""
    print(f"\n{Colors.BOLD}{Colors.BLUE}")
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║     ai-trading-compliance v2.0 MVP 测试 (最小可用版)       ║")
    print("║     测试: 硬门禁、R分级、合规引擎、审计轨迹             ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print(f"{Colors.RESET}\n")
    
    results = []
    
    # 运行所有测试
    results.append(("硬门禁检查器", test_hard_gate_checker()))
    results.append(("R0-R3 分级器", test_r_level_classifier()))
    results.append(("合规引擎", test_compliance_engine()))
    results.append(("审计轨迹", test_audit_trail()))
    
    # 打印总结
    print(f"\n{Colors.BOLD}{'='*60}{Colors.RESET}")
    print(f"{Colors.BOLD}  测试总结{Colors.RESET}")
    print(f"{Colors.BOLD}{'='*60}{Colors.RESET}\n")
    
    passed_total = 0
    total_tests = len(results)
    
    for name, passed in results:
        status = f"{Colors.GREEN}✓ PASS{Colors.RESET}" if passed else f"{Colors.RED}✗ FAIL{Colors.RESET}"
        print(f"  {status}  {name}")
        if passed:
            passed_total += 1
    
    print(f"\n  {Colors.BOLD}总计: {passed_total}/{total_tests} 个测试套件通过{Colors.RESET}\n")
    
    if passed_total == total_tests:
        print(f"{Colors.GREEN}{Colors.BOLD}  🎉 所有测试通过！ai-trading-compliance v2.0 基础功能正常{Colors.RESET}\n")
        return 0
    else:
        print(f"{Colors.RED}{Colors.BOLD}  ⚠️  部分测试失败，请检查上述问题{Colors.RESET}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
