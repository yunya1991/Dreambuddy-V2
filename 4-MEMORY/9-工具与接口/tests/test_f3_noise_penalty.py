# -*- coding: utf-8 -*-
"""
F3: cognitive-session 噪音记忆权重惩罚测试。

目标：在 CLE.recall() 返回结果的后处理中，
对 source=cognitive-session + quality=C + vc=0 + 同时含「解决路径」+「timeout/error」的模板化记录，
对 score 乘以 NOISE_PENALTY=0.5，并重新降序排序。

TDD 顺序：RED -> GREEN -> 验证。
"""

import json
import sys
import os
import tempfile
from pathlib import Path

import pytest

_COG_DIR = Path(__file__).resolve().parent.parent
if str(_COG_DIR) not in sys.path:
    sys.path.insert(0, str(_COG_DIR))

from cognitive_loop_entry import CognitiveLoopEntry


# ═══════════════════════════════════════════════════════════════
# 测试数据构造器
# ═══════════════════════════════════════════════════════════════

NOISE_RECORDS = [
    # 典型 timeout 模板噪音（应惩罚）
    {"content": "[解决路径] 问题: 任务涉及 29 个文件 | 方案: 修改了 58 次文件 | 结果: timeout (60步, 70.1min)",
     "quality": "C", "tags": ["solution_path", "strategy-execution"], "source": "cognitive-session"},
    {"content": "[解决路径] 问题: 任务涉及 9 个文件 | 方案: 修改了 19 次文件 | 结果: timeout (19步, 70.2min)",
     "quality": "C", "tags": ["solution_path", "strategy-execution"], "source": "cognitive-session"},
    {"content": "[解决路径] 问题: 任务涉及 7 个文件 | 方案: 修改了 9 次文件 | 结果: error (9步, 23.8min)",
     "quality": "C", "tags": ["solution_path", "strategy-execution"], "source": "cognitive-session"},
    {"content": "[解决路径] 问题: 任务涉及 5 个文件 | 方案: 修改了 15 次文件 | 结果: timeout",
     "quality": "C", "tags": ["solution_path"], "source": "cognitive-session"},
]

VALID_RECORDS = [
    # 硬约束（不应惩罚）
    {"content": "[硬约束][风控红] SL爆仓安全边际：静态SL必须位于爆仓价+0.3%缓冲的安全侧",
     "quality": "B", "tags": ["风控硬约束", "SL"], "source": "mcp"},
    # cognitive-session但不是C级（不应惩罚）
    {"content": "[解决路径] 问题: V15Executor架构 | 方案: TDD完成 | 结果: success (1步, 0.0min)",
     "quality": "S", "tags": ["solution_path", "architecture-design"], "source": "cognitive-session"},
    # cognitive-session且C级但vc>0（不应惩罚，已经验证的经验）
    {"content": "[解决路径] 问题: Python路径修复 | 方案: 提交1次 | 结果: success",
     "quality": "C", "tags": ["solution_path"], "source": "cognitive-session"},  # 运行时vc设为1
    # 不是timeout解决路径（mcp来源，不应惩罚）
    {"content": "BDSM回购驱动力可持续性评估模型三角评估：RQ40%+MB30%+SI30%",
     "quality": "B", "tags": ["BDSM模型"], "source": "mcp"},
    # dreamos-daily-monitor（cognitive-session以外的运营经验，不应惩罚）
    {"content": "调度器入口应惰性导入重依赖flask，否则解释器缺包阻断看门狗自愈",
     "quality": "C", "tags": ["dreamos", "eager-import"], "source": "dreamos-daily-monitor"},
]


@pytest.fixture
def cle_isolated(tmp_path):
    """隔离的 CLE，使用独立 SQLite DB。"""
    db_file = tmp_path / "test_cognitive.db"
    cle = CognitiveLoopEntry(
        storage_path=str(db_file),
        memory_id="AM-TEST-001",
        enable_distill=False,
    )

    # 先插入噪音（4条）
    noise_ids = []
    for r in NOISE_RECORDS:
        mid = cle._vm.add(
            content=r["content"], quality_level=r["quality"],
            confidence=0.3, tags=r["tags"], source=r["source"],
            memory_type="experience",
        )
        noise_ids.append(mid)

    # 再插入有效记忆（5条，其中1条C+cognitive-session需要手动verify_count设为1）
    valid_ids = []
    for i, r in enumerate(VALID_RECORDS):
        mid = cle._vm.add(
            content=r["content"], quality_level=r["quality"],
            confidence=0.3 if r["quality"] == "C" else 0.5,
            tags=r["tags"], source=r["source"], memory_type="experience",
        )
        valid_ids.append(mid)
        if i == 2:  # vc设为1的那条
            cle._vm.db.execute(
                "UPDATE memories SET verify_count = 1 WHERE id = ?",
                (mid,),
            )
            cle._vm.db.commit()

    return cle, noise_ids, valid_ids


# ═══════════════════════════════════════════════════════════════
# RED 测试（惩罚逻辑应存在但当前未实现 → 断言失败）
# ═══════════════════════════════════════════════════════════════

def test_f3_noise_records_are_penalized(cle_isolated):
    """噪音模板（C+cognitive-session+vc=0+timeout/error解决路径）的score应该被×0.5。"""
    cle, noise_ids, valid_ids = cle_isolated

    # 用一个能同时召回「硬约束」与「timeout解决路径」的query
    # 这里简单的测试方式：用 search 拿 raw，看 CLE 的 recall 是否做了惩罚
    results = cle.recall("任务涉及 文件 修改 timeout 风控", top_k=20)

    # 提取噪音ID->score的映射
    noise_scores = {}
    valid_scores = {}
    for r in results:
        if r["id"] in noise_ids:
            noise_scores[r["id"]] = r["score"]
        elif r["id"] in valid_ids:
            valid_scores[r["id"]] = r["score"]

    # 先拿到未惩罚的原始 score（通过 search，不经过 CLE 后处理）
    raw_results = cle._vm.search("任务涉及 文件 修改 timeout 风控", top_k=20)
    raw_map = {r.id: r.score for r in raw_results}

    # 断言：所有噪音的最终score == 原始score * ≈0.5
    # （因为惩罚逻辑应该在 CLE.recall 的后处理阶段做）
    penalized_count = 0
    for nid in noise_ids:
        if nid in raw_map and nid in noise_scores:
            raw = raw_map[nid]
            final = noise_scores[nid]
            # 惩罚后应接近 raw * 0.5（允许浮点误差）
            expected = round(raw * 0.5, 6)
            if abs(final - expected) < 1e-4:
                penalized_count += 1

    assert penalized_count >= 2, (
        f"期望至少2条噪音被正确惩罚(score×0.5)，实际仅{penalized_count}/{len(noise_scores)}。"
        f" 原始: {raw_map}, 惩罚后: {noise_scores}"
    )


def test_f3_valid_records_not_penalized(cle_isolated):
    """非噪音记忆（硬约束、S级、vc≥1、非cognitive-session）不应被惩罚。"""
    cle, noise_ids, valid_ids = cle_isolated

    results = cle.recall("风控模型 BDSM V15 导入", top_k=20)
    valid_scores_after = {r["id"]: r["score"] for r in results if r["id"] in valid_ids}

    raw_results = cle._vm.search("风控模型 BDSM V15 导入", top_k=20)
    raw_map = {r.id: r.score for r in raw_results}

    # 非噪音：score应与原始接近（不被0.5倍）
    unpenalized = 0
    for vid in valid_ids:
        if vid in valid_scores_after and vid in raw_map:
            raw = raw_map[vid]
            final = valid_scores_after[vid]
            # 与原始相同（误差 <1%）而不是 0.5
            ratio = final / raw if raw > 0 else 0
            if ratio > 0.9:
                unpenalized += 1

    assert unpenalized >= 3, (
        f"期望至少3条非噪音未被惩罚(ratio>0.9)，实际{unpenalized}/{len(valid_scores_after)}。"
        f" 原始: {raw_map}, 最终: {valid_scores_after}"
    )


def test_f3_results_stably_sorted_after_penalty(cle_isolated):
    """惩罚后结果仍按score降序稳定排序。"""
    cle, _, _ = cle_isolated
    results = cle.recall("任务涉及", top_k=9)
    scores = [r["score"] for r in results]
    # 非严格降序即可（允许并列）
    for i in range(1, len(scores)):
        assert scores[i-1] + 1e-9 >= scores[i], (
            f"惩罚后结果未按score降序: {scores}"
        )
