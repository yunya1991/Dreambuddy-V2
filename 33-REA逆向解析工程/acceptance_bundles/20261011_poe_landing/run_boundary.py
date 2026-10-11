"""边界验证 — FAIL-OPEN + 3 个负面场景。"""
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from core.ai_audit import audit_ai_output
from core.architecture_pattern_detector import detect_architecture_patterns
from core.design_decision_recovery import recover_decisions
from core.evolution_narrative import generate_narrative
from dsh_nodes import S33_rea_audit, S33_rea_narrative, S33_rea_recover_decisions

print("=" * 70)
print("PoE 边界验证（dream-acceptance-verify 步骤6）")
print("=" * 70)

# ========== 边界 1: 不存在路径 ==========

print("\n[边界1] 不存在路径 → 所有模块 FAIL-OPEN 不抛异常")
result1 = audit_ai_output("/nonexistent/path/xyz")
result2 = detect_architecture_patterns("/nonexistent/path/xyz")
result3 = recover_decisions("/nonexistent/path/xyz")
result4 = generate_narrative("/nonexistent/path/xyz")
all_unknown = (
    any(e.level.value == "unknown" for e in result1.get("evidence", []))
    and any(e.level.value == "unknown" for e in result2.get("evidence", []))
    and any(e.level.value == "unknown" for e in result3.get("evidence", []))
    and any(e.level.value == "unknown" for e in result4.get("evidence", []))
)
print(f"observed=boundary-1 nonexistent_path all_failopen_no_throw={all_unknown}")

# ========== 边界 2: 空目录 ==========

print("\n[边界2] 空目录 → 无崩溃，返回 unknown Evidence")
with tempfile.TemporaryDirectory() as d:
    r1 = audit_ai_output(d)
    r2 = detect_architecture_patterns(d)
    r3 = recover_decisions(d)
    no_crash = all(isinstance(r, dict) for r in [r1, r2, r3])
    print(f"observed=boundary-2 empty_dir no_crash={no_crash} audit_gate={r1.get('gate_decision')}")

# ========== 边界 3: 非 Python 文件/目录 ==========

print("\n[边界3] 非 Python 路径 → FAIL-OPEN")
with tempfile.TemporaryDirectory() as d:
    Path(d, "readme.txt").write_text("not python")
    r = audit_ai_output(d)
    print(f"observed=boundary-3 non_python poe_score={r['poe_score']} gate={r['gate_decision']} has_unknown_evidence={any(e.level.value == 'unknown' for e in r.get('evidence', []))}")

# ========== 边界 4: DSH 节点缺 target 参数 ==========

print("\n[边界4] DSH 节点缺 target → ok=False 不抛异常")
r = S33_rea_audit({})
print(f"observed=boundary-4 missing_target ok={r.get('ok')} error={r.get('error')}")

# ========== 边界 5: 大量魔法数字 + 深嵌套 ==========

print("\n[边界5] 极端代码 → 复杂度惩罚 + 债务清单")
extreme = "def f():\n    x = 1\n    for i in range(100):\n        if i:\n            if i:\n                if i:\n                    x += 999\n    return x * 3.14\n"
with tempfile.TemporaryDirectory() as d:
    Path(d, "extreme.py").write_text(extreme)
    r = audit_ai_output(d)
    print(f"observed=boundary-5 extreme_code complexity_penalty={r['complexity_penalty']:.3f} debts_count={len(r['cognitive_debt'])} gate={r['gate_decision']}")

print("\n" + "=" * 70)
print("边界验证完成 — 5 个场景")
print("=" * 70)
