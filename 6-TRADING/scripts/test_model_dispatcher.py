#!/usr/bin/env python3
"""
model_dispatcher 压力测试
=========================
验证调度逻辑在各种注册表状态下的行为正确性。

场景:
  T01  当前状态：仅 deepseek-v4 可用 → 所有任务路由至 deepseek-v4
  T02  gate_check → __code__
  T03  接入强模型后 synthesis 任务自动升级
  T04  所有模型不可用 → 回退 base_fallback
  T05  prefer_highest 选 reasoning_depth 最高，同分取 cost_tier 最低
  T06  仅满足部分阈值的模型不被选中
  T07  update_model_availability 写回注册表
  T08  update_process_d_score 写回注册表
  T09  dispatch_screen1_plan 返回正确步骤数 + 依赖关系
  T10  format_dispatch_plan 不崩溃

运行: python test_model_dispatcher.py
"""

import json
import os
import sys
import io
import copy

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, r"C:\tmp")
from model_dispatcher import (
    dispatch,
    get_task_info,
    dispatch_screen1_plan,
    format_dispatch_plan,
    update_model_availability,
    update_process_d_score,
    TASK_THRESHOLDS,
)

PASS_COUNT = 0
FAIL_COUNT = 0


def _ok(name):
    global PASS_COUNT
    PASS_COUNT += 1
    print(f"  ✅ {name}")


def _fail(name, reason):
    global FAIL_COUNT
    FAIL_COUNT += 1
    print(f"  ❌ {name}: {reason}")


def assert_eq(name, got, expected):
    if got == expected:
        _ok(name)
    else:
        _fail(name, f"expected={expected!r}  got={got!r}")


def assert_true(name, cond, msg=""):
    if cond:
        _ok(name)
    else:
        _fail(name, msg or "False")


def scenario(name):
    print(f"\n{'─'*60}")
    print(f"  {name}")
    print(f"{'─'*60}")


# ── 构建 mock 注册表 ──────────────────────────────────────────────────────────

def _reg_only_deepseek():
    return {
        "registry_version": "test",
        "updated": "2026-06-02",
        "base_fallback": "deepseek-v4",
        "models": {
            "deepseek-v4": {
                "available": True, "cost_tier": 1,
                "scores": {"reasoning_depth": 3, "chinese_finance": 4,
                           "structured_output": 5, "instruction_follow": 4,
                           "context_window_k": 64},
            },
            "claude-opus-4": {
                "available": False, "cost_tier": 5,
                "scores": {"reasoning_depth": 5, "chinese_finance": 4,
                           "structured_output": 5, "instruction_follow": 5,
                           "context_window_k": 200},
            },
        },
    }


def _reg_with_strong():
    reg = _reg_only_deepseek()
    reg["models"]["claude-opus-4"]["available"] = True
    return reg


def _reg_all_unavailable():
    reg = _reg_only_deepseek()
    reg["models"]["deepseek-v4"]["available"] = False
    return reg


def _reg_weak_only():
    return {
        "registry_version": "test",
        "updated": "2026-06-02",
        "base_fallback": "deepseek-v4",
        "models": {
            "weak-model": {
                "available": True, "cost_tier": 1,
                "scores": {"reasoning_depth": 1, "chinese_finance": 1,
                           "structured_output": 3, "instruction_follow": 2,
                           "context_window_k": 8},
            },
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# T01: 仅 deepseek-v4 可用
# ─────────────────────────────────────────────────────────────────────────────
scenario("T01 — 仅 deepseek-v4 可用 → 所有非代码任务路由至 deepseek-v4")
reg = _reg_only_deepseek()
for tt in ["data_collection", "dim_annotation_cycle", "dim_annotation_macro",
           "dim_annotation_cross_market", "json_write"]:
    assert_eq(tt, dispatch(tt, reg), "deepseek-v4")

# synthesis 任务 prefer_highest=True，但唯一可用模型仍是 deepseek-v4
for tt in ["synthesis_a1", "synthesis_a2", "synthesis_a3", "synthesis_cross_asset"]:
    assert_eq(f"{tt} fallback to deepseek", dispatch(tt, reg), "deepseek-v4")


# ─────────────────────────────────────────────────────────────────────────────
# T02: gate_check → __code__
# ─────────────────────────────────────────────────────────────────────────────
scenario("T02 — gate_check → __code__（不调用任何模型）")
assert_eq("gate_check", dispatch("gate_check", reg), "__code__")


# ─────────────────────────────────────────────────────────────────────────────
# T03: 接入强模型后 synthesis 自动升级
# ─────────────────────────────────────────────────────────────────────────────
scenario("T03 — claude-opus-4 上线后 synthesis 自动选最强模型")
reg_strong = _reg_with_strong()
for tt in ["synthesis_a1", "synthesis_a2", "synthesis_a3"]:
    assert_eq(f"{tt} → opus", dispatch(tt, reg_strong), "claude-opus-4")

# 非合成任务仍选便宜模型
assert_eq("dim_annotation_macro 仍用 deepseek", dispatch("dim_annotation_macro", reg_strong), "deepseek-v4")


# ─────────────────────────────────────────────────────────────────────────────
# T04: 所有模型不可用 → base_fallback
# ─────────────────────────────────────────────────────────────────────────────
scenario("T04 — 所有模型不可用 → 回退 base_fallback")
reg_empty = _reg_all_unavailable()
for tt in ["dim_annotation_cycle", "synthesis_a3", "json_write"]:
    assert_eq(f"{tt} → fallback", dispatch(tt, reg_empty), "deepseek-v4")


# ─────────────────────────────────────────────────────────────────────────────
# T05: prefer_highest 在两个可用模型中选 reasoning_depth 更高的
# ─────────────────────────────────────────────────────────────────────────────
scenario("T05 — prefer_highest：选 reasoning_depth 最高，同分选 cost_tier 最低")
reg_two = _reg_with_strong()

# synthesis → opus (reasoning=5) 优于 deepseek (reasoning=3)
assert_eq("synthesis_a1 → opus", dispatch("synthesis_a1", reg_two), "claude-opus-4")

# 同 reasoning_depth 的情况：添加第三个模型验证 cost_tier tiebreak
reg_tie = copy.deepcopy(reg_two)
reg_tie["models"]["model-cheap"] = {
    "available": True, "cost_tier": 2,
    "scores": {"reasoning_depth": 5, "chinese_finance": 4,
               "structured_output": 5, "instruction_follow": 5},
}
# opus cost_tier=5, model-cheap cost_tier=2, 同 reasoning=5 → 选 model-cheap
result = dispatch("synthesis_a3", reg_tie)
assert_eq("tiebreak by cost_tier", result, "model-cheap")


# ─────────────────────────────────────────────────────────────────────────────
# T06: 仅满足部分阈值的弱模型不被选中
# ─────────────────────────────────────────────────────────────────────────────
scenario("T06 — 弱模型分数不达阈值 → 回退 base_fallback")
reg_weak = _reg_weak_only()
# synthesis 要求 reasoning_depth >= 5，weak-model=1，不满足
assert_eq("synthesis_a3 → fallback", dispatch("synthesis_a3", reg_weak), "deepseek-v4")
# data_collection 要求低，weak-model 能满足
assert_eq("data_collection → weak-model", dispatch("data_collection", reg_weak), "weak-model")


# ─────────────────────────────────────────────────────────────────────────────
# T07: update_model_availability 读写注册表
# ─────────────────────────────────────────────────────────────────────────────
scenario("T07 — update_model_availability 写回文件并生效")
import tempfile, shutil

orig = r"C:\tmp\model_registry.json"
with tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="w", encoding="utf-8") as tmp:
    shutil.copy(orig, tmp.name)
    backup = tmp.name

try:
    update_model_availability("claude-opus-4", True)
    with open(orig, "r", encoding="utf-8") as f:
        updated = json.load(f)
    assert_eq("claude-opus-4 available=True", updated["models"]["claude-opus-4"]["available"], True)

    update_model_availability("claude-opus-4", False)
    with open(orig, "r", encoding="utf-8") as f:
        updated2 = json.load(f)
    assert_eq("claude-opus-4 available=False", updated2["models"]["claude-opus-4"]["available"], False)
finally:
    shutil.copy(backup, orig)   # 还原
    os.unlink(backup)


# ─────────────────────────────────────────────────────────────────────────────
# T08: update_process_d_score 写回注册表
# ─────────────────────────────────────────────────────────────────────────────
scenario("T08 — update_process_d_score 写回并可读出")
with tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="w", encoding="utf-8") as tmp:
    shutil.copy(orig, tmp.name)
    backup = tmp.name

try:
    update_process_d_score("deepseek-v4", 0.72)
    with open(orig, "r", encoding="utf-8") as f:
        updated = json.load(f)
    assert_eq("accuracy written", updated["models"]["deepseek-v4"]["process_d_accuracy"], 0.72)
    assert_true("last_evaluated set", bool(updated["models"]["deepseek-v4"]["last_evaluated"]))

    # 非法值应抛异常
    try:
        update_process_d_score("deepseek-v4", 1.5)
        _fail("invalid accuracy", "应抛 ValueError")
    except ValueError:
        _ok("invalid accuracy raises ValueError")
finally:
    shutil.copy(backup, orig)
    os.unlink(backup)


# ─────────────────────────────────────────────────────────────────────────────
# T09: dispatch_screen1_plan 结构验证
# ─────────────────────────────────────────────────────────────────────────────
scenario("T09 — dispatch_screen1_plan 返回正确步骤 + 依赖关系")
plan = dispatch_screen1_plan(_reg_only_deepseek())

assert_eq("plan step count", len(plan), 10)
assert_eq("step 1 is gate_check", plan[0]["task_type"], "gate_check")
assert_eq("gate_check model __code__", plan[0]["model"], "__code__")

# cross_market 依赖 macro
cm = next(p for p in plan if p["task_type"] == "dim_annotation_cross_market")
assert_true("cross_market depends_on macro",
            "dim_annotation_macro" in cm["depends_on"])

# synthesis 步骤全有 skill
for p in plan:
    if p["task_type"].startswith("synthesis_"):
        assert_true(f"{p['task_type']} has skill", bool(p["skill"]))


# ─────────────────────────────────────────────────────────────────────────────
# T10: format_dispatch_plan 可渲染
# ─────────────────────────────────────────────────────────────────────────────
scenario("T10 — format_dispatch_plan 不崩溃，输出合理长度")
plan = dispatch_screen1_plan(_reg_only_deepseek())
try:
    text = format_dispatch_plan(plan)
    assert_true("output length > 200", len(text) > 200, f"len={len(text)}")
    _ok(f"format_dispatch_plan: {len(text)} chars")
except Exception as e:
    _fail("format_dispatch_plan", str(e))


# ── 汇总 ──────────────────────────────────────────────────────────────────────
print(f"\n{'═'*60}")
print(f"  调度器压力测试汇总")
print(f"{'═'*60}")
print(f"  通过: {PASS_COUNT}  失败: {FAIL_COUNT}  总计: {PASS_COUNT + FAIL_COUNT}")
print(f"{'═'*60}")

if FAIL_COUNT == 0:
    print("\n  ✅ 所有场景通过，模型调度器验证完成")
    sys.exit(0)
else:
    sys.exit(1)
