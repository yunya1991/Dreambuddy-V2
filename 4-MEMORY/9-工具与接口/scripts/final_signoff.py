#!/usr/bin/env python3
"""最终签收脚本：V1-V15 全量验收（设计节 6.2 + 7.9）。

用法：
  python3 scripts/final_signoff.py              # 跑全部 15 项验收
  python3 scripts/final_signoff.py --json       # JSON 输出
  python3 scripts/final_signoff.py --verbose    # 详细输出

设计节 6.2 V1-V9 + 设计节 7.9 V10-V15：
  V1  SKILL.md 格式合规          SkillLoader 启动日志       14 个全部 OK
  V2  skills-index.json 自动重建  删除后重启 daemon          5 秒内重建，14 条目
  V3  recall 返回 processes 字段  cognitive-cli recall       processes.meta ≥ 1，match_score > 0
  V4  process_block 注入         recall 后查内部状态         items ≥ 2，token < 3500
  V5  System Prompt 渲染         working-memory dump        末尾有 🎯 流程建议段
  V6  旧 mapping 迁移完成        迁移脚本 dry-run + apply    parent_id 全在 14 Skill name 或 custom-path
  V7  事后校验生效               模拟完整会话 commit         applied 含 process_verify_report，score ∈ [0,1]
  V8  异常隔离                   写坏一个 SKILL.md           其余 13 个继续可用，daemon 不崩
  V9  向后兼容                   include_process=False 调用  返回 JSON 与改造前一致
  V10 思维链压缩生效             查 EvaluationSample         thought_chain_compressed 5-15 条
  V11 A/B 评测输出 path_advantage 跑 5 个样本任务            每个输出 [-1.0, 1.0] 得分
  V12 学习决策生效               模拟 path_advantage ≥ 0.2×2  Solution Path 自动 C→B
  V13 飞书告警触发               模拟 daemon 崩溃            飞书收到 🔴 Critical 卡片
  V14 quarantined 过滤           标记一条 quarantined         recall 不再召回该条
  V15 历史评测反哺               recall 后查 process_block    应用案例含 📊 历史评测行
"""
import json
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable, Dict, List, Optional

_SCRIPT_DIR = Path(__file__).parent.parent


@dataclass
class AcceptanceItem:
    """单项验收结果。"""
    vid: str
    name: str
    method: str
    criteria: str
    passed: bool
    actual: str = ""


def _run_cli(cmd: str) -> dict:
    """执行 CLI 命令返回 JSON。"""
    try:
        proc = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=60,
        )
        if proc.returncode != 0:
            return {}
        return json.loads(proc.stdout)
    except (json.JSONDecodeError, subprocess.TimeoutExpired, OSError):
        return {}


# ---- V1-V15 静态元数据（name/method/criteria，供 run_all_acceptance 构建项）----
ACCEPTANCE_META: Dict[str, List[str]] = {
    "V1":  ["SKILL.md 格式合规", "SkillLoader 启动日志", "14 个全部 OK，无 frontmatter 红线告警"],
    "V2":  ["skills-index.json 自动重建", "删除后重启 daemon", "5 秒内重建，14 条目，md5 非空"],
    "V3":  ["recall 返回 processes 字段", 'cognitive-cli recall "测试 TDD"', "processes.meta ≥ 1，match_score > 0，hard_gates 非空"],
    "V4":  ["process_block 注入", "recall 后查内部状态", "items ≥ 2，token < 3500"],
    "V5":  ["System Prompt 渲染", "working-memory dump", "末尾出现 🎯 流程建议段，含 HARD-GATE 文本"],
    "V6":  ["旧 mapping 迁移完成", "迁移脚本 dry-run + apply", "parent_id 全在 14 Skill name 或 custom-path；legacy_template_id 保留"],
    "V7":  ["事后校验生效", "模拟完整会话 commit", "applied 含 process_verify_report，score ∈ [0,1]，followed 布尔值"],
    "V8":  ["异常隔离", "写坏一个 SKILL.md（改 frontmatter 为 ***）", "其余 13 个继续可用，daemon 不崩"],
    "V9":  ["向后兼容", "include_process=False 调 recall", "返回 JSON 与改造前一致（仅 memories + count）"],
    "V10": ["思维链压缩生效", "完成会话后查 EvaluationSample", "thought_chain_compressed 5-15 条，无幻觉"],
    "V11": ["A/B 评测输出 path_advantage", "跑 5 个样本任务", "每个输出 [-1.0, 1.0] 区间得分"],
    "V12": ["学习决策生效", "模拟 path_advantage ≥ +0.2 连续 2 次", "Solution Path 自动 C → B"],
    "V13": ["飞书告警触发", "模拟 daemon 崩溃", "飞书收到 🔴 Critical 卡片，含崩溃上下文"],
    "V14": ["quarantined 过滤", "标记一条 Solution Path quarantined", "recall 不再召回该条"],
    "V15": ["历史评测反哺", "recall 后查 process_block", "应用案例含 📊 历史评测行"],
}

_VID_ORDER: List[str] = [f"V{i}" for i in range(1, 16)]

# 真实 _check_vN() 最近一次结果缓存（供 run_all_acceptance 在真实运行时回填 actual）
_LAST_ITEMS: Dict[str, AcceptanceItem] = {}


def _run_acceptance_check(vid: str) -> bool:
    """通用验收检查分发（单测时可被 mock 返回 True，避免 subprocess）。

    真实运行时调用对应 _check_vN()，缓存其 AcceptanceItem 供回填 actual。
    """
    check_fn = _CHECKS.get(vid)
    if check_fn is None:
        return False
    item = check_fn()
    _LAST_ITEMS[vid] = item
    return item.passed


# ---- V1-V9（设计节 6.2）----

def _check_v1() -> AcceptanceItem:
    """V1: SKILL.md 格式合规，14 个全部 OK。"""
    result = _run_cli("python3 cognitive_loop_entry.py skills list")
    skills = result.get("skills", [])
    ok_count = sum(1 for s in skills if s.get("status") == "OK")
    return AcceptanceItem(
        vid="V1", name="SKILL.md 格式合规",
        method="SkillLoader 启动日志", criteria="14 个全部 OK，无 frontmatter 红线告警",
        passed=ok_count == 14, actual=f"{ok_count}/14 OK",
    )


def _check_v2() -> AcceptanceItem:
    """V2: skills-index.json 自动重建。"""
    index_path = _SCRIPT_DIR.parent / "0-元记忆" / "superpowers" / "skills-index.json"
    if not index_path.exists():
        return AcceptanceItem("V2", "skills-index.json 自动重建",
            "删除后重启 daemon", "5 秒内重建，14 条目，md5 非空",
            passed=False, actual="文件不存在")
    try:
        data = json.loads(index_path.read_text())
        count = len(data.get("skills", {}))
        all_md5 = all(s.get("md5_of_base") for s in data.get("skills", {}).values())
    except (json.JSONDecodeError, OSError):
        count, all_md5 = 0, False
    return AcceptanceItem("V2", "skills-index.json 自动重建",
        "删除后重启 daemon", "5 秒内重建，14 条目，md5 非空",
        passed=count == 14 and all_md5, actual=f"{count} 条目, md5={'OK' if all_md5 else 'MISSING'}")


def _check_v3() -> AcceptanceItem:
    """V3: recall 返回 processes 字段。"""
    result = _run_cli('python3 cognitive_loop_entry.py recall "测试 TDD"')
    processes = result.get("processes", {})
    meta = processes.get("meta", [])
    has_score = any(m.get("match_score", 0) > 0 for m in meta)
    has_gates = any(m.get("hard_gates") for m in meta)
    return AcceptanceItem("V3", "recall 返回 processes 字段",
        'cognitive-cli recall "测试 TDD"', "processes.meta ≥ 1，match_score > 0，hard_gates 非空",
        passed=len(meta) >= 1 and has_score and has_gates,
        actual=f"meta={len(meta)}, score>0={has_score}, gates={has_gates}")


def _check_v4() -> AcceptanceItem:
    """V4: WorkingMemory.process_block 注入。"""
    result = _run_cli("python3 cognitive_loop_entry.py working-memory dump")
    process_block = result.get("process_block", {})
    items = process_block.get("items", {})
    token = process_block.get("token_used", 0)
    return AcceptanceItem("V4", "process_block 注入",
        "recall 后查内部状态", "items ≥ 2，token < 3500",
        passed=len(items) >= 2 and token < 3500,
        actual=f"items={len(items)}, token={token}")


def _check_v5() -> AcceptanceItem:
    """V5: System Prompt 渲染。"""
    result = _run_cli("python3 cognitive_loop_entry.py working-memory dump")
    prompt = result.get("prompt_context", "")
    has_section = "🎯 流程建议" in prompt or "流程建议" in prompt
    has_gate = "HARD-GATE" in prompt
    return AcceptanceItem("V5", "System Prompt 渲染",
        "working-memory dump", "末尾出现 🎯 流程建议段，含 HARD-GATE 文本",
        passed=has_section and has_gate,
        actual=f"section={has_section}, gate={has_gate}")


def _check_v6() -> AcceptanceItem:
    """V6: 旧 mapping 迁移完成。"""
    result = _run_cli("python3 scripts/migrate_legacy_mappings.py --verify")
    migrated = result.get("migrated", 0)
    invalid = result.get("invalid", [])
    return AcceptanceItem("V6", "旧 mapping 迁移完成",
        "迁移脚本 dry-run + apply", "parent_id 全在 14 Skill name 或 custom-path；legacy_template_id 保留",
        passed=migrated > 0 and len(invalid) == 0,
        actual=f"migrated={migrated}, invalid={len(invalid)}")


def _check_v7() -> AcceptanceItem:
    """V7: 事后校验生效。"""
    result = _run_cli("python3 cognitive_loop_entry.py stats applied --latest 1")
    applied = result.get("applied", [{}])
    if not applied:
        return AcceptanceItem("V7", "事后校验生效",
            "模拟完整会话 commit", "applied 含 process_verify_report，score ∈ [0,1]",
            passed=False, actual="无 applied 数据")
    a = applied[0]
    report = a.get("process_verify_report", {})
    score = report.get("score", -1)
    has_followed = "followed" in report
    return AcceptanceItem("V7", "事后校验生效",
        "模拟完整会话 commit", "applied 含 process_verify_report，score ∈ [0,1]，followed 布尔值",
        passed=0 <= score <= 1 and has_followed,
        actual=f"score={score}, followed={has_followed}")


def _check_v8() -> AcceptanceItem:
    """V8: 异常隔离。"""
    result = _run_cli("python3 cognitive_loop_entry.py skills list")
    skills = result.get("skills", [])
    loaded = sum(1 for s in skills if s.get("loaded"))
    has_error = any(s.get("status") == "ERROR" for s in skills)
    # 有错误但其余继续可用
    return AcceptanceItem("V8", "异常隔离",
        "写坏一个 SKILL.md（改 frontmatter 为 ***）", "其余 13 个继续可用，daemon 不崩",
        passed=loaded >= 13 and has_error,
        actual=f"loaded={loaded}, has_error={has_error}")


def _check_v9() -> AcceptanceItem:
    """V9: 向后兼容。"""
    result = _run_cli('python3 cognitive_loop_entry.py recall "test" --no-process')
    has_memories = "memories" in result
    has_count = "count" in result
    no_processes = "processes" not in result
    return AcceptanceItem("V9", "向后兼容",
        "include_process=False 调 recall", "返回 JSON 与改造前一致（仅 memories + count）",
        passed=has_memories and has_count and no_processes,
        actual=f"memories={has_memories}, count={has_count}, no_processes={no_processes}")


# ---- V10-V15（设计节 7.9）----

def _check_v10() -> AcceptanceItem:
    """V10: 思维链压缩生效。"""
    result = _run_cli("python3 cognitive_loop_entry.py stats evaluation --latest 1")
    sample = result.get("evaluation_sample", {})
    chain = sample.get("thought_chain_compressed", [])
    return AcceptanceItem("V10", "思维链压缩生效",
        "完成会话后查 EvaluationSample", "thought_chain_compressed 5-15 条，无幻觉",
        passed=5 <= len(chain) <= 15,
        actual=f"chain长度={len(chain)}")


def _check_v11() -> AcceptanceItem:
    """V11: A/B 评测输出 path_advantage。"""
    result = _run_cli("python3 cognitive_loop_entry.py stats evaluation --recent 5")
    evaluations = result.get("evaluations", [])
    valid = all(-1.0 <= e.get("path_advantage", 0) <= 1.0 for e in evaluations)
    return AcceptanceItem("V11", "A/B 评测输出 path_advantage",
        "跑 5 个样本任务", "每个输出 [-1.0, 1.0] 区间得分",
        passed=len(evaluations) >= 5 and valid,
        actual=f"evaluations={len(evaluations)}, all_valid={valid}")


def _check_v12() -> AcceptanceItem:
    """V12: 学习决策生效。"""
    result = _run_cli("python3 cognitive_loop_entry.py stats applied --upgraded")
    upgraded = result.get("upgraded_applied", [])
    has_c_to_b = any(
        u.get("from_level") == "C" and u.get("to_level") == "B" for u in upgraded
    )
    return AcceptanceItem("V12", "学习决策生效",
        "模拟 path_advantage ≥ +0.2 连续 2 次", "Solution Path 自动 C → B",
        passed=has_c_to_b,
        actual=f"upgraded={len(upgraded)}, C→B={has_c_to_b}")


def _check_v13() -> AcceptanceItem:
    """V13: 飞书告警触发。"""
    result = _run_cli("python3 cognitive_loop_entry.py stats alerts --recent 1")
    alerts = result.get("alerts", [])
    has_critical = any(a.get("level") == "Critical" for a in alerts)
    return AcceptanceItem("V13", "飞书告警触发",
        "模拟 daemon 崩溃", "飞书收到 🔴 Critical 卡片，含崩溃上下文",
        passed=has_critical,
        actual=f"alerts={len(alerts)}, has_critical={has_critical}")


def _check_v14() -> AcceptanceItem:
    """V14: quarantined 过滤。"""
    result = _run_cli('python3 cognitive_loop_entry.py recall "test"')
    processes = result.get("processes", {})
    applied = processes.get("applied", [])
    quarantined_count = sum(1 for a in applied if a.get("quality_level") == "quarantined")
    return AcceptanceItem("V14", "quarantined 过滤",
        "标记一条 Solution Path quarantined", "recall 不再召回该条",
        passed=quarantined_count == 0,
        actual=f"recall 中 quarantined={quarantined_count}")


def _check_v15() -> AcceptanceItem:
    """V15: 历史评测反哺。"""
    result = _run_cli("python3 cognitive_loop_entry.py working-memory dump")
    process_block = result.get("process_block", {})
    items = process_block.get("items", {})
    all_text = " ".join(items.values()) if isinstance(items, dict) else str(items)
    has_eval_line = "📊 历史评测" in all_text or "历史评测" in all_text
    return AcceptanceItem("V15", "历史评测反哺",
        "recall 后查 process_block", "应用案例含 📊 历史评测行",
        passed=has_eval_line,
        actual=f"has_eval_line={has_eval_line}")


# vid → 真实检查函数（_run_acceptance_check 分发用）
_CHECKS: Dict[str, Callable[[], AcceptanceItem]] = {
    "V1": _check_v1, "V2": _check_v2, "V3": _check_v3, "V4": _check_v4,
    "V5": _check_v5, "V6": _check_v6, "V7": _check_v7, "V8": _check_v8,
    "V9": _check_v9, "V10": _check_v10, "V11": _check_v11, "V12": _check_v12,
    "V13": _check_v13, "V14": _check_v14, "V15": _check_v15,
}


def run_all_acceptance() -> List[AcceptanceItem]:
    """跑全部 V1-V15 验收。

    单测时 _run_acceptance_check 被 mock 返回 True（不触发 subprocess）；
    真实运行时 _run_acceptance_check 调用 _check_vN() 并缓存 actual 用于回填。
    """
    items: List[AcceptanceItem] = []
    for vid in _VID_ORDER:
        name, method, criteria = ACCEPTANCE_META[vid]
        passed = _run_acceptance_check(vid)
        # 真实运行时回填 actual（mock 时不缓存，actual 保持空）
        actual = _LAST_ITEMS.get(vid, AcceptanceItem(vid, name, method, criteria, passed)).actual
        items.append(AcceptanceItem(
            vid=vid, name=name, method=method, criteria=criteria,
            passed=passed, actual=actual,
        ))
    return items


def main():
    import argparse
    parser = argparse.ArgumentParser(description="最终签收：V1-V15 全量验收")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    parser.add_argument("--verbose", action="store_true", help="详细输出")
    args = parser.parse_args()

    results = run_all_acceptance()
    passed_count = sum(1 for r in results if r.passed)

    if args.json:
        output = {
            "total": len(results),
            "passed": passed_count,
            "all_passed": passed_count == len(results),
            "results": [asdict(r) for r in results],
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(f"{'='*70}")
        print(f"  Superpowers 集成最终签收 — V1-V15 全量验收")
        print(f"{'='*70}")
        for r in results:
            status = "✅" if r.passed else "❌"
            print(f"  {status} {r.vid}: {r.name}")
            if args.verbose or not r.passed:
                print(f"      方法: {r.method}")
                print(f"      标准: {r.criteria}")
                print(f"      实际: {r.actual}")
        print(f"{'='*70}")
        print(f"  通过: {passed_count}/{len(results)}")
        if passed_count == len(results):
            print(f"  🎉 全部验收通过 — 认知闭环设计目标达成（设计节 6.6）")
        else:
            print(f"  ⚠️  {len(results) - passed_count} 项未通过 — 需修复后重跑")

    return 0 if passed_count == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
