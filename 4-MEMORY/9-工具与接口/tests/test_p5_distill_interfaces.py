#!/usr/bin/env python3
"""
P5: 7标准接口+2便捷方法补全校验 — TDD RED→GREEN
覆盖:
  - distill_candidates()          (7标准接口之1)
  - run_distill_from_review()     (便捷方法之1)
  - search_similar_cases()        (便捷方法之2 = search_similar别名)
"""
import json
import sys
import os
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vector_memory_interface import VectorMemoryInterface


_QUALITY_RANK = {"S": 0, "A": 1, "B": 2, "C": 3, "D": 4}


def _make_seeded_vmi(tmp_db: str):
    """构造带种子数据的VMI，覆盖多质量/多验证/多置信组合。"""
    vm = VectorMemoryInterface(storage_path=tmp_db, engine="numpy")
    seeds = [
        # (content, quality, conf, tags, verify_count, memory_type, source)
        ("BTC趋势突破：MA20之上且成交量放大2倍时LONG胜率高", "S", 0.98, ["BTC", "趋势"], 15, "strategy", "backtest_2026q2"),
        ("马丁加仓间隔：同一方向至少等4根1H K线再下一档", "A", 0.82, ["马丁", "风控"], 6, "risk", "live_trade_0712"),
        ("OKX下单: SL/TP参数名必须用 stop_loss_px/take_profit_px", "A", 0.88, ["OKX", "API"], 4, "lesson", "bugfix_AUG11"),
        ("文档代码对齐：先SPEC再实现，A8校验闭环", "B", 0.65, ["工程", "A8"], 2, "principle", "mu_dev_core"),
        ("MACD金叉信号：在震荡市中胜率仅约47%，不宜单独使用", "B", 0.55, ["MACD", "指标"], 1, "strategy", "backtest_pool"),
        ("C级记忆：仅1次弱验证，confidence低（不应被蒸馏）", "C", 0.30, ["测试"], 0, "noise", "dummy"),
        ("S级归档记忆（应跳过）", "archived", 0.20, [], 5, "archived", "old"),
        ("D级证伪记忆（应跳过）", "D", 0.05, ["反例"], 3, "falsified", "invalid"),
    ]
    for content, q, conf, tags, vc, mt, src in seeds:
        vm.add(content, quality_level=q, confidence=conf, tags=tags,
               memory_type=mt, source=src, verify_count=vc)
    return vm


# ============================================================
# 1. 接口存在性检查
# ============================================================

def test_distill_candidates_method_exists_and_callable():
    """distill_candidates 必须存在且可调用（入参 min_quality, limit）"""
    with tempfile.TemporaryDirectory() as td:
        db = str(Path(td) / "t.db")
        vm = VectorMemoryInterface(storage_path=db, engine="numpy")
        assert hasattr(vm, "distill_candidates"), "缺少方法: distill_candidates"
        assert callable(getattr(vm, "distill_candidates")), "distill_candidates 不可调用"
        # 空DB调用应返回空列表，不抛异常
        result = vm.distill_candidates(min_quality="B", limit=5)
        assert isinstance(result, list), "返回值必须是 list"
        vm.close()


def test_search_similar_cases_alias_exists_and_matches_search_similar():
    """search_similar_cases 必须是 search_similar 的规范别名。"""
    with tempfile.TemporaryDirectory() as td:
        db = str(Path(td) / "t.db")
        vm = VectorMemoryInterface(storage_path=db, engine="numpy")
        mid = vm.add("BTC MA20 趋势突破后跟涨", quality_level="B", confidence=0.55, tags=["BTC"])
        assert hasattr(vm, "search_similar_cases"), "缺少便捷方法别名: search_similar_cases"
        assert callable(getattr(vm, "search_similar_cases")), "search_similar_cases 不可调用"
        # 别名结果应与 search_similar 等价
        a = vm.search_similar_cases("BTC 趋势突破跟涨", top_k=5, threshold=0.2)
        b = vm.search_similar("BTC 趋势突破跟涨", top_k=5, threshold=0.2)
        assert [r.id for r in a] == [r.id for r in b], "search_similar_cases 与 search_similar 结果必须等价"
        vm.close()


def test_run_distill_from_review_exists_callable_returns_dict():
    """run_distill_from_review(review_data) 必须存在，返回统计dict。"""
    with tempfile.TemporaryDirectory() as td:
        db = str(Path(td) / "t.db")
        vm = VectorMemoryInterface(storage_path=db, engine="numpy")
        assert hasattr(vm, "run_distill_from_review"), "缺少便捷方法: run_distill_from_review"
        assert callable(getattr(vm, "run_distill_from_review")), "run_distill_from_review 不可调用"
        # 空review返回空统计结构
        stats = vm.run_distill_from_review({})
        assert isinstance(stats, dict), "必须返回 dict"
        assert "processed" in stats, "统计结果必须包含 processed 字段"
        assert "upgraded" in stats, "统计结果必须包含 upgraded 字段"
        assert "skipped" in stats, "统计结果必须包含 skipped 字段"
        vm.close()


# ============================================================
# 2. distill_candidates 行为校验
# ============================================================

def test_distill_candidates_b_quality_filters_noise_and_sorts_priority():
    """min_quality='B'时：仅返回 S/A/B；跳过 archived/D/C级；顺序 S>A>B 且验证次数多>少。"""
    with tempfile.TemporaryDirectory() as td:
        db = str(Path(td) / "seed.db")
        vm = _make_seeded_vmi(db)

        cands = vm.distill_candidates(min_quality="B", limit=100)

        # 合格条件(来自DistillScheduler):
        #   B级: verify≥1 AND conf≥0.40
        #   A级: verify≥3 AND conf≥0.70
        #   S级: verify≥10 AND conf≥0.95
        # 首先，数量：种子数据中合格的应该是 S(1), A(2), B(2) → 共5条
        ids = [c["id"] for c in cands]
        qualities = [c["quality_level"] for c in cands]
        # 绝对排除 archived / D / 不达标的C
        assert "archived" not in qualities
        assert "D" not in qualities
        assert "C" not in qualities, "不达标的C级记忆不应进入蒸馏候选"
        # 顺序：S 应在 A 前，A 应在 B 前
        ranks = [_QUALITY_RANK[q] for q in qualities]
        assert ranks == sorted(ranks), f"候选顺序必须按质量 S>A>B，实际: {qualities}"
        # 每条候选必须带蒸馏必要字段（对齐 DistillScheduler.distill_to_global）
        required_keys = {"id", "content", "quality_level", "confidence",
                         "tags", "memory_type", "source", "verify_count"}
        for c in cands:
            missing = required_keys - set(c.keys())
            assert not missing, f"候选缺蒸馏字段: {missing}"
        vm.close()


def test_distill_candidates_limit_and_min_quality_a():
    """min_quality='A' 只返回 S/A；limit 生效截断。"""
    with tempfile.TemporaryDirectory() as td:
        db = str(Path(td) / "seed.db")
        vm = _make_seeded_vmi(db)

        cands = vm.distill_candidates(min_quality="A", limit=2)

        assert len(cands) <= 2, "limit=2 应截断"
        for c in cands:
            assert c["quality_level"] in ("S", "A"), "min_quality=A 不应含 B"
        vm.close()


def test_distill_candidates_candidate_tags_are_list_not_str():
    """tags 字段必须是 list（不能是 JSON 字符串）。"""
    with tempfile.TemporaryDirectory() as td:
        db = str(Path(td) / "seed.db")
        vm = _make_seeded_vmi(db)
        cands = vm.distill_candidates(min_quality="B")
        for c in cands:
            assert isinstance(c["tags"], list), f"tags 必须是 list，实际 {type(c['tags'])}: {c['tags']}"
        vm.close()


# ============================================================
# 3. run_distill_from_review 行为校验
# ============================================================

def test_run_distill_from_review_matches_by_keyword_and_increments_verify():
    """review_data 中含 matched_patterns/doc_only_functions → 对匹配记忆 increment_verify。"""
    with tempfile.TemporaryDirectory() as td:
        db = str(Path(td) / "seed.db")
        vm = _make_seeded_vmi(db)

        # 构造类 A8Review：匹配"OKX""MACD"关键词
        review = {
            "subsystem": "test",
            "matched_functions": ["place_order"],
            "doc_only_functions": [],
            "code_only_functions": [],
            "matched_patterns": ["OKX", "MACD"],  # 自定义扩展：review 命中的关键词
            "consistency_score": 75.0,
        }

        # 先获取 review 前的 verify_count
        before_okx = [r for r in vm.search("OKX", top_k=1)][0]
        before_macd = [r for r in vm.search("MACD金叉", top_k=1)][0]

        stats = vm.run_distill_from_review(review)

        assert stats["processed"] >= 2, "至少应处理2条匹配记忆(OKX+MACD)"
        assert stats["upgraded"] >= 0, "upgraded 不能为负"

        # 验证 verify_count 被递增
        after_okx = vm.get(before_okx.id)
        after_macd = vm.get(before_macd.id)
        assert after_okx["verify_count"] >= before_okx.metadata["verify_count"] + 1, \
            "匹配到 review 的记忆 verify_count 应+1"
        assert after_macd["verify_count"] >= before_macd.metadata["verify_count"] + 1, \
            "匹配到 review 的记忆 verify_count 应+1"
        vm.close()


def test_run_distill_from_review_auto_upgrades_quality_when_thresholds_met():
    """verify_count 上升达到 B→A 或 A→S 阈值时，质量自动升级。"""
    with tempfile.TemporaryDirectory() as td:
        db = str(Path(td) / "t.db")
        vm = VectorMemoryInterface(storage_path=db, engine="numpy")
        # 构造边界记忆：A级 conf=0.72 verify=2 → verify+1后=3，刚好触发 A→S？不，S阈值是 verify≥10 AND conf≥0.95
        # 换：B级 conf=0.72 verify=2 → verify+1后=3，达到A级阈值(verify≥3, conf≥0.70) → 应升级到A
        mid = vm.add(
            "测试边界：B级高置信，差1次验证即可升A",
            quality_level="B", confidence=0.72, tags=["边界"], verify_count=2)

        review = {"matched_patterns": ["边界"], "consistency_score": 90.0}
        stats = vm.run_distill_from_review(review)

        after = vm.get(mid)
        # B(conf≥0.40, verify≥1) → A阈值：conf≥0.70 + verify≥3
        # conf=0.72≥0.70 ✔️, verify 原来=2 +1=3 ✔️ → 应升级到 A
        assert after["quality_level"] == "A", \
            f"B级达到A阈值(conf≥0.70,verify≥3)应升级到A，实际={after['quality_level']}, verify={after['verify_count']}"
        assert stats["upgraded"] >= 1, "应有1条质量被升级"
        vm.close()


# ============================================================
# 运行器
# ============================================================

_TESTS = [
    ("test_distill_candidates_method_exists_and_callable", test_distill_candidates_method_exists_and_callable),
    ("test_search_similar_cases_alias_exists_and_matches_search_similar", test_search_similar_cases_alias_exists_and_matches_search_similar),
    ("test_run_distill_from_review_exists_callable_returns_dict", test_run_distill_from_review_exists_callable_returns_dict),
    ("test_distill_candidates_b_quality_filters_noise_and_sorts_priority", test_distill_candidates_b_quality_filters_noise_and_sorts_priority),
    ("test_distill_candidates_limit_and_min_quality_a", test_distill_candidates_limit_and_min_quality_a),
    ("test_distill_candidates_candidate_tags_are_list_not_str", test_distill_candidates_candidate_tags_are_list_not_str),
    ("test_run_distill_from_review_matches_by_keyword_and_increments_verify", test_run_distill_from_review_matches_by_keyword_and_increments_verify),
    ("test_run_distill_from_review_auto_upgrades_quality_when_thresholds_met", test_run_distill_from_review_auto_upgrades_quality_when_thresholds_met),
]


def main():
    passed = 0
    failed = 0
    for name, fn in _TESTS:
        print(f"\n▶  运行: {name}")
        try:
            fn()
            print(f"✅ {name} 通过")
            passed += 1
        except Exception as e:
            print(f"❌ {name} 失败: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{'='*60}")
    print(f"📊 结果: 通过 {passed} / {passed+failed}, 失败 {failed}")
    print(f"{'='*60}")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
