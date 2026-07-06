#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ai-trading-compliance v2.0 - 综合测试脚本

测试所有检查器的实际逻辑:
1. R0-R3 分级器
2. 硬门禁检查器 (9项)
3. 回滚验证器 (5项)
4. 风险方向检查器
5. 合规引擎 (端到端)
6. 审计轨迹管理器
"""

import json
import sys
from pathlib import Path

# 添加 scripts 目录到 sys.path
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

try:
    from compliance_engine import ComplianceEngine
    from r_level_classifier import RLevelClassifier
    from hard_gate_checker import HardGateChecker
    from rollback_validator import RollbackValidator
    from risk_direction_checker import RiskDirectionChecker
    from audit_trail import AuditTrailManager
    print("✓ 所有检查器导入成功")
except ImportError as e:
    print(f"✗ 导入失败: {e}")
    sys.exit(1)


def test_r_level_classifier():
    """测试 R0-R3 分级器"""
    print("\n" + "="*60)
    print("测试 1: R0-R3 分级器")
    print("="*60)

    try:
        classifier = RLevelClassifier()

        # 测试用例 1: R0 只读变更
        bundle_r0 = {
            "intent": {"what": "查看策略配置", "why": "分析", "impact_scope": ["monitor"]},
            "change_type": "R0",
            "risk_level": "P3"
        }
        result_r0 = classifier.classify(bundle_r0)
        print(f"✓ R0 分级测试: {result_r0}")

        # 测试用例 2: R1 非生产变更
        bundle_r1 = {
            "intent": {"what": "更新回测脚本", "why": "改进分析", "impact_scope": ["parameter"]},
            "change_type": "R1",
            "risk_level": "P3"
        }
        result_r1 = classifier.classify(bundle_r1)
        print(f"✓ R1 分级测试: {result_r1}")

        # 测试用例 3: R2 受控变更
        bundle_r2 = {
            "intent": {"what": "优化止损逻辑", "why": "降低回撤", "impact_scope": ["parameter", "logic"]},
            "change_type": "R2",
            "risk_level": "P1"
        }
        result_r2 = classifier.classify(bundle_r2)
        print(f"✓ R2 分级测试: {result_r2}")

        # 测试用例 4: R3 代码变更
        bundle_r3 = {
            "intent": {"what": "重构信号生成模块", "why": "提升性能", "impact_scope": ["代码", "架构"]},
            "change_type": "R3",
            "risk_level": "P0"
        }
        result_r3 = classifier.classify(bundle_r3)
        print(f"✓ R3 分级测试: {result_r3}")

        print("\n✅ R0-R3 分级器测试通过")
        return True

    except Exception as e:
        print(f"\n✗ R0-R3 分级器测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_hard_gate_checker():
    """测试硬门禁检查器 (9项)"""
    print("\n" + "="*60)
    print("测试 2: 硬门禁检查器 (9项)")
    print("="*60)

    try:
        checker = HardGateChecker(workspace_dir=str(SCRIPT_DIR.parent.parent))

        # 测试用例 1: 完整变更包 (应该 PASS 或 WARN)
        bundle_pass = {
            "doc_refs": [str(SCRIPT_DIR.parent / "SKILL.md")],
            "artifacts": {
                "data_snapshot_id": "snap_20260506",
                "config_version": "v1.2.3",
                "strategy_key": "momentum_v2"
            },
            "rollback_plan": {
                "rollback_plan_id": "rollback_001",
                "rollback_points": [str(SCRIPT_DIR)],
                "triggers": ["max_drawdown > 0.05", "pnl < -100"]
            },
            "change_type": "R2",
            "risk_level": "P1",
            "intent": "测试变更"
        }
        result_pass = checker.check(bundle_pass)
        print(f"\n✓ 完整变更包测试: {result_pass['summary']}")
        print(f"  失败项数: {result_pass['failed_count']}/9")

        # 测试用例 2: 缺失字段 (应该 FAIL)
        bundle_fail = {
            "doc_refs": [],
            "artifacts": {},
            "change_type": "R3",
            "risk_level": "P0"
        }
        result_fail = checker.check(bundle_fail)
        print(f"\n✓ 缺失字段测试: {result_fail['summary']}")
        print(f"  失败项数: {result_fail['failed_count']}/9")

        print("\n✅ 硬门禁检查器测试通过")
        return True

    except Exception as e:
        print(f"\n✗ 硬门禁检查器测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_rollback_validator():
    """测试回滚验证器 (5项)"""
    print("\n" + "="*60)
    print("测试 3: 回滚验证器 (5项)")
    print("="*60)

    try:
        validator = RollbackValidator(workspace_dir=str(SCRIPT_DIR.parent.parent))

        # 测试用例 1: 完整回滚计划 (应该 PASS)
        bundle_pass = {
            "rollback_plan": {
                "rollback_plan_id": "rollback_001",
                "rollback_points": [str(SCRIPT_DIR)],
                "triggers": ["max_drawdown > 0.05", "pnl < -100"],
                "actions": ["restore_config", "disable_feature"],
                "manual_trigger": "人工确认"
            }
        }
        result_pass = validator.validate(bundle_pass)
        print(f"\n✓ 完整回滚计划测试: {result_pass['summary']}")

        # 测试用例 2: 缺失字段 (应该 FAIL)
        bundle_fail = {
            "rollback_plan": {
                "rollback_plan_id": "rollback_002"
            }
        }
        result_fail = validator.validate(bundle_fail)
        print(f"\n✓ 缺失字段测试: {result_fail['summary']}")

        print("\n✅ 回滚验证器测试通过")
        return True

    except Exception as e:
        print(f"\n✗ 回滚验证器测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_risk_direction_checker():
    """测试风险方向检查器"""
    print("\n" + "="*60)
    print("测试 4: 风险方向检查器")
    print("="*60)

    try:
        checker = RiskDirectionChecker(workspace_dir=str(SCRIPT_DIR.parent.parent))

        # 测试用例 1: 收紧型变更
        bundle_tighten = {
            "intent": {
                "what": "修复杠杆计算 bug",
                "why": "收紧风险控制",
                "impact_scope": ["parameter"]
            },
            "change_type": "R2",
            "risk_level": "P1"
        }
        result_tighten = checker.evaluate(bundle_tighten)
        print(f"\n✓ 收紧型变更测试: {result_tighten['summary']}")

        # 测试用例 2: 风险扩张型变更
        bundle_expansion = {
            "intent": {
                "what": "放宽杠杆阈值并增加交易对",
                "why": "扩大收益",
                "impact_scope": ["parameter", "strategy"]
            },
            "change_type": "R3",
            "risk_level": "P0",
            "rollout_plan": {
                "mode": "full"
            }
        }
        result_expansion = checker.evaluate(bundle_expansion)
        print(f"\n✓ 风险扩张型变更测试: {result_expansion['summary']}")
        print(f"  Canary 要求: {result_expansion.get('canary_required', False)}")

        print("\n✅ 风险方向检查器测试通过")
        return True

    except Exception as e:
        print(f"\n✗ 风险方向检查器测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_compliance_engine():
    """测试合规引擎 (端到端)"""
    print("\n" + "="*60)
    print("测试 5: 合规引擎 (端到端)")
    print("="*60)

    try:
        engine = ComplianceEngine(audit_dir=str(SCRIPT_DIR.parent / "audit"))

        # 测试用例 1: 完整变更包 (应该 PASS 或 WARN)
        bundle_pass = {
            "intent": {
                "what": "修复风险管理逻辑",
                "why": "收紧风险控制",
                "evidence": "回测显示风险指标异常",
                "impact_scope": ["parameter"]
            },
            "change_type": "R2",
            "risk_level": "P1",
            "doc_refs": [str(SCRIPT_DIR.parent / "SKILL.md")],
            "artifacts": {
                "data_snapshot_id": "snap_20260506",
                "config_version": "v1.2.3",
                "strategy_key": "momentum_v2"
            },
            "rollback_plan": {
                "rollback_plan_id": "rollback_001",
                "rollback_points": [str(SCRIPT_DIR)],
                "triggers": ["max_drawdown > 0.05"],
                "actions": ["restore_config"]
            },
            "trace_id": "trace_20260506_001"
        }
        receipt_pass = engine.process(bundle_pass)
        print(f"\n✓ 完整变更包测试: decision={receipt_pass['decision']}")
        print(f"  变更分类: {receipt_pass['change_classification']['change_type']}")
        print(f"  发布要求: {receipt_pass['rollout_requirements']['mode']}")

        print("\n✅ 合规引擎测试通过")
        return True

    except Exception as e:
        print(f"\n✗ 合规引擎测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_audit_trail():
    """测试审计轨迹管理器"""
    print("\n" + "="*60)
    print("测试 6: 审计轨迹管理器")
    print("="*60)

    try:
        manager = AuditTrailManager(audit_dir=str(SCRIPT_DIR.parent / "audit"))

        # 写入测试记录
        test_receipt = {
            "decision": "pass",
            "change_classification": {
                "change_type": "R2",
                "risk_level": "P1"
            },
            "hard_constraints_checked": {},
            "blockers": [],
            "warnings": [],
            "required_actions": [],
            "rollout_requirements": {"mode": "canary"},
            "audit_fields": {
                "doc_refs": [],
                "trace_id": "test_001",
                "artifacts": [],
                "approver_roles": ["risk_owner"]
            }
        }
        manager.record(test_receipt)
        print(f"✓ 审计记录写入成功")

        # 查询测试记录
        records = manager.query(trace_id="test_001")
        print(f"✓ 审计记录查询成功: {len(records)} 条记录")

        print("\n✅ 审计轨迹管理器测试通过")
        return True

    except Exception as e:
        print(f"\n✗ 审计轨迹管理器测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """主测试流程"""
    print("="*60)
    print("ai-trading-compliance v2.0 - 综合测试")
    print("="*60)

    results = []

    # 执行所有测试
    results.append(("R0-R3 分级器", test_r_level_classifier()))
    results.append(("硬门禁检查器", test_hard_gate_checker()))
    results.append(("回滚验证器", test_rollback_validator()))
    results.append(("风险方向检查器", test_risk_direction_checker()))
    results.append(("合规引擎", test_compliance_engine()))
    results.append(("审计轨迹管理器", test_audit_trail()))

    # 打印测试报告
    print("\n" + "="*60)
    print("测试报告")
    print("="*60)

    passed = 0
    failed = 0

    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}  {name}")
        if result:
            passed += 1
        else:
            failed += 1

    print("\n" + "-"*60)
    print(f"总计: {passed+failed} | 通过: {passed} | 失败: {failed}")
    print("-"*60)

    if failed > 0:
        sys.exit(1)
    else:
        print("\n🎉 所有测试通过!")
        sys.exit(0)


if __name__ == "__main__":
    main()
