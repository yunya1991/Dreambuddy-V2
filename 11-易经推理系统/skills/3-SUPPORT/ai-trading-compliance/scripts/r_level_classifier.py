#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
R0-R3 自动分级器

分类规则:
- R0: 纯读取/诊断/报告生成 - 只读观测，允许自动执行
- R1: 配置参数查看/非生产变更 - 允许自动执行但必须可审计
- R2: 受控变更(配置/灰度/回滚/触发) - 必须审批后才能执行
- R3: 代码变更(策略逻辑/执行链路) - 禁止直接生效，必须走更严格流程
"""

import re
from typing import Dict, Any, List


class RLevelClassifier:
    """
    R0-R3 变更分级器

    检测方法:
    1. 检查 change_type 是否与实际变更内容匹配
    2. 检测是否涉及 prod_write、external_publish、strategy_change
    3. 风险扩张检测
    """

    def __init__(self):
        # 定义 R3 关键词 (代码变更)
        self.r3_keywords = [
            'strategy_change', 'strategy_logic', 'execution_chain',
            'code_change', 'algorithm', 'model_update',
            'risk_gate', 'gate_logic', 'scoring_logic'
        ]

        # 定义 R2 关键词 (受控变更)
        self.r2_keywords = [
            'config_change', 'parameter_adjustment', 'gray_release',
            'canary', 'rollback_trigger', 'automation_adjustment'
        ]

        # 定义 R1 关键词 (非生产变更)
        self.r1_keywords = [
            'config_view', 'non_prod_change', 'diagnostic',
            'report_generation', 'data_query'
        ]

        # 定义 R0 关键词 (只读)
        self.r0_keywords = [
            'read_only', 'diagnostic', 'observation',
            'report', 'query', 'view'
        ]

        # Prod 写入检测
        self.prod_write_patterns = [
            r'prod.*write', r'production.*write', r'主盘.*写入',
            r'实盘.*修改', r'prod.*config', r'production.*config'
        ]

        # 外联发布检测
        self.external_publish_patterns = [
            r'publish.*twitter', r'publish.*telegram', r'发布.*推特',
            r'发布.*TG', r'external.*publish', r'outbox'
        ]

    def classify(self, change_bundle: Dict[str, Any]) -> str:
        """
        对变更包进行 R0-R3 自动分级

        Args:
            change_bundle: 变更包字典

        Returns:
            str: "R0" | "R1" | "R2" | "R3"
        """
        # 获取手动分级 (如果有)
        manual_level = change_bundle.get("change_type", "R0")

        # 自动检测分级
        auto_level = self._auto_classify(change_bundle)

        # 记录分类理由
        self._log_classification_reason(manual_level, auto_level, change_bundle)

        # 返回更高的分级 (更严格)
        return self._choose_stricter_level(manual_level, auto_level)

    def _auto_classify(self, change_bundle: Dict[str, Any]) -> str:
        """自动检测变更级别"""

        # 检测 1: 是否有 Prod 写入
        if self._detect_prod_write(change_bundle):
            return "R3"  # Prod 写入必须走最严格流程

        # 检测 2: 是否有外联发布
        if self._detect_external_publish(change_bundle):
            return "R2"  # 外联发布需要审批

        # 检测 3: 代码/策略变更
        if self._detect_code_change(change_bundle):
            return "R3"

        # 检测 4: 配置/参数变更
        if self._detect_config_change(change_bundle):
            return "R2"

        # 检测 5: 有回滚计划
        if self._detect_rollback_plan(change_bundle):
            return "R2"

        # 检测 6: 诊断/报告类
        if self._detect_diagnostic(change_bundle):
            return "R0"

        # 默认: R1 (非生产变更)
        return "R1"

    def _detect_prod_write(self, bundle: Dict[str, Any]) -> bool:
        """检测 Prod 写入"""
        intent_what = bundle.get("intent", {}).get("what", "").lower()
        intent_scope = bundle.get("intent", {}).get("impact_scope", [])

        # 检查 impact_scope
        if "prod" in intent_scope or "production" in intent_scope:
            return True

        # 检查关键词
        for pattern in self.prod_write_patterns:
            if re.search(pattern, intent_what, re.IGNORECASE):
                return True

        return False

    def _detect_external_publish(self, bundle: Dict[str, Any]) -> bool:
        """检测外联发布"""
        intent_what = bundle.get("intent", {}).get("what", "").lower()
        intent_scope = bundle.get("intent", {}).get("impact_scope", [])

        # 检查 impact_scope
        if "external" in intent_scope:
            return True

        # 检查 external_publish 字段
        if "external_publish" in bundle:
            return True

        # 检查关键词
        for pattern in self.external_publish_patterns:
            if re.search(pattern, intent_what, re.IGNORECASE):
                return True

        return False

    def _detect_code_change(self, bundle: Dict[str, Any]) -> bool:
        """检测代码/策略变更"""
        intent_what = bundle.get("intent", {}).get("what", "").lower()

        # 检查关键词
        for keyword in self.r3_keywords:
            if keyword in intent_what:
                return True

        # 检查 artifacts 是否包含策略
        artifacts = bundle.get("artifacts", {})
        if "strategy_key" in artifacts:
            # 有 strategy_key 可能是策略变更
            if "backtest_summary" in artifacts or "robustness" in artifacts:
                return True

        return False

    def _detect_config_change(self, bundle: Dict[str, Any]) -> bool:
        """检测配置/参数变更"""
        intent_what = bundle.get("intent", {}).get("what", "").lower()

        # 检查关键词
        for keyword in self.r2_keywords:
            if keyword in intent_what:
                return True

        # 检查 rollout_plan (灰度发布计划)
        if "rollout_plan" in bundle:
            return True

        return False

    def _detect_rollback_plan(self, bundle: Dict[str, Any]) -> bool:
        """检测回滚计划"""
        return "rollback_plan" in bundle

    def _detect_diagnostic(self, bundle: Dict[str, Any]) -> bool:
        """检测诊断/报告类 (R0)"""
        intent_what = bundle.get("intent", {}).get("what", "").lower()
        intent_why = bundle.get("intent", {}).get("why", "").lower()

        # R0 关键词
        r0_patterns = [
            r'report', r'报告', r'diagnos', r'诊断',
            r'query', r'查询', r'view', r'查看', r'观察',
            r'read', r'读取', r'list', r'列出'
        ]

        for pattern in r0_patterns:
            if re.search(pattern, intent_what, re.IGNORECASE):
                return True
            if re.search(pattern, intent_why, re.IGNORECASE):
                return True

        return False

    def _log_classification_reason(
        self,
        manual_level: str,
        auto_level: str,
        bundle: Dict[str, Any]
    ) -> None:
        """记录分类理由"""
        intent_what = bundle.get("intent", {}).get("what", "未知")

        print(f"  分类依据:")
        print(f"    - 变更意图: {intent_what[:50]}...")
        print(f"    - 手动分级: {manual_level}")
        print(f"    - 自动分级: {auto_level}")

        if manual_level != auto_level:
            print(f"    ⚠️ 手动分级与自动分级不一致，使用更严格的: {self._choose_stricter_level(manual_level, auto_level)}")

    def _choose_stricter_level(self, level1: str, level2: str) -> str:
        """
        选择更严格的分级

        严格程度: R3 > R2 > R1 > R0
        """
        strictness = {"R3": 3, "R2": 2, "R1": 1, "R0": 0}

        # 返回更严格的
        if strictness.get(level1, 0) >= strictness.get(level2, 0):
            return level1
        else:
            return level2

    def get_level_description(self, level: str) -> str:
        """获取分级描述"""
        descriptions = {
            "R0": "只读观测/诊断/报告生成 - 允许自动执行",
            "R1": "配置参数查看/非生产变更 - 允许自动执行但必须可审计",
            "R2": "受控变更(配置/灰度/回滚/触发) - 必须审批后才能执行",
            "R3": "代码变更(策略逻辑/执行链路) - 禁止直接生效，必须走更严格流程"
        }
        return descriptions.get(level, "未知分级")


def test_classification():
    """测试分级器"""
    classifier = RLevelClassifier()

    # 测试用例 1: R0 - 只读报告
    bundle_r0 = {
        "intent": {
            "what": "生成交易报告",
            "why": "诊断系统状态",
            "impact_scope": ["diagnostic"]
        },
        "change_type": "R0",
        "risk_level": "P3"
    }
    result_r0 = classifier.classify(bundle_r0)
    print(f"\n测试 R0: {result_r0} - {classifier.get_level_description(result_r0)}")

    # 测试用例 2: R2 - 配置变更
    bundle_r2 = {
        "intent": {
            "what": "调整杠杆参数",
            "why": "优化仓位管理",
            "impact_scope": ["parameter"]
        },
        "change_type": "R2",
        "risk_level": "P1",
        "rollout_plan": {
            "mode": "canary"
        }
    }
    result_r2 = classifier.classify(bundle_r2)
    print(f"\n测试 R2: {result_r2} - {classifier.get_level_description(result_r2)}")

    # 测试用例 3: R3 - 策略变更
    bundle_r3 = {
        "intent": {
            "what": "修改策略逻辑",
            "why": "提升策略表现",
            "impact_scope": ["strategy"]
        },
        "change_type": "R3",
        "risk_level": "P0",
        "artifacts": {
            "strategy_key": "momentum_strategy_v2",
            "backtest_summary": {}
        }
    }
    result_r3 = classifier.classify(bundle_r3)
    print(f"\n测试 R3: {result_r3} - {classifier.get_level_description(result_r3)}")


if __name__ == "__main__":
    test_classification()
