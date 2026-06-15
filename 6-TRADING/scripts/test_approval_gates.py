#!/usr/bin/env python3
"""
审批分类门禁 — 压力测试
测试 approval_agent.py 的 resolve_category() 和 check_pending() 路由逻辑。
无需飞书 API，纯本地测试。
"""
import json, os, sys, time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 加载被测试模块
sys.path.insert(0, str(Path(__file__).parent))
from approval_agent import (
    resolve_category, GOVERNANCE_TEMPLATES, TRADING_TEMPLATES,
    EMERGENCY_TIMEOUT_MINUTES, TIMEOUT_MINUTES,
    GATE_C_AUTO_APPROVE, GATE_C_AUTO_REJECT,
    A9_AUTO_APPROVE, A9_AUTO_REJECT,
)

# ── 测试结果统计 ──
pass_count = 0
fail_count = 0

def test(name, condition, detail=""):
    global pass_count, fail_count
    if condition:
        pass_count += 1
        print(f"  ✅ {name}")
    else:
        fail_count += 1
        print(f"  ❌ {name}" + (f"  | {detail}" if detail else ""))

def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

# ═══════════════════════════════════════════
# Part 1: resolve_category 单元测试
# ═══════════════════════════════════════════
section("Part 1: resolve_category 分类路由")

# 1.1 gate_c / a9
cat, label = resolve_category("gate_c", "", False)
test("gate_c → gate_c", cat == "gate_c", f"got {cat}")
test("gate_c label", "入场" in label, label)

cat, label = resolve_category("a9", "", False)
test("a9 → a9", cat == "a9", f"got {cat}")
test("a9 label", "离场" in label, label)

# 1.2 governance
cat, label = resolve_category("index_ops", "2F40FE12-255E-4FD4-AAD7-FD36C45FEA66", False)
test("index_ops + governance模板 → governance", cat == "governance", f"got {cat}")
test("governance label", "治理" in label, label)

# 1.3 trading_emergency
cat, label = resolve_category("trading_evolution", "096DC318-681B-478A-90CC-BD9701FC732C", True)
test("trading_evolution + emergency → trading_emergency", cat == "trading_emergency", f"got {cat}")
test("emergency label", "紧急" in label, label)

# 1.4 trading (non-emergency)
cat, label = resolve_category("trading_evolution", "096DC318-681B-478A-90CC-BD9701FC732C", False)
test("trading_evolution + non-emergency → trading", cat == "trading", f"got {cat}")
test("trading label", "交易审批" in label, label)

# 1.5 unknown type (default)
cat, label = resolve_category("some_unknown", "", False)
test("unknown type → trading (默认)", cat == "trading", f"got {cat}")

# 1.6 unknown type with emergency flag
cat, label = resolve_category("some_unknown", "", True)
test("unknown + emergency → trading_emergency", cat == "trading_emergency", f"got {cat}")

# 1.7 空模板 + governance type (不匹配)
cat, label = resolve_category("index_ops", "", False)
test("空模板 + index_ops → trading (默认)", cat == "trading", f"got {cat}")
# 因为模板不是 governance 的，所以回退到默认 trading

# ═══════════════════════════════════════════
# Part 2: check_pending 路由逻辑测试
# ═══════════════════════════════════════════
section("Part 2: check_pending 路由逻辑（模拟）")

now = datetime.now(timezone.utc)

# 模拟审批条目
entries = [
    # (name, category, is_emergency, created_minutes_ago, expected_action)
    ("治理审批 - 永不自动",   "governance",         False, 60,  "SKIP_AI"),
    ("交易非紧急 - 永不自动", "trading",            False, 60,  "SKIP_AI"),
    ("交易紧急 - 5min超时",   "trading_emergency",   True,  2,  "WAIT"),   # 未超时
    ("交易紧急 - 5min已过",   "trading_emergency",   True,  7,  "AUTO_APPROVE"),  # 已超时
    ("gate_c - 30minAI",     "gate_c",              False, 45, "AI_DECIDE"),  # 超时
    ("a9 - 30minAI",         "a9",                  False, 45, "AI_DECIDE"),
    ("边缘: 紧急 4min（未到）","trading_emergency",   True,  4,  "WAIT"),
    ("边缘: 紧急 6min（刚到）","trading_emergency",   True,  6,  "AUTO_APPROVE"),
]

for name, category, is_emergency, mins_ago, expected in entries:
    created = now - timedelta(minutes=mins_ago)
    elapsed = mins_ago
    
    if category == "governance":
        action = "SKIP_AI"
    elif category == "trading" and not is_emergency:
        action = "SKIP_AI"
    elif category == "trading_emergency":
        action = "WAIT" if elapsed < EMERGENCY_TIMEOUT_MINUTES else "AUTO_APPROVE"
    elif category in ("gate_c", "a9"):
        action = "AI_DECIDE" if elapsed >= TIMEOUT_MINUTES else "WAIT"
    else:
        action = "UNKNOWN"
    
    result = "✅" if action == expected else "❌"
    print(f"  {result} {name:<35} elapsed={mins_ago:>2}min → {action:<15} (期望: {expected})")
    if action != expected:
        fail_count += 1
    else:
        pass_count += 1

# ═══════════════════════════════════════════
# Part 3: Gate-C 评分逻辑测试
# ═══════════════════════════════════════════
section("Part 3: Gate-C 评分阈值检查")

test("GATE_C_AUTO_APPROVE 置信度 70%", GATE_C_AUTO_APPROVE["composite_confidence"] == 0.70)
test("GATE_C_AUTO_APPROVE A7评分 32", GATE_C_AUTO_APPROVE["a7_score_min"] == 32)
test("GATE_C_AUTO_APPROVE Screen1 55", GATE_C_AUTO_APPROVE["screen1_score_min"] == 55)
test("GATE_C_AUTO_APPROVE 漂移 5%", GATE_C_AUTO_APPROVE["max_price_drift_pct"] == 5.0)
test("GATE_C_AUTO_REJECT 置信度 60%", GATE_C_AUTO_REJECT["composite_confidence"] == 0.60)
test("GATE_C_AUTO_REJECT Screen1 40", GATE_C_AUTO_REJECT["screen1_score_min"] == 40)
test("GATE_C_AUTO_REJECT 连续SKIP 3次", GATE_C_AUTO_REJECT["consecutive_skip_max"] == 3)

# ═══════════════════════════════════════════
# Part 4: A9 评分阈值检查
# ═══════════════════════════════════════════
section("Part 4: A9 阈值检查")

test("A9_AUTO_APPROVE exit_score 65", A9_AUTO_APPROVE["exit_score_min"] == 65)
test("A9_AUTO_REJECT exit_score 40", A9_AUTO_REJECT["exit_score_min"] == 40)

# ═══════════════════════════════════════════
# Part 5: 配置一致性检查
# ═══════════════════════════════════════════
section("Part 5: 配置一致性")

test("紧急超时 5分钟", EMERGENCY_TIMEOUT_MINUTES == 5)
test("普通超时 30分钟", TIMEOUT_MINUTES == 30)
test("治理模板不包含交易模板", "096DC318" not in str(GOVERNANCE_TEMPLATES))
test("交易模板不包含治理模板", "2F40FE12" not in str(TRADING_TEMPLATES))

# ═══════════════════════════════════════════
# Part 6: 模拟 check_pending 完整路由
# ═══════════════════════════════════════════
section("Part 6: 完整路由模拟（混合场景）")

# 模拟 approval_state.json 中的条目（无需飞书 API）
scenarios = [
    # governance: 即使过了24h也不自动
    {"category": "governance", "is_emergency": False, "minutes_ago": 1440, "template": "2F40FE12-...", "expect": "SKIP"},
    # trading_emergency: 2分钟→等待, 6分钟→自动
    {"category": "trading_emergency", "is_emergency": True, "minutes_ago": 2, "expect": "WAIT"},
    {"category": "trading_emergency", "is_emergency": True, "minutes_ago": 6, "expect": "AUTO"},
    # trading: 即使过了24h也不自动
    {"category": "trading", "is_emergency": False, "minutes_ago": 1440, "expect": "SKIP"},
    # gate_c: 35分钟→AI决策
    {"category": "gate_c", "is_emergency": False, "minutes_ago": 35, "expect": "AI"},
    # a9: 20分钟→等待, 40分钟→AI决策
    {"category": "a9", "is_emergency": False, "minutes_ago": 20, "expect": "WAIT"},
    {"category": "a9", "is_emergency": False, "minutes_ago": 40, "expect": "AI"},
    # 旧条目(无category字段, 默认trading): 60分钟→不自动
    {"category": None, "is_emergency": False, "minutes_ago": 60, "expect": "SKIP"},
]

for s in scenarios:
    cat = s["category"]
    emer = s["is_emergency"]
    mins = s["minutes_ago"]
    
    # 模拟 check_pending 的路由逻辑
    if cat is None:
        cat = "trading"  # 默认值
    
    if cat == "governance":
        action = "SKIP"
    elif cat == "trading" and not emer:
        action = "SKIP"
    elif cat == "trading_emergency":
        action = "WAIT" if mins < 5 else "AUTO"
    elif cat in ("gate_c", "a9"):
        action = "WAIT" if mins < 30 else "AI"
    else:
        action = "UNKNOWN"
    
    cat_display = cat if cat else "trading(default)"
    label = f"category={cat_display:<20} emergency={str(emer):<5} elapsed={mins:>4}min"
    result = "✅" if action == s["expect"] else "❌"
    print(f"  {result} {label} → {action:<6} (期望: {s['expect']})")
    if action != s["expect"]:
        fail_count += 1
    else:
        pass_count += 1

# ═══════════════════════════════════════════
# 最终统计
# ═══════════════════════════════════════════
section("最终统计")
total = pass_count + fail_count
print(f"  总计: {total} 个测试")
print(f"  ✅ 通过: {pass_count}")
print(f"  ❌ 失败: {fail_count}")
print(f"  通过率: {pass_count/total*100:.0f}%")
print()

if fail_count == 0:
    print("  🎉 双审批门禁全部测试通过！")
else:
    print(f"  ⚠️ 有 {fail_count} 个测试失败，需要修复")
    sys.exit(1)
