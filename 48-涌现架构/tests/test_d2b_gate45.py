"""D2-B 真实 45 门禁（gate_45）测试。"""

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
D2B = ROOT / "experiments" / "d2b_engineering"
if str(D2B) not in sys.path:
    sys.path.insert(0, str(D2B))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


generator = _load("d2b_generator_gate", D2B / "generator.py")
gate_45 = _load("d2b_gate_45", D2B / "gate_45.py")


def _plan(gap_type="architecture_gap", skeleton=None):
    gap = {
        "gap_id": "test-gate-1",
        "gap_type": gap_type,
        "evidence": {"issue": "x"},
        "expected_value": "y",
    }
    plan = generator.generate(gap)
    if skeleton is not None:
        plan.code_skeleton = skeleton
    return plan


def test_scan_secrets_detects_aws_key():
    hits = gate_45.scan_secrets('key = "AKIAIOSFODNN7EXAMPLE"')
    assert any("aws_access_key" in h for h in hits)


def test_scan_secrets_clean_code():
    hits = gate_45.scan_secrets("def f():\n    return 1\n")
    assert hits == []


def test_materialize_writes_compilable_skeleton(tmp_path):
    plan = _plan()
    assert plan.code_skeleton  # generator 现在产出骨架
    target = gate_45.materialize(plan, tmp_path)
    assert target.exists()
    import py_compile

    py_compile.compile(str(target), doraise=True)


def test_run_real_gate_passes_clean_plan(tmp_path):
    plan = _plan()
    result = gate_45.run_real_gate(plan, workspace_root=tmp_path)
    if result["gate_mode"] != "real_45_local":
        import pytest

        pytest.skip("45-评测系统 不可用")
    assert result["gate_pass"] is True
    assert result["syntax_pass"] is True
    assert result["secrets_pass"] is True
    assert result["bypass_pass"] is True
    assert result["evaluator_items"]["E-H1-secrets"]["status"] == "PASS"
    assert result["evaluator_items"]["E-H5-bypass"]["status"] == "PASS"
    # E-H2：骨架 stdlib-only → 无供应链攻击面
    assert result["vuln_status"] == "stdlib_only"
    assert result["vuln_pass"] is True
    # E-H3：本地可追溯链（git 环境）
    if result["traceability_commit"]:
        assert result["traceability_pass"] is True
        assert result["traceability_mode"] == "local_attestation"
    # deferred 仅剩余 E-H4/E-W5/E-W6
    assert "E-H4" in result["deferred"]
    assert "E-W5" in result["deferred"]
    assert "E-W6" in result["deferred"]


def test_scan_vulnerabilities_stdlib_only(tmp_path):
    f = tmp_path / "m.py"
    f.write_text("import ast, json\n")
    vulns, status = gate_45.scan_vulnerabilities(f)
    assert status == "stdlib_only"
    assert vulns == []


def test_third_party_imports_extraction(tmp_path):
    f = tmp_path / "m.py"
    f.write_text("import os\nimport requests\nfrom numpy import array\n")
    third = gate_45._third_party_imports(f)
    assert "requests" in third
    assert "numpy" in third
    assert "os" not in third


def test_build_local_traceability(tmp_path):
    f = tmp_path / "m.py"
    f.write_text("x = 1\n")
    trace = gate_45.build_local_traceability(f)
    assert trace["build_digest"]
    assert trace["sbom_subject_digest"] == trace["build_digest"]
    assert trace["attestation_verified"] is True
    assert trace["mode"] == "local_attestation"
    assert (tmp_path / "m.py.provenance.json").exists()


def test_run_real_gate_blocks_secret_leak(tmp_path):
    plan = _plan(skeleton='aws_key = "AKIAIOSFODNN7EXAMPLE"\n')
    result = gate_45.run_real_gate(plan, workspace_root=tmp_path)
    if result["gate_mode"] != "real_45_local":
        import pytest

        pytest.skip("45-评测系统 不可用")
    assert result["secrets_pass"] is False
    assert result["gate_pass"] is False
    assert result["evaluator_items"]["E-H1-secrets"]["status"] == "BLOCK"


def test_run_real_gate_blocks_bypass(tmp_path):
    plan = _plan(skeleton="# run: pytest -x || true\nx = 1\n")
    result = gate_45.run_real_gate(plan, workspace_root=tmp_path)
    if result["gate_mode"] != "real_45_local":
        import pytest

        pytest.skip("45-评测系统 不可用")
    assert result["bypass_pass"] is False
    assert result["gate_pass"] is False
    assert result["evaluator_items"]["E-H5-bypass"]["status"] == "BLOCK"


def test_evaluate_gate_prefers_real_mode(tmp_path):
    evaluate = _load("d2b_evaluate_gate", D2B / "evaluate.py")
    plan = _plan()
    gate = evaluate._gate(plan)
    if gate["gate_mode"] != "real_45_local":
        import pytest

        pytest.skip("45-评测系统 不可用")
    assert gate["gate_pass"] is True
    if gate.get("implemented"):
        # 完整实现模式：E-H4 真实覆盖率
        assert gate["coverage_rate"] is not None
        assert gate["coverage_pass"] is True
    else:
        # 骨架模式：E-H4/E-W5 代理指标保留并标注
        assert "coverage_proxy" in gate
        assert "proxy_metrics_note" in gate
