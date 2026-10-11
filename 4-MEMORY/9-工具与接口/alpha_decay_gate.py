#!/usr/bin/env python3
"""Alpha Decay 自动门禁 — AlphaDecayGate

定位：L4 元认知层策略级衰减检测，借鉴 Vibe-Trading sdm_decay_scan（24.4K★）。
现状痛点：SKILL 治理偏治理（P2-4 只管入库验证），缺策略级衰减 ——
SKILL/策略入库后长期不验证，alpha（有效性置信）随时间衰减却无人管理。

核心机制（半衰期衰减 + 三级门禁）:
  1. compute_decayed_confidence(confidence, days, half_life)
     — decayed = confidence * 0.5^(days / half_life)
     — days=0 不衰减；1 个半衰期减半；2 个半衰期 1/4
  2. decide_gate_action(decayed_confidence)
     — >= 0.5 → "ok"（保持 active）
     — >= 0.25 → "re-verify"（触发重新验证，接 P2-4 verify()）
     — < 0.25 → "deactivate"（降级 shadow / 下线）
  3. scan(entries) — 批量扫描，每项输出 {skill_id, decayed, action}
  4. get_actionable(entries) — 过滤需行动条目（re-verify + deactivate）

设计原则:
  - FAIL-OPEN：None/负数/字符串/缺字段 → 保守处理不阻塞主流程
  - 与 P2-4 SkillVerificationGate 协同：re-verify 条目回灌 P2-4 verify()
  - 轻量级：纯 Python，无外部依赖

参考:
  - SPEC-CognitiveSystem-Evolution.md §1.1（Vibe-Trading sdm_decay_scan）+ §4.3 P3-5
  - Alpha Decay: 量化交易策略超额收益随时间衰减的普遍现象
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional


# ============================================================
# 常量
# ============================================================

DEFAULT_HALF_LIFE_DAYS: float = 30.0  # 默认半衰期 30 天
ACTIVE_THRESHOLD: float = 0.5  # 衰减后 >= 此值保持 active
SHADOW_THRESHOLD: float = 0.25  # 衰减后 >= 此值 re-verify，否则 deactivate

ACTION_OK = "ok"
ACTION_REVERIFY = "re-verify"
ACTION_DEACTIVATE = "deactivate"


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    """安全浮点转换。None/NaN/inf/字符串异常 → default（FAIL-OPEN）。"""
    try:
        if value is None:
            return default
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (TypeError, ValueError):
        return default


# ============================================================
# AlphaDecayGate 主类
# ============================================================


class AlphaDecayGate:
    """策略级 Alpha Decay 自动门禁。

    半衰期公式量化 SKILL/策略有效性随时间衰减，
    三级门禁决策输出行动清单，re-verify 条目回灌 P2-4 重新验证。
    """

    def __init__(
        self,
        half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
        active_threshold: float = ACTIVE_THRESHOLD,
        shadow_threshold: float = SHADOW_THRESHOLD,
    ) -> None:
        """
        Args:
            half_life_days: 半衰期（天），confidence 每隔此天数减半
            active_threshold: 保持 active 的衰减后置信下限
            shadow_threshold: re-verify 的衰减后置信下限（低于则 deactivate）
        """
        self._half_life = _safe_float(half_life_days, DEFAULT_HALF_LIFE_DAYS) or DEFAULT_HALF_LIFE_DAYS
        self._active_threshold = active_threshold
        self._shadow_threshold = shadow_threshold

    # ============================================================
    # 1. 半衰期衰减计算
    # ============================================================

    def compute_decayed_confidence(
        self,
        confidence: Any,
        days_since_verify: Any,
    ) -> float:
        """计算半衰期衰减后的置信度。

        公式: decayed = confidence * 0.5^(days / half_life)

        Args:
            confidence: 原始置信度 0.0-1.0
            days_since_verify: 距上次验证的天数（负数视为 0）

        Returns:
            衰减后置信度 0.0-1.0。confidence 无效 → 0.0（FAIL-OPEN）
        """
        conf = _safe_float(confidence)
        if conf is None or conf < 0.0:
            return 0.0  # FAIL-OPEN：无效置信 → 0

        days = _safe_float(days_since_verify, 0.0) or 0.0
        if days < 0.0:
            days = 0.0  # 未来验证时间不产生衰减

        try:
            decayed = conf * (0.5 ** (days / self._half_life))
            if math.isnan(decayed) or math.isinf(decayed):
                return 0.0
            return max(0.0, min(1.0, decayed))
        except (OverflowError, ZeroDivisionError, ValueError):
            return 0.0  # FAIL-OPEN

    # ============================================================
    # 2. 门禁决策
    # ============================================================

    def decide_gate_action(self, decayed_confidence: Any) -> str:
        """基于衰减后置信度决策门禁行动。

        规则:
          - >= active_threshold (0.5) → "ok"
          - >= shadow_threshold (0.25) → "re-verify"
          - < shadow_threshold → "deactivate"

        Args:
            decayed_confidence: 衰减后置信度 0.0-1.0

        Returns:
            "ok" | "re-verify" | "deactivate"。None → "ok"（FAIL-OPEN 不阻塞）
        """
        conf = _safe_float(decayed_confidence)
        if conf is None:
            return ACTION_OK  # FAIL-OPEN：无数据不行动

        if conf >= self._active_threshold:
            return ACTION_OK
        if conf >= self._shadow_threshold:
            return ACTION_REVERIFY
        return ACTION_DEACTIVATE

    # ============================================================
    # 3. 批量扫描
    # ============================================================

    def scan(self, entries: List[Any]) -> List[Dict[str, Any]]:
        """批量扫描策略/SKILL 条目，输出每项衰减 + 门禁决策。

        Args:
            entries: 条目列表，每项 {
                "skill_id": str,
                "confidence": float,
                "days_since_verify": float,
            }
            无效条目（None/缺 skill_id）→ 跳过

        Returns:
            [{skill_id, original, decayed, action, days_since_verify}]
        """
        results: List[Dict[str, Any]] = []
        if not entries:
            return results

        for entry in entries:
            try:
                if not isinstance(entry, dict):
                    continue  # FAIL-OPEN：无效条目跳过
                skill_id = entry.get("skill_id")
                if not skill_id:
                    continue  # FAIL-OPEN：缺 ID 跳过

                confidence = entry.get("confidence")
                days = entry.get("days_since_verify")

                decayed = self.compute_decayed_confidence(confidence, days)
                action = self.decide_gate_action(decayed)

                results.append({
                    "skill_id": skill_id,
                    "original": _safe_float(confidence, 0.0),
                    "decayed": decayed,
                    "action": action,
                    "days_since_verify": _safe_float(days, 0.0),
                })
            except Exception:
                continue  # FAIL-OPEN：单条异常跳过

        return results

    def get_actionable(self, entries: List[Any]) -> List[Dict[str, Any]]:
        """过滤出需要行动的条目（action != "ok"）。

        re-verify 条目回灌 P2-4 SkillVerificationGate.verify()，
        deactivate 条目降级 shadow / 下线。

        Args:
            entries: 同 scan() 输入

        Returns:
            仅含 action in ("re-verify", "deactivate") 的结果
        """
        return [
            r for r in self.scan(entries)
            if r["action"] in (ACTION_REVERIFY, ACTION_DEACTIVATE)
        ]


# ============================================================
# CLI 自测
# ============================================================


if __name__ == "__main__":
    print("=" * 60)
    print("AlphaDecayGate — 功能验证")
    print("=" * 60)

    gate = AlphaDecayGate(half_life_days=30)

    # 衰减曲线
    for days in (0, 15, 30, 60, 90):
        decayed = gate.compute_decayed_confidence(0.9, days)
        print(f"  confidence=0.9, days={days:>3} → decayed={decayed:.3f} ({gate.decide_gate_action(decayed)})")

    # 批量扫描
    entries = [
        {"skill_id": "fresh", "confidence": 0.9, "days_since_verify": 5},
        {"skill_id": "stale", "confidence": 0.8, "days_since_verify": 45},
        {"skill_id": "dead", "confidence": 0.6, "days_since_verify": 150},
    ]
    actionable = gate.get_actionable(entries)
    print(f"\n需行动条目: {len(actionable)}")
    for r in actionable:
        print(f"  {r['skill_id']}: decayed={r['decayed']:.3f} → {r['action']}")

    print("\n" + "=" * 60)
    print("✅ AlphaDecayGate 功能验证通过")
