"""
D3: ResourceAwareDegrader — 资源感知主动降级阶梯（借鉴 ds4 SSD streaming）

SPEC: SPEC-ds4架构借鉴与系统增强.md §3.2 Dimension 3
哲学: ds4 SSD streaming——资源不足时主动降级，而非崩溃。
映射: 从"异常跳过"升级为"主动降级阶梯"——资源不足时逐步简化推理路径。

降级阶梯:
  Level 0 (FULL):         完整深度学习推理（签名+SDE+路径积分+HJB）
  Level 1 (SIMPLIFIED):   简化推理（签名+GARCH+argmin，跳过路径积分）
  Level 2 (RULE_BASELINE): 规则基线（当前四层闭环规则决策）
  Level 3 (FAIL_OPEN):    中性兜底（不下单）

评估维度:
  - 有效样本数 (< 2000 → 降级, < 100 → 规则基线)
  - 模型训练状态 (未训练 → 简化)
  - 最近推理耗时 (> 5000ms → FAIL-OPEN)
  - 系统负载 (> 0.9 → FAIL-OPEN)

硬约束:
  HC-DS4-04: 降级决策必须可观测（日志记录级别和原因）
  HC-DS4-05: 降级到规则基线时，决策质量不得低于当前四层闭环基线
"""
from __future__ import annotations

import logging
from enum import IntEnum
from typing import Any

logger = logging.getLogger(__name__)


class DegradationLevel(IntEnum):
    """降级级别（数值越大降级越严重）.

    使用 IntEnum 自带的 .name 属性获取级别名称（如 "FULL"）.
    """

    FULL = 0          # 完整推理
    SIMPLIFIED = 1    # 简化推理
    RULE_BASELINE = 2 # 规则基线
    FAIL_OPEN = 3     # 中性兜底


class ResourceAwareDegrader:
    """资源感知的主动降级阶梯."""

    # 阈值配置
    SAMPLE_THRESHOLD_SIMPLIFIED = 2000   # < 2000 → 简化
    SAMPLE_THRESHOLD_RULE_BASELINE = 100  # < 100 → 规则基线
    INFERENCE_TIMEOUT_MS = 5000          # > 5000ms → FAIL-OPEN
    SYSTEM_LOAD_THRESHOLD = 0.9          # > 0.9 → FAIL-OPEN

    # 路径来源分类
    DEEP_REASONING_SOURCES = {"deep_reasoning", "path_integral", "neural_sde"}
    SIMPLIFIED_SOURCES = {"signature", "garch", "argmin", "deep_reasoning"}
    RULE_BASELINE_SOURCES = {"rule_baseline"}

    def assess_level(self, context: dict[str, Any]) -> DegradationLevel:
        """根据资源状态评估当前应使用的推理级别.

        Args:
            context: 资源上下文，可包含:
              - sample_count: 有效样本数
              - model_trained: 模型是否训练完成
              - inference_time_ms: 最近推理耗时（毫秒）
              - system_load: 系统负载（0~1）

        Returns:
            DegradationLevel: 建议的推理级别
        """
        result = self.assess_level_with_reason(context)
        return result["level"]

    def assess_level_with_reason(self, context: dict[str, Any]) -> dict[str, Any]:
        """评估级别并返回降级原因（可观测性）.

        Returns:
            dict: {"level": DegradationLevel, "reason": str}
        """
        level = DegradationLevel.FULL
        reasons: list[str] = []

        if not isinstance(context, dict):
            context = {}

        # 1. 样本数检查
        sample_count = context.get("sample_count")
        if isinstance(sample_count, (int, float)):
            if sample_count < self.SAMPLE_THRESHOLD_RULE_BASELINE:
                level = max(level, DegradationLevel.RULE_BASELINE)
                reasons.append(f"sample_count={sample_count} < {self.SAMPLE_THRESHOLD_RULE_BASELINE}")
            elif sample_count < self.SAMPLE_THRESHOLD_SIMPLIFIED:
                level = max(level, DegradationLevel.SIMPLIFIED)
                reasons.append(f"sample_count={sample_count} < {self.SAMPLE_THRESHOLD_SIMPLIFIED}")

        # 2. 模型训练状态
        model_trained = context.get("model_trained")
        if model_trained is False:
            level = max(level, DegradationLevel.SIMPLIFIED)
            reasons.append("model not trained")

        # 3. 推理耗时
        inference_time = context.get("inference_time_ms")
        if isinstance(inference_time, (int, float)) and inference_time > self.INFERENCE_TIMEOUT_MS:
            level = max(level, DegradationLevel.FAIL_OPEN)
            reasons.append(f"inference_time={inference_time}ms > {self.INFERENCE_TIMEOUT_MS}ms")

        # 4. 系统负载
        system_load = context.get("system_load")
        if isinstance(system_load, (int, float)) and system_load > self.SYSTEM_LOAD_THRESHOLD:
            level = max(level, DegradationLevel.FAIL_OPEN)
            reasons.append(f"system_load={system_load} > {self.SYSTEM_LOAD_THRESHOLD}")

        reason = "; ".join(reasons) if reasons else "resources sufficient"

        # HC-DS4-04: 降级决策可观测
        if level > DegradationLevel.FULL:
            logger.info("[DS4-D3] degradation → level=%s reason=%s",
                        level.name, reason)
        else:
            logger.debug("[DS4-D3] level=%s reason=%s",
                         level.name, reason)

        return {"level": level, "reason": reason}

    def degrade_path(self, paths: list[dict], level: DegradationLevel) -> list[dict]:
        """根据降级级别过滤路径候选.

        Args:
            paths: 候选路径列表，每个 dict 含 "source" 字段
            level: 降级级别

        Returns:
            list[dict]: 过滤后的路径列表
        """
        if not isinstance(paths, list) or not paths:
            return []

        if level == DegradationLevel.FULL:
            # Level 0: 保留所有路径
            return list(paths)

        if level == DegradationLevel.FAIL_OPEN:
            # Level 3: 中性兜底，返回空
            return []

        # 过滤逻辑
        result = []
        for p in paths:
            if not isinstance(p, dict):
                continue
            source = str(p.get("source", ""))

            if level == DegradationLevel.SIMPLIFIED:
                # Level 1: 跳过路径积分等重计算路径
                if source in {"path_integral", "neural_sde"}:
                    continue
                result.append(p)

            elif level == DegradationLevel.RULE_BASELINE:
                # Level 2: 仅保留规则基线路径
                if source in self.RULE_BASELINE_SOURCES:
                    result.append(p)

            else:
                # 未知级别：保留（FAIL-OPEN 不删）
                result.append(p)

        return result

    def should_use_deep_reasoning(self, context: dict[str, Any]) -> bool:
        """便捷方法：是否应使用深度学习推理.

        Returns:
            True = 使用完整深度学习推理, False = 降级到更简单路径
        """
        level = self.assess_level(context)
        return level == DegradationLevel.FULL
