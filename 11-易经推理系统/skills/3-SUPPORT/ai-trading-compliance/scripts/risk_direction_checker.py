#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
风险方向检查器 (Risk Direction Checker)

判定变更是收紧型 (tighten-only) 还是风险扩张型 (risk expansion)

收紧型 (TIGHTEN_ONLY):
- 修复/自动化动作默认为收紧型 (止血型)
- 禁止用"放宽门槛/加仓"掩盖执行或数据问题

风险扩张型 (RISK_EXPANSION):
- 扩大交易对/杠杆/频率/放宽风控阈值/新增外联发布
- 必须证明通过更高证据等级的沙箱验证
- 在 Prod 走人工审批 (risk owner + strategy owner)
- 先 Canary，再二次审批后扩面
"""

import os
from typing import Dict, Any, List


class RiskDirectionChecker:
    """
    风险方向检查器

    判定逻辑:
    1. 检测是否涉及风险扩张要素
    2. 检测是否有审批
    3. 返回 TIGHTEN_ONLY 或 RISK_EXPANSION
    """

    def __init__(self, workspace_dir: str = None):
        """
        初始化风险方向检查器

        Args:
            workspace_dir: 工作目录 (默认: 当前目录)
        """
        self.workspace_dir = workspace_dir or os.getcwd()

        # 风险扩张关键词
        self.expansion_keywords = [
            'increase_leverage', 'add_trading_pair', 'increase_frequency',
            'relax_threshold', 'relax_risk_control', 'expand_position',
            '放宽', '加仓', '扩大', '增加杠杆', '增加频率',
            'leverage', 'margin', 'expand'
        ]

        # 收紧型关键词
        self.tighten_keywords = [
            'reduce_leverage', 'reduce_position', 'tighten_threshold',
            'add_risk_control', 'fix_bug', 'heal', 'repair',
            '收紧', '降低', '修复', '止血', 'reduce', 'fix'
        ]

        # 需要审批的风险扩张类型
        self.requires_approval = [
            'increase_leverage', 'add_trading_pair', 'relax_threshold',
            '新增外联', 'external_publish', 'expand_position'
        ]

        # 环境关键词
        self.prod_keywords = ['prod', 'production', 'main', 'master', '实盘', '生产']

    def evaluate(self, change_bundle: Dict[str, Any]) -> Dict[str, Any]:
        """
        评估变更的风险方向

        Returns:
            Dict: {
                "summary": "TIGHTEN_ONLY" | "RISK_EXPANSION",
                "details": [...],
                "has_approval": bool,
                "approval_roles": List[str],
                "canary_required": bool,
                "secondary_approval_required": bool
            }
        """
        print("  评估风险方向...")

        details = []
        is_expansion = False
        has_approval = False
        approval_roles = []
        canary_required = False
        secondary_approval_required = False

        # 检测 1: 变更意图
        intent_what = change_bundle.get("intent", {}).get("what", "").lower()
        intent_why = change_bundle.get("intent", {}).get("why", "").lower()

        # 检查风险扩张关键词
        expansion_detected = []
        for keyword in self.expansion_keywords:
            if keyword in intent_what or keyword in intent_why:
                expansion_detected.append(keyword)
                is_expansion = True

        if expansion_detected:
            details.append({
                "check": "变更意图",
                "result": "风险扩张",
                "keywords": expansion_detected
            })
            print(f"    ⚠ 检测到风险扩张关键词: {expansion_detected}")
        else:
            # 检查收紧型关键词
            tighten_detected = []
            for keyword in self.tighten_keywords:
                if keyword in intent_what or keyword in intent_why:
                    tighten_detected.append(keyword)

            if tighten_detected:
                details.append({
                    "check": "变更意图",
                    "result": "收紧型",
                    "keywords": tighten_detected
                })
                print(f"    ✓ 检测到收紧型关键词: {tighten_detected}")

        # 检测 2: artifacts 是否包含风险扩张
        artifacts = change_bundle.get("artifacts", {})
        if artifacts:
            artifact_analysis = self._analyze_artifacts(artifacts)
            if artifact_analysis["is_expansion"]:
                is_expansion = True
                details.append({
                    "check": "artifacts 分析",
                    "result": "风险扩张",
                    "reason": artifact_analysis["reason"]
                })
                print(f"    ⚠ artifacts 分析显示风险扩张: {artifact_analysis['reason']}")

        # 检测 3: rollout_plan 是否是 canary/full
        rollout_plan = change_bundle.get("rollout_plan", {})
        if rollout_plan:
            mode = rollout_plan.get("mode", "disabled")
            if mode == "full":
                is_expansion = True
                canary_required = True
                details.append({
                    "check": "发布计划",
                    "result": "风险扩张",
                    "reason": "full 发布模式 (建议改为 canary)"
                })
                print(f"    ⚠ 检测到 full 发布模式 (风险扩张，建议 canary)")
            elif mode == "canary":
                details.append({
                    "check": "发布计划",
                    "result": "可控发布",
                    "reason": "canary 发布模式"
                })
                print(f"    ✓ 检测到 canary 发布模式 (可控)")

        # 检测 4: external_publish 是否存在
        external_publish = change_bundle.get("external_publish")
        if external_publish:
            is_expansion = True
            canary_required = True
            details.append({
                "check": "外联发布",
                "result": "风险扩张",
                "reason": "包含外联发布"
            })
            print(f"    ⚠ 检测到外联发布 (风险扩张)")

        # 检测 5: 环境检测
        environment = self._detect_environment(change_bundle)
        if environment == "Prod":
            secondary_approval_required = True
            details.append({
                "check": "环境检测",
                "result": "生产环境",
                "reason": "Prod 环境需要二次审批"
            })
            print(f"    ⚠ 检测到 Prod 环境 (需要二次审批)")

        # 检测 6: 是否有审批
        if is_expansion:
            # 检查 doc_refs 是否包含审批记录
            doc_refs = change_bundle.get("doc_refs", [])
            approval_found = any("approval" in ref.lower() or
                                "审批" in ref for ref in doc_refs)
            has_approval = approval_found

            if has_approval:
                details.append({
                    "check": "审批状态",
                    "result": "已审批",
                    "doc_refs": [ref for ref in doc_refs
                                if "approval" in ref.lower() or "审批" in ref]
                })
                print(f"    ✓ 检测到审批记录")
            else:
                details.append({
                    "check": "审批状态",
                    "result": "缺少审批",
                    "reason": "风险扩张变更需要审批"
                })
                print(f"    ✗ 风险扩张变更缺少审批")

            # 确定需要的审批角色
            approval_roles = self._determine_approval_roles(change_bundle)

        # 返回结果
        summary = "RISK_EXPANSION" if is_expansion else "TIGHTEN_ONLY"

        print(f"  风险方向评估结果: {summary}")
        if canary_required:
            print(f"    → 要求: Canary 发布")
        if secondary_approval_required:
            print(f"    → 要求: 二次审批")

        return {
            "summary": summary,
            "details": details,
            "has_approval": has_approval,
            "approval_roles": approval_roles,
            "canary_required": canary_required,
            "secondary_approval_required": secondary_approval_required
        }

    def _analyze_artifacts(self, artifacts: Dict[str, Any]) -> Dict[str, Any]:
        """
        分析 artifacts 检测风险扩张

        Returns:
            Dict: {"is_expansion": bool, "reason": str}
        """
        is_expansion = False
        reason = ""

        # 检查 backtest_summary
        if "backtest_summary" in artifacts:
            backtest = artifacts["backtest_summary"]
            if isinstance(backtest, dict):
                # 检查夏普比率是否下降
                sharpe = backtest.get("sharpe_ratio", 0)
                if sharpe < 1.0:
                    is_expansion = True
                    reason = f"回测夏普比率过低: {sharpe}"

                # 检查最大回撤是否过大
                max_dd = backtest.get("max_drawdown", 0)
                if max_dd > 0.15:
                    is_expansion = True
                    reason = f"回测最大回撤过大: {max_dd}"

        # 检查 config_changes
        if "config_changes" in artifacts:
            config = artifacts["config_changes"]
            if isinstance(config, dict):
                # 检查杠杆是否增加
                leverage_change = config.get("leverage", "")
                if "increase" in leverage_change.lower() or "增加" in leverage_change:
                    is_expansion = True
                    reason = "配置变更包含杠杆增加"

                # 检查仓位是否扩大
                position_change = config.get("position_size", "")
                if "increase" in position_change.lower() or "扩大" in position_change:
                    is_expansion = True
                    reason = "配置变更包含仓位扩大"

        return {"is_expansion": is_expansion, "reason": reason}

    def _detect_environment(self, bundle: Dict[str, Any]) -> str:
        """
        检测变更的目标环境

        Returns:
            str: "Prod" | "Non-Prod" | "Unknown"
        """
        # 从 bundle 中提取环境信息
        bundle_str = str(bundle).lower()

        # 检查是否包含生产环境关键词
        for keyword in self.prod_keywords:
            if keyword in bundle_str:
                return "Prod"

        # 检查 profile 字段
        profile = bundle.get("profile", "")
        if profile and any(kw in profile.lower() for kw in self.prod_keywords):
            return "Prod"

        # 检查 artifacts 中的环境信息
        artifacts = bundle.get("artifacts", {})
        env = artifacts.get("environment", "")
        if env and any(kw in env.lower() for kw in self.prod_keywords):
            return "Prod"

        return "Non-Prod"

    def _determine_approval_roles(self, bundle: Dict[str, Any]) -> List[str]:
        """确定需要的审批角色"""
        roles = []

        # 风险所有者必须审批
        roles.append("risk_owner")

        # 策略所有者必须审批
        artifacts = bundle.get("artifacts", {})
        if "strategy_key" in artifacts:
            roles.append("strategy_owner")

        # 如果是 Prod 环境，需要 ops 审批
        if self._detect_environment(bundle) == "Prod":
            roles.append("ops")
            print(f"    ✓ 检测到 Prod 环境，添加 ops 审批角色")

        return roles


def test_risk_direction_checker():
    """测试风险方向检查器"""
    checker = RiskDirectionChecker()

    # 测试 1: 收紧型变更
    bundle_tighten = {
        "intent": {
            "what": "修复杠杆计算 bug",
            "why": "收紧风险控制",
            "impact_scope": ["parameter"]
        },
        "change_type": "R2",
        "risk_level": "P1"
    }

    print("测试 1: 收紧型变更 (期望: TIGHTEN_ONLY)")
    result_tighten = checker.evaluate(bundle_tighten)
    print(f"结果: {result_tighten['summary']}\n")

    # 测试 2: 风险扩张型变更
    bundle_expansion = {
        "intent": {
            "what": "放宽杠杆阈值并增加交易对",
            "why": "扩大收益",
            "impact_scope": ["parameter", "strategy"]
        },
        "change_type": "R3",
        "risk_level": "P0",
        "rollout_plan": {
            "mode": "canary"
        },
        "external_publish": {
            "channel": "twitter",
            "approval_status": "pending"
        }
    }

    print("测试 2: 风险扩张型变更 (期望: RISK_EXPANSION)")
    result_expansion = checker.evaluate(bundle_expansion)
    print(f"结果: {result_expansion['summary']}")


if __name__ == "__main__":
    test_risk_direction_checker()
