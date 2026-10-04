"""N-P0a VerificationObserver 观测层测试（RED 阶段）。

验收标准：
- 观测层独立模块，默认 OFF，开启后旁路记录 recall/verify 事件
- 不修改 recall()/verify() 的返回值（零行为变更）
- recall→verify 转化率可计算
- oracle gap 可估计
- gold set 可管理
- 观测异常 FAIL-OPEN 静默
"""
import json
import os
import tempfile
import time
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# RED 起手：模块尚未创建，应抛 ModuleNotFoundError
# ---------------------------------------------------------------------------

def test_module_importable():
    from verification_observer import VerificationObserver  # noqa: F401
    from verification_observer import RecallEvent, VerifyEvent, GoldSetManager  # noqa: F401


# ---------------------------------------------------------------------------
# 事件数据类
# ---------------------------------------------------------------------------

def test_recall_event_fields():
    from verification_observer import RecallEvent
    ev = RecallEvent(
        session_id="s1",
        context="测试问题",
        top_k=5,
        returned_ids=["VM-1", "VM-2"],
        returned_scores=[0.8, 0.6],
        ts=1000.0,
    )
    assert ev.session_id == "s1"
    assert ev.context == "测试问题"
    assert ev.top_k == 5
    assert ev.returned_ids == ["VM-1", "VM-2"]
    assert ev.returned_scores == [0.8, 0.6]
    assert ev.ts == 1000.0


def test_verify_event_fields():
    from verification_observer import VerifyEvent
    ev = VerifyEvent(
        session_id="s1",
        memory_id="VM-1",
        success=True,
        old_confidence=0.3,
        new_confidence=0.4,
        old_quality="C",
        new_quality="B",
        ts=1001.0,
    )
    assert ev.memory_id == "VM-1"
    assert ev.success is True
    assert ev.old_confidence == 0.3
    assert ev.new_confidence == 0.4
    assert ev.old_quality == "C"
    assert ev.new_quality == "B"


# ---------------------------------------------------------------------------
# VerificationObserver 核心
# ---------------------------------------------------------------------------

def test_observer_default_off():
    from verification_observer import VerificationObserver
    obs = VerificationObserver(storage_path=tempfile.mkdtemp())
    assert obs.is_enabled() is False


def test_observer_enable_disable():
    from verification_observer import VerificationObserver
    obs = VerificationObserver(storage_path=tempfile.mkdtemp())
    obs.enable()
    assert obs.is_enabled() is True
    obs.disable()
    assert obs.is_enabled() is False


def test_record_recall_when_disabled_is_noop():
    from verification_observer import VerificationObserver
    obs = VerificationObserver(storage_path=tempfile.mkdtemp())
    # disabled → 不写入，不抛异常
    obs.record_recall(session_id="s1", context="q", top_k=5,
                      returned_ids=[], returned_scores=[])
    assert obs.get_recall_count() == 0


def test_record_recall_when_enabled():
    from verification_observer import VerificationObserver
    obs = VerificationObserver(storage_path=tempfile.mkdtemp())
    obs.enable()
    obs.record_recall(session_id="s1", context="q", top_k=5,
                      returned_ids=["VM-1", "VM-2"],
                      returned_scores=[0.8, 0.6])
    assert obs.get_recall_count() == 1
    events = obs.get_recall_events()
    assert len(events) == 1
    assert events[0].returned_ids == ["VM-1", "VM-2"]


def test_record_verify_when_enabled():
    from verification_observer import VerificationObserver
    obs = VerificationObserver(storage_path=tempfile.mkdtemp())
    obs.enable()
    obs.record_verify(session_id="s1", memory_id="VM-1", success=True,
                      old_confidence=0.3, new_confidence=0.4,
                      old_quality="C", new_quality="B")
    assert obs.get_verify_count() == 1


def test_record_recall_fail_open_on_exception(monkeypatch):
    from verification_observer import VerificationObserver
    obs = VerificationObserver(storage_path=tempfile.mkdtemp())
    obs.enable()
    # 注入异常：存储写入失败
    def boom(*a, **kw):
        raise RuntimeError("disk full")
    monkeypatch.setattr(obs, "_persist_recall", boom)
    # FAIL-OPEN：不抛异常；事件已在内存观测到，持久化失败静默
    obs.record_recall(session_id="s1", context="q", top_k=5,
                      returned_ids=["VM-1"], returned_scores=[0.5])
    assert obs.get_recall_count() == 1  # 内存中仍计数，持久化失败静默


# ---------------------------------------------------------------------------
# 转化率与 oracle gap
# ---------------------------------------------------------------------------

def test_conversion_rate_no_verify():
    from verification_observer import VerificationObserver
    obs = VerificationObserver(storage_path=tempfile.mkdtemp())
    obs.enable()
    obs.record_recall(session_id="s1", context="q", top_k=5,
                      returned_ids=["VM-1"], returned_scores=[0.5])
    # 没有 verify 事件 → 转化率 0.0
    assert obs.conversion_rate() == 0.0


def test_conversion_rate_with_verify():
    from verification_observer import VerificationObserver
    obs = VerificationObserver(storage_path=tempfile.mkdtemp())
    obs.enable()
    # 2 次 recall 返回 3 条记忆
    obs.record_recall(session_id="s1", context="q1", top_k=5,
                      returned_ids=["VM-1", "VM-2"],
                      returned_scores=[0.8, 0.6])
    obs.record_recall(session_id="s2", context="q2", top_k=5,
                      returned_ids=["VM-3"], returned_scores=[0.7])
    # 1 次成功 verify
    obs.record_verify(session_id="s1", memory_id="VM-1", success=True,
                      old_confidence=0.3, new_confidence=0.4,
                      old_quality="C", new_quality="B")
    # 转化率 = 成功 verify 数 / recall 返回总数 = 1/3
    assert abs(obs.conversion_rate() - 1.0 / 3.0) < 1e-9


def test_oracle_gap_estimation():
    """oracle gap = 理想最优质量 - 实际 top-k 平均质量。"""
    from verification_observer import VerificationObserver, quality_to_numeric
    obs = VerificationObserver(storage_path=tempfile.mkdtemp())
    obs.enable()
    # top-3: A(0.8), B(0.5), C(0.3) → 平均 0.533
    obs.record_recall(session_id="s1", context="q", top_k=3,
                      returned_ids=["VM-1", "VM-2", "VM-3"],
                      returned_scores=[0.9, 0.7, 0.5],
                      returned_qualities=["A", "B", "C"])
    gap = obs.oracle_gap()
    # 理想最优 = 1.0（S 级），实际平均 = (0.8+0.5+0.3)/3 = 0.533
    expected = 1.0 - (0.8 + 0.5 + 0.3) / 3.0
    assert abs(gap - expected) < 1e-9


def test_quality_to_numeric():
    from verification_observer import quality_to_numeric
    assert quality_to_numeric("S") == 1.0
    assert quality_to_numeric("A") == 0.8
    assert quality_to_numeric("B") == 0.5
    assert quality_to_numeric("C") == 0.3
    assert quality_to_numeric("D") == 0.1
    assert quality_to_numeric("unknown") == 0.0  # FAIL-OPEN 默认


# ---------------------------------------------------------------------------
# GoldSetManager
# ---------------------------------------------------------------------------

def test_gold_set_add_and_get():
    from verification_observer import GoldSetManager
    gs = GoldSetManager(storage_path=tempfile.mkdtemp())
    gs.add(memory_id="VM-1", content="测试经验",
           gold_quality="B", gold_confidence=0.5, tags=["test"])
    entry = gs.get("VM-1")
    assert entry is not None
    assert entry.memory_id == "VM-1"
    assert entry.gold_quality == "B"
    assert entry.gold_confidence == 0.5


def test_gold_set_count_and_list():
    from verification_observer import GoldSetManager
    gs = GoldSetManager(storage_path=tempfile.mkdtemp())
    gs.add(memory_id="VM-1", content="a", gold_quality="B",
           gold_confidence=0.5, tags=["t1"])
    gs.add(memory_id="VM-2", content="b", gold_quality="A",
           gold_confidence=0.8, tags=["t2"])
    assert gs.count() == 2
    ids = gs.list_ids()
    assert set(ids) == {"VM-1", "VM-2"}


def test_gold_set_cohen_kappa():
    """双人标注一致性 Cohen's kappa。"""
    from verification_observer import GoldSetManager
    gs = GoldSetManager(storage_path=tempfile.mkdtemp())
    # 两条标注一致
    gs.add(memory_id="VM-1", content="a", gold_quality="B",
           gold_confidence=0.5, tags=[], annotator_quality="B")
    gs.add(memory_id="VM-2", content="b", gold_quality="A",
           gold_confidence=0.8, tags=[], annotator_quality="A")
    kappa = gs.cohen_kappa()
    assert kappa == 1.0  # 完全一致


def test_gold_set_cohen_kappa_disagreement():
    from verification_observer import GoldSetManager
    gs = GoldSetManager(storage_path=tempfile.mkdtemp())
    gs.add(memory_id="VM-1", content="a", gold_quality="B",
           gold_confidence=0.5, tags=[], annotator_quality="A")  # 不一致
    gs.add(memory_id="VM-2", content="b", gold_quality="A",
           gold_confidence=0.8, tags=[], annotator_quality="A")  # 一致
    kappa = gs.cohen_kappa()
    assert kappa < 1.0
    assert kappa >= 0.0


# ---------------------------------------------------------------------------
# 持久化
# ---------------------------------------------------------------------------

def test_observer_persistence_across_instances():
    from verification_observer import VerificationObserver
    tmpdir = tempfile.mkdtemp()
    obs1 = VerificationObserver(storage_path=tmpdir)
    obs1.enable()
    obs1.record_recall(session_id="s1", context="q", top_k=5,
                       returned_ids=["VM-1"], returned_scores=[0.5])
    # 新实例读取同一存储
    obs2 = VerificationObserver(storage_path=tmpdir)
    obs2.enable()
    assert obs2.get_recall_count() == 1


def test_gold_set_persistence():
    from verification_observer import GoldSetManager
    tmpdir = tempfile.mkdtemp()
    gs1 = GoldSetManager(storage_path=tmpdir)
    gs1.add(memory_id="VM-1", content="a", gold_quality="B",
            gold_confidence=0.5, tags=["t"])
    gs2 = GoldSetManager(storage_path=tmpdir)
    assert gs2.count() == 1
    assert gs2.get("VM-1").gold_quality == "B"


# ---------------------------------------------------------------------------
# 指标报告
# ---------------------------------------------------------------------------

def test_metrics_report():
    from verification_observer import VerificationObserver
    obs = VerificationObserver(storage_path=tempfile.mkdtemp())
    obs.enable()
    obs.record_recall(session_id="s1", context="q", top_k=3,
                      returned_ids=["VM-1", "VM-2"],
                      returned_scores=[0.9, 0.7],
                      returned_qualities=["A", "B"])
    obs.record_verify(session_id="s1", memory_id="VM-1", success=True,
                      old_confidence=0.3, new_confidence=0.4,
                      old_quality="C", new_quality="B")
    report = obs.metrics_report()
    assert report["recall_count"] == 1
    assert report["verify_count"] == 1
    assert report["success_verify_count"] == 1
    assert "conversion_rate" in report
    assert "oracle_gap" in report
