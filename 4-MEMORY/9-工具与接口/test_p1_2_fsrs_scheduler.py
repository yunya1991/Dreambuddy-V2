"""P1-2 FSRS 遗忘调度器 TDD RED 测试

基于 FSRS (Free Spaced Repetition Scheduler) 幂律遗忘曲线，
对低质量低活跃记忆执行降权/审核队列调度。

幂律公式: R(t) = (1 + t/s)^(-d)
  t: 距上次 verify 的天数
  s: 稳定性（verify_count + quality_level 决定）
  d: 难度系数（quality 越低 d 越大）

B2 安全网（评审修复）:
  - 90 天 grace period: 不降权
  - 仅降权不归档（不删除/移走）
  - 人工审核闸门（生成 review_queue，不自动归档）

RED 契约:
  1. fsrs_forgetting_scheduler 模块不存在 → ImportError
  2. FSRSForgettingScheduler 类不存在 → AttributeError
  3. compute_retrievability() 不存在
  4. schedule() 不存在
  5. CognitiveLoopEntry.schedule_forgetting() 不存在

参考: SPEC-CognitiveSystem-Evolution.md §2.3.3 P1-2 + 评审修复 B2
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))


# ─────────────────────────────── FSRSForgettingScheduler ───────────────────────────────


class TestFSRSForgettingScheduler:
    """FSRS 幂律遗忘调度器。"""

    def test_import_fsrs_scheduler(self):
        """RED: fsrs_forgetting_scheduler 模块可导入。"""
        from fsrs_forgetting_scheduler import FSRSForgettingScheduler  # noqa: F401

    def test_compute_retrievability_fresh_memory(self, tmp_path):
        """RED: 刚 verify 的记忆 R 接近 1.0（无遗忘）。"""
        from fsrs_forgetting_scheduler import FSRSForgettingScheduler

        scheduler = FSRSForgettingScheduler()
        # 1 天前 verify
        last_verify = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        r = scheduler.compute_retrievability(
            days_since_verify=1,
            verify_count=2,
            quality_level="B",
        )
        # 新鲜记忆 R 应 > 0.7
        assert r > 0.7, f"新鲜记忆 R 应 > 0.7, got {r}"

    def test_compute_retrievability_old_c_memory(self, tmp_path):
        """RED: 100天未 verify 的 C 级记忆 R 应低。"""
        from fsrs_forgetting_scheduler import FSRSForgettingScheduler

        scheduler = FSRSForgettingScheduler()
        r = scheduler.compute_retrievability(
            days_since_verify=100,
            verify_count=0,
            quality_level="C",
        )
        # 100天未 verify 的 C 级 R 应 < 0.4
        assert r < 0.4, f"100天 C 级 R 应 < 0.4, got {r}"

    def test_compute_retrievability_stable_a_memory(self, tmp_path):
        """RED: A 级 + 多次 verify 的记忆即使长期未 verify 也应稳定。"""
        from fsrs_forgetting_scheduler import FSRSForgettingScheduler

        scheduler = FSRSForgettingScheduler()
        r = scheduler.compute_retrievability(
            days_since_verify=200,
            verify_count=10,
            quality_level="A",
        )
        # A 级 + verify 10次即使 200 天也应 > 0.4
        assert r > 0.4, f"A 级稳定记忆 200天 R 应 > 0.4, got {r}"

    def test_grace_period_skips_recent_memories(self, tmp_path):
        """RED: B2 安全网 — 90 天 grace period 内不降权。"""
        from fsrs_forgetting_scheduler import FSRSForgettingScheduler

        scheduler = FSRSForgettingScheduler(grace_period_days=90)
        memories = [
            {
                "id": "VM-001",
                "quality_level": "C",
                "verify_count": 0,
                "updated_at": (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(),
                "confidence": 0.3,
            },
        ]
        report = scheduler.schedule(memories, dry_run=True)
        # 30 天 < 90 天 grace period → 不降权
        assert report["demoted_count"] == 0
        assert len(report["review_queue"]) == 0

    def test_schedule_demotes_old_c_memories(self, tmp_path):
        """RED: 120天未 verify 的 C 级记忆应降权（但加入审核队列，不归档）。"""
        from fsrs_forgetting_scheduler import FSRSForgettingScheduler

        scheduler = FSRSForgettingScheduler(grace_period_days=90)
        memories = [
            {
                "id": "VM-001",
                "content": "老旧 C 级经验",
                "quality_level": "C",
                "verify_count": 0,
                "updated_at": (datetime.now(timezone.utc) - timedelta(days=120)).isoformat(),
                "confidence": 0.3,
            },
        ]
        report = scheduler.schedule(memories, dry_run=True)
        # 应降权
        assert report["demoted_count"] >= 1
        # 应加入审核队列
        assert len(report["review_queue"]) >= 1
        # 不应归档（B2 安全网）
        assert report["archived_count"] == 0

    def test_schedule_does_not_demote_b_or_above(self, tmp_path):
        """RED: B 级及以上记忆不降权（只对 C/D 级遗忘调度）。"""
        from fsrs_forgetting_scheduler import FSRSForgettingScheduler

        scheduler = FSRSForgettingScheduler(grace_period_days=90)
        memories = [
            {
                "id": "VM-001",
                "content": "B 级经验",
                "quality_level": "B",
                "verify_count": 1,
                "updated_at": (datetime.now(timezone.utc) - timedelta(days=200)).isoformat(),
                "confidence": 0.5,
            },
        ]
        report = scheduler.schedule(memories, dry_run=True)
        # B 级不降权
        assert report["demoted_count"] == 0

    def test_schedule_review_queue_has_details(self, tmp_path):
        """RED: review_queue 应含 memory_id + retrievability + reason。"""
        from fsrs_forgetting_scheduler import FSRSForgettingScheduler

        scheduler = FSRSForgettingScheduler(grace_period_days=90)
        memories = [
            {
                "id": "VM-001",
                "content": "老旧记忆",
                "quality_level": "C",
                "verify_count": 0,
                "updated_at": (datetime.now(timezone.utc) - timedelta(days=150)).isoformat(),
                "confidence": 0.3,
            },
        ]
        report = scheduler.schedule(memories, dry_run=True)
        if report["review_queue"]:
            item = report["review_queue"][0]
            assert "memory_id" in item
            assert "retrievability" in item
            assert "reason" in item

    def test_dry_run_does_not_modify(self, tmp_path):
        """RED: dry_run=True 不修改记忆。"""
        from fsrs_forgetting_scheduler import FSRSForgettingScheduler

        scheduler = FSRSForgettingScheduler(grace_period_days=90)
        original_confidence = 0.3
        memories = [
            {
                "id": "VM-001",
                "content": "老旧记忆",
                "quality_level": "C",
                "verify_count": 0,
                "updated_at": (datetime.now(timezone.utc) - timedelta(days=150)).isoformat(),
                "confidence": original_confidence,
            },
        ]
        scheduler.schedule(memories, dry_run=True)
        # dry_run 不修改
        assert memories[0]["confidence"] == original_confidence

    def test_apply_demotion_decreases_confidence(self, tmp_path):
        """RED: apply（非 dry_run）应降低 confidence。"""
        from fsrs_forgetting_scheduler import FSRSForgettingScheduler

        scheduler = FSRSForgettingScheduler(grace_period_days=90)
        original_confidence = 0.3
        memories = [
            {
                "id": "VM-001",
                "content": "老旧记忆",
                "quality_level": "C",
                "verify_count": 0,
                "updated_at": (datetime.now(timezone.utc) - timedelta(days=150)).isoformat(),
                "confidence": original_confidence,
            },
        ]
        scheduler.schedule(memories, dry_run=False)
        # 应降权（confidence 减小）
        assert memories[0]["confidence"] < original_confidence


# ─────────────────────────────── CognitiveLoopEntry 集成 ───────────────────────────────


class TestCognitiveLoopEntryFSRS:
    """CognitiveLoopEntry FSRS 集成。"""

    def test_schedule_forgetting_method_exists(self):
        """RED: CognitiveLoopEntry 应有 schedule_forgetting() 方法。"""
        from cognitive_loop_entry import CognitiveLoopEntry
        assert hasattr(CognitiveLoopEntry, "schedule_forgetting")
