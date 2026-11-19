#!/usr/bin/env python3
"""l2_prompt_bridge 运行时桥测试（SPEC-57 §8 P6）。"""

from __future__ import annotations

import sys
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[1] / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

import l2_prompt_bridge as bridge  # noqa: E402

PROMPTS = (
    "l2.app.skill",
    "l2.app.trade_ops",
    "l2.worker.rea",
    "l2.emergence.meta_evolution",
)
META_FIELDS = (
    "prompt_id",
    "prompt_version",
    "prompt_fingerprint",
    "constitution_version",
    "constitution_tokens",
    "tool_set_fingerprint",
    "reasoning_effort",
)


def test_render_injects_constitution_for_all_assets():
    for prompt_id in PROMPTS:
        rendered = bridge.render(prompt_id)
        assert rendered["injected"] is True, prompt_id
        assert "constitution@1.0.0" in rendered["system_prompt"], prompt_id
        meta = rendered["meta"]
        assert meta and all(meta.get(k) for k in META_FIELDS), prompt_id


def test_render_section_extracts_trade_ops_block():
    rendered = bridge.render("l2.app.trade_ops", section="五、", include_asset=True)
    assert "Process D" in rendered["section_text"]
    assert "Screen 2" not in rendered["section_text"]


def test_render_variables_are_appended_as_json():
    rendered = bridge.render(
        "l2.worker.rea", variables={"target_symbol": "BTC"}, include_asset=False
    )
    assert '"target_symbol": "BTC"' in rendered["system_prompt"]


def test_render_unknown_prompt_fails_open():
    rendered = bridge.render("l2.not_registered.prompt")
    assert rendered["injected"] is False
    assert rendered["meta"] is None
    assert rendered["system_prompt"] == ""


def test_gate_allows_clean_and_denies_execution_claim():
    clean = bridge.gate(
        "l2.app.trade_ops",
        {"summary": "区间震荡", "risk_flags": []},
        evidence="partial",
    )
    assert clean["verdict"] == "allow", clean

    denied = bridge.gate(
        "l2.app.trade_ops",
        {"summary": "已买入 BTC", "risk_flags": []},
        evidence="partial",
    )
    assert denied["verdict"] == "deny", denied
    assert any(v["code"] == "E_CLAIM_EXECUTION" for v in denied["violations"])


def test_gate_flags_evidence_missing():
    result = bridge.gate("l2.worker.rea", {"findings": ["x"]}, evidence=None)
    assert result["verdict"] in ("needs_review", "degraded"), result


def test_verify_reports_eval_coverage_and_fingerprint():
    for prompt_id in PROMPTS:
        info = bridge.verify(prompt_id)
        assert info["fingerprint_ok"] is True, prompt_id
        assert info["eval_cases"] >= 20, prompt_id


def test_tree_fingerprint_ignores_os_metadata():
    """tree 资产忽略点开头文件：Finder 生成的 .DS_Store 不得改变指纹。"""
    import prompt_context_57 as pc

    entry = pc.get_prompt("l2.emergence.meta_evolution")
    target = pc.REPO_ROOT / entry["asset_path"]
    marker = target / ".DS_Store"
    before = pc.asset_fingerprint(entry)
    if marker.exists():  # 不覆盖用户已有的 Finder 元数据
        assert pc.asset_fingerprint(entry) == before
        return
    marker.write_bytes(b"finder-noise")
    try:
        assert pc.asset_fingerprint(entry) == before
    finally:
        marker.unlink(missing_ok=True)
