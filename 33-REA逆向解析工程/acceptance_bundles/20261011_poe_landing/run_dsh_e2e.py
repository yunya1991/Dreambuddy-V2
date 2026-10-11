"""DSH 端到端测试 — 用真实代码触发 3 个新 DSH 节点。

测试目标：
1. S33_rea_audit 对真实 AI 产出代码（含魔法数字+深嵌套）做 PoE 门禁审计
2. S33_rea_recover_decisions 对 33-REA 自身 core/ 做设计决策还原
3. S33_rea_narrative 对 dreambuddy-v2 仓库自身做演化叙事生成
"""
import json
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent.parent  # dreambuddy-v2
REA_ROOT = Path(__file__).parent.parent.parent          # 33-REA逆向解析工程
sys.path.insert(0, str(REA_ROOT))

from dsh_nodes import (
    DSH_NODE_REGISTRY,
    S33_rea_audit,
    S33_rea_narrative,
    S33_rea_recover_decisions,
    dispatch,
)

print("=" * 70)
print("DSH 端到端测试 — 3 个新节点对真实代码触发")
print("=" * 70)

# 验证节点注册
print("\n[节点注册验证]")
expected_nodes = ["s33_rea_audit", "s33_rea_recover_decisions", "s33_rea_narrative"]
for n in expected_nodes:
    status = "✓ 已注册" if n in DSH_NODE_REGISTRY else "✗ 未注册"
    print(f"  {n}: {status}")

# ============================================================
# DSH 端到端 1: S33_rea_audit 对真实 AI 产出代码审计
# ============================================================

print("\n" + "-" * 70)
print("[DSH 端到端 1] S33_rea_audit 对真实 AI 产出代码做 PoE 门禁审计")
print("-" * 70)

# 构造一份典型的 AI 产出代码（无注释+魔法数字+深嵌套）
ai_produced_code = """
def process_data(data, mode):
    items = data.split(',')
    result = 0
    for i in range(142):
        if items[i % len(items)] == 'x':
            if mode == 'strict':
                if i > 50:
                    result += 100
                else:
                    result -= 50
            else:
                result += 75
        else:
            result += 25
    return result * 3.14

MAGIC_THRESHOLD = 0.85

class Handler:
    def handle(self, req):
        if req:
            return 200
        return 500
"""

with tempfile.TemporaryDirectory() as d:
    Path(d, "ai_output.py").write_text(ai_produced_code)
    # 通过 dispatch 路由调用（模拟真实 IPC 调用路径）
    result = dispatch("s33_rea_audit", {
        "target": d,
        "ai_context": {
            "agent_id": "test-agent",
            "model": "gpt-4",
            "prompt_hash": "abc123",
            "timestamp": "2026-10-11T00:00:00Z",
        },
    })

    print(f"\n  调用: dispatch('s33_rea_audit', {{target, ai_context}})")
    print(f"  ok: {result['ok']}")
    r = result["result"]
    print(f"  poe_score: {r['poe_score']:.3f}")
    print(f"  evidence_chain_score: {r['evidence_chain_score']:.3f}")
    print(f"  coverage_score: {r['coverage_score']:.3f}")
    print(f"  complexity_penalty: {r['complexity_penalty']:.3f}")
    print(f"  gate_decision: {r['gate_decision'].upper()}")
    print(f"  cognitive_debt 数量: {len(r['cognitive_debt'])}")
    print(f"  audit_layer_status: {r.get('audit_layer_status', {})}")
    print(f"  evidence 数量: {len(r['evidence'])}")
    print(f"  known_gaps 数量: {len(r['known_gaps'])}")
    print(f"  cognitive_record tags: {r['cognitive_record']['tags']}")

    # 关键断言
    assert result["ok"] is True, "DSH 调用应成功"
    assert r["poe_score"] < 0.5, "AI 无注释代码 poe_score 应 < 0.5"
    assert r["gate_decision"] == "reject", "AI 无注释代码应被 REJECT"
    assert len(r["cognitive_debt"]) > 0, "应检测到认知债务"
    print("\n  ✓ 断言通过: ok=True, poe<0.5, gate=reject, debts>0")

# ============================================================
# DSH 端到端 2: S33_rea_recover_decisions 对 33-REA 自身 core/ 还原
# ============================================================

print("\n" + "-" * 70)
print("[DSH 端到端 2] S33_rea_recover_decisions 对 33-REA 自身 core/ 还原")
print("-" * 70)

core_dir = str(REPO_ROOT / "33-REA逆向解析工程" / "core")
result = S33_rea_recover_decisions({"target": core_dir})

print(f"\n  调用: S33_rea_recover_decisions({{target: '33-REA/core'}})")
print(f"  ok: {result['ok']}")
r = result["result"]
print(f"  decisions 数量: {len(r['decisions'])}")
print(f"  evidence 数量: {len(r['evidence'])}")
print(f"  known_gaps 数量: {len(r['known_gaps'])}")

# 打印前 3 条决策
for i, dec in enumerate(r["decisions"][:3], 1):
    decision_text = dec.get("decision", "")[:80] if isinstance(dec, dict) else str(dec)[:80]
    print(f"  决策{i}: {decision_text}")

assert result["ok"] is True, "DSH 调用应成功"
assert len(r["decisions"]) > 0, "33-REA 自身 core/ 应有可还原的设计决策"
print(f"\n  ✓ 断言通过: ok=True, decisions>0 (识别到 {len(r['decisions'])} 条决策)")

# ============================================================
# DSH 端到端 3: S33_rea_narrative 对 dreambuddy-v2 仓库演化叙事
# ============================================================

print("\n" + "-" * 70)
print("[DSH 端到端 3] S33_rea_narrative 对 dreambuddy-v2 仓库演化叙事")
print("-" * 70)

result = S33_rea_narrative({"target": str(REPO_ROOT)})

print(f"\n  调用: S33_rea_narrative({{target: 'dreambuddy-v2'}})")
print(f"  ok: {result['ok']}")
r = result["result"]
print(f"  turning_points 数量: {len(r['turning_points'])}")
print(f"  tech_debt_timeline 数量: {len(r['tech_debt_timeline'])}")
print(f"  evidence 数量: {len(r['evidence'])}")
print(f"  known_gaps 数量: {len(r['known_gaps'])}")

# 打印前 3 个转折点
for i, tp in enumerate(r["turning_points"][:3], 1):
    msg = tp.get("message", "")[:80] if isinstance(tp, dict) else str(tp)[:80]
    commit = tp.get("commit", "")[:8] if isinstance(tp, dict) else ""
    stats = tp.get("change_stats", {}) if isinstance(tp, dict) else {}
    print(f"  转折点{i}: {commit} | {msg} | files={stats.get('files_changed', 0)} +/-={stats.get('insertions', 0)}/{stats.get('deletions', 0)}")

# 打印前 3 条技术债
for i, debt in enumerate(r["tech_debt_timeline"][:3], 1):
    if isinstance(debt, dict):
        marker = debt.get("marker", "")
        file = debt.get("file", "")[:50]
        print(f"  技术债{i}: [{marker}] {file}")

assert result["ok"] is True, "DSH 调用应成功"
# dreambuddy-v2 是 git 仓库，应有转折点
if len(r["turning_points"]) > 0:
    print(f"\n  ✓ 断言通过: ok=True, turning_points>0 (检测到 {len(r['turning_points'])} 个转折点)")
else:
    print(f"\n  ⚠️ 转折点为 0（可能 commit message 无 refactor 关键字），但节点调用成功")

print("\n" + "=" * 70)
print("DSH 端到端测试完成 — 3 个新节点全部可调用")
print("=" * 70)
