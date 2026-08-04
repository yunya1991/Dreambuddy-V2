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