import importlib.util
from pathlib import Path


REPO_ROOT = Path("/Users/zhangjiangtao/WorkBuddy/dream-multiskill-v2")


def _load_module(rel_path: str):
    path = REPO_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _payload(out):
    return out["payload"]


def test_a3_entrypoint_builds_strategy_artifact(tmp_path: Path):
    mod = _load_module("workflows/trading-decision/A3_simulation/entrypoint.py")
    out = mod.run_a3_simulation(
        {
            "trace_id": "t-a3",
            "signal_score": 66.0,
            "volatility": 0.025,
            "market_regime": "trend",
        },
        output_dir=tmp_path,
    )
    assert out["header"]["source"] == "A3"
    assert out["header"]["target"] == "A4"
    payload = _payload(out)
    assert payload["stage_id"] == "A3"
    assert payload["strategy_mode"] in {"trend_follow", "mean_revert", "neutral"}
    assert Path(payload["artifact_path"]).exists()


def test_a4_entrypoint_outputs_risk_gate(tmp_path: Path):
    mod = _load_module("workflows/trading-decision/A4_validation/entrypoint.py")
    out = mod.run_a4_validation(
        {
            "trace_id": "t-a4",
            "max_drawdown_pct": 3.2,
            "position_ratio": 0.35,
            "stop_loss_pct": 1.1,
        },
        output_dir=tmp_path,
    )
    assert out["header"]["source"] == "A4"
    assert out["header"]["target"] == "A5"
    payload = _payload(out)
    assert payload["stage_id"] == "A4"
    assert payload["risk_gate"] in {"PASS", "REVIEW", "BLOCK"}
    assert Path(payload["artifact_path"]).exists()


def test_a5_entrypoint_outputs_execution_plan(tmp_path: Path):
    mod = _load_module("workflows/trading-decision/A5_execution/entrypoint.py")
    out = mod.run_a5_execution(
        {
            "trace_id": "t-a5",
            "direction": "LONG",
            "entry_price": 64000.0,
            "leverage": 3,
        },
        output_dir=tmp_path,
    )
    assert out["header"]["source"] == "A5"
    assert out["header"]["target"] == "A9"
    payload = _payload(out)
    assert payload["stage_id"] == "A5"
    assert payload["order_plan"]["side"] in {"BUY", "SELL"}
    assert Path(payload["artifact_path"]).exists()


def test_phase2_trade_skills_exist():
    required = [
        REPO_ROOT / "skills/1-TRADE/dream-strategy-designer/SKILL.md",
        REPO_ROOT / "skills/1-TRADE/dream-strategy-parser/SKILL.md",
        REPO_ROOT / "skills/1-TRADE/dream-tactical-validator/SKILL.md",
        REPO_ROOT / "skills/1-TRADE/dream-pretrade-gatekeeper/SKILL.md",
        REPO_ROOT / "skills/1-TRADE/dream-tactical-executor/SKILL.md",
    ]
    for p in required:
        assert p.exists(), f"missing migrated skill: {p}"
