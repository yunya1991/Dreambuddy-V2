#!/usr/bin/env python3
"""
A8自我批评门禁检查
确保A8的输出质量符合要求
基于五本书的理论基础设计检查项
"""

import json
import os
import sys
from datetime import datetime

def load_a8_report(report_path):
    """加载A8自我批评报告"""
    try:
        with open(report_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"加载报告失败: {e}")
        return None

def check_critical_thinking_elements(report):
    """检查是否应用了Paul的8个思维元素"""
    issues = report.get('critical_thinking_issues', {})
    if not issues or 'issues_found' not in issues:
        return {
            'check_name': '批判性思维元素检查',
            'status': 'FAIL',
            'reason': '未找到批判性思维问题分析',
            'details': '报告必须包含critical_thinking_issues部分'
        }
    
    elements_covered = set()
    for issue in issues.get('issues_found', []):
        element = issue.get('element', '')
        if element:
            elements_covered.add(element)
    
    if len(elements_covered) < 3:
        return {
            'check_name': '批判性思维元素检查',
            'status': 'WARNING',
            'reason': f'仅覆盖{len(elements_covered)}个思维元素，建议覆盖更多',
            'details': f'已覆盖: {list(elements_covered)}'
        }
    
    return {
        'check_name': '批判性思维元素检查',
        'status': 'PASS',
        'reason': f'覆盖了{len(elements_covered)}个思维元素',
        'details': f'已覆盖: {list(elements_covered)}'
    }

def check_cognitive_biases(report):
    """检查是否应用了Kahneman的7大认知偏差识别"""
    biases = report.get('cognitive_biases', {})
    if not biases or 'biases_detected' not in biases:
        return {
            'check_name': '认知偏差识别检查',
            'status': 'FAIL',
            'reason': '未找到认知偏差识别',
            'details': '报告必须包含cognitive_biases部分'
        }
    
    bias_types = set()
    for bias in biases.get('biases_detected', []):
        bias_type = bias.get('type', '')
        if bias_type:
            bias_types.add(bias_type)
    
    if len(bias_types) < 2:
        return {
            'check_name': '认知偏差识别检查',
            'status': 'WARNING',
            'reason': f'仅识别{len(bias_types)}种认知偏差，建议识别更多',
            'details': f'已识别: {list(bias_types)}'
        }
    
    return {
        'check_name': '认知偏差识别检查',
        'status': 'PASS',
        'reason': f'识别了{len(bias_types)}种认知偏差',
        'details': f'已识别: {list(bias_types)}'
    }

def check_rationality_assessment(report):
    """检查是否应用了Stanovich的理性评估"""
    rationality = report.get('rationality_assessment', {})
    if not rationality:
        return {
            'check_name': '理性评估检查',
            'status': 'FAIL',
            'reason': '未找到理性评估',
            'details': '报告必须包含rationality_assessment部分'
        }
    
    if 'cognitive_rationality' not in rationality or 'instrumental_rationality' not in rationality:
        return {
            'check_name': '理性评估检查',
            'status': 'WARNING',
            'reason': '理性评估不完整，缺少认知理性或工具理性',
            'details': '应同时包含cognitive_rationality和instrumental_rationality'
        }
    
    for category in ['cognitive_rationality', 'instrumental_rationality']:
        for key, value in rationality.get(category, {}).items():
            if not isinstance(value, (int, float)) or value < 0 or value > 100:
                return {
                    'check_name': '理性评估检查',
                    'status': 'WARNING',
                    'reason': f'{category}.{key}的评分{value}超出合理范围(0-100)',
                    'details': '评分应在0-100之间'
                }
    
    return {
        'check_name': '理性评估检查',
        'status': 'PASS',
        'reason': '理性评估完整且合理',
        'details': f'整体理性评分: {rationality.get("overall_rationality_score", "N/A")}'
    }

def check_contradiction_analysis(report):
    """检查是否应用了毛泽东的矛盾分析方法"""
    contradictions = report.get('contradictions', {})
    if not contradictions or 'contradictions_identified' not in contradictions:
        return {
            'check_name': '矛盾分析检查',
            'status': 'FAIL',
            'reason': '未找到矛盾分析',
            'details': '报告必须包含contradictions部分'
        }
    
    contradictions_found = contradictions.get('contradictions_identified', [])
    if len(contradictions_found) < 1:
        return {
            'check_name': '矛盾分析检查',
            'status': 'WARNING',
            'reason': '未识别出任何矛盾',
            'details': 'A0-A7中必然存在矛盾，应主动识别'
        }
    
    main_contradictions = [c for c in contradictions_found if c.get('main_contradiction', False)]
    if not main_contradictions:
        return {
            'check_name': '矛盾分析检查',
            'status': 'WARNING',
            'reason': '未识别主要矛盾',
            'details': '应识别当前的主要矛盾'
        }
    
    return {
        'check_name': '矛盾分析检查',
        'status': 'PASS',
        'reason': f'识别了{len(contradictions_found)}个矛盾，其中{len(main_contradictions)}个主要矛盾',
        'details': f'主要矛盾: {[c.get("contradiction_id") for c in main_contradictions]}'
    }

def check_theory_practice_alignment(report):
    """检查是否应用了毛泽东的知行合一理论"""
    alignment = report.get('theory_practice_alignment', {})
    if not alignment:
        return {
            'check_name': '知行合一检查',
            'status': 'FAIL',
            'reason': '未找到知行合一评估',
            'details': '报告必须包含theory_practice_alignment部分'
        }
    
    if 'alignment_score' not in alignment:
        return {
            'check_name': '知行合一检查',
            'status': 'WARNING',
            'reason': '未提供知行合一评分',
            'details': '应提供alignment_score(0-100)'
        }
    
    alignment_score = alignment.get('alignment_score', 0)
    if alignment_score < 60:
        return {
            'check_name': '知行合一检查',
            'status': 'WARNING',
            'reason': f'知行合一评分较低: {alignment_score}',
            'details': '应加强理论-实践一致性的检查'
        }
    
    return {
        'check_name': '知行合一检查',
        'status': 'PASS',
        'reason': f'知行合一评分: {alignment_score}',
        'details': alignment.get('alignment_level', 'N/A')
    }

def check_improvement_suggestions(report):
    """检查改进建议是否具体、可操作"""
    suggestions = report.get('improvement_suggestions', [])
    if not suggestions:
        return {
            'check_name': '改进建议检查',
            'status': 'FAIL',
            'reason': '未提供改进建议',
            'details': '报告必须包含improvement_suggestions部分'
        }
    
    for suggestion in suggestions:
        if 'description' not in suggestion or 'rationale' not in suggestion:
            return {
                'check_name': '改进建议检查',
                'status': 'WARNING',
                'reason': '改进建议缺少描述或理论依据',
                'details': '每条建议应包含description和rationale'
            }
    
    return {
        'check_name': '改进建议检查',
        'status': 'PASS',
        'reason': f'提供了{len(suggestions)}条改进建议',
        'details': f'建议ID: {[s.get("suggestion_id") for s in suggestions]}'
    }

def check_theory_refinement_proposals(report):
    """检查理论完善提案是否完整"""
    proposals = report.get('theory_refinement_proposals', [])
    
    contradictions = report.get('contradictions', {})
    main_contradictions = [c for c in contradictions.get('contradictions_identified', []) if c.get('main_contradiction', False)]
    
    if main_contradictions and not proposals:
        return {
            'check_name': '理论完善提案检查',
            'status': 'WARNING',
            'reason': '识别了主要矛盾，但未提供理论完善提案',
            'details': '应有对应的theory_refinement_proposals'
        }
    
    if proposals:
        for proposal in proposals:
            if 'target_system' not in proposal or 'refinement' not in proposal:
                return {
                    'check_name': '理论完善提案检查',
                    'status': 'WARNING',
                    'reason': '理论完善提案缺少关键信息',
                    'details': '每条提案应包含target_system和refinement'
                }
    
    return {
        'check_name': '理论完善提案检查',
        'status': 'PASS',
        'reason': f'提供了{len(proposals)}条理论完善提案',
        'details': f'提案ID: {[p.get("proposal_id") for p in proposals]}'
    }

def run_all_checks(report_path):
    """运行所有门禁检查"""
    report = load_a8_report(report_path)
    if not report:
        return {
            'overall_status': 'ERROR',
            'message': '无法加载报告',
            'checks': []
        }
    
    checks = [
        check_critical_thinking_elements(report),
        check_cognitive_biases(report),
        check_rationality_assessment(report),
        check_contradiction_analysis(report),
        check_theory_practice_alignment(report),
        check_improvement_suggestions(report),
        check_theory_refinement_proposals(report)
    ]
    
    pass_count = sum(1 for c in checks if c['status'] == 'PASS')
    warning_count = sum(1 for c in checks if c['status'] == 'WARNING')
    fail_count = sum(1 for c in checks if c['status'] == 'FAIL')
    
    if fail_count > 0:
        overall_status = 'FAIL'
    elif warning_count > 0:
        overall_status = 'WARNING'
    else:
        overall_status = 'PASS'
    
    return {
        'overall_status': overall_status,
        'summary': f'通过: {pass_count}, 警告: {warning_count}, 失败: {fail_count}',
        'checks': checks,
        'report_id': report.get('report_id', 'Unknown'),
        'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }

def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("用法: python a8_self_criticism_gate.py <report_json_path>")
        print("  或: python a8_self_criticism_gate.py --report <report_json_path>")
        sys.exit(1)
    
    # 解析参数
    if sys.argv[1] == '--report' and len(sys.argv) >= 3:
        report_path = sys.argv[2]
    else:
        report_path = sys.argv[1]
    
    if not os.path.exists(report_path):
        print(f"文件不存在: {report_path}")
        sys.exit(1)
    
    result = run_all_checks(report_path)
    
    print("=" * 80)
    print("A8自我批评门禁检查结果")
    print("=" * 80)
    print(f"报告ID: {result.get('report_id')}")
    print(f"检查时间: {result.get('date')}")
    print(f"总体状态: {result.get('overall_status')}")
    print(f"摘要: {result.get('summary')}")
    print("-" * 80)
    
    for check in result.get('checks', []):
        status_symbol = "✓" if check['status'] == 'PASS' else ("⚠" if check['status'] == 'WARNING' else "✗")
        print(f"{status_symbol} {check['check_name']}: {check['status']}")
        print(f"  原因: {check['reason']}")
        print(f"  详情: {check['details']}")
        print()
    
    # 保存结果
    result_path = report_path.replace('.json', '_gate_result.json')
    with open(result_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    
    print(f"检查结果已保存到: {result_path}")
    
    # 返回适当的退出码
    if result['overall_status'] == 'FAIL':
        sys.exit(1)
    else:
        sys.exit(0)

if __name__ == "__main__":
    main()
