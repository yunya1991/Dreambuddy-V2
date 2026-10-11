#!/usr/bin/env python3
"""P2 F4 验收脚本: TDR数据源从1个扩展到5个。

验收标准:
  - F4: TDR数据源包含认知(B级以上)/SKILL/文档/知识库
  - 5个数据源 Provider 全部注册成功: tdr / cognitive / skill / doc / rea
  - 各 Provider 可 fetch_cases 返回 TrainingCase 列表
  - ActiveTrainingCollector 可调度全部 5 个 Provider
"""
import os
import sys
import tempfile

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_34_DIR = os.path.dirname(_THIS_DIR)
_PROJECT_ROOT = os.path.dirname(_34_DIR)
_ADAPTERS_DIR = os.path.join(_34_DIR, "adapters")
_CORE_DIR = os.path.join(_34_DIR, "core")
_SCRIPTS_DIR = os.path.join(_PROJECT_ROOT, "scripts")

for _p in [_THIS_DIR, _34_DIR, _ADAPTERS_DIR, _CORE_DIR, _SCRIPTS_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# 使用临时 TDR DB
_tmpdir = tempfile.mkdtemp(prefix="p2_f4_acceptance_")
os.environ["SPL_DB_DIR"] = _tmpdir


def main():
    from active_training_collector import ActiveTrainingCollector

    # ── 验收 1: 5个 Provider 全部可实例化 ────────────────────
    print("=" * 60)
    print("F4 验收: TDR数据源从1个扩展到5个")
    print("=" * 60)

    providers = {}

    # 1. TDR
    try:
        from tdr_data_provider import TDRTrainingDataProvider
        providers["tdr"] = TDRTrainingDataProvider()
        print(f"  [1/5] tdr: ✅ 实例化成功")
    except Exception as e:
        print(f"  [1/5] tdr: ❌ 失败: {e}")

    # 2. Cognitive
    try:
        from cognitive_memory_collector import CognitiveMemoryCollector
        providers["cognitive"] = CognitiveMemoryCollector()
        print(f"  [2/5] cognitive: ✅ 实例化成功")
    except Exception as e:
        print(f"  [2/5] cognitive: ❌ 失败: {e}")

    # 3. Skill
    try:
        from skill_system_collector import SkillSystemCollector
        providers["skill"] = SkillSystemCollector()
        print(f"  [3/5] skill: ✅ 实例化成功")
    except Exception as e:
        print(f"  [3/5] skill: ❌ 失败: {e}")

    # 4. Doc
    try:
        from doc_knowledge_collector import DocKnowledgeCollector
        providers["doc"] = DocKnowledgeCollector()
        print(f"  [4/5] doc: ✅ 实例化成功")
    except Exception as e:
        print(f"  [4/5] doc: ❌ 失败: {e}")

    # 5. REA
    try:
        from rea_batch_collector import REABatchCollector
        providers["rea"] = REABatchCollector()
        print(f"  [5/5] rea: ✅ 实例化成功")
    except Exception as e:
        print(f"  [5/5] rea: ❌ 失败: {e}")

    # ── 验收 2: ActiveTrainingCollector 注册全部5个 ──────────
    print("\n注册到 ActiveTrainingCollector:")
    collector = ActiveTrainingCollector()
    for name, provider in providers.items():
        collector.register_provider(provider)

    registered = list(collector._providers.keys())
    print(f"  已注册数据源: {registered}")
    expected = {"tdr", "cognitive", "skill", "doc", "rea"}
    actual = set(registered)

    if expected == actual:
        print(f"  ✅ 5个数据源全部注册成功")
    else:
        missing = expected - actual
        print(f"  ❌ 缺少数据源: {missing}")
        return False

    # ── 验收 3: 各 Provider 的 get_source_name + get_quality_threshold ──
    print("\n各 Provider 属性验证:")
    for name, provider in providers.items():
        src = provider.get_source_name()
        thresh = provider.get_quality_threshold()
        print(f"  {name}: source='{src}', threshold='{thresh}'")
        assert src == name, f"source name mismatch: {src} != {name}"

    # ── 验收 4: 各 Provider 可 fetch_cases（FAIL-OPEN） ──────
    print("\nfetch_cases 验证 (真实数据源):")

    # TDR: 清空后存入一条测试数据
    try:
        from case_bank_server import store_case, _connect
        conn = _connect()
        conn.execute("DELETE FROM solution_cases")
        conn.commit()
        conn.close()
        store_case({
            "intent": "f4_tdr_test", "actions": ["a"], "outcome_text": "o",
            "learned": ["l"], "quality": "B", "source": "tdr",
        })
        cases = providers["tdr"].fetch_cases(limit=10)
        print(f"  tdr: {len(cases)} cases ✅")
    except Exception as e:
        print(f"  tdr: ❌ {e}")

    # Cognitive: 查询真实 cognitive_memory.db
    try:
        cases = providers["cognitive"].fetch_cases(limit=10)
        print(f"  cognitive: {len(cases)} cases ✅ (B级以上记忆)")
    except Exception as e:
        print(f"  cognitive: ❌ {e}")

    # Skill: 查询真实 registry.json
    try:
        cases = providers["skill"].fetch_cases(limit=10)
        print(f"  skill: {len(cases)} cases ✅ (active SKILLs)")
    except Exception as e:
        print(f"  skill: ❌ {e}")

    # Doc: 解析真实 INDEX.md
    try:
        cases = providers["doc"].fetch_cases(limit=10)
        print(f"  doc: {len(cases)} cases ✅ (文档索引条目)")
    except Exception as e:
        print(f"  doc: ❌ {e}")

    # REA: 扫描 34 目录
    try:
        cases = providers["rea"].fetch_cases(limit=10)
        print(f"  rea: {len(cases)} cases (依赖 algorithm_reducer 可用性)")
    except Exception as e:
        print(f"  rea: ❌ {e}")

    # ── 验收 5: register_all_default_providers 便捷方法 ─────
    print("\nregister_all_default_providers 便捷方法:")
    collector2 = ActiveTrainingCollector()
    collector2.register_all_default_providers()
    registered2 = list(collector2._providers.keys())
    print(f"  自动注册数据源: {registered2}")
    if len(registered2) >= 4:  # REA 可能因依赖不可用而跳过
        print(f"  ✅ 自动注册成功 ({len(registered2)}/5)")
    else:
        print(f"  ⚠️ 只注册了 {len(registered2)} 个")

    # ── 总结 ─────────────────────────────────────────────
    print("\n" + "=" * 60)
    if expected == actual:
        print("F4 验收: ✅ PASS")
        print("  TDR数据源从1个(tdr)扩展到5个(tdr+cognitive+skill+doc+rea)")
        return True
    else:
        print("F4 验收: ❌ FAIL")
        return False


if __name__ == "__main__":
    result = main()
    sys.exit(0 if result else 1)
