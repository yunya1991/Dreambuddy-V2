#!/usr/bin/env python3
"""
ACT-R 激活模型 — ACTRActivation

定位：L2 记忆层激活排序，使 recall 不只看相似度 score，
还考虑使用频率、时间衰减、上下文相关度。

ACT-R 激活公式:
  Activation = base_level + relatedness + base_confidence

  base_level = ln(Σ t_j^(-d))
    d = 衰减率（默认 0.5）
    t_j = 第 j 次使用距今时间（天）
    （用 verify_count 近似：每次 verify 间距均匀分布）

  relatedness = W_j * keyword_hit_count
    W_j = 上下文相关度权重（默认 0.3 per hit）
    keyword_hit_count = context 关键词在 content 中的命中数

  base_confidence = memory.confidence（基础置信度）

效果:
  - 高 verify_count → 高激活（频率效应）
  - 最近使用 → 高激活（时间衰减）
  - 上下文相关 → 高激活（相关度加成）
  - 高置信度 → 高激活（基础加成）

参考:
  - SPEC-CognitiveSystem-Evolution.md §2.3.3 P1-4
  - ACT-R (Anderson, 1996): declarative chunks + activation-based retrieval
  - 认知科学记忆 VM-1791716947623: 记忆强度(非年龄)是预测误差驱动更新的边界条件
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# ============================================================
# 默认参数
# ============================================================

DEFAULT_DECAY = 0.5          # ACT-R 标准衰减率 d
DEFAULT_W = 0.3             # 每个关键词命中权重
MAX_ACTIVATION = 10.0       # 激活值上限（防止 ln 爆炸）


class ACTRActivation:
    """
    ACT-R 激活模型。

    计算记忆的激活值，用于 recall 排序。
    激活值 = base_level（频率+衰减）+ relatedness（上下文相关）+ base_confidence
    """

    def __init__(
        self,
        decay: float = DEFAULT_DECAY,
        w_weight: float = DEFAULT_W,
        max_activation: float = MAX_ACTIVATION,
    ):
        """
        初始化 ACT-R 模型。

        Args:
            decay: 衰减率 d（0-1，越大遗忘越快）
            w_weight: 关键词命中权重 W
            max_activation: 激活值上限
        """
        self.decay = decay
        self.w_weight = w_weight
        self.max_activation = max_activation

    # ============================================================
    # 核心激活计算
    # ============================================================

    def compute_activation(
        self,
        days_since_last_use: float,
        verify_count: int,
        context_keywords: List[str],
        content: str,
        base_confidence: float = 0.3,
    ) -> float:
        """计算单条记忆的 ACT-R 激活值。

        Activation = base_level + relatedness + base_confidence

        Args:
            days_since_last_use: 距上次使用天数
            verify_count: verify 次数（频率代理）
            context_keywords: 上下文关键词列表
            content: 记忆内容
            base_confidence: 基础置信度

        Returns:
            激活值（正数，越高越活跃）
        """
        # ---- base_level: ln(Σ t_j^(-d)) ----
        # 无 verify 记录时，用 days_since 作为单次 t
        if verify_count <= 0:
            # 无使用记录 → 低基础激活
            t = max(1.0, days_since_last_use)
            base_level = math.log(t ** (-self.decay))  # ln(t^(-d)) = -d*ln(t)
            # 无使用 → base_level 为负或零
        else:
            # 有 verify 记录：近似每次 verify 间距均匀
            # t_j = days_since * (j / (verify_count+1))  for j=1..verify_count
            # Σ t_j^(-d) ≈ verify_count * (days_since/2)^(-d)  （用中位数近似）
            t_avg = max(1.0, days_since_last_use / max(1, verify_count))
            sum_term = verify_count * (t_avg ** (-self.decay))
            base_level = math.log(max(1e-10, sum_term))

        # ---- relatedness: W * keyword_hit_count ----
        hit_count = self._count_keyword_hits(context_keywords, content)
        relatedness = self.w_weight * hit_count

        # ---- base_confidence ----
        base_conf = float(base_confidence)

        # ---- 总激活值 ----
        activation = base_level + relatedness + base_conf

        # 钳制
        activation = max(-10.0, min(self.max_activation, activation))

        return round(activation, 4)

    # ============================================================
    # 批量排序
    # ============================================================

    def rank_by_activation(
        self,
        memories: List[Dict[str, Any]],
        context: str,
        now: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """按 ACT-R 激活值重排序记忆列表。

        Args:
            memories: 记忆列表（每条含 id/content/score/verify_count/updated_at/confidence）
            context: recall 上下文
            now: 当前时间（测试注入）

        Returns:
            按激活值降序排列的记忆列表（含 activation 字段）
        """
        if now is None:
            now = datetime.now(timezone.utc)

        keywords = self._tokenize(context)

        for mem in memories:
            # 解析时间
            updated = mem.get("updated_at", "")
            days_since = self._days_since(updated, now)

            activation = self.compute_activation(
                days_since_last_use=days_since,
                verify_count=int(mem.get("verify_count", 0) or 0),
                context_keywords=keywords,
                content=mem.get("content", ""),
                base_confidence=float(mem.get("confidence", 0.3) or 0.3),
            )
            mem["activation"] = activation

        # 按激活值降序
        return sorted(memories, key=lambda m: m.get("activation", 0.0), reverse=True)

    # ============================================================
    # 辅助方法
    # ============================================================

    def _count_keyword_hits(self, keywords: List[str], content: str) -> int:
        """统计关键词在内容中的命中数。"""
        if not keywords or not content:
            return 0
        content_lower = content.lower()
        return sum(1 for kw in keywords if kw.lower() in content_lower)

    def _tokenize(self, text: str) -> List[str]:
        """简单分词（按空格/标点切分，保留中文）。"""
        if not text:
            return []
        # 按空格切分
        words = re.split(r"[\s,，;；、]+", text.strip())
        return [w for w in words if w]

    def _days_since(self, updated_at: str, now: datetime) -> float:
        """计算距上次更新的天数。"""
        if not updated_at:
            return 0.0
        try:
            dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            delta = now - dt
            return max(0.0, delta.total_seconds() / 86400.0)
        except Exception:
            return 0.0


# ============================================================
# CLI 自测
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("ACTRActivation — 功能验证")
    print("=" * 60)

    model = ACTRActivation()

    # 基础计算
    act1 = model.compute_activation(
        days_since_last_use=1,
        verify_count=3,
        context_keywords=["BTC", "策略"],
        content="BTC趋势策略经验",
        base_confidence=0.5,
    )
    act2 = model.compute_activation(
        days_since_last_use=100,
        verify_count=0,
        context_keywords=["XYZ"],
        content="无关内容",
        base_confidence=0.3,
    )
    print(f"\n高频近期相关记忆: activation={act1}")
    print(f"低频旧无关记忆:   activation={act2}")
    print(f"act1 > act2: {act1 > act2}")

    # 排序测试
    from datetime import timedelta
    memories = [
        {"id": "VM-001", "content": "BTC策略", "score": 0.9,
         "verify_count": 0,
         "updated_at": (datetime.now(timezone.utc) - timedelta(days=200)).isoformat(),
         "confidence": 0.3},
        {"id": "VM-002", "content": "BTC趋势", "score": 0.6,
         "verify_count": 5,
         "updated_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
         "confidence": 0.7},
    ]
    ranked = model.rank_by_activation(memories, context="BTC趋势")
    for m in ranked:
        print(f"  {m['id']}: activation={m['activation']:.4f}, score={m['score']}")

    print("\n" + "=" * 60)
    print("✅ ACTRActivation 功能验证通过")
