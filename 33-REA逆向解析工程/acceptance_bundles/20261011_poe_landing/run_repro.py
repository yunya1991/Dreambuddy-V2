"""PoE 端到端症状复测 — 按 SPEC AC-1~AC-8 逐项运行。

每项输出 observed= 标记行（dream-acceptance-verify HC-5 要求）。
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from core.architecture_pattern_detector import detect_architecture_patterns
from core.ai_audit import audit_ai_output, compute_poe_score
from core.cognitive_integration import (
    prepare_audit_record_params,
    prepare_decision_record_params,
    prepare_methodology_record_params,
)
from core.design_decision_recovery import recover_decisions
from core.evolution_narrative import generate_narrative
from core.evidence import Evidence, EvidenceLevel
from core.methodology_abstraction import abstract_methodology
from dsh_nodes import S33_rea_audit, S33_rea_recover_decisions, S33_rea_narrative

print("=" * 70)
print("PoE SPEC 端到端症状复测")
print("=" * 70)

# ========== AC-1: 设计决策还原 ==========

print("\n[AC-1] 设计决策还原 → ADR 风格记录")
with tempfile.TemporaryDirectory() as d:
    os.makedirs(f"{d}/models"); os.makedirs(f"{d}/views"); os.makedirs(f"{d}/controllers")
    Path(f"{d}/models/__init__.py").write_text("")
    Path(f"{d}/views/__init__.py").write_text("")
    Path(f"{d}/controllers/__init__.py").write_text("")
    Path(f"{d}/models/user.py").write_text("class User:\n    def __init__(self, name):\n        self.name = name\n")
    Path(f"{d}/views/v.py").write_text("class V:\n    def render(self, u):\n        return u.name\n")
    Path(f"{d}/controllers/c.py").write_text("from m.models.user import User\nclass C:\n    pass\n")
    result = recover_decisions(d)
    decisions = result.get("decisions", [])
    print(f"observed=AC-1 decisions_count={len(decisions)} has_decision={'decision' in decisions[0] if decisions else False} has_context={'context' in decisions[0] if decisions else False} has_evidence={'evidence' in decisions[0] if decisions else False}")

# ========== AC-2: 架构模式识别带证据 ==========

print("\n[AC-2] 架构模式识别 → provenance + level")
with tempfile.TemporaryDirectory() as d:
    os.makedirs(f"{d}/services"); os.makedirs(f"{d}/repositories")
    Path(f"{d}/services/__init__.py").write_text("")
    Path(f"{d}/repositories/__init__.py").write_text("")
    Path(f"{d}/services/svc.py").write_text("class Svc:\n    pass\n")
    result = detect_architecture_patterns(d)
    patterns = result.get("patterns", [])
    if patterns:
        ev = patterns[0].get("evidence")
        provenance_nonempty = bool(ev and ev.provenance)
        level_value = ev.level.value if ev else None
        print(f"observed=AC-2 patterns_count={len(patterns)} provenance_nonempty={provenance_nonempty} level={level_value}")
    else:
        print(f"observed=AC-2 FAIL patterns_count=0")

# ========== AC-3: 演化叙事检测转折点 ==========

print("\n[AC-3] 演化叙事 → 转折点 + commit hash")
with tempfile.TemporaryDirectory() as d:
    subprocess.run(["git", "init"], cwd=d, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=d, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=d, capture_output=True)
    Path(f"{d}/app.py").write_text("def main():\n    pass\n")
    subprocess.run(["git", "add", "-A"], cwd=d, capture_output=True)
    subprocess.run(["git", "commit", "-m", "feat: init"], cwd=d, capture_output=True)
    # 重构
    os.makedirs(f"{d}/models")
    Path(f"{d}/app.py").unlink()
    Path(f"{d}/models/user.py").write_text("class User:\n    pass\n")
    subprocess.run(["git", "add", "-A"], cwd=d, capture_output=True)
    subprocess.run(["git", "commit", "-m", "refactor: split into models"], cwd=d, capture_output=True)

    result = generate_narrative(d)
    tps = result.get("turning_points", [])
    if tps:
        tp = tps[0]
        change_stats = tp.get("change_stats", {})
        print(f"observed=AC-3 turning_points_count={len(tps)} commit_hash_exists={bool(tp.get('commit'))} files_changed={change_stats.get('files_changed', 0)}")
    else:
        print(f"observed=AC-3 FAIL turning_points_count=0")

# ========== AC-4: 方法论抽象跨项目聚类 ==========

print("\n[AC-4] 方法论抽象 → 跨项目聚类")
investigations = []
for proj in ["proj-a", "proj-b", "proj-c"]:
    investigations.append({
        "target": f"/mock/{proj}",
        "patterns": [{
            "pattern": "MVC",
            "matched_dirs": ["models", "views", "controllers"],
            "evidence": Evidence(
                result="MVC detected",
                level=EvidenceLevel.DERIVATION,
                provenance={"target": f"/mock/{proj}"},
                confidence=0.85,
                known_gaps=[],
            ),
        }],
        "decisions": [],
    })
result = abstract_methodology(investigations)
methodologies = result.get("methodologies", [])
if methodologies:
    m = methodologies[0]
    ev = m.get("evidence")
    src_projects = ev.provenance.get("source_projects", []) if ev else []
    print(f"observed=AC-4 methodologies_count={len(methodologies)} problem_pattern_has_MVC={'MVC' in m.get('problem_pattern', '')} source_projects_count={len(src_projects)}")
else:
    print(f"observed=AC-4 FAIL methodologies_count=0")

# ========== AC-5: AI 审计输出证据链完整度得分 ==========

print("\n[AC-5] AI 审计 → evidence_chain_score + poe_score")
with tempfile.TemporaryDirectory() as d:
    Path(f"{d}/ai_code.py").write_text("def complex():\n    x = 142\n    return x * 3.14\n")
    result = audit_ai_output(d)
    print(f"observed=AC-5 evidence_chain_score={result['evidence_chain_score']:.3f} poe_score={result['poe_score']:.3f} gate={result['gate_decision']} debts_count={len(result['cognitive_debt'])}")

# ========== AC-6: Evidence-First 全量扫描 ==========

print("\n[AC-6] Evidence-First 硬约束 → 全模块扫描无裸结论")
with tempfile.TemporaryDirectory() as d:
    Path(f"{d}/sample.py").write_text("def fn():\n    return 42\n")
    # 对每个新增模块的输出做全量扫描
    bare_count = 0
    total_ev = 0
    for name, r in [
        ("pattern", detect_architecture_patterns(d)),
        ("decision", recover_decisions(d)),
        ("narrative", generate_narrative(d)),
        ("audit", audit_ai_output(d)),
    ]:
        for e in r.get("evidence", []):
            total_ev += 1
            if not e.provenance:
                bare_count += 1
    print(f"observed=AC-6 total_evidence={total_ev} bare_conclusions={bare_count} verdict={'PASS' if bare_count == 0 else 'FAIL'}")

# ========== AC-7: DSH 新节点可调用 ==========

print("\n[AC-7] DSH 新节点 → S33_rea_audit IPC 调用")
with tempfile.TemporaryDirectory() as d:
    Path(f"{d}/ai.py").write_text("def f():\n    return 142\n")
    result = S33_rea_audit({"target": d})
    r = result.get("result", {})
    print(f"observed=AC-7 ok={result.get('ok')} has_target={'target' in r} has_evidence={'evidence' in r} has_known_gaps={'known_gaps' in r} gate={r.get('gate_decision')}")

# ========== AC-8: 审计结果写入认知记忆 ==========

print("\n[AC-8] 审计结果 → record 参数")
with tempfile.TemporaryDirectory() as d:
    Path(f"{d}/ai.py").write_text("def f():\n    return 142\n")
    audit_result = audit_ai_output(d)
    params = prepare_audit_record_params(audit_result)
    print(f"observed=AC-8 has_content={isinstance(params.get('content'), str)} has_quality_level={'quality_level' in params} tags_has_rea_audit={'rea-audit' in params.get('tags', '')}")

# ========== AC-9 & AC-10: 对 33-REA 自身模块运行 ==========

print("\n[AC-9/10] 对 33-REA 自身 core/ 运行决策还原 + 审计")
core_dir = str(REPO_ROOT / "core")
decision_result = recover_decisions(core_dir)
audit_result = audit_ai_output(core_dir)
print(f"observed=AC-9 self_recover decisions_count={len(decision_result.get('decisions', []))}")
print(f"observed=AC-10 self_audit poe_score={audit_result['poe_score']:.3f} gate={audit_result['gate_decision']} evidence_chain={audit_result['evidence_chain_score']:.3f}")

# ========== NFR-7: FAIL-OPEN 验证 ==========

print("\n[NFR-7] FAIL-OPEN → 不存在路径 / 异常输入")
result = audit_ai_output("/nonexistent/path/xyz")
print(f"observed=NFR-7 poe_score={result['poe_score']} gate={result['gate_decision']} has_unknown_evidence={any(e.level.value == 'unknown' for e in result.get('evidence', []))}")

# ========== NFR-1a: Inference 幻觉控制 ==========

print("\n[NFR-1a] Inference 幻觉控制 → known_gaps 非空 + confidence ≤ 0.6")
with tempfile.TemporaryDirectory() as d:
    Path(f"{d}/repo.py").write_text(
        "from sqlalchemy.orm import Session\n"
        "class R:\n"
        "    def find(self, s):\n"
        "        return s.execute('SELECT 1')\n"
    )
    result = recover_decisions(d)
    inferences = []
    for dec in result.get("decisions", []):
        for alt in dec.get("alternatives", []):
            if isinstance(alt, dict) and alt.get("level") == "inference":
                inferences.append(alt)
    all_have_gaps = all(alt.get("known_gaps") for alt in inferences) if inferences else True
    all_below_conf = all(alt.get("confidence", 1.0) <= 0.6 for alt in inferences) if inferences else True
    print(f"observed=NFR-1a inference_count={len(inferences)} all_have_known_gaps={all_have_gaps} all_confidence_le_0.6={all_below_conf}")

print("\n" + "=" * 70)
print("症状复测完成 — 详见上方 observed= 标记行")
print("=" * 70)
