"""体检与人类可读报告。"""

from __future__ import annotations

import datetime
import json
import time
import unicodedata
from pathlib import Path

from . import contract, scanner

SCHEMA_VERSION = "1.0"

PROBLEM_KEYS = contract.problem_keys()
LABELS = contract.labels()


def health_of(metrics: dict) -> str:
    return contract.health_of(metrics)


def _now_iso() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _json_load(text, fallback):
    try:
        return json.loads(text) if text else fallback
    except (TypeError, ValueError):
        return fallback


def doctor(root, config: dict, conn) -> dict:
    root = Path(root).expanduser().resolve()
    now = time.time()
    details = {}

    # 1. 断链：索引中的本地引用指向不存在的文件
    edge_rows = conn.execute(
        "SELECT DISTINCT src, dst FROM edges WHERE kind='references'"
    ).fetchall()
    broken = [
        {"src": row["src"], "dst": row["dst"]}
        for row in edge_rows
        if not (root / row["dst"]).exists()
    ]

    # 2. 孤儿文件：存在但未登记（docs / skills 均未收录）
    registered = {row["path"] for row in conn.execute("SELECT path FROM docs")}
    registered |= {row["path"] for row in conn.execute("SELECT path FROM skills")}
    on_disk = {
        path.relative_to(root).as_posix()
        for path in scanner.iter_files(root, config.get("ignore") or [])
    }
    orphans = sorted(on_disk - registered)

    # 3. 索引漂移：哈希不一致或文件已消失
    drift = []
    for row in conn.execute("SELECT path, sha256 FROM docs"):
        path = root / row["path"]
        if not path.exists():
            drift.append({"path": row["path"], "reason": "missing"})
            continue
        try:
            if scanner.sha256_file(path) != row["sha256"]:
                drift.append({"path": row["path"], "reason": "hash_mismatch"})
        except OSError:
            drift.append({"path": row["path"], "reason": "unreadable"})
    for row in conn.execute("SELECT path, sha256 FROM skills"):
        path = root / row["path"]
        if not path.exists():
            drift.append({"path": row["path"], "reason": "missing"})
            continue
        try:
            if scanner.sha256_file(path) != row["sha256"]:
                drift.append({"path": row["path"], "reason": "hash_mismatch"})
        except OSError:
            drift.append({"path": row["path"], "reason": "unreadable"})

    # 4. 技能冲突：重名 / 缺版本 / 触发词重叠 / 文件缺失
    skills = conn.execute(
        "SELECT name, path, version, triggers_json, sha256 FROM skills WHERE status != 'orphan'"
    ).fetchall()
    conflicts = []
    by_name = {}
    digests = {}
    for row in skills:
        by_name.setdefault(row["name"], []).append(row["path"])
        digests[row["path"]] = row["sha256"]
        if not (row["version"] or "").strip():
            conflicts.append({"kind": "missing_version", "skill": row["name"], "path": row["path"]})
    for name, paths in by_name.items():
        if len(paths) > 1:
            # 跨模块同名且内容完全一致：视为有意保留的双份，不判冲突。
            if len({digests.get(p) for p in paths}) == 1:
                continue
            conflicts.append({"kind": "duplicate_name", "skill": name, "paths": sorted(paths)})
    for index, left in enumerate(skills):
        left_triggers = set(_json_load(left["triggers_json"], []))
        for right in skills[index + 1:]:
            if left["sha256"] and left["sha256"] == right["sha256"]:
                continue
            overlap = left_triggers & set(_json_load(right["triggers_json"], []))
            if overlap:
                conflicts.append({
                    "kind": "trigger_overlap",
                    "skills": sorted([left["name"], right["name"]]),
                    "triggers": sorted(overlap),
                })

    # 5. 会话待分拣：超过 TTL 50% 仍未分拣
    ttl_seconds = float(config.get("session_ttl_days") or 7) * 86400
    stale_sessions = conn.execute(
        "SELECT COUNT(*) AS n FROM sessions WHERE triaged_at IS NULL AND (? - created_at) > ?",
        (now, ttl_seconds / 2),
    ).fetchone()["n"]

    # 6. 待定积压
    pending_row = conn.execute(
        "SELECT COUNT(*) AS n, MIN(created_at) AS oldest FROM pending WHERE state='open'"
    ).fetchone()
    pending_backlog = pending_row["n"] or 0
    oldest_hours = 0.0
    if pending_backlog and pending_row["oldest"]:
        oldest_hours = round((now - pending_row["oldest"]) / 3600, 1)

    metrics = {
        "broken_links": len(broken),
        "orphan_files": len(orphans),
        "index_drift": len(drift),
        "skill_conflicts": len(conflicts),
        "stale_sessions": stale_sessions,
        "pending_backlog": pending_backlog,
        "oldest_pending_hours": oldest_hours,
    }

    details = {
        "broken_links": broken[:20],
        "orphan_files": orphans[:20],
        "index_drift": drift[:20],
        "skill_conflicts": conflicts[:20],
        "documented": len(registered),
    }

    # 7. 代码-文档对应（行号越界 / 无文档代码 / 文档漂移）
    try:
        from . import codemap as codemap_module

        code_map = codemap_module.analyze(root, config, conn)
        metrics.update(code_map["metrics"])
        details.update(code_map["details"])
    except Exception as exc:  # 单项检查失败不影响整体体检
        details["code_map_error"] = str(exc)[:200]

    return {
        "schema_version": SCHEMA_VERSION,
        "command": "doctor",
        "workspace": str(root),
        "mode": config.get("mode", "dev"),
        "generated_at": _now_iso(),
        "metrics": metrics,
        "details": details,
        "recommendations": recommendations(metrics, details),
        "health": health_of(metrics),
    }


def recommendations(metrics: dict, details: dict) -> list:
    items = []
    if metrics.get("anchor_out_of_range"):
        items.append("修正行号引用：{} 处文档引用的行号超出目标文件行数，执行 cm map 查看明细".format(
            metrics["anchor_out_of_range"]))
    if metrics.get("code_without_doc"):
        items.append("补文档：{} 个核心模块源码未被任何文档引用，执行 cm map --gaps 查看".format(
            metrics["code_without_doc"]))
    if metrics.get("doc_drift"):
        items.append("复审漂移：{} 处被引用文件已晚于文档更新 3 天以上，确认接口是否变化".format(
            metrics["doc_drift"]))
    if metrics["broken_links"]:
        sample = details["broken_links"][0] if details["broken_links"] else {}
        sample_text = "（例如 {} → {}）".format(sample.get("src", "?"), sample.get("dst", "?")) \
            if sample else ""
        items.append("先修断链：{} 条引用指向不存在的文件{}，优先处理入口索引类文档".format(
            metrics["broken_links"], sample_text))
    if metrics["index_drift"]:
        items.append("修复索引漂移：{} 个文件哈希或存在性不一致，执行 cm scan --full 重建".format(
            metrics["index_drift"]))
    if metrics["orphan_files"]:
        items.append("登记孤儿文件：{} 个文件未被索引，执行 cm scan 纳入管理".format(
            metrics["orphan_files"]))
    if metrics["skill_conflicts"]:
        items.append("收敛技能冲突：{} 处（重名 / 缺版本 / 触发词重叠），合并或补充版本号".format(
            metrics["skill_conflicts"]))
    if metrics["stale_sessions"]:
        items.append("清理会话：{} 条超过 TTL 一半仍未分拣，执行 cm triage（M2）".format(
            metrics["stale_sessions"]))
    if metrics["pending_backlog"]:
        items.append("处理待定：{} 条待复核（最老 {} 小时），执行 cm triage（M2）".format(
            metrics["pending_backlog"], metrics["oldest_pending_hours"]))
    if not items:
        items.append("工作区健康：九类指标均为 0，建议每周运行一次 cm doctor")
    return items[:3]


def format_init(result: dict) -> str:
    status_text = {"created": "已初始化", "existing": "已存在（沿用现有配置）"}
    lines = [
        "{}：{}".format(status_text.get(result["status"], result["status"]), result["workspace"]),
        "模式：{}".format(result["mode"]),
        "状态目录：{}".format(result["cm_dir"]),
        "数据表：schema v{}，FTS5 {}".format(
            result["schema_version"], "可用" if result["fts"] else "不可用（已降级）"),
    ]
    return "\n".join(lines)


def format_scan(stats: dict) -> str:
    return (
        "扫描完成：登记 {scanned} 个文件（文本 {text} / 二进制 {binary}），"
        "技能 {skills} 个，未变化 {unchanged}，失败 {errors}，耗时 {elapsed_seconds}s"
    ).format(**stats)


def format_doctor(result: dict) -> str:
    metrics = result["metrics"]
    rows = [
        (LABELS["broken_links"], metrics["broken_links"]),
        (LABELS["orphan_files"], metrics["orphan_files"]),
        (LABELS["index_drift"], metrics["index_drift"]),
        (LABELS["skill_conflicts"], metrics["skill_conflicts"]),
        (LABELS["stale_sessions"], metrics["stale_sessions"]),
        (LABELS["pending_backlog"], "{}（最老 {} 小时）".format(
            metrics["pending_backlog"], metrics["oldest_pending_hours"])),
        (LABELS["anchor_out_of_range"], metrics.get("anchor_out_of_range", 0)),
        (LABELS["code_without_doc"], metrics.get("code_without_doc", 0)),
        (LABELS["doc_drift"], metrics.get("doc_drift", 0)),
    ]
    health_text = {"good": "健康", "attention": "需要处理", "poor": "问题较多"}
    lines = [
        "认知管家 · 工作区体检（{}）".format(result["mode"]),
        "工作区：{}".format(result["workspace"]),
        "生成时间：{}".format(result["generated_at"]),
        "",
        _table(rows),
        "",
        "结论：{}".format(health_text.get(result["health"], result["health"])),
        "建议：",
    ]
    for index, item in enumerate(result["recommendations"], 1):
        lines.append("{}. {}".format(index, item))
    return "\n".join(lines)


def format_route(result: dict) -> str:
    parts = result.get("confidence_parts", {})
    lines = [
        "认知管家 · 路由（{}）".format(result.get("id", "-")),
        "工作区：{}".format(result.get("workspace", "-")),
        "写入模式：{}".format(result.get("apply_mode", "plan")),
        "",
        "主载体：{}    置信度：{:.2f}".format(
            result.get("primary", "-"), float(result.get("confidence", 0))),
        "分量：evidence={} consistency={} history={} conflict={}".format(
            parts.get("evidence"), parts.get("consistency"),
            parts.get("history"), parts.get("conflict")),
    ]
    attachments = result.get("attachments") or []
    if attachments:
        lines.append("从属引用：")
        for item in attachments:
            lines.append("  - {} ← {}（{}，物化 {}）".format(
                item["target"]["path"], item["edge"], item["route"],
                item.get("materialize", "none")))
    else:
        lines.append("从属引用：无")
    if result.get("alternatives"):
        lines.append("未决候选：{}".format(
            "、".join("{} {:.2f}".format(item["route"], item["confidence"])
                      for item in result["alternatives"])))
    admission_result = result.get("admission") or {}
    if admission_result.get("applicable"):
        checks = admission_result.get("checks", {})
        lines.append("准入：{}（{}）".format(
            admission_result.get("decision"),
            " / ".join("{}={}".format(key, checks[key].get("result"))
                       for key in ("A1", "A2", "A3", "A4") if key in checks)))
    lines.extend([
        "下一步：{}".format(result.get("next_action")),
        "目标：{}".format((result.get("target") or {}).get("path") or "（无文件）"),
    ])
    patch = result.get("patch")
    if patch:
        lines.append("Patch：{}（{}，{}）".format(
            patch.get("summary"), len(patch.get("files", [])),
            "已落盘" if result.get("apply_mode") == "apply" else "未落盘"))
        for item in patch.get("files", []):
            lines.append("  {} {}".format(item["op"], item["path"]))
    apply_result = result.get("apply")
    if apply_result:
        lines.append("写入结果：{}".format(
            "已应用" if apply_result.get("applied") else apply_result.get("reason", "跳过")))
    lines.append("原因：")
    for reason in result.get("reasons", []):
        lines.append("  - {}".format(reason))
    return "\n".join(lines)


def format_mark_done(result: dict) -> str:
    return "已登记执行：指纹 {}（近 90 天 {} 次，source={}）".format(
        result.get("signature"), result.get("executions_90d"), result.get("source"))


def format_rollback(result: dict) -> str:
    if not result.get("rolled_back"):
        lines = ["回滚中止：{}".format(result.get("reason"))]
        for item in result.get("conflicts", []):
            lines.append("  - {}：{}".format(item.get("path"), item.get("reason")))
        return "\n".join(lines)
    lines = ["回滚完成：{}".format(result.get("run_id"))]
    for item in result.get("restored", []):
        action = {"removed": "已删除", "restored": "已还原"}.get(item.get("action"),
                                                                 item.get("action"))
        lines.append("  - {} {}".format(action, item.get("path")))
    return "\n".join(lines)


def format_config(config: dict, updated: list) -> str:
    if updated:
        lines = ["已更新：{}".format(", ".join(updated)), ""]
    else:
        lines = ["当前配置：", ""]
    keys = ("mode", "apply", "high_threshold", "low_threshold", "session_ttl_days",
            "materialize", "max_attachments")
    for key in keys:
        if key in config:
            lines.append("{}: {}".format(key, config[key]))
    return "\n".join(lines)


def format_pack(result: dict) -> str:
    lines = [
        "认知管家 · 上下文打包（只读）",
        "查询：{}".format(result.get("query", "-")),
        "预算：{}    估算：{} tokens    命中：{} 条".format(
            result.get("budget"), result.get("estimated_tokens"), result.get("item_count")),
        "",
    ]
    for index, item in enumerate(result.get("items", []), 1):
        lines.append("{}. {}  [{}，{} tokens，score {}]".format(
            index, item["path"], item.get("kind", "-"),
            item.get("estimated_tokens", 0), item.get("score", 0)))
        lines.append("   {}".format(item.get("reason", "")))
    if not result.get("items"):
        lines.append("（无命中）")
    for note in result.get("notes", []):
        lines.append("提示：{}".format(note))
    return "\n".join(lines)


def format_triage(result: dict) -> str:
    sessions = result.get("sessions", {})
    pending = result.get("pending", {})
    lines = [
        "认知管家 · 分拣{}".format("（演练）" if result.get("dry_run") else ""),
        "过期会话：{} 条（本次回收 {} 条）".format(
            sessions.get("expired", 0), sessions.get("marked_expired", 0)),
    ]
    for item in sessions.get("items", []):
        lines.append("  - #{} {}（创建 {}）".format(
            item["id"], item.get("content_ref", "-"), item.get("created_at", "-")))
    lines.append("待定项：{} 条（丢弃 {} / 复核 {}）".format(
        pending.get("open", 0), pending.get("dropped", 0), pending.get("incremented", 0)))
    for item in pending.get("items", []):
        lines.append("  - #{} {} 复核 {} 次（{} 小时）".format(
            item["id"], item.get("payload_ref", "-"),
            item.get("review_count", 0), item.get("age_hours", 0)))
    for note in result.get("notes", []):
        lines.append("提示：{}".format(note))
    return "\n".join(lines)


def format_index(result: dict) -> str:
    counts = result["counts"]
    rows = [
        ("文档总数", counts["docs"]),
        ("技能总数", counts["skills"]),
        ("断链", counts["broken_links"]),
        ("孤儿文件", counts["orphan_files"]),
        ("索引漂移", counts["index_drift"]),
    ]
    lines = [
        "认知管家 · 索引（{}）".format(result["mode"]),
        "工作区：{}".format(result["workspace"]),
        "生成时间：{}".format(result["generated_at"]),
        "",
        _table(rows),
    ]
    broken = result["details"].get("broken_links") or []
    if broken:
        lines.append("")
        lines.append("断链样例：")
        for item in broken[:5]:
            lines.append("  - {} → {}".format(item.get("src"), item.get("dst")))
    orphans = result["details"].get("orphan_files") or []
    if orphans:
        lines.append("")
        lines.append("孤儿样例：")
        for item in orphans[:5]:
            lines.append("  - {}".format(item))
    for note in result.get("notes", []):
        lines.append("提示：{}".format(note))
    return "\n".join(lines)


def format_skill_lint(result: dict) -> str:
    summary = result["summary"]
    lines = [
        "认知管家 · 技能检查",
        "工作区：{}".format(result["workspace"]),
        "技能数：{}    问题：{}（错误 {} / 警告 {}）".format(
            summary["skills"], summary["total"], summary["error"], summary["warning"]),
    ]
    issues = result.get("issues") or []
    if not issues:
        lines.append("结论：未发现问题")
        return "\n".join(lines)
    lines.append("")
    for position, item in enumerate(issues, 1):
        lines.append("{}. [{}] {}：{}".format(
            position, item["severity"], item["kind"], item["detail"]))
    return "\n".join(lines)


def _table(rows) -> str:
    width = max(_display_width(label) for label, _ in rows)
    return "\n".join(
        "{}{}  {}".format(label, " " * (width - _display_width(label)), value)
        for label, value in rows
    )


def _display_width(text) -> int:
    return sum(
        2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
        for char in str(text)
    )


def to_json(payload) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)
