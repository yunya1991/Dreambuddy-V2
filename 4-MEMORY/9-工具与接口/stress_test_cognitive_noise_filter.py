#!/usr/bin/env python3
"""
认知系统降噪逻辑压力测试。

验证目标：
1. 纯数据文件变更 → 不 record（skipped=no_code_file）
2. 纯代码文件变更 → record（含语义提取）
3. 混合变更（数据+代码）→ record 但经验内容只含代码文件，剔除数据文件
4. 高频状态文件（v15_state/_state/_sltp/backtest_cache）→ 即使混入也不进入经验
5. 易经L4代码目录（scripts/memory_l4/*.py）→ 应 record（非 data/memory_l4）
6. 易经L4数据目录（data/episodes/data/l4_events）→ 不 record

使用 dry_run 模式，不写入数据库。
"""
import sys
import os
import time
import tempfile
import shutil
from pathlib import Path
from collections import Counter

# 加入认知系统路径
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from cognitive_daemon import (
    is_code_file,
    _has_code_file,
    trigger_change_record,
    generate_change_experience,
    EXCLUDE_DIRS,
    EXCLUDE_FILES,
)


# ============================================================
# 测试用例定义
# ============================================================

TEST_CASES = [
    # (用例名, 变更字典{path: "added"|"modified"|"deleted"}, 期望recorded, 期望经验含哪些文件, 期望经验不含哪些文件)
    {
        "name": "H1-纯数据文件_v15_state",
        "changes": {"14-V15经典马丁策略/data/v15_state.json": "modified"},
        "expect_recorded": False,
        "expect_skip_reason": "no_code_file",
    },
    {
        "name": "H2-纯数据文件_v4_position_sltp",
        "changes": {"12-三屏趋势系统/data/v4_position_sltp.json": "modified"},
        "expect_recorded": False,
        "expect_skip_reason": "no_code_file",
    },
    {
        "name": "H3-纯状态文件_orchestrator_state",
        "changes": {"14-V15经典马丁策略/data/orchestrator_state.json": "modified"},
        "expect_recorded": False,
        "expect_skip_reason": "no_code_file",
    },
    {
        "name": "H4-回测缓存目录",
        "changes": {"14-V15经典马丁策略/data/backtest_cache/OP_1w_200.json": "modified"},
        "expect_recorded": False,
        "expect_skip_reason": "no_code_file",
    },
    {
        "name": "H5-易经L4数据目录_episodes",
        "changes": {"11-易经推理系统/data/episodes/live_BTC_20260731.json": "added"},
        "expect_recorded": False,
        "expect_skip_reason": "no_code_file",
    },
    {
        "name": "H6-易经L4数据目录_l4_events",
        "changes": {"11-易经推理系统/data/l4_events/open_ETH_20260731.json": "added"},
        "expect_recorded": False,
        "expect_skip_reason": "no_code_file",
    },
    {
        "name": "H7-a7_gate_logs",
        "changes": {"11-易经推理系统/data/a7_gate_logs/a7_gate_20260731_120000.json": "added"},
        "expect_recorded": False,
        "expect_skip_reason": "no_code_file",
    },
    {
        "name": "H8-strategy_diversity_stats",
        "changes": {"11-易经推理系统/data/strategy_diversity/stats.json": "modified"},
        "expect_recorded": False,
        "expect_skip_reason": "no_code_file",
    },
    {
        "name": "H9-认知系统自身产物",
        "changes": {"4-MEMORY/2-交易记忆单元/bayesian_memories.json": "modified"},
        "expect_recorded": False,
        "expect_skip_reason": "no_code_file",
    },
    {
        "name": "H10-纯代码文件_polling_trader",
        "changes": {"11-易经推理系统/scripts/memory_l4/polling_trader.py": "modified"},
        "expect_recorded": True,
        "expect_content_contains": ["polling_trader.py"],
    },
    {
        "name": "H11-纯代码文件_风控规则",
        "changes": {"13-通用风控模块/rules/exit_rules.py": "modified"},
        "expect_recorded": True,
        "expect_content_contains": ["exit_rules.py"],
    },
    {
        "name": "H12-纯代码文件_认知系统",
        "changes": {"4-MEMORY/9-工具与接口/cognitive_daemon.py": "modified"},
        "expect_recorded": True,
        "expect_content_contains": ["cognitive_daemon.py"],
    },
    {
        "name": "H13-混合_代码+数据(应只记代码)",
        "changes": {
            "14-V15经典马丁策略/data/v15_state.json": "modified",
            "11-易经推理系统/scripts/memory_l4/polling_trader.py": "modified",
        },
        "expect_recorded": True,
        "expect_content_contains": ["polling_trader.py"],
        "expect_content_not_contains": ["v15_state"],
    },
    {
        "name": "H14-混合_多代码+多数据(应只记代码)",
        "changes": {
            "14-V15经典马丁策略/data/v15_state.json": "modified",
            "12-三屏趋势系统/data/v4_position_sltp.json": "modified",
            "14-V15经典马丁策略/data/orchestrator_state.json": "modified",
            "11-易经推理系统/scripts/memory_l4/yijing_exit_system.py": "modified",
            "13-通用风控模块/rules/exit_rules.py": "modified",
        },
        "expect_recorded": True,
        "expect_content_contains": ["yijing_exit_system.py", "exit_rules.py"],
        "expect_content_not_contains": ["v15_state", "v4_position", "orchestrator_state"],
    },
    {
        "name": "H15-易经scripts_memory_l4代码(应record,非data)",
        "changes": {
            "11-易经推理系统/scripts/memory_l4/app_memory_interface.py": "modified",
            "11-易经推理系统/scripts/memory_l4/distill_engine.py": "modified",
        },
        "expect_recorded": True,
        "expect_content_contains": ["app_memory_interface.py", "distill_engine.py"],
    },
    {
        "name": "H16-易经data_memory_l4数据(应skip)",
        "changes": {
            "11-易经推理系统/data/memory_l4/cases/case_001.json": "added",
            "11-易经推理系统/data/memory_l4/reviews/rev_001.json": "added",
        },
        "expect_recorded": False,
        "expect_skip_reason": "no_code_file",
    },
    {
        "name": "H17-高频批量_100个状态文件",
        "changes": {f"14-V15经典马丁策略/data/v15_state_{i}.json": "modified" for i in range(100)},
        "expect_recorded": False,
        "expect_skip_reason": "no_code_file",
    },
    {
        "name": "H18-高频批量_100个代码文件",
        "changes": {f"11-易经推理系统/scripts/test_{i}.py": "modified" for i in range(100)},
        "expect_recorded": True,
    },
    {
        "name": "H19-空变更",
        "changes": {},
        "expect_recorded": False,
    },
    {
        "name": "H20-PID和Lock文件",
        "changes": {
            "4-MEMORY/9-工具与接口/.cognitive_daemon.pid": "modified",
            "14-V15经典马丁策略/data/hyperopt.lock": "modified",
        },
        "expect_recorded": False,
        "expect_skip_reason": "no_code_file",
    },
]


def run_stress_test():
    """运行压力测试。"""
    print("=" * 70)
    print("认知系统降噪逻辑压力测试 (dry_run模式，不写数据库)")
    print("=" * 70)
    print(f"测试用例数: {len(TEST_CASES)}")
    print(f"排除目录: {len(EXCLUDE_DIRS)} 个")
    print(f"排除文件模式: {len(EXCLUDE_FILES)} 个")
    print()

    passed = 0
    failed = 0
    skipped_details = []

    for i, tc in enumerate(TEST_CASES, 1):
        name = tc["name"]
        changes = tc["changes"]

        # dry_run 模式调用
        result = trigger_change_record(changes, dry_run=True)

        # dry_run 时 recorded 恒为 False，用 experience 是否非空判断"是否会被记录"
        recorded = bool(result.get("experience", "")) if result.get("dry_run") else result.get("recorded", False)
        skip_reason = result.get("skipped", "")
        experience = result.get("experience", "")

        expect_recorded = tc.get("expect_recorded")
        expect_skip = tc.get("expect_skip_reason")
        expect_contains = tc.get("expect_content_contains", [])
        expect_not_contains = tc.get("expect_content_not_contains", [])

        ok = True
        reasons = []

        # 检查 recorded 状态（dry_run 下用 experience 非空等价）
        if recorded != expect_recorded:
            ok = False
            reasons.append(f"recorded={recorded} 期望{expect_recorded}")

        # 检查 skip_reason
        if expect_skip and skip_reason != expect_skip:
            ok = False
            reasons.append(f"skip={skip_reason!r} 期望{expect_skip!r}")

        # 检查经验内容包含
        if expect_contains:
            for s in expect_contains:
                if s not in experience:
                    ok = False
                    reasons.append(f"经验缺 '{s}'")

        # 检查经验内容不包含
        if expect_not_contains:
            for s in expect_not_contains:
                if s in experience:
                    ok = False
                    reasons.append(f"经验误含 '{s}'")

        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed += 1

        print(f"[{status}] {i:02d}. {name}")
        if not ok:
            for r in reasons:
                print(f"         - {r}")
            print(f"         变更: {list(changes.keys())[:3]}...")
            if experience:
                print(f"         经验: {experience[:120]}")

    print()
    print("=" * 70)
    print(f"压力测试结果: {passed} PASS / {failed} FAIL / {len(TEST_CASES)} TOTAL")
    print(f"通过率: {passed/len(TEST_CASES)*100:.1f}%")
    print("=" * 70)

    return failed == 0


def run_high_frequency_simulation():
    """模拟高频文件变更场景（模拟 daemon 实际运行时的防抖窗口）。"""
    print()
    print("=" * 70)
    print("高频变更模拟（模拟交易时段每秒多次状态文件变更）")
    print("=" * 70)

    # 模拟交易时段 5 分钟内的高频变更
    noise_files = [
        "14-V15经典马丁策略/data/v15_state.json",
        "12-三屏趋势系统/data/v4_position_sltp.json",
        "14-V15经典马丁策略/data/orchestrator_state.json",
        "11-易经推理系统/data/strategy_diversity/stats.json",
        "14-V15经典马丁策略/data/capital_manager/engine_state.json",
    ]
    code_files = [
        "11-易经推理系统/scripts/memory_l4/polling_trader.py",
        "13-通用风控模块/rules/exit_rules.py",
    ]

    scenarios = [
        ("S1-连续100次纯噪声", {f: "modified" for f in noise_files * 20}, False),
        ("S2-连续100次纯代码", {f: "modified" for f in code_files * 50}, True),
        ("S3-99噪声+1代码", {**{f: "modified" for f in noise_files * 19}, code_files[0]: "modified"}, True),
        ("S4-50噪声+50代码", {**{f: "modified" for f in noise_files * 10}, **{f: "modified" for f in code_files * 25}}, True),
    ]

    print(f"场景数: {len(scenarios)}")
    print()

    passed = 0
    for name, changes, expect_recorded in scenarios:
        result = trigger_change_record(changes, dry_run=True)
        recorded = bool(result.get("experience", "")) if result.get("dry_run") else result.get("recorded", False)
        ok = recorded == expect_recorded
        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        n_code = sum(1 for f in changes if is_code_file(f))
        n_data = len(changes) - n_code
        print(f"[{status}] {name}: 变更{len(changes)}个(代码{n_code}/数据{n_data}) -> recorded={recorded} 期望{expect_recorded}")

    print()
    print(f"高频模拟结果: {passed}/{len(scenarios)} PASS")
    return passed == len(scenarios)


if __name__ == "__main__":
    ok1 = run_stress_test()
    ok2 = run_high_frequency_simulation()
    print()
    if ok1 and ok2:
        print(">>> 全部压力测试通过，降噪逻辑有效 <<<")
        sys.exit(0)
    else:
        print(">>> 存在失败用例，需检查 <<<")
        sys.exit(1)
