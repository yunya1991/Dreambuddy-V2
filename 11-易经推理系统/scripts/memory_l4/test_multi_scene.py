# -*- coding: utf-8 -*-
"""多场景模拟测试 — 验证L4记忆系统统一接口工作正常

8个场景覆盖：
1. 基础CRUD完整闭环
2. 多类型搜索（case/review/distill/all）
3. 过滤条件搜索（inst_id/decision/is_profit/system_source）
4. 关键词搜索（带query vs 不带query）
5. 蒸馏候选（不同质量阈值）
6. 健康检查与统计信息
7. CBR语义相似度检索
8. 异常处理与边界条件
"""
import json
import os
import sys

sys.path.insert(0, ".")
from scripts.memory_l4.app_memory_interface import (
    search, add, update, get, stats, distill_candidates, healthcheck,
    search_similar_cases,
    APP_MEMORY_ID, APP_MEMORY_VERSION,
)

PASS = 0
FAIL = 0
TEST_IDS = []  # 记录测试创建的ID用于清理
SEP = "=" * 60


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {detail}")


def section(title):
    print(f"\n{SEP}")
    print(f"  场景：{title}")
    print(f"{SEP}")


# ════════════════════════════════════════════════════════════
# 场景1：基础CRUD完整闭环
# ════════════════════════════════════════════════════════════
section("1. 基础CRUD — 添加→获取→更新→验证")

case_data = {
    "type": "case",
    "inst_id": "BTC-USDT-SWAP",
    "decision": "LONG",
    "confidence": 0.85,
    "system_source": "multi_scene_test",
    "decision_outcome": {"pnl_pct": 3.2, "drawdown": 1.5},
    "environment_snapshot": {"regime": "trending_up"},
    "tags": ["test", "scene1", "crud"],
}
new_id = add(case_data)
TEST_IDS.append(new_id)
check("Add 返回有效ID", new_id.startswith("AM-TRD-001-CASE-"), f"got {new_id}")

retrieved = get(new_id)
check("Get 返回完整数据", retrieved is not None and retrieved.get("inst_id") == "BTC-USDT-SWAP")
check("Get 自动生成timestamp", "timestamp" in retrieved if retrieved else False)

upd_ok = update(new_id, {"confidence": 0.95, "review": {"status": "reviewed"}})
check("Update 成功", upd_ok is True)

updated = get(new_id)
check("Update 字段已生效", updated.get("confidence") == 0.95)
check("Update 新字段已添加", updated.get("review", {}).get("status") == "reviewed")


# ════════════════════════════════════════════════════════════
# 场景2：多类型搜索
# ════════════════════════════════════════════════════════════
section("2. 多类型搜索 — case/review/distill/all")

case_results = search(memory_type="case", top_k=3)
check("Case 搜索有结果", len(case_results) > 0)
check("Case 结果类型正确", all(r["type"] == "case" for r in case_results))

review_results = search(memory_type="review", top_k=3)
check("Review 搜索有结果", len(review_results) > 0)
check("Review 结果类型正确", all(r["type"] == "review" for r in review_results))

distill_results = search(memory_type="distill", top_k=3)
check("Distill 搜索有结果", len(distill_results) > 0)
check("Distill 结果类型正确", all(r["type"] == "distill" for r in distill_results))

all_results = search(memory_type="all", top_k=10)
check("All 搜索返回多类型", len(set(r["type"] for r in all_results)) >= 2)


# ════════════════════════════════════════════════════════════
# 场景3：过滤条件搜索
# ════════════════════════════════════════════════════════════
section("3. 过滤条件搜索 — inst_id/decision/is_profit/system_source")

filter_case = {
    "type": "case",
    "inst_id": "ETH-USDT-SWAP",
    "decision": "SHORT",
    "confidence": 0.7,
    "system_source": "multi_scene_test",
    "decision_outcome": {"pnl_pct": -1.5, "drawdown": 2.0},
    "environment_snapshot": {"regime": "ranging"},
    "tags": ["test", "scene3", "filter"],
}
filter_id = add(filter_case)
TEST_IDS.append(filter_id)

eth_results = search(filters={"inst_id": "ETH-USDT-SWAP"}, memory_type="case", top_k=10)
check("inst_id 过滤生效", all(r["data"].get("inst_id") == "ETH-USDT-SWAP" for r in eth_results))
check("能找到刚添加的ETH案例", len(eth_results) > 0)

src_results = search(filters={"system_source": "multi_scene_test"}, memory_type="case", top_k=10)
check("system_source 过滤生效", all(r["data"].get("system_source") == "multi_scene_test" for r in src_results))
check("能找到2条测试数据", len(src_results) >= 2)

profit_results = search(filters={"is_profit": False}, memory_type="case", top_k=50)
check("is_profit=False 过滤生效", all(
    (r["data"].get("decision_outcome") or {}).get("pnl_pct", 0) <= 0
    for r in profit_results
))


# ════════════════════════════════════════════════════════════
# 场景4：关键词搜索
# ════════════════════════════════════════════════════════════
section("4. 关键词搜索 — 带query vs 不带query")

kw_results = search(query="BTC", memory_type="case", top_k=5)
check("关键词搜索有结果", len(kw_results) > 0)
check("关键词搜索按分数排序", all(
    kw_results[i]["score"] >= kw_results[i + 1]["score"]
    for i in range(len(kw_results) - 1)
))

no_q_results = search(query="", memory_type="case", top_k=5)
check("空query返回全部", len(no_q_results) == 5)

no_match = search(query="ZZZNOTEXIST12345", memory_type="case", top_k=5)
check("无匹配query返回空", len(no_match) == 0)


# ════════════════════════════════════════════════════════════
# 场景5：蒸馏候选 — 不同质量阈值
# ════════════════════════════════════════════════════════════
section("5. 蒸馏候选 — 不同min_quality阈值")

high_q = distill_candidates(min_quality=0.8, limit=20)
check("高质量阈值候选", all(c["quality_score"] >= 0.8 for c in high_q))

mid_q = distill_candidates(min_quality=0.3, limit=20)
check("中质量阈值候选", all(c["quality_score"] >= 0.3 for c in mid_q))
check("中阈值结果 >= 高阈值结果", len(mid_q) >= len(high_q))

low_q = distill_candidates(min_quality=0.0, limit=100)
check("零阈值返回最多", len(low_q) >= len(mid_q))

if low_q:
    c = low_q[0]
    check("候选包含claim", "claim" in c)
    check("候选包含kind", "kind" in c)
    check("候选包含quality_score", "quality_score" in c)
    check("候选包含id", "id" in c)


# ════════════════════════════════════════════════════════════
# 场景6：健康检查与统计信息
# ════════════════════════════════════════════════════════════
section("6. 健康检查与统计 — 结构与数据完整性")

hc = healthcheck()
check("healthcheck 返回status", hc.get("status") in ("healthy", "degraded", "unhealthy"))
check("healthcheck 包含app_memory_id", hc.get("app_memory_id") == APP_MEMORY_ID)
check("healthcheck 包含version", hc.get("version") == APP_MEMORY_VERSION)
check("healthcheck 包含pipeline", "pipeline" in hc)
check("healthcheck pipeline有cases", "cases" in hc.get("pipeline", {}))
check("healthcheck pipeline有reviews", "reviews" in hc.get("pipeline", {}))
check("healthcheck pipeline有distills", "distills" in hc.get("pipeline", {}))

st = stats()
check("stats 包含total_memories", "total_memories" in st)
check("stats total > 0", st["total_memories"] > 0)
check("stats 包含by_type", "by_type" in st)
check("stats by_type有case", "case" in st.get("by_type", {}))
check("stats by_type有review", "review" in st.get("by_type", {}))
check("stats by_type有distill", "distill" in st.get("by_type", {}))
check("stats 包含health", "health" in st)
check("stats 包含evolution", "evolution" in st)
check("stats total = case + review + distill + stats",
      st["total_memories"] == st["by_type"]["case"] + st["by_type"]["review"] + st["by_type"]["distill"] + st["by_type"]["stats_snapshot"])


# ════════════════════════════════════════════════════════════
# 场景7：CBR语义相似度检索
# ════════════════════════════════════════════════════════════
section("7. CBR语义相似度检索 — search_similar_cases")

try:
    similar = search_similar_cases(inst_id="BTC-USDT-SWAP", regime="trending_up", decision="LONG", top_k=3)
    check("CBR检索不抛异常", True)
    check("CBR返回列表", isinstance(similar, list))
    if similar:
        check("CBR结果有id", "id" in similar[0])
        # CBR引擎可用时有similarity/case字段；回退到普通搜索时有score字段
        is_cbr_mode = "similarity" in similar[0]
        if is_cbr_mode:
            check("CBR模式 — 有similarity字段", True)
            check("CBR模式 — 有case字段", "case" in similar[0])
            check("CBR相似度排序", all(
                similar[i]["similarity"] >= similar[i + 1]["similarity"]
                for i in range(len(similar) - 1)
            ))
        else:
            check("回退模式 — 普通搜索结果", "score" in similar[0])
            check("回退模式 — 有type字段", "type" in similar[0])
    else:
        check("CBR返回空列表（无数据时正常）", True)
except Exception as e:
    check("CBR检索不抛异常", False, str(e))


# ════════════════════════════════════════════════════════════
# 场景8：异常处理与边界条件
# ════════════════════════════════════════════════════════════
section("8. 异常处理 — 错误ID/不存在/无效类型")

not_exist = get("AM-TRD-001-CASE-NOT_EXIST_99999")
check("Get 不存在的ID返回None", not_exist is None)

upd_not_exist = update("AM-TRD-001-CASE-NOT_EXIST_99999", {"x": 1})
check("Update 不存在的ID返回False", upd_not_exist is False)

bad_format = get("INVALID-ID-FORMAT")
check("Get 格式错误ID返回None", bad_format is None)

try:
    add({"type": "unknown_type", "data": "test"})
    check("Add 不支持类型抛异常", False, "no exception raised")
except ValueError:
    check("Add 不支持类型抛ValueError", True)
except Exception as e:
    check("Add 不支持类型抛ValueError", False, f"got {type(e).__name__}")

auto_id = add({"type": "case", "inst_id": "AUTO-ID-TEST"})
TEST_IDS.append(auto_id)
check("Add 无case_id时自动生成", auto_id.startswith("AM-TRD-001-CASE-CASE_") and len(auto_id) > 30)

auto_rev_id = add({"type": "review", "case_id": "AUTO_REV_TEST"})
TEST_IDS.append(auto_rev_id)
check("Add 无review_id时自动生成", auto_rev_id.startswith("AM-TRD-001-REV-REV_"))


# ════════════════════════════════════════════════════════════
# 清理测试数据
# ════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print(f"  清理 {len(TEST_IDS)} 条测试数据...")
print(f"{SEP}")
from scripts.memory_l4.app_memory_interface import memory_l4_cases_dir, memory_l4_reviews_dir

cleaned = 0
for tid in TEST_IDS:
    parts = tid.replace(f"{APP_MEMORY_ID}-", "")
    type_prefix, _, raw_id = parts.partition("-")
    if type_prefix == "CASE":
        path = memory_l4_cases_dir() / f"{raw_id}.json"
    elif type_prefix == "REV":
        path = memory_l4_reviews_dir() / f"{raw_id}.json"
    else:
        continue
    if path.exists():
        os.remove(path)
        cleaned += 1
print(f"  清理完成: {cleaned} 条")

# ════════════════════════════════════════════════════════════
# 汇总
# ════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print(f"  测试结果汇总")
print(f"{SEP}")
print(f"  通过: {PASS}")
print(f"  失败: {FAIL}")
print(f"  总计: {PASS + FAIL}")
print(f"  通过率: {PASS / (PASS + FAIL) * 100:.1f}%")
print(f"{SEP}")
