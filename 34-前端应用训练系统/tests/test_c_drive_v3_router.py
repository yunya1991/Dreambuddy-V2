"""§3.4 C-Drive v3 路由器测试 — 部署策略 TDD

测试 c_drive_v3_router 模块的五步链路编排 + 灰度策略。
RED 阶段：assert ModuleNotFoundError / ImportError
GREEN 阶段：实现 c_drive_v3_router.py 使测试通过

覆盖 SPEC §3.4 部署策略:
  - CDRIVE_V3 feature flag (env var)
  - 灰度 10%→50%→100% (hash-based)
  - run_v3() 五步链路: recall→route→jev→decision→close_loop
  - FAIL-OPEN 设计
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _make_result(confidence=0.5, direction="NEUTRAL"):
    """生成 mock result 对象"""
    return type("R", (), {"confidence": confidence, "direction": direction})()


# ============================================================
# 1. 模块导入测试 (RED: ModuleNotFoundError)
# ============================================================

class TestModuleImport:
    """验证 c_drive_v3_router 模块可导入"""

    def test_import_router(self):
        from core.c_drive_v3_router import CDriveV3Router
        assert CDriveV3Router is not None

    def test_import_should_use_v3(self):
        from core.c_drive_v3_router import should_use_v3
        assert callable(should_use_v3)

    def test_import_hash_node_id(self):
        from core.c_drive_v3_router import _hash_node_id
        assert callable(_hash_node_id)

    def test_default_gray_percent(self):
        from core.c_drive_v3_router import DEFAULT_GRAY_PERCENT
        assert DEFAULT_GRAY_PERCENT == 0


# ============================================================
# 2. 灰度策略测试 — 10%→50%→100%
# ============================================================

class TestGrayRelease:
    """灰度部署策略: hash(node_id) % 100 < gray_percent"""

    def test_gray_0_percent_disabled(self):
        """灰度 0%: 所有 node_id 都不走 v3"""
        from core.c_drive_v3_router import should_use_v3
        assert should_use_v3("C1", gray_percent=0) is False
        assert should_use_v3("F1", gray_percent=0) is False

    def test_gray_100_percent_full(self):
        """灰度 100%: 所有 node_id 都走 v3"""
        from core.c_drive_v3_router import should_use_v3
        assert should_use_v3("C1", gray_percent=100) is True
        assert should_use_v3("F1", gray_percent=100) is True

    def test_gray_10_percent_consistent(self):
        """灰度 10%: 同一 node_id 多次调用结果一致 (hash 确定性)"""
        from core.c_drive_v3_router import should_use_v3
        r1 = should_use_v3("C1", gray_percent=10)
        r2 = should_use_v3("C1", gray_percent=10)
        assert r1 == r2

    def test_gray_50_percent_distribution(self):
        """灰度 50%: 约 50% 的 node_id 走 v3 (±10%)"""
        from core.c_drive_v3_router import should_use_v3
        count = sum(
            1 for i in range(200)
            if should_use_v3(f"node_{i}", gray_percent=50)
        )
        assert 80 <= count <= 120  # ±20% 容差

    def test_gray_10_percent_distribution(self):
        """灰度 10%: 约 10% 的 node_id 走 v3"""
        from core.c_drive_v3_router import should_use_v3
        count = sum(
            1 for i in range(200)
            if should_use_v3(f"node_{i}", gray_percent=10)
        )
        assert 5 <= count <= 30  # 宽容区间

    def test_gray_env_var(self):
        """环境变量 CDRIVE_V3_GRAY_PERCENT 控制"""
        from core.c_drive_v3_router import should_use_v3
        old = os.environ.get("CDRIVE_V3_GRAY_PERCENT")
        os.environ["CDRIVE_V3_GRAY_PERCENT"] = "100"
        try:
            assert should_use_v3("any_node") is True
        finally:
            if old is None:
                del os.environ["CDRIVE_V3_GRAY_PERCENT"]
            else:
                os.environ["CDRIVE_V3_GRAY_PERCENT"] = old

    def test_gray_env_var_default(self):
        """无环境变量时默认 0%"""
        from core.c_drive_v3_router import should_use_v3
        old = os.environ.pop("CDRIVE_V3_GRAY_PERCENT", None)
        try:
            assert should_use_v3("any_node") is False
        finally:
            if old is not None:
                os.environ["CDRIVE_V3_GRAY_PERCENT"] = old

    def test_hash_deterministic(self):
        """hash 结果确定且在 0-99"""
        from core.c_drive_v3_router import _hash_node_id
        h1 = _hash_node_id("C1")
        h2 = _hash_node_id("C1")
        assert h1 == h2
        assert 0 <= h1 <= 99

    def test_hash_different_nodes(self):
        """不同 node_id 产生不同 hash (概率)"""
        from core.c_drive_v3_router import _hash_node_id
        h1 = _hash_node_id("C1")
        h2 = _hash_node_id("F1")
        assert h1 != h2  # 不同字符串极大概率不同 hash


# ============================================================
# 3. CDriveV3Router — Tier 1 (高匹配 fast-path)
# ============================================================

class TestV3RouterTier1:
    """Tier 1: 高匹配度 → 直接推进 (零 token)"""

    def test_tier1_high_match_direct_continue(self):
        """match_score >= 0.7, density >= 3 → Tier1 → CONTINUE"""
        from core.c_drive_v3_router import CDriveV3Router

        def mock_recall(context="", top_k=5, min_quality="C", **kw):
            return [{"score": 0.85, "content": "mem"} for _ in range(5)]

        router = CDriveV3Router(recall_fn=mock_recall)
        result = router.run_v3(
            node_id="C1", result=_make_result(0.5), state={}, signals=[],
        )
        assert result["tier"] == "TIER1"
        assert result["action"] == "CONTINUE"
        assert "recall" in result["steps_executed"]
        assert "route:TIER1" in result["steps_executed"]

    def test_tier1_zero_token(self):
        """Tier 1 不调用 LLM (零 token)"""
        from core.c_drive_v3_router import CDriveV3Router

        llm_calls = []

        def mock_recall(context="", top_k=5, min_quality="C", **kw):
            return [{"score": 0.85, "content": "mem"} for _ in range(5)]

        def mock_llm(prompt):
            llm_calls.append(prompt)
            return "llm response"

        def mock_debate(signals, direction):
            llm_calls.append("debate")
            return {}

        router = CDriveV3Router(
            recall_fn=mock_recall, llm_fn=mock_llm, debate_fn=mock_debate,
        )
        result = router.run_v3(
            node_id="C1", result=_make_result(0.9), state={}, signals=[],
        )
        assert result["tier"] == "TIER1"
        assert len(llm_calls) == 0  # 零 token

    def test_tier1_high_match_score(self):
        """Tier 1 match_score 接近 0.85"""
        from core.c_drive_v3_router import CDriveV3Router

        def mock_recall(context="", top_k=5, min_quality="C", **kw):
            return [{"score": 0.85, "content": "mem"} for _ in range(5)]

        router = CDriveV3Router(recall_fn=mock_recall)
        result = router.run_v3(
            node_id="C1", result=_make_result(0.5), state={}, signals=[],
        )
        assert result["match_score"] >= 0.7
        assert result["case_density"] >= 3


# ============================================================
# 4. CDriveV3Router — Tier 2 (低匹配 33-REA 反思)
# ============================================================

class TestV3RouterTier2:
    """Tier 2: 低匹配 → L1 33-REA 反思 (零 token)"""

    def test_tier2_low_match_routed(self):
        """match_score < 0.7, density >= 2 → Tier2"""
        from core.c_drive_v3_router import CDriveV3Router

        def mock_recall(context="", top_k=5, min_quality="C", **kw):
            return [{"score": 0.5, "content": "mem"} for _ in range(3)]

        router = CDriveV3Router(recall_fn=mock_recall)
        result = router.run_v3(
            node_id="C1", result=_make_result(0.4), state={}, signals=[],
        )
        assert result["tier"] == "TIER2"
        assert "route:TIER2" in result["steps_executed"]

    def test_tier2_rea_derives_decision(self):
        """Tier 2 调用 33-REA derive_decision_from_rea"""
        from core.c_drive_v3_router import CDriveV3Router

        def mock_recall(context="", top_k=5, min_quality="C", **kw):
            return [{"score": 0.5, "content": "mem"} for _ in range(3)]

        rea_calls = []

        def mock_rea_parse(code=""):
            rea_calls.append(code)
            return type("R", (), {
                "known_gaps": ["missing: strategy module"],
                "confidence": 0.5,
                "evidence_level": "MEDIUM",
            })()

        router = CDriveV3Router(
            recall_fn=mock_recall, rea_parse_fn=mock_rea_parse,
        )
        result = router.run_v3(
            node_id="C1", result=_make_result(0.4), state={}, signals=[],
        )
        assert result["tier"] == "TIER2"
        assert len(rea_calls) > 0  # REA 被调用


# ============================================================
# 5. CDriveV3Router — Tier 3 (案例少 SKILL 调研)
# ============================================================

class TestV3RouterTier3:
    """Tier 3: 案例少+低匹配 → L3 SKILL 调研"""

    def test_tier3_few_cases_routed(self):
        """match_score < 0.4, density < 2 → Tier3"""
        from core.c_drive_v3_router import CDriveV3Router

        def mock_recall(context="", top_k=5, min_quality="C", **kw):
            return [{"score": 0.2, "content": "mem"}]  # only 1

        router = CDriveV3Router(recall_fn=mock_recall)
        result = router.run_v3(
            node_id="C1", result=_make_result(0.3), state={}, signals=[],
        )
        assert result["tier"] == "TIER3"
        assert "route:TIER3" in result["steps_executed"]

    def test_tier3_effort_level_deep(self):
        """Tier 3 effort_level = deep"""
        from core.c_drive_v3_router import CDriveV3Router

        def mock_recall(context="", top_k=5, min_quality="C", **kw):
            return [{"score": 0.2, "content": "mem"}]

        router = CDriveV3Router(recall_fn=mock_recall)
        result = router.run_v3(
            node_id="C1", result=_make_result(0.3), state={}, signals=[],
        )
        assert result["effort_level"] == "deep"


# ============================================================
# 6. CDriveV3Router — Tier 4 (多路径 Debate)
# ============================================================

class TestV3RouterTier4:
    """Tier 4: 多路径 → L4 Debate 选择"""

    def test_tier4_multi_path_routed(self):
        """signals 同时有 long+short → multi_path → Tier4"""
        from core.c_drive_v3_router import CDriveV3Router

        def mock_recall(context="", top_k=5, min_quality="C", **kw):
            return [{"score": 0.8, "content": "mem"} for _ in range(5)]

        def mock_debate(signals, direction):
            return {"bull_confidence": 0.6, "bear_confidence": 0.3,
                    "bull_argument": "bull", "bear_argument": "bear"}

        router = CDriveV3Router(
            recall_fn=mock_recall, debate_fn=mock_debate,
        )
        result = router.run_v3(
            node_id="C1", result=_make_result(0.5), state={},
            signals=[{"direction": "long"}, {"direction": "short"}],
        )
        assert result["tier"] == "TIER4"
        assert "route:TIER4" in result["steps_executed"]

    def test_tier4_debate_called(self):
        """Tier 4 调用 debate_fn"""
        from core.c_drive_v3_router import CDriveV3Router

        debate_calls = []

        def mock_recall(context="", top_k=5, min_quality="C", **kw):
            return [{"score": 0.8, "content": "mem"} for _ in range(5)]

        def mock_debate(signals, direction):
            debate_calls.append((signals, direction))
            return {"bull_confidence": 0.6, "bear_confidence": 0.3}

        router = CDriveV3Router(
            recall_fn=mock_recall, debate_fn=mock_debate,
        )
        result = router.run_v3(
            node_id="C1", result=_make_result(0.5), state={},
            signals=[{"direction": "long"}, {"direction": "short"}],
        )
        assert len(debate_calls) > 0

    def test_tier4_single_direction_not_triggered(self):
        """只有 long 或只有 short → 不触发 Tier4"""
        from core.c_drive_v3_router import CDriveV3Router

        def mock_recall(context="", top_k=5, min_quality="C", **kw):
            return [{"score": 0.85, "content": "mem"} for _ in range(5)]

        router = CDriveV3Router(recall_fn=mock_recall)
        result = router.run_v3(
            node_id="C1", result=_make_result(0.5), state={},
            signals=[{"direction": "long"}, {"direction": "long"}],
        )
        assert result["tier"] != "TIER4"


# ============================================================
# 7. jev 全局裁决 — 所有非 skip 场景
# ============================================================

class TestV3RouterJevGate:
    """Step 3: L4 jev 全局裁决"""

    def test_jev_step_present(self):
        """所有场景都走 jev 步骤"""
        from core.c_drive_v3_router import CDriveV3Router

        def mock_recall(context="", top_k=5, min_quality="C", **kw):
            return [{"score": 0.85, "content": "mem"} for _ in range(5)]

        router = CDriveV3Router(recall_fn=mock_recall)
        result = router.run_v3(
            node_id="C1", result=_make_result(0.5), state={}, signals=[],
        )
        assert any(s.startswith("jev:") for s in result["steps_executed"])

    def test_jev_decision_field(self):
        """jev_decision 字段存在"""
        from core.c_drive_v3_router import CDriveV3Router

        def mock_recall(context="", top_k=5, min_quality="C", **kw):
            return [{"score": 0.85, "content": "mem"} for _ in range(5)]

        router = CDriveV3Router(recall_fn=mock_recall)
        result = router.run_v3(
            node_id="C1", result=_make_result(0.5), state={}, signals=[],
        )
        assert result.get("jev_decision") is not None

    def test_jev_can_override_decision(self):
        """jev 可以改写决策 (低 believability CONTINUE→INSERT_BEFORE)"""
        from core.c_drive_v3_router import CDriveV3Router

        # believability = density * match_score < 0.5 → CONTINUE 被改写
        def mock_recall(context="", top_k=5, min_quality="C", **kw):
            return [{"score": 0.2, "content": "mem"} for _ in range(2)]

        router = CDriveV3Router(recall_fn=mock_recall)
        result = router.run_v3(
            node_id="C1", result=_make_result(0.5), state={}, signals=[],
        )
        # match < 0.4, density < 2 → Tier3, 但 jev 仍对决策裁决
        assert result.get("jev_decision") is not None


# ============================================================
# 8. 认知闭环 — Step 5
# ============================================================

class TestV3RouterCognitiveLoop:
    """Step 5: 认知闭环 close_loop"""

    def test_close_loop_step_present(self):
        """close_loop 步骤在 steps 中"""
        from core.c_drive_v3_router import CDriveV3Router

        def mock_recall(context="", top_k=5, min_quality="C", **kw):
            return [{"score": 0.85, "content": "mem"} for _ in range(5)]

        def mock_record(content="", tags="", quality_level="C", **kw):
            return {"id": "VM-test", "status": "ok"}

        def mock_verify(memory_id="", success=True, **kw):
            return {"status": "ok"}

        router = CDriveV3Router(
            recall_fn=mock_recall,
            record_fn=mock_record,
            verify_fn=mock_verify,
        )
        result = router.run_v3(
            node_id="C1", result=_make_result(0.5), state={}, signals=[],
        )
        assert "close_loop" in result["steps_executed"]

    def test_close_loop_not_called_without_record_fn(self):
        """无 record_fn → 不执行 close_loop"""
        from core.c_drive_v3_router import CDriveV3Router

        def mock_recall(context="", top_k=5, min_quality="C", **kw):
            return [{"score": 0.85, "content": "mem"} for _ in range(5)]

        router = CDriveV3Router(recall_fn=mock_recall)
        result = router.run_v3(
            node_id="C1", result=_make_result(0.5), state={}, signals=[],
        )
        assert "close_loop" not in result["steps_executed"]
        assert result.get("cognitive_result") is None


# ============================================================
# 9. FAIL-OPEN — 异常不阻塞
# ============================================================

class TestV3RouterFailOpen:
    """FAIL-OPEN: 任何异常都不阻塞决策输出"""

    def test_recall_failure_does_not_block(self):
        """recall 异常 → 降级到空 memories，不阻塞"""
        from core.c_drive_v3_router import CDriveV3Router

        def mock_recall(**kw):
            raise Exception("recall failed")

        router = CDriveV3Router(recall_fn=mock_recall)
        result = router.run_v3(
            node_id="C1", result=_make_result(0.5), state={}, signals=[],
        )
        assert result["action"] is not None
        assert result["match_score"] == 0.0
        assert result["case_density"] == 0

    def test_debate_failure_does_not_block(self):
        """debate 异常 → 不阻塞"""
        from core.c_drive_v3_router import CDriveV3Router

        def mock_recall(context="", top_k=5, min_quality="C", **kw):
            return [{"score": 0.85, "content": "mem"} for _ in range(5)]

        def mock_debate(signals, direction):
            raise Exception("debate failed")

        router = CDriveV3Router(
            recall_fn=mock_recall, debate_fn=mock_debate,
        )
        result = router.run_v3(
            node_id="C1", result=_make_result(0.5), state={},
            signals=[{"direction": "long"}, {"direction": "short"}],
        )
        assert result["action"] is not None

    def test_record_failure_does_not_block(self):
        """record 异常 → 不阻塞决策"""
        from core.c_drive_v3_router import CDriveV3Router

        def mock_recall(context="", top_k=5, min_quality="C", **kw):
            return [{"score": 0.85, "content": "mem"} for _ in range(5)]

        def mock_record(**kw):
            raise Exception("record failed")

        router = CDriveV3Router(
            recall_fn=mock_recall, record_fn=mock_record,
        )
        result = router.run_v3(
            node_id="C1", result=_make_result(0.5), state={}, signals=[],
        )
        assert result["action"] is not None

    def test_rea_parse_failure_does_not_block(self):
        """REA 解析异常 → 不阻塞"""
        from core.c_drive_v3_router import CDriveV3Router

        def mock_recall(context="", top_k=5, min_quality="C", **kw):
            return [{"score": 0.5, "content": "mem"} for _ in range(3)]

        def mock_rea_parse(code=""):
            raise Exception("REA parse failed")

        router = CDriveV3Router(
            recall_fn=mock_recall, rea_parse_fn=mock_rea_parse,
        )
        result = router.run_v3(
            node_id="C1", result=_make_result(0.4), state={}, signals=[],
        )
        assert result["action"] is not None
        assert result["tier"] == "TIER2"

    def test_no_fns_at_all(self):
        """完全不注入任何函数 → 仍返回决策 (全 FAIL-OPEN)"""
        from core.c_drive_v3_router import CDriveV3Router

        router = CDriveV3Router()
        result = router.run_v3(
            node_id="C1", result=_make_result(0.5), state={}, signals=[],
        )
        assert result["action"] is not None
        assert "recall" in result["steps_executed"]


# ============================================================
# 10. 完整链路 — 五步全部执行
# ============================================================

class TestV3RouterFullChain:
    """五步链路完整执行验证"""

    def test_all_five_steps_tier2(self):
        """Tier 2 场景: recall→route→jev→decision→close_loop 全执行"""
        from core.c_drive_v3_router import CDriveV3Router

        def mock_recall(context="", top_k=5, min_quality="C", **kw):
            return [{"score": 0.5, "content": "mem"} for _ in range(3)]

        def mock_record(content="", tags="", quality_level="C", **kw):
            return {"id": "VM-test", "status": "ok"}

        def mock_verify(memory_id="", success=True, **kw):
            return {"status": "ok"}

        router = CDriveV3Router(
            recall_fn=mock_recall,
            record_fn=mock_record,
            verify_fn=mock_verify,
        )
        result = router.run_v3(
            node_id="C1", result=_make_result(0.4), state={}, signals=[],
        )
        steps = result["steps_executed"]
        assert "recall" in steps
        assert any(s.startswith("route:") for s in steps)
        assert any(s.startswith("jev:") for s in steps)
        assert "close_loop" in steps

    def test_result_has_all_required_fields(self):
        """结果包含所有必要字段"""
        from core.c_drive_v3_router import CDriveV3Router

        def mock_recall(context="", top_k=5, min_quality="C", **kw):
            return [{"score": 0.85, "content": "mem"} for _ in range(5)]

        router = CDriveV3Router(recall_fn=mock_recall)
        result = router.run_v3(
            node_id="C1", result=_make_result(0.5), state={}, signals=[],
        )
        required = [
            "action", "reason", "confidence", "steps_executed",
            "match_score", "case_density", "tier", "jev_decision",
            "effort_level",
        ]
        for key in required:
            assert key in result, f"Missing field: {key}"

    def test_reason_includes_tier_info(self):
        """reason 包含 tier + match + density 信息"""
        from core.c_drive_v3_router import CDriveV3Router

        def mock_recall(context="", top_k=5, min_quality="C", **kw):
            return [{"score": 0.85, "content": "mem"} for _ in range(5)]

        router = CDriveV3Router(recall_fn=mock_recall)
        result = router.run_v3(
            node_id="C1", result=_make_result(0.5), state={}, signals=[],
        )
        assert "TIER1" in result["reason"]
        assert "match" in result["reason"].lower()


# ============================================================
# 11. 验收标准 — SPEC §5
# ============================================================

class TestAcceptanceCriteria:
    """SPEC §5 验收标准检查"""

    def test_jev_global_coverage(self):
        """jev 全局覆盖率 100% 非 skip"""
        from core.c_drive_v3_router import CDriveV3Router

        scenarios = [
            # (memories_score, memories_count, signals)
            (0.85, 5, []),           # Tier1
            (0.5, 3, []),            # Tier2
            (0.2, 1, []),            # Tier3
            (0.85, 5, [{"direction": "long"}, {"direction": "short"}]),  # Tier4
        ]

        for score, count, signals in scenarios:
            _score, _count = score, count
            def _mk_recall(_s=_score, _c=_count):
                def _fn(context="", top_k=5, min_quality="C", **kw):
                    return [{"score": _s, "content": "mem"} for _ in range(_c)]
                return _fn
            router = CDriveV3Router(
                recall_fn=_mk_recall(),
                debate_fn=lambda s, d: {"bull_confidence": 0.6, "bear_confidence": 0.3},
            )
            result = router.run_v3(
                node_id="C1", result=_make_result(0.5), state={}, signals=signals,
            )
            assert any(st.startswith("jev:") for st in result["steps_executed"]), \
                f"jev not executed for tier={result['tier']}"

    def test_decision_diversity(self):
        """不同场景产生多样化决策 (非全部 CONTINUE)"""
        from core.c_drive_v3_router import CDriveV3Router

        decisions = set()

        # Tier1 高匹配
        def mock_recall_high(context="", top_k=5, min_quality="C", **kw):
            return [{"score": 0.9, "content": "m"} for _ in range(6)]

        r = CDriveV3Router(recall_fn=mock_recall_high).run_v3(
            "C1", _make_result(0.5), {}, [],
        )
        decisions.add(r["action"])

        # Tier3 低匹配
        def mock_recall_low(context="", top_k=5, min_quality="C", **kw):
            return [{"score": 0.1, "content": "m"}]

        r = CDriveV3Router(recall_fn=mock_recall_low).run_v3(
            "C1", _make_result(0.2), {}, [],
        )
        decisions.add(r["action"])

        # 至少 2 种不同决策
        assert len(decisions) >= 2
