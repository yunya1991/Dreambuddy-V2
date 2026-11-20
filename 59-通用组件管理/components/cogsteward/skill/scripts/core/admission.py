"""记忆准入四问（A1–A4）。

契约见 references/admission-rules.md：默认拒绝，答不出「不可再推导」就不写；
记忆只存指针，不复制正文；不确定一律进 pending，不进入检索。

实现说明（与 SPEC 表格的措辞差异见 docs/TECHNICAL_DESIGN.md §10）：
- A1 的 `not_derivable` 视为合法判定（表示没有可推导来源，属于新知识），
  与 SPEC §5.5 的路由输出示例保持一致；
- `derivable_from` 必须给出真实存在的相对路径，否则降级为 unknown；
- 任意一项为 unknown → `pending=True`，由调用方写入 pending 表。
"""

from __future__ import annotations

from pathlib import Path

ADMISSION_ROUTES = ("memory",)

DEFAULT_FACTS = {
    "a1": {"result": "unknown"},
    "a2": {"result": "unknown"},
    "a3": {"result": "none"},
    "a4": {"result": "unknown"},
}


def _as_dict(value, default: dict) -> dict:
    if value is None:
        return dict(default)
    if isinstance(value, str):
        return {"result": value}
    if isinstance(value, dict):
        merged = dict(default)
        merged.update(value)
        return merged
    return dict(default)


def _path_exists(root: Path, rel: str) -> bool:
    raw = (rel or "").strip()
    if not raw or raw.startswith("/") or raw.startswith(".."):
        return False
    try:
        return (root / raw).exists()
    except OSError:
        return False


def _check_a1(root: Path, fact: dict) -> dict:
    result = str(fact.get("result") or "unknown")
    if result == "derivable_from":
        paths = fact.get("paths") or []
        if isinstance(paths, str):
            paths = [paths]
        paths = [str(item).strip() for item in paths if str(item).strip()]
        missing = [item for item in paths if not _path_exists(root, item)]
        if not paths:
            return {"result": "unknown", "reason": "derivable_from 未给出路径", "pending": True}
        if missing:
            return {
                "result": "unknown",
                "reason": "derivable_from 路径不存在：{}".format(", ".join(missing[:3])),
                "paths": paths,
                "pending": True,
            }
        return {
            "result": "derivable_from",
            "paths": paths,
            "pointer_only": True,
            "pending": False,
        }
    if result == "not_derivable":
        return {"result": "not_derivable", "pending": False}
    return {"result": "unknown", "reason": "A1 未判定", "pending": True}


def _check_a2(root: Path, fact: dict) -> dict:
    result = str(fact.get("result") or "unknown")
    if result == "ssot_path":
        path = str(fact.get("path") or "").strip()
        if not _path_exists(root, path):
            return {
                "result": "unknown",
                "reason": "ssot_path 不存在：{}".format(path or "(空)"),
                "pending": True,
            }
        return {"result": "ssot_path", "path": path, "pointer_only": True, "pending": False}
    if result == "none":
        return {"result": "none", "pending": False}
    return {"result": "unknown", "reason": "A2 未判定", "pending": True}


def _check_a3(root: Path, fact: dict) -> dict:
    result = str(fact.get("result") or "none")
    if result == "evidence_ref":
        ref = str(fact.get("ref") or "").strip()
        if not ref:
            return {"result": "none", "reason": "evidence_ref 为空", "pending": False}
        looks_like_path = "/" in ref or "." in ref
        if looks_like_path and not _path_exists(root, ref):
            return {
                "result": "unknown",
                "reason": "evidence_ref 不存在：{}".format(ref),
                "pending": True,
            }
        return {"result": "evidence_ref", "ref": ref, "pending": False}
    return {"result": "none", "pending": False, "downgrade": "observation"}


def _check_a4(fact: dict) -> dict:
    result = str(fact.get("result") or "unknown")
    if result == "yes":
        return {"result": "yes", "pending": False}
    if result == "no":
        return {"result": "no", "blocked": True, "pending": False}
    return {"result": "unknown", "ttl_days": 30, "pending": True}


def evaluate(root, primary: str, facts: dict = None) -> dict:
    """返回准入结论；非记忆载体直接跳过。"""
    if primary not in ADMISSION_ROUTES:
        return {
            "applicable": False,
            "passed": True,
            "pending": False,
            "blocked": False,
            "decision": "skip",
            "kind": primary,
            "confidence_cap": None,
            "ttl_days": None,
            "checks": {},
            "reasons": ["{} 载体无需准入".format(primary)],
        }

    root = Path(root).expanduser().resolve()
    facts = facts or {}
    checks = {
        "A1": _check_a1(root, _as_dict(facts.get("a1"), DEFAULT_FACTS["a1"])),
        "A2": _check_a2(root, _as_dict(facts.get("a2"), DEFAULT_FACTS["a2"])),
        "A3": _check_a3(root, _as_dict(facts.get("a3"), DEFAULT_FACTS["a3"])),
        "A4": _check_a4(_as_dict(facts.get("a4"), DEFAULT_FACTS["a4"])),
    }

    pending = any(check.get("pending") for check in checks.values())
    blocked = any(check.get("blocked") for check in checks.values())
    reason_items = [
        "{} {}".format(key, check["reason"]) for key, check in checks.items() if check.get("reason")
    ]

    decision = "reject" if blocked else ("pending" if pending else "accept")
    kind = "memory"
    confidence_cap = None
    if checks["A3"].get("downgrade") == "observation":
        kind = "observation"
        confidence_cap = 0.5
        reason_items.append("A3 无落点，降级 observation，置信度上限 0.5")
    if blocked:
        reason_items.append("A4=no：六个月后无价值，拒绝写入")
    if pending:
        reason_items.append("准入含 unknown：写入 pending，不进入检索")

    ttl_days = checks["A4"].get("ttl_days")
    return {
        "applicable": True,
        "passed": not blocked,
        "pending": bool(pending),
        "blocked": bool(blocked),
        "decision": decision,
        "kind": kind,
        "pointer_only": bool(checks["A1"].get("pointer_only") or checks["A2"].get("pointer_only")),
        "confidence_cap": confidence_cap,
        "ttl_days": ttl_days,
        "checks": checks,
        "reasons": reason_items,
    }
