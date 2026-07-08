import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_module(rel_path: str):
    path = REPO_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_gate_requires_system_tests_when_trading_orchestrator_changes():
    mod = _load_module("scripts/ci/safe_main_merge_gate.py")
    event = {
        "pull_request": {
            "base": {"ref": "main"},
            "head": {"ref": "feature/abc"},
            "title": "feat: update orchestrator",
        }
    }
    changed_files = [
        "workflows/trading-decision/orchestrator/system_loop.py",
        "constraints/workflows-spec/trading.md",
    ]
    violations, _notes = mod.check_rules(event, changed_files)
    assert any("system-level trading tests" in v for v in violations)


def test_gate_passes_when_trading_orchestrator_and_system_tests_both_changed():
    mod = _load_module("scripts/ci/safe_main_merge_gate.py")
    event = {
        "pull_request": {
            "base": {"ref": "main"},
            "head": {"ref": "feature/abc"},
            "title": "feat: update orchestrator",
        }
    }
    changed_files = [
        "workflows/trading-decision/orchestrator/system_loop.py",
        "tests/test_trading_system_loop_e2e_p1p2.py",
        "constraints/workflows-spec/trading.md",
    ]
    violations, _notes = mod.check_rules(event, changed_files)
    assert all("system-level trading tests" not in v for v in violations)


def test_gate_passes_when_memory_l4_contract_test_changed():
    mod = _load_module("scripts/ci/safe_main_merge_gate.py")
    event = {
        "pull_request": {
            "base": {"ref": "main"},
            "head": {"ref": "feature/abc"},
            "title": "feat: add memory l4 bridge",
        }
    }
    changed_files = [
        "workflows/trading-decision/orchestrator/memory_l4_contract_bridge.py",
        "tests/test_trading_memory_l4_contract_e2e.py",
        "constraints/workflows-spec/trading.md",
    ]
    violations, _notes = mod.check_rules(event, changed_files)
    assert all("system-level trading tests" not in v for v in violations)
