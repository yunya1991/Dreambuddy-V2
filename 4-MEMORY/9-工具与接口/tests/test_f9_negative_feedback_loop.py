# -*- coding: utf-8 -*-
"""
F9: 负反馈闭环建设。

目标：补充 CLE 方法 `mark_adoption_and_verify_unused(results, adopted_ids)`，
在 recall 结果列表 + 用户实际采用的记忆ID集合 差异中：
  1. 末位 score 最低、且未被采用的 1 条记忆，自动 verify(False)；
  2. 跳过 S/A 级和 vc≥3 的（已经经过充分锤炼，不因单次不采纳降级）；
  3. FAIL-OPEN：任何异常原样返回 adoption 元数据，不抛错；
  4. 空列表 / adopted_ids=None / 全部都被采用 → 跳过verify(F)，返回空闭环元数据。

通过"末位末用自动负反馈"平衡当前98%全verify(True)导致boost全1.1的倾斜。
"""

import json
import sys
import os
from pathlib import Path

import pytest

_COG_DIR = Path(__file__).resolve().parent.parent
if str(_COG_DIR) not in sys.path:
    sys.path.insert(0, str(_COG_DIR))

from cognitive_loop_entry import CognitiveLoopEntry


@pytest.fixture
def cle_isolated(tmp_path):
    db_file = tmp_path / "test_f9.db"
    cle = CognitiveLoopEntry(
        storage_path=str(db_file),
        memory_id="AM-TEST-F9",
        enable_distill=False,
    )
    return cle


def _insert(cle, content, quality, vc=0, source="cognitive-session", score=None):
    mid = cle._vm.add(
        content=content, quality_level=quality,
        confidence=0.3 if quality == "C" else (0.4 if quality == "B" else 0.7),
        tags=["f9test"], source=source, memory_type="experience",
    )
    if vc > 0:
        cle._vm.db.execute(
            "UPDATE memories SET verify_count = ? WHERE id = ?", (vc, mid))
        cle._vm.db.commit()
    # get() 返回 dict（直接SQL行结构），含 id/content/quality_level/confidence/verify_count 等
    row = cle._vm.get(mid) or {}
    rec = dict(row)
    rec.setdefault("id", mid)
    if score is not None:
        rec["score"] = score
    else:
        rec.setdefault("score", 0.5)
    # 把 quality_level 显式补到顶层（F9判定要用到）
    rec.setdefault("quality_level", quality)
    if vc > 0:
        rec["verify_count"] = vc
    else:
        rec.setdefault("verify_count", 0)
    return rec


def test_f9_last_unused_non_adopted_is_verified_false(cle_isolated):
    """末位最低score且未采用的记忆(B/C+vc<3)应自动verify(False)。"""
    cle = cle_isolated
    m1 = _insert(cle, "Top1 有用", "B", vc=1, score=0.9)   # adopted
    m2 = _insert(cle, "Top2 一般", "C", vc=0, score=0.5)   # adopted
    m3 = _insert(cle, "Top3 末位不用", "C", vc=0, score=0.2)  # 末位 未采用

    results = [m1, m2, m3]
    adopted_ids = {m1["id"], m2["id"]}

    # 未实现 → AttributeError 或 返回空
    meta = cle.mark_adoption_and_verify_unused(results, adopted_ids)

    assert meta.get("applied") is True, "应标记已应用负反馈闭环"
    assert meta.get("negative_verified_count") == 1, "末位1条应触发verify(F)"
    fid = meta["negative_verified_ids"][0]
    assert fid == m3["id"], f"应verify(F)末位未采用 {m3['id']}, 实际{fid}"
    # DB中 verify_count 应该+1且confidence下降
    row = cle._vm.db.execute(
        "SELECT verify_count, confidence FROM memories WHERE id=?", (fid,)
    ).fetchone()
    assert row[0] == 1, f"verify_count应从0→1, 实际={row[0]}"


def test_f9_skips_senior_memories(cle_isolated):
    """S/A 级或 vc≥3 的末位未采用记忆不触发verify(F)，下一位替代。"""
    cle = cle_isolated
    m1 = _insert(cle, "Top1", "B", vc=1, score=0.9)
    # 末位是 S 级：应跳过，找下一位未采用
    m2 = _insert(cle, "Top2 C vc0 未用", "C", vc=0, score=0.4)  # 真正应被verify
    m3 = _insert(cle, "Top3 S 级 senior", "S", vc=10, score=0.2)  # 末位 S, 跳过

    results = [m1, m2, m3]
    adopted = {m1["id"]}

    meta = cle.mark_adoption_and_verify_unused(results, adopted)
    assert meta.get("negative_verified_count") == 1
    vid = meta["negative_verified_ids"][0]
    assert vid == m2["id"], f"应跳过S级末位，选中m2={m2['id']}, 实际={vid}"


def test_f9_no_candidates_or_all_adopted_safe(cle_isolated):
    """全采用 / adopted=None / 空列表 → 无负反馈但不报错。"""
    cle = cle_isolated
    m1 = _insert(cle, "M1", "C", score=0.8)
    m2 = _insert(cle, "M2", "C", score=0.7)

    # 情况1: 全部都采用
    meta1 = cle.mark_adoption_and_verify_unused([m1, m2], {m1["id"], m2["id"]})
    assert meta1.get("negative_verified_count") == 0
    assert meta1.get("applied") is True

    # 情况2: adopted=None / 空set
    meta2 = cle.mark_adoption_and_verify_unused([m1, m2], None)
    assert meta2.get("applied") is True
    assert meta2.get("negative_verified_count") == 0

    # 情况3: 空 results
    meta3 = cle.mark_adoption_and_verify_unused([], {m1["id"]})
    assert meta3.get("negative_verified_count") == 0


def test_f9_fail_open_swallows_errors(monkeypatch, cle_isolated):
    """verify内部异常时整条FAIL-OPEN：标记applied=True但nvc=0，不向外抛异常。"""
    cle = cle_isolated
    m1 = _insert(cle, "采用", "B", vc=1, score=0.9)
    m2 = _insert(cle, "末位未用", "C", vc=0, score=0.2)

    # 替换 cle.verify 为抛错函数
    def boom(*a, **kw):
        raise RuntimeError("boom")
    monkeypatch.setattr(cle, "verify", boom)

    # 应FAIL-OPEN不抛
    meta = cle.mark_adoption_and_verify_unused([m1, m2], {m1["id"]})
    assert meta.get("applied") is True
    assert meta.get("negative_verified_count") == 0  # 异常无verify完成
    assert "error" in meta
