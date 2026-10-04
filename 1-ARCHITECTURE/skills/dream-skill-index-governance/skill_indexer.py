"""skill-indexer 构建器 MVP

扫描 SKILL.md frontmatter → 生成 registry.json + dep-graph.json + drift-report.json + conflict-report.json

工程约束：HC-1a（独立模块不改核心）/ HC-9（只产索引信号）/ FAIL-OPEN / 零回归
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - yaml is standard in this repo
    yaml = None  # type: ignore[assignment]

# 认知系统接入（FAIL-OPEN：不可用时 _get_cle_or_none 返回 None）
_COGNITIVE_DIR = Path(__file__).resolve().parents[3] / "4-MEMORY" / "9-工具与接口"
_HAS_COGNITIVE = False
if _COGNITIVE_DIR.exists() and str(_COGNITIVE_DIR) not in sys.path:
    sys.path.insert(0, str(_COGNITIVE_DIR))
try:
    from cognitive_loop_entry import get_cle  # type: ignore[import-not-found]
    _HAS_COGNITIVE = True
except Exception:
    _HAS_COGNITIVE = False

SCHEMA_VERSION = "1.0"

# 可选字段默认值
_DEFAULT_STATUS = "active"
_DEFAULT_CATEGORY = "uncategorized"
_VALID_STATUSES = {"proposed", "shadow", "active", "deprecated", "archived"}

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

# 项目自有 SKILL 根目录（排除第三方：币安Skill/binance-skills-hub-main）
_REPO_ROOT = Path(__file__).resolve().parents[3]
ALL_SKILL_ROOTS: list[Path] = [
    _REPO_ROOT / ".trae" / "skills",
    _REPO_ROOT / "1-ARCHITECTURE" / "skills",
    _REPO_ROOT / "6-TRADING" / "skills",
    _REPO_ROOT / "11-易经推理系统" / "skills" / "0-CORE",
    _REPO_ROOT / "11-易经推理系统" / "skills" / "1-TRADE",
    _REPO_ROOT / "11-易经推理系统" / "skills" / "2-INTELLIGENCE",
    _REPO_ROOT / "11-易经推理系统" / "skills" / "3-SUPPORT",
    _REPO_ROOT / "11-易经推理系统" / "skills" / "4-GENERIC",
    _REPO_ROOT / "4-MEMORY" / "0-元记忆" / "superpowers" / "skills",
    _REPO_ROOT / "4-MEMORY" / "0-元记忆" / "trading-cognition" / "skills",
    _REPO_ROOT / "deploy" / "hermes" / "skills" / "trading",
    _REPO_ROOT / "experiments" / "ab-trading" / "skills",
    _REPO_ROOT / "AGENT协作工具" / "SKILLS",
    _REPO_ROOT / "24-图结构上下文压缩" / "skills",
]


@dataclass(frozen=True)
class SkillEntry:
    """单个 SKILL 的解析结果。"""
    name: str
    description: str = ""
    version: str = "0.0.0"
    path: Path = Path()
    location_role: str = "unknown"  # trae-entry | project-index | unknown
    status: str = _DEFAULT_STATUS
    category: str = _DEFAULT_CATEGORY
    triggers: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    provides: list[str] = field(default_factory=list)
    cognitive_links: list[str] = field(default_factory=list)
    content_hash: str = ""
    parse_error: str | None = None
    override_fields: dict | None = None
    facets: dict[str, str] = field(default_factory=dict)
    # P0-2 量化进化字段（默认值保证向后兼容）
    confidence: float = 0.3
    apply_count: int = 0
    last_verified: str | None = None
    # P2 回归检测：最近 20 次执行记录 {success, duration, timestamp}
    execution_history: list[dict] = field(default_factory=list)
    # P2 进化归因：变更日志 {change_summary, source_memory_ids, changed_by, changed_at}
    evolution_log: list[dict] = field(default_factory=list)


# ─────────────────────────────── scan_skills ───────────────────────────────

def _infer_location_role(path: Path) -> str:
    s = str(path)
    if ".trae" in s and "skills" in s:
        return "trae-entry"
    if "1-ARCHITECTURE" in s and "skills" in s:
        return "project-index"
    return "unknown"


def _parse_frontmatter(text: str) -> dict[str, Any] | None:
    """提取并解析 YAML frontmatter，失败返回 None。"""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None
    if yaml is None:
        return None
    try:
        data = yaml.safe_load(m.group(1))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v) for v in value]
    return []


def _safe_float(value: Any, default: float) -> float:
    """安全转换为 float，失败返回 default。"""
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int) -> int:
    """安全转换为 int，失败返回 default。"""
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_execution_history(raw: Any) -> list[dict]:
    """解析 execution_history 字段（list of dict）。FAIL-OPEN。"""
    if not raw or not isinstance(raw, list):
        return []
    result: list[dict] = []
    for item in raw[-20:]:  # 最多保留 20 条
        if isinstance(item, dict):
            result.append({
                "success": bool(item.get("success", False)),
                "duration": _safe_float(item.get("duration"), 0.0),
                "timestamp": str(item.get("timestamp", "")),
            })
    return result


def _parse_evolution_log(raw: Any) -> list[dict]:
    """解析 evolution_log 字段（list of dict）。FAIL-OPEN。"""
    if not raw or not isinstance(raw, list):
        return []
    result: list[dict] = []
    for item in raw:
        if isinstance(item, dict):
            result.append({
                "change_summary": str(item.get("change_summary", "")),
                "source_memory_ids": item.get("source_memory_ids", []) if isinstance(item.get("source_memory_ids"), list) else [],
                "changed_by": str(item.get("changed_by", "human")),
                "changed_at": str(item.get("changed_at", "")),
            })
    return result


def scan_skills(root_paths: list[Path]) -> list[SkillEntry]:
    """扫描 root_paths 下所有 SKILL.md 并解析 frontmatter。FAIL-OPEN。"""
    entries: list[SkillEntry] = []
    for root in root_paths:
        try:
            skill_files = list(Path(root).rglob("SKILL.md"))
        except Exception:
            continue  # FAIL-OPEN：单路径扫描失败不阻塞其他
        for sf in skill_files:
            entries.append(_parse_one(sf))
    return entries


def _load_override(skill_dir: Path) -> dict[str, Any] | None:
    """读取 skill.override.yaml，失败返回 None（FAIL-OPEN）。"""
    override_path = skill_dir / "skill.override.yaml"
    if not override_path.exists():
        return None
    if yaml is None:
        return None
    try:
        data = yaml.safe_load(override_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _parse_one(skill_md: Path) -> SkillEntry:
    name = skill_md.parent.name
    override = _load_override(skill_md.parent)
    content_hash = ""
    try:
        raw = skill_md.read_text(encoding="utf-8")
    except Exception as exc:  # FAIL-OPEN
        return SkillEntry(name=name, path=skill_md, parse_error=f"read_error: {exc}",
                          override_fields=override)

    content_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    fm = _parse_frontmatter(raw)
    if fm is None:
        return SkillEntry(
            name=name,
            path=skill_md,
            location_role=_infer_location_role(skill_md),
            content_hash=content_hash,
            parse_error="no_frontmatter_or_invalid_yaml",
            override_fields=override,
        )

    raw_name = fm.get("name")
    parsed_name = str(raw_name) if raw_name else name
    status = str(fm.get("status", _DEFAULT_STATUS))
    if status not in _VALID_STATUSES:
        status = _DEFAULT_STATUS

    category = str(fm.get("category", _DEFAULT_CATEGORY))
    triggers = _as_str_list(fm.get("triggers"))

    # facets：优先用 frontmatter 显式声明，否则从 category/triggers/path 推断
    raw_facets = fm.get("facets")
    if isinstance(raw_facets, dict):
        facets = {k: str(v) for k, v in raw_facets.items()}
    else:
        try:
            from skill_facets import infer_facets
            facets = infer_facets(category=category, triggers=triggers, path=skill_md)
        except Exception:
            facets = {}

    return SkillEntry(
        name=parsed_name,
        description=str(fm.get("description", "")),
        version=str(fm.get("version", "0.0.0")),
        path=skill_md,
        location_role=_infer_location_role(skill_md),
        status=status,
        category=category,
        triggers=triggers,
        depends_on=_as_str_list(fm.get("depends_on")),
        provides=_as_str_list(fm.get("provides")),
        cognitive_links=_as_str_list(fm.get("cognitive_links")),
        content_hash=content_hash,
        parse_error=None,
        override_fields=override,
        facets=facets,
        confidence=_safe_float(fm.get("confidence"), 0.3),
        apply_count=_safe_int(fm.get("apply_count"), 0),
        last_verified=str(fm.get("last_verified")) if fm.get("last_verified") else None,
        execution_history=_parse_execution_history(fm.get("execution_history")),
        evolution_log=_parse_evolution_log(fm.get("evolution_log")),
    )


# ─────────────────────────────── build_registry ───────────────────────────────

def _entry_to_dict(e: SkillEntry) -> dict[str, Any]:
    return {
        "name": e.name,
        "description": e.description,
        "version": e.version,
        "path": str(e.path),
        "location_role": e.location_role,
        "status": e.status,
        "category": e.category,
        "triggers": e.triggers,
        "depends_on": e.depends_on,
        "provides": e.provides,
        "cognitive_links": e.cognitive_links,
        "content_hash": e.content_hash,
        "parse_error": e.parse_error,
        "override_fields": e.override_fields,
        "facets": e.facets,
        "confidence": e.confidence,
        "apply_count": e.apply_count,
        "last_verified": e.last_verified,
        "execution_history": e.execution_history,
        "evolution_log": e.evolution_log,
    }


def build_registry(entries: list[SkillEntry]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "total_count": len(entries),
        "skills": [_entry_to_dict(e) for e in entries],
    }


# ─────────────────────────────── build_dep_graph ───────────────────────────────

def build_dep_graph(entries: list[SkillEntry]) -> dict[str, Any]:
    nodes = [{"id": e.name, "category": e.category, "status": e.status} for e in entries]
    edges: list[dict[str, Any]] = []
    known = {e.name for e in entries}
    for e in entries:
        for dep in e.depends_on:
            edges.append({"from": e.name, "to": dep, "resolved": dep in known})
    return {
        "schema_version": SCHEMA_VERSION,
        "nodes": nodes,
        "edges": edges,
    }


# ─────────────────────────────── detect_drift ───────────────────────────────

def _is_known_skill_root(path: Path) -> bool:
    """判断 SKILL 路径是否在已知 SKILL 根目录下（非双位置也不算漂移）。

    同时支持绝对路径匹配和路径模式匹配（如路径含 "6-TRADING/skills"）。
    """
    try:
        path_str = str(path)
        # 模式匹配：路径包含已知根目录名
        for root in ALL_SKILL_ROOTS:
            root_name = root.name  # 如 "skills"
            root_parent = root.parent.name  # 如 "6-TRADING"
            pattern = f"{root_parent}/{root_name}"
            if pattern in path_str:
                return True
        # 绝对路径匹配
        resolved = path.resolve()
        for root in ALL_SKILL_ROOTS:
            try:
                resolved.relative_to(root.resolve())
                return True
            except (ValueError, OSError):
                continue
    except Exception:
        pass
    return False


def detect_drift(entries: list[SkillEntry]) -> dict[str, Any]:
    """双位置存储漂移检测。

    规则：
    - 双位置（trae-entry + project-index）都有 → 不漂移
    - 只在 trae-entry 或只在 project-index → 漂移（需补双位置）
    - 在已知 SKILL 根目录但 role=unknown（如 6-TRADING/skills）→ 不漂移（注册的非双位置 SKILL）
    """
    by_name: dict[str, dict[str, SkillEntry]] = {}
    for e in entries:
        by_name.setdefault(e.name, {})[e.location_role] = e

    drifted: list[dict[str, Any]] = []
    for name, roles in by_name.items():
        has_trae = "trae-entry" in roles
        has_project = "project-index" in roles
        has_unknown = "unknown" in roles

        # 双位置齐全 → 不漂移
        if has_trae and has_project:
            continue

        # 只有 unknown role 且在已知根目录 → 不漂移（注册的非双位置 SKILL）
        if has_unknown and not has_trae and not has_project:
            unknown_entries = [e for r, e in roles.items() if r == "unknown"]
            if all(_is_known_skill_root(e.path) for e in unknown_entries):
                continue

        # 其余情况 → 漂移
        drifted.append({
            "name": name,
            "present_roles": list(roles.keys()),
            "missing_roles": (["trae-entry"] if not has_trae else [])
                            + (["project-index"] if not has_project else []),
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "total_drifted": len(drifted),
        "drifted": drifted,
    }


# ─────────────────────────────── detect_conflicts ───────────────────────────────

def detect_conflicts(entries: list[SkillEntry]) -> dict[str, Any]:
    """触发词冲突检测：同一 trigger 被多个 SKILL 声明。

    P1 升级：用权威词表排除泛化 trigger（如 "a", "code" 等），
    并对同义词归一化后再检测冲突。
    """
    # 加载权威词表（FAIL-OPEN：不可用时 None）
    thesaurus = None
    try:
        from skill_thesaurus import load_thesaurus, normalize_trigger, is_generic_trigger
        thesaurus = load_thesaurus()
    except Exception:
        thesaurus = None

    trigger_to_skills: dict[str, set[str]] = {}
    for e in entries:
        for t in e.triggers:
            # 排除泛化 trigger
            if thesaurus is not None and is_generic_trigger(t, thesaurus):
                continue
            # 同义词归一化
            norm = normalize_trigger(t, thesaurus) if thesaurus is not None else t
            trigger_to_skills.setdefault(norm, set()).add(e.name)

    conflicts: list[dict[str, Any]] = []
    for trigger, skills in trigger_to_skills.items():
        if len(skills) > 1:
            conflicts.append({"trigger": trigger, "skills": sorted(skills)})
    conflicts.sort(key=lambda c: c["trigger"])
    return {
        "schema_version": SCHEMA_VERSION,
        "total_conflicts": len(conflicts),
        "conflicts": conflicts,
    }


# ─────────────────────────────── build（一键生成） ───────────────────────────────

def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def build(root_paths: list[Path], output_dir: Path) -> dict[str, Any]:
    """一键生成 registry.json + dep-graph.json + drift-report.json + conflict-report.json。FAIL-OPEN。"""
    output_dir = Path(output_dir)
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass  # FAIL-OPEN

    entries = scan_skills(root_paths)
    registry = build_registry(entries)
    dep_graph = build_dep_graph(entries)
    drift = detect_drift(entries)
    conflicts = detect_conflicts(entries)

    try:
        _write_json(output_dir / "registry.json", registry)
        _write_json(output_dir / "dep-graph.json", dep_graph)
        _write_json(output_dir / "drift-report.json", drift)
        _write_json(output_dir / "conflict-report.json", conflicts)
    except Exception:
        pass  # FAIL-OPEN：写入失败不阻塞返回结果

    return {
        "registry": registry,
        "dep_graph": dep_graph,
        "drift": drift,
        "conflicts": conflicts,
    }


# ─────────────────────────────── validate（P2-3） ───────────────────────────────

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def _find_peer_skill(skill_dir: Path) -> Path | None:
    """在对侧位置查找同名 SKILL 目录（双位置漂移检查）。"""
    skill_dir = Path(skill_dir)
    name = skill_dir.name
    s = str(skill_dir)
    # 当前在 .trae/skills → 对侧在 1-ARCHITECTURE/skills
    if ".trae" in s and "skills" in s:
        # 向上找到 .trae 的父目录（项目根）
        parts = skill_dir.parts
        try:
            idx = parts.index(".trae")
        except ValueError:
            return None
        project_root = Path(*parts[:idx])
        peer = project_root / "1-ARCHITECTURE" / "skills" / name / "SKILL.md"
        if peer.exists():
            return peer
        return None
    # 当前在 1-ARCHITECTURE/skills → 对侧在 .trae/skills
    if "1-ARCHITECTURE" in s and "skills" in s:
        parts = skill_dir.parts
        try:
            idx = parts.index("1-ARCHITECTURE")
        except ValueError:
            return None
        project_root = Path(*parts[:idx])
        peer = project_root / ".trae" / "skills" / name / "SKILL.md"
        if peer.exists():
            return peer
        return None
    return None


def validate(skill_dir: Path | str) -> dict[str, Any]:
    """校验单个 SKILL 目录。FAIL-OPEN：异常 → valid=True。

    返回 {"valid": bool, "errors": list[str], "warnings": list[str]}
    """
    errors: list[str] = []
    warnings: list[str] = []
    try:
        skill_dir = Path(skill_dir)
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            errors.append("missing SKILL.md")
            return {"valid": not errors, "errors": errors, "warnings": warnings}

        raw = skill_md.read_text(encoding="utf-8")
        fm = _parse_frontmatter(raw)
        if fm is None:
            errors.append("missing or invalid frontmatter")
            return {"valid": not errors, "errors": errors, "warnings": warnings}

        # 必填字段：name / description / version
        for field_name in ("name", "description", "version"):
            val = fm.get(field_name)
            if val is None or (isinstance(val, str) and val.strip() == ""):
                errors.append(f"missing required field: {field_name}")

        # status 校验（缺失不报错）
        status = fm.get("status")
        if status is not None and str(status) not in _VALID_STATUSES:
            errors.append(f"invalid status: {status} (must be one of {sorted(_VALID_STATUSES)})")

        # triggers 非空（如果存在）
        triggers = fm.get("triggers")
        if triggers is not None:
            tlist = _as_str_list(triggers)
            if not tlist:
                errors.append("triggers field present but empty")

        # version SemVer（不合法给 warning）
        version = fm.get("version")
        if version is not None and not _SEMVER_RE.match(str(version)):
            warnings.append(f"version '{version}' is not valid SemVer (X.Y.Z)")

        # 双位置漂移检查
        peer = _find_peer_skill(skill_dir)
        if peer is None:
            s = str(skill_dir)
            if (".trae" in s and "skills" in s) or ("1-ARCHITECTURE" in s and "skills" in s):
                warnings.append(f"drift: no peer skill found in the other location for '{skill_dir.name}'")

        return {"valid": not errors, "errors": errors, "warnings": warnings}
    except Exception:
        # FAIL-OPEN：异常 → valid=True
        return {"valid": True, "errors": errors, "warnings": warnings}


# ─────────────────────────────── P3-1 生命周期状态机 ───────────────────────────────

_LIFECYCLE_TRANSITIONS: dict[str, set[str]] = {
    "proposed": {"shadow", "archived"},
    "shadow": {"active", "archived"},
    "active": {"deprecated", "archived"},
    "deprecated": {"archived"},
    "archived": {"archived"},
}


def lifecycle_transition(current: str, target: str, evidence: list[str]) -> dict[str, Any]:
    """5 阶段生命周期状态机转换校验。

    合法转换：proposed→shadow, shadow→active, active→deprecated,
    deprecated→archived，以及任意状态→archived（强制归档）。
    """
    try:
        allowed = _LIFECYCLE_TRANSITIONS.get(current, set())
        if target not in allowed:
            return {"ok": False, "error": f"illegal transition: {current} → {target}"}
        return {"ok": True, "from": current, "to": target, "evidence": evidence}
    except Exception:
        return {"ok": False, "error": "lifecycle_transition internal error"}


# ─────────────────────────────── P3-2 认知 hooks ───────────────────────────────

def _match_score(context: str, e: SkillEntry) -> int:
    """匹配度 = triggers 命中数 + name 子串命中 + category 命中。"""
    score = 0
    ctx = context.lower()
    for t in e.triggers:
        if t and t.lower() in ctx:
            score += 1
    if e.name and e.name.lower() in ctx:
        score += 1
    if e.category and e.category.lower() in ctx:
        score += 1
    return score


def recall_hook(context: str, entries: list[SkillEntry]) -> list[dict[str, Any]]:
    """基于 context 关键词匹配 SKILL，返回 top 5 候选（按匹配度降序）。"""
    try:
        scored = [(_match_score(context, e), e) for e in entries]
        scored = [(s, e) for s, e in scored if s > 0]
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:5]
        return [
            {
                "name": e.name,
                "description": e.description,
                "category": e.category,
                "triggers": e.triggers,
                "status": e.status,
                "match_score": s,
            }
            for s, e in top
        ]
    except Exception:
        return []


def _get_cle_or_none():
    """获取认知系统 CognitiveLoopEntry 单例，不可用时返回 None（FAIL-OPEN）。"""
    if not _HAS_COGNITIVE:
        return None
    try:
        return get_cle()
    except Exception:
        return None


def record_hook(
    skill_id: str,
    memory_id: str,
    skill_dir: Path | None = None,
) -> dict[str, Any]:
    """建立 skill ↔ memory 双向关联 + apply_count += 1。

    此 hook 由认知系统 record 流程调用，认知记录已完成，
    此处仅将 memory_id 写入 SKILL.md cognitive_links 并递增 apply_count，
    **不重复 record**。FAIL-OPEN：写入失败静默降级。

    Args:
        skill_id: SKILL 名称
        memory_id: 认知记忆 VM-id（已由认知系统生成）
        skill_dir: SKILL 目录（可选，提供则写入 cognitive_links + apply_count）
    """
    written = False
    apply_count_incremented = False
    if skill_dir is not None:
        try:
            from skill_lifecycle_writer import _add_link_only, increment_apply_count
            r = _add_link_only(skill_dir, memory_id)
            written = r.get("ok", False)
            inc = increment_apply_count(skill_dir)
            apply_count_incremented = inc.get("ok", False)
        except Exception:
            written = False

    return {
        "skill_id": skill_id,
        "memory_id": memory_id,
        "linked": True,
        "written": written,
        "apply_count_incremented": apply_count_incremented,
    }


def verify_hook(
    skill_id: str,
    success: bool,
    entries: list[SkillEntry],
    skill_dir: Path | None = None,
) -> dict[str, Any]:
    """verify 后更新 confidence + 执行 lifecycle 升级。

    此 hook 由认知系统 verify 流程调用，verify 已完成，
    此处：
      1. 按贝叶斯规则更新 confidence + last_verified
      2. shadow+success 且 confidence>=0.6 且 apply_count>=1 时写回 active
    **不重复 verify**。FAIL-OPEN：写入失败静默降级。

    Args:
        skill_id: SKILL 名称
        success: 校验是否通过
        entries: SKILL 列表（用于查当前 status/confidence/apply_count）
        skill_dir: SKILL 目录（可选，提供则执行写回）
    """
    suggested: str | None = None
    lifecycle_written = False
    confidence_updated = False
    entry = next((e for e in entries if e.name == skill_id), None)

    # 1. 更新 confidence + last_verified（无论 success 与否）
    if skill_dir is not None:
        try:
            from skill_lifecycle_writer import update_confidence
            r = update_confidence(skill_dir, success)
            confidence_updated = r.get("ok", False)
        except Exception:
            confidence_updated = False

    # 2. shadow→active 升级：需 confidence>=0.6 且 apply_count>=1
    if success and entry and entry.status == "shadow":
        meets_confidence = entry.confidence >= 0.6
        meets_apply_count = entry.apply_count >= 1
        if meets_confidence and meets_apply_count:
            suggested = "shadow→active"
            if skill_dir is not None:
                try:
                    from skill_lifecycle_writer import write_lifecycle
                    r = write_lifecycle(skill_dir, "active", evidence=["verify-success"])
                    lifecycle_written = r.get("written", False)
                except Exception:
                    lifecycle_written = False
        else:
            suggested = (
                f"shadow→active pending: confidence={entry.confidence} "
                f"(need >=0.6), apply_count={entry.apply_count} (need >=1)"
            )

    return {
        "skill_id": skill_id,
        "success": success,
        "confidence_updated": confidence_updated,
        "suggested_transition": suggested,
        "lifecycle_written": lifecycle_written,
    }


def _compute_baseline(history: list[dict], window: int = 10) -> dict[str, float] | None:
    """计算最近 N 次执行的 baseline（成功率均值 + 耗时均值）。

    Args:
        history: execution_history 列表
        window: 计算窗口（默认最近 10 次）

    Returns:
        {"success_rate": float, "avg_duration": float, "sample_count": int}
        或 None（历史不足 3 条）
    """
    if len(history) < 3:
        return None
    recent = history[-window:]
    success_count = sum(1 for h in recent if h.get("success", False))
    durations = [h.get("duration", 0.0) for h in recent if h.get("duration", 0) > 0]
    return {
        "success_rate": success_count / len(recent),
        "avg_duration": sum(durations) / len(durations) if durations else 0.0,
        "sample_count": len(recent),
    }


def detect_regression(entries: list[SkillEntry]) -> list[dict[str, Any]]:
    """Task 7: 检测 Skill 回归。

    基于 execution_history 计算 baseline vs current 对比：
    - 成功率下降 > 15% → 告警
    - 耗时上升 > 50% → 告警
    - 告警后建议降级为 shadow

    无 execution_history 时回退到 confidence+apply_count 阈值检测。

    Args:
        entries: SKILL 列表

    Returns:
        回归告警列表，每项含 skill_id/baseline/current/reason/suggested_action
    """
    regressions: list[dict[str, Any]] = []

    for e in entries:
        history = e.execution_history

        if len(history) >= 6:
            # 有足够历史：baseline（前半） vs current（后半）
            mid = len(history) // 2
            baseline = _compute_baseline(history[:mid])
            current = _compute_baseline(history[-mid:])

            if baseline and current:
                alerts: list[str] = []
                # 成功率下降 > 15%
                if baseline["success_rate"] > 0 and current["success_rate"] < baseline["success_rate"] - 0.15:
                    alerts.append(
                        f"成功率下降 {round((baseline['success_rate'] - current['success_rate']) * 100, 1)}% "
                        f"({round(baseline['success_rate'] * 100, 1)}% → {round(current['success_rate'] * 100, 1)}%)"
                    )
                # 耗时上升 > 50%
                if baseline["avg_duration"] > 0 and current["avg_duration"] > baseline["avg_duration"] * 1.5:
                    alerts.append(
                        f"耗时上升 {round((current['avg_duration'] / baseline['avg_duration'] - 1) * 100, 1)}% "
                        f"({round(baseline['avg_duration'], 2)}s → {round(current['avg_duration'], 2)}s)"
                    )

                if alerts:
                    regressions.append({
                        "skill_id": e.name,
                        "status": e.status,
                        "baseline": baseline,
                        "current": current,
                        "reason": "; ".join(alerts),
                        "suggested_action": "降级为 shadow 并审查 skill 内容",
                    })
        else:
            # 历史不足：回退到 confidence+apply_count 检测
            if e.apply_count >= 3 and e.confidence < 0.3:
                regressions.append({
                    "skill_id": e.name,
                    "confidence": e.confidence,
                    "apply_count": e.apply_count,
                    "status": e.status,
                    "reason": f"apply_count={e.apply_count} 但 confidence={e.confidence}<0.3，可能回归",
                    "suggested_action": "审查 skill 内容或降级为 shadow/deprecated",
                })
            elif e.apply_count >= 5 and e.confidence < 0.5:
                regressions.append({
                    "skill_id": e.name,
                    "confidence": e.confidence,
                    "apply_count": e.apply_count,
                    "status": e.status,
                    "reason": f"apply_count={e.apply_count} 但 confidence={e.confidence}<0.5，需关注",
                    "suggested_action": "增加验证次数或审查 skill 内容",
                })

    return regressions


# ─────────────────────────────── CLI 入口（P2-2） ───────────────────────────────

def _cli_query(roots: list[Path], trigger: str | None, category: str | None, status: str | None) -> None:
    entries = scan_skills(roots)
    matched = []
    for e in entries:
        if trigger is not None and trigger not in e.triggers:
            continue
        if category is not None and e.category != category:
            continue
        if status is not None and e.status != status:
            continue
        matched.append(_entry_to_dict(e))
    print(json.dumps({"schema_version": SCHEMA_VERSION, "count": len(matched), "skills": matched}, ensure_ascii=False))


def _cli_detect_drift(roots: list[Path]) -> None:
    entries = scan_skills(roots)
    print(json.dumps(detect_drift(entries), ensure_ascii=False))


def _cli_detect_conflicts(roots: list[Path]) -> None:
    entries = scan_skills(roots)
    print(json.dumps(detect_conflicts(entries), ensure_ascii=False))


def _cli_validate(skill_dir: Path) -> None:
    print(json.dumps(validate(skill_dir), ensure_ascii=False))


def _cli_lifecycle(skill_dir: Path, transition: str) -> None:
    """读取 SKILL 当前 status，检查转换合法性。"""
    # 从 SKILL.md 读取 status
    status = _DEFAULT_STATUS
    try:
        raw = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        fm = _parse_frontmatter(raw)
        if fm and fm.get("status"):
            status = str(fm.get("status"))
    except Exception:
        pass
    # 解析 transition "X→Y"
    try:
        parts = transition.replace("->", "→").split("→")
        current = parts[0].strip()
        target = parts[1].strip() if len(parts) > 1 else ""
    except Exception:
        current, target = "", ""
    # 若未从 transition 解析出 current，使用 SKILL 当前 status
    if not current:
        current = status
    res = lifecycle_transition(current, target, [f"cli_transition:{transition}"])
    print(json.dumps({"skill_dir": str(skill_dir), "current_status": status, **res}, ensure_ascii=False))


def _cli_recall_hook(context: str, roots: list[Path]) -> None:
    entries = scan_skills(roots)
    print(json.dumps({"schema_version": SCHEMA_VERSION, "candidates": recall_hook(context, entries)}, ensure_ascii=False))


def _cli_record_hook(skill_id: str, memory_id: str) -> None:
    print(json.dumps(record_hook(skill_id, memory_id), ensure_ascii=False))


def _cli_verify_hook(skill_id: str, success: bool, roots: list[Path]) -> None:
    entries = scan_skills(roots)
    print(json.dumps(verify_hook(skill_id, success, entries), ensure_ascii=False))


def _add_roots_args(p: argparse.ArgumentParser) -> None:
    """为需要扫描 SKILL 的子命令统一添加 --roots / --all 参数。"""
    p.add_argument("--roots", nargs="+", type=Path, default=None,
                   help="SKILL 根目录列表（与 --all 二选一）")
    p.add_argument("--all", action="store_true", dest="scan_all",
                   help="扫描所有项目自有 SKILL 目录（ALL_SKILL_ROOTS）")


def _resolve_roots(args: argparse.Namespace) -> list[Path]:
    """根据 --all / --roots 解析扫描路径。"""
    if getattr(args, "scan_all", False):
        return ALL_SKILL_ROOTS
    roots = getattr(args, "roots", None)
    if not roots:
        raise SystemExit("错误：必须指定 --roots 或 --all")
    return roots


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="skill_indexer", description="Skill indexer CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    # build
    p_build = sub.add_parser("build", help="Build registry + reports")
    _add_roots_args(p_build)
    p_build.add_argument("--output", required=True, type=Path)

    # query
    p_query = sub.add_parser("query", help="Query skills")
    _add_roots_args(p_query)
    p_query.add_argument("--trigger", default=None)
    p_query.add_argument("--category", default=None)
    p_query.add_argument("--status", default=None)

    # detect-drift
    p_drift = sub.add_parser("detect-drift", help="Detect location drift")
    _add_roots_args(p_drift)

    # detect-conflicts
    p_conf = sub.add_parser("detect-conflicts", help="Detect trigger conflicts")
    _add_roots_args(p_conf)

    # validate
    p_val = sub.add_parser("validate", help="Validate a single skill dir")
    p_val.add_argument("--skill-dir", required=True, type=Path)

    # lifecycle (P3-1)
    p_lc = sub.add_parser("lifecycle", help="Check lifecycle transition")
    p_lc.add_argument("--skill-dir", required=True, type=Path)
    p_lc.add_argument("--transition", required=True, help="e.g. shadow→active")

    # recall-hook (P3-2)
    p_recall = sub.add_parser("recall-hook", help="Cognitive recall hook")
    p_recall.add_argument("--context", required=True)
    _add_roots_args(p_recall)

    # record-hook (P3-2)
    p_record = sub.add_parser("record-hook", help="Cognitive record hook")
    p_record.add_argument("--skill-id", required=True)
    p_record.add_argument("--memory-id", required=True)

    # verify-hook (P3-2)
    p_verify = sub.add_parser("verify-hook", help="Cognitive verify hook")
    p_verify.add_argument("--skill-id", required=True)
    p_verify.add_argument("--success", required=True, choices=["true", "false"])
    _add_roots_args(p_verify)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        roots = _resolve_roots(args) if args.command in {
            "build", "query", "detect-drift", "detect-conflicts",
            "recall-hook", "verify-hook",
        } else None
        if args.command == "build":
            build(roots, args.output)
        elif args.command == "query":
            _cli_query(roots, args.trigger, args.category, args.status)
        elif args.command == "detect-drift":
            _cli_detect_drift(roots)
        elif args.command == "detect-conflicts":
            _cli_detect_conflicts(roots)
        elif args.command == "validate":
            _cli_validate(args.skill_dir)
        elif args.command == "lifecycle":
            _cli_lifecycle(args.skill_dir, args.transition)
        elif args.command == "recall-hook":
            _cli_recall_hook(args.context, roots)
        elif args.command == "record-hook":
            _cli_record_hook(args.skill_id, args.memory_id)
        elif args.command == "verify-hook":
            _cli_verify_hook(args.skill_id, args.success == "true", roots)
        return 0
    except Exception:
        # FAIL-OPEN
        return 0


if __name__ == "__main__":
    sys.exit(main())
