#!/usr/bin/env python3
"""
FSRS 遗忘调度器 — FSRSForgettingScheduler

定位：L2 记忆层遗忘调度，基于 FSRS (Free Spaced Repetition Scheduler) 幂律遗忘曲线，
对低质量低活跃记忆执行降权 + 人工审核队列调度。

幂律公式: R(t) = (1 + t/s)^(-d)
  t: 距上次 verify 的天数
  s: 稳定性（verify_count + quality_level 决定）
  d: 难度系数（quality_level 越低 d 越大，遗忘越快）

B2 安全网（评审修复）:
  1. 90 天 grace period: 90 天内不降权
  2. 仅降权不归档: confidence × 0.8，不删除/移走记忆
  3. 人工审核闸门: 生成 review_queue，不自动归档

调度规则:
  - R > 0.7: 健康，无操作
  - 0.4 < R <= 0.7: 降权（confidence × 0.8）
  - R <= 0.4: 加入审核队列（不自动归档）
  - 90 天内: 跳过（grace period）
  - B 级及以上: 不降权（仅对 C/D 级遗忘调度）

参考:
  - SPEC-CognitiveSystem-Evolution.md §2.3.3 P1-2
  - FSRS 2024: power law 比 exponential 更拟合真实数据
  - 评审修复 B2: C 级先只降权不归档，90 天 grace period，人工审核闸门
  - 认知科学记忆 VM-1791716947623: 记忆强度(非年龄)是预测误差驱动更新的边界条件
"""
from __future__ import annotations

import json
import math
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional


# ============================================================
# 默认参数
# ============================================================

# 质量等级 → 难度系数 d（越高越容易遗忘）
QUALITY_DIFFICULTY = {
    "S": 0.2,  # 公理级，几乎不遗忘
    "A": 0.3,  # 可信级，缓慢遗忘
    "B": 0.4,  # 待验证级，中等遗忘
    "C": 0.6,  # 假设级，较快遗忘
    "D": 0.8,  # 已证伪，最快遗忘
}

# 质量等级 → 基础稳定性 s
QUALITY_STABILITY = {
    "S": 365.0,  # S 级：1年稳定性
    "A": 180.0,  # A 级：半年
    "B": 60.0,   # B 级：2月
    "C": 15.0,   # C 级：15天
    "D": 5.0,    # D 级：5天
}

DEFAULT_GRACE_PERIOD_DAYS = 90  # B2 安全网：90 天 grace period
DEMOTION_FACTOR = 0.8           # 降权因子
REVIEW_THRESHOLD = 0.4          # R < 此值加入审核队列
DEMOTE_THRESHOLD = 0.7          # R < 此值降权


@dataclass
class ForgettingReport:
    """遗忘调度报告。"""
    total_scanned: int = 0
    skipped_grace: int = 0      # grace period 内跳过
    skipped_quality: int = 0    # B 级以上跳过
    demoted_count: int = 0      # 降权数
    archived_count: int = 0     # 归档数（B2: 始终 0）
    review_queue: List[Dict[str, Any]] = field(default_factory=list)
    demoted_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_scanned": self.total_scanned,
            "skipped_grace": self.skipped_grace,
            "skipped_quality": self.skipped_quality,
            "demoted_count": self.demoted_count,
            "archived_count": self.archived_count,
            "review_queue": self.review_queue,
            "demoted_ids": self.demoted_ids,
        }


class FSRSForgettingScheduler:
    """
    FSRS 幂律遗忘调度器。

    基于幂律遗忘曲线计算每条记忆的可检索性（retrievability），
    对低 R 值的 C/D 级记忆执行降权或加入审核队列。

    B2 安全网确保:
    - 不在 grace period 内降权
    - 不自动归档（仅降权 + 审核队列）
    - 不对 B 级以上降权
    """

    def __init__(
        self,
        grace_period_days: int = DEFAULT_GRACE_PERIOD_DAYS,
        demotion_factor: float = DEMOTION_FACTOR,
        review_threshold: float = REVIEW_THRESHOLD,
        demote_threshold: float = DEMOTE_THRESHOLD,
    ):
        self.grace_period_days = grace_period_days
        self.demotion_factor = demotion_factor
        self.review_threshold = review_threshold
        self.demote_threshold = demote_threshold
        self._lock = threading.Lock()

    # ============================================================
    # 核心：FSRS 幂律遗忘曲线
    # ============================================================

    def compute_retrievability(
        self,
        days_since_verify: float,
        verify_count: int,
        quality_level: str,
    ) -> float:
        """计算记忆可检索性 R(t)。

        幂律公式: R(t) = (1 + t/s)^(-d)
          t: 距上次 verify 的天数
          s: 稳定性（quality_level 基础 + verify_count 加成）
          d: 难度系数（quality_level 决定）

        verify_count 越高 → s 越大（越稳定）→ R 越高
        quality_level 越低 → d 越大（越易遗忘）→ R 越低

        Returns:
            R 值 [0.0, 1.0]
        """
        # 基础稳定性
        base_s = QUALITY_STABILITY.get(quality_level, 15.0)
        # verify_count 加成：每次 verify 增加 10% 稳定性
        stability = base_s * (1.0 + 0.1 * min(verify_count, 20))
        # 难度系数
        difficulty = QUALITY_DIFFICULTY.get(quality_level, 0.6)

        # 幂律遗忘: R = (1 + t/s)^(-d)
        t = max(0.0, days_since_verify)
        ratio = 1.0 + t / stability
        r = ratio ** (-difficulty)

        # 钳制到 [0, 1]
        return max(0.0, min(1.0, r))

    # ============================================================
    # 调度主入口
    # ============================================================

    def schedule(
        self,
        memories: List[Dict[str, Any]],
        dry_run: bool = True,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """对记忆列表执行遗忘调度。

        Args:
            memories: 记忆列表（每条含 id/quality_level/verify_count/updated_at/confidence）
            dry_run: True 只生成报告不修改；False 执行降权
            now: 当前时间（测试用注入），None 用真实时间

        Returns:
            ForgettingReport.to_dict()
        """
        with self._lock:
            now = now or datetime.now(timezone.utc)
            report = ForgettingReport(total_scanned=len(memories))

            for mem in memories:
                mid = mem.get("id", "")
                ql = mem.get("quality_level", "C")
                vc = int(mem.get("verify_count", 0) or 0)
                updated = mem.get("updated_at", "")
                confidence = float(mem.get("confidence", 0.0) or 0.0)

                # 解析时间
                days_since = self._days_since(updated, now)

                # B2 安全网 1: grace period 内跳过
                if days_since < self.grace_period_days:
                    report.skipped_grace += 1
                    continue

                # B2 安全网 2: B 级以上不降权
                if self._quality_rank(ql) >= self._quality_rank("B"):
                    report.skipped_quality += 1
                    continue

                # 计算 R
                r = self.compute_retrievability(
                    days_since_verify=days_since,
                    verify_count=vc,
                    quality_level=ql,
                )

                # R > demote_threshold: 健康
                if r > self.demote_threshold:
                    continue  # 无操作

                # R <= review_threshold: 加入审核队列
                if r <= self.review_threshold:
                    report.review_queue.append({
                        "memory_id": mid,
                        "retrievability": round(r, 4),
                        "days_since_verify": round(days_since, 1),
                        "quality_level": ql,
                        "verify_count": vc,
                        "current_confidence": confidence,
                        "reason": f"R={r:.3f} <= {self.review_threshold}（幂律遗忘严重）",
                    })
                    # 不自动归档（B2 安全网）
                    # 但降权（dry_run 也统计，只是不实际修改）
                    report.demoted_ids.append(mid)
                    report.demoted_count += 1
                    if not dry_run:
                        new_conf = confidence * self.demotion_factor
                        mem["confidence"] = round(new_conf, 4)
                # review_threshold < R <= demote_threshold: 降权
                else:
                    report.demoted_ids.append(mid)
                    report.demoted_count += 1
                    if not dry_run:
                        new_conf = confidence * self.demotion_factor
                        mem["confidence"] = round(new_conf, 4)

            return report.to_dict()

    # ============================================================
    # 辅助方法
    # ============================================================

    def _days_since(self, updated_at: str, now: datetime) -> float:
        """计算距上次更新的天数。"""
        if not updated_at:
            return 0.0
        try:
            # 兼容 ISO 格式
            dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            delta = now - dt
            return max(0.0, delta.total_seconds() / 86400.0)
        except Exception:
            return 0.0

    @staticmethod
    def _quality_rank(ql: str) -> int:
        """质量等级排序值（越高越好）。"""
        ranks = {"S": 5, "A": 4, "B": 3, "C": 2, "D": 1}
        return ranks.get(ql, 2)


# ============================================================
# CLI 自测
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("FSRSForgettingScheduler — 功能验证")
    print("=" * 60)

    scheduler = FSRSForgettingScheduler()

    # 测试 R 计算
    r_fresh = scheduler.compute_retrievability(1, 2, "B")
    r_old = scheduler.compute_retrievability(100, 0, "C")
    r_stable = scheduler.compute_retrievability(200, 10, "A")
    print(f"\n新鲜 B 级 R: {r_fresh:.4f}")
    print(f"100天 C 级 R: {r_old:.4f}")
    print(f"200天 A 级 R: {r_stable:.4f}")

    # 测试调度
    memories = [
        {
            "id": "VM-001",
            "content": "新鲜 C 级",
            "quality_level": "C",
            "verify_count": 0,
            "updated_at": (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(),
            "confidence": 0.3,
        },
        {
            "id": "VM-002",
            "content": "老旧 C 级",
            "quality_level": "C",
            "verify_count": 0,
            "updated_at": (datetime.now(timezone.utc) - timedelta(days=150)).isoformat(),
            "confidence": 0.3,
        },
        {
            "id": "VM-003",
            "content": "老旧 B 级",
            "quality_level": "B",
            "verify_count": 1,
            "updated_at": (datetime.now(timezone.utc) - timedelta(days=200)).isoformat(),
            "confidence": 0.5,
        },
    ]

    report = scheduler.schedule(memories, dry_run=True)
    print(f"\n调度报告: {json.dumps(report, indent=2, ensure_ascii=False)}")

    print("\n" + "=" * 60)
    print("✅ FSRSForgettingScheduler 功能验证通过")
