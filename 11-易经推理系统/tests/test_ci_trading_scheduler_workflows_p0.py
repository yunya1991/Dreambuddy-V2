from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (REPO_ROOT / rel_path).read_text(encoding="utf-8")


def test_trading_ladder_workflow_exists_and_has_cron():
    text = _read(".github/workflows/trading-ladder-a1-a3.yml")
    assert "name: Trading Ladder A1-A3" in text
    assert "workflow_dispatch:" in text
    assert 'cron: "0 16 * * *"' in text


def test_trading_a4_workflow_exists_and_has_cron():
    text = _read(".github/workflows/trading-a4-validation.yml")
    assert "name: Trading A4 Validation" in text
    assert 'cron: "0 */4 * * *"' in text


def test_trading_a5_workflow_exists_and_has_cron():
    text = _read(".github/workflows/trading-a5-execution.yml")
    assert "name: Trading A5 Execution" in text
    assert 'cron: "0 */8 * * *"' in text


def test_trading_a6_workflow_exists_and_has_cron():
    text = _read(".github/workflows/trading-a6-intelligence.yml")
    assert "name: Trading A6 Intelligence" in text
    assert 'cron: "0 * * * *"' in text


def test_trading_a8_workflow_exists_and_has_cron():
    text = _read(".github/workflows/trading-a8-governance.yml")
    assert "name: Trading A8 Governance" in text
    assert 'cron: "0 6 * * *"' in text


def test_all_trading_scheduler_workflows_present():
    required = [
        ".github/workflows/trading-ladder-a1-a3.yml",
        ".github/workflows/trading-a4-validation.yml",
        ".github/workflows/trading-a5-execution.yml",
        ".github/workflows/trading-a6-intelligence.yml",
        ".github/workflows/trading-a8-governance.yml",
    ]
    missing = [p for p in required if not (REPO_ROOT / p).exists()]
    assert not missing


def test_safe_main_merge_gate_runs_trading_scheduler_tests():
    text = _read(".github/workflows/safe-main-merge-gate.yml")
    assert "tests/test_ci_trading_scheduler_workflows_p0.py" in text
