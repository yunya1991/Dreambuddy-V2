#!/usr/bin/env python3
"""Jev Judge 多场景模拟验证脚本

通过 mock _call_jev_api，模拟 Jev API 返回，验证完整链路：
  - 工作验收（任务完成/未完成）
  - 步骤质量（合格/不合格）
  - 意图路由（分类）
  - 字段过滤（HC-5/HC-9 禁止字段剔除）
  - FAIL-OPEN 降级（开关关闭/缺 Key/校验失败/API 异常）

运行: python3 verify_jev_scenarios.py
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from unittest.mock import patch

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

import jev_judge


# ============================================================
# 模拟 Jev API 响应
# ============================================================

def mock_api(state, questions):
    """根据 questions 内容返回模拟的 Jev 响应"""
    answers = {}
    for name, q in questions.items():
        qtype = q.get("type")
        instr = q.get("instructions", "")

        if qtype == "noul":
            # 根据指令关键词模拟概率
            if "完成" in instr or "done" in instr.lower() or "complete" in instr.lower():
                # 工作验收场景
                if "未完成" in str(state) or "partial" in str(state).lower():
                    answers[name] = {"type": "noul", "noul": 0.30}
                else:
                    answers[name] = {"type": "noul", "noul": 0.95}
            elif "合格" in instr or "passed" in instr.lower():
                # 步骤质量场景
                if "error" in str(state).lower() or "失败" in str(state):
                    answers[name] = {"type": "noul", "noul": 0.25}
                else:
                    answers[name] = {"type": "noul", "noul": 0.88}
            else:
                answers[name] = {"type": "noul", "noul": 0.50}

        elif qtype == "choice":
            criteria = q.get("criteria", {})
            # 根据 state 内容模拟选择
            state_str = str(state).lower()
            if "交易" in str(state) or "trade" in state_str:
                choice = "trading_decision"
            elif "行情" in str(state) or "price" in state_str:
                choice = "market_query"
            elif "趋势" in str(state) or "trend" in state_str:
                choice = "trend_analysis"
            elif "风险" in str(state) or "risk" in state_str:
                choice = "risk_analysis"
            else:
                choice = list(criteria.keys())[0] if criteria else "other"
            # 构造概率分布
            probs = {k: 0.05 for k in criteria}
            probs[choice] = 0.85
            answers[name] = {
                "type": "choice",
                "choice": choice,
                "confidence": 0.82,
                "probabilities": probs,
            }

        elif qtype == "score":
            criteria = q.get("criteria", [])
            n = len(criteria)
            if "未完成" in str(state) or "partial" in str(state).lower():
                score = 0.5
                probs = {str(i): 0.1 for i in range(n)}
                probs["0"] = 0.7
            else:
                score = float(n - 1) - 0.2
                probs = {str(i): 0.05 for i in range(n)}
                probs[str(n - 1)] = 0.85
            legend = {str(i): c for i, c in enumerate(criteria)}
            answers[name] = {
                "type": "score",
                "score": score,
                "legend": legend,
                "probabilities": probs,
                "confidence": 0.78,
            }

    return {
        "model": "jev-1.13.0-mock",
        "answers": answers,
        "usage": {"input_tokens": 420, "output_tokens": 71},
    }


def mock_api_with_forbidden_fields(state, questions):
    """模拟 Jev 返回包含禁止字段的响应（测试 HC-5/HC-9 过滤）"""
    base = mock_api(state, questions)
    # 注入禁止字段
    for name in base["answers"]:
        base["answers"][name]["reward"] = 0.5
        base["answers"][name]["direction"] = "long"
        base["answers"][name]["action"] = "buy"
        base["answers"][name]["position"] = 1.0
        base["answers"][name]["size"] = 100
    return base


def mock_api_raises(state, questions):
    """模拟 API 异常"""
    raise ConnectionError("mock network failure")


# ============================================================
# 场景定义
# ============================================================

SCENARIOS = [
    # --- 工作验收 ---
    {
        "name": "工作验收-任务完成",
        "state": {"task": "实现用户登录功能", "current_output": "已完成登录页面+API+测试"},
        "questions": {
            "task_complete": {"type": "noul", "instructions": "这个任务是否已经完成？"},
            "quality_score": {"type": "score", "instructions": "完成质量如何？", "criteria": ["未完成", "部分完成", "基本完成", "高质量完成"]},
        },
        "assertions": [
            ("degraded", False),
            ("answers.task_complete.noul", 0.95),
            ("answers.quality_score.score", 2.8),
            ("model", "jev-1.13.0-mock"),
        ],
    },
    {
        "name": "工作验收-任务未完成",
        "state": {"task": "实现用户登录功能", "current_output": "partial: 只写了页面"},
        "questions": {
            "task_complete": {"type": "noul", "instructions": "这个任务是否已经完成？"},
            "quality_score": {"type": "score", "instructions": "完成质量如何？", "criteria": ["未完成", "部分完成", "基本完成", "高质量完成"]},
        },
        "assertions": [
            ("degraded", False),
            ("answers.task_complete.noul", 0.30),
            ("answers.quality_score.score", 0.5),
        ],
    },
    # --- 步骤质量 ---
    {
        "name": "步骤质量-合格",
        "state": {"step": 3, "step_output": "函数正确返回预期结果"},
        "questions": {
            "step_passed": {"type": "noul", "instructions": "这个步骤的产出是否合格？"},
        },
        "assertions": [
            ("degraded", False),
            ("answers.step_passed.noul", 0.88),
        ],
    },
    {
        "name": "步骤质量-不合格",
        "state": {"step": 3, "step_output": "error: 函数抛出异常"},
        "questions": {
            "step_passed": {"type": "noul", "instructions": "这个步骤的产出是否合格？"},
        },
        "assertions": [
            ("degraded", False),
            ("answers.step_passed.noul", 0.25),
        ],
    },
    # --- 意图路由 ---
    {
        "name": "意图路由-交易决策",
        "state": {"user_input": "我想做交易，开仓做多比特币"},
        "questions": {
            "intent": {"type": "choice", "instructions": "用户意图？", "criteria": {"market_query": "行情", "trend_analysis": "趋势", "trading_decision": "交易", "risk_analysis": "风险", "other": "其他"}},
        },
        "assertions": [
            ("degraded", False),
            ("answers.intent.choice", "trading_decision"),
            ("answers.intent.confidence", 0.82),
        ],
    },
    {
        "name": "意图路由-行情查询",
        "state": {"user_input": "比特币现在价格多少"},
        "questions": {
            "intent": {"type": "choice", "instructions": "用户意图？", "criteria": {"market_query": "行情", "trend_analysis": "趋势", "trading_decision": "交易", "risk_analysis": "风险", "other": "其他"}},
        },
        "assertions": [
            ("degraded", False),
            ("answers.intent.choice", "market_query"),
        ],
    },
    {
        "name": "意图路由-风险分析",
        "state": {"user_input": "当前仓位风险如何"},
        "questions": {
            "intent": {"type": "choice", "instructions": "用户意图？", "criteria": {"market_query": "行情", "trend_analysis": "趋势", "trading_decision": "交易", "risk_analysis": "风险", "other": "其他"}},
        },
        "assertions": [
            ("degraded", False),
            ("answers.intent.choice", "risk_analysis"),
        ],
    },
    # --- 字段过滤 (HC-5/HC-9) ---
    {
        "name": "字段过滤-禁止字段被剔除",
        "state": {"task": "test"},
        "questions": {
            "q": {"type": "noul", "instructions": "是否完成？"},
        },
        "mock_fn": mock_api_with_forbidden_fields,
        "assertions": [
            ("degraded", False),
            ("answers.q.noul", 0.95),
        ],
        "forbidden_check": ["reward", "direction", "action", "position", "size", "position_delta", "target_weight", "notional"],
    },
    # --- FAIL-OPEN 降级 ---
    {
        "name": "FAIL-OPEN-API异常",
        "state": {"task": "test"},
        "questions": {"q": {"type": "noul", "instructions": "x"}},
        "mock_fn": mock_api_raises,
        "assertions": [
            ("degraded", True),
            ("answers", {}),
        ],
    },
    {
        "name": "FAIL-OPEN-开关关闭",
        "env": {"ENABLE_JEV_JUDGE": "0"},
        "state": {"task": "test"},
        "questions": {"q": {"type": "noul", "instructions": "x"}},
        "assertions": [
            ("degraded", True),
            ("reason", "jev_judge_disabled"),
        ],
    },
    {
        "name": "FAIL-OPEN-缺少APIKey",
        "env": {"ENABLE_JEV_JUDGE": "1", "TYPESAFE_API_KEY": ""},
        "state": {"task": "test"},
        "questions": {"q": {"type": "noul", "instructions": "x"}},
        "assertions": [
            ("degraded", True),
            ("reason", "missing TYPESAFE_API_KEY"),
        ],
    },
    {
        "name": "FAIL-OPEN-无效question类型",
        "env": {"ENABLE_JEV_JUDGE": "1", "TYPESAFE_API_KEY": "fake"},
        "state": {"task": "test"},
        "questions": {"q": {"type": "bogus", "instructions": "x"}},
        "assertions": [
            ("degraded", True),
        ],
        "reason_contains": "invalid type",
    },
    {
        "name": "FAIL-OPEN-choice缺criteria",
        "env": {"ENABLE_JEV_JUDGE": "1", "TYPESAFE_API_KEY": "fake"},
        "state": {"task": "test"},
        "questions": {"q": {"type": "choice", "instructions": "x"}},
        "assertions": [
            ("degraded", True),
        ],
        "reason_contains": "criteria",
    },
    {
        "name": "FAIL-OPEN-score缺criteria",
        "env": {"ENABLE_JEV_JUDGE": "1", "TYPESAFE_API_KEY": "fake"},
        "state": {"task": "test"},
        "questions": {"q": {"type": "score", "instructions": "x"}},
        "assertions": [
            ("degraded", True),
        ],
        "reason_contains": "criteria",
    },
    {
        "name": "FAIL-OPEN-空questions",
        "env": {"ENABLE_JEV_JUDGE": "1", "TYPESAFE_API_KEY": "fake"},
        "state": {"task": "test"},
        "questions": {},
        "assertions": [
            ("degraded", True),
        ],
        "reason_contains": "invalid_questions",
    },
]


# ============================================================
# 验证引擎
# ============================================================

def get_nested(obj, path):
    """按点路径获取嵌套值"""
    keys = path.split(".")
    cur = obj
    for k in keys:
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return None
    return cur


def run_scenario(scenario):
    """运行单个场景，返回 (passed, details)"""
    name = scenario["name"]
    env_overrides = scenario.get("env", {})
    mock_fn = scenario.get("mock_fn", mock_api)

    # 设置环境覆盖
    patches = []
    for k, v in env_overrides.items():
        patches.append(patch.dict(os.environ, {k: v}))

    # 重新加载模块级常量（因为 judge() 直接读模块变量）
    patches.append(patch.object(jev_judge, "ENABLE_JEV_JUDGE", env_overrides.get("ENABLE_JEV_JUDGE", "1") == "1"))
    patches.append(patch.object(jev_judge, "TYPESAFE_API_KEY", env_overrides.get("TYPESAFE_API_KEY", "fake-key")))

    # 总是 mock API 调用（用场景指定的 mock_fn 或默认 mock_api）
    patches.append(patch.object(jev_judge, "_call_jev_api", mock_fn))

    for p in patches:
        p.start()

    try:
        result = jev_judge.judge(scenario["state"], scenario["questions"])
    except Exception as e:
        for p in patches:
            p.stop()
        return False, f"EXCEPTION: {type(e).__name__}: {e}\n{traceback.format_exc()}"

    for p in patches:
        p.stop()

    # 验证断言
    failures = []
    for path, expected in scenario.get("assertions", []):
        actual = get_nested(result, path)
        if actual != expected:
            failures.append(f"  ✗ {path}: expected {expected!r}, got {actual!r}")

    # 验证 reason 包含
    if "reason_contains" in scenario:
        reason = result.get("reason", "")
        if scenario["reason_contains"] not in reason:
            failures.append(f"  ✗ reason should contain '{scenario['reason_contains']}', got '{reason}'")

    # 验证禁止字段被剔除
    forbidden = scenario.get("forbidden_check", [])
    for field in forbidden:
        for ans_name, ans in result.get("answers", {}).items():
            if isinstance(ans, dict) and field in ans:
                failures.append(f"  ✗ HC-9/HC-5 违规: answers.{ans_name} 包含禁止字段 '{field}'")

    if failures:
        return False, "\n".join(failures)
    return True, f"OK (degraded={result.get('degraded')})"


def main():
    print("=" * 70)
    print("Jev Judge 多场景模拟验证")
    print("=" * 70)

    passed = 0
    failed = 0
    failed_scenarios = []

    for i, scenario in enumerate(SCENARIOS, 1):
        name = scenario["name"]
        ok, details = run_scenario(scenario)
        status = "PASS" if ok else "FAIL"
        print(f"\n[{i:2d}/{len(SCENARIOS)}] {status} - {name}")
        if not ok:
            print(details)
            failed += 1
            failed_scenarios.append(name)
        else:
            print(f"     {details}")
            passed += 1

    print("\n" + "=" * 70)
    print(f"结果: {passed} passed, {failed} failed, 共 {len(SCENARIOS)} 场景")
    print("=" * 70)

    if failed_scenarios:
        print(f"\n失败场景: {', '.join(failed_scenarios)}")
        return 1
    print("\n所有场景验证通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
