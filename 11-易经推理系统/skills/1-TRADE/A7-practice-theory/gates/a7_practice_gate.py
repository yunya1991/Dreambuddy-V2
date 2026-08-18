#!/usr/bin/env python3
"""
A7 实践论门禁检查实现
基于毛泽东《实践论》的实践论思想，为A4(战术验证)和A5(战术执行)提供门禁检查
"""

import json
import os
from datetime import datetime, timedelta

class A7PracticeGate:
    """A7实践论门禁检查器"""
    
    def __init__(self, workspace_root="/Users/zhangjiangtao/WorkBuddy/20260415144304"):
        self.workspace_root = workspace_root
        self.trading_reports_dir = os.path.join(workspace_root, "reports/trading")
        self.practice_logs_dir = os.path.join(workspace_root, ".workbuddy/practice_logs")
        
        # 确保实践日志目录存在
        os.makedirs(self.practice_logs_dir, exist_ok=True)
    
    def check_a4_gate(self, a1_report, a2_analysis, a3_strategy, practice_log=None):
        """
        A4门禁检查（实践验证前）
        检查项：
        1. 认识来源充分性 (A1-A3报告是否完整?)
        2. 验证设计合理性 (小仓试探方案是否可行?)
        3. 反馈机制完整性 (是否有实践日志记录?)
        4. 真理标准明确性 (P&L/胜率/回撤标准是否明确?)
        """
        checks = {
            "认识来源充分性": self._check_recognition_source(a1_report, a2_analysis, a3_strategy),
            "验证设计合理性": self._check_verification_design(a3_strategy),
            "反馈机制完整性": self._check_feedback_mechanism(practice_log),
            "真理标准明确性": self._check_truth_criteria(a3_strategy)
        }
        
        # 计算通过率
        passed = sum(1 for check in checks.values() if check["pass"])
        total = len(checks)
        pass_rate = passed / total
        
        # 门禁结果：全部通过才PASS
        gate_result = "PASS" if passed == total else "FAIL"
        
        # 生成检查报告
        report = {
            "gate_type": "A4_practice_verification",
            "timestamp": datetime.now().isoformat(),
            "checks": checks,
            "summary": {
                "passed": passed,
                "total": total,
                "pass_rate": f"{pass_rate:.1%}",
                "gate_result": gate_result
            },
            "recommendation": "继续A4实践验证" if gate_result == "PASS" else "返回A1-A3重新调研"
        }
        
        # 保存检查报告
        self._save_gate_report("a4_gate_report", report)
        
        return report
    
    def check_a5_gate(self, a4_scout_report, a3_strategy, execution_plan, practice_log=None):
        """
        A5门禁检查（实践执行前）
        检查项：
        1. 验证充分性 (A4验证样本≥3-5次?)
        2. 认识正确性 (A4反馈是否修正了认识?)
        3. 执行纪律 (是否有明确的执行纪律和止损?)
        4. 风险可控 (实践风险是否在可接受范围?)
        5. 反馈机制 (是否有实时反馈机制?)
        """
        checks = {
            "验证充分性": self._check_verification_sufficient(a4_scout_report),
            "认识正确性": self._check_recognition_correctness(a4_scout_report),
            "执行纪律": self._check_execution_discipline(execution_plan),
            "风险可控": self._check_risk_controllable(execution_plan),
            "反馈机制": self._check_feedback_mechanism(practice_log)
        }
        
        # 计算通过率
        passed = sum(1 for check in checks.values() if check["pass"])
        total = len(checks)
        pass_rate = passed / total
        
        # 门禁结果：全部通过才PASS
        gate_result = "PASS" if passed == total else "FAIL"
        
        # 生成检查报告
        report = {
            "gate_type": "A5_practice_execution",
            "timestamp": datetime.now().isoformat(),
            "checks": checks,
            "summary": {
                "passed": passed,
                "total": total,
                "pass_rate": f"{pass_rate:.1%}",
                "gate_result": gate_result
            },
            "recommendation": "继续A5实践执行" if gate_result == "PASS" else "返回A4重新验证"
        }
        
        # 保存检查报告
        self._save_gate_report("a5_gate_report", report)
        
        return report
    
    def _check_recognition_source(self, a1_report, a2_analysis, a3_strategy):
        """检查认识来源充分性"""
        # 模拟检查逻辑
        a1_complete = a1_report and a1_report.get("exists", False)
        a2_complete = a2_analysis and a2_analysis.get("exists", False)
        a3_complete = a3_strategy and a3_strategy.get("exists", False)
        
        all_complete = a1_complete and a2_complete and a3_complete
        
        return {
            "pass": all_complete,
            "details": {
                "a1_complete": a1_complete,
                "a2_complete": a2_complete,
                "a3_complete": a3_complete,
                "message": "A1-A3报告完整" if all_complete else "A1-A3报告不完整，需要补充"
            }
        }
    
    def _check_verification_design(self, a3_strategy):
        """检查验证设计合理性"""
        # 模拟检查逻辑
        has_strategy = a3_strategy and a3_strategy.get("exists", False)
        has_entry_plan = a3_strategy and "entry_strategy" in a3_strategy
        
        design_ok = has_strategy and has_entry_plan
        
        return {
            "pass": design_ok,
            "details": {
                "has_strategy": has_strategy,
                "has_entry_plan": has_entry_plan,
                "message": "验证设计方案合理" if design_ok else "验证设计方案不合理，需要完善"
            }
        }
    
    def _check_feedback_mechanism(self, practice_log):
        """检查反馈机制完整性"""
        # 模拟检查逻辑
        has_log = practice_log is not None
        log_complete = has_log and len(practice_log) > 0
        
        return {
            "pass": log_complete,
            "details": {
                "has_log": has_log,
                "log_complete": log_complete,
                "message": "反馈机制完整" if log_complete else "反馈机制不完整，需要建立实践日志"
            }
        }
    
    def _check_truth_criteria(self, a3_strategy):
        """检查真理标准明确性"""
        # 模拟检查逻辑
        has_criteria = a3_strategy and "truth_criteria" in a3_strategy
        criteria_complete = has_criteria and len(a3_strategy["truth_criteria"]) >= 3
        
        return {
            "pass": criteria_complete,
            "details": {
                "has_criteria": has_criteria,
                "criteria_complete": criteria_complete,
                "message": "真理标准明确" if criteria_complete else "真理标准不明确，需要定义P&L/胜率/回撤标准"
            }
        }
    
    def _check_verification_sufficient(self, a4_scout_report):
        """检查验证充分性 (A4验证样本≥3-5次?)"""
        # 模拟检查逻辑
        has_report = a4_scout_report and a4_scout_report.get("exists", False)
        sample_count = a4_scout_report.get("verification_samples", 0) if has_report else 0
        sufficient = sample_count >= 3
        
        return {
            "pass": sufficient,
            "details": {
                "has_report": has_report,
                "sample_count": sample_count,
                "sufficient": sufficient,
                "message": f"A4验证样本充足({sample_count}次)" if sufficient else f"A4验证样本不足({sample_count}次)，需要≥3次"
            }
        }
    
    def _check_recognition_correctness(self, a4_scout_report):
        """检查认识正确性 (A4反馈是否修正了认识?)"""
        # 模拟检查逻辑
        has_report = a4_scout_report and a4_scout_report.get("exists", False)
        has_feedback = has_report and "feedback" in a4_scout_report
        recognition_corrected = has_feedback and a4_scout_report.get("recognition_corrected", False)
        
        return {
            "pass": recognition_corrected,
            "details": {
                "has_report": has_report,
                "has_feedback": has_feedback,
                "recognition_corrected": recognition_corrected,
                "message": "认识已修正" if recognition_corrected else "认识未修正，需要根据A4反馈修正认识"
            }
        }
    
    def _check_execution_discipline(self, execution_plan):
        """检查执行纪律 (是否有明确的执行纪律和止损?)"""
        # 模拟检查逻辑
        has_plan = execution_plan is not None
        has_stop_loss = has_plan and "stop_loss" in execution_plan
        has_position_discipline = has_plan and "position_discipline" in execution_plan
        
        discipline_ok = has_stop_loss and has_position_discipline
        
        return {
            "pass": discipline_ok,
            "details": {
                "has_plan": has_plan,
                "has_stop_loss": has_stop_loss,
                "has_position_discipline": has_position_discipline,
                "message": "执行纪律明确" if discipline_ok else "执行纪律不明确，需要定义止损和仓位纪律"
            }
        }
    
    def _check_risk_controllable(self, execution_plan):
        """检查风险可控 (实践风险是否在可接受范围?)"""
        # 模拟检查逻辑
        has_plan = execution_plan is not None
        risk_level = execution_plan.get("risk_level", "unknown") if has_plan else "unknown"
        risk_controllable = risk_level in ["low", "medium"]
        
        return {
            "pass": risk_controllable,
            "details": {
                "has_plan": has_plan,
                "risk_level": risk_level,
                "risk_controllable": risk_controllable,
                "message": "风险可控" if risk_controllable else "风险不可控，需要降低风险水平"
            }
        }
    
    def _save_gate_report(self, report_type, report):
        """保存门禁检查报告"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{report_type}_{timestamp}.json"
        filepath = os.path.join(self.practice_logs_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        return filepath

# 测试函数
def test_a7_gate():
    """测试A7门禁检查"""
    gate = A7PracticeGate()
    
    # 模拟A4门禁检查
    print("=== 测试A4门禁检查 ===")
    a1_report = {"exists": True, "freshness": "<4h"}
    a2_analysis = {"exists": True, "resistance_path": "清晰"}
    a3_strategy = {"exists": True, "direction": "LONG", "truth_criteria": ["P&L>0", "win_rate>50%", "max_drawdown<10%"]}
    
    a4_result = gate.check_a4_gate(a1_report, a2_analysis, a3_strategy)
    print(f"A4门禁结果: {a4_result['summary']['gate_result']}")
    print(f"通过率: {a4_result['summary']['pass_rate']}")
    print()
    
    # 模拟A5门禁检查
    print("=== 测试A5门禁检查 ===")
    a4_scout_report = {"exists": True, "verification_samples": 4, "success_rate": "75%", "recognition_corrected": True}
    execution_plan = {"stop_loss": 78000.0, "position_discipline": "30%", "risk_level": "medium"}
    
    a5_result = gate.check_a5_gate(a4_scout_report, a3_strategy, execution_plan)
    print(f"A5门禁结果: {a5_result['summary']['gate_result']}")
    print(f"通过率: {a5_result['summary']['pass_rate']}")
    
    return a4_result, a5_result

if __name__ == "__main__":
    test_a7_gate()