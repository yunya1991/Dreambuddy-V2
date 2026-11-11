#!/usr/bin/env python3
"""52-LobeHub 协议集成 Phase 5 — 45 域评测器适配层。

职责边界（诚实原则）：
  - 只做「契约接入 + provenance」：把 PlanCard 映射到 45 的评测器名称，
    检查该评测器是否注册、规划期所需的领域产物是否落盘；
  - 规划期 PlanCard 没有领域产物（EngineeringScan / BacktestStats / StressPlan），
    因此**缺产物时一律 INCONCLUSIVE，绝不编造 PASS/BLOCK**；
  - 45 源码只 import 不修改；不可用/导入失败一律 fail-open，绝不抛异常。

已知局限：真实产物评测需要先把 `45-评测系统/artifacts/inputs/{run_id}.json`
映射为 45 领域对象（后续接入），当前即使产物存在也只做契约校验。
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

ORCHESTRATOR_DIR = Path(__file__).resolve().parent
REPO_ROOT = ORCHESTRATOR_DIR.parents[1]
DEFAULT_EVALUATORS_ROOT = REPO_ROOT / "45-评测系统"
ARTIFACT_SUBDIR = ("artifacts", "inputs")
# 45 根目录下的通用包名（与宿主其它子系统同名，需隔离导入）
IMPORT_NAMESPACES = ("api", "core", "evaluators", "integrations", "scorers", "storage")

# 域 → 45 评测器名称（R5 决议映射）
DOMAIN_MAP = {
    "engineering": "engineering-scan",
    "finance": "finance-backtest-stats",
    "ai": "ai-stress",
}

# 工具名前缀 → 域（取 tool 最后一段做前缀匹配）
TOOL_PREFIX_DOMAIN = (
    ("backtest", "finance"),
    ("scan", "engineering"),
    ("tests", "engineering"),
    ("stress", "ai"),
)

# 意图关键词 → 域（确定性计数，非 LLM 推断）
INTENT_KEYWORDS = {
    "finance": (
        "回测",
        "夏普",
        "因子",
        "策略",
        "交易",
        "持仓",
        "收益",
        "波动率",
        "均线",
        "阈值",
        "资金",
        "风控",
    ),
    "engineering": ("工程", "代码", "测试", "重构", "依赖", "仓库", "接口", "部署", "性能", "模块"),
    "ai": ("模型", "推理", "提示词", "裁判", "校准", "压力", "对齐", "幻觉", "llm", "agent"),
}

VERDICT_PASS = "PASS"
VERDICT_BLOCK = "BLOCK"
VERDICT_INCONCLUSIVE = "INCONCLUSIVE"

# 结构分权重（权重和 1.10，最终按总权重归一化到 0-1）
STRUCTURAL_WEIGHTS = {
    "tool_legality": 0.25,
    "step_count": 0.15,
    "validation": 0.20,
    "evidence_refs": 0.20,
    "risk_flags": 0.20,
    "cost_estimate": 0.10,
}
TOTAL_STRUCTURAL_WEIGHT = sum(STRUCTURAL_WEIGHTS.values())


def _fail_open(root: Path, exc: BaseException) -> dict[str, Any]:
    return {
        "available": False,
        "error": f"{type(exc).__name__}: {exc}",
        "names": [],
        "versions": {},
        "root": str(root),
    }


def _load_registry(root: Path) -> dict[str, Any]:
    """隔离导入 45 registry（临时让出同名包，避免宿主 sys.modules 串包）。

    45 根目录含通用包名（core/storage/api/...），与仓库其它子系统的同名包
    冲突。这里临时移除同名模块、把 45 根目录置于 sys.path 首位，导入完立即
    还原，既不改 45 源码，也不污染宿主进程。
    """
    saved_path = list(sys.path)
    saved_modules: dict[str, Any] = {}
    for module_name in list(sys.modules):
        top = module_name.split(".")[0]
        if top in IMPORT_NAMESPACES:
            saved_modules[module_name] = sys.modules.pop(module_name)
    sys.path.insert(0, str(root))
    try:
        registry_module = importlib.import_module("evaluators.registry")
        registry = registry_module.load_defaults()
        names = list(registry.names())
        versions = {name: list(registry.versions(name)) for name in names}
        return {"names": names, "versions": versions}
    finally:
        for module_name in list(sys.modules):
            if module_name.split(".")[0] in IMPORT_NAMESPACES:
                del sys.modules[module_name]
        sys.modules.update(saved_modules)
        sys.path[:] = saved_path


def discover(evaluators_root: str | None = None) -> dict[str, Any]:
    """发现 45 评测器（只读 import，不改 45 源码，异常一律 fail-open）。

    返回 {available, names, versions, root}；失败额外带 error。
    """
    root = Path(evaluators_root) if evaluators_root is not None else DEFAULT_EVALUATORS_ROOT
    if not root.exists():
        return _fail_open(root, FileNotFoundError(f"评测器根目录不存在：{root}"))
    root_str = str(root)
    try:
        loaded = _load_registry(root)
        names = loaded["names"]
        versions = loaded["versions"]
    except Exception as exc:  # noqa: BLE001 — 45 不可用必须 fail-open
        return _fail_open(root, exc)
    return {
        "available": True,
        "names": names,
        "versions": versions,
        "root": root_str,
    }


def _tool_basename(tool: str) -> str:
    return tool.rsplit(".", 1)[-1].strip().lower()


def detect_domain(card: dict[str, Any]) -> str:
    """域判定：plan_steps[].tool 前缀 → 意图关键词 → 默认 engineering。"""
    steps = card.get("plan_steps") if isinstance(card, dict) else None
    for step in steps if isinstance(steps, list) else []:
        tool = step.get("tool") if isinstance(step, dict) else None
        if not isinstance(tool, str):
            continue
        basename = _tool_basename(tool)
        for prefix, domain in TOOL_PREFIX_DOMAIN:
            if basename.startswith(prefix):
                return domain

    intent = str(card.get("intent") or "") if isinstance(card, dict) else ""
    lowered = intent.lower()
    counts = {
        domain: sum(1 for keyword in keywords if keyword in lowered)
        for domain, keywords in INTENT_KEYWORDS.items()
    }
    best = max(counts, key=lambda domain: counts[domain])
    return best if counts[best] > 0 else "engineering"


def _artifact_path(root: Path, run_id: str) -> Path:
    safe_run_id = Path(str(run_id or "unknown")).name
    return root.joinpath(*ARTIFACT_SUBDIR, f"{safe_run_id}.json")


def evaluate_plan(
    card: dict[str, Any],
    *,
    run_id: str,
    evaluators_root: str | None = None,
    discovery: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """PlanCard → 45 评测契约结果。

    返回 {verdict, reason, evaluator: "name@version", domain, required_artifacts}。
    规则：45 不可用 → INCONCLUSIVE/45_unavailable；评测器未注册 →
    INCONCLUSIVE/evaluator_not_found；产物缺失 → INCONCLUSIVE/missing_artifacts。
    缺产物时**禁止**返回 PASS/BLOCK。
    """
    root = Path(evaluators_root) if evaluators_root is not None else DEFAULT_EVALUATORS_ROOT
    info = discovery if discovery is not None else discover(str(root))
    domain = detect_domain(card)
    evaluator_name = DOMAIN_MAP[domain]
    artifact = _artifact_path(root, run_id)
    required_artifacts = [str(artifact)]

    if not info.get("available"):
        return {
            "verdict": VERDICT_INCONCLUSIVE,
            "reason": "45_unavailable",
            "evaluator": f"{evaluator_name}@unresolved",
            "domain": domain,
            "required_artifacts": required_artifacts,
        }

    names = info.get("names") or []
    versions = info.get("versions") or {}
    if evaluator_name not in names:
        return {
            "verdict": VERDICT_INCONCLUSIVE,
            "reason": "evaluator_not_found",
            "evaluator": f"{evaluator_name}@unresolved",
            "domain": domain,
            "required_artifacts": required_artifacts,
        }

    version_list = versions.get(evaluator_name) or []
    version = version_list[-1] if version_list else "unknown"
    evaluator_ref = f"{evaluator_name}@{version}"
    if not artifact.exists():
        return {
            "verdict": VERDICT_INCONCLUSIVE,
            "reason": "missing_artifacts",
            "evaluator": evaluator_ref,
            "domain": domain,
            "required_artifacts": required_artifacts,
        }

    # 产物已落盘，但 PlanCard 侧的领域对象映射尚未接入（后续 Phase）。
    return {
        "verdict": VERDICT_INCONCLUSIVE,
        "reason": "artifact_not_evaluated",
        "evaluator": evaluator_ref,
        "domain": domain,
        "required_artifacts": required_artifacts,
    }


def _step_count_raw(count: int) -> float:
    if 2 <= count <= 8:
        return 1.0
    if count == 1 or 9 <= count <= 12:
        return 0.5
    return 0.2


def _allowed_set(allowed_tools: Any) -> set[str] | None:
    if allowed_tools is None:
        return None
    if isinstance(allowed_tools, set):
        return allowed_tools
    if hasattr(allowed_tools, "allowed"):
        return set(allowed_tools.allowed())
    return {str(tool) for tool in allowed_tools}


def structural_score(
    card: dict[str, Any], allowed_tools: Any = None
) -> tuple[float, list[dict[str, Any]]]:
    """确定性、非退化的规划质量分（0-1，保留 3 位小数）与逐项明细。

    allowed_tools 为 None 时不做注册校验（tool 合法率取「有无工具」）。
    权重和 1.10，按总权重归一化，避免满分卡直接饱和（防 T1 恒 0 退化）。
    """
    steps = card.get("plan_steps") if isinstance(card, dict) else None
    step_list = (
        [step for step in steps if isinstance(step, dict)] if isinstance(steps, list) else []
    )
    allowed = _allowed_set(allowed_tools)

    if allowed is None:
        tool_raw = (
            1.0 if step_list and all(isinstance(s.get("tool"), str) for s in step_list) else 0.0
        )
    elif step_list:
        legal = sum(
            1 for step in step_list if isinstance(step.get("tool"), str) and step["tool"] in allowed
        )
        tool_raw = legal / len(step_list)
    else:
        tool_raw = 0.0

    validation = card.get("validation") if isinstance(card, dict) else None
    evidence_refs = card.get("evidence_refs") if isinstance(card, dict) else None
    evidence_count = len(evidence_refs) if isinstance(evidence_refs, list) else 0
    risk_flags = card.get("risk_flags") if isinstance(card, dict) else None
    risk_count = len(risk_flags) if isinstance(risk_flags, list) else 0
    cost = card.get("cost_estimate") if isinstance(card, dict) else None

    raws = {
        "tool_legality": tool_raw,
        "step_count": _step_count_raw(len(step_list)),
        "validation": 1.0 if isinstance(validation, dict) and bool(validation) else 0.0,
        "evidence_refs": min(1.0, evidence_count / 2),
        "risk_flags": max(0.4, 1.0 - 0.15 * risk_count),
        "cost_estimate": 1.0 if isinstance(cost, dict) and bool(cost) else 0.0,
    }

    detail: list[dict[str, Any]] = []
    weighted_sum = 0.0
    for name, weight in STRUCTURAL_WEIGHTS.items():
        raw = raws[name]
        contribution = weight * raw
        weighted_sum += contribution
        detail.append(
            {
                "name": name,
                "raw": round(raw, 3),
                "weight": weight,
                "contribution": round(contribution, 4),
            }
        )

    normalized = weighted_sum / TOTAL_STRUCTURAL_WEIGHT if TOTAL_STRUCTURAL_WEIGHT else 0.0
    return round(max(0.0, min(1.0, normalized)), 3), detail
