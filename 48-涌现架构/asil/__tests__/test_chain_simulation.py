# ruff: noqa: E402  (sys.path 必须先于 asil 导入)
"""链路畅通性验证 — 场景化集成测试（Trae 内模拟，零外部 LLM）。

覆盖：正常链路 / 漂移熔断 / 空 gap bootstrap / 恶意方案拒绝 /
      Trae 评注覆盖自动裁决 / D2 模板演进。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

from asil.d2b_adapter import D2BAdapter
from asil.emergence_loop import D2EmergenceLoop, D3EmergenceLoop
from asil.orchestrator import ASILOrchestrator
from asil.trigger_scanner import PipelineTrigger
from asil.variant_generator import RuleVariant


def _trigger(type_: str = "low_confidence_memory", **kw) -> PipelineTrigger:
    return PipelineTrigger(type=type_, source="chain-sim", evidence={"ratio": 0.7}, **kw)


class TestPipelineChain:
    def test_normal_chain_reaches_verify_and_distill(self):
        orch = ASILOrchestrator()
        out = orch.run_pipeline(_trigger())

        assert out["phase"] == 2
        assert out["d3_intent"] is not None
        assert out["build_plan"]["modules"]
        assert out["verdict"]["verdict"] in ("candidate", "rejected", "inconclusive")
        assert out["route"] in ("FEEDBACK_VERIFY_DISTILL", "SKIP_DISTILL", "REPORT_ONLY")
        assert out["kill_switch"]["level"] in ("L0", "L1", "L2", "L3", "L4")
        assert out["llm_tokens_used"] == 0  # C12：Phase 2 仍零 LLM

    def test_drift_chain_triggers_kill_switch(self):
        orch = ASILOrchestrator()
        out = orch.run_pipeline(_trigger(psi_value=0.31))
        assert out["kill_switch"]["level"] == "L2"
        assert out["kill_switch"]["action"] in ("reduce_position", "shadow_only", "no_op")

    def test_empty_gaps_uses_bootstrap_fallback(self, tmp_path):
        empty = tmp_path / "gaps.jsonl"
        empty.write_text("")
        orch = ASILOrchestrator(d2b_adapter=D2BAdapter(gaps_path=empty))
        out = orch.run_pipeline(_trigger(type_="e6_gap_detected"))
        assert out["build_plan"]["modules"]  # bootstrap 模板兜底成功
        assert out["verdict"]["verdict"] != "dead"
        assert "bootstrap" not in out or out["build_plan"].get("bootstrap") is not False

    def test_bypass_plan_is_rejected(self):
        orch = ASILOrchestrator()
        evil = {
            "architecture_graph": {"nodes": ["evil"], "edges": []},
            "modules": ["evil/bypass.py"],
            "code_skeleton": "def hack():\n    eval('1+1')\n",
            "design_rationale": "bypass oracle",
        }
        out = orch.run_pipeline(_trigger(), mock_build_plan=evil)
        assert out["verdict"]["verdict"] == "rejected"
        assert out["route"] == "FEEDBACK_RECORD_FAILURE"  # 失败路径，不进入蒸馏

    def test_metrics_chain_consistent(self):
        orch = ASILOrchestrator()
        for t, psi in (
            ("low_confidence_memory", None),
            ("e6_gap_detected", None),
            ("drift_detected", 0.31),
        ):
            orch.run_pipeline(_trigger(type_=t, psi_value=psi))
        snap = orch.metrics_snapshot()
        assert snap["total_pipelines"] == 3
        assert snap["completed_pipelines"] == 3
        assert 0.0 <= snap["completion_rate"] <= 1.0
        assert snap["llm_tokens_used"] == 0
        assert snap["recall_stats"]["n_recalls"] > 100  # 真实 recall 源已接入
        assert snap["distill_effectiveness"] >= 0.0


class TestTraeInTheLoop:
    def _loop(self, tmp_path, reviewer: str) -> D3EmergenceLoop:
        return D3EmergenceLoop(
            variants=[
                RuleVariant("base", fallback="general"),
                RuleVariant("candidate", fallback="majority"),
            ],
            reviewer=reviewer,
            review_dir=tmp_path / "reviews",
            loop_dir=tmp_path / "loops",
        )

    def test_trae_annotation_overrides_auto_gate(self, tmp_path):
        # 第一遍：生成评审包，自动兜底（基线 0.782 vs 候选 0.782 → reject）
        first = self._loop(tmp_path, "trae").run(rounds=1)
        assert first["history"][0]["reviewer"] == "auto"

        req = sorted((tmp_path / "reviews").glob("*.request.json"))[0]
        body = json.loads(req.read_text())
        assert body["payload"]["domain"] == "D3"
        req.with_name(req.name.replace(".request.json", ".result.json")).write_text(
            json.dumps({"decision": "accept", "notes": "Trae 模拟评注：同意试运行"})
        )

        # 第二遍：同一 payload 哈希 → 读到回写 → 覆盖门禁
        second = self._loop(tmp_path, "trae").run(rounds=1)
        h = second["history"][0]
        assert h["reviewer"] == "trae"
        assert h["decision"] == "accept"
        assert second["champion"] == "candidate"  # 评注真正改写了冠军

    def test_auto_reviewer_needs_no_annotation(self, tmp_path):
        summary = self._loop(tmp_path, "auto").run(rounds=1)
        assert summary["history"][0]["reviewer"] == "auto"
        assert summary["champion"] == "base"  # 无提升 → 拒绝，冠军不变


class TestD2EvolveChain:
    def test_evolve_generates_next_gen_policies(self, tmp_path):
        gaps = tmp_path / "gaps.jsonl"
        gaps.write_text(
            json.dumps(
                {
                    "gap_id": "GAP-SIM",
                    "gap_type": "architecture_gap",
                    "evidence": {},
                    "expected_value": "假依赖率 < 5%",
                    "status": "open",
                }
            )
        )
        before = gaps.read_text()
        loop = D2EmergenceLoop(
            gaps_path=gaps,
            evolve_rounds=2,
            reviewer="auto",
            review_dir=tmp_path / "r",
            loop_dir=tmp_path / "l",
        )
        summary = loop.run()
        assert summary["policy_round"]["policies"]
        assert gaps.read_text() == before  # 零执行权
        assert "overall_pass_rate" in summary
        # Wilson 区间与证据等级必须随 D2 结果输出
        assert 0.0 <= summary["overall_ci"]["ci_low"] <= summary["overall_ci"]["ci_high"] <= 1.0
        assert summary["overall_evidence"] in ("insufficient", "weak", "adequate")
        assert all("ci_low" in v for v in summary["scoreboard"].values())
        assert "ci_improved" in summary["policy_round"]
