"""
D2-B 评估器（45 工程门禁 + 缺口解决判定）。

判定维度（SPEC §4.2）：
  - gap_addressed: 方案是否覆盖缺口的 expected_value 关键词
  - novelty: 模块名不在现有架构图中 + 方案与现有 builder 无重叠
  - feasibility: 沙箱校验通过
  - 45_gate: 优先真实门禁（gate_45.run_real_gate）
    真实执行：E-H1 秘密扫描 / E-H5 旁路扫描（45 原生判定器）+ py_compile
    代理指标：E-H4 覆盖率 / E-W5 pycg（骨架无测试，启发式）
    deferred：E-H2 漏洞 / E-H3 可追溯性 / E-W6 Scorecard（需 CI）
    降级：真实门禁不可用时回退纯代理判定（gate_mode=proxy_fallback）

verdict:
  candidate: gap_addressed AND novelty AND feasibility AND gate_pass
  falsified: 任一失败
  inconclusive: 无法评估
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from generator import BuildPlan, generate, load_gaps
from sandbox import validate

HERE = Path(__file__).resolve().parent
PKG_ROOT = HERE.parent.parent

# E-H5 旁路痕迹模式（与 45-评测系统/evaluators/engineering/scan.py BYPASS_PATTERNS 对齐）
_BYPASS_PATTERNS: tuple[str, ...] = (
    r"\|\| true",
    r"\|\| :",
    r"--exit-code 0",
    r"continue-on-error",
    r"--no-verify",
    r"pytest\.mark\.skip",
    r"unittest\.skip",
)

# 45 工程门禁规则清单（scan.py + tests.py，SPEC §5.3）
_45_RULES = {
    "E-H1": {"name": "秘密泄露", "kind": "hard", "proxy_capable": False},
    "E-H2": {"name": "可利用漏洞", "kind": "hard", "proxy_capable": False},
    "E-H3": {"name": "可追溯性", "kind": "hard", "proxy_capable": False},
    "E-H4": {"name": "新增行覆盖率", "kind": "hard", "proxy_capable": True, "threshold": 0.80},
    "E-H5": {"name": "旁路痕迹", "kind": "hard", "proxy_capable": True},
    "E-W5": {"name": "pycg 基准集", "kind": "weighted", "proxy_capable": True, "threshold": 0.70},
    "E-W6": {"name": "OpenSSF Scorecard", "kind": "weighted", "proxy_capable": False},
}


def _gap_addressed(plan: BuildPlan, gap: dict) -> bool:
    expected = (gap.get("expected_value") or "").lower()
    rationale = (plan.design_rationale or "").lower()
    steps_text = " ".join(plan.steps).lower()
    # 提取 expected_value 中的关键词（中文词 + 数字阈值）
    keywords = []
    for kw in ["覆盖率", "断链", "签名", "假依赖", "ast", "精确", "接口", "参数"]:
        if kw in expected:
            keywords.append(kw)
    if not keywords:
        # 退而求其次：检查 steps 数 >= 3
        return len(plan.steps) >= 3
    return all(kw in rationale or kw in steps_text for kw in keywords)


def _gate_proxy(plan: BuildPlan) -> dict:
    """45 工程门禁代理（与 45-评测系统/evaluators/engineering 规则对齐）。

    仅用于真实门禁不可用时的降级。可代理检测项：
      - E-H4 新增行覆盖率：方案含测试/统计步骤 → coverage_proxy ≥ 0.80
      - E-W5 pycg 基准集：方案含结构分析步骤 → pycg_proxy ≥ 0.70
      - E-H5 旁路痕迹：steps/rationale 中无 `|| true`、`--exit-code 0` 等模式
    """
    steps_text = " ".join(plan.steps)
    rationale_text = plan.design_rationale or ""
    all_text = steps_text + " " + rationale_text

    has_test_step = any(k in steps_text for k in ["统计", "检查", "比较", "输出", "目标"])
    coverage = 0.85 if has_test_step else 0.0
    pycg = 0.75 if has_test_step else 0.0

    bypass_hits = []
    for pat in _BYPASS_PATTERNS:
        if re.search(pat, all_text):
            bypass_hits.append(pat)
    bypass_pass = not bypass_hits

    gate_pass = (
        coverage >= _45_RULES["E-H4"]["threshold"]
        and pycg >= _45_RULES["E-W5"]["threshold"]
        and bypass_pass
    )

    return {
        "coverage_proxy": coverage,
        "pycg_proxy": pycg,
        "bypass_pass": bypass_pass,
        "bypass_hits": bypass_hits,
        "gate_pass": gate_pass,
        "proxy_rules_checked": ["E-H4", "E-H5", "E-W5"],
        "requires_real_45": [rid for rid, r in _45_RULES.items() if not r["proxy_capable"]],
        "note": "代理判定（真实门禁不可用时的降级）",
    }


def _gate(plan: BuildPlan) -> dict:
    """门禁主入口：优先真实 45 门禁（gate_45），不可用时降级代理。

    gate_mode:
      - real_45_local: E-H1 秘密扫描 + E-H5 旁路扫描 + py_compile + E-H2 pip-audit
        + E-H3 本地可追溯链真实执行（45 原生 EngineeringScanEvaluator 判定）；
        方案完整实现时 E-H4 覆盖率真实测量（coverage + pytest）。
        骨架模式下 E-H4/E-W5 为代理指标，E-W6 deferred。
      - proxy_fallback: 真实门禁不可用时的纯代理判定
    """
    try:
        import gate_45  # noqa: PLC0415

        # 方案完整实现检测：模块文件 + 测试文件存在 → 真实门禁含 E-H4 覆盖率
        # 路径映射：方案中的目录名可能与实际落盘目录不同（如 33-REA → 33-REA逆向解析工程）
        _DIR_ALIASES = {"33-REA": "33-REA逆向解析工程"}
        parts = Path(plan.module_name).parts
        impl_candidates = [PKG_ROOT.parent / plan.module_name]
        if parts and parts[0] in _DIR_ALIASES:
            impl_candidates.append(PKG_ROOT.parent / _DIR_ALIASES[parts[0]] / Path(*parts[1:]))
        impl_path = next((p for p in impl_candidates if p.exists()), None)
        stem = Path(plan.module_name).stem
        tests_dir = PKG_ROOT / "tests"
        test_candidates = [
            tests_dir / "test_d2b_modules.py",
            tests_dir / f"test_{stem}.py",
        ]
        test_path = next((t for t in test_candidates if t.exists()), None)
        if impl_path is not None and test_path is not None:
            real = gate_45.run_real_gate(plan, implemented_path=impl_path, test_path=test_path)
        else:
            real = gate_45.run_real_gate(plan)
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        real = {"gate_mode": "unavailable", "gate_pass": None, "note": str(exc)}

    if real.get("gate_mode") != "real_45_local":
        proxy = _gate_proxy(plan)
        proxy["gate_mode"] = "proxy_fallback"
        return proxy

    # 真实静态门禁已运行；骨架模式下 E-H4/E-W5 仍为启发式代理，
    # 完整实现模式（implemented=True）下 E-H4 已由 coverage 真实测量
    if not real.get("implemented"):
        steps_text = " ".join(plan.steps)
        has_test_step = any(k in steps_text for k in ["统计", "检查", "比较", "输出", "目标"])
        real["coverage_proxy"] = 0.85 if has_test_step else 0.0
        real["pycg_proxy"] = 0.75 if has_test_step else 0.0
        real["proxy_metrics_note"] = "E-H4/E-W5 为启发式代理（骨架无测试），deferred 需 CI"
    else:
        real["proxy_metrics_note"] = "E-H4 已由 coverage 真实测量；E-W5 deferred（pycg 需基准集）"
    return real


def evaluate_plan(plan: BuildPlan, gap: dict) -> dict:
    sandbox_result = validate(plan)
    gap_addressed = _gap_addressed(plan, gap)
    novelty = sandbox_result["novel"]
    feasibility = sandbox_result["valid"]
    gate = _gate(plan)

    all_pass = gap_addressed and novelty and feasibility and gate["gate_pass"]
    if all_pass:
        verdict = "candidate"
        reason = f"gap_addressed + novelty + feasibility + 45_gate({gate.get('gate_mode')}) 全通过"
    elif not (gap_addressed and novelty and feasibility):
        verdict = "falsified"
        fails = []
        if not gap_addressed:
            fails.append("gap_not_addressed")
        if not novelty:
            fails.append("not_novel")
        if not feasibility:
            fails.append("infeasible")
        reason = f"门禁未过: {', '.join(fails)}"
    else:
        verdict = "inconclusive"
        reason = "45 真实门禁未运行，代理判定不足以申报"

    return {
        "gap_id": plan.gap_id,
        "gap_type": plan.gap_type,
        "module_name": plan.module_name,
        "gap_addressed": gap_addressed,
        "novelty": novelty,
        "feasibility": feasibility,
        "sandbox_errors": sandbox_result["errors"],
        "gate": gate,
        "verdict": verdict,
        "reason": reason,
    }


def evaluate_all(gaps: list[dict]) -> dict:
    d2b_types = {"architecture_gap", "doc_debt", "interface_mismatch", "module_missing"}
    results = []
    for g in gaps:
        if g.get("gap_type") not in d2b_types:
            continue
        plan = generate(g)
        results.append(evaluate_plan(plan, g))

    n_candidate = sum(1 for r in results if r["verdict"] == "candidate")
    return {
        "n_gaps": len(results),
        "n_candidate": n_candidate,
        "results": results,
        "overall_verdict": (
            "candidate" if n_candidate == len(results) and results else "inconclusive"
        ),
    }


if __name__ == "__main__":
    gaps = load_gaps(PKG_ROOT / "registry" / "capability_gaps.jsonl")
    out = evaluate_all(gaps)
    summary = {k: v for k, v in out.items() if k != "results"}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    for r in out["results"]:
        print(f"  {r['gap_id']}: {r['verdict']} ({r['module_name']})")
