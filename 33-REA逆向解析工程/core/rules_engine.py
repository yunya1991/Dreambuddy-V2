"""架构约束引擎（SPEC-33-F §2.5 / T-F06）。

规则文件 `rea_rules.yaml`（仓库根可选），支持三种规则：
  - forbid_edge：禁止 A 层 → B 层的依赖边
  - forbid_cycle：禁止 scope 内的循环依赖
  - threshold：fan_out 等度量阈值

硬性约束（SPEC-F §5）：无 rea_rules.yaml 时完全跳过，零行为变化。
违例输出统一 Evidence（level=derivation，含 file/rule_id）。
"""

from __future__ import annotations

import os
from pathlib import PurePosixPath
from typing import Any

import yaml


def load_rules(path: str) -> list[dict[str, Any]]:
    """加载 rea_rules.yaml，文件不存在或解析失败返回空列表（FAIL-OPEN）。"""
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return list(data.get("rules") or [])
    except (yaml.YAMLError, OSError):
        return []


def load_layers(path: str) -> dict[str, list[str]]:
    """加载层定义，文件不存在返回空字典。"""
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return dict(data.get("layers") or {})
    except (yaml.YAMLError, OSError):
        return {}


def _match_layer(module: str, patterns: list[str]) -> bool:
    """判断模块是否属于某一层（glob 匹配）。"""
    p = PurePosixPath(module)
    for pattern in patterns:
        # 处理 /** 结尾：匹配该目录下所有文件
        if pattern.endswith("/**"):
            prefix = pattern[:-3]
            if module.startswith(prefix + "/") or module == prefix:
                return True
        elif p.match(pattern):
            return True
    return False


def _module_layer(module: str, layers: dict[str, list[str]]) -> str | None:
    """返回模块所属的层名，不属于任何层返回 None。"""
    for layer_name, patterns in layers.items():
        if _match_layer(module, patterns):
            return layer_name
    return None


def _make_violation(
    rule_id: str,
    rule_type: str,
    file: str,
    message: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构造统一违例记录。"""
    provenance = {
        "analysis": "rules_engine",
        "rule_id": rule_id,
        "rule_type": rule_type,
        "file": file,
    }
    if extra:
        provenance.update(extra)
    return {
        "rule_id": rule_id,
        "rule_type": rule_type,
        "file": file,
        "line": 0,  # 行号需源码级解析，当前为模块级检查
        "evidence": {
            "result": message,
            "level": "derivation",
            "provenance": provenance,
            "confidence": 0.9,
            "known_gaps": ["行号需源码级 AST 解析，当前为模块级检查"],
        },
    }


def _check_forbid_edge(
    adjacency: dict[str, list[str]],
    layers: dict[str, list[str]],
    rule: dict[str, Any],
) -> list[dict[str, Any]]:
    """检查禁止边规则。"""
    from_layer = rule.get("from", "")
    to_layer = rule.get("to", "")
    message = rule.get("message", f"禁止 {from_layer} → {to_layer} 依赖")
    violations = []

    for src, dsts in adjacency.items():
        src_layer = _module_layer(src, layers)
        if src_layer != from_layer:
            continue
        for dst in dsts:
            dst_layer = _module_layer(dst, layers)
            # to 可以是层名或路径前缀
            if dst_layer == to_layer or dst.startswith(to_layer + "/") or to_layer in dst:
                violations.append(
                    _make_violation(
                        rule["id"],
                        "forbid_edge",
                        src,
                        f"{message}: {src} → {dst}",
                        {"from_module": src, "to_module": dst},
                    )
                )
    return violations


def _find_cycles_in_scope(
    adjacency: dict[str, list[str]],
    scope_modules: set[str],
) -> list[list[str]]:
    """在 scope 内查找循环依赖（简化 DFS）。"""
    cycles = []
    visited = set()
    rec_stack = set()
    path: list[str] = []

    def dfs(node: str) -> bool:
        visited.add(node)
        rec_stack.add(node)
        path.append(node)
        for neighbor in adjacency.get(node, []):
            if neighbor not in scope_modules:
                continue
            if neighbor not in visited:
                if dfs(neighbor):
                    return True
            elif neighbor in rec_stack:
                # 找到环
                cycle_start = path.index(neighbor)
                cycles.append(path[cycle_start:] + [neighbor])
                return True
        path.pop()
        rec_stack.discard(node)
        return False

    for module in sorted(scope_modules):
        if module not in visited:
            dfs(module)
    return cycles


def _check_forbid_cycle(
    adjacency: dict[str, list[str]],
    layers: dict[str, list[str]],
    rule: dict[str, Any],
) -> list[dict[str, Any]]:
    """检查禁止循环规则。"""
    scope_layers = rule.get("scope", [])
    if isinstance(scope_layers, str):
        scope_layers = [scope_layers]
    scope_modules = {m for m in adjacency if _module_layer(m, layers) in scope_layers}
    cycles = _find_cycles_in_scope(adjacency, scope_modules)
    violations = []
    for cycle in cycles:
        cycle_str = " → ".join(cycle)
        violations.append(
            _make_violation(
                rule["id"],
                "forbid_cycle",
                cycle[0],
                f"跨层循环依赖: {cycle_str}",
                {"cycle": cycle},
            )
        )
    return violations


def _check_threshold(
    adjacency: dict[str, list[str]],
    layers: dict[str, list[str]],
    rule: dict[str, Any],
) -> list[dict[str, Any]]:
    """检查阈值规则。"""
    metric = rule.get("metric", "fan_out")
    max_val = rule.get("max", 25)
    scope = rule.get("scope", "")
    scope_modules = (
        {m for m in adjacency if _module_layer(m, layers) == scope}
        if scope
        else set(adjacency.keys())
    )

    violations = []
    for module in sorted(scope_modules):
        if metric == "fan_out":
            value = len(adjacency.get(module, []))
            if value > max_val:
                violations.append(
                    _make_violation(
                        rule["id"],
                        "threshold",
                        module,
                        f"{module} fan_out={value} 超过阈值 {max_val}",
                        {"metric": metric, "value": value, "threshold": max_val},
                    )
                )
    return violations


def check_constraints(
    adjacency: dict[str, list[str]],
    layers: dict[str, list[str]],
    rules: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """执行所有约束检查，返回违例列表。"""
    if not rules or not layers:
        return []
    violations = []
    for rule in rules:
        rule_type = rule.get("type", "")
        if rule_type == "forbid_edge":
            violations.extend(_check_forbid_edge(adjacency, layers, rule))
        elif rule_type == "forbid_cycle":
            violations.extend(_check_forbid_cycle(adjacency, layers, rule))
        elif rule_type == "threshold":
            violations.extend(_check_threshold(adjacency, layers, rule))
    return violations
