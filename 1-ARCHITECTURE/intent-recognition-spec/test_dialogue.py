#!/usr/bin/env python3
"""
多轮对话测试脚本

验证 Phase 2 对话状态管理的核心功能：
1. 指代消解 — "那它呢" → 继承上一轮标的
2. 槽位继承 — "改成200股" → 继承 stock + action
3. 修正回滚 — "不是买，是卖" → 修正操作方向
4. 确认流程 — 高风险交易二次确认
5. 取消 — "算了" → 取消待确认操作
"""

import sys
import os
import json
from pathlib import Path

# 设置路径
SPEC_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SPEC_DIR))
sys.path.insert(0, str(SPEC_DIR.parent.parent / "16-调控系统" / "core"))

from intent_classifier import classify_intent
from dialogue_state import DialogueStateManager


def test_scenario(name: str, inputs: list, expected_checks: list):
    """运行一个多轮对话场景测试"""
    print(f"\n{'='*60}")
    print(f"🧪 场景: {name}")
    print(f"{'='*60}")

    dsm = DialogueStateManager()
    results = []

    for i, user_input in enumerate(inputs, 1):
        print(f"\n[Turn {i}] 用户: {user_input}")

        result = dsm.process(
            user_input,
            classify_fn=lambda text, ctx: classify_intent(text, ctx),
        )

        # 打印关键信息
        print(f"  意图: {result.get('intent_primary')}/{result.get('intent_secondary')}")
        print(f"  槽位: {json.dumps(result.get('slots', {}), ensure_ascii=False)}")
        print(f"  置信度: {result.get('confidence', 'N/A')}")

        if result.get("reference_resolved"):
            print(f"  指代消解: {json.dumps(result['reference_resolved'], ensure_ascii=False)}")
        if result.get("slots_inherited"):
            print(f"  槽位继承: ✅")
        if result.get("confirmation_required"):
            print(f"  ⚠️ 需要确认: {result.get('confirm_message', '')}")
        if result.get("confirmed"):
            print(f"  ✅ 已确认")
        if result.get("confirmation_flow") == "cancelled":
            print(f"  ❌ 已取消")

        results.append(result)

    # 验证期望
    print(f"\n📋 验证:")
    all_passed = True
    for check in expected_checks:
        turn_idx = check.get("turn", 0) - 1
        if turn_idx < 0 or turn_idx >= len(results):
            continue

        r = results[turn_idx]
        field = check.get("field", "intent_primary")
        expected_val = check.get("value")

        actual_val = r.get(field)

        # 特殊处理 slots 中的字段
        if field.startswith("slots."):
            slot_name = field.split(".", 1)[1]
            actual_val = r.get("slots", {}).get(slot_name)

        passed = str(actual_val) == str(expected_val)
        status = "✅" if passed else "❌"
        desc = check.get("desc", f"Turn {turn_idx+1} {field}={expected_val}")
        print(f"  {status} {desc}: 期望={expected_val}, 实际={actual_val}")
        if not passed:
            all_passed = False

    return all_passed


def main():
    print("🤖 交易系统对话状态管理测试")
    print("=" * 60)

    all_passed = True

    # ── 场景 1: 指代消解 ─────────────────────────────────────────
    all_passed &= test_scenario(
        "指代消解 — '那它呢' 继承上一轮标的",
        inputs=[
            "茅台走势怎么样？",
            "那它呢",  # "它" 应该解析为 "茅台"
        ],
        expected_checks=[
            {"turn": 1, "field": "intent_primary", "value": "analysis", "desc": "第1轮意图"},
            {"turn": 2, "field": "slots.stock", "value": "贵州茅台", "desc": "第2轮标的继承"},
        ],
    )

    # ── 场景 2: 槽位继承 + 修正 ─────────────────────────────────
    all_passed &= test_scenario(
        "槽位继承 + 修正 — '改成200股' 继承 stock",
        inputs=[
            "帮我买100股茅台",
            "改成200股",  # 应该继承 stock=贵州茅台
        ],
        expected_checks=[
            {"turn": 1, "field": "intent_secondary", "value": "buy", "desc": "第1轮操作"},
            {"turn": 2, "field": "intent_secondary", "value": "modify", "desc": "第2轮修正"},
            {"turn": 2, "field": "slots.quantity", "value": "200", "desc": "第2轮修正数量"},
        ],
    )

    # ── 场景 3: 修正操作方向 ───────────────────────────────────
    all_passed &= test_scenario(
        "修正操作方向 — '不是买，是卖'",
        inputs=[
            "帮我买100股茅台",
            "不是买，是卖",  # 应该修正 action=sell
        ],
        expected_checks=[
            {"turn": 1, "field": "intent_secondary", "value": "buy", "desc": "第1轮操作"},
            {"turn": 2, "field": "intent_secondary", "value": "sell", "desc": "第2轮修正为卖"},
            {"turn": 2, "field": "slots.action", "value": "sell", "desc": "第2轮action修正"},
        ],
    )

    # ── 场景 4: 高风险确认流程 ─────────────────────────────────
    all_passed &= test_scenario(
        "高风险确认流程 — 买入 → 确认",
        inputs=[
            "帮我买100股茅台",
            "好的",  # 确认
        ],
        expected_checks=[
            {"turn": 1, "field": "confirmation_required", "value": True, "desc": "第1轮需要确认"},
            {"turn": 2, "field": "confirmed", "value": True, "desc": "第2轮确认通过"},
        ],
    )

    # ── 场景 5: 取消流程 ───────────────────────────────────────
    all_passed &= test_scenario(
        "取消流程 — 买入 → 取消",
        inputs=[
            "帮我买100股茅台",
            "算了",  # 取消
        ],
        expected_checks=[
            {"turn": 1, "field": "confirmation_required", "value": True, "desc": "第1轮需要确认"},
            {"turn": 2, "field": "confirmation_flow", "value": "cancelled", "desc": "第2轮取消"},
        ],
    )

    # ── 场景 6: 多轮分析+交易 ───────────────────────────────────
    all_passed &= test_scenario(
        "多轮分析 → 交易 — 茅台分析后直接交易",
        inputs=[
            "茅台现在多少钱？",       # query
            "走势怎么样？",           # analysis（继承茅台）
            "帮我买入100股",          # trade/buy（继承茅台）
        ],
        expected_checks=[
            {"turn": 1, "field": "intent_primary", "value": "query", "desc": "第1轮查询"},
            {"turn": 2, "field": "intent_primary", "value": "analysis", "desc": "第2轮分析"},
            {"turn": 2, "field": "slots.stock", "value": "贵州茅台", "desc": "第2轮标的继承"},
            {"turn": 3, "field": "intent_primary", "value": "trade", "desc": "第3轮交易"},
            {"turn": 3, "field": "slots.stock", "value": "贵州茅台", "desc": "第3轮标的继承"},
        ],
    )

    # ── 总结 ────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    if all_passed:
        print("✅ 所有场景测试通过！")
    else:
        print("❌ 部分场景测试失败，请检查上面的 ❌ 项")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
