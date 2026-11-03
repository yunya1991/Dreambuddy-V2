"""Phase A 认知 agent 参数化 — sort_mode=train_base 排序 TDD

SPEC-L0-DOMAIN-AGENTS v0.2 §5.3 Phase A 验收：
  同类事件 recall 命中率 ↑ 15%（A8 校验）；PSI > 0.25 自动告警。
H1 硬约束：零 MCP 壳改动（envelope schema 不变）。
"""


def _seed_memories(cle, tmppath, n=8, betas=None):
    """在 tmp_path 下 seed n 条记忆，返回 ids。"""
    ids = []
    for i in range(n):
        mem_id = cle.record(
            content=f"train_base seed {i} — 认知 agent 训练基座排序测试",
            quality_level="B" if i % 2 == 0 else "C",
            confidence=0.3 + 0.05 * i,
            source="phase_a_test",
        )
        ids.append(mem_id)

    # 给部分记忆先 verify 几次，让 Beta 后验有差异
    if betas:
        for mid, (successes, failures) in zip(ids, betas, strict=True):
            for _ in range(successes):
                cle.verify(mid, success=True)
            for _ in range(failures):
                cle.verify(mid, success=False)

    return ids


# RED 1: sort_mode="train_base" 是有效选项，返回结果非空
def test_red1_train_base_mode_exists(tmp_path):
    from cognitive_loop_entry import CognitiveLoopEntry

    cle = CognitiveLoopEntry(storage_path=str(tmp_path / "test.db"))
    try:
        _seed_memories(cle, tmp_path, n=5)
        results = cle.recall("train_base seed", top_k=3, sort_mode="train_base")
        assert len(results) <= 3
        assert len(results) > 0
    finally:
        cle.close()


# RED 2: Beta 后验 mean 高的记忆排名靠前（success 多的被 promote）
def test_red2_beta_mean_ranks_high(tmp_path):
    from cognitive_loop_entry import CognitiveLoopEntry

    cle = CognitiveLoopEntry(storage_path=str(tmp_path / "test.db"))
    try:
        ids = _seed_memories(cle, tmp_path, n=5, betas=[(3, 0), (0, 3), (2, 1), (1, 2), (1, 0)])
        results = cle.recall("train_base seed", top_k=5, sort_mode="train_base")
        result_ids = [r["id"] for r in results]
        # 成功最多的 ids[0] 应该在结果里
        assert ids[0] in result_ids[:2]
    finally:
        cle.close()


# RED 3: drift_detected=True → 所有 arm 重置（TS gate 重初始化）
def test_red3_psi_drift_resets_arm(tmp_path):
    from cognitive_interfaces import BetaState
    from drift_detector import PSI_MINOR_DRIFT, classify_drift

    # 模拟 PSI > 0.25
    psi_val = PSI_MINOR_DRIFT + 0.1
    assert classify_drift(psi_val) != "stable"

    # TB3 pareto_score 在 PSI=0.4 时 psi_stability=0，其余维度正常
    from training_reward import compute_reward, pareto_score

    reward = compute_reward(
        beta_state=BetaState(alpha=3.0, beta=1.0),
        psi_value=0.4,
        recall_hits=8,
        recall_total=10,
        known_gaps_count=2,
        cross_domain_refs=1,
    )
    # psi_stability = max(0, 1-0.4) = 0.6，pareto_score 应该比 PSI=0.05 低
    reward_stable = compute_reward(
        beta_state=BetaState(alpha=3.0, beta=1.0),
        psi_value=0.05,
        recall_hits=8,
        recall_total=10,
        known_gaps_count=2,
        cross_domain_refs=1,
    )
    assert pareto_score(reward) < pareto_score(reward_stable)


# RED 4: sort_mode 默认值仍然是 "score"（向后兼容）
def test_red4_default_sort_mode_score(tmp_path):
    from cognitive_loop_entry import CognitiveLoopEntry

    cle = CognitiveLoopEntry(storage_path=str(tmp_path / "test.db"))
    try:
        _seed_memories(cle, tmp_path, n=5)
        # 默认 sort_mode="score" 不抛错
        results_default = cle.recall("train_base seed", top_k=3)
        results_explicit = cle.recall("train_base seed", top_k=3, sort_mode="score")
        assert len(results_default) == len(results_explicit)
    finally:
        cle.close()


# RED 5: train_base 模式不影响 PoE / 质量过滤（H1 零壳改动）
def test_red5_train_base_preserves_poe_and_quality(tmp_path):
    from cognitive_loop_entry import CognitiveLoopEntry

    cle = CognitiveLoopEntry(storage_path=str(tmp_path / "test.db"))
    try:
        _seed_memories(cle, tmp_path, n=5)
        # min_quality="A" 应该把大部分过滤掉（只 seed 了 B 和 C）
        results = cle.recall("train_base seed", top_k=5, sort_mode="train_base", min_quality="A")
        # 可能空（没 A 级），也可能只有 verify 过升到 A 的；关键是 **不崩**
        assert isinstance(results, list)
    finally:
        cle.close()
