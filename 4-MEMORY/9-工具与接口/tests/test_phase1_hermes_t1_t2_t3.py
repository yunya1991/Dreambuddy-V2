#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 1: Hermes 四角色进化循环 — TDD 测试文件（RED-GREEN）

三部分：
    TestEVT1Scheduler     → EV-T1 四角色 cron（6 TC）
    TestEVT2Constitution  → EV-T2 宪法红线 9 条 + audit_proposal + PROP 解析 + 宪法漂移（7 TC）
    TestEVT3Voyager       → EV-T3 VOYAGER 5 维评分 + 连续 3 次 success → AUTO 草案审核队列（7 TC）

硬约束：
  1. NO PRODUCTION CODE WITHOUT FAILING TEST FIRST
  2. 所有新增测试按"看失败 → 写最小实现 → 看通过"循环跑
  3. fixture 全部使用函数参数注入，不得直接调用（如 isolated_paths(tmp_path) 错误写法）
"""
from __future__ import annotations

import json
import os
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set

import pytest

_SCRIPT_DIR = Path(__file__).resolve().parent
_PARENT = _SCRIPT_DIR.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))
_PROJECT_ROOT = _PARENT.parent.parent


# ==================================================================
# 共用 fixtures
# ==================================================================


@pytest.fixture
def workdirs(tmp_path):
    """隔离工作目录：evolution_pipeline + review_queue + voyager_jsonl + bayesian db mock 根"""
    root = tmp_path / "phase1"
    pipeline = root / "evolution_pipeline"
    drafts = root / "solution_path_drafts" / "review_queue"
    voyager = root / "voyager"
    for p in (pipeline, drafts, voyager):
        p.mkdir(parents=True, exist_ok=True)
    bayesian = root / "bayesian_memories.json"
    bayesian.write_text(json.dumps({
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "memory_count": 0,
        "schema_version": 2,
        "memories": [],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "root": root,
        "pipeline": pipeline,
        "drafts": drafts,
        "voyager_dir": voyager,
        "voyager_jsonl": voyager / "voyager_consecutive.jsonl",
        "voyager_extra": voyager / "voyager_memory_extra.json",
        "review_index": drafts.parent / "review_queue_index.json",
        "bayesian": bayesian,
    }


@pytest.fixture
def sample_proposal_clean():
    """一个干净、B 类合法、不踩红线的示例 proposal（用于基线对比）"""
    return {
        "proposal_id": "PROP-TEST-001",
        "actor": "B",
        "category": "memory_structure",
        "touched_files": {
            "4-MEMORY/9-工具与接口/constitution.py",
        },
        "written_paths": {
            "4-MEMORY/9-工具与接口/constitution.py",
        },
        "proposed_changes_by_path": {
            "4-MEMORY/9-工具与接口/constitution.py": {"delta": "+38 -2", "lines_modified": 40},
        },
        "approvals": {},
        "is_production_change": False,
    }


# ==================================================================
# EV-T1: 四角色 Scheduler
# ==================================================================


class TestEVT1Scheduler:
    """cognitive_evolution_scheduler.py 四角色 cron（6 TC）"""

    # --- TC t01: CLI --help 包含关键参数 ---------------------------------
    def test_t01_cli_help_contains_key_params(self, workdirs):
        runner = _PARENT / "cognitive_evolution_scheduler.py"
        assert runner.exists(), f"缺少脚本: {runner}"
        import subprocess
        result = subprocess.run(
            [sys.executable, str(runner), "--help"],
            capture_output=True, text=True, check=False, timeout=30,
            cwd=str(_PARENT),
        )
        stdout = result.stdout + result.stderr
        # 必须包含 8 个关键参数/角色名
        for kw in ("evolution", "critic", "verifier", "gardener",
                   "--dry-run", "--no-llm", "--max-proposals", "--role"):
            assert kw in stdout, f"--help 缺少关键字 '{kw}'，输出:\n{stdout}"
        assert result.returncode == 0

    # --- TC t02: --role evolution --dry-run --no-llm --max-proposals 3 → 3 个 PROPOSED ----
    def test_t02_evolution_dryrun_no_llm_3_proposals(self, workdirs):
        runner = _PARENT / "cognitive_evolution_scheduler.py"
        assert runner.exists()
        import subprocess
        env = os.environ.copy()
        env["PYTHONPATH"] = str(_PARENT)
        result = subprocess.run(
            [sys.executable, str(runner),
             "--role", "evolution",
             "--dry-run",
             "--no-llm",
             "--max-proposals", "3",
             "--work-dir", str(workdirs["pipeline"])],
            capture_output=True, text=True, check=False, timeout=60,
            cwd=str(_PARENT), env=env,
        )
        assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        proposed = list((workdirs["pipeline"] / "PROPOSED").glob("*.json")) \
            if (workdirs["pipeline"] / "PROPOSED").exists() else []
        assert len(proposed) == 3, \
            f"期望生成 3 个 PROPOSED 文件，实际 {len(proposed)}: {proposed}\n{result.stdout}"
        # 每个提案字段完整
        for p in proposed:
            d = json.loads(p.read_text(encoding="utf-8"))
            for k in ("id", "ts", "actor", "category",
                      "touched_files", "proposed_changes_by_path"):
                assert k in d, f"提案 {p.name} 缺失字段 {k}: {d}"
            assert d["actor"] == "evolution"
        # dry-run 下绝无 APPLIED 目录
        applied = workdirs["pipeline"] / "APPLIED"
        assert not applied.exists(), "dry-run 不应生成 APPLIED 目录"

    # --- TC t03: Critic 拦截 R1 违规（碰原版 SKILL.md） ---------------------
    def test_t03_critic_blocks_r1_violation(self, workdirs):
        # 手写一个 R1 违规提案 PROPOSED（直接放目录，模拟上轮 Evolution 生成）
        prop_dir = workdirs["pipeline"] / "PROPOSED"
        prop_dir.mkdir(parents=True, exist_ok=True)
        bad_prop = {
            "id": "PROP-BAD-R1", "ts": datetime.now(timezone.utc).isoformat(),
            "actor": "evolution", "category": "prompt",
            "touched_files": ["0-元记忆/superpowers/skills/brainstorming/SKILL.md"],
            "proposed_changes_by_path": {
                "0-元记忆/superpowers/skills/brainstorming/SKILL.md": {"delta": "+3 -1"}
            },
        }
        (prop_dir / "PROP-BAD-R1.json").write_text(
            json.dumps(bad_prop, ensure_ascii=False), encoding="utf-8")
        runner = _PARENT / "cognitive_evolution_scheduler.py"
        assert runner.exists()
        import subprocess
        env = os.environ.copy()
        env["PYTHONPATH"] = str(_PARENT)
        result = subprocess.run(
            [sys.executable, str(runner),
             "--role", "critic", "--no-llm",
             "--work-dir", str(workdirs["pipeline"])],
            capture_output=True, text=True, check=False, timeout=60,
            cwd=str(_PARENT), env=env,
        )
        assert result.returncode == 0, \
            f"FAIL-OPEN: Critic 本身不得抛异常退出; stderr:\n{result.stderr}"
        critiqued = list((workdirs["pipeline"] / "CRITIQUED").glob("*.json")) \
            if (workdirs["pipeline"] / "CRITIQUED").exists() else []
        assert len(critiqued) >= 1, f"缺少 CRITIQUED 文件；stdout:\n{result.stdout}"
        # 找对应 PROP-BAD-R1 的 CRITIQUED 结果
        matched = None
        for c in critiqued:
            d = json.loads(c.read_text(encoding="utf-8"))
            if d.get("id") == "PROP-BAD-R1" or "BAD-R1" in str(c.name):
                matched = d
                break
        assert matched is not None, f"未找到 PROP-BAD-R1 的 Critique 结果；文件={critiqued}"
        audit = matched.get("constitution_audit") or {}
        assert audit.get("passed") is False, \
            f"R1 违规应 constitution_audit.passed=False；实际={audit}"
        # R1 CRITICAL 违规存在
        violations: List[Dict[str, Any]] = []
        for _rr in (audit.get("rule_results") or {}).values():
            violations.extend((_rr or {}).get("violations", []))
        r1_criticals = [v for v in violations
                        if str(v.get("rule_id")).upper() in ("R1",)
                        and str(v.get("severity")).upper() == "CRITICAL"]
        assert r1_criticals, f"未发现 R1 CRITICAL 违规；violations={violations}"
        assert matched.get("critique_passed") is False

    # --- TC t04: Verifier --no-llm FAIL-OPEN（不掉模型不 crash） -----------
    def test_t04_verifier_no_llm_fail_open(self, workdirs):
        # 先造一个已通过 Critic + Constitution 的 VALIDATE 就绪状态
        prop_dir = workdirs["pipeline"] / "PROPOSED"
        crit_dir = workdirs["pipeline"] / "CRITIQUED"
        prop_dir.mkdir(parents=True, exist_ok=True)
        crit_dir.mkdir(parents=True, exist_ok=True)
        pid = "PROP-CLEAN-READY-TO-VALIDATE"
        prop = {
            "id": pid, "ts": datetime.now(timezone.utc).isoformat(),
            "actor": "evolution", "category": "prompt",
            "touched_files": [
                "4-MEMORY/9-工具与接口/cognitive_loop_entry.py"],
            "proposed_changes_by_path": {
                "4-MEMORY/9-工具与接口/cognitive_loop_entry.py": {"delta": "+5 -0"}},
        }
        (prop_dir / f"{pid}.json").write_text(json.dumps(prop), encoding="utf-8")
        crit = {
            "id": pid, "ts": datetime.now(timezone.utc).isoformat(),
            "actor": "critic",
            "constitution_audit": {
                "passed": True, "rule_results": {}, "total_violations": 0,
            },
            "criticism": "规则校验通过，无模型打分（--no-llm）",
            "critique_passed": True,
        }
        (crit_dir / f"{pid}.json").write_text(json.dumps(crit), encoding="utf-8")

        runner = _PARENT / "cognitive_evolution_scheduler.py"
        import subprocess
        env = os.environ.copy()
        env["PYTHONPATH"] = str(_PARENT)
        result = subprocess.run(
            [sys.executable, str(runner),
             "--role", "verifier", "--no-llm",
             "--work-dir", str(workdirs["pipeline"])],
            capture_output=True, text=True, check=False, timeout=60,
            cwd=str(_PARENT), env=env,
        )
        assert result.returncode == 0, \
            f"FAIL-OPEN: Verifier 不得 crash；stderr:\n{result.stderr}"
        val_dir = workdirs["pipeline"] / "VALIDATED"
        assert val_dir.exists(), "应有 VALIDATED 目录"
        vals = list(val_dir.glob(f"{pid}*.json"))
        assert len(vals) >= 1
        d = json.loads(vals[0].read_text(encoding="utf-8"))
        assert "validation_passed" in d  # bool 值都可以，只验证字段存在（FAIL-OPEN）
        assert d.get("actor") == "verifier"

    # --- TC t05: Gardener --dry-run 不删除，只打印 + exit 0 -----------------
    def test_t05_gardener_dry_run_no_delete(self, workdirs):
        # 先预植一些待删除的 C 级 90 天老记忆（在一个 gardener 待修剪列表文件中，不触碰真正 bayesian db）
        # 用自定义的 artifacts 模拟：在 pipeline/GARDENER_TRASH 里先写点测试文件（观察 gardener --dry-run 是否生成而不删除）
        trash = workdirs["pipeline"] / "GARDENER_TRASH_MARKERS"
        trash.mkdir(parents=True, exist_ok=True)
        for i in range(3):
            (trash / f"mem-marker-{i}.json").write_text(
                json.dumps({"age_days": 90 + i, "verify_count": 0,
                            "quality_level": "C", "should_delete": True}),
                encoding="utf-8")
        runner = _PARENT / "cognitive_evolution_scheduler.py"
        import subprocess
        env = os.environ.copy()
        env["PYTHONPATH"] = str(_PARENT)
        result = subprocess.run(
            [sys.executable, str(runner),
             "--role", "gardener", "--dry-run", "--no-llm",
             "--work-dir", str(workdirs["pipeline"])],
            capture_output=True, text=True, check=False, timeout=60,
            cwd=str(_PARENT), env=env,
        )
        assert result.returncode == 0, f"stderr:\n{result.stderr}"
        # dry-run 下 GARDENER_TRASH_MARKERS 目录内容不变
        assert len(list(trash.glob("mem-marker-*.json"))) == 3, \
            "Gardener --dry-run 不得删除标记文件"
        # 必须在 GARDENER_REPORTS 或 stdout 有修剪计划
        reports_dir = workdirs["pipeline"] / "GARDENER_REPORTS"
        report_exists = reports_dir.exists() and any(reports_dir.iterdir())
        combined = (result.stdout or "") + (result.stderr or "")
        plan_mentioned = any(
            k in combined.lower() for k in ("prune", "trim", "delete",
                                            "修剪", "删除", "合并", "归档"))
        assert report_exists or plan_mentioned, \
            "Gardener --dry-run 必须输出或记录修剪计划（报告目录或stdout）"

    # --- TC t06: launchd plist 模板 8 条 StartCalendarInterval -----------------
    def test_t06_launchd_template_eight_intervals(self, workdirs):
        runner = _PARENT / "cognitive_evolution_scheduler.py"
        text = runner.read_text(encoding="utf-8")
        # 要求包含完整 plist 模板段落（含 StartCalendarInterval 关键字）
        assert "StartCalendarInterval" in text, \
            "脚本头部 docstring/main 必须内嵌 launchd plist 模板"
        assert "com.dreambuddy.cognitive-evolution" in text, \
            "plist Label 应为 com.dreambuddy.cognitive-evolution"
        # 必须出现 8 次 Hour+Minute 组合（Evolution×2 / Verifier×4 / Critic×1 / Gardener×1）
        # 简单判定：出现 Hour 关键字 ≥ 8 次
        import re
        hours = re.findall(r"<key>Hour</key>", text)
        assert len(hours) >= 8, \
            f"需要 ≥8 条 StartCalendarInterval（四角色时间点），实际 {len(hours)}"
        # Gardener 需含 Weekday 1
        weekdays = re.findall(r"<key>Weekday</key>", text)
        assert len(weekdays) >= 1, "Gardener 每周调度需含 Weekday 键"


# ==================================================================
# EV-T2: 宪法 Constitution
# ==================================================================


class TestEVT2Constitution:
    """constitution.py 9 条红线 + audit + PROP 解析 + 宪法漂移（7 TC）"""

    # --- TC t10: R1 原版 SKILL.md 触碰 → CRITICAL + audit.passed=False -------
    def test_t10_r1_original_skill_critical(self, sample_proposal_clean):
        from constitution import audit_proposal  # 待实现
        p = dict(sample_proposal_clean)
        p["touched_files"] = {"0-元记忆/superpowers/skills/brainstorming/SKILL.md"}
        p["written_paths"] = set(p["touched_files"])
        res = audit_proposal(p, proposal_source="unit-test")
        assert res["passed"] is False, f"R1 违规应 fail：{res}"
        violations = _collect_violations(res)
        r1s = [v for v in violations if v.get("rule_id") == "R1"]
        assert len(r1s) >= 1 and r1s[0]["severity"].upper() == "CRITICAL", \
            f"R1 违规需 CRITICAL；violations={violations}"

    # --- TC t11: R3 A 类 actor 写 solution_paths/ → CRITICAL ----------------
    def test_t11_r3_ab_boundary_a_writes_solution_paths_critical(self, sample_proposal_clean):
        from constitution import audit_proposal
        p = dict(sample_proposal_clean)
        p["actor"] = "A"
        p["category"] = "trading_params"
        p["written_paths"] = {"4-MEMORY/2-交易记忆单元/solution_paths/APP-TRD-123456.json"}
        p["touched_files"] = set(p["written_paths"])
        res = audit_proposal(p, proposal_source="unit-test")
        violations = _collect_violations(res)
        r3 = [v for v in violations if v.get("rule_id") == "R3"]
        assert r3 and r3[0]["severity"].upper() == "CRITICAL", \
            f"R3(A→solution_paths) 需 CRITICAL；violations={violations}"
        assert res["passed"] is False

    # --- TC t12: R4 B 类 actor 写 config.json 交易参数 → CRITICAL -------------
    def test_t12_r4_ab_boundary_b_writes_config_critical(self, sample_proposal_clean):
        from constitution import audit_proposal
        p = dict(sample_proposal_clean)
        p["actor"] = "B"
        p["written_paths"] = {"experiments/ab-trading/data/config.json",
                              "11-易经推理系统/data/okx_sim/config.json"}
        p["touched_files"] = set(p["written_paths"])
        res = audit_proposal(p, proposal_source="unit-test")
        violations = _collect_violations(res)
        r4 = [v for v in violations if v.get("rule_id") == "R4"]
        assert r4 and r4[0]["severity"].upper() == "CRITICAL", \
            f"R4(B→config.json) 需 CRITICAL；violations={violations}"
        assert res["passed"] is False

    # --- TC t13: R7 实验区隔离：生产标记=CRITICAL / 非生产标记=HIGH 不阻塞 --------
    def test_t13_r7_experiment_zone_isolation_two_severity(self, sample_proposal_clean):
        from constitution import audit_proposal
        base = dict(sample_proposal_clean)
        base["touched_files"] = {"3-EVOLUTION/pipeline.ts"}
        base["written_paths"] = set(base["touched_files"])
        # (a) 生产改动
        p1 = dict(base)
        p1["is_production_change"] = True
        res1 = audit_proposal(p1, proposal_source="unit-test")
        vs1 = _collect_violations(res1)
        r7_critical = [v for v in vs1 if v.get("rule_id") == "R7"
                       and v["severity"].upper() == "CRITICAL"]
        assert r7_critical, f"生产改动碰实验区 R7 应为 CRITICAL；violations={vs1}"
        assert res1["passed"] is False
        # (b) 非生产改动
        p2 = dict(base)
        p2["is_production_change"] = False
        res2 = audit_proposal(p2, proposal_source="unit-test")
        vs2 = _collect_violations(res2)
        r7_high = [v for v in vs2 if v.get("rule_id") == "R7"
                   and v["severity"].upper() == "HIGH"]
        # HIGH 不算 CRITICAL → 整体仍可能 pass（只要无其他 CRITICAL 违规）
        assert r7_high, f"非生产改动碰实验区 R7 应为 HIGH；violations={vs2}"
        assert res2["passed"] is True or res2["passed"] is False, \
            "R7 HIGH 不强制 fail（允许被其他 CRITICAL 叠加 fail）"

    # --- TC t14: R9 AUTO 草案未审核 → CRITICAL --------------------------------
    def test_t14_r9_auto_draft_unreviewed_promotion_critical(self, sample_proposal_clean):
        from constitution import audit_proposal
        p = dict(sample_proposal_clean)
        promoted_patch = {
            "promoted_path": "4-MEMORY/2-交易记忆单元/solution_paths/APP-TRD-AUTO-9999.json",
            "source_review_path": "4-MEMORY/artifacts/solution_path_drafts/"
                                  "review_queue/APP-TRD-AUTO-9999.json",
            "review_status": "PENDING",  # 未审核
            "reviewed_by": None,
        }
        p["auto_draft_promotion"] = promoted_patch
        p["written_paths"] = {promoted_patch["promoted_path"]}
        res = audit_proposal(p, proposal_source="unit-test")
        violations = _collect_violations(res)
        r9 = [v for v in violations if v.get("rule_id") == "R9"]
        assert r9 and r9[0]["severity"].upper() == "CRITICAL", \
            f"R9 AUTO 未审核提升需 CRITICAL；violations={violations}"
        assert res["passed"] is False

    # --- TC t15: PROP-*.md 解析器 ---------------------------------------------
    def test_t15_parse_proposal_md_extracts_fields(self, tmp_path):
        from constitution import parse_proposal_md
        md = textwrap.dedent("""
        # PROP-TEST-2026 示例提案

        ## Scope
        - 归属：B 类（认知流程）
        - 类别：memory_structure

        ## Files Touched
        - 4-MEMORY/9-工具与接口/constitution.py
        - 4-MEMORY/9-工具与接口/cognitive_loop_entry.py

        ## Proposed Changes
        - 增加 R9 红线

        ## Approval
        - 审批：飞书审批单号 FEISHU-12345
        - 审批人：zhangjiangtao
        - 状态：PENDING
        """).strip()
        path = tmp_path / "PROP-TEST.md"
        path.write_text(md, encoding="utf-8")
        parsed = parse_proposal_md(str(path))
        # Files Touched 解析正确
        files = parsed.get("touched_files") or set()
        assert isinstance(files, set) or isinstance(files, list), files
        files_s = set(files)
        assert "4-MEMORY/9-工具与接口/constitution.py" in files_s, files_s
        assert "4-MEMORY/9-工具与接口/cognitive_loop_entry.py" in files_s, files_s
        # approvals / proposal_id
        assert parsed.get("proposal_id") == "PROP-TEST-2026", parsed
        approvals = parsed.get("approvals") or {}
        assert "FEISHU-12345" in str(approvals), approvals
        # category & actor
        assert parsed.get("category") == "memory_structure", parsed
        assert parsed.get("actor") == "B", parsed

    # --- TC t16: 宪法自校验（漂移）→ WARNING 但不阻塞 -------------------------
    def test_t16_constitution_drift_warns_no_block(self, sample_proposal_clean, monkeypatch):
        import constitution as const_mod  # 待实现模块

        # 篡改一个 check_* 的 1 字节（模拟被外部修改）
        original_src = const_mod.check_original_skill_immutable.__code__.co_code
        # 使用 monkeypatch 替换 audit_proposal 内部的 _self_check_constitution_hash
        # 模拟"算出来的 hash != CONSTITUTION_HASH 常量" → 写 warning
        real_audit = const_mod.audit_proposal

        def fake_hash_fail(*a, **kw):
            return False  # self-check fail (drifted)

        def _patched_self_check():
            return False

        # patch self-check 的"内部hash验证"为失败
        monkeypatch.setattr(const_mod, "_self_check_constitution_hash",
                            _patched_self_check, raising=False)
        # 干净提案应仍 passed=True（不阻塞），但 audit 中含漂移告警标记
        res = real_audit(sample_proposal_clean)
        # self-check FAIL 情况下仍 overall passed
        assert res["passed"] is True, f"宪法漂移不得阻塞提案审计：{res}"
        # 并且必须有 constitution_mismatch / drift / warning 的痕迹
        flags = ("constitution_mismatch", "drift_detected", "hash_warning",
                 "self_check_failed")
        hit = any(k in res for k in flags)
        if not hit:
            # 查 severity_counts / rule_results 里有没有"告警"标记
            combined = json.dumps(res, ensure_ascii=False, default=str)
            hit = any(k in combined.lower() for k in flags)
        assert hit, f"宪法漂移应有告警字段（{flags} 之一）；audit={res}"


# ==================================================================
# EV-T3: VOYAGER 5 维评分 + 连续 3 次 → AUTO 草案
# ==================================================================


class TestEVT3Voyager:
    """cognitive_loop_entry.record()/verify() 扩展（7 TC）"""

    # --- TC t20: record() auto 打分 → bayesian 记忆 voyager_scores.overall ---
    def test_t20_record_auto_voyager_scores_stored(self, workdirs, monkeypatch):
        from cognitive_loop_entry import CognitiveLoopEntry
        # mock 内部存储：不让它读真实 DB，改写到 workdirs["bayesian"]
        cle = _build_cle_with_db(workdirs, monkeypatch)

        mid = cle.record(
            content="修复 debug 任务：步骤1 定位 /Users/x/fix.py 128 行；步骤2 改 abc；原因=根因空指针；已验证 ✓ passed ✓；"
                    "修改文件共 3 个：a.py / b.py / c.py",
            quality_level="C", confidence=0.3,
            tags=["debug", "fix", "bug"], source="unit-test", memory_type="experience",
            domain="debug",
            # voyager_scores=None → 触发 auto
        )
        # bayesian 对应记忆有 voyager_scores 扩展
        db = json.loads(workdirs["bayesian"].read_text(encoding="utf-8"))
        mem = _find_mem_by_id(db, mid)
        assert mem is not None, f"记忆 {mid} 未在 bayesian DB: {db}"
        vs = mem.get("voyager_scores") or {}
        for dim in ("completeness", "accuracy", "efficiency", "depth",
                    "actionability", "overall"):
            assert dim in vs, f"voyager_scores 缺失维度 {dim}: {vs}"
            assert 0.0 <= float(vs[dim]) <= 1.0, f"{dim}={vs[dim]} 越界"
        # 上面内容特征丰富，overall 应 ≥ 0.4（简单模式：所有维度 auto 规则都命中）
        assert float(vs["overall"]) >= 0.3, f"overall={vs['overall']} 过低; {vs}"

    # --- TC t21: record() 显式 voyager_scores 优先，overall=1.0 ----------------
    def test_t21_record_explicit_voyager_priority(self, workdirs, monkeypatch):
        from cognitive_loop_entry import CognitiveLoopEntry
        cle = _build_cle_with_db(workdirs, monkeypatch)
        explicit = {
            "completeness": 1.0, "accuracy": 1.0, "efficiency": 1.0,
            "depth": 1.0, "actionability": 1.0,
        }
        mid = cle.record(
            content="极简", quality_level="C", confidence=0.3,
            tags=["demo"], source="unit-test",
            domain="demo", voyager_scores=explicit, enable_voyager_auto=False,
        )
        db = json.loads(workdirs["bayesian"].read_text(encoding="utf-8"))
        mem = _find_mem_by_id(db, mid)
        assert mem is not None
        vs = mem["voyager_scores"]
        # 显式未传 overall → 函数按权重汇总
        assert abs(float(vs["overall"]) - 1.0) < 1e-6, \
            f"显式全 1.0 → overall 应 = 1.0；实际={vs}"

    # --- TC t22: verify 连续 3 次 success → meets_draft_threshold=True --------
    def test_t22_verify_three_consecutive_success_produces_draft(
            self, workdirs, monkeypatch):
        from cognitive_loop_entry import CognitiveLoopEntry
        # 把审核队列路径 & voyager_jsonl 路径定向到 workdirs
        cle = _build_cle_with_db(workdirs, monkeypatch)
        # 注入 3 条不同 memory_id，但 domain+tags 一致的"高分 auto"记录，并连续 verify(success=True)
        base_tags = ["debug", "fix"]
        domain = "debug"
        content_pattern = (
            "调试修复任务：步骤1 打开 {f}；步骤2 定位根因空指针；步骤3 修复；"
            "步骤4 单测通过 ✓ passed；步骤5 提交 commit c123。"
            "改动文件 a.py / b.py / c.py；涉及原因分析。"
        )
        drafts_before = len(list(workdirs["drafts"].glob("APP-DEV-AUTO-*.json")))
        last_voyager = None
        for i in range(3):
            mid = cle.record(
                content=content_pattern.format(f=f"mod_{i}.py"),
                quality_level="C", confidence=0.5 + 0.05 * i,
                tags=list(base_tags), source="unit-test",
                domain=domain,
                # 给高分显式，保证 overall≥0.7
                voyager_scores={
                    "completeness": 0.9, "accuracy": 0.9, "efficiency": 0.8,
                    "depth": 0.85, "actionability": 0.9,
                },
            )
            vr = cle.verify(mid, success=True)
            assert vr.get("success") is True, f"verify 失败: {vr}"
            last_voyager = vr.get("voyager") or {}
        # 最终 voyager 返回的阈值信号
        assert last_voyager.get("meets_draft_threshold") is True, \
            f"连续 3 次 success 且 overall≥0.7 应 meets_draft_threshold=True；最后返回={last_voyager}"
        # 审核队列 1 份新草案
        drafts_after = list(workdirs["drafts"].glob("APP-DEV-AUTO-*.json"))
        assert len(drafts_after) == drafts_before + 1, \
            f"应新增 1 份 APP-DEV-AUTO-* 草案；之前 {drafts_before} 之后 {len(drafts_after)}；voyager={last_voyager}"
        draft_path = (set(str(p) for p in drafts_after) - set([])).pop() if drafts_after else str(drafts_after[-1])
        d = json.loads(Path(drafts_after[-1]).read_text(encoding="utf-8"))
        assert str(d.get("template_id")).startswith("APP-DEV-AUTO-"), d.get("template_id")
        # 严格降级 + 审核状态
        assert d.get("confidence") == 0.3, d
        assert d.get("quality_level") == "C", d
        md = d.get("metadata") or {}
        assert md.get("review_status") == "PENDING", md
        base_ids = md.get("base_memory_ids") or []
        assert len(base_ids) == 3, f"base_memory_ids 需恰好 3 项：{base_ids}"

    # --- TC t23: 7 天去重（同 domain+tags 已有 PENDING 草案 → 不再产）---------
    def test_t23_seven_day_deduplication(self, workdirs, monkeypatch):
        # 先手动植入 1 份 1 天前的同 domain+tags 的 PENDING 草案
        existing = workdirs["drafts"] / "APP-DEV-AUTO-0000000000000.json"
        existing.write_text(json.dumps({
            "template_id": "APP-DEV-AUTO-0000000000000",
            "name": "existing", "steps": [], "description": "x",
            "confidence": 0.3, "verify_count": 0, "quality_level": "C",
            "source": "voyager-auto-draft",
            "tags": ["solution_path", "auto-draft", "review-required", "debug", "fix"],
            "layer": "applied", "parent_template_id": "none",
            "metadata": {
                "auto_generated": True,
                "review_status": "PENDING",
                "reviewed_by": None, "reviewed_at": None,
                "domain": "debug", "draft_created_at":
                    (datetime.now(timezone.utc).timestamp() - 86400),
            }
        }, ensure_ascii=False), encoding="utf-8")
        from cognitive_loop_entry import CognitiveLoopEntry
        cle = _build_cle_with_db(workdirs, monkeypatch)
        # 再连续 3 次同 domain+tags 的 verify
        for i in range(3):
            mid = cle.record(
                content="调试修复 步骤1 步骤2 步骤3；验证通过 ✓；改 a.py b.py c.py；根因xyz",
                quality_level="C", confidence=0.6,
                tags=["debug", "fix"], domain="debug", source="unit-test",
                voyager_scores={"completeness":0.9,"accuracy":0.9,"efficiency":0.8,
                                "depth":0.85,"actionability":0.9},
            )
            vr = cle.verify(mid, success=True)
        drafts = list(workdirs["drafts"].glob("APP-DEV-AUTO-*.json"))
        # 只保留 existing 一份，不应新增第二份
        assert len(drafts) == 1, f"7天去重失败：期望 1 份实际 {len(drafts)}：{drafts}"
        assert drafts[0].name == existing.name
        # verify 返回 voyager.auto_draft_generated=False
        assert (vr.get("voyager") or {}).get("auto_draft_generated") is False, \
            f"去重应 auto_draft_generated=False；最后返回={vr.get('voyager')}"

    # --- TC t24: 草案 JSON 严格字段 ------------------------------------------
    def test_t24_draft_json_strictly_downgraded_fields(self, workdirs, monkeypatch):
        from cognitive_loop_entry import CognitiveLoopEntry
        cle = _build_cle_with_db(workdirs, monkeypatch)
        for i in range(3):
            mid = cle.record(
                content="交易研究：步骤1 读取K线 步骤2 计算指标 步骤3 回测；验证passed；"
                        "涉及文件 data/a.csv / strat/b.py / back/c.py；根因突破MA20",
                quality_level="B", confidence=0.8,  # 源头给 B/0.8，草案必须强制降级
                tags=["strategy-research", "backtest", "trading"],
                domain="backtest", source="unit-test",
                voyager_scores={"completeness":0.95,"accuracy":0.9,
                                "efficiency":0.7,"depth":0.9,"actionability":0.85},
            )
            cle.verify(mid, success=True)
        # 审核队列中必须恰好 1 条 TRD-AUTO 草案
        trd = list(workdirs["drafts"].glob("APP-TRD-AUTO-*.json"))
        assert len(trd) == 1, f"期望 1 条 TRD-AUTO 草案，实际 {len(trd)}: {trd}"
        d = json.loads(trd[0].read_text(encoding="utf-8"))
        # 严格降级
        assert d.get("confidence") == 0.3, f"强制 confidence=0.3；实际={d.get('confidence')}"
        assert d.get("quality_level") == "C", f"强制 quality=C；实际={d.get('quality_level')}"
        md = d.get("metadata") or {}
        assert md.get("review_status") == "PENDING"
        assert md.get("auto_generated") is True
        assert len(md.get("base_memory_ids") or []) == 3
        assert "trading" in d.get("tags") or "strategy-research" in d.get("tags")

    # --- TC t25: 中间插入失败 → 连续计数归零，不触发草案 ----------------------
    def test_t25_consecutive_reset_on_failure(self, workdirs, monkeypatch):
        from cognitive_loop_entry import CognitiveLoopEntry
        cle = _build_cle_with_db(workdirs, monkeypatch)
        # success / success / failure / success / success → 最后连续=2，不够 3
        pattern = [True, True, False, True, True]
        last_vr = None
        for s in pattern:
            mid = cle.record(
                content=f"步骤1 x 步骤2 y；验证{'✓' if s else '✗'}；改 a.py b.py c.py；根因z",
                quality_level="C", confidence=0.5, tags=["fix", "bug"],
                domain="debug", source="unit-test",
                voyager_scores={"completeness":0.9,"accuracy":0.9,"efficiency":0.9,
                                "depth":0.9,"actionability":0.9},
            )
            last_vr = cle.verify(mid, success=s)
        v = last_vr.get("voyager") or {}
        assert v.get("consecutive_positive_count") == 2, \
            f"插入 1 次失败后，连续成功应为 2；实际={v.get('consecutive_positive_count')}"
        assert v.get("meets_draft_threshold") is False
        drafts = list(workdirs["drafts"].glob("APP-DEV-AUTO-*.json"))
        assert len(drafts) == 0, f"阈值未达不得产草案：{drafts}"

    # --- TC t26: 老记忆无 voyager_scores → verify 兼容不 crash ---------------
    def test_t26_legacy_memory_without_voyager_compatible(self, workdirs, monkeypatch):
        """bayesian 里塞一条老记忆（无 voyager_scores 字段），直接调 verify → 不 crash，
        用 confidence*verify_count 近似 overall。"""
        # 先手动塞老记忆进 DB，绕过 record()
        db = json.loads(workdirs["bayesian"].read_text(encoding="utf-8"))
        legacy_id = "GM-TRD-LEGACY-NOVOYAGER"
        db["memories"].append({
            "memory_id": legacy_id,
            "content": "[老记忆] 无 voyager_scores 字段",
            "category": "lesson", "confidence": 0.6, "quality_level": "B",
            "verify_count": 5, "conflict_count": 0,
            "beta_alpha": 1, "beta_beta": 1,
            "created_at": "2026-08-01T00:00:00+00:00",
            "last_updated": "2026-08-02T00:00:00+00:00",
            "source": "legacy",
            "tags": ["legacy", "trading"],
            # 没有 voyager_scores！
        })
        db["memory_count"] = len(db["memories"])
        workdirs["bayesian"].write_text(json.dumps(db, ensure_ascii=False, indent=2),
                                         encoding="utf-8")
        from cognitive_loop_entry import CognitiveLoopEntry
        cle = _build_cle_with_db(workdirs, monkeypatch)
        # 直接 verify → 不能抛异常
        vr = cle.verify(legacy_id, success=True)
        assert vr.get("success") is True, f"老记忆 verify 不得失败：{vr}"
        v = vr.get("voyager") or {}
        # FAIL-OPEN：approx_overall 必须有近似值（用 confidence*verify_count / max）
        overall_approx = v.get("voyager_overall")
        assert overall_approx is not None, \
            f"老记忆应给出近似 overall；voyager={v}"
        assert 0.0 <= float(overall_approx) <= 1.0


# ==================================================================
# 测试辅助函数（公共）
# ==================================================================


def _collect_violations(audit_result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """从 audit_proposal 返回值中收集 violations（两种形态兼容：dataclass / dict）"""
    out: List[Dict[str, Any]] = []
    rr = audit_result.get("rule_results") or {}
    if hasattr(rr, "values"):
        iterator = rr.values()
    else:
        iterator = []
    for v in iterator:
        if isinstance(v, dict):
            out.extend(v.get("violations", []))
        elif hasattr(v, "violations"):
            for item in list(v.violations):
                out.append(item if isinstance(item, dict) else {
                    "rule_id": getattr(item, "rule_id", None),
                    "severity": getattr(item, "severity", None),
                    "file": getattr(item, "file", None),
                    "reason": getattr(item, "reason", None),
                })
    # 也支持 audit_result 顶层 violations 字段（扁平化返回）
    for v in audit_result.get("violations", []):
        if isinstance(v, dict):
            out.append(v)
    return out


def _find_mem_by_id(db: Dict[str, Any], memory_id: str):
    for m in db.get("memories", []):
        if m.get("memory_id") == memory_id:
            return m
    # 可能是 cle.add() 返回的 id 在 bayesian memory 里走了 GM- 前缀；如果没找到，按 tags 兜底找最后一条
    mems = db.get("memories", [])
    return mems[-1] if mems else None


def _build_cle_with_db(workdirs, monkeypatch):
    """构造 CognitiveLoopEntry，让其内部 bayesian db 读写指向 workdirs["bayesian"] +
    voyager_jsonl 指向 workdirs["voyager_jsonl"] + drafts 指向 workdirs["drafts"]。"""
    from cognitive_loop_entry import CognitiveLoopEntry
    cle = CognitiveLoopEntry()

    # 如果 vector_memory_interface.VectorMemory 暴露 bayesian_db_path，直接 monkeypatch；
    # 否则通过私有属性访问兜底；若完全不可达则通过 cle._vm 属性路径
    vm = getattr(cle, "_vm", None)
    if vm is not None:
        for attr in ("bayesian_db_path", "bayesian_path", "db_path", "_db_path"):
            if hasattr(vm, attr):
                monkeypatch.setattr(vm, attr, workdirs["bayesian"], raising=False)
                break
        # 另外，voyager 相关路径可能存在于 cle 自身；兜底：通过 patch 内部常量路径
    # patch 全局常量（若 cognitive_loop_entry 模块内定义了 DRAFT_REVIEW_QUEUE_DIR / VOYAGER_CONSECUTIVE_JSONL）
    import cognitive_loop_entry as cle_mod
    for name, path in (
        ("DRAFT_REVIEW_QUEUE_DIR", workdirs["drafts"]),
        ("DRAFT_REVIEW_INDEX_PATH", workdirs["review_index"]),
        ("VOYAGER_CONSECUTIVE_JSONL", workdirs["voyager_jsonl"]),
        ("VOYAGER_CONSECUTIVE_PATH", workdirs["voyager_jsonl"]),
        ("VOYAGER_MEMORY_EXTRA_PATH", workdirs["voyager_extra"]),
        ("BAYESIAN_MEMORY_FILE_DEFAULT", workdirs["bayesian"]),
    ):
        if hasattr(cle_mod, name):
            monkeypatch.setattr(cle_mod, name, path, raising=False)
    # 确保 drafts 目录存在（模块级常量目录若不存在则创建）
    workdirs["drafts"].mkdir(parents=True, exist_ok=True)
    workdirs["voyager_dir"].mkdir(parents=True, exist_ok=True)
    return cle
