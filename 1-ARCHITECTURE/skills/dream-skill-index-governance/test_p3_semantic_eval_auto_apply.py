"""P3 语义评估层 + 自动 apply 测试 — TDD RED 阶段

覆盖：
1. skill_semantic_evaluator — 复用 dream-qwen-eval-collab 千问评估环节（5维评分）
2. skill_auto_applicator — 减少人工干预，行为+语义双适应度自动 apply status
"""
from __future__ import annotations

from pathlib import Path

import pytest


# ───────────────────────────── 1. skill_semantic_evaluator ─────────────────────────────

def test_semantic_evaluator_importable():
    import skill_semantic_evaluator
    assert hasattr(skill_semantic_evaluator, "build_eval_prompt")
    assert hasattr(skill_semantic_evaluator, "parse_qwen_response")
    assert hasattr(skill_semantic_evaluator, "evaluate_skill")


def test_build_eval_prompt_contains_5_dimensions():
    """prompt 应包含 SKILL 评审的 5 个维度。"""
    import skill_semantic_evaluator as sse

    prompt = sse.build_eval_prompt("# Test SKILL\n\nSome content")
    assert "完整性" in prompt
    assert "可落地性" in prompt
    assert "工程适配性" in prompt
    assert "风险识别" in prompt
    assert "表达清晰度" in prompt


def test_build_eval_prompt_contains_skill_content():
    """prompt 应包含待评审的 SKILL 内容。"""
    import skill_semantic_evaluator as sse
    content = "# My Skill\nname: dream-test"
    prompt = sse.build_eval_prompt(content)
    assert "dream-test" in prompt


def test_build_eval_prompt_asks_for_json():
    """prompt 应要求千问返回 JSON 格式评分。"""
    import skill_semantic_evaluator as sse
    prompt = sse.build_eval_prompt("content")
    assert "JSON" in prompt or "json" in prompt


def test_parse_qwen_response_extracts_scores():
    """从千问回复中解析 5 维评分 + 总分。"""
    import skill_semantic_evaluator as sse

    response = """
```json
{
  "completeness": 8.5,
  "actionability": 7.0,
  "engineering_fit": 9.0,
  "risk_awareness": 6.5,
  "clarity": 8.0,
  "overall": 7.8,
  "suggestions": ["triggers 可更精准", "补充 FAIL-OPEN 说明"]
}
```
"""
    result = sse.parse_qwen_response(response)
    assert result is not None
    assert result["completeness"] == 8.5
    assert result["actionability"] == 7.0
    assert result["engineering_fit"] == 9.0
    assert result["overall"] == 7.8
    assert len(result["suggestions"]) == 2


def test_parse_qwen_response_invalid_returns_none():
    """无法解析的回复 → None。"""
    import skill_semantic_evaluator as sse
    assert sse.parse_qwen_response("garbage text no json") is None


def test_evaluate_skill_with_mock_bsk():
    """evaluate_skill 用 mock bsk_caller 返回评分。"""
    import skill_semantic_evaluator as sse

    def mock_bsk(prompt):
        return '{"completeness": 9.0, "actionability": 8.5, "engineering_fit": 9.5, "risk_awareness": 8.0, "clarity": 9.0, "overall": 8.8, "suggestions": []}'

    result = sse.evaluate_skill("# SKILL content", bsk_caller=mock_bsk)
    assert result is not None
    assert result["overall"] == 8.8
    assert result["completeness"] == 9.0


def test_evaluate_skill_fail_open_without_bsk():
    """无 bsk_caller → 返回 None（FAIL-OPEN）。"""
    import skill_semantic_evaluator as sse
    assert sse.evaluate_skill("# content", bsk_caller=None) is None


# ───────────────────────────── 2. skill_auto_applicator ─────────────────────────────

def test_auto_applicator_importable():
    import skill_auto_applicator
    assert hasattr(skill_auto_applicator, "decide_action")
    assert hasattr(skill_auto_applicator, "apply_decision")


def test_decide_action_both_high_auto_activate():
    """行为分高 + 语义分高 → auto_activate。"""
    import skill_auto_applicator as saa

    decision = saa.decide_action(
        behavior={"success_rate": 0.9, "invocation_count": 10},
        semantic={"overall": 8.5},
    )
    assert decision["action"] == "auto_activate"
    assert decision["confidence"] == "high"


def test_decide_action_both_low_auto_deprecate():
    """行为分低 + 语义分低 → auto_deprecate。"""
    import skill_auto_applicator as saa

    decision = saa.decide_action(
        behavior={"success_rate": 0.2, "invocation_count": 10},
        semantic={"overall": 3.5},
    )
    assert decision["action"] == "auto_deprecate"
    assert decision["confidence"] == "high"


def test_decide_action_mixed_needs_human():
    """行为分高但语义分低（或反之）→ 需人工 gate。"""
    import skill_auto_applicator as saa

    # 行为好但语义差
    d1 = saa.decide_action(
        behavior={"success_rate": 0.9, "invocation_count": 10},
        semantic={"overall": 3.0},
    )
    assert d1["action"] == "needs_human_review"

    # 行为差但语义好
    d2 = saa.decide_action(
        behavior={"success_rate": 0.2, "invocation_count": 10},
        semantic={"overall": 9.0},
    )
    assert d2["action"] == "needs_human_review"


def test_decide_action_insufficient_data_no_auto():
    """调用次数不足 → 不自动 apply。"""
    import skill_auto_applicator as saa

    decision = saa.decide_action(
        behavior={"success_rate": 0.9, "invocation_count": 1},
        semantic={"overall": 9.0},
    )
    assert decision["action"] == "needs_human_review"
    assert "数据不足" in decision["reason"]


def test_decide_action_mid_range_refine():
    """中间分数段 → refine_triggers，仍需人工。"""
    import skill_auto_applicator as saa

    decision = saa.decide_action(
        behavior={"success_rate": 0.6, "invocation_count": 10},
        semantic={"overall": 6.5},
    )
    assert decision["action"] == "refine_triggers"


def test_apply_decision_writes_status(tmp_path):
    """apply_decision 调用 lifecycle_writer 写回 status。"""
    import skill_auto_applicator as saa
    from skill_lifecycle_writer import write_lifecycle

    # 创建一个测试 SKILL.md
    skill_dir = tmp_path / "dream-test"
    skill_dir.mkdir()
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text("---\nname: dream-test\nstatus: shadow\n---\nbody", encoding="utf-8")

    result = saa.apply_decision(
        skill_path=skill_md,
        action="auto_activate",
        reason="测试自动激活",
        write_status_fn=write_lifecycle,
    )
    assert result is True
    # 验证 status 已变更
    content = skill_md.read_text(encoding="utf-8")
    assert "status: active" in content


def test_apply_decision_unknown_action_returns_false(tmp_path):
    """未知 action → False。"""
    import skill_auto_applicator as saa
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text("---\nname: x\nstatus: shadow\n---\n", encoding="utf-8")
    result = saa.apply_decision(skill_md, "bogus_action", "reason", write_status_fn=lambda *a, **k: {"ok": True})
    assert result is False
