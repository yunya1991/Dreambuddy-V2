"""依赖版本审计 — 解析依赖清单文件，检测版本声明。

支持的清单文件：
- pyproject.toml (PEP 621)
- requirements.txt
- package.json (npm)

每条结论带 Evidence（来源 + known_gaps）。
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from .evidence import Evidence


# 依赖版本说明符正则
_SPEC_RE = re.compile(
    r"^([a-zA-Z0-9_-]+)\s*"  # 包名
    r"([<>=!~]=?)?\s*"        # 操作符
    r"([\d.]+[a-zA-Z0-9.*+]*)?"  # 版本号
)


def audit_dependencies(target: str) -> dict[str, Any]:
    """审计目标目录的依赖版本声明。

    Args:
        target: 目录路径

    Returns:
        {
            "declared": [{name, operator, version, source}],
            "manifests_found": [文件列表],
            "summary": str,
            "evidence": [Evidence],
        }
    """
    result: dict[str, Any] = {
        "declared": [],
        "manifests_found": [],
        "summary": "",
        "evidence": [],
    }

    if not os.path.isdir(target):
        result["evidence"].append(Evidence(
            result=f"目标不是目录: {target}",
            provenance={"target": target},
            confidence=1.0,
            known_gaps=["无法审计非目录路径"],
            level="observation",
        ))
        return result

    # 查找依赖清单文件
    manifests: list[str] = []
    pyproject = os.path.join(target, "pyproject.toml")
    requirements = os.path.join(target, "requirements.txt")
    package_json = os.path.join(target, "package.json")

    if os.path.isfile(pyproject):
        manifests.append(pyproject)
        deps = _parse_pyproject(pyproject)
        result["declared"].extend(deps)

    if os.path.isfile(requirements):
        manifests.append(requirements)
        deps = _parse_requirements(requirements)
        result["declared"].extend(deps)

    if os.path.isfile(package_json):
        manifests.append(package_json)
        deps = _parse_package_json(package_json)
        result["declared"].extend(deps)

    result["manifests_found"] = manifests

    result["summary"] = (
        f"依赖审计: {len(manifests)} 个清单文件, "
        f"{len(result['declared'])} 个声明依赖"
    )

    result["evidence"] = _build_evidence(
        result["declared"], manifests, target,
    )

    return result


# ---------------------------------------------------------------------------
# 解析器
# ---------------------------------------------------------------------------

def _parse_pyproject(path: str) -> list[dict[str, str]]:
    """解析 pyproject.toml 中的 [project.dependencies]。

    使用 tomllib (Python 3.11+) 或回退到正则解析。
    """
    deps: list[dict[str, str]] = []
    try:
        import tomllib
        with open(path, "rb") as f:
            data = tomllib.load(f)
        project = data.get("project", {})
        for spec in project.get("dependencies", []):
            parsed = _parse_version_spec(spec)
            if parsed:
                parsed["source"] = "pyproject.toml"
                deps.append(parsed)
        return deps
    except ImportError:
        pass

    # 回退：正则解析
    try:
        content = _read_file(path)
    except Exception:
        return deps

    in_deps = False
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("dependencies") and "[" in line:
            in_deps = True
            continue
        if in_deps:
            if "]" in line:
                in_deps = False
                continue
            # 提取引号内的内容
            match = re.search(r'["\']([^"\']+)["\']', line)
            if match:
                parsed = _parse_version_spec(match.group(1))
                if parsed:
                    parsed["source"] = "pyproject.toml"
                    deps.append(parsed)

    return deps


def _parse_requirements(path: str) -> list[dict[str, str]]:
    """解析 requirements.txt。"""
    deps: list[dict[str, str]] = []
    try:
        content = _read_file(path)
    except Exception:
        return deps

    for line in content.split("\n"):
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        parsed = _parse_version_spec(line)
        if parsed:
            parsed["source"] = "requirements.txt"
            deps.append(parsed)

    return deps


def _parse_package_json(path: str) -> list[dict[str, str]]:
    """解析 package.json 的 dependencies + devDependencies。"""
    deps: list[dict[str, str]] = []
    try:
        content = _read_file(path)
        data = json.loads(content)
    except Exception:
        return deps

    for section in ("dependencies", "devDependencies"):
        section_deps = data.get(section, {})
        if isinstance(section_deps, dict):
            for name, version in section_deps.items():
                deps.append({
                    "name": name,
                    "operator": _extract_operator(str(version)),
                    "version": _clean_version(str(version)),
                    "source": f"package.json[{section}]",
                })

    return deps


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _parse_version_spec(spec: str) -> dict[str, str] | None:
    """解析版本说明符（如 'requests>=2.28.0'）。"""
    # 去掉 extras: package[extra]>=1.0
    spec = spec.split("[")[0].strip()
    match = _SPEC_RE.match(spec)
    if not match:
        return None
    name, op, ver = match.groups()
    if not name:
        return None
    return {
        "name": name,
        "operator": op or "",
        "version": ver or "",
    }


def _extract_operator(version: str) -> str:
    """从 npm 版本号提取操作符。"""
    if version.startswith("^"):
        return "^"
    if version.startswith("~"):
        return "~"
    if version.startswith(">="):
        return ">="
    if version.startswith("=="):
        return "=="
    return ""


def _clean_version(version: str) -> str:
    """清理 npm 版本号前缀。"""
    return version.lstrip("^~>=<" )


def _read_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _build_evidence(
    declared: list[dict],
    manifests: list[str],
    target: str,
) -> list[Evidence]:
    evidence: list[Evidence] = []

    evidence.append(Evidence(
        result=f"找到 {len(manifests)} 个依赖清单文件",
        provenance={"target": target, "manifests": manifests},
        confidence=1.0,
        known_gaps=[
            "未解析 lock 文件（poetry.lock/package-lock.json），无法对比声明版本与锁定版本",
            "setup.py 中的动态依赖未解析",
            "可选依赖 (extras) 未完全展开",
        ],
        level="observation",
    ))

    if declared:
        evidence.append(Evidence(
            result=f"声明 {len(declared)} 个依赖",
            provenance={"target": target, "analysis": "dependency_audit"},
            confidence=0.9,
            known_gaps=[
                "版本约束语义不同：>= vs ~= vs ^ 不等价",
                "传递依赖未解析（只审计直接声明）",
            ],
            level="derivation",
        ))

    return evidence
