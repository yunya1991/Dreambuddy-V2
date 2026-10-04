#!/usr/bin/env python3
"""
交易系统意图识别器 - Prompt Engineering Baseline

Phase 1: 基于系统 Prompt 的零样本意图识别基线
模型: Qwen (OpenAI 兼容协议)
输出: 结构化 JSON

用法:
    python intent_classifier.py "茅台现在多少钱？"
    python intent_classifier.py --evaluate  # 运行所有测试用例评估
"""

import json
import sys
import os
import argparse
import time
from pathlib import Path
from typing import Dict, Any, List, Optional

# ── 路径设置 ──────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent.parent.parent
SPEC_DIR = Path(__file__).resolve().parent

# 将项目根目录加入 path，以便导入 qwen_client
sys.path.insert(0, str(BASE_DIR / "16-调控系统" / "core"))

try:
    from qwen_client import chat_completion, QWEN_MODEL
    HAS_QWEN = True
except ImportError:
    HAS_QWEN = False
    print("⚠️  未找到 qwen_client，将使用 mock 模式")


# ── 系统 Prompt 加载 ───────────────────────────────────────────────────────

def load_system_prompt() -> str:
    """从 system_prompt.md 加载系统 Prompt"""
    prompt_file = SPEC_DIR / "system_prompt.md"
    with open(prompt_file, "r", encoding="utf-8") as f:
        content = f.read()

    # 提取 System Prompt 部分（第一个 ``` 代码块）
    lines = content.split("\n")
    in_code_block = False
    prompt_lines = []
    code_block_started = False

    for line in lines:
        if line.strip().startswith("```") and not code_block_started:
            in_code_block = True
            code_block_started = True
            continue
        elif line.strip().startswith("```") and in_code_block:
            in_code_block = False
            break
        if in_code_block:
            prompt_lines.append(line)

    if not prompt_lines:
        # fallback: 返回整个内容
        return content

    return "\n".join(prompt_lines)


# ── 槽位后置归一化 ────────────────────────────────────────────────────────

STOCK_ALIASES = {
    "茅台": "贵州茅台",
    "宁德": "宁德时代",
    "中芯": "中芯国际",
    "比亚迪": "比亚迪",
    "五粮液": "五粮液",
    "平安": "中国平安",
    "招行": "招商银行",
    "美的": "美的集团",
    "海康": "海康威视",
    "隆基": "隆基绿能",
    "光大": "光大证券",
    "中信": "中信证券",
}

TIME_ALIASES = {
    "今天": "today",
    "今日": "today",
    "昨天": "yesterday",
    "昨日": "yesterday",
    "明天": "tomorrow",
    "明日": "tomorrow",
    "本周": "this_week",
    "上周": "last_week",
    "下周": "next_week",
    "本月": "this_month",
    "上月": "last_month",
}

SECTOR_SUFFIXES = ["板块", "概念", "行业", "赛道"]

INDICATOR_ALIASES = {
    "创历史新高": "all_time_high",
    "历史新高": "all_time_high",
    "超卖": "oversold",
    "超买": "overbought",
    "金叉": "golden_cross",
    "死叉": "death_cross",
    "突破": "breakout",
    "背离": "divergence",
}

ORDER_REF_ALIASES = {
    "刚才那单": "last",
    "上一单": "last",
    "刚刚那个": "last",
    "最后那单": "last",
}

QUANTITY_ALIASES = {
    "梭哈": "all_in",
    "全仓": "all_in",
    "满仓": "all_in",
    "全部": "all",
    "所有": "all",
    "清仓": "all",
}


def normalize_slots(result: Dict[str, Any]) -> Dict[str, Any]:
    """对模型输出的槽位进行后置归一化"""
    slots = result.get("slots", {})
    if not slots:
        return result

    normalized = {}

    for key, val in slots.items():
        if val is None:
            normalized[key] = val
            continue

        val_str = str(val).strip()

        # 1. 标的名归一化
        if key in ("stock",):
            normalized[key] = STOCK_ALIASES.get(val_str, val_str)

        # 2. 时间范围归一化
        elif key in ("time_range", "trigger_time"):
            normalized[key] = TIME_ALIASES.get(val_str, val_str)

        # 3. 板块名归一化（去掉"板块"/"概念"等后缀）
        elif key in ("sector",):
            cleaned = val_str
            for suffix in SECTOR_SUFFIXES:
                if cleaned.endswith(suffix):
                    cleaned = cleaned[: -len(suffix)]
                    break
            normalized[key] = cleaned

        # 4. 指标归一化
        elif key in ("indicator",):
            normalized[key] = INDICATOR_ALIASES.get(val_str, val_str)

        # 5. 订单引用归一化
        elif key in ("order_reference",):
            normalized[key] = ORDER_REF_ALIASES.get(val_str, val_str)

        # 6. 数量归一化
        elif key in ("quantity",):
            normalized[key] = QUANTITY_ALIASES.get(val_str, val)

        # 7. 布尔值归一化
        elif key in ("implied_holding", "alert", "test_mode", "comparison"):
            if isinstance(val, bool):
                normalized[key] = val
            elif val_str.lower() in ("true", "1", "yes", "是"):
                normalized[key] = True
            elif val_str.lower() in ("false", "0", "no", "否", "none"):
                normalized[key] = False
            else:
                normalized[key] = val

        # 8. condition_type 归一化
        elif key in ("condition_type",):
            ct_map = {
                "止损": "stop_loss",
                "止盈": "take_profit",
                "stop_loss": "stop_loss",
                "take_profit": "take_profit",
            }
            normalized[key] = ct_map.get(val_str, val_str)

        # 9. direction 归一化
        elif key in ("direction",):
            dir_map = {
                "涨到": "up",
                "跌到": "down",
                "跌破": "down",
                "突破": "up",
                "up": "up",
                "down": "down",
                "向上": "up",
                "向下": "down",
            }
            normalized[key] = dir_map.get(val_str, val_str)

        # 10. quantity_unit 归一化
        elif key in ("quantity_unit",):
            qu_map = {
                "股": "share",
                "手": "lot",
                "share": "share",
                "lot": "lot",
                "个": "unit",
                "张": "contract",
            }
            normalized[key] = qu_map.get(val_str, val_str)

        else:
            normalized[key] = val

    result["slots"] = normalized

    # 归一化 multi_intent 中的槽位
    if result.get("multi_intent") and result.get("intents"):
        for intent in result["intents"]:
            if intent.get("slots"):
                temp_result = {"slots": intent["slots"]}
                temp_result = normalize_slots(temp_result)
                intent["slots"] = temp_result["slots"]

    return result


# ── 意图识别核心 ──────────────────────────────────────────────────────────

def classify_intent(user_input: str, context: Optional[Dict] = None) -> Dict[str, Any]:
    """
    识别用户输入的意图

    Args:
        user_input: 用户自然语言输入
        context: 上下文信息（历史对话、持仓等）

    Returns:
        结构化的意图识别结果
    """
    system_prompt = load_system_prompt()

    # 添加上下文信息（如果有）
    user_message = user_input
    if context:
        context_str = json.dumps(context, ensure_ascii=False, indent=2)
        user_message = f"上下文信息:\n{context_str}\n\n用户输入: {user_input}"

    if HAS_QWEN:
        result = _classify_with_qwen(system_prompt, user_message)
        return normalize_slots(result)
    else:
        return _classify_mock(user_input)


def _classify_with_qwen(system_prompt: str, user_message: str) -> Dict[str, Any]:
    """使用 Qwen 模型进行意图识别"""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message}
    ]

    try:
        response = chat_completion(
            messages=messages,
            temperature=0.1,  # 低温度，保证输出稳定
            max_tokens=1024,
            timeout=60,  # 增加超时到 60s，避免复杂意图超时
            retries=3,     # 增加重试次数
        )

        if not response.success:
            return {
                "intent_primary": "unknown",
                "intent_secondary": "unknown",
                "risk_level": "low",
                "slots": {},
                "confidence": 0.0,
                "error": response.error,
            }

        content = response.content

        # 尝试解析 JSON
        result = _parse_json_response(content)
        return result

    except Exception as e:
        return {
            "intent_primary": "dialog",
            "intent_secondary": "chitchat",
            "risk_level": "low",
            "slots": {},
            "confidence": 0.0,
            "error": str(e),
        }


def _parse_json_response(content: str) -> Dict[str, Any]:
    """从模型响应中解析 JSON"""
    # 清理可能的 markdown 标记
    content = content.strip()

    # 尝试直接解析
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # 尝试提取 ```json ... ``` 块
    if "```json" in content:
        start = content.index("```json") + 7
        end = content.index("```", start)
        json_str = content[start:end].strip()
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass

    # 尝试提取第一个 { 到最后一个 }
    if "{" in content and "}" in content:
        start = content.index("{")
        end = content.rindex("}") + 1
        json_str = content[start:end]
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass

    # 都失败了，返回原始内容
    return {
        "intent_primary": "unknown",
        "intent_secondary": "unknown",
        "risk_level": "low",
        "slots": {},
        "confidence": 0.0,
        "parse_error": True,
        "raw_content": content
    }


def _classify_mock(user_input: str) -> Dict[str, Any]:
    """Mock 模式（没有 API key 时使用）"""
    return {
        "intent_primary": "query",
        "intent_secondary": "market_query",
        "risk_level": "low",
        "slots": {
            "stock": "mock_stock"
        },
        "confidence": 0.5,
        "multi_intent": False,
        "intents": [],
        "clarify_needed": False,
        "clarify_question": None,
        "mock": True
    }


# ── 评估逻辑 ──────────────────────────────────────────────────────────────

def evaluate(test_cases_path: Optional[str] = None, limit: Optional[int] = None) -> Dict[str, Any]:
    """运行测试用例集并评估准确率"""

    if test_cases_path is None:
        test_cases_path = SPEC_DIR / "test-cases.json"

    with open(test_cases_path, "r", encoding="utf-8") as f:
        raw = f.read()

    # 支持 // 注释的 JSON（非正式 JSON，但方便人类阅读）
    clean_lines = []
    for line in raw.split("\n"):
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        clean_lines.append(line)
    clean_content = "\n".join(clean_lines)
    data = json.loads(clean_content)

    test_cases = data["test_cases"]
    if limit:
        test_cases = test_cases[:limit]
    total = len(test_cases)

    results = []
    primary_correct = 0
    secondary_correct = 0
    slot_correct = 0
    slot_total = 0

    print(f"🧪 运行意图识别评估 - 共 {total} 条测试用例")
    print("=" * 60)

    for i, tc in enumerate(test_cases, 1):
        print(f"\n[{i}/{total}] {tc['id']}: {tc['input'][:40]}...")

        try:
            result = classify_intent(tc["input"])
        except Exception as e:
            print(f"  ❌ 错误: {e}")
            result = {"error": str(e)}

        expected = tc["expected"]

        # 评估一级意图
        primary_match = result.get("intent_primary") == expected.get("intent_primary")
        if primary_match:
            primary_correct += 1
            print(f"  一级意图: ✅ {result.get('intent_primary')}")
        else:
            print(f"  一级意图: ❌ 期望={expected.get('intent_primary')}, 实际={result.get('intent_primary')}")

        # 评估二级意图
        secondary_match = result.get("intent_secondary") == expected.get("intent_secondary")
        if secondary_match:
            secondary_correct += 1
            print(f"  二级意图: ✅ {result.get('intent_secondary')}")
        else:
            print(f"  二级意图: ❌ 期望={expected.get('intent_secondary')}, 实际={result.get('intent_secondary')}")

        # 评估槽位
        expected_slots = expected.get("slots", {})
        result_slots = result.get("slots", {})
        for slot_name, expected_val in expected_slots.items():
            slot_total += 1
            actual_val = result_slots.get(slot_name)
            if str(actual_val) == str(expected_val):
                slot_correct += 1
                print(f"  槽位[{slot_name}]: ✅ {actual_val}")
            else:
                print(f"  槽位[{slot_name}]: ❌ 期望={expected_val}, 实际={actual_val}")

        print(f"  置信度: {result.get('confidence', 'N/A')}")

        results.append({
            "id": tc["id"],
            "input": tc["input"],
            "expected": expected,
            "actual": result,
            "primary_correct": primary_match,
            "secondary_correct": secondary_match,
            "difficulty": tc.get("difficulty"),
            "category": tc.get("category"),
        })

        sys.stdout.flush()

    # 汇总统计
    primary_accuracy = primary_correct / total * 100 if total > 0 else 0
    secondary_accuracy = secondary_correct / total * 100 if total > 0 else 0
    slot_accuracy = slot_correct / slot_total * 100 if slot_total > 0 else 0

    summary = {
        "total": total,
        "primary_accuracy": primary_accuracy,
        "secondary_accuracy": secondary_accuracy,
        "slot_accuracy": slot_accuracy,
        "primary_correct": primary_correct,
        "secondary_correct": secondary_correct,
        "slot_correct": slot_correct,
        "slot_total": slot_total,
        "results": results,
    }

    # 按难度统计
    by_difficulty = {}
    for r in results:
        diff = r["difficulty"]
        if diff not in by_difficulty:
            by_difficulty[diff] = {"total": 0, "primary_correct": 0, "secondary_correct": 0}
        by_difficulty[diff]["total"] += 1
        if r["primary_correct"]:
            by_difficulty[diff]["primary_correct"] += 1
        if r["secondary_correct"]:
            by_difficulty[diff]["secondary_correct"] += 1

    summary["by_difficulty"] = by_difficulty

    # 按类别统计
    by_category = {}
    for r in results:
        cat = r["category"]
        if cat not in by_category:
            by_category[cat] = {"total": 0, "primary_correct": 0, "secondary_correct": 0}
        by_category[cat]["total"] += 1
        if r["primary_correct"]:
            by_category[cat]["primary_correct"] += 1
        if r["secondary_correct"]:
            by_category[cat]["secondary_correct"] += 1

    summary["by_category"] = by_category

    return summary


def print_summary(summary: Dict[str, Any]):
    """打印评估结果汇总"""
    print("\n" + "=" * 60)
    print("📊 评估结果汇总")
    print("=" * 60)
    print(f"  总用例数:       {summary['total']}")
    print(f"  一级意图准确率: {summary['primary_accuracy']:.1f}% ({summary['primary_correct']}/{summary['total']})")
    print(f"  二级意图准确率: {summary['secondary_accuracy']:.1f}% ({summary['secondary_correct']}/{summary['total']})")
    print(f"  槽位准确率:     {summary['slot_accuracy']:.1f}% ({summary['slot_correct']}/{summary['slot_total']})")

    print("\n按难度分布:")
    for diff, stats in summary.get("by_difficulty", {}).items():
        p = stats["primary_correct"] / stats["total"] * 100 if stats["total"] > 0 else 0
        print(f"  {diff}: {stats['total']}条, 一级准确率={p:.1f}%")

    print("\n按类别分布:")
    for cat, stats in summary.get("by_category", {}).items():
        p = stats["primary_correct"] / stats["total"] * 100 if stats["total"] > 0 else 0
        print(f"  {cat}: {stats['total']}条, 一级准确率={p:.1f}%")

    # 错误用例列表
    error_cases = [r for r in summary["results"] if not r["primary_correct"]]
    if error_cases:
        print(f"\n❌ 错误用例 ({len(error_cases)}条):")
        for r in error_cases:
            print(f"  {r['id']}: {r['input'][:50]}...")
            print(f"    期望: {r['expected']['intent_primary']}/{r['expected']['intent_secondary']}")
            print(f"    实际: {r['actual'].get('intent_primary', '?')}/{r['actual'].get('intent_secondary', '?')}")


# ── 主函数 ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="交易系统意图识别器")
    parser.add_argument("input", nargs="?", help="用户输入文本")
    parser.add_argument("--evaluate", action="store_true", help="运行评估")
    parser.add_argument("--test-cases", help="测试用例文件路径")
    parser.add_argument("--output", help="评估结果输出文件 (JSON)")
    parser.add_argument("--limit", type=int, help="限制评估用例数量")

    args = parser.parse_args()

    if args.evaluate:
        summary = evaluate(args.test_cases, limit=args.limit)
        print_summary(summary)

        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                # 移除详细结果以减小文件体积？保留吧
                json.dump(summary, f, ensure_ascii=False, indent=2)
            print(f"\n💾 结果已保存到: {args.output}")

    elif args.input:
        result = classify_intent(args.input)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
