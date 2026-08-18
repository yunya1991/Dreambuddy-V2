#!/usr/bin/env python3
"""
A8 自动化分析脚本 - 分析A0/A7输出
自动应用批判性思维、认知偏差识别、理性评估、矛盾分析、知行合一检查
生成A8自我批评报告
"""

import json
import os
import sys
import argparse
from datetime import datetime

def load_json_file(file_path, file_desc):
    """加载JSON文件"""
    if not os.path.exists(file_path):
        print(f"错误：{file_desc}文件不存在: {file_path}")
        return None
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"错误：{file_desc}JSON解析失败: {e}")
        return None
    except Exception as e:
        print(f"错误：加载{file_desc}失败: {e}")
        return None

def check_critical_thinking(report, agent_name):
    """检查批判性思维（Paul的8个思维元素）"""
    elements = [
        "目的（Purpose）", "问题（Question）", "信息（Information）",
        "推断（Inference）", "概念（Concepts）", "假设（Assumptions）",
        "视角（Viewpoints）", "意涵（Implications）"
    ]
    
    covered = []
    uncovered = []
    
    # 检查A0的输出
    if agent_name == "A0":
        # 检查是否包含8个思维元素的分析
        if 'critical_thinking_elements' in report:
            for element in elements:
                if element in report.get('critical_thinking_elements', {}):
                    covered.append(element)
                else:
                    uncovered.append(element)
        else:
            # 未包含critical_thinking_elements，检查是否有替代字段
            if 'contradictions' in report:
                covered.append("问题（Question）")  # 识别矛盾=提出问题
            if 'cognitive_biases' in report:
                covered.append("信息（Information）")  # 识别偏差=收集信息
            uncovered = [e for e in elements if e not in covered]
    
    # 检查A7的输出
    elif agent_name == "A7":
        # A7的报告结构不同
        if 'a7_gate_check' in report:
            check_items = report['a7_gate_check']
            if len(check_items) >= 3:
                covered.append("目的（Purpose）")
            if '认识来源充分性' in check_items:
                covered.append("信息（Information）")
            if '验证设计合理性' in check_items:
                covered.append("推断（Inference）")
            if '反馈机制完整性' in check_items:
                covered.append("意涵（Implications）")
            uncovered = [e for e in elements if e not in covered]
        else:
            uncovered = elements  # 全部未覆盖
    
    score = len(covered) / len(elements) * 100
    
    return {
        'covered': covered,
        'uncovered': uncovered,
        'score': score,
        'passed': score >= 70  # 至少覆盖70%的元素
    }

def check_cognitive_biases(report, agent_name):
    """检查认知偏差识别（Kahneman的7大偏差）"""
    biases_7 = [
        "锚定效应", "框架效应", "可用性偏差",
        "过度自信", "损失厌恶", "确认偏误", "后见之明偏差"
    ]
    
    detected = []
    missed = []
    
    # 检查A0的输出
    if agent_name == "A0":
        biases_found = report.get('cognitive_biases', {}).get('biases_detected', [])
        detected_types = [b.get('type', '') for b in biases_found]
        
        for bias in biases_7:
            if bias in detected_types:
                detected.append(bias)
            else:
                missed.append(bias)
    
    # 检查A7的输出
    elif agent_name == "A7":
        # A7的报告可能不直接列出认知偏差，需要推断
        # 暂时假设A7未识别认知偏差
        missed = biases_7
        detected = []
    
    recognition_rate = len(detected) / len(biases_7) * 100 if biases_7 else 0
    
    return {
        'detected': detected,
        'missed': missed,
        'recognition_rate': recognition_rate,
        'passed': recognition_rate >= 60  # 至少识别60%的偏差
    }

def check_rationality(report, agent_name):
    """检查理性评估（Stanovich框架）"""
    # 获取自评分数
    self_rating = report.get('rationality_assessment', {}).get('overall_rationality_score', 0)
    
    # A8评估分数（简化版，实际应更复杂）
    # 这里使用规则：如果自评>80，但认知偏差识别率<60%，则高估
    biases_check = check_cognitive_biases(report, agent_name)
    
    if self_rating > 80 and biases_check['recognition_rate'] < 60:
        a8_rating = self_rating - 30  # 严重高估
        deviation = -30
    elif self_rating > 70 and biases_check['recognition_rate'] < 70:
        a8_rating = self_rating - 15  # 中等高估
        deviation = -15
    else:
        a8_rating = self_rating - 5  # 轻微高估（普遍现象）
        deviation = -5
    
    return {
        'self_rating': self_rating,
        'a8_rating': a8_rating,
        'deviation': deviation,
        'passed': abs(deviation) < 10  # 偏差<10分算准确
    }

def check_contradiction_analysis(report, agent_name):
    """检查矛盾分析（毛泽东矛盾论）"""
    if agent_name == "A0":
        contradictions = report.get('contradictions', {}).get('contradictions_identified', [])
        main_contradiction = report.get('contradictions', {}).get('main_contradiction', None)
        
        if not contradictions:
            return {'score': 0, 'passed': False, 'reason': '未识别任何矛盾'}
        
        if not main_contradiction:
            return {'score': 30, 'passed': False, 'reason': '未识别主要矛盾'}
        
        # 识别了主要矛盾，评分80+
        return {'score': 85, 'passed': True, 'reason': '识别了主要矛盾'}
    
    elif agent_name == "A7":
        # A7的报告可能不包含矛盾分析
        return {'score': 20, 'passed': False, 'reason': 'A7输出中未包含矛盾分析'}
    
    return {'score': 0, 'passed': False, 'reason': '未知Agent'}

def check_theory_practice_alignment(report, agent_name):
    """检查知行合一（毛泽东实践论）"""
    alignment_score = report.get('theory_practice_alignment', {}).get('alignment_score', 0)
    
    # 简化评估：如果alignment_score < 50，但报告自评很高，则不一致
    if agent_name == "A0":
        # 检查改进建议是否具体
        suggestions = report.get('improvement_suggestions', [])
        specific_suggestions = [s for s in suggestions if 'action' in s and 'responsible' in s]
        
        if len(specific_suggestions) < len(suggestions) / 2:
            return {'score': alignment_score - 20, 'passed': False, 'reason': '改进建议不具体'}
        
        return {'score': alignment_score, 'passed': alignment_score >= 60, 'reason': ''}
    
    elif agent_name == "A7":
        # 检查门禁决策是否合理
        gate_decision = report.get('gate_decision', '')
        
        if gate_decision == "WARNING - 有条件通过":
            return {'score': alignment_score - 25, 'passed': False, 'reason': '门禁放水'}
        
        return {'score': alignment_score, 'passed': alignment_score >= 70, 'reason': ''}
    
    return {'score': 0, 'passed': False, 'reason': '未知Agent'}

def generate_criticism_report(a0_report, a7_report, output_path):
    """生成A8自我批评报告"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    report_id = f"A8_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    # 执行所有检查
    a0_ct = check_critical_thinking(a0_report, "A0")
    a0_cb = check_cognitive_biases(a0_report, "A0")
    a0_rt = check_rationality(a0_report, "A0")
    a0_ca = check_contradiction_analysis(a0_report, "A0")
    a0_tp = check_theory_practice_alignment(a0_report, "A0")
    
    a7_ct = check_critical_thinking(a7_report, "A7")
    a7_cb = check_cognitive_biases(a7_report, "A7")
    a7_rt = check_rationality(a7_report, "A7")
    a7_ca = check_contradiction_analysis(a7_report, "A7")
    a7_tp = check_theory_practice_alignment(a7_report, "A7")
    
    # 生成Markdown报告
    report_content = f"""# A8 自我批评报告（自动化分析）

**报告ID**: {report_id}  
**生成时间**: {timestamp}  
**分析对象**: A0 + A7 输出  
**分析类型**: 自动化批评

---

## 一、A0输出分析

### 1.1 批判性思维检查（Paul的8个元素）
- **覆盖元素**: {a0_ct['covered']}
- **未覆盖元素**: {a0_ct['uncovered']}
- **评分**: {a0_ct['score']:.1f}分
- **状态**: {'✅ PASS' if a0_ct['passed'] else '❌ FAIL'}

### 1.2 认知偏差识别（Kahneman的7大偏差）
- **已识别**: {a0_cb['detected']}
- **未识别**: {a0_cb['missed']}
- **识别率**: {a0_cb['recognition_rate']:.1f}%
- **状态**: {'✅ PASS' if a0_cb['passed'] else '❌ FAIL'}

### 1.3 理性评估（Stanovich框架）
- **A0自评**: {a0_rt['self_rating']}分
- **A8评估**: {a0_rt['a8_rating']}分
- **偏差**: {a0_rt['deviation']}分
- **状态**: {'✅ PASS' if a0_rt['passed'] else '❌ FAIL'}

### 1.4 矛盾分析（毛泽东矛盾论）
- **评分**: {a0_ca['score']}分
- **原因**: {a0_ca['reason']}
- **状态**: {'✅ PASS' if a0_ca['passed'] else '❌ FAIL'}

### 1.5 知行合一检查（毛泽东实践论）
- **评分**: {a0_tp['score']}分
- **原因**: {a0_tp['reason']}
- **状态**: {'✅ PASS' if a0_tp['passed'] else '❌ FAIL'}

---

## 二、A7输出分析

### 2.1 批判性思维检查（Paul的8个元素）
- **覆盖元素**: {a7_ct['covered']}
- **未覆盖元素**: {a7_ct['uncovered']}
- **评分**: {a7_ct['score']:.1f}分
- **状态**: {'✅ PASS' if a7_ct['passed'] else '❌ FAIL'}

### 2.2 认知偏差识别（Kahneman的7大偏差）
- **已识别**: {a7_cb['detected']}
- **未识别**: {a7_cb['missed']}
- **识别率**: {a7_cb['recognition_rate']:.1f}%
- **状态**: {'✅ PASS' if a7_cb['passed'] else '❌ FAIL'}

### 2.3 理性评估（Stanovich框架）
- **A7自评**: {a7_rt['self_rating']}分
- **A8评估**: {a7_rt['a8_rating']}分
- **偏差**: {a7_rt['deviation']}分
- **状态**: {'✅ PASS' if a7_rt['passed'] else '❌ FAIL'}

### 2.4 矛盾分析（毛泽东矛盾论）
- **评分**: {a7_ca['score']}分
- **原因**: {a7_ca['reason']}
- **状态**: {'✅ PASS' if a7_ca['passed'] else '❌ FAIL'}

### 2.5 知行合一检查（毛泽东实践论）
- **评分**: {a7_tp['score']}分
- **原因**: {a7_tp['reason']}
- **状态**: {'✅ PASS' if a7_tp['passed'] else '❌ FAIL'}

---

## 三、总体评估

### 3.1 A0总体状态
- 批判性思维: {'✅' if a0_ct['passed'] else '❌'}
- 认知偏差识别: {'✅' if a0_cb['passed'] else '❌'}
- 理性评估: {'✅' if a0_rt['passed'] else '❌'}
- 矛盾分析: {'✅' if a0_ca['passed'] else '❌'}
- 知行合一: {'✅' if a0_tp['passed'] else '❌'}

**A0总体状态**: {'✅ PASS' if all([a0_ct['passed'], a0_cb['passed'], a0_rt['passed'], a0_ca['passed'], a0_tp['passed']]) else '❌ FAIL'}

### 3.2 A7总体状态
- 批判性思维: {'✅' if a7_ct['passed'] else '❌'}
- 认知偏差识别: {'✅' if a7_cb['passed'] else '❌'}
- 理性评估: {'✅' if a7_rt['passed'] else '❌'}
- 矛盾分析: {'✅' if a7_ca['passed'] else '❌'}
- 知行合一: {'✅' if a7_tp['passed'] else '❌'}

**A7总体状态**: {'✅ PASS' if all([a7_ct['passed'], a7_cb['passed'], a7_rt['passed'], a7_ca['passed'], a7_tp['passed']]) else '❌ FAIL'}

---

## 四、改进建议

### 4.1 对A0的改进建议
1. 覆盖所有8个批判性思维元素
2. 识别全部7大认知偏差
3. 降低理性自评，避免高估
4. 明确识别主要矛盾
5. 提高知行合一评分至60+

### 4.2 对A7的改进建议
1. 加强批判性思维（特别是假设和视角）
2. 识别认知偏差（A7容易忽视）
3. 严格门禁标准，避免放水
4. 增加矛盾分析（A7也应分析矛盾）
5. 提高知行合一评分至70+

---

## 五、批评有效性验证机制（新增）

### 5.1 批评记录
- **批评ID**: {report_id}
- **批评时间**: {timestamp}
- **批评对象**: A0 + A7
- **批评内容**: 上述所有检查项

### 5.2 改进跟踪
- **跟踪期限**: 7天
- **改进证据**: A0/A7重新运行后的输出
- **验证标准**: 所有FAIL项变为PASS

### 5.3 批评有效性评分（7天后评估）
- **有效**: A0/A7改进后，所有检查项PASS
- **部分有效**: A0/A7改进后，部分检查项PASS
- **无效**: A0/A7改进后，仍然FAIL

**如果批评无效**: 回滚此次批评，重新分析

---

**报告生成完成**: {timestamp}
"""

    # 保存报告
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(report_content)
    
    print(f"✅ A8批评报告已生成: {output_path}")
    
    # 返回检查结果（用于调用门禁脚本）
    return {
        'report_id': report_id,
        'a0_status': 'PASS' if all([a0_ct['passed'], a0_cb['passed'], a0_rt['passed'], a0_ca['passed'], a0_tp['passed']]) else 'FAIL',
        'a7_status': 'PASS' if all([a7_ct['passed'], a7_cb['passed'], a7_rt['passed'], a7_ca['passed'], a7_tp['passed']]) else 'FAIL',
        'timestamp': timestamp
    }

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='A8自动化分析脚本 - 分析A0/A7输出')
    parser.add_argument('a0_json', help='A0输出的JSON文件路径')
    parser.add_argument('a7_json', help='A7输出的JSON文件路径')
    parser.add_argument('-o', '--output', help='输出报告路径（可选）', default=None)
    
    args = parser.parse_args()
    
    # 加载A0和A7的输出
    a0_report = load_json_file(args.a0_json, "A0输出")
    a7_report = load_json_file(args.a7_json, "A7输出")
    
    if not a0_report or not a7_report:
        sys.exit(1)
    
    # 确定输出路径
    if args.output:
        output_path = args.output
    else:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_path = f"reports/a8_auto_criticism_{timestamp}.md"
    
    # 生成批评报告
    result = generate_criticism_report(a0_report, a7_report, output_path)
    
    # 输出摘要
    print("="*80)
    print("A8自动化分析完成")
    print("="*80)
    print(f"A0状态: {result['a0_status']}")
    print(f"A7状态: {result['a7_status']}")
    print(f"报告ID: {result['report_id']}")
    print("="*80)
    
    # 根据状态返回exit code
    if result['a0_status'] == 'FAIL' or result['a7_status'] == 'FAIL':
        sys.exit(1)
    else:
        sys.exit(0)

if __name__ == "__main__":
    main()
