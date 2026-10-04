"""Skill Lifecycle Writer — 把生命周期状态实际写回 SKILL.md frontmatter。

解决 skill_indexer.lifecycle_transition 只校验不写回的缺口（P0）。
FAIL-OPEN：异常时返回 ok=False，不修改文件。

工程约束：HC-1a（独立模块）/ FAIL-OPEN / 零回归
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from skill_indexer import lifecycle_transition

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


def _parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """解析 frontmatter，返回 (data_dict, body_text)。"""
    m = _FRONTMATTER_RE.match(content)
    if not m:
        return {}, content
    fm_str = m.group(1)
    body = content[m.end():]
    data: dict[str, Any] = {}
    for line in fm_str.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            if val.startswith("[") and val.endswith("]"):
                # 检查是否为 JSON 格式的 list-of-dict
                if "{" in val:
                    try:
                        data[key] = json.loads(val)
                    except json.JSONDecodeError:
                        items = [v.strip().strip("'\"") for v in val[1:-1].split(",") if v.strip()]
                        data[key] = items
                else:
                    items = [v.strip().strip("'\"") for v in val[1:-1].split(",") if v.strip()]
                    data[key] = items
            elif val.lower() == "true":
                data[key] = True
            elif val.lower() == "false":
                data[key] = False
            elif val in ("null", "~", ""):
                data[key] = None
            else:
                data[key] = val.strip("'\"")
    return data, body


def _serialize_frontmatter(data: dict[str, Any]) -> str:
    """把 dict 序列化回 YAML frontmatter 字符串。"""
    lines: list[str] = []
    for key, val in data.items():
        if isinstance(val, list):
            if val and isinstance(val[0], dict):
                # list-of-dict：用 JSON 序列化（可被 yaml.safe_load 解析）
                lines.append(f"{key}: {json.dumps(val, ensure_ascii=False)}")
            else:
                items = ", ".join(str(v) for v in val)
                lines.append(f"{key}: [{items}]")
        elif val is None:
            lines.append(f"{key}: null")
        elif isinstance(val, bool):
            lines.append(f"{key}: {'true' if val else 'false'}")
        else:
            lines.append(f"{key}: {val}")
    return "\n".join(lines)


def write_lifecycle(
    skill_dir: Path,
    target_status: str,
    evidence: list[str] | None = None,
) -> dict[str, Any]:
    """把 SKILL 的 status 写回 frontmatter，并追加 evidence 到 cognitive_links。

    Args:
        skill_dir: SKILL 目录（含 SKILL.md）
        target_status: 目标状态
        evidence: 认知记忆 VM-id 列表，追加到 cognitive_links

    Returns:
        {ok, from, to, written, path?, error?}
    """
    evidence = evidence or []
    skill_file = Path(skill_dir) / "SKILL.md"
    if not skill_file.exists():
        return {"ok": False, "error": "SKILL.md not found", "written": False}

    try:
        content = skill_file.read_text(encoding="utf-8")
        data, body = _parse_frontmatter(content)
        current_status = data.get("status", "active")

        # 校验转换合法性（复用 skill_indexer 的状态机）
        trans = lifecycle_transition(current_status, target_status, evidence)
        if not trans["ok"]:
            return {
                "ok": False,
                "from": current_status,
                "to": target_status,
                "written": False,
                "error": trans.get("error", "invalid transition"),
            }

        # 更新字段
        data["status"] = target_status
        data["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if evidence:
            existing = data.get("cognitive_links")
            if not isinstance(existing, list):
                existing = []
            merged = list(dict.fromkeys(existing + evidence))  # 去重保序
            data["cognitive_links"] = merged

        # FR-E2: 自动追加 evolution_log 条目
        evo_log = data.get("evolution_log")
        if not isinstance(evo_log, list):
            evo_log = []
        evo_log.append({
            "change_summary": f"status: {current_status}→{target_status}",
            "source_memory_ids": evidence,
            "changed_by": "human",
            "changed_at": datetime.now(timezone.utc).isoformat(),
        })
        data["evolution_log"] = evo_log

        # 写回
        new_fm = _serialize_frontmatter(data)
        sep = "" if body.startswith("\n") else "\n"
        new_content = f"---\n{new_fm}\n---{sep}{body}"
        skill_file.write_text(new_content, encoding="utf-8")

        return {
            "ok": True,
            "from": current_status,
            "to": target_status,
            "written": True,
            "path": str(skill_file),
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "written": False}


def add_cognitive_link(skill_dir: Path, memory_id: str) -> dict[str, Any]:
    """把一个 VM-id 追加到 SKILL.md 的 cognitive_links（不改 status）。"""
    return _add_link_only(skill_dir, memory_id)


def increment_apply_count(skill_dir: Path) -> dict[str, Any]:
    """apply_count += 1（由 record_hook 调用）。FAIL-OPEN。"""
    skill_file = Path(skill_dir) / "SKILL.md"
    if not skill_file.exists():
        return {"ok": False, "error": "SKILL.md not found"}
    try:
        content = skill_file.read_text(encoding="utf-8")
        data, body = _parse_frontmatter(content)
        current = _safe_int(data.get("apply_count"), 0)
        data["apply_count"] = current + 1
        data["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        new_fm = _serialize_frontmatter(data)
        sep = "" if body.startswith("\n") else "\n"
        skill_file.write_text(f"---\n{new_fm}\n---{sep}{body}", encoding="utf-8")
        return {"ok": True, "apply_count": data["apply_count"], "written": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def update_confidence(skill_dir: Path, success: bool) -> dict[str, Any]:
    """按贝叶斯规则更新 confidence + last_verified（由 verify_hook 调用）。

    success=True: confidence = min(1.0, confidence + (1 - confidence) * 0.3)
    success=False: confidence = max(0.0, confidence * 0.7)
    """
    skill_file = Path(skill_dir) / "SKILL.md"
    if not skill_file.exists():
        return {"ok": False, "error": "SKILL.md not found"}
    try:
        content = skill_file.read_text(encoding="utf-8")
        data, body = _parse_frontmatter(content)
        current = _safe_float(data.get("confidence"), 0.3)
        if success:
            new_conf = min(1.0, current + (1.0 - current) * 0.3)
        else:
            new_conf = max(0.0, current * 0.7)
        data["confidence"] = round(new_conf, 4)
        data["last_verified"] = datetime.now(timezone.utc).isoformat()
        data["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        new_fm = _serialize_frontmatter(data)
        sep = "" if body.startswith("\n") else "\n"
        skill_file.write_text(f"---\n{new_fm}\n---{sep}{body}", encoding="utf-8")
        return {"ok": True, "confidence": data["confidence"], "written": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _safe_int(value: Any, default: int) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _add_link_only(skill_dir: Path, memory_id: str) -> dict[str, Any]:
    skill_file = Path(skill_dir) / "SKILL.md"
    if not skill_file.exists():
        return {"ok": False, "error": "SKILL.md not found"}
    try:
        content = skill_file.read_text(encoding="utf-8")
        data, body = _parse_frontmatter(content)
        existing = data.get("cognitive_links")
        if not isinstance(existing, list):
            existing = []
        if memory_id not in existing:
            existing.append(memory_id)
            data["cognitive_links"] = existing
            data["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            new_fm = _serialize_frontmatter(data)
            sep = "" if body.startswith("\n") else "\n"
            skill_file.write_text(f"---\n{new_fm}\n---{sep}{body}", encoding="utf-8")
        return {"ok": True, "memory_id": memory_id, "written": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Task 8: 演化归因 ──────────────────────────────────────────

def log_evolution_change(
    skill_dir: Path,
    change_summary: str,
    changed_by: str = "human",
    source_memory_ids: list[str] | None = None,
) -> dict[str, Any]:
    """记录 Skill 演化变更归因（JSON Lines 日志）。

    Args:
        skill_dir: Skill 目录路径
        change_summary: 变更摘要（不超过 200 字）
        changed_by: 变更来源（human/hermes/dreaming）
        source_memory_ids: 触发变更的记忆 ID 列表

    Returns:
        {"ok": bool, "log_file": str, "entry": dict}
    """
    if changed_by not in ("human", "hermes", "dreaming"):
        changed_by = "human"
    skill_file = Path(skill_dir) / "SKILL.md"
    if not skill_file.exists():
        return {"ok": False, "error": "SKILL.md not found"}

    log_dir = Path(skill_dir)
    log_file = log_dir / "evolution_log.jsonl"

    try:
        content = skill_file.read_text(encoding="utf-8")
        data, _ = _parse_frontmatter(content)
        skill_name = data.get("name", Path(skill_dir).name)
        current_version = data.get("version", "unknown")
        current_confidence = _safe_float(data.get("confidence"), 0.3)
        current_apply_count = _safe_int(data.get("apply_count"), 0)

        entry = {
            "skill_name": skill_name,
            "changed_at": datetime.now(timezone.utc).isoformat(),
            "changed_by": changed_by,
            "change_summary": change_summary[:200],
            "source_memory_ids": source_memory_ids or [],
            "version_after": current_version,
            "confidence_after": current_confidence,
            "apply_count_after": current_apply_count,
        }
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return {"ok": True, "log_file": str(log_file), "entry": entry}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── FR-R1: 记录 execution_history ───────────────────────────────

def record_execution(skill_dir: Path, success: bool, duration: float) -> dict[str, Any]:
    """追加一次执行记录到 SKILL.md 的 execution_history（保留最近 20 条）。

    Args:
        skill_dir: Skill 目录路径
        success: 本次执行是否成功
        duration: 执行耗时（秒）

    Returns:
        {"ok": bool, "execution_history": list}
    """
    skill_file = Path(skill_dir) / "SKILL.md"
    if not skill_file.exists():
        return {"ok": False, "error": "SKILL.md not found"}
    try:
        content = skill_file.read_text(encoding="utf-8")
        data, body = _parse_frontmatter(content)
        history = data.get("execution_history")
        if not isinstance(history, list):
            history = []
        history.append({
            "success": success,
            "duration": round(duration, 4),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        # 保留最近 20 条
        history = history[-20:]
        data["execution_history"] = history
        new_fm = _serialize_frontmatter(data)
        sep = "" if body.startswith("\n") else "\n"
        skill_file.write_text(f"---\n{new_fm}\n---{sep}{body}", encoding="utf-8")
        return {"ok": True, "execution_history": history}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── FR-E3: 查询进化历史 ─────────────────────────────────────────

def query_evolution_history(skill_dir: Path) -> dict[str, Any]:
    """查询 Skill 的完整进化历史（evolution_log + evolution_log.jsonl）。

    合并 SKILL.md frontmatter 中的 evolution_log 和外部 JSONL 日志。

    Args:
        skill_dir: Skill 目录路径

    Returns:
        {"skill_name": str, "evolution_log": list, "jsonl_entries": list}
    """
    skill_file = Path(skill_dir) / "SKILL.md"
    jsonl_file = Path(skill_dir) / "evolution_log.jsonl"
    result: dict[str, Any] = {
        "skill_name": Path(skill_dir).name,
        "evolution_log": [],
        "jsonl_entries": [],
    }

    # 从 frontmatter 读取
    if skill_file.exists():
        try:
            content = skill_file.read_text(encoding="utf-8")
            data, _ = _parse_frontmatter(content)
            fm_log = data.get("evolution_log")
            if isinstance(fm_log, list):
                result["skill_name"] = data.get("name", result["skill_name"])
                result["evolution_log"] = fm_log
        except Exception:
            pass

    # 从 JSONL 读取
    if jsonl_file.exists():
        try:
            for line in jsonl_file.read_text(encoding="utf-8").strip().split("\n"):
                line = line.strip()
                if line:
                    result["jsonl_entries"].append(json.loads(line))
        except Exception:
            pass

    return result


# ── FR-E2: 自动追加 evolution_log ───────────────────────────────

def append_evolution_log_to_frontmatter(skill_dir: Path, change_summary: str,
                                        changed_by: str = "human",
                                        source_memory_ids: list[str] | None = None) -> dict[str, Any]:
    """向 SKILL.md frontmatter 的 evolution_log 字段追加一条变更记录。

    与 log_evolution_change() 的区别：此函数写入 frontmatter 内嵌字段，
    log_evolution_change() 写入外部 JSONL 文件。两者互补。

    Args:
        skill_dir: Skill 目录路径
        change_summary: 变更摘要
        changed_by: 变更来源（human/hermes/dreaming）
        source_memory_ids: 来源记忆 ID 列表

    Returns:
        {"ok": bool, "evolution_log": list}
    """
    skill_file = Path(skill_dir) / "SKILL.md"
    if not skill_file.exists():
        return {"ok": False, "error": "SKILL.md not found"}
    try:
        content = skill_file.read_text(encoding="utf-8")
        data, body = _parse_frontmatter(content)
        evo_log = data.get("evolution_log")
        if not isinstance(evo_log, list):
            evo_log = []
        evo_log.append({
            "change_summary": change_summary[:200],
            "source_memory_ids": source_memory_ids or [],
            "changed_by": changed_by if changed_by in ("human", "hermes", "dreaming") else "human",
            "changed_at": datetime.now(timezone.utc).isoformat(),
        })
        data["evolution_log"] = evo_log
        new_fm = _serialize_frontmatter(data)
        sep = "" if body.startswith("\n") else "\n"
        skill_file.write_text(f"---\n{new_fm}\n---{sep}{body}", encoding="utf-8")
        return {"ok": True, "evolution_log": evo_log}
    except Exception as e:
        return {"ok": False, "error": str(e)}
