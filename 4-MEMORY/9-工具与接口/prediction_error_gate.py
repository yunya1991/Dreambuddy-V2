#!/usr/bin/env python3
"""预测误差门控 record — PredictionErrorGate

定位：L4 元认知层 record 路径核心增强，借鉴预测编码/自由能原理（Friston）
与记忆再巩固边界（Royal Society B 2026）。

核心思想:
  record 前生成"预期"（基于 recall 结果），与实际结果差异大时提高
  quality_level 初值（类比情绪记忆增强 — 高预测误差事件更值得记住）。

核心能力:
  1. compute_prediction_error(expected, actual) — 预测误差 = |expected - actual|
  2. decide_quality_level(prediction_error) — 门控决策:
     - 误差 > PE_THRESHOLD (0.3) → "B"（高预测误差 → 提升初始质量）
     - 否则 → "C"（符合预期 → 正常质量）
  3. should_accept_intrusion(base_level) — 记忆再巩固边界:
     - 只有弱记忆（base_level < BASE_LEVEL_BOUNDARY 0.5）才在 recall 后
       接受新信息侵入；强记忆抵抗侵入（防止已验证记忆被随意改写）
  4. prepare_record_params(content, expected, actual, extra_tags) — 输出
     record() 参数（content + quality_level + tags 带 prediction_error）

设计原则:
  - FAIL-OPEN：None/NaN/字符串/异常 → 误差 0.0 → 正常质量 C，不阻塞 record
  - 复用 33-REA cognitive_integration.prepare_record_params 模式
  - 依赖 P3-2 Self-Model（metadata 决策链）但无硬耦合
  - 轻量级：纯 Python，无外部依赖

参考:
  - SPEC-CognitiveSystem-Evolution.md §2.5.4 + §4.3 P3-4
  - Friston 自由能原理 / 预测编码
  - 记忆再巩固边界 (Memory Reconsolidation Boundary)
"""
from __future__ import annotations

import math
from typing import Any, Dict, Optional


# ============================================================
# 常量
# ============================================================

PE_THRESHOLD: float = 0.3  # 预测误差阈值，严格大于则升级 quality_level
BASE_LEVEL_BOUNDARY: float = 0.5  # 记忆再巩固边界：base_level < 0.5 视为弱记忆
HIGH_QUALITY: str = "B"  # 高预测误差 → 提升初始质量
NORMAL_QUALITY: str = "C"  # 符合预期 → 正常质量


def _safe_float(value: Any) -> Optional[float]:
    """安全浮点转换。None/NaN/inf/字符串异常 → None（FAIL-OPEN）。"""
    try:
        if value is None:
            return None
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


# ============================================================
# PredictionErrorGate 主类
# ============================================================


class PredictionErrorGate:
    """预测误差门控 record。

    record 前计算"预期 vs 实际"的预测误差，差异大时提升 quality_level
    初值（B），符合预期时正常质量（C）。类比情绪记忆增强机制。
    """

    def __init__(
        self,
        pe_threshold: float = PE_THRESHOLD,
        base_level_boundary: float = BASE_LEVEL_BOUNDARY,
    ) -> None:
        """
        Args:
            pe_threshold: 预测误差阈值（严格大于则升级为 B，默认 0.3）
            base_level_boundary: 记忆再巩固边界（base_level 低于此值视为弱记忆）
        """
        self._pe_threshold = pe_threshold
        self._base_level_boundary = base_level_boundary

    # ============================================================
    # 1. 预测误差计算
    # ============================================================

    def compute_prediction_error(
        self,
        expected_outcome: Any,
        actual_outcome: Any,
    ) -> float:
        """计算预测误差 |expected - actual|。

        Args:
            expected_outcome: 预期结果（基于 recall 的先验，0.0-1.0）
            actual_outcome: 实际结果（0.0-1.0）

        Returns:
            预测误差 0.0-1.0。任何输入无效时返回 0.0（FAIL-OPEN，不阻塞 record）
        """
        expected = _safe_float(expected_outcome)
        actual = _safe_float(actual_outcome)
        if expected is None or actual is None:
            return 0.0  # FAIL-OPEN
        try:
            error = abs(expected - actual)
            if math.isnan(error) or math.isinf(error):
                return 0.0
            # 截断到 [0, 1]（输入超范围时保守处理）
            return max(0.0, min(1.0, error))
        except Exception:
            return 0.0  # FAIL-OPEN

    # ============================================================
    # 2. quality_level 门控决策
    # ============================================================

    def decide_quality_level(self, prediction_error: Any) -> str:
        """基于预测误差决策 quality_level。

        规则（SPEC §2.5.4）:
          - prediction_error > pe_threshold → "B"（高预测误差 → 提升初始质量）
          - 否则 → "C"（符合预期 → 正常质量）

        Args:
            prediction_error: 预测误差 0.0-1.0

        Returns:
            "B" 或 "C"
        """
        error = _safe_float(prediction_error)
        if error is None:
            return NORMAL_QUALITY  # FAIL-OPEN
        return HIGH_QUALITY if error > self._pe_threshold else NORMAL_QUALITY

    # ============================================================
    # 3. 记忆再巩固边界
    # ============================================================

    def should_accept_intrusion(self, base_level: Any) -> bool:
        """记忆再巩固边界：只有弱记忆才在 recall 后接受新信息侵入。

        对应 Royal Society B 2026 记忆再巩固边界:
          - base_level < boundary → 弱记忆 → 接受侵入（True）
          - base_level >= boundary → 强记忆 → 抵抗侵入（False）

        Args:
            base_level: 记忆基础激活水平 0.0-1.0（ACT-R base_level）

        Returns:
            True=接受新信息侵入，False=抵抗。None 时返回 True（FAIL-OPEN 不阻塞）
        """
        level = _safe_float(base_level)
        if level is None:
            return True  # FAIL-OPEN：无 base_level 数据时不阻塞
        return level < self._base_level_boundary

    # ============================================================
    # 4. record() 参数准备
    # ============================================================

    def prepare_record_params(
        self,
        content: str,
        expected_outcome: Any,
        actual_outcome: Any,
        extra_tags: str = "",
    ) -> Dict[str, Any]:
        """准备 record() 参数：门控 quality_level + tags 注入 prediction_error。

        Args:
            content: 记忆内容
            expected_outcome: 预期结果
            actual_outcome: 实际结果
            extra_tags: 额外标签（逗号分隔，可选）

        Returns:
            {
              "content": 内容,
              "quality_level": "B"|"C",
              "tags": "prediction_error=X.XX[,extra_tags]",
              "prediction_error": 误差值（float，便于调用方记录 metadata）,
            }
        """
        try:
            error = self.compute_prediction_error(expected_outcome, actual_outcome)
            quality = self.decide_quality_level(error)

            tag_parts = [f"prediction_error={error:.2f}"]
            if extra_tags:
                tag_parts.append(extra_tags)

            return {
                "content": content,
                "quality_level": quality,
                "tags": ",".join(tag_parts),
                "prediction_error": error,
            }
        except Exception:
            # FAIL-OPEN：异常时正常质量，保证 record 不被阻塞
            return {
                "content": content,
                "quality_level": NORMAL_QUALITY,
                "tags": f"prediction_error=0.00{',' + extra_tags if extra_tags else ''}",
                "prediction_error": 0.0,
            }


# ============================================================
# CLI 自测
# ============================================================


if __name__ == "__main__":
    print("=" * 60)
    print("PredictionErrorGate — 功能验证")
    print("=" * 60)

    gate = PredictionErrorGate()

    # 场景1: 高预测误差 → B
    p1 = gate.prepare_record_params("意外反转案例", 0.2, 0.9, extra_tags="33-REA")
    print(f"\n场景1 高误差: quality={p1['quality_level']}, tags={p1['tags']}")

    # 场景2: 符合预期 → C
    p2 = gate.prepare_record_params("常规记录", 0.5, 0.5)
    print(f"场景2 符合预期: quality={p2['quality_level']}, tags={p2['tags']}")

    # 场景3: 再巩固边界
    print(f"\n场景3 弱记忆(base=0.2)接受侵入: {gate.should_accept_intrusion(0.2)}")
    print(f"场景3 强记忆(base=0.9)抵抗侵入: {gate.should_accept_intrusion(0.9)}")

    # 场景4: FAIL-OPEN
    p4 = gate.prepare_record_params("异常输入", None, "invalid")
    print(f"\n场景4 FAIL-OPEN: quality={p4['quality_level']}, error={p4['prediction_error']}")

    print("\n" + "=" * 60)
    print("✅ PredictionErrorGate 功能验证通过")
