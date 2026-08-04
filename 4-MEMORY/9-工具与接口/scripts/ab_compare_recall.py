#!/usr/bin/env python3
"""
A/B 盲测脚本：自创 6 模板 (A路) vs 原版 14 Skill (B路) recall 命中率对比。
Task 14 小步验证：确认原版 ≥ 自创后方可安全推进 Task 15-20。
"""
import sys
from pathlib import Path

# 加载路径
COGNITIVE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(COGNITIVE_DIR))

from cognitive_superpowers import (
    ProcessTemplateRegistry,
    retrieve_relevant_processes,
    SkillLoader,
    LEGACY_TO_NEW,
)

# 10 个真实任务（覆盖 6 个自创模板 + 4 个原版独有场景）
TASKS = [
    # ID,  任务描述,                                  期望语义类别
    (1,  "为交易系统写单元测试 先写失败用例再实现 TDD",  "TDD/测试"),
    (2,  "polling_trader 超时了 复现 bug 排查 root cause", "调试/Debug"),
    (3,  "重构 yijing_exit_system 清理坏味道 小步修改",   "重构/Refactor"),
    (4,  "提交前做代码审查 review 检查逻辑正确性",         "审查/Review"),
    (5,  "设计认知系统集成方案 3 种方案对比 需求分析",     "设计/创意"),
    (6,  "把设计文档拆成 0.5-2h 粒度 task 列表 实施计划",  "计划/Planning"),
    (7,  "按计划执行 逐 task 完成 checkpoint 验证",       "执行/Executing"),
    (8,  "开发完成 收尾 合并分支 git commit 清理",        "收尾/Finishing"),
    (9,  "并发派发 3 个无依赖子任务 并行执行",            "并行/Parallel"),
    (10, "验证修复是否完成 跑回归测试 确认通过",          "验证/Verify"),
]

# 期望：A 路（旧自创）应该命中的 template_id
EXPECT_A = {
    1: ["TDD-001"],
    2: ["DEBUG-001"],
    3: ["REFACTOR-001"],
    4: ["REVIEW-001"],
    5: ["DESIGN-001"],
    6: [],  # 旧无 writing-plans
    7: [],  # 旧无 executing-plans
    8: [],  # 旧无 finishing
    9: [],  # 旧无 parallel
    10: [], # 旧无 verification
}

# 期望：B 路（新原版）应该命中的 skill_id
EXPECT_B = {
    1: ["test-driven-development"],
    2: ["systematic-debugging"],
    3: ["test-driven-development"],  # 重构 → TDD (LEGACY 映射)
    4: ["requesting-code-review"],
    5: ["brainstorming"],
    6: ["writing-plans"],
    7: ["executing-plans"],
    8: ["finishing-a-development-branch"],
    9: ["dispatching-parallel-agents"],
    10: ["verification-before-completion"],
}


def run_a(query: str, registry: ProcessTemplateRegistry) -> list:
    """A 路：旧自创 6 模板检索（不传 loader）"""
    results = retrieve_relevant_processes(query, registry=registry, top_k=3, layer="meta")
    return [(t.template_id, t.name, round(t.confidence, 2)) for t in results]


def run_b(query: str, registry: ProcessTemplateRegistry, loader: SkillLoader) -> list:
    """B 路：新原版 14 Skill 检索（传 loader）"""
    results = retrieve_relevant_processes(query, registry=registry, top_k=3, layer="meta", loader=loader)
    return [(t.template_id, t.name, round(t.confidence, 2)) for t in results]


def main():
    print("=" * 120)
    print("A/B 盲测：自创 6 模板 (A路) vs 原版 14 Skill (B路) recall 命中率对比")
    print("=" * 120)

    # 初始化
    registry = ProcessTemplateRegistry()
    loader = SkillLoader()

    a_hits = 0
    b_hits = 0
    a_total = 0
    b_total = 0

    for tid, query, category in TASKS:
        a_results = run_a(query, registry)
        b_results = run_b(query, registry, loader)

        a_ids = [r[0] for r in a_results]
        b_ids = [r[0] for r in b_results]

        # 命中判定
        exp_a = EXPECT_A.get(tid, [])
        exp_b = EXPECT_B.get(tid, [])

        a_hit = any(e in a_ids[:3] for e in exp_a) if exp_a else False
        b_hit = any(e in b_ids[:3] for e in exp_b) if exp_b else False

        if exp_a:
            a_total += 1
            if a_hit: a_hits += 1
        if exp_b:
            b_total += 1
            if b_hit: b_hits += 1

        a_mark = "✅" if a_hit else ("—" if not exp_a else "❌")
        b_mark = "✅" if b_hit else ("—" if not exp_b else "❌")

        print(f"\n[Task {tid:2d}] {category:15s}  query: {query[:55]}")
        print(f"  A路(旧自创) {a_mark}  Top3: {a_ids}")
        for r in a_results[:3]:
            print(f"       {r[0]:20s}  {r[1]:25s}  conf={r[2]}")
        print(f"  B路(原版14) {b_mark}  Top3: {b_ids}")
        for r in b_results[:3]:
            print(f"       {r[0]:35s}  {r[1][:30]:30s}  conf={r[2]}")

    print("\n" + "=" * 120)
    a_rate = a_hits / a_total * 100 if a_total else 0
    b_rate = b_hits / b_total * 100 if b_total else 0
    print(f"A 路（旧自创 6 模板）命中率: {a_hits}/{a_total} = {a_rate:.0f}%")
    print(f"B 路（原版 14 Skill）  命中率: {b_hits}/{b_total} = {b_rate:.0f}%")
    print(f"覆盖率: A路 {a_total}/10 任务有对应模板, B路 {b_total}/10 任务有对应模板")
    print()
    if b_rate >= a_rate:
        print(f"★ 结论：B 路 ≥ A 路（{b_rate:.0f}% ≥ {a_rate:.0f}%），可安全删除自创模板，推进 Task 15-20")
    else:
        print(f"⚠️  结论：B 路 < A 路（{b_rate:.0f}% < {a_rate:.0f}%），需检查原版 supplement 触发词覆盖率后再推进")
    print("=" * 120)


if __name__ == "__main__":
    main()
