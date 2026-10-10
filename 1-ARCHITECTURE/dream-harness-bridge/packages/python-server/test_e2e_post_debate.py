#!/usr/bin/env python3
"""test_e2e_post_debate.py — E2E 端到端验收 (SPEC v1.2-rc1)

验收三层架构完整管道: Layer1(评审) → Layer2(反思) → Layer3(训练)
+ 认知闭环 (record→recall→verify) + FAIL-OPEN + 延迟 + 冷启动

用 mock LLM (prompt 关键词分流) 验证管道完整性，不依赖真实 LLM API。
"""
from __future__ import annotations
import json, os, sys, time, unittest

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)


# ── 测试数据构造 ──────────────────────────────────────────────

def _make_transcript():
    return [
        {"speaker": "bull", "round": 1, "content": {
            "thesis": "BTC 稀缺性决定长期价值",
            "arguments": ["2100万枚上限", "减半周期", "机构采用率上升"],
            "quote": "数字黄金",
            "confidence": 0.85,
        }, "persona": "乐观分析师"},
        {"speaker": "bear", "round": 1, "content": {
            "thesis": "BTC 波动性远超黄金不适合做避险资产",
            "arguments": ["单日波动可达20%", "监管不确定性"],
            "quote": "不是黄金是赌场",
            "confidence": 0.72,
        }, "persona": "谨慎风控师"},
    ]


def _make_verdict():
    return {"summary": "正方领先", "winner": "bull",
            "key_insights": ["稀缺性论据有力"], "topic_angle": "避险资产定位"}


def _make_llm():
    """mock LLM — 用 prompt 关键词分流返回不同 JSON。"""
    adj_json = json.dumps({
        "bull": {d: 4 for d in ["clarity", "arrangement", "topic_relevance",
                                 "emotional_appeal", "fact_authenticity",
                                 "logical_validity"]},
        "bear": {d: 3 for d in ["clarity", "arrangement", "topic_relevance",
                                 "emotional_appeal", "fact_authenticity",
                                 "logical_validity"]},
        "rfd": "正方在论证清晰度和切题度上领先，证据更扎实",
        "key_clash_points": ["稀缺性vs波动性", "避险资产定位是否成立"],
    })
    strat_json = json.dumps({
        "bull_strategies": ["evidence-heavy", "burden-of-proof"],
        "bear_strategies": ["disadvantage", "counterplan"],
        "confidence": 0.8,
    })
    refl_json = json.dumps({
        "review": {
            "turn_points": [{"round": 1, "bull": "稀缺性", "bear": "波动性"}],
            "key_pivot": "第1轮正方数据引用",
            "rfd_summary": "正方领先",
        },
        "strategy_analysis": {
            "evidence-heavy": {"used_by": "bull", "effect": 4},
            "disadvantage": {"used_by": "bear", "effect": 3},
        },
        "gaps": {
            "evidence_gaps": ["缺少黄金对比数据"],
            "dropped_args": ["反方未展开监管论据"],
            "unused_tactics": ["正方可用价值翻转"],
        },
        "recommendations": ["增加黄金波动率对比数据", "反方应加强监管论据"],
        "persona_suggestions": {"bull": "保持数据优势", "bear": "加强反驳力度"},
    })

    def llm_fn(prompt, max_tokens=600):
        if "分析以下辩论论点" in prompt:
            return strat_json
        if "独立裁判" in prompt:
            return adj_json
        return refl_json
    return llm_fn


# ── E2E 验收: 三层产出完整性 ─────────────────────────────────

class TestE2ELayerIntegrity(unittest.TestCase):
    """验证三层管道各层产出字段完整且有效。"""

    @classmethod
    def setUpClass(cls):
        from c_drive_agent import run_post_debate_pipeline
        cls.result = run_post_debate_pipeline(
            topic="BTC是数字黄金",
            transcript=_make_transcript(),
            verdict=_make_verdict(),
            llm_fn=_make_llm(),
            bull_persona="乐观分析师",
            bear_persona="谨慎风控师",
        )

    def test_layer1_six_dimensions_all_1_to_5(self):
        """Layer1: 6 维评分均在 1-5 范围内。"""
        dim_comp = self.result["adjudication"]["dimension_comparison"]
        dims = ["clarity", "arrangement", "topic_relevance",
                "emotional_appeal", "fact_authenticity", "logical_validity"]
        for dim in dims:
            self.assertIn(dim, dim_comp, f"缺少维度 {dim}")
            bull_val = dim_comp[dim]["bull"]
            bear_val = dim_comp[dim]["bear"]
            self.assertGreaterEqual(bull_val, 1, f"{dim} bull <1")
            self.assertLessEqual(bull_val, 5, f"{dim} bull >5")
            self.assertGreaterEqual(bear_val, 1, f"{dim} bear <1")
            self.assertLessEqual(bear_val, 5, f"{dim} bear >5")

    def test_layer1_rfd_nonempty(self):
        """Layer1: RFD 裁决理由非空。"""
        rfd = self.result["adjudication"]["rfd"]
        self.assertTrue(rfd, "RFD 为空")

    def test_layer1_key_clash_points_nonempty(self):
        """Layer1: 关键交锋点非空。"""
        clash = self.result["adjudication"]["key_clash_points"]
        self.assertIsInstance(clash, list)
        self.assertGreater(len(clash), 0, "key_clash_points 为空")

    def test_layer1_winner_valid(self):
        """Layer1: winner 为 bull/bear/draw 之一。"""
        winner = self.result["adjudication"]["winner"]
        self.assertIn(winner, ["bull", "bear", "draw"])

    def test_layer1_timestamp_nonempty(self):
        """Layer1: 时间戳非空。"""
        ts = self.result["adjudication"]["timestamp"]
        self.assertTrue(ts, "timestamp 为空")

    def test_layer2_strategy_tags_nonempty(self):
        """Layer2: 策略标签非空 (HC7 前置)。"""
        tags = self.result["reflection"]["strategy_tags"]
        self.assertIsInstance(tags, list)
        self.assertGreater(len(tags), 0, "strategy_tags 为空")

    def test_layer2_gaps_three_fields(self):
        """Layer2: gaps 三字段完整 (evidence_gaps/dropped_args/unused_tactics)。"""
        gaps = self.result["reflection"]["gaps"]
        self.assertIsInstance(gaps, dict)
        for field in ["evidence_gaps", "dropped_args", "unused_tactics"]:
            self.assertIn(field, gaps, f"gaps 缺少 {field}")
            self.assertIsInstance(gaps[field], list, f"{field} 不是 list")

    def test_layer2_recommendations_nonempty(self):
        """Layer2: 改进建议非空。"""
        recs = self.result["reflection"]["recommendations"]
        self.assertIsInstance(recs, list)
        self.assertGreater(len(recs), 0, "recommendations 为空")

    def test_layer2_review_nonempty(self):
        """Layer2: 复盘字段非空。"""
        review = self.result["reflection"]["review"]
        self.assertIsInstance(review, dict)
        self.assertGreater(len(review), 0, "review 为空")

    def test_layer3_all_updated(self):
        """Layer3: 贝叶斯+Elo+CBR 三参数均更新成功。"""
        train = self.result["training"]
        self.assertTrue(train.get("bayesian_updated"), "bayesian 未更新")
        self.assertTrue(train.get("elo_updated"), "elo 未更新")
        self.assertTrue(train.get("cbr_ingested"), "cbr 未入库")


# ── E2E 验收: 认知闭环 ───────────────────────────────────────

class TestE2ECognitiveLoop(unittest.TestCase):
    """验证认知闭环: record → recall → verify。"""

    def test_reflection_memory_id(self):
        """Layer2 反思 record 写入后返回 memory_id (认知适配器可用时)。"""
        from c_drive_agent import run_post_debate_pipeline, _load_cognitive_adapter
        cog = _load_cognitive_adapter()
        result = run_post_debate_pipeline(
            topic="BTC是数字黄金",
            transcript=_make_transcript(),
            verdict=_make_verdict(),
            llm_fn=_make_llm(),
        )
        memory_id = result["reflection"].get("memory_id")
        if cog is not None:
            # 认知适配器可用 → memory_id 应非空
            self.assertIsNotNone(memory_id, "认知适配器可用但 memory_id 为空")
            # recall 验证可检索
            recalled = cog.recall(
                context="BTC 数字黄金 辩论反思", top_k=3, min_quality="C")
            memories = recalled.get("memories", recalled) if isinstance(recalled, dict) else recalled
            self.assertIsInstance(memories, list)
            self.assertGreater(len(memories), 0, "recall 返回空")
        else:
            # 认知适配器不可用 → FAIL-OPEN，memory_id 可能为 None
            print("\n[INFO] 认知适配器不可用，FAIL-OPEN 验证通过")

    def test_cognitive_record_recall_roundtrip(self):
        """直接调用认知工具验证 record→recall 闭环。"""
        from c_drive_agent import _load_cognitive_adapter
        cog = _load_cognitive_adapter()
        if cog is None:
            print("[INFO] 认知适配器不可用，跳过 record→recall 闭环测试")
            return
        # record
        mid = cog.record(
            content="[E2E验收] 三层管道认知闭环测试记录",
            quality_level="C",
            tags="e2e,cognitive_loop,debate_pipeline",
        )
        if isinstance(mid, dict):
            mid = mid.get("memory_id")
        self.assertIsNotNone(mid, "record 返回 None memory_id")
        # recall
        recalled = cog.recall(
            context="E2E验收 认知闭环", top_k=5, min_quality="C")
        memories = recalled.get("memories", recalled) if isinstance(recalled, dict) else recalled
        self.assertIsInstance(memories, list)
        # verify
        if mid:
            cog.verify(memory_id=mid, success=True)
            print(f"[INFO] verify 成功: {mid}")


# ── E2E 验收: FAIL-OPEN ──────────────────────────────────────

class TestE2EFailOpen(unittest.TestCase):
    """验证各层 FAIL-OPEN 独立降级不崩溃。"""

    def test_no_llm_all_layers_degrade(self):
        """无 LLM 时三层均降级但不崩溃。"""
        from c_drive_agent import run_post_debate_pipeline
        result = run_post_debate_pipeline(
            topic="BTC是数字黄金",
            transcript=_make_transcript(),
            verdict=_make_verdict(),
            llm_fn=None,  # 无 LLM
        )
        self.assertIsInstance(result, dict)
        self.assertIn("adjudication", result)
        self.assertIn("reflection", result)
        self.assertIn("training", result)
        # 降级时 winner 用 verdict 兜底
        self.assertEqual(result["adjudication"]["winner"], "bull")
        # Layer3 训练层不依赖 LLM，即使 Layer1/2 降级仍可执行训练更新
        # 关键验证: 不崩溃 + 三层结构完整 (已在上方断言)

    def test_llm_exception_degrades_gracefully(self):
        """LLM 异常时降级不崩溃。"""
        from c_drive_agent import run_post_debate_pipeline

        def bad_llm(prompt, max_tokens=600):
            raise RuntimeError("LLM 服务不可用")

        result = run_post_debate_pipeline(
            topic="BTC是数字黄金",
            transcript=_make_transcript(),
            verdict=_make_verdict(),
            llm_fn=bad_llm,
        )
        self.assertIsInstance(result, dict)
        # 降级时仍有三层结构
        self.assertIn("adjudication", result)
        self.assertIn("reflection", result)
        self.assertIn("training", result)

    def test_partial_llm_failure(self):
        """部分 LLM 调用失败时其他层仍执行。"""
        from c_drive_agent import run_post_debate_pipeline
        call_count = [0]

        def partial_llm(prompt, max_tokens=600):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("首次调用失败")
            return json.dumps({
                "bull": {d: 4 for d in ["clarity", "arrangement", "topic_relevance",
                                         "emotional_appeal", "fact_authenticity",
                                         "logical_validity"]},
                "bear": {d: 3 for d in ["clarity", "arrangement", "topic_relevance",
                                         "emotional_appeal", "fact_authenticity",
                                         "logical_validity"]},
                "rfd": "正方领先",
                "key_clash_points": ["稀缺性vs波动性"],
            })

        result = run_post_debate_pipeline(
            topic="BTC是数字黄金",
            transcript=_make_transcript(),
            verdict=_make_verdict(),
            llm_fn=partial_llm,
        )
        self.assertIsInstance(result, dict)
        # 至少有一层执行成功 (不全部崩溃)
        has_result = bool(result.get("adjudication") or result.get("reflection"))
        self.assertTrue(has_result, "所有层都崩溃了")


# ── E2E 验收: 延迟 ───────────────────────────────────────────

class TestE2ELatency(unittest.TestCase):
    """HC11: Layer1-3 总延迟 < 10s。"""

    def test_pipeline_latency_under_10s(self):
        """三层管道总延迟 < 10 秒。"""
        from c_drive_agent import run_post_debate_pipeline
        start = time.time()
        result = run_post_debate_pipeline(
            topic="BTC是数字黄金",
            transcript=_make_transcript(),
            verdict=_make_verdict(),
            llm_fn=_make_llm(),
        )
        elapsed = time.time() - start
        self.assertLess(elapsed, 10.0, f"管道延迟 {elapsed:.2f}s > 10s")
        print(f"\n[INFO] 三层管道总延迟: {elapsed:.3f}s")

    def test_no_llm_latency_under_5s(self):
        """无 LLM 降级模式延迟 < 5 秒。"""
        from c_drive_agent import run_post_debate_pipeline
        start = time.time()
        run_post_debate_pipeline(
            topic="BTC是数字黄金",
            transcript=_make_transcript(),
            verdict=_make_verdict(),
            llm_fn=None,
        )
        elapsed = time.time() - start
        self.assertLess(elapsed, 5.0, f"降级延迟 {elapsed:.2f}s > 5s")
        print(f"[INFO] 降级模式延迟: {elapsed:.3f}s")


# ── E2E 验收: 冷启动 ─────────────────────────────────────────

class TestE2EColdStart(unittest.TestCase):
    """验证冷启动退化: 首次调用 get_cold_start_phase() == 'cold_start'。"""

    def test_cold_start_phase_initial(self):
        """新建 DebateTrainer 时冷启动阶段为 cold_start。"""
        from debate_trainer import DebateTrainer
        trainer = DebateTrainer()
        phase = trainer.get_cold_start_phase()
        self.assertEqual(phase, "cold_start")

    def test_pipeline_does_not_crash_on_cold_start(self):
        """冷启动条件下管道仍正常执行。"""
        from c_drive_agent import run_post_debate_pipeline
        result = run_post_debate_pipeline(
            topic="BTC是数字黄金",
            transcript=_make_transcript(),
            verdict=_make_verdict(),
            llm_fn=_make_llm(),
        )
        # 冷启动时 training 仍应成功 (CBR 入库, 即使检索会跳过)
        self.assertTrue(result["training"]["cbr_ingested"],
                        "冷启动时 CBR 入库应成功")


# ── E2E 验收: 管道完整性汇总 ─────────────────────────────────

class TestE2EPipelineSummary(unittest.TestCase):
    """E2E 验收汇总: 一次调用验证全链路。"""

    def test_full_pipeline_e2e(self):
        """一次调用完成全链路 E2E 验收。"""
        from c_drive_agent import run_post_debate_pipeline
        result = run_post_debate_pipeline(
            topic="BTC是数字黄金",
            transcript=_make_transcript(),
            verdict=_make_verdict(),
            llm_fn=_make_llm(),
            bull_persona="乐观分析师",
            bear_persona="谨慎风控师",
        )

        # ── 三层结构完整 ──
        self.assertIn("adjudication", result)
        self.assertIn("reflection", result)
        self.assertIn("training", result)

        # ── Layer1 关键字段 ──
        adj = result["adjudication"]
        self.assertIn("winner", adj)
        self.assertIn("rfd", adj)
        self.assertIn("key_clash_points", adj)
        self.assertIn("dimension_comparison", adj)
        self.assertIn("bull_total", adj)
        self.assertIn("bear_total", adj)
        self.assertIn("timestamp", adj)
        self.assertTrue(adj["rfd"], "RFD 非空")
        self.assertGreater(len(adj["key_clash_points"]), 0)
        self.assertIn(adj["winner"], ["bull", "bear", "draw"])

        # ── Layer2 关键字段 ──
        refl = result["reflection"]
        self.assertIn("strategy_tags", refl)
        self.assertIn("gaps", refl)
        self.assertIn("recommendations", refl)
        self.assertIn("review", refl)
        self.assertIn("strategy_analysis", refl)
        self.assertGreater(len(refl["strategy_tags"]), 0, "策略标签非空")
        for f in ["evidence_gaps", "dropped_args", "unused_tactics"]:
            self.assertIn(f, refl["gaps"])
        self.assertGreater(len(refl["recommendations"]), 0, "建议非空")

        # ── Layer3 关键字段 ──
        train = result["training"]
        self.assertIn("bayesian_updated", train)
        self.assertIn("elo_updated", train)
        self.assertIn("cbr_ingested", train)
        self.assertTrue(train["bayesian_updated"], "贝叶斯更新")
        self.assertTrue(train["elo_updated"], "Elo 更新")
        self.assertTrue(train["cbr_ingested"], "CBR 入库")

        print("\n[INFO] E2E 全链路验收通过: 三层产出完整 + 训练参数更新")


if __name__ == "__main__":
    unittest.main(verbosity=2)
