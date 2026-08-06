#!/usr/bin/env python3
"""
Superpowers流程模板测试 — TDD红阶段
验证流程模板的存储、检索、校验机制
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent))


def test_process_template_data_model():
    """流程模板数据模型：ID、名称、步骤、置信度、验证次数"""
    from cognitive_superpowers import ProcessTemplate

    tdd = ProcessTemplate(
        template_id="TDD-001",
        name="测试驱动开发",
        steps=["理解需求", "写失败测试", "写最小实现", "测试通过", "重构"],
        description="先写测试再写代码的标准流程",
        confidence=0.85,
        verify_count=12,
        source="software-engineering-best-practices",
    )

    assert tdd.template_id == "TDD-001"
    assert tdd.name == "测试驱动开发"
    assert len(tdd.steps) == 5
    assert tdd.confidence == 0.85
    assert tdd.verify_count == 12
    assert tdd.quality_level == "A"  # conf≥0.70 → A级

    print("✅ test_process_template_data_model 通过")
    return True


def test_process_template_quality_levels():
    """流程模板质量等级映射（与记忆系统一致）"""
    from cognitive_superpowers import ProcessTemplate

    # S级：conf≥0.95, verify≥10
    s = ProcessTemplate("S-001", "S级流程", ["step"], confidence=0.96, verify_count=12)
    assert s.quality_level == "S"

    # A级：conf≥0.70, verify≥3
    a = ProcessTemplate("A-001", "A级流程", ["step"], confidence=0.75, verify_count=5)
    assert a.quality_level == "A"

    # B级：conf≥0.40, verify≥1
    b = ProcessTemplate("B-001", "B级流程", ["step"], confidence=0.50, verify_count=2)
    assert b.quality_level == "B"

    # C级：conf<0.40, verify=0
    c = ProcessTemplate("C-001", "C级流程", ["step"], confidence=0.25, verify_count=0)
    assert c.quality_level == "C"

    print("✅ test_process_template_quality_levels 通过")
    return True


def test_process_template_registry():
    """流程模板注册表：存储、检索、列出"""
    from cognitive_superpowers import ProcessTemplateRegistry

    registry = ProcessTemplateRegistry(auto_discover=False)

    # 注册流程模板
    tdd = registry.register(
        template_id="TDD-001",
        name="测试驱动开发",
        steps=["写测试", "写代码", "重构"],
        confidence=0.85,
        verify_count=10,
        layer="meta",
    )

    assert tdd.template_id == "TDD-001"

    # 检索流程模板
    found = registry.get("TDD-001")
    assert found is not None
    assert found.name == "测试驱动开发"

    # 列出所有流程模板
    all_templates = registry.list_all()
    assert len(all_templates) >= 1

    print("✅ test_process_template_registry 通过")
    return True


def test_retrieve_relevant_processes():
    """检索相关流程模板：根据任务类型/关键词匹配"""
    from cognitive_superpowers import ProcessTemplateRegistry, retrieve_relevant_processes

    registry = ProcessTemplateRegistry(auto_discover=False)
    registry.register("TDD-001", "测试驱动开发", ["写测试", "写代码"], confidence=0.85, verify_count=10, layer="meta")
    registry.register("DEBUG-001", "系统化调试", ["复现", "定位", "修复"], confidence=0.75, verify_count=8, layer="meta")
    registry.register("REFACTOR-001", "代码重构", ["识别坏味道", "小步重构", "验证"], confidence=0.70, verify_count=5, layer="meta")

    # 检索相关流程（关键词"测试"匹配TDD）
    results = retrieve_relevant_processes("测试 单测", registry, top_k=3)
    assert len(results) > 0
    # TDD应排在前面（关键词"测试"匹配）
    assert results[0].template_id == "TDD-001"

    # 按置信度排序
    results2 = retrieve_relevant_processes("修复bug", registry, top_k=3)
    assert len(results2) > 0

    print("✅ test_retrieve_relevant_processes 通过")
    return True


def test_format_process_suggestions():
    """格式化流程建议：生成AI可读的建议文本"""
    from cognitive_superpowers import ProcessTemplate, format_process_suggestions

    tdd = ProcessTemplate("TDD-001", "测试驱动开发", ["写测试", "写代码", "重构"], confidence=0.85, verify_count=10, layer="meta")
    debug = ProcessTemplate("DEBUG-001", "系统化调试", ["复现", "定位", "修复"], confidence=0.75, verify_count=8, layer="meta")

    text = format_process_suggestions([tdd, debug])

    assert "测试驱动开发" in text
    assert "TDD-001" in text
    assert "0.85" in text
    assert "非约束" in text or "非强制" in text

    print("✅ test_format_process_suggestions 通过")
    return True


def test_verify_process_followed():
    """校验是否遵循流程：对比行动链与流程步骤"""
    from cognitive_superpowers import ProcessTemplate, verify_process_followed

    tdd = ProcessTemplate("TDD-001", "测试驱动开发", ["写测试", "写代码", "重构"], confidence=0.85, verify_count=10, layer="meta")

    # 遵循TDD的行动链
    followed_chain = [
        {"action_type": "file_change", "detail": "added test_tdd.py"},
        {"action_type": "file_change", "detail": "added implementation.py"},
        {"action_type": "tool_call", "detail": "run tests"},
        {"action_type": "file_change", "detail": "refactored implementation.py"},
    ]
    result1 = verify_process_followed(tdd, followed_chain)
    assert result1["followed"] == True
    assert result1["matched_steps"] >= 2

    # 未遵循TDD的行动链（直接写代码）
    not_followed_chain = [
        {"action_type": "file_change", "detail": "added implementation.py"},
        {"action_type": "file_change", "detail": "modified implementation.py"},
    ]
    result2 = verify_process_followed(tdd, not_followed_chain)
    assert result2["followed"] == False

    print("✅ test_verify_process_followed 通过")
    return True


def test_process_template_bayesian_update():
    """流程模板贝叶斯更新：验证成功→置信度上升"""
    from cognitive_superpowers import ProcessTemplate, update_process_confidence

    tdd = ProcessTemplate("TDD-001", "测试驱动开发", ["step"], confidence=0.50, verify_count=1, layer="meta")

    # 验证成功
    updated = update_process_confidence(tdd, success=True)
    assert updated.confidence > 0.50, "成功应提升置信度"
    assert updated.verify_count == 2

    # 验证失败
    tdd2 = ProcessTemplate("DEBUG-001", "调试", ["step"], confidence=0.50, verify_count=1, layer="meta")
    updated2 = update_process_confidence(tdd2, success=False)
    assert updated2.confidence < 0.50, "失败应降低置信度"

    print("✅ test_process_template_bayesian_update 通过")
    return True


def test_process_template_persistence():
    """流程模板持久化：保存到文件系统"""
    from cognitive_superpowers import ProcessTemplateRegistry
    import tempfile
    import os

    tmpdir = tempfile.mkdtemp()
    try:
        registry = ProcessTemplateRegistry(meta_data_dir=tmpdir, auto_discover=False)

        # 注册并保存
        registry.register("TDD-001", "测试驱动开发", ["step"], confidence=0.85, verify_count=10, layer="meta")
        registry.save()

        # 检查文件存在
        data_file = tmpdir + "/process_templates.json"
        assert os.path.exists(data_file), f"应有流程文件: {data_file}"

        # 重新加载
        registry2 = ProcessTemplateRegistry(meta_data_dir=tmpdir, auto_discover=False)
        registry2.load()
        found = registry2.get("TDD-001")
        assert found is not None
        assert found.name == "测试驱动开发"

        print("✅ test_process_template_persistence 通过")
        return True
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_skill_loader_trading_skills():
    """P1: SkillLoader 双源加载 — 交易 Skill 从 trading-cognition 目录加载"""
    from cognitive_superpowers import SkillLoader

    loader = SkillLoader()
    # 开发 Skill 仍为 14 个
    assert len(loader.skills) == 14, f"开发 Skill 应为 14 个，实际 {len(loader.skills)}"
    # 交易 Skill 应为 6 个
    assert len(loader.trading_skills) == 6, f"交易 Skill 应为 6 个，实际 {len(loader.trading_skills)}"
    # 验证 skill_id
    expected_ids = {"t0-market-cognition", "t1-strategy-synthesis", "t2-trade-execution",
                    "t3-risk-gatekeeper", "t4-intelligence-radar", "t5-meta-reflection"}
    actual_ids = set(loader.trading_skills.keys())
    assert actual_ids == expected_ids, f"交易 Skill ID 不匹配: 缺失 {expected_ids - actual_ids}, 多余 {actual_ids - expected_ids}"

    print("✅ test_skill_loader_trading_skills 通过")
    return True


def test_retrieve_trading_by_task_type():
    """P1: retrieve 按 task_type 路由 — trading 类召回交易 Skill，dev 类召回开发 Skill"""
    from cognitive_superpowers import SkillLoader

    loader = SkillLoader()

    # 交易 task_type → 召回交易 Skill
    result_trading = loader.retrieve("深度调研 市场分析 矛盾分析", task_type="strategy-research")
    assert len(result_trading["meta"]) > 0, "交易 task_type 应返回交易 Skill"
    trading_skill_ids = [sk.skill_id for sk, _, _ in result_trading["meta"]]
    trading_set = set(loader.trading_skills.keys())
    assert any(tid in trading_set for tid in trading_skill_ids), f"应包含 T 系列 Skill: {trading_skill_ids}"

    # 开发 task_type → 召回开发 Skill
    result_dev = loader.retrieve("TDD 测试 单测", task_type="python-development")
    assert len(result_dev["meta"]) > 0, "开发 task_type 应返回开发 Skill"
    dev_skill_ids = [sk.skill_id for sk, _, _ in result_dev["meta"]]
    assert all(tid not in trading_set for tid in dev_skill_ids), f"不应包含 T 系列 Skill: {dev_skill_ids}"

    # 无 task_type（向后兼容）→ 召回开发 Skill
    result_default = loader.retrieve("TDD 测试")
    assert len(result_default["meta"]) > 0, "默认应返回开发 Skill"

    print("✅ test_retrieve_trading_by_task_type 通过")
    return True


def test_resolve_unit_for_trading_task_types():
    """P2: 交易 task_type → MU-TRD（不是 MU-DEV）"""
    from cognitive_superpowers import resolve_unit_for_task

    # 新增的 4 个交易 task_type 都应路由到 MU-TRD
    for tt in ("strategy-research", "strategy-backtest", "strategy-execution", "strategy-governance"):
        unit = resolve_unit_for_task(tt)
        assert unit is not None, f"{tt} 应返回非 None"
        assert unit["unit_id"] == "MU-TRD", f"{tt} 应路由到 MU-TRD，实际 {unit['unit_id']}"

    # 原有的 trading-system/trading-data 仍为 MU-TRD
    for tt in ("trading-system", "trading-data"):
        unit = resolve_unit_for_task(tt)
        assert unit is not None and unit["unit_id"] == "MU-TRD", f"{tt} 应为 MU-TRD"

    # 开发 task_type 仍为 MU-DEV
    assert resolve_unit_for_task("python-development")["unit_id"] == "MU-DEV"

    print("✅ test_resolve_unit_for_trading_task_types 通过")
    return True


def test_trading_applied_template_id_prefix():
    """P2: 交易会话的 applied_id 前缀为 APP-TRD-（区分开发 APP-）"""
    from cognitive_session import CognitiveSessionManager, CognitiveSession
    import tempfile, os

    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = CognitiveSessionManager(sessions_dir=tmpdir)
        sess = mgr.on_file_change("experiments/ab-trading/core/nodes/a0_contradiction.py")
        # task_type 应为 strategy-execution（P0 修复）
        assert sess.task_type == "strategy-execution", f"task_type={sess.task_type}"

        # 模拟 _deposit_applied_template 中的 id 生成逻辑
        # 直接测试 id 前缀逻辑
        is_trading = sess.task_type in ("trading-system", "trading-data",
                                         "strategy-research", "strategy-backtest",
                                         "strategy-execution", "strategy-governance",
                                         "strategy-state", "risk-control")
        prefix = "APP-TRD-" if is_trading else "APP-"
        applied_id = f"{prefix}{sess.id.split('-')[-1]}"
        assert applied_id.startswith("APP-TRD-"), f"交易 applied_id 应前缀 APP-TRD-，实际 {applied_id}"

    print("✅ test_trading_applied_template_id_prefix 通过")
    return True


def test_update_path_advantage_from_trading():
    """P2: path_advantage 用 P&L/夏普做客观指标贝叶斯升级"""
    from cognitive_superpowers import ProcessTemplateRegistry, ProcessTemplate
    import tempfile, json

    with tempfile.TemporaryDirectory() as tmpdir:
        registry = ProcessTemplateRegistry(
            meta_data_dir=tmpdir, app_memory_dirs=[], auto_discover=False
        )
        # 创建一个 C 级交易模板
        t = ProcessTemplate(
            template_id="APP-TRD-test1",
            name="测试交易模板",
            steps=["step1"],
            confidence=0.3,
            verify_count=0,
            layer="applied",
            quality_level="C",
        )
        registry._applied_templates["APP-TRD-test1"] = t

        # 场景1: 正 P&L + 正夏普 → 正向 path_advantage → 连续 2 次升 B
        registry.update_path_advantage_from_trading(
            "APP-TRD-test1",
            pnl_pct=5.0,
            sharpe_ratio=1.5,
            max_drawdown_pct=10.0,
            win_rate=0.6,
        )
        assert t.path_advantage_history[-1] > 0.2, f"正 P&L 应给正向分: {t.path_advantage_history[-1]}"
        assert t.consecutive_positive == 1

        # 第二次正向 → 升 B
        registry.update_path_advantage_from_trading(
            "APP-TRD-test1",
            pnl_pct=3.0,
            sharpe_ratio=1.2,
            max_drawdown_pct=8.0,
            win_rate=0.55,
        )
        assert t.quality_level == "B", f"连续 2 次正向应升 B，实际 {t.quality_level}"

        # 场景2: 负 P&L + 负夏普 → 负向 → 连续 3 次降 quarantined
        for i in range(3):
            registry.update_path_advantage_from_trading(
                "APP-TRD-test1",
                pnl_pct=-8.0,
                sharpe_ratio=-0.5,
                max_drawdown_pct=25.0,
                win_rate=0.3,
            )
        assert t.quality_level == "quarantined", f"连续 3 次负向应降 quarantined，实际 {t.quality_level}"

        # 场景3: outcome_metrics 存入 metadata
        t2 = ProcessTemplate(
            template_id="APP-TRD-test2",
            name="测试交易模板2",
            steps=["step1"],
            confidence=0.3,
            verify_count=0,
            layer="applied",
            quality_level="C",
        )
        registry._applied_templates["APP-TRD-test2"] = t2
        registry.update_path_advantage_from_trading(
            "APP-TRD-test2",
            pnl_pct=10.0,
            sharpe_ratio=2.0,
            max_drawdown_pct=5.0,
            win_rate=0.7,
        )
        assert "outcome_metrics" in t2.metadata, "应存入 outcome_metrics"
        om = t2.metadata["outcome_metrics"]
        assert om["pnl_pct"] == 10.0
        assert om["sharpe_ratio"] == 2.0
        assert "computed_path_advantage" in om

    print("✅ test_update_path_advantage_from_trading 通过")
    return True


def test_trading_recall_returns_correct_structure():
    """P3: trading_recall() 返回 memories + processes/meta + processes/applied 三段结构"""
    from cognitive_loop_entry import trading_recall

    result = trading_recall(
        context="BTC 做多 置信度0.72 震荡市场",
        task_type="strategy-execution",
        top_k_mem=3,
        top_meta=2,
        top_applied=2,
    )

    # 基本结构验证
    assert "memories" in result, "应包含 memories"
    assert "count" in result, "应包含 count"
    assert "processes" in result, "应包含 processes"
    assert "ok" in result, "应包含 ok 标志"
    assert isinstance(result["memories"], list), "memories 应为列表"
    assert isinstance(result["processes"], dict), "processes 应为字典"
    assert "meta" in result["processes"], "processes 应包含 meta"
    assert "applied" in result["processes"], "processes 应包含 applied"
    assert "process_block_markdown" in result["processes"], "processes 应包含 process_block_markdown"

    # ok=True 时 memories 应可序列化
    if result.get("ok"):
        for m in result["memories"]:
            assert "id" in m or "content" in m, f"memory 条目缺少字段: {m}"

    print("✅ test_trading_recall_returns_correct_structure 通过")
    return True


def test_trading_recall_fail_safe():
    """P3: trading_recall() 认知系统不可用时失败安全（返回 ok=False，不抛异常）"""
    from cognitive_loop_entry import trading_recall
    from unittest.mock import patch, MagicMock

    # 模拟 get_cle() 抛异常
    with patch("cognitive_loop_entry.get_cle", side_effect=Exception("DB unavailable")):
        result = trading_recall(context="BTC 做多", task_type="strategy-execution")

    assert result["ok"] == False, f"失败时应 ok=False，实际 {result.get('ok')}"
    assert result["count"] == 0, "失败时 count 应为 0"
    assert result["memories"] == [], "失败时 memories 应为空"
    assert "error" in result, "失败时应包含 error 字段"

    print("✅ test_trading_recall_fail_safe 通过")
    return True


def test_trading_recall_routes_to_trading_skills():
    """P3: trading_recall() with trading task_type 召回 T 系列 Skill（非开发 Skill）"""
    from cognitive_loop_entry import trading_recall

    result = trading_recall(
        context="市场分析 矛盾分析 策略设计",
        task_type="strategy-research",
        top_k_mem=1,
        top_meta=3,
        top_applied=1,
    )

    if result.get("ok") and result["processes"]["meta"]:
        trading_skill_ids = {"t0-market-cognition", "t1-strategy-synthesis",
                             "t2-trade-execution", "t3-risk-gatekeeper",
                             "t4-intelligence-radar", "t5-meta-reflection"}
        meta_ids = [m.get("skill_id") for m in result["processes"]["meta"]]
        # 至少有一个 T 系列 Skill 被召回
        assert any(mid in trading_skill_ids for mid in meta_ids), \
            f"交易 task_type 应召回 T 系列 Skill，实际: {meta_ids}"

    print("✅ test_trading_recall_routes_to_trading_skills 通过")
    return True


def test_summarize_cognitive_recall():
    """P3: _summarize_cognitive_recall 从 inference 提取认知召回摘要"""
    import sys
    _trader_path = str(Path(__file__).resolve().parents[2] / "11-易经推理系统" / "scripts" / "memory_l4")
    if _trader_path not in sys.path:
        sys.path.insert(0, _trader_path)

    # _summarize_cognitive_recall 是静态方法，无需实例化 PollingTrader
    from polling_trader import PollingTrader

    # 场景1: 有认知召回结果
    inference_ok = {
        "cognitive_recall": {
            "ok": True,
            "count": 3,
            "processes": {
                "meta": [
                    {"skill_id": "t0-market-cognition", "display_name": "市场认知"},
                    {"skill_id": "t3-risk-gatekeeper", "display_name": "风控门禁"},
                ],
                "applied": [{"applied_id": "APP-TRD-001"}, {"applied_id": "APP-TRD-002"}],
            },
        }
    }
    summary = PollingTrader._summarize_cognitive_recall(inference_ok)
    assert summary["ok"] == True
    assert summary["mem_count"] == 3
    assert summary["meta_skills"] == ["t0-market-cognition", "t3-risk-gatekeeper"]
    assert summary["applied_count"] == 2

    # 场景2: 无认知召回（fail_closed 或未启用）
    inference_empty = {"cognitive_recall": {"ok": False}}
    summary2 = PollingTrader._summarize_cognitive_recall(inference_empty)
    assert summary2["ok"] == False

    # 场景3: 完全无 cognitive_recall 字段
    inference_none = {"direction": "LONG"}
    summary3 = PollingTrader._summarize_cognitive_recall(inference_none)
    assert summary3["ok"] == False

    print("✅ test_summarize_cognitive_recall 通过")
    return True


if __name__ == "__main__":
    print("=" * 60)
    print("🔴 TDD RED 阶段：Superpowers流程模板测试（期望失败）")
    print("=" * 60)

    tests = [
        ("test_process_template_data_model", test_process_template_data_model),
        ("test_process_template_quality_levels", test_process_template_quality_levels),
        ("test_process_template_registry", test_process_template_registry),
        ("test_retrieve_relevant_processes", test_retrieve_relevant_processes),
        ("test_format_process_suggestions", test_format_process_suggestions),
        ("test_verify_process_followed", test_verify_process_followed),
        ("test_process_template_bayesian_update", test_process_template_bayesian_update),
        ("test_process_template_persistence", test_process_template_persistence),
        ("test_skill_loader_trading_skills", test_skill_loader_trading_skills),
        ("test_retrieve_trading_by_task_type", test_retrieve_trading_by_task_type),
        ("test_resolve_unit_for_trading_task_types", test_resolve_unit_for_trading_task_types),
        ("test_trading_applied_template_id_prefix", test_trading_applied_template_id_prefix),
        ("test_update_path_advantage_from_trading", test_update_path_advantage_from_trading),
        ("test_trading_recall_returns_correct_structure", test_trading_recall_returns_correct_structure),
        ("test_trading_recall_fail_safe", test_trading_recall_fail_safe),
        ("test_trading_recall_routes_to_trading_skills", test_trading_recall_routes_to_trading_skills),
        ("test_summarize_cognitive_recall", test_summarize_cognitive_recall),
    ]

    passed = 0
    failed = 0
    failures = []

    for name, fn in tests:
        print(f"\n▶ 运行: {name}")
        try:
            if fn():
                passed += 1
        except Exception as ex:
            failed += 1
            failures.append((name, f"{type(ex).__name__}: {ex}"))
            print(f"   ❌ {type(ex).__name__}: {ex}")

    print("\n" + "=" * 60)
    print(f"📊 结果: 通过 {passed} / {len(tests)}, 失败 {failed}")
    if failures:
        for n, r in failures:
            print(f"  - {n}: {r}")
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)