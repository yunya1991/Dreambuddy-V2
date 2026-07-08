#!/usr/bin/env python3
"""
简单测试A7实践论门禁检查
"""

import sys
import os

# 添加当前目录到路径
sys.path.append(os.path.dirname(__file__))

try:
    from a7_practice_gate import A7PracticeGate
    
    print("=" * 60)
    print("简单测试 A7 实践论门禁检查")
    print("=" * 60)
    print()
    
    # 创建A7门禁检查器
    gate = A7PracticeGate()
    
    # 测试A4门禁检查 - 完整数据
    print("测试1: A4门禁检查 - 完整数据")
    print("-" * 40)
    
    a1_report = {"exists": True, "freshness": "<4h"}
    a2_analysis = {"exists": True, "resistance_path": "清晰"}
    a3_strategy = {
        "exists": True, 
        "direction": "LONG",
        "truth_criteria": ["P&L>0", "win_rate>50%", "max_drawdown<10%"]
    }
    practice_log = [{"timestamp": "2026-04-26T10:00:00", "action": "开始A4验证"}]
    
    result_a4 = gate.check_a4_gate(a1_report, a2_analysis, a3_strategy, practice_log)
    
    print(f"门禁结果: {result_a4['summary']['gate_result']}")
    print(f"通过率: {result_a4['summary']['pass_rate']}")
    print(f"建议: {result_a4['recommendation']}")
    print()
    
    # 测试A5门禁检查 - 完整数据
    print("测试2: A5门禁检查 - 完整数据")
    print("-" * 40)
    
    a4_scout_report = {
        "exists": True, 
        "verification_samples": 5,
        "recognition_corrected": True
    }
    execution_plan = {
        "stop_loss": 78000.0,
        "position_discipline": "30%",
        "risk_level": "medium"
    }
    
    result_a5 = gate.check_a5_gate(a4_scout_report, a3_strategy, execution_plan, practice_log)
    
    print(f"门禁结果: {result_a5['summary']['gate_result']}")
    print(f"通过率: {result_a5['summary']['pass_rate']}")
    print(f"建议: {result_a5['recommendation']}")
    print()
    
    # 测试A4门禁检查 - 不完整数据(应该失败)
    print("测试3: A4门禁检查 - 不完整数据(应该失败)")
    print("-" * 40)
    
    a1_report_incomplete = {"exists": True}
    a2_analysis_incomplete = None  # 缺失
    a3_strategy_incomplete = {"exists": True}
    practice_log_incomplete = None  # 缺失
    
    result_a4_fail = gate.check_a4_gate(
        a1_report_incomplete, 
        a2_analysis_incomplete, 
        a3_strategy_incomplete, 
        practice_log_incomplete
    )
    
    print(f"门禁结果: {result_a4_fail['summary']['gate_result']}")
    print(f"通过率: {result_a4_fail['summary']['pass_rate']}")
    print(f"建议: {result_a4_fail['recommendation']}")
    print()
    
    # 测试A5门禁检查 - 不完整数据(应该失败)
    print("测试4: A5门禁检查 - 不完整数据(应该失败)")
    print("-" * 40)
    
    a4_scout_report_incomplete = {"exists": True, "verification_samples": 2}  # 样本不足
    execution_plan_incomplete = {"stop_loss": 78000.0}  # 缺少position_discipline
    practice_log_incomplete = None  # 缺失
    
    result_a5_fail = gate.check_a5_gate(
        a4_scout_report_incomplete, 
        a3_strategy_incomplete, 
        execution_plan_incomplete, 
        practice_log_incomplete
    )
    
    print(f"门禁结果: {result_a5_fail['summary']['gate_result']}")
    print(f"通过率: {result_a5_fail['summary']['pass_rate']}")
    print(f"建议: {result_a5_fail['recommendation']}")
    print()
    
    # 总结
    print("=" * 60)
    print("测试总结")
    print("=" * 60)
    print()
    
    tests = [
        ("A4门禁检查(完整数据)", result_a4['summary']['gate_result']),
        ("A5门禁检查(完整数据)", result_a5['summary']['gate_result']),
        ("A4门禁检查(不完整数据)", result_a4_fail['summary']['gate_result']),
        ("A5门禁检查(不完整数据)", result_a5_fail['summary']['gate_result'])
    ]
    
    all_expected = True
    for test_name, result in tests:
        if "(完整数据)" in test_name:
            expected = "PASS"
        else:
            expected = "FAIL"
        
        status = "✓ 符合预期" if result == expected else "✗ 不符合预期"
        if result != expected:
            all_expected = False
        print(f"{status} {test_name}: {result} (预期: {expected})")
    
    print()
    if all_expected:
        print("✅ 全部测试通过！A7门禁检查工作正常")
        sys.exit(0)
    else:
        print("❌ 部分测试失败！需要检查A7门禁检查逻辑")
        sys.exit(1)
        
except ImportError as e:
    print(f"❌ 导入错误: {e}")
    sys.exit(1)
except Exception as e:
    print(f"❌ 测试错误: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)