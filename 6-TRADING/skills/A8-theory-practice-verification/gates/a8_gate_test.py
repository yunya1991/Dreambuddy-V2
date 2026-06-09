#!/usr/bin/env python3
"""简化版A8门禁检查 - 用于测试"""
import json
import sys
import os

def main():
    print("=" * 80)
    print("A8门禁检查 - 测试版")
    print("=" * 80)
    
    if len(sys.argv) < 2:
        print("用法: python a8_gate_test.py <report_json_path>")
        sys.exit(1)
    
    report_path = sys.argv[1]
    print(f"正在检查报告: {report_path}")
    
    if not os.path.exists(report_path):
        print(f"错误: 文件不存在: {report_path}")
        sys.exit(1)
    
    try:
        with open(report_path, 'r', encoding='utf-8') as f:
            report = json.load(f)
        print("✓ 报告JSON格式正确")
    except Exception as e:
        print(f"✗ 报告JSON格式错误: {e}")
        sys.exit(1)
    
    # 基本检查
    checks = []
    
    # 检查1: 是否有critical_thinking_issues
    if 'critical_thinking_issues' in report:
        checks.append(("✓", "批判性思维检查", "PASS"))
    else:
        checks.append(("✗", "批判性思维检查", "FAIL"))
    
    # 检查2: 是否有cognitive_biases
    if 'cognitive_biases' in report:
        checks.append(("✓", "认知偏差检查", "PASS"))
    else:
        checks.append(("✗", "认知偏差检查", "FAIL"))
    
    # 检查3: 是否有rationality_assessment
    if 'rationality_assessment' in report:
        checks.append(("✓", "理性评估检查", "PASS"))
    else:
        checks.append(("✗", "理性评估检查", "FAIL"))
    
    # 检查4: 是否有contradictions
    if 'contradictions' in report:
        checks.append(("✓", "矛盾分析检查", "PASS"))
    else:
        checks.append(("✗", "矛盾分析检查", "FAIL"))
    
    # 输出结果
    print("\n检查结果:")
    print("-" * 80)
    for symbol, name, status in checks:
        print(f"{symbol} {name}: {status}")
    
    # 保存简单结果
    result = {
        'report_id': report.get('report_id', 'Unknown'),
        'checks': [{'name': n, 'status': s} for _, n, s in checks],
        'overall_status': 'PASS' if all(s == 'PASS' for _, _, s in checks) else 'WARNING'
    }
    
    result_path = report_path.replace('.json', '_test_result.json')
    with open(result_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    
    print(f"\n检查结果已保存到: {result_path}")
    print("=" * 80)
    
    if result['overall_status'] == 'PASS':
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()
