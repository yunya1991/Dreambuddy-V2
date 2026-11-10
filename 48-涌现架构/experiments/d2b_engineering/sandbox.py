"""
D2-B 沙箱验证（零执行权）。

只做静态校验，不执行任何生成代码：
  - 方案模块名不在现有架构图中（新颖性前置）
  - 所有依赖可解析（stdlib 或架构图中存在的路径）
  - 方案步骤非空且每步有动词（可行性前置）
  - 架构图 patch 的 edge kind 合法
"""

from __future__ import annotations

from pathlib import Path

from generator import BuildPlan, _arch_graph, _existing_modules

HERE = Path(__file__).resolve().parent
PKG_ROOT = HERE.parent.parent

VALID_EDGE_KINDS = {"import", "call", "doc_ref"}
STDLIB = {"ast", "os", "sys", "json", "re", "pathlib", "typing", "dataclasses", "collections"}


def _dep_exists(dep: str, graph: dict) -> bool:
    if dep in STDLIB:
        return True
    if dep == "architecture_graph.json":
        return True
    node_ids = {n["id"] for n in graph.get("nodes", [])}
    if dep in node_ids:
        return True
    # 前缀匹配：dep 是某节点 id 的前缀，或某节点 id 是 dep 目录的前缀
    for nid in node_ids:
        if nid.startswith(dep) or dep.startswith(nid.rsplit("/", 1)[0]):
            return True
    # 目录级匹配：取 dep 的第一个路径段，检查是否有节点以此开头
    top = dep.split("/")[0]
    for nid in node_ids:
        if nid.startswith(top):
            return True
    return False


def validate(plan: BuildPlan) -> dict:
    graph = _arch_graph()
    existing = _existing_modules(graph)
    errors: list[str] = []
    warnings: list[str] = []

    # 1. 新颖性：模块名不与现有重复
    if plan.module_name in existing:
        errors.append(f"模块名已存在: {plan.module_name}")

    # 2. 依赖可解析
    for dep in plan.dependencies:
        if not _dep_exists(dep, graph):
            errors.append(f"依赖不可解析: {dep}")

    # 3. 步骤可行性
    if not plan.steps:
        errors.append("方案无步骤")
    else:
        verbs = {"遍历", "加载", "提取", "统计", "检查", "生成", "比较", "输出", "回写", "对", "用"}
        for i, step in enumerate(plan.steps):
            if not any(step.strip().startswith(v) for v in verbs):
                warnings.append(f"步骤 {i+1} 可能缺动词: {step[:40]}")

    # 4. patch edge kind 合法
    patch = plan.architecture_graph_patch
    for edge in patch.get("add_edges", []):
        if edge.get("kind") not in VALID_EDGE_KINDS:
            errors.append(f"非法 edge kind: {edge.get('kind')}")

    # 5. 方案文本语法检查（rationale 非空）
    if not plan.design_rationale or len(plan.design_rationale) < 20:
        errors.append("design_rationale 过短")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "novel": plan.module_name not in existing,
        "deps_resolved": all(_dep_exists(d, graph) for d in plan.dependencies),
    }
