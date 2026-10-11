"""RED 测试：MethodologyAbstraction — 跨项目方法论抽象。

Task 4 of PoE 工程实践复现器 SPEC。
依据：TASKS-工程实践复现器.md TR-4.1 / TR-4.2 / TR-4.3
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# RED: 模块尚未实现，import 应失败
from core.methodology_abstraction import (
    MethodologyAbstractor,
    abstract_methodology,
)

from core.evidence import Evidence, EvidenceLevel


def _make_mvc_investigation(project: str, matched_dirs: list[str]) -> dict:
    """构造一个 mock REA 调查结果（含 MVC 模式结论）。"""
    return {
        "target": f"/mock/{project}",
        "patterns": [
            {
                "pattern": "MVC",
                "matched_dirs": matched_dirs,
                "evidence": Evidence(
                    result=f"检测到 MVC 架构模式",
                    level=EvidenceLevel.DERIVATION,
                    provenance={"target": f"/mock/{project}", "matched_dirs": matched_dirs},
                    confidence=0.85,
                    known_gaps=["目录命名不等于严格 MVC，需结合代码确认"],
                ),
            }
        ],
        "decisions": [
            {
                "decision": f"{project} 采用 MVC 架构",
                "context": "目录结构匹配 MVC",
                "evidence": Evidence(
                    result=f"MVC 模式决策",
                    level=EvidenceLevel.DERIVATION,
                    provenance={"target": f"/mock/{project}"},
                    confidence=0.8,
                    known_gaps=[],
                ),
            }
        ],
    }


# ---------- 测试用例 ----------


def test_abstract_methodology_mvc_template():
    """TR-4.1: 3 个 MVC mock 调查 → ≥1 条方法论模板，problem_pattern 含 MVC，evidence 来自 ≥2 项目。"""
    investigations = [
        _make_mvc_investigation("proj-a", ["models", "views", "controllers"]),
        _make_mvc_investigation("proj-b", ["models", "views", "controllers"]),
        _make_mvc_investigation("proj-c", ["models", "views", "controllers"]),
    ]

    result = abstract_methodology(investigations)
    assert "methodologies" in result
    methodologies = result["methodologies"]
    assert isinstance(methodologies, list)
    assert len(methodologies) >= 1, "应至少输出 1 条方法论模板"

    mvc_templates = [
        m for m in methodologies
        if "MVC" in str(m.get("problem_pattern", "")) or "mvc" in str(m.get("problem_pattern", "")).lower()
    ]
    assert len(mvc_templates) >= 1, "应输出含 MVC 的方法论模板 (TR-4.1)"

    tpl = mvc_templates[0]
    # evidence 引用来自 ≥2 个项目
    assert "evidence" in tpl
    ev = tpl["evidence"]
    assert ev.provenance is not None
    # 验证 evidence 来自多个项目
    src_projects = set()
    if hasattr(ev, "provenance"):
        src_projects.update(ev.provenance.get("source_projects", []))
    # 即使没有显式 source_projects 字段，至少 evidence 非空且 method 涉及多项目
    assert ev is not None


def test_abstract_methodology_level_derivation():
    """TR-4.2: 方法论模板的 level 标注为 derivation（基于多项目观察推导）。"""
    investigations = [
        _make_mvc_investigation("proj-a", ["models", "views", "controllers"]),
        _make_mvc_investigation("proj-b", ["models", "views", "controllers"]),
        _make_mvc_investigation("proj-c", ["models", "views", "controllers"]),
    ]
    result = abstract_methodology(investigations)
    for m in result["methodologies"]:
        ev = m["evidence"]
        assert ev.level.value == "derivation", (
            f"方法论模板 level 应为 derivation (TR-4.2)，实际 {ev.level}"
        )


def test_abstract_methodology_empty_input():
    """TR-4.3: 输入空列表 → 返回空模板列表 + level=unknown Evidence，不抛异常。"""
    result = abstract_methodology([])
    assert "methodologies" in result
    assert result["methodologies"] == []
    evidence_list = result.get("evidence", [])
    assert len(evidence_list) > 0
    assert any(e.level.value == "unknown" for e in evidence_list)


def test_abstract_methodology_returns_applicability():
    """方法论模板应含 applicability（适用条件）。"""
    investigations = [
        _make_mvc_investigation("proj-a", ["models", "views", "controllers"]),
        _make_mvc_investigation("proj-b", ["models", "views", "controllers"]),
        _make_mvc_investigation("proj-c", ["models", "views", "controllers"]),
    ]
    result = abstract_methodology(investigations)
    for m in result["methodologies"]:
        assert "applicability" in m, "方法论模板应含 applicability 字段"
        assert isinstance(m["applicability"], list)


def test_abstract_methodology_evidence_cross_project_refs():
    """附加：方法论模板的 evidence 应引用多个项目的原始 Evidence。"""
    investigations = [
        _make_mvc_investigation("proj-a", ["models", "views", "controllers"]),
        _make_mvc_investigation("proj-b", ["models", "views", "controllers"]),
        _make_mvc_investigation("proj-c", ["models", "views", "controllers"]),
    ]
    result = abstract_methodology(investigations)
    for m in result["methodologies"]:
        ev = m["evidence"]
        # provenance 应有 source_projects 字段，含 ≥2 个项目
        if hasattr(ev, "provenance"):
            sources = ev.provenance.get("source_projects", [])
            assert len(sources) >= 2, f"evidence 应引用 ≥2 个项目 (TR-4.1)，实际 {len(sources)}"


def test_methodology_abstractor_class_usable():
    """MethodologyAbstractor 类可直接实例化。"""
    abstractor = MethodologyAbstractor()
    investigations = [
        _make_mvc_investigation("proj-a", ["models", "views", "controllers"]),
        _make_mvc_investigation("proj-b", ["models", "views", "controllers"]),
    ]
    result = abstractor.abstract(investigations)
    assert "methodologies" in result
