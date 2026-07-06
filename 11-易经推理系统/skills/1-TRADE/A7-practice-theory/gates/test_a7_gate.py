#!/usr/bin/env python3
"""
测试A7实践论门禁检查 - 使用完整数据
"""

import json
import sys
import os

# 导入A7门禁检查模块
sys.path.append(os.path.dirname(__file__))
from a7_practice_gate import A7PracticeGate

def load_test_data():
    """加载完整测试数据"""
    test_data_file = "../test_cases/complete_test_data.json"
    with open(test_data_file, 'r', encoding='utf-8') as f:
        return json.load(f)

def test_a4_gate_complete():
    """测试A4门禁检查 - 使用完整数据"""
    print("=" * 60)
    print("测试 A4 门禁检查 - 完整数据")
    print("=" * 60)
    
    # 加载测试数据
    test_data = load_test_data()
    test_case = test_data["test_case_001"]
    
    # 创建A7门禁检查器
    gate = A7PracticeGate()
    
    # 执行A4门禁检查
    result = gate.check_a4_gate(
        a1_report=test_case["a1_report"],
        a2_analysis=test_case["a2_analysis"],
        a3_strategy=test_case["a3_strategy"],
        practice_log=test_case["practice_log"]
    )
    
    # 打印结果
    print(f"门禁类型: {result['gate_type']}")
    print(f"时间戳: {result['timestamp']}")
    print()
    
    print("检查结果:")
    for check_name, check_result in result['checks'].items():
        status = "✓ 通过" if check_result['pass'] else "✗ 失败"
        print(f"  {status} {check_name}")
        print(f"    详情: {check_result['details']['message']}")
    print()
    
    print(f"总结:")
    print(f"  通过项: {result['summary']['passed']}/{result['summary']['total']}")
    print(f"  通过率: {result['summary']['pass_rate']}")
    print(f"  门禁结果: {result['summary']['gate_result']}")
    print(f"  建议: {result['recommendation']}")
    print()
    
    return result

def test_a5_gate_complete():
    """测试A5门禁检查 - 使用完整数据"""
    print("=" * 60)
    print("测试 A5 门禁检查 - 完整数据")
    print("=" * 60)
    
    # 加载测试数据
    test_data = load_test_data()
    test_case = test_data["test_case_002"]
    
    # 创建A7门禁检查器
    gate = A7PracticeGate()
    
    # 执行A5门禁检查
    result = gate.check_a5_gate(
        a4_scout_report=test_case["a4_scout_report"],
        a3_strategy=test_case["a3_strategy"],
        execution_plan=test_case["execution_plan"],
        practice_log=test_case["practice_log"]
    )
    
    # 打印结果
    print(f"门禁类型: {result['gate_type']}")
    print(f"时间戳: {result['timestamp']}")
    print()
    
    print("检查结果:")
    for check_name, check_result in result['checks'].items():
        status = "✓ 通过" if check_result['pass'] else "✗ 失败"
        print(f"  {status} {check_name}")
        print(f"    详情: {check_result['details']['message']}")
    print()
    
    print(f"总结:")
    print(f"  通过项: {result['summary']['passed']}/{result['summary']['total']}")
    print(f"  通过率: {result['summary']['pass_rate']}")
    print(f"  门禁结果: {result['summary']['gate_result']}")
    print(f"  建议: {result['recommendation']}")
    print()
    
    return result

def test_a4_gate_fail():
    """测试A4门禁检查 - 不完整数据(应该失败)"""
    print("=" * 60)
    print("测试 A4 门禁检查 - 不完整数据(应该失败)")
    print("=" * 60)
    
    # 创建不完整的测试数据
    incomplete_data = {
        "a1_report": {"exists": True},
        "a2_analysis": None,  # 缺失
        "a3_strategy": {"exists": True},
        "practice_log": None  # 缺失
    }
    
    # 创建A7门禁检查器
    gate = A7PracticeGate()
    
    # 执行A4门禁检查
    result = gate.check_a4_gate(
        a1_report=incomplete_data["a1_report"],
        a2_analysis=incomplete_data["a2_analysis"],
        a3_strategy=incomplete_data["a3_strategy"],
        practice_log=incomplete_data["practice_log"]
    )
    
    # 打印结果
    print(f"门禁类型: {result['gate_type']}")
    print(f"时间戳: {result['timestamp']}")
    print()
    
    print("检查结果:")
    for check_name, check_result in result['checks'].items():
        status = "✓ 通过" if check_result['pass'] else "✗ 失败"
        print(f"  {status} {check_name}")
        print(f"    详情: {check_result['details']['message']}")
    print()
    
    print(f"总结:")
    print(f"  通过项: {result['summary']['passed']}/{result['summary']['total']}")
    print(f"  通过率: {result['summary']['pass_rate']}")
    print(f"  门禁结果: {result['summary']['gate_result']}")
    print(f"  建议: {result['recommendation']}")
    print()
    
    return result

def test_a5_gate_fail():
    """测试A5门禁检查 - 不完整数据(应该失败)"""
    print("=" * 60)
    print("测试 A5 门禁检查 - 不完整数据(应该失败)")
    print("=" * 60)
    
    # 创建不完整的测试数据
    incomplete_data = {
        "a4_scout_report": {"exists": True, "verification_samples": 2},  # 样本不足
        "a3_strategy": {"exists": True},
        "execution_plan": {"stop_loss": 78000.0},  # 缺少position_discipline
        "practice_log": None  # 缺失
    }
    
    # 创建A7门禁检查器
    gate = A7PracticeGate()
    
    # 执行A5门禁检查
    result = gate.check_a5_gate(
        a4_scout_report=incomplete_data["a4_scout_report"],
        a3_strategy=incomplete_data["a3_strategy"],
        execution_plan=incomplete_data["execution_plan"],
        practice_log=incomplete_data["practice_log"]
    )
    
    # 打印结果
    print(f"门禁类型: {result['gate_type']}")
    print(f"时间戳: {result['timestamp']}")
    print()
    
    print("检查结果:")
    for check_name, check_result in result['checks'].items():
        status = "✓ 通过" if check_result['pass'] else "✗ 失败"
        print(f"  {status} {check_name}")
        print(f"    详情: {check_result['details']['message']}")
    print()
    
    print(f"总结:")
    print(f"  通过项: {result['summary']['passed']}/{result['summary']['total']}")
    print(f"  通过率: {result['summary']['pass_rate']}")
    print(f"  门禁结果: {result['summary']['gate_result']}")
    print(f"  建议: {result['recommendation']}")
    print()
    
    return result

def main():
    """主测试函数"""
    print("开始 A7 实践论门禁检查测试...")
    print()
    
    # 测试1: A4门禁检查 - 完整数据
    result_a4_complete = test_a4_gate_complete()
    
    # 测试2: A5门禁检查 - 完整数据
    result_a5_complete = test_a5_gate_complete()
    
    # 测试3: A4门禁检查 - 不完整数据(应该失败)
    result_a4_fail = test_a4_gate_fail()
    
    # 测试4: A5门禁检查 - 不完整数据(应该失败)
    result_a5_fail = test_a5_gate_fail()
    
    # 总结
    print("=" * 60)
    print("测试总结")
    print("=" * 60)
    
    tests = [
        ("A4门禁检查(完整数据)", result_a4_complete['summary']['gate_result']),
        ("A5门禁检查(完整数据)", result_a5_complete['summary']['gate_result']),
        ("A4门禁检查(不完整数据)", result_a4_fail['summary']['gate_result']),
        ("A5门禁检查(不完整数据)", result_a5_fail['summary']['gate_result'])
    ]
    
    for test_name, result in tests:
        expected_pass = (test_name.endswith("(完整数据)") and result == "PASS") or 
                       (test_name.endswith("(不完整数据)") and result == "FAIL")
        status = "✓ 符合预期" if expected_pass else "✗ 不符合预期"
        print(f"{status} {test_name}: {result}")
    
    print()
    print("预期结果:")
    print("  - 完整数据测试: 应该 PASS")
    print("  - 不完整数据测试: 应该 FAIL")
    print()
    
    # 检查是否全部符合预期
    all_expected = all(
        (test_name.endswith("(完整数据)") and result == "PASS") or 
        (test_name.endswith("(不完整数据)") and result == "FAIL")
        for test_name, result in tests
    )
    
    if all_expected:
        print("✅ 全部测试通过！A7门禁检查工作正常")
    else:
        print("❌ 部分测试失败！需要检查A7门禁检查逻辑")
    
    return all_expected

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)