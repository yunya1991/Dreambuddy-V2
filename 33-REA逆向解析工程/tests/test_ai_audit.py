"""RED 测试：AIAuditor — AI 产出审计（PoE 核心门禁）。

Task 5 of PoE 工程实践复现器 SPEC。
依据：TASKS-工程实践复现器.md TR-5.1 / TR-5.2 / TR-5.3
关联：DESIGN-PHILOSOPHY-PoE.md §5 门禁阈值
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# RED: 模块尚未实现，import 应失败
from core.ai_audit import (
    AIAuditor,
    audit_ai_output,
    compute_poe_score,
)


# ---------- 测试样本 ----------

UNCOMMENTED_UNTESTED = """
def complex_logic(data):
    items = data.split(',')
    result = 0
    for i in range(142):
        if items[i % len(items)] == 'x':
            result += 100
        else:
            result -= 50
    return result * 3.14

MAGIC = 0.85

class Handler:
    def handle(self, req):
        return 200 if req else 500
"""

WELL_DOCUMENTED = '''
def calculate_mean(values):
    """计算算术平均值。

    Args:
        values: 数值列表

    Returns:
        float: 平均值，空列表返回 0.0
    """
    if not values:
        return 0.0
    return sum(values) / len(values)


class Statistics:
    """描述性统计工具。"""

    def __init__(self, data):
        self._data = list(data)

    def mean(self):
        """返回均值。"""
        return calculate_mean(self._data)
'''


# ---------- 测试用例 ----------


def test_audit_ai_output_uncommented_low_score():
    """TR-5.1: 无注释无测试的 AI 代码 → evidence_chain_score ∈ [0,1] 且 < 0.5，债务清单非空。"""
    with tempfile.TemporaryDirectory() as d:
        Path(d, "ai_output.py").write_text(UNCOMMENTED_UNTESTED)
        result = audit_ai_output(d)

        assert "evidence_chain_score" in result
        score = result["evidence_chain_score"]
        assert 0.0 <= score <= 1.0, f"score 应在 [0,1] 范围，实际 {score}"
        assert score < 0.5, f"无注释无测试应 < 0.5 (TR-5.1)，实际 {score}"

        assert "cognitive_debt" in result
        assert len(result["cognitive_debt"]) > 0, "债务清单应非空 (TR-5.1)"


def test_audit_ai_output_well_documented_high_score():
    """TR-5.2: 有完整注释和测试 → evidence_chain_score >= 0.7。"""
    with tempfile.TemporaryDirectory() as d:
        Path(d, "well_doc.py").write_text(WELL_DOCUMENTED)
        Path(d, "README.md").write_text("# Well Documented Project\n")
        os.makedirs(os.path.join(d, "tests"))
        Path(d, "tests", "test_well_doc.py").write_text(
            "from well_doc import calculate_mean\n\n"
            "def test_mean():\n    assert calculate_mean([1, 2, 3]) == 2.0\n"
        )
        result = audit_ai_output(d)
        score = result["evidence_chain_score"]
        assert score >= 0.7, f"完整注释+测试应 >= 0.7 (TR-5.2)，实际 {score}"


def test_audit_ai_output_debt_has_provenance_and_level():
    """TR-5.3: 每条认知债务带 provenance（文件+行号）和 level 标注。"""
    with tempfile.TemporaryDirectory() as d:
        Path(d, "ai_output.py").write_text(UNCOMMENTED_UNTESTED)
        result = audit_ai_output(d)
        for debt in result["cognitive_debt"]:
            ev = debt.get("evidence")
            if ev is None:
                ev = debt  # 兼容两种结构
            assert ev.provenance is not None, "债务必须带 provenance (TR-5.3)"
            assert "file" in ev.provenance, "provenance 必须含 file (TR-5.3)"
            assert "line" in ev.provenance, "provenance 必须含 line (TR-5.3)"
            assert ev.level is not None, "债务必须带 level 标注 (TR-5.3)"


def test_audit_ai_output_returns_poe_score():
    """应返回 poe_score 综合得分（按 DESIGN-PHILOSOPHY-PoE §5 公式）。"""
    with tempfile.TemporaryDirectory() as d:
        Path(d, "ai_output.py").write_text(UNCOMMENTED_UNTESTED)
        result = audit_ai_output(d)
        assert "poe_score" in result
        assert 0.0 <= result["poe_score"] <= 1.0


def test_audit_ai_output_returns_gate_decision():
    """应返回 gate_decision（pass/review/reject）。"""
    with tempfile.TemporaryDirectory() as d:
        Path(d, "ai_output.py").write_text(UNCOMMENTED_UNTESTED)
        result = audit_ai_output(d)
        assert "gate_decision" in result
        assert result["gate_decision"] in ("pass", "review", "reject")


def test_compute_poe_score_formula():
    """compute_poe_score 按 DESIGN-PHILOSOPHY-PoE §5.2 公式：
    poe_score = clamp(raw * layer_bonus, 0, 1)
    raw = 0.4*evi + 0.25*cov + 0.2*(1-complexity)"""
    poe = compute_poe_score(
        evidence_chain_score=1.0,
        coverage_score=1.0,
        complexity_penalty=0.0,
        has_design_decision=True,
        has_narrative=False,
        has_methodology=False,
    )
    # raw = 0.4 + 0.25 + 0.2 = 0.85, bonus=1.05（+Decision）→ 0.8925
    assert 0.85 <= poe <= 1.0, f"完整 P0+P1 得分应在 [0.85, 1.0]，实际 {poe}"

    poe_minimal = compute_poe_score(
        evidence_chain_score=0.0,
        coverage_score=0.0,
        complexity_penalty=1.0,
        has_design_decision=False,
        has_narrative=False,
        has_methodology=False,
    )
    assert poe_minimal < 0.5, f"空证据链应 < 0.5，实际 {poe_minimal}"


def test_audit_ai_output_nonexistent_target_failopen():
    """FAIL-OPEN: 不存在目录返回 poe_score=0.0 + gate=review + unknown Evidence。"""
    result = audit_ai_output("/nonexistent/target/xyz")
    assert result["poe_score"] == 0.0
    assert result["gate_decision"] == "review"
    assert any(e.level.value == "unknown" for e in result.get("evidence", []))


def test_audit_ai_output_detects_magic_number():
    """附加：应识别魔法数字（如 142 / 3.14）为认知债务。"""
    with tempfile.TemporaryDirectory() as d:
        Path(d, "ai_output.py").write_text(UNCOMMENTED_UNTESTED)
        result = audit_ai_output(d)
        debt_types = []
        for debt in result["cognitive_debt"]:
            ev = debt.get("evidence", debt)
            debt_types.append(str(ev.provenance.get("type", "")) + str(ev.result))
        assert any("magic" in t.lower() or "魔法" in t for t in debt_types), \
            "应检测魔法数字 (TR-5.3 附加)"


def test_ai_auditor_class_usable():
    """AIAuditor 类可直接实例化。"""
    with tempfile.TemporaryDirectory() as d:
        Path(d, "ai_output.py").write_text(WELL_DOCUMENTED)
        auditor = AIAuditor()
        result = auditor.audit(d)
        assert "evidence_chain_score" in result
