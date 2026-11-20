"""技能规范检查（cm skill lint）。

只读检查 SKILL.md frontmatter：
- 缺版本号
- 重名
- 触发词重叠
- depends_on 指向不存在的技能（按名称或路径均未找到）
- triggers 不是列表

发现 issues 仍返回退出码 0（与 doctor 一致）；用法错误由 CLI 返回 2。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from . import scanner, store

SCHEMA_VERSION = "1.0"
SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"


def _strip(value: str) -> str:
    return store._strip_quotes(value.strip())


def _parse_frontmatter(text: str) -> dict:
    """解析 frontmatter，支持行内列表与缩进块列表。"""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    meta = {}
    current = None
    for raw in text[3:end].splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- "):
            if current:
                if not isinstance(meta.get(current), list):
                    meta[current] = []
                meta[current].append(_strip(stripped[2:]))
            continue
        if ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        key = key.strip()
        value = value.strip()
        if not value:
            meta[key] = []
            current = key
        else:
            meta[key] = store._parse_scalar(value)
            current = None
    return meta


def _as_list(value) -> list:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [item.strip() for item in value.replace("，", ",").split(",") if item.strip()]
    return []


def _content_digest(path) -> str:
    """SKILL.md 内容摘要，用于识别跨模块的完全重复副本。"""
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return ""


def _collect(root: Path, config: dict) -> list:
    entries = []
    for path in scanner.iter_files(root, config.get("ignore") or []):
        if path.name.lower() != "skill.md":
            continue
        rel_path = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            text = ""
        meta = _parse_frontmatter(text)
        entries.append(
            {
                "path": rel_path,
                "dir_name": path.parent.name,
                "name": str(meta.get("name") or path.parent.name).strip(),
                "version": str(meta.get("version") or "").strip(),
                "triggers": meta.get("triggers"),
                "depends_on": meta.get("depends_on"),
            }
        )
    return entries


def lint(root, config: dict) -> dict:
    root = Path(root).expanduser().resolve()
    entries = _collect(root, config)
    issues = []

    names = {entry["name"] for entry in entries if entry["name"]}
    paths = {entry["path"] for entry in entries}
    dirs = {entry["dir_name"] for entry in entries}

    # 1. 缺版本号 / 触发词非列表
    for entry in entries:
        if not entry["version"]:
            issues.append(
                {
                    "severity": SEVERITY_WARNING,
                    "kind": "missing_version",
                    "skills": [entry["name"]],
                    "detail": "{} 缺少 version 字段".format(entry["path"]),
                }
            )
        triggers = entry["triggers"]
        if triggers is not None and not isinstance(triggers, list):
            issues.append(
                {
                    "severity": SEVERITY_WARNING,
                    "kind": "triggers_not_list",
                    "skills": [entry["name"]],
                    "detail": "{} 的 triggers 应为列表".format(entry["path"]),
                }
            )

    # 2. 重名
    by_name = {}
    for entry in entries:
        by_name.setdefault(entry["name"], []).append(entry["path"])
    for name, grouped in by_name.items():
        if len(grouped) > 1:
            # 跨模块同名且内容完全一致：属于有意保留的双份，不报错。
            if len({_content_digest(root / path) for path in grouped}) == 1:
                continue
            issues.append(
                {
                    "severity": SEVERITY_ERROR,
                    "kind": "duplicate_name",
                    "skills": [name],
                    "detail": "同名技能：{}".format("、".join(sorted(grouped))),
                }
            )

    # 3. 触发词重叠
    normalized = [
        (entry["name"], entry["path"], set(_as_list(entry["triggers"]))) for entry in entries
    ]
    for position, (left_name, left_path, left_triggers) in enumerate(normalized):
        for right_name, right_path, right_triggers in normalized[position + 1 :]:
            overlap = left_triggers & right_triggers
            if overlap:
                issues.append(
                    {
                        "severity": SEVERITY_WARNING,
                        "kind": "trigger_overlap",
                        "skills": sorted([left_name, right_name]),
                        "detail": "触发词重叠：{}（{} 与 {}）".format(
                            "、".join(sorted(overlap)), left_path, right_path
                        ),
                    }
                )

    # 4. depends_on 指向不存在的技能
    for entry in entries:
        for dep in _as_list(entry["depends_on"]):
            if dep in names or dep in paths or dep in dirs:
                continue
            if (root / dep).exists():
                continue
            issues.append(
                {
                    "severity": SEVERITY_ERROR,
                    "kind": "missing_dependency",
                    "skills": [entry["name"]],
                    "detail": "{} 依赖的 {} 不存在（按名称或路径均未找到）".format(
                        entry["path"], dep
                    ),
                }
            )

    summary = {
        "skills": len(entries),
        "error": sum(1 for item in issues if item["severity"] == SEVERITY_ERROR),
        "warning": sum(1 for item in issues if item["severity"] == SEVERITY_WARNING),
        "total": len(issues),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "command": "skill lint",
        "workspace": str(root),
        "mode": config.get("mode", "dev"),
        "issues": issues,
        "summary": summary,
    }
