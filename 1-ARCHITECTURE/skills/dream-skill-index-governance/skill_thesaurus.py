"""Skill Thesaurus — 触发词权威词表。

借鉴图书馆学 LCSH 权威控制：
- synonyms: 同义词归一化（USE/UF）
- disambiguation: 冲突 trigger 按 domain 消歧
- generic_triggers: 泛化 trigger 黑名单，从冲突检测排除

工程约束：HC-1a（独立模块）/ FAIL-OPEN / 零回归
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

DEFAULT_THESAURUS_PATH = Path(__file__).parent / "skill_thesaurus.yaml"


def load_thesaurus(path: Path | str | None = None) -> dict[str, Any] | None:
    """加载权威词表 YAML。FAIL-OPEN：不可用时返回 None。"""
    p = Path(path) if path else DEFAULT_THESAURUS_PATH
    if not p.exists():
        return None
    try:
        text = p.read_text(encoding="utf-8")
        if yaml is not None:
            return yaml.safe_load(text)
        # 极简 YAML 解析兜底（仅支持本词表结构）
        return _minimal_yaml_parse(text)
    except Exception:
        return None


def normalize_trigger(trigger: str, thesaurus: dict[str, Any] | None) -> str:
    """同义词归一化：把 trigger 映射到 canonical 形式。"""
    if not thesaurus:
        return trigger
    synonyms = thesaurus.get("synonyms", {}) or {}
    for canonical, entry in synonyms.items():
        if trigger == canonical:
            return canonical
        uf = entry.get("uf", []) if isinstance(entry, dict) else []
        if trigger in uf:
            return canonical
    return trigger


def disambiguate(trigger: str, domain: str, thesaurus: dict[str, Any] | None) -> str | None:
    """按 domain 消歧冲突 trigger，返回目标 SKILL 名。无法消歧返回 None。"""
    if not thesaurus:
        return None
    disamb = thesaurus.get("disambiguation", {}) or {}
    entry = disamb.get(trigger)
    if not entry:
        return None
    # 精确匹配 domain
    if domain in entry:
        return entry[domain]
    # 回退到 default
    return entry.get("default")


def is_generic_trigger(trigger: str, thesaurus: dict[str, Any] | None) -> bool:
    """判断 trigger 是否为泛化无意义词（应从冲突检测排除）。"""
    if not thesaurus:
        return False
    generic = thesaurus.get("generic_triggers", []) or []
    # 容错：YAML 可能把 on/off/yes/no 解析为 bool
    generic_strs = [str(g).lower() for g in generic]
    return trigger.lower() in generic_strs


def _minimal_yaml_parse(text: str) -> dict[str, Any]:
    """极简 YAML 解析（仅支持本词表的同义词/消歧/黑名单结构）。"""
    import re

    result: dict[str, Any] = {"synonyms": {}, "disambiguation": {}, "generic_triggers": []}
    lines = text.splitlines()
    current_section = None
    current_key = None

    for line in lines:
        stripped = line.rstrip()
        if not stripped or stripped.startswith("#"):
            continue

        # 顶级 section
        if not line.startswith(" ") and stripped.endswith(":"):
            current_section = stripped[:-1].strip()
            current_key = None
            continue

        if current_section == "synonyms":
            if not line.startswith(" ") and ":" in stripped:
                key, _, val = stripped.partition(":")
                current_key = key.strip()
                result["synonyms"][current_key] = {"canonical": current_key, "uf": []}
                if val.strip():
                    # inline list
                    result["synonyms"][current_key]["uf"] = _parse_inline_list(val)
            elif line.startswith("    ") and "uf:" in stripped:
                _, _, val = stripped.partition("uf:")
                if val.strip():
                    result["synonyms"][current_key]["uf"] = _parse_inline_list(val)

        elif current_section == "disambiguation":
            if not line.startswith(" ") and ":" in stripped:
                key, _, val = stripped.partition(":")
                current_key = key.strip()
                result["disambiguation"][current_key] = {}
                if val.strip():
                    result["disambiguation"][current_key] = _parse_inline_dict(val)
            elif line.startswith("    ") and ":" in stripped:
                k, _, v = stripped.strip().partition(":")
                result["disambiguation"].setdefault(current_key, {})[k.strip()] = v.strip()

        elif current_section == "generic_triggers":
            if stripped.startswith("- "):
                result["generic_triggers"].append(stripped[2:].strip())

    return result


def _parse_inline_list(val: str) -> list[str]:
    val = val.strip()
    if val.startswith("[") and val.endswith("]"):
        return [v.strip().strip("'\"") for v in val[1:-1].split(",") if v.strip()]
    return [val.strip("'\"")]


def _parse_inline_dict(val: str) -> dict[str, str]:
    val = val.strip()
    if val.startswith("{") and val.endswith("}"):
        inner = val[1:-1]
        result = {}
        for pair in inner.split(","):
            if ":" in pair:
                k, _, v = pair.partition(":")
                result[k.strip()] = v.strip().strip("'\"")
        return result
    return {}
