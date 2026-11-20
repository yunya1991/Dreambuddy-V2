"""路由内核：判定树 → confidence → patch → plan / apply。

契约见 references/routing-matrix.md 与 references/confidence.md。
默认 plan：只输出建议与 patch 摘要，不写工作区文件；
只有 `cm config apply=on` 且调用方显式要求 apply 时才落盘（先快照）。
"""

from __future__ import annotations

import datetime
import hashlib
import json
import re
import time
from pathlib import Path

from . import admission, apply as apply_engine, signature, store

SCHEMA_VERSION = "1.1"
EXECUTION_WINDOW_DAYS = 90
MAX_PATCH_FILES = 10
MAX_MODIFY_BYTES = 200 * 1024

STRONG_REUSE_WORDS = (
    "清单", "流程", "步骤", "脚本", "自动化", "sop", "runbook", "发布检查",
)
WEAK_REUSE_WORDS = (
    "模板", "每次", "例行", "照做", "操作", "检查", "批处理", "定时",
)
STABLE_WORDS = (
    "规范", "标准", "事实", "定义", "接口", "架构", "说明", "文档",
    "约定", "路径", "配置项", "背景", "现状", "方案",
)
EXPERIENCE_WORDS = (
    "坑", "教训", "结论", "取舍", "经验", "反模式", "踩坑", "注意",
    "记住", "避免", "原因", "判断", "误判",
)

STEP_RE = re.compile(r"(?m)^\s*(?:\d+[.、)]|[-*]\s*\[[ xX]\]|第[一二三四五六七八九十]+步)")
PATH_RE = re.compile(
    r"[A-Za-z0-9_][A-Za-z0-9_./-]*\.(?:md|markdown|txt|py|sh|json|ya?ml|ts|tsx|js|rs|go)"
)

ROUTE_PRIORITY = {"skill": 3, "doc": 2, "memory": 1, "session": 0}
ATTACH_EDGE = {
    "skill": "references",
    "doc": "documented_by",
    "memory": "derived_from",
    "session": "references",
}
NEXT_ACTION = {
    "skill": "create_skill",
    "doc": "create_doc",
    "memory": "write_memory",
    "session": "keep_session",
}


def _hit_words(text: str, words) -> list:
    lowered = text.lower()
    return [word for word in words if word in lowered]


def _detect(content: str) -> dict:
    reuse_hits = _hit_words(content, STRONG_REUSE_WORDS) + _hit_words(content, WEAK_REUSE_WORDS)
    stable_hits = _hit_words(content, STABLE_WORDS)
    experience_hits = _hit_words(content, EXPERIENCE_WORDS)
    has_steps = bool(STEP_RE.search(content))

    strong_hit = bool(_hit_words(content, STRONG_REUSE_WORDS))
    reuse_hit = bool(reuse_hits) and (
        strong_hit or len(reuse_hits) >= 2 or has_steps
    )
    return {
        "skill": {"hit": reuse_hit, "score": len(reuse_hits) + (1 if has_steps else 0),
                  "words": reuse_hits},
        "doc": {"hit": bool(stable_hits), "score": len(stable_hits), "words": stable_hits},
        "memory": {"hit": bool(experience_hits), "score": len(experience_hits),
                   "words": experience_hits},
    }


def _slug(text: str, limit: int = 24) -> str:
    cleaned = signature.clean(text)
    cleaned = re.sub(r"\s+", "-", cleaned)
    cleaned = re.sub(r"[^0-9a-z\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff-]", "", cleaned)
    cleaned = cleaned.strip("-")
    return cleaned[:limit] or "untitled"


def _title(content: str) -> str:
    for line in content.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped[:80]
    return _slug(content)


def _today() -> str:
    return datetime.date.today().isoformat()


def _next_run_id(conn, now: float) -> str:
    stamp = datetime.datetime.fromtimestamp(now).strftime("%Y%m%d")
    start = datetime.datetime.fromtimestamp(now).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).timestamp()
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM runs WHERE created_at >= ?", (start,)
    ).fetchone()
    return "rt-{}-{:04d}".format(stamp, int(row["n"] or 0) + 1)


def _recent_execution_count(conn, sig: str, now: float) -> int:
    since = now - EXECUTION_WINDOW_DAYS * 86400
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM executions "
        "WHERE intent_signature = ? AND executed_at >= ? AND source IN ('record', 'mark_done')",
        (sig, since),
    ).fetchone()
    return int(row["n"] or 0)


def _confirm(conn, sig: str, now: float):
    row = conn.execute(
        "SELECT expires_at FROM intent_confirms WHERE intent_signature = ?", (sig,)
    ).fetchone()
    if row and float(row["expires_at"] or 0) > now:
        return row
    return None


def _write_confirm(conn, sig: str, now: float, ttl_days: int) -> None:
    conn.execute(
        "INSERT INTO intent_confirms(intent_signature, confirmed_at, expires_at) "
        "VALUES(?, ?, ?) ON CONFLICT(intent_signature) DO UPDATE SET "
        "confirmed_at=excluded.confirmed_at, expires_at=excluded.expires_at",
        (sig, now, now + max(int(ttl_days), 1) * 86400),
    )
    conn.commit()


def _existing_paths(root: Path, content: str) -> list:
    found = []
    for match in PATH_RE.finditer(content):
        candidate = match.group(0).strip().rstrip(".,;:)")
        if candidate.startswith("/") or ".." in candidate.split("/"):
            continue
        try:
            if (root / candidate).exists() and candidate not in found:
                found.append(candidate)
        except OSError:
            continue
        if len(found) >= 3:
            break
    return found


def _confidence_value(config: dict, evidence: float, consistency: float,
                      history: float, conflict: float) -> float:
    value = (
        float(config.get("weight_evidence", 0.35)) * evidence
        + float(config.get("weight_consistency", 0.30)) * consistency
        + float(config.get("weight_history", 0.20)) * history
        + float(config.get("weight_conflict", 0.15)) * (1.0 - conflict)
    )
    return round(value, 3)


def _confidence_parts(config: dict, evidence: float, consistency: float,
                      history: float, conflict: float) -> dict:
    return {
        "evidence": round(evidence, 3),
        "consistency": round(consistency, 3),
        "history": round(history, 3),
        "conflict": round(conflict, 3),
    }


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _file_entry(root: Path, rel_path: str, op: str, content=None) -> dict:
    entry = {"op": op, "path": rel_path}
    if op in ("create", "modify"):
        entry["content"] = content or ""
        entry["sha256"] = _sha256_text(content or "")
    else:
        entry["sha256"] = ""
    return entry


def _skill_content(title: str, description: str, sig: str) -> str:
    return "\n".join([
        "---",
        "name: {}".format(_slug(title)),
        "display_name: {}".format(title),
        "display_name_en: {}".format(_slug(title)),
        "description: \"{}\"".format(description.replace("\"", "'")[:80]),
        "description_zh: {}".format(description.replace("\n", " ")[:60]),
        "description_en: Generated by CogSteward; refine before use.",
        "version: 0.1.0",
        "author: CogSteward",
        "allowed-tools: Read, Glob, Grep",
        "---",
        "",
        "# {}".format(title),
        "",
        "## 何时使用",
        "",
        "- {}".format(description),
        "",
        "## 反触发（不要调用）",
        "",
        "- 一次性任务",
        "",
        "## 流程",
        "",
        "1. 待补充（来源指纹 {}）".format(sig),
        "",
        "## 输出",
        "",
        "<固定字段 / 文件 / 报告结构>",
        "",
        "## 边界",
        "",
        "- 做：",
        "- 不做：",
        "",
    ])


def _doc_content(title: str, content: str, sig: str) -> str:
    return "\n".join([
        "# {}".format(title),
        "",
        "> 来源：cm route（指纹 {}）".format(sig),
        "> 日期：{}".format(_today()),
        "",
        content.strip(),
        "",
    ])


def _memory_pointer(sig: str, content_ref: str, admission_result: dict) -> str:
    lines = [
        "# 记忆指针 {}".format(sig),
        "",
        "- 指纹：{}".format(sig),
        "- 内容引用：{}（只存引用，不保存正文）".format(content_ref),
        "- 创建：{}".format(_today()),
        "- 准入：",
    ]
    for key in ("A1", "A2", "A3", "A4"):
        check = admission_result.get("checks", {}).get(key, {})
        lines.append("  - {}: {}".format(key, check.get("result", "unknown")))
    lines.append("")
    return "\n".join(lines)


def _stub_content(title: str, primary: str, primary_path: str, edge: str, sig: str) -> str:
    return "\n".join([
        "# {}".format(title),
        "",
        "> 主载体：{} → {}".format(primary, primary_path),
        "> 从属关系：{}".format(edge),
        "> 指纹：{}".format(sig),
        "",
        "（从属物化：仅登记指针，不复制正文）",
        "",
    ])


def _resolve_doc_target(root: Path, conn, title: str, slug: str) -> tuple:
    """返回 (路径, 是否修改)。已登记或已存在的文档走追加，否则新建。"""
    row = conn.execute(
        "SELECT path, size FROM docs WHERE title = ? AND status != 'orphan' "
        "ORDER BY indexed_at DESC LIMIT 1",
        (title,),
    ).fetchone()
    if row:
        size = int(row["size"] or 0)
        if size <= MAX_MODIFY_BYTES:
            return row["path"], True
    candidate = "docs/{}.md".format(slug)
    target = root / candidate
    if target.exists():
        try:
            if target.stat().st_size <= MAX_MODIFY_BYTES:
                return candidate, True
        except OSError:
            pass
    return candidate, False


def _append_content(existing: str, title: str, content: str, sig: str) -> str:
    return "\n".join([
        existing.rstrip(),
        "",
        "## 追加 · {}（指纹 {}）".format(_today(), sig),
        "",
        content.strip(),
        "",
    ])


def _build_patch(root: Path, conn, primary: str, target_path: str, title: str,
                 content: str, sig: str, admission_result: dict,
                 attachments: list) -> dict:
    entries = []
    if primary == "skill":
        new_content = _skill_content(title, content.strip(), sig)
        op = "create"
        if (root / target_path).exists():
            try:
                old = (root / target_path).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                old = ""
            if old == new_content:
                op = "modify"
            else:
                target_path = "skills/{}-{}/SKILL.md".format(_slug(title), sig[:8])
                op = "modify" if (root / target_path).exists() else "create"
        entries.append(_file_entry(root, target_path, op, new_content))
    elif primary == "doc":
        doc_path, modify = _resolve_doc_target(root, conn, title, _slug(title))
        if modify:
            try:
                existing = (root / doc_path).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                existing = ""
            entries.append(_file_entry(root, doc_path, "modify",
                                       _append_content(existing, title, content, sig)))
        else:
            entries.append(_file_entry(root, doc_path, "create",
                                       _doc_content(title, content, sig)))
        target_path = doc_path
    elif primary == "memory":
        content_ref = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
        op = "modify" if (root / target_path).exists() else "create"
        entries.append(_file_entry(root, target_path, op,
                                   _memory_pointer(sig, content_ref, admission_result)))

    for attachment in attachments:
        if attachment.get("materialize") == "none":
            continue
        route = attachment["route"]
        path = attachment.get("target", {}).get("path")
        if not path:
            continue
        op = "modify" if (root / path).exists() else "create"
        entries.append(_file_entry(
            root, path, op,
            _stub_content(title, primary, target_path, attachment["edge"], sig),
        ))

    # 去重路径，保留先出现的操作
    seen, unique = set(), []
    for entry in entries:
        if entry["path"] in seen:
            continue
        seen.add(entry["path"])
        unique.append(entry)

    return {
        "summary": "新增 / 修改 {} 个文件（主载体 {}）".format(len(unique), primary),
        "files": unique[:MAX_PATCH_FILES],
    }


def _alternatives(config: dict, detection: dict, primary: str, evidence: float,
                  history: float) -> list:
    """候选互斥未决：仅当非主载体同样命中且分数并列时给出。"""
    scores = {route: info["score"] for route, info in detection.items() if info["hit"]}
    if len(scores) < 2:
        return []
    ordered = sorted(scores.values(), reverse=True)
    if ordered[0] != ordered[1]:
        return []
    result = []
    for route, score in scores.items():
        if route == primary:
            continue
        value = _confidence_value(config, evidence, 0.5, history, 0.5)
        result.append({"route": route, "confidence": value})
    return result


def route(root, config: dict, conn, content: str, *, apply_requested: bool = False,
          confirm: bool = False, facts: dict = None) -> dict:
    """执行一次路由，返回契约化结果；默认不落盘。"""
    root = Path(root).expanduser().resolve()
    now = time.time()
    content = (content or "").strip()
    if not content:
        raise store.CmError(store.EXIT_USAGE, "路由内容不能为空")

    salt = str(config.get("signature_salt") or "")
    described = signature.describe(content, salt)
    sig = described["signature"]

    if confirm:
        _write_confirm(conn, sig, now, int(config.get("confirm_ttl_days", 90)))
    confirm_row = _confirm(conn, sig, now)

    execution_count = _recent_execution_count(conn, sig, now)
    detection = _detect(content)
    hits = [route_name for route_name in ("skill", "doc", "memory")
            if detection[route_name]["hit"]]
    primary = max(hits, key=lambda item: ROUTE_PRIORITY[item]) if hits else "session"

    title = _title(content)
    slug = _slug(content)
    if primary == "skill":
        target_path = "skills/{}/SKILL.md".format(slug)
        if (root / target_path).exists():
            target_path = "skills/{}-{}/SKILL.md".format(slug, sig[:8])
    elif primary == "doc":
        target_path = "docs/{}.md".format(slug)
    elif primary == "memory":
        target_path = ".cm/memory/{}.md".format(sig)
    else:
        target_path = ""

    admission_result = admission.evaluate(root, primary, facts)
    max_attach = int(config.get("max_attachments", 0))
    materialize = str(config.get("materialize", "none"))
    attachments = []
    for route_name in sorted(hits, key=lambda item: ROUTE_PRIORITY[item], reverse=True):
        if route_name == primary:
            continue
        if len(attachments) >= max_attach:
            break
        if route_name == "session":
            continue
        attach_path = {
            "doc": "docs/{}-从属.md".format(slug),
            "skill": "skills/{}-从属/SKILL.md".format(slug),
            "memory": ".cm/memory/{}-从属.md".format(sig),
        }[route_name]
        attachments.append({
            "route": route_name,
            "edge": ATTACH_EDGE[route_name],
            "materialize": materialize,
            "target": {"path": attach_path},
        })

    evidence_files = _existing_paths(root, content)
    evidence = []
    evidence_score = 0.3
    if evidence_files or execution_count:
        evidence_score = 1.0
    elif confirm_row:
        evidence_score = 0.6
    if execution_count:
        evidence.append({"kind": "execution_count", "value": execution_count})
    for path in evidence_files:
        evidence.append({"kind": "file", "value": path})
    if confirm_row:
        evidence.append({"kind": "user_confirm", "value": sig})
    derivable = admission_result.get("checks", {}).get("A1", {})
    if derivable.get("result") == "derivable_from":
        evidence.append({"kind": "derivation", "value": ", ".join(derivable.get("paths", []))})

    alternatives = _alternatives(config, detection, primary, evidence_score,
                                 min(execution_count / 5.0, 1.0))
    if not hits:
        consistency = 0.2
    elif len(hits) == 1:
        consistency = 1.0
    elif alternatives:
        consistency = 0.5
    else:
        consistency = 0.8
    history = min(execution_count / 5.0, 1.0)
    conflict = 0.5 if alternatives else 0.0
    confidence = _confidence_value(config, evidence_score, consistency, history, conflict)
    if admission_result.get("confidence_cap") is not None:
        confidence = min(confidence, float(admission_result["confidence_cap"]))

    requires_confirm = bool(
        primary == "skill" and execution_count < 2 and confirm_row is None
    ) or bool(admission_result.get("pending"))
    if admission_result.get("blocked"):
        requires_confirm = True

    patch = None
    if admission_result.get("passed") and not admission_result.get("pending"):
        patch = _build_patch(
            root, conn, primary, target_path, title, content, sig,
            admission_result, attachments,
        )
        if patch["files"] and primary in ("skill", "doc", "memory"):
            target_path = patch["files"][0]["path"]
        if not patch["files"]:
            patch = None

    idempotency_key = "sha256:" + hashlib.sha256(
        "{}|{}|{}".format(described["normalized"], primary, target_path or "-").encode("utf-8")
    ).hexdigest()[:32]

    low = float(config.get("low_threshold", 0.5))
    high = float(config.get("high_threshold", 0.8))
    reasons = []
    for route_name, info in detection.items():
        if info["hit"]:
            reasons.append("{}: 命中 {} 个关键词（{}）".format(
                route_name, info["score"], "、".join(info["words"][:3])))
    if execution_count:
        reasons.append("近 {} 天同指纹执行 {} 次".format(EXECUTION_WINDOW_DAYS, execution_count))
    if confirm_row:
        reasons.append("用户已确认，确认不计入执行次数")
    if not hits:
        reasons.append("未命中可复用 / 稳定 / 经验特征，回落 session")
    reasons.append("evidence={} / consistency={} / history={} / conflict={}".format(
        evidence_score, consistency, round(history, 3), conflict))

    if admission_result.get("pending"):
        next_action = "write_pending"
        reasons.append("准入 pending：不进入检索，等待 cm triage")
    elif admission_result.get("blocked"):
        next_action = "ask_user"
        reasons.extend(admission_result.get("reasons", []))
    elif confidence < low:
        next_action = "ask_user"
        reasons.append("confidence {:.2f} 低于 low {:.2f}，不写入".format(confidence, low))
    elif confidence < high or requires_confirm:
        next_action = "ask_user"
        if requires_confirm:
            reasons.append("D1 执行次数不足或需用户确认")
        else:
            reasons.append("confidence {:.2f} 位于 low–high 区间".format(confidence))
    else:
        next_action = NEXT_ACTION[primary]

    if next_action in ("ask_user", "write_pending"):
        patch = None

    run_id = _next_run_id(conn, now)
    apply_mode = "plan"
    apply_result = None

    if admission_result.get("pending"):
        existing = conn.execute(
            "SELECT id FROM pending WHERE payload_ref = ? AND state = 'open'",
            (idempotency_key,),
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO pending(kind, payload_ref, created_at, review_count, state) "
                "VALUES('memory', ?, ?, 0, 'open')",
                (idempotency_key, now),
            )

    wants_apply = bool(apply_requested)
    can_apply = (
        wants_apply
        and bool(config.get("apply"))
        and next_action in (NEXT_ACTION["skill"], NEXT_ACTION["doc"], NEXT_ACTION["memory"])
        and patch is not None
    )
    if wants_apply and not config.get("apply"):
        reasons.append("apply 未开启（cm config apply=on 后才落盘）")
    if can_apply and len(patch["files"]) > MAX_PATCH_FILES:
        can_apply = False
        reasons.append("patch 超过 {} 个文件，强制降级 plan".format(MAX_PATCH_FILES))

    if can_apply:
        replay = apply_engine.find_applied(conn, idempotency_key)
        if replay:
            apply_result = {
                "applied": False,
                "replayed": True,
                "run_id": replay["run_id"],
                "reason": "idempotency_key 已应用，跳过重复写入",
            }
            reasons.append("幂等命中：同一 key 已应用")
        else:
            apply_result = apply_engine.apply_patch(
                root, run_id, idempotency_key, patch, conn=conn,
            )
            apply_mode = "apply"
            reasons.append("已按 patch 落盘并生成快照")
    elif wants_apply and next_action == NEXT_ACTION["session"] and config.get("apply"):
        expires = now + int(config.get("session_ttl_days", 7)) * 86400
        conn.execute(
            "INSERT INTO sessions(content_ref, created_at, expires_at, triaged_at) "
            "VALUES(?, ?, ?, NULL)",
            (sig, now, expires),
        )
        apply_mode = "apply"

    conn.execute(
        "INSERT INTO runs(intent_signature, route, confidence, outcome, created_at) "
        "VALUES(?, ?, ?, ?, ?)",
        (sig, primary, confidence, next_action, now),
    )
    conn.commit()

    return {
        "schema_version": SCHEMA_VERSION,
        "id": run_id,
        "idempotency_key": idempotency_key,
        "apply_mode": apply_mode,
        "primary": primary,
        "attachments": attachments,
        "alternatives": alternatives,
        "confidence": confidence,
        "confidence_parts": _confidence_parts(
            config, evidence_score, consistency, history, conflict),
        "evidence": evidence,
        "admission": admission_result,
        "requires_user_confirm": requires_confirm,
        "target": {"path": target_path, "template": _template_for(primary)},
        "next_action": next_action,
        "patch": patch,
        "reasons": reasons,
        "signature": sig,
        "signature_normalized": described["normalized"],
        "signature_version": described["version"],
        "workspace": str(root),
        "apply": apply_result,
    }


def _template_for(primary: str) -> str:
    return {
        "skill": "skill-basic",
        "doc": "doc-index",
        "memory": "memory-pointer",
        "session": "session",
    }[primary]


def mark_done(root, config: dict, conn, content: str, source: str = "mark_done") -> dict:
    """登记一次真实执行；用户确认不算执行。"""
    if source not in ("record", "mark_done"):
        raise store.CmError(store.EXIT_USAGE, "未知执行来源：{}".format(source))
    content = (content or "").strip()
    if not content:
        raise store.CmError(store.EXIT_USAGE, "执行内容不能为空")
    salt = str(config.get("signature_salt") or "")
    described = signature.describe(content, salt)
    now = time.time()
    conn.execute(
        "INSERT INTO executions(intent_signature, executed_at, source) VALUES(?, ?, ?)",
        (described["signature"], now, source),
    )
    conn.commit()
    count = _recent_execution_count(conn, described["signature"], now)
    return {
        "signature": described["signature"],
        "normalized": described["normalized"],
        "version": described["version"],
        "source": source,
        "executions_90d": count,
    }


def confirm_intent(root, config: dict, conn, content: str) -> dict:
    content = (content or "").strip()
    if not content:
        raise store.CmError(store.EXIT_USAGE, "确认内容不能为空")
    described = signature.describe(content, str(config.get("signature_salt") or ""))
    now = time.time()
    ttl = int(config.get("confirm_ttl_days", 90))
    _write_confirm(conn, described["signature"], now, ttl)
    return {
        "signature": described["signature"],
        "expires_at": now + ttl * 86400,
        "ttl_days": ttl,
    }
