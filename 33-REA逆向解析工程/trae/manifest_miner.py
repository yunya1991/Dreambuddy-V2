"""Manifest Miner — 解析 Trae 的能力清单（agent/model/skill/plugin/MCP）。

回答的是「声明了什么能力、按什么维度装配」，不回答「运行时是否真的生效」。
声明即 observation；装配语义（如按模型裁剪）为 derivation。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .common import TRAE_HOME, evidence, load_json

MANIFEST_DIR = TRAE_HOME / "builtin/baseline/manifests"
SKILLS_DIR = TRAE_HOME / "skills"
PLUGINS_DIR = TRAE_HOME / "plugins"
MCPS_DIR = TRAE_HOME / "mcps"


def _parse_frontmatter(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return {}
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    meta: dict[str, str] = {}
    for line in text[3:end].splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta


def _user_skills() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not SKILLS_DIR.exists():
        return out
    for d in sorted(SKILLS_DIR.iterdir()):
        skill_md = d / "SKILL.md"
        if not d.is_dir() or not skill_md.exists():
            continue
        meta = _parse_frontmatter(skill_md)
        out.append(
            {
                "name": d.name,
                "path": str(skill_md),
                "frontmatter_name": meta.get("name", d.name),
                "description": meta.get("description", "")[:200],
            }
        )
    return out


def _plugins() -> list[dict[str, Any]]:
    data = load_json(TRAE_HOME / "installed-plugins.json", {}) or {}
    plugins: list[dict[str, Any]] = []
    for market in data.get("data", {}).get("marketplaces", []) or []:
        for p in market.get("plugins", []) or []:
            skills = []
            mcp_servers = []
            try:
                skills = json.loads(p.get("skills_json") or "[]") if p.get("skills_json") else []
            except Exception:
                skills = []
            try:
                mcp_servers = (
                    json.loads(p.get("mcp_servers_json") or "[]")
                    if p.get("mcp_servers_json")
                    else []
                )
            except Exception:
                mcp_servers = []
            src = (p.get("source") or {}).get("path", "")
            skill_dir = Path(src) / "skills" if src else None
            disk_skills = 0
            if skill_dir and skill_dir.exists():
                disk_skills = len(list(skill_dir.glob("*/SKILL.md")))
            plugins.append(
                {
                    "plugin_id": p.get("plugin_id"),
                    "version": p.get("version"),
                    "source_path": src,
                    "skills_declared": len(skills),
                    "skills_on_disk": disk_skills,
                    "mcp_servers": len(mcp_servers),
                    "connector": p.get("connector_json") or "",
                }
            )
    return plugins


def _manifests() -> dict[str, Any]:
    result: dict[str, Any] = {"global_skills": [], "agent_types": {}}
    g = load_json(MANIFEST_DIR / "global.json", {}) or {}
    result["global_skills"] = [s.get("name") for s in (g.get("global", {}).get("skills", []) or [])]
    for name in ("trae", "solo"):
        d = load_json(MANIFEST_DIR / f"{name}.json", {}) or {}
        for at in d.get("agent_types", []) or []:
            agent = at.get("name")
            # trae.json 与 solo.json 可能包含同名 agent；按 model 去重，避免重复计数。
            models_by_name = {m["model"]: m for m in result["agent_types"].get(agent, [])}
            for m in at.get("models", []) or []:
                skills = [s.get("name") for s in (m.get("skills", []) or [])]
                models_by_name[m.get("name")] = {
                    "model": m.get("name"),
                    "skill_count": len(skills),
                    "skills": skills,
                }
            result["agent_types"][agent] = list(models_by_name.values())
    return result


def _mcp_surface() -> dict[str, Any]:
    modes: dict[str, set[str]] = {}
    servers: dict[str, set[str]] = {}
    sessions = 0
    for sess in MCPS_DIR.glob("*"):
        if not sess.is_dir():
            continue
        sessions += 1
        for mode in sess.glob("*"):
            if not mode.is_dir():
                continue
            mname = mode.name
            modes.setdefault(mname, set())
            for srv in mode.glob("*"):
                if not srv.is_dir():
                    continue
                sname = srv.name
                servers.setdefault(sname, set())
                for tf in (srv / "tools").glob("*.json"):
                    modes[mname].add(tf.stem)
                    servers[sname].add(tf.stem)
    return {
        "sessions": sessions,
        "modes": {k: {"tool_count": len(v), "tools": sorted(v)} for k, v in sorted(modes.items())},
        "servers": {
            k: {"tool_count": len(v), "tools": sorted(v)} for k, v in sorted(servers.items())
        },
    }


def _permissions() -> dict[str, Any]:
    perm = load_json(TRAE_HOME / "permission/global.json", {}) or {}
    sandbox = load_json(TRAE_HOME / "sandbox.json", {}) or {}
    fs = (perm.get("resourceAuthorization") or {}).get("filesystem") or {}
    return {
        "active_profile": perm.get("activeProfileId"),
        "fs_read_write": len(fs.get("readWrite", []) or []),
        "fs_read_only": len(fs.get("readOnly", []) or []),
        "sandbox_fs_read_write": len((sandbox.get("filesystem") or {}).get("readWrite", []) or []),
        "sandbox_network_default": (sandbox.get("network") or {}).get("default"),
    }


def run_manifest_miner() -> dict[str, Any]:
    manifests = _manifests()
    user_skills = _user_skills()
    plugins = _plugins()
    mcp = _mcp_surface()
    perms = _permissions()

    agent_summary = {}
    for agent, models in manifests["agent_types"].items():
        counts = [m["skill_count"] for m in models]
        agent_summary[agent] = {
            "models": len(models),
            "skill_count_min": min(counts) if counts else 0,
            "skill_count_max": max(counts) if counts else 0,
            "profiles": models,
        }

    ev = [
        evidence(
            {"global_skills": len(manifests["global_skills"]), "agent_types": list(agent_summary)},
            "observation",
            {"source": "manifests", "path": str(MANIFEST_DIR)},
        ),
        evidence(
            agent_summary,
            "derivation",
            {"source": "manifests", "rule": "agent_type × model → skills"},
            confidence=0.9,
            known_gaps=[
                "manifest 是声明，运行时会话可能因模型能力/权限被裁剪",
                "同一 model 在不同 agent_type 下的 skills 可能不同，未做交叉去重",
            ],
        ),
        evidence(
            {"user_skills": len(user_skills), "plugins": len(plugins)},
            "observation",
            {"source": "filesystem", "paths": [str(SKILLS_DIR), str(PLUGINS_DIR)]},
        ),
        evidence(
            {k: v["tool_count"] for k, v in mcp["modes"].items()},
            "observation",
            {"source": "mcps", "path": str(MCPS_DIR), "sessions": mcp["sessions"]},
            known_gaps=[
                "工具面按会话+mode 物化，不同会话可能不同；此处是历史并集",
                "原生 chat 工具不物化，未计入",
            ],
        ),
        evidence(
            perms,
            "observation",
            {"source": "permission/sandbox", "path": str(TRAE_HOME)},
        ),
    ]

    return {
        "summary": (
            f"agent_types={list(agent_summary)}；user_skills={len(user_skills)}；"
            f"plugins={len(plugins)}；mcp_sessions={mcp['sessions']}；"
            f"modes={len(mcp['modes'])}"
        ),
        "manifests": manifests,
        "agent_summary": agent_summary,
        "user_skills": user_skills,
        "plugins": plugins,
        "mcp_surface": mcp,
        "permissions": perms,
        "evidence": ev,
    }
