#!/usr/bin/env python3
"""Transactive Memory 索引 — TransactiveMemory

定位：L4 元认知层交互记忆索引，借鉴 arXiv:2606.19911 交互记忆理论
（Wegner: 团队认知分工 —— "谁擅长什么"的共享目录）。
现状痛点：247 SKILL 无"谁擅长什么"的 agent profile —— 任务路由时
不清楚哪个 agent/SKILL 擅长哪个领域，只能全量匹配。

核心机制（谁擅长什么 → 精准路由）:
  1. register_expert(domain, agent_id, confidence) — 注册 agent profile
     （agent = SKILL/子代理/子系统）
  2. who_knows(domain) — 查询某领域专家列表，按置信度降序（路由取最优）
  3. record_outcome(domain, agent_id, success) — 执行结果强化：
     成功 → confidence += STEP（上限 1.0）
     失败 → confidence -= STEP（下限 0.0）
     （强化学习式 profile 随实战更新）
  4. get_profile(agent_id) — 反查 agent 擅长领域
  5. stats() — 索引统计（domains/agents/entries）

设计原则:
  - FAIL-OPEN：无效注册/未知 agent → 静默忽略，绝不阻塞
  - 线程安全：所有操作加锁
  - 与 P2-4 协同：SKILL 入库（active）时自动建 profile，outcome 回灌强化
  - 轻量级：纯 Python，无外部依赖

参考:
  - SPEC-CognitiveSystem-Evolution.md §1.3 + §4.3 P3-7
  - arXiv:2606.19911 (Transactive Memory)
"""
from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional


# ============================================================
# 常量
# ============================================================

DEFAULT_CONFIDENCE: float = 0.5  # 注册默认置信度
REINFORCE_STEP: float = 0.1  # 每次成败的置信度调整步长
CONFIDENCE_MAX: float = 1.0
CONFIDENCE_MIN: float = 0.0


# ============================================================
# TransactiveMemory 主类
# ============================================================


class TransactiveMemory:
    """交互记忆索引："谁擅长什么"的共享 agent profile 目录。

    注册（register_expert）→ 路由（who_knows）→ 强化（record_outcome）
    形成交互记忆闭环，让任务精准路由到最擅长的 agent。
    """

    def __init__(self, reinforce_step: float = REINFORCE_STEP) -> None:
        """
        Args:
            reinforce_step: 成败强化的置信度调整步长
        """
        self._reinforce_step = reinforce_step
        # 结构: {domain: {agent_id: confidence}}
        self._domain_experts: Dict[str, Dict[str, float]] = {}
        self._lock = threading.Lock()

    # ============================================================
    # 1. 注册 agent profile
    # ============================================================

    def register_expert(
        self,
        domain: Any,
        agent_id: Any,
        confidence: float = DEFAULT_CONFIDENCE,
    ) -> bool:
        """注册"agent 擅长 domain"的 profile 条目。

        Args:
            domain: 领域标签（如 "技术分析"/"宏观"/"链上分析"）
            agent_id: agent/SKILL/子系统标识
            confidence: 初始置信度 0.0-1.0

        Returns:
            True=注册成功，False=无效输入被忽略（FAIL-OPEN）
        """
        if not domain or not agent_id:
            return False  # FAIL-OPEN：无效输入忽略

        try:
            conf = float(confidence)
            conf = max(CONFIDENCE_MIN, min(CONFIDENCE_MAX, conf))
        except (TypeError, ValueError):
            conf = DEFAULT_CONFIDENCE

        with self._lock:
            self._domain_experts.setdefault(str(domain), {})[str(agent_id)] = conf
        return True

    # ============================================================
    # 2. 路由查询：谁擅长 domain
    # ============================================================

    def who_knows(self, domain: Any, limit: int = 10) -> List[Dict[str, Any]]:
        """查询某领域专家列表，按置信度降序。

        Args:
            domain: 领域标签
            limit: 返回条数上限

        Returns:
            [{"domain", "agent_id", "confidence"}]，未注册领域 → 空列表
        """
        with self._lock:
            experts = self._domain_experts.get(str(domain) if domain else "", {})
            if not experts:
                return []
            ranked = sorted(
                experts.items(), key=lambda kv: kv[1], reverse=True
            )[:limit]
            return [
                {"domain": str(domain), "agent_id": aid, "confidence": conf}
                for aid, conf in ranked
            ]

    # ============================================================
    # 3. 执行结果强化（profile 随实战更新）
    # ============================================================

    def record_outcome(
        self,
        domain: Any,
        agent_id: Any,
        success: Optional[bool],
    ) -> bool:
        """记录执行结果，强化/弱化该 agent 在该领域的置信度。

        规则:
          - success=True → confidence += step（上限 1.0）
          - success=False → confidence -= step（下限 0.0）
          - 未注册条目 → 忽略（FAIL-OPEN）

        Args:
            domain: 领域标签
            agent_id: agent 标识
            success: 执行成败

        Returns:
            True=更新成功，False=条目不存在被忽略
        """
        if not domain or not agent_id or success is None:
            return False  # FAIL-OPEN

        with self._lock:
            experts = self._domain_experts.get(str(domain), {})
            if str(agent_id) not in experts:
                return False  # FAIL-OPEN：未知条目忽略

            conf = experts[str(agent_id)]
            conf = conf + self._reinforce_step if success else conf - self._reinforce_step
            experts[str(agent_id)] = max(CONFIDENCE_MIN, min(CONFIDENCE_MAX, conf))
        return True

    # ============================================================
    # 4. 反查 agent profile
    # ============================================================

    def get_profile(self, agent_id: Any) -> List[Dict[str, Any]]:
        """反查 agent 擅长的所有领域。

        Args:
            agent_id: agent 标识

        Returns:
            [{"domain", "agent_id", "confidence"}]（按置信度降序），未知 → []
        """
        if not agent_id:
            return []

        with self._lock:
            profile = []
            for domain, experts in self._domain_experts.items():
                conf = experts.get(str(agent_id))
                if conf is not None:
                    profile.append({
                        "domain": domain,
                        "agent_id": str(agent_id),
                        "confidence": conf,
                    })
            profile.sort(key=lambda p: p["confidence"], reverse=True)
            return profile

    # ============================================================
    # 5. 统计
    # ============================================================

    def stats(self) -> Dict[str, Any]:
        """索引统计。"""
        with self._lock:
            agents = set()
            entries = 0
            for experts in self._domain_experts.values():
                agents.update(experts.keys())
                entries += len(experts)
            return {
                "domains": len(self._domain_experts),
                "agents": len(agents),
                "expertise_entries": entries,
            }

    def clear(self) -> None:
        """清空索引。"""
        with self._lock:
            self._domain_experts.clear()


# ============================================================
# CLI 自测
# ============================================================


if __name__ == "__main__":
    print("=" * 60)
    print("TransactiveMemory — 功能验证")
    print("=" * 60)

    tm = TransactiveMemory()
    tm.register_expert("宏观", "macro-skill", confidence=0.6)
    tm.register_expert("宏观", "fed-skill", confidence=0.95)

    print(f"\n谁擅长宏观: {tm.who_knows('宏观')}")

    tm.record_outcome("宏观", "macro-skill", success=True)
    print(f"macro-skill 成功后: {tm.who_knows('宏观')[1]}")

    print(f"fed-skill profile: {tm.get_profile('fed-skill')}")
    print(f"stats: {tm.stats()}")

    print("\n" + "=" * 60)
    print("✅ TransactiveMemory 功能验证通过")
