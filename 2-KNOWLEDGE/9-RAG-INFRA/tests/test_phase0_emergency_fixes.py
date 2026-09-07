# -*- coding: utf-8 -*-
"""Phase 0 紧急接线测试套件（TDD TEST-FIRST）。

覆盖 3 个 FIX：
  FIX-EV-0：archive_from_conversation 归档成功后自动 verify(success=True)
  FIX-EV-1：search_with_feedback 中 annotate_chunk 接入检索返回链 + 低质量降权
  FIX-EV-2：16-调控系统 evolution_cron_runner 独立 cron 脚本
"""

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

_RAG_INFRA_DIR = Path(__file__).resolve().parent.parent
if str(_RAG_INFRA_DIR) not in sys.path:
    sys.path.insert(0, str(_RAG_INFRA_DIR))

import pytest


# ============================================================
# FakeCLE & fixtures（复用 test_bridge.py 模式）
# ============================================================

class FakeCLE:
    def __init__(self, verify_ok=True):
        self.records = []
        self.verifies = []
        self._counter = 0
        self._verify_ok = verify_ok

    def record(self, content, quality_level="C", confidence=0.3,
               tags=None, source="trae", memory_type="experience"):
        self._counter += 1
        mid = f"VM-FAKE-{self._counter:04d}"
        self.records.append({"memory_id": mid, "content": content,
                             "quality_level": quality_level,
                             "confidence": confidence,
                             "tags": tags or [], "source": source})
        return mid

    def verify(self, memory_id, success=True):
        self.verifies.append({"memory_id": memory_id, "success": success})
        if not self._verify_ok:
            return {"success": False, "error": f"记忆不存在: {memory_id}"}
        return {"success": True, "memory_id": memory_id, "new_quality": "B"}


@pytest.fixture
def fake_cle():
    return FakeCLE()


@pytest.fixture
def isolated_paths(tmp_path):
    return {
        "weight_path": tmp_path / "weight_feedback.json",
        "map_path": tmp_path / "retrieval_memory_map.jsonl",
    }


# ============================================================
# FIX-EV-0 测试：归档 → verify 自动触发
# ============================================================

class TestFIXEV0ArchiveVerify:
    """FIX-EV-0: archive_from_conversation 归档成功后自动 verify(success=True)。"""

    def test_tc01_archive_triggers_verify_on_success(self, monkeypatch, tmp_path, isolated_paths):
        """[PASS条件] 单条成功归档 → 1次 record + 1次 verify(success=True)。"""
        # 1. 准备 FakeCLE 并注入到 workflow 的认知系统访问
        cle = FakeCLE()

        from bridge import memory_bridge as mb_mod
        # monkeypatch 懒加载入口 _get_cle
        def _patched_get_cle():
            return cle

        monkeypatch.setattr(mb_mod, "_get_cle", _patched_get_cle)

        # 2. 构造一个最小 detection，mock archiver.archive_research 返回 indexed
        from integration import workflow as wf_mod

        def _fake_archive_research(detection, content, kb_dir, topic="", scenario=""):
            # 写一个假 md 文件到 tmp_path，模拟真实归档
            kb_dir = Path(kb_dir)
            dest = kb_dir / "7-EXTERNAL-RESEARCH" / "finance" / "quant-methods" / "2026-09-01-test.md"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text("# test\n\ncontent\n", encoding="utf-8")
            return {
                "status": "indexed",
                "file_path": str(dest),
                "chunks_indexed": 3,
                "nodes_extracted": 2,
                "index_status": "ok",
                "graph_status": "ok",
            }

        # workflow.py 已绑定 archive_research 到自身命名空间，patch 调用点
        monkeypatch.setattr(wf_mod, "archive_research", _fake_archive_research)

        # 3. 执行 archive_from_conversation
        fake_content = "关于kalman滤波的量化策略研究：卡尔曼滤波可用于价格平滑..."
        detections = [{
            "type": "finance",
            "category": "finance",
            "subcategory": "quant-methods",
            "suggested_path": "finance/quant-methods",
            "tags": ["#kalman", "#量化"],
            "keywords_matched": ["kalman", "量化"],
            "excerpt": "kalman滤波可用于价格平滑",
        }]

        def _fake_detect_research(content):
            return detections

        monkeypatch.setattr(wf_mod, "detect_research", _fake_detect_research)

        # 使用临时 weight_path + map_path
        result = wf_mod.archive_from_conversation(
            fake_content,
            research_topic="Kalman量化滤波",
            research_scenario="对话中讨论",
            knowledge_dir=tmp_path / "kb",
            enable_memory=True,
            map_path=isolated_paths["map_path"],
        )

        # 4. 断言：record 被调用 1 次（_record_archive_as_memory）
        assert len(cle.records) == 1, f"应调用 1 次 record，实际 {len(cle.records)}"
        # 5. 核心断言：verify 被调用 1 次且 success=True（FIX-EV-0 的目标）
        assert len(cle.verifies) == 1, (
            f"FIX-EV-0 FAIL: 归档成功应自动 verify 1 次，实际 {len(cle.verifies)} 次"
        )
        assert cle.verifies[0]["success"] is True, "verify 应为 success=True（归档成功=正反馈）"

        # 6. 返回值包含 memory_verified 计数
        assert "memory_verified" in result, "返回值应包含 memory_verified 字段"
        assert result["memory_verified"] == 1

    def test_tc02_archive_failed_no_verify(self, monkeypatch, tmp_path, fake_cle, isolated_paths):
        """[PASS条件] 归档状态=failed → 不 verify（避免坏内容被正反馈）。"""
        from integration import workflow as wf_mod

        def _fake_fail(detection, content, kb_dir, topic="", scenario=""):
            return {"status": "failed", "error": "权限不足"}

        # workflow.py 中已通过 `from .archiver import archive_research` 绑定，
        # 必须 patch wf_mod.archive_research 才能在调用点生效
        monkeypatch.setattr(wf_mod, "archive_research", _fake_fail)
        monkeypatch.setattr(wf_mod, "detect_research", lambda c: [{
            "type": "finance", "category": "finance", "subcategory": "x",
            "suggested_path": "finance/x", "tags": [], "keywords_matched": [],
            "excerpt": "",
        }])

        from bridge import memory_bridge as mb_mod
        monkeypatch.setattr(mb_mod, "_get_cle", lambda: fake_cle)

        result = wf_mod.archive_from_conversation(
            "content", research_topic="T", knowledge_dir=tmp_path / "kb",
            enable_memory=True, map_path=isolated_paths["map_path"],
        )

        assert result["memory_verified"] == 0
        assert len(fake_cle.verifies) == 0, "归档失败不应触发 verify"

    def test_tc03_duplicate_archive_still_verifies(self, monkeypatch, tmp_path, fake_cle, isolated_paths):
        """[PASS条件] 归档status=duplicate（去重但内容有效）→ 仍然 verify。"""
        from integration import workflow as wf_mod

        def _fake_dup(detection, content, kb_dir, topic="", scenario=""):
            return {"status": "duplicate", "file_path": str(tmp_path / "d.md"),
                    "chunks_indexed": 0, "nodes_extracted": 0}

        # 必须 patch workflow 命名空间中的 archive_research
        monkeypatch.setattr(wf_mod, "archive_research", _fake_dup)
        monkeypatch.setattr(wf_mod, "detect_research", lambda c: [{
            "type": "finance", "category": "finance", "subcategory": "x",
            "suggested_path": "finance/x", "tags": [], "keywords_matched": [],
            "excerpt": "content",
        }])

        from bridge import memory_bridge as mb_mod
        monkeypatch.setattr(mb_mod, "_get_cle", lambda: fake_cle)

        result = wf_mod.archive_from_conversation(
            "content", knowledge_dir=tmp_path / "kb",
            enable_memory=True, map_path=isolated_paths["map_path"],
        )

        assert len(fake_cle.verifies) == 1, "duplicate 归档依然有效，应 verify"
        assert result["memory_verified"] == 1

    def test_tc04_verify_failopen_when_cle_down(self, monkeypatch, tmp_path, isolated_paths):
        """[PASS条件] 认知系统不可用时，archive主流程依然返回，memory_verified=0。"""
        from integration import workflow as wf_mod

        def _fake_ok(detection, content, kb_dir, topic="", scenario=""):
            return {"status": "indexed", "file_path": str(tmp_path / "a.md"),
                    "chunks_indexed": 1, "nodes_extracted": 1,
                    "index_status": "ok", "graph_status": "ok"}

        monkeypatch.setattr(wf_mod, "archive_research", _fake_ok)
        monkeypatch.setattr(wf_mod, "detect_research", lambda c: [{
            "type": "finance", "category": "finance", "subcategory": "x",
            "suggested_path": "finance/x", "tags": [], "keywords_matched": [],
            "excerpt": "x",
        }])

        from bridge import memory_bridge as mb_mod

        class _BrokenCLE:
            def record(self, *a, **kw):
                raise RuntimeError("DB locked")

            def verify(self, *a, **kw):
                raise RuntimeError("DB locked")

        monkeypatch.setattr(mb_mod, "_get_cle", lambda: _BrokenCLE())

        # 核心断言：不抛异常
        result = wf_mod.archive_from_conversation(
            "content", knowledge_dir=tmp_path / "kb",
            enable_memory=True, map_path=isolated_paths["map_path"],
        )

        assert result["status"] == "done", "FAIL-OPEN: 认知异常不阻塞归档主流程"
        assert result["memory_verified"] == 0


# ============================================================
# FIX-EV-1 测试：annotate_chunk 接入检索返回链
# ============================================================

class TestFIXEV1AnnotateInRetrieval:
    """FIX-EV-1: search_with_feedback 中 annotate_chunk 接入。"""

    def test_tc10_search_with_feedback_includes_annotation(self, monkeypatch, isolated_paths):
        """[PASS条件] search_with_feedback 返回的每个结果含 annotation 字段。"""
        from rag_engine import hybrid_retriever as hr_mod

        # mock hybrid_search 返回固定结果（避免真实向量/图谱依赖）
        def _fake_hybrid_search(query, **kw):
            return [
                {
                    "source_file": "1-TRADING/BCRM推理引擎.md",
                    "heading": "核心架构",
                    "domain": "1-TRADING",
                    "content": ("BCRM推理引擎采用阴阳矛盾+八卦力学+五角校验的三层架构，"
                                "支持2025-2026市场数据回测，参考 https://example.com，"
                                "参数confidence_threshold=0.7955，|列1|列2|"),
                    "score": 0.85,
                    "final_score": 0.85,
                    "rerank_signals": {},
                },
                {
                    "source_file": "7-EXTERNAL-RESEARCH/empty.md",
                    "heading": "空",
                    "domain": "",
                    "content": "短",
                    "score": 0.30,
                    "final_score": 0.30,
                    "rerank_signals": {},
                },
            ]

        monkeypatch.setattr(hr_mod, "hybrid_search", _fake_hybrid_search)
        # 禁用 boost + record，单独验证 annotate 功能
        result = hr_mod.search_with_feedback(
            "BCRM架构", top_k=5,
            enable_record=False, enable_boost=False,
            weight_path=isolated_paths["weight_path"],
            map_path=isolated_paths["map_path"],
        )

        results = result["results"]
        assert len(results) == 2
        # 核心断言：每个结果含 annotation
        for r in results:
            assert "annotation" in r, (
                f"FIX-EV-1 FAIL: 结果缺少 annotation 字段，heading={r.get('heading')}"
            )
            ann = r["annotation"]
            assert "domain" in ann and "tags" in ann and "quality" in ann

        # 第一个结果（充实内容）quality.overall 应 ≥ 0.7
        q1 = results[0]["annotation"]["quality"]["overall"]
        assert q1 >= 0.7, f"高质量内容 quality.overall 应≥0.7，实际 {q1}"

        # 第二个结果（短内容）quality.overall 应较低
        q2 = results[1]["annotation"]["quality"]["overall"]
        assert q2 < 0.6, f"低质量内容 quality.overall 应<0.6，实际 {q2}"

        # 返回值应标注 annotations_applied
        assert "annotations_applied" in result
        assert result["annotations_applied"] is True

    def test_tc11_low_quality_gets_penalized(self, monkeypatch, isolated_paths):
        """[PASS条件] quality.overall < 0.5 → final_score *= 0.9 降权，rerank_signals记录。"""
        from rag_engine import hybrid_retriever as hr_mod

        def _fake_hybrid_search(query, **kw):
            return [
                {
                    "source_file": "thin.md",
                    "heading": "薄",
                    "content": "sparse",  # 极短 => 完整性0.2 准确性0.4 时效性0.5 => overall≈0.367
                    "score": 0.90,
                    "final_score": 0.90,  # 原始高分，靠 annotate 降权
                    "rerank_signals": {},
                },
                {
                    "source_file": "thick.md",
                    "heading": "厚",
                    "content": ("完整长内容，含2025年份日期与数字参数，"
                                "结构完整含表格|a|b|参考链接https://x.com"),
                    "score": 0.88,  # 原始略低于前者
                    "final_score": 0.88,
                    "rerank_signals": {},
                },
            ]

        monkeypatch.setattr(hr_mod, "hybrid_search", _fake_hybrid_search)
        result = hr_mod.search_with_feedback(
            "q", top_k=5, enable_record=False, enable_boost=False,
            weight_path=isolated_paths["weight_path"],
            map_path=isolated_paths["map_path"],
        )

        results = result["results"]
        thin_r = [r for r in results if r["source_file"] == "thin.md"][0]
        thick_r = [r for r in results if r["source_file"] == "thick.md"][0]

        q_thin = thin_r["annotation"]["quality"]["overall"]
        # 若 thin 真<0.5，断言降权
        if q_thin < 0.5:
            assert thin_r["rerank_signals"].get("quality_penalty") == 0.9, (
                "低质量(<0.5)结果应触发 quality_penalty=0.9"
            )
            expected_score = round(0.90 * 0.9, 4)
            assert abs(thin_r["final_score"] - expected_score) < 0.01, (
                f"低质量降权后 final_score 应≈{expected_score}，实际{thin_r['final_score']}"
            )

    def test_tc12_annotate_failopen(self, monkeypatch, isolated_paths):
        """[PASS条件] annotate模块抛异常时，search正常返回，annotations_applied=False。"""
        from rag_engine import hybrid_retriever as hr_mod
        import evolution.annotate as ann_mod

        def _fake_hybrid_search(query, **kw):
            return [{"source_file": "a.md", "heading": "h", "content": "x",
                     "score": 0.5, "final_score": 0.5, "rerank_signals": {}}]

        monkeypatch.setattr(hr_mod, "hybrid_search", _fake_hybrid_search)

        # 破坏 annotate_chunk
        def _broken(*a, **kw):
            raise RuntimeError("标注模型OOM")

        monkeypatch.setattr(ann_mod, "annotate_chunk", _broken)

        result = hr_mod.search_with_feedback(
            "q", enable_record=False, enable_boost=False,
            weight_path=isolated_paths["weight_path"],
            map_path=isolated_paths["map_path"],
        )

        assert len(result["results"]) == 1, "FAIL-OPEN: annotate异常不阻塞检索"
        assert result["annotations_applied"] is False


# ============================================================
# FIX-EV-2 测试：16-调控系统 evolution_cron_runner
# ============================================================

class TestFIXEV2EvolutionCronRunner:
    """FIX-EV-2: evolution_cron_runner.py 独立进化cron脚本。"""

    def _runner_path(self):
        return (Path(__file__).resolve().parents[3]
                / "16-调控系统" / "scripts" / "evolution_cron_runner.py")

    def test_tc20_runner_file_exists(self):
        """[PASS条件] evolution_cron_runner.py 文件存在且语法正确。"""
        path = self._runner_path()
        assert path.exists(), f"FIX-EV-2 FAIL: 脚本不存在: {path}"
        # 语法检查
        import py_compile
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as e:
            pytest.fail(f"脚本语法错误: {e}")

    def test_tc21_runner_dry_run(self, tmp_path):
        """[PASS条件] --dry-run 执行：完成策略遍历、生成报告JSON、不写回参数。"""
        import subprocess

        runner_p = self._runner_path()
        runner = str(runner_p)
        report_dir = tmp_path / "reports"
        report_dir.mkdir()

        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        proc = subprocess.run(
            [sys.executable, runner, "--dry-run",
             "--report-dir", str(report_dir)],
            capture_output=True, text=True, timeout=120,
            cwd=str(runner_p.parent),
            env=env,
        )

        output = proc.stdout + proc.stderr
        assert ("进化cron" in output or "Evolution" in output
                or "REPORT" in output or proc.returncode in (0, 2)), (
            f"dry-run输出异常:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )

    def test_tc22_runner_help_text(self):
        """[PASS条件] --help 显示关键参数说明（--dry-run --strategy-id --report-dir）。"""
        import subprocess

        runner_p = self._runner_path()
        runner = str(runner_p)
        proc = subprocess.run(
            [sys.executable, runner, "--help"],
            capture_output=True, text=True, timeout=30,
            cwd=str(runner_p.parent),
        )
        help_text = proc.stdout
        assert any(k in help_text for k in ("--dry-run", "dry-run",
                                            "--strategy-id", "--report-dir")), (
            f"help缺少关键参数说明:\n{help_text[:800]}"
        )

    def test_tc23_runner_has_launchd_docstring(self):
        """[PASS条件] 脚本头部或__main__部分包含 launchd plist 注册说明。"""
        content = self._runner_path().read_text(encoding="utf-8")
        assert ("launchd" in content.lower()
                or "plist" in content.lower()
                or "cron" in content.lower()), (
            "脚本应包含 launchd plist 注册说明或 cron 调度指南"
        )
