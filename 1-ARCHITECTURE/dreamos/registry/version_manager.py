"""
DreamOS Registry — 版本管理与依赖检查

功能:
    1. 节点版本管理 (semver)
    2. 依赖声明与检查 (depends_on)
    3. 版本兼容性检测
    4. 节点分组与标签管理

节点元信息扩展:
    - version: 节点版本号 (semver, 如 "1.0.0")
    - requires: 依赖的其他节点 ID 及版本要求
    - provides: 此节点提供的能力
    - deprecated: 是否已废弃
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field

from dreamos.shared.errors import OSError, ErrorCode
from dreamos.shared.interfaces import Node


# ============================================================
# 版本比较
# ============================================================

def parse_version(version_str: str) -> Tuple[int, int, int]:
    """解析 semver 版本号

    Returns:
        (major, minor, patch)
    """
    try:
        parts = version_str.split(".")
        major = int(parts[0]) if len(parts) > 0 else 0
        minor = int(parts[1]) if len(parts) > 1 else 0
        patch = int(parts[2]) if len(parts) > 2 else 0
        return (major, minor, patch)
    except (ValueError, IndexError):
        return (0, 0, 0)


def compare_versions(v1: str, v2: str) -> int:
    """比较两个版本号

    Returns:
        1: v1 > v2
        0: v1 == v2
        -1: v1 < v2
    """
    a = parse_version(v1)
    b = parse_version(v2)
    if a > b:
        return 1
    elif a < b:
        return -1
    return 0


def satisfies_requirement(version: str, requirement: str) -> bool:
    """检查版本是否满足要求

    支持的要求格式:
        - ">=1.0.0"  大于等于
        - "<=2.0.0"  小于等于
        - ">1.0.0"   大于
        - "<2.0.0"   小于
        - "1.0.0"    精确等于
        - "~1.2.0"   兼容 (同 minor)
        - "^1.0.0"   兼容 (同 major)
    """
    if not requirement:
        return True

    req = requirement.strip()

    if req.startswith(">="):
        return compare_versions(version, req[2:]) >= 0
    elif req.startswith("<="):
        return compare_versions(version, req[2:]) <= 0
    elif req.startswith(">"):
        return compare_versions(version, req[1:]) > 0
    elif req.startswith("<"):
        return compare_versions(version, req[1:]) < 0
    elif req.startswith("~"):
        # ~1.2.0: >=1.2.0, <1.3.0
        ver = req[1:]
        maj, min_, _ = parse_version(ver)
        upper = f"{maj}.{min_ + 1}.0"
        return compare_versions(version, ver) >= 0 and compare_versions(version, upper) < 0
    elif req.startswith("^"):
        # ^1.2.0: >=1.2.0, <2.0.0
        ver = req[1:]
        maj, _, _ = parse_version(ver)
        upper = f"{maj + 1}.0.0"
        return compare_versions(version, ver) >= 0 and compare_versions(version, upper) < 0
    else:
        # 精确等于
        return compare_versions(version, req) == 0


# ============================================================
# 依赖检查结果
# ============================================================

@dataclass
class DependencyCheckResult:
    """依赖检查结果"""
    ok: bool = True
    missing: List[str] = field(default_factory=list)        # 缺少的节点
    incompatible: Dict[str, str] = field(default_factory=dict)  # 版本不兼容 {node_id: expected}
    deprecated: List[str] = field(default_factory=list)    # 已废弃的节点

    @property
    def issues(self) -> int:
        return len(self.missing) + len(self.incompatible) + len(self.deprecated)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "missing": self.missing,
            "incompatible": self.incompatible,
            "deprecated": self.deprecated,
            "issues": self.issues,
        }


# ============================================================
# 版本化节点 mixin
# ============================================================

class VersionedNodeMixin:
    """节点版本化 mixin

    让节点支持版本号、依赖声明、废弃标记。

    用法:
        class MyNode(VersionedNodeMixin, BaseNode):
            version = "1.0.0"
            requires = {"A0": ">=1.0.0"}
            provides = ["trend_analysis"]
    """
    version: str = "0.1.0"
    requires: Dict[str, str] = {}       # {node_id: version_requirement}
    provides: List[str] = []            # 提供的能力
    deprecated: bool = False
    deprecation_note: str = ""


# ============================================================
# 注册表扩展方法
# ============================================================

class RegistryExtension:
    """注册表扩展 — 版本管理 + 依赖检查

    用法:
        ext = RegistryExtension(registry)

        # 检查依赖
        result = ext.check_dependencies("A1")

        # 查找提供某能力的节点
        nodes = ext.find_by_capability("trend_analysis")

        # 按版本获取
        node = ext.get_version("A0", ">=1.0.0")
    """

    def __init__(self, registry):
        self._registry = registry

    def check_dependencies(self, node_id: str) -> DependencyCheckResult:
        """检查节点的依赖是否满足

        Args:
            node_id: 要检查的节点 ID

        Returns:
            DependencyCheckResult
        """
        result = DependencyCheckResult()
        node = self._registry.get(node_id)
        if node is None:
            result.missing.append(node_id)
            result.ok = False
            return result

        # 检查 requires
        requires = getattr(node, "requires", {}) or {}
        for dep_id, version_req in requires.items():
            dep_node = self._registry.get(dep_id)
            if dep_node is None:
                result.missing.append(dep_id)
                result.ok = False
            else:
                dep_version = getattr(dep_node, "version", "0.0.0")
                if not satisfies_requirement(dep_version, version_req):
                    result.incompatible[dep_id] = f"需要 {version_req}, 实际 {dep_version}"
                    result.ok = False

        # 检查是否废弃
        if getattr(node, "deprecated", False):
            result.deprecated.append(node_id)

        return result

    def check_all_dependencies(self) -> Dict[str, DependencyCheckResult]:
        """检查所有节点的依赖"""
        results = {}
        for node in self._registry.list_nodes():
            results[node.node_id] = self.check_dependencies(node.node_id)
        return results

    def find_by_capability(self, capability: str) -> List[Node]:
        """查找提供指定能力的节点"""
        results = []
        for node in self._registry.list_nodes():
            provides = getattr(node, "provides", []) or []
            if capability in provides:
                results.append(node)
        return results

    def get_version(self, node_id: str, version_req: str = "") -> Optional[Node]:
        """按版本要求获取节点"""
        node = self._registry.get(node_id)
        if node is None:
            return None
        if not version_req:
            return node
        node_version = getattr(node, "version", "0.0.0")
        if satisfies_requirement(node_version, version_req):
            return node
        return None

    def list_versions(self) -> Dict[str, str]:
        """列出所有节点的版本"""
        result = {}
        for node in self._registry.list_nodes():
            result[node.node_id] = getattr(node, "version", "0.0.0")
        return result

    def validate(self) -> Tuple[bool, List[str]]:
        """验证整个注册表的健康度

        Returns:
            (is_valid, list_of_errors)
        """
        errors = []
        deps = self.check_all_dependencies()

        for nid, result in deps.items():
            if not result.ok:
                if result.missing:
                    errors.append(f"{nid}: 缺少依赖 {', '.join(result.missing)}")
                if result.incompatible:
                    for dep, reason in result.incompatible.items():
                        errors.append(f"{nid}: {dep} 版本不兼容 ({reason})")

        return len(errors) == 0, errors
