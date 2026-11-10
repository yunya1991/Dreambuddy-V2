"""D2-B 工程方案生成测试。"""

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
D2B = ROOT / "experiments" / "d2b_engineering"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


generator = _load("generator", D2B / "generator.py")
sandbox = _load("sandbox", D2B / "sandbox.py")
evaluate = _load("d2b_evaluate", D2B / "evaluate.py")
BuildPlan = generator.BuildPlan
generate = generator.generate
validate = sandbox.validate
evaluate_plan = evaluate.evaluate_plan


def test_generate_returns_plan_for_known_gap_types():
    for gt in ["architecture_gap", "doc_debt", "interface_mismatch"]:
        gap = {
            "gap_id": "test-1",
            "gap_type": gt,
            "evidence": {"issue": "x"},
            "expected_value": "y",
        }
        plan = generate(gap)
        assert isinstance(plan, BuildPlan)
        assert plan.gap_type == gt
        assert len(plan.steps) > 0
        assert plan.design_rationale


def test_validate_accepts_stdlib_deps():
    plan = BuildPlan(
        gap_id="t",
        gap_type="architecture_gap",
        module_name="33-REA/test_new_module_xyz.py",
        architecture_graph_patch={"add_edges": [{"source": "a", "target": "b", "kind": "import"}]},
        design_rationale="用 ast 精确解析 call 边，降低假依赖率到 5% 以下" * 2,
        steps=["遍历节点", "提取签名", "统计覆盖率", "输出报告"],
        dependencies=["ast", "json"],
        novelty_note="",
    )
    result = validate(plan)
    assert result["deps_resolved"] is True


def test_evaluate_plan_candidate_for_doc_debt():
    gap = {
        "gap_id": "t",
        "gap_type": "doc_debt",
        "evidence": {"issue": "文档断链"},
        "expected_value": "核心模块文档覆盖率 >= 0.9，断链数 = 0",
    }
    plan = generate(gap)
    result = evaluate_plan(plan, gap)
    assert result["gap_addressed"] is True
    assert result["verdict"] in {"candidate", "inconclusive"}
