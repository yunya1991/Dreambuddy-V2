#!/usr/bin/env python3
"""
Skill 索引 HTTP Adapter — 单次请求模式调用 skill_indexer.py 的只读接口。

用法:
  python3 skill_index_adapter.py list '{}'
  python3 skill_index_adapter.py query '{"trigger":"recall","category":"memory","status":"active"}'
  python3 skill_index_adapter.py drift '{}'
  python3 skill_index_adapter.py conflicts '{}'

stdout: 单行 JSON {"ok": true, "data": {...}} 或 {"ok": false, "error": "..."}
stderr: 错误日志 + import 噪音

设计:
  - 复刻 P0 cognitive_adapter.py stdout→stderr 重定向模式 (VM-1789618914215)
  - 只读不改: 调用 scan_skills / build_registry / detect_drift / detect_conflicts
  - 不改 skill_indexer.py 后端, 仅在 3.1-FRONTEND 接入层新增 adapter
  - FAIL-OPEN: 异常返回 {ok: false, error, traceback}, 不崩溃

复用已有后端能力 (VM-1790871057901):
  - skill_indexer.scan_skills / build_registry / detect_drift / detect_conflicts
  - record_hook / verify_hook 已实现（不在本 adapter 暴露，只读）
"""
import sys
import os
import json
import traceback


def _resolve_skill_indexer_dir():
    """解析 1-ARCHITECTURE/skills/dream-skill-index-governance 绝对路径。"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidate1 = os.path.normpath(os.path.join(
        script_dir, '..', '1-ARCHITECTURE', 'skills', 'dream-skill-index-governance'
    ))
    if os.path.exists(candidate1):
        return candidate1
    candidate2 = '/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/skills/dream-skill-index-governance'
    if os.path.exists(candidate2):
        return candidate2
    return candidate1


def _safe_print(payload):
    """唯一向 stdout 输出的入口，确保单行 JSON。"""
    sys.stdout = sys.__stdout__
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + '\n')
    sys.stdout.flush()


def main():
    if len(sys.argv) < 2:
        _safe_print({"ok": False, "error": "missing command argument"})
        return

    command = sys.argv[1]
    args_raw = sys.argv[2] if len(sys.argv) > 2 else '{}'
    try:
        args = json.loads(args_raw) if args_raw else {}
    except json.JSONDecodeError as e:
        _safe_print({"ok": False, "error": f"invalid args JSON: {e}"})
        return

    # === 关键: import 和 handler 执行期间把 stdout 重定向到 stderr ===
    sys.stdout = sys.stderr

    try:
        skill_dir = _resolve_skill_indexer_dir()
        if skill_dir not in sys.path:
            sys.path.insert(0, skill_dir)
        from skill_indexer import (
            ALL_SKILL_ROOTS, scan_skills, build_registry,
            detect_drift, detect_conflicts,
        )
    except Exception as e:
        _safe_print({
            "ok": False,
            "error": f"import_failed: {type(e).__name__}: {e}",
            "traceback": traceback.format_exc(),
        })
        return

    try:
        roots = ALL_SKILL_ROOTS
        entries = scan_skills(roots)

        if command == "list":
            # 返回完整 registry（含所有 Skill 元数据）
            registry = build_registry(entries)
            _safe_print({"ok": True, "data": registry})

        elif command == "query":
            # 按 trigger / category / status 过滤
            trigger = args.get("trigger")
            category = args.get("category")
            status = args.get("status")
            matched = []
            for e in entries:
                if trigger is not None and trigger not in e.triggers:
                    continue
                if category is not None and e.category != category:
                    continue
                if status is not None and e.status != status:
                    continue
                matched.append({
                    "name": e.name,
                    "description": e.description,
                    "version": e.version,
                    "status": e.status,
                    "category": e.category,
                    "triggers": e.triggers,
                    "cognitive_links": e.cognitive_links,
                    "confidence": e.confidence,
                    "apply_count": e.apply_count,
                    "last_verified": e.last_verified,
                    "path": str(e.path),
                })
            _safe_print({
                "ok": True,
                "data": {
                    "schema_version": "1.0",
                    "count": len(matched),
                    "skills": matched,
                }
            })

        elif command == "drift":
            drift = detect_drift(entries)
            _safe_print({"ok": True, "data": drift})

        elif command == "conflicts":
            conflicts = detect_conflicts(entries)
            _safe_print({"ok": True, "data": conflicts})

        elif command == "stats":
            # 聚合统计：按 status / category 分组
            by_status = {}
            by_category = {}
            for e in entries:
                by_status[e.status] = by_status.get(e.status, 0) + 1
                by_category[e.category] = by_category.get(e.category, 0) + 1
            _safe_print({
                "ok": True,
                "data": {
                    "total_count": len(entries),
                    "by_status": by_status,
                    "by_category": by_category,
                    "roots_scanned": len(roots),
                }
            })

        else:
            _safe_print({
                "ok": False,
                "error": f"unknown command: {command}. available: list, query, drift, conflicts, stats",
            })

    except Exception as e:
        _safe_print({
            "ok": False,
            "error": f"handler_error: {type(e).__name__}: {e}",
            "traceback": traceback.format_exc(),
        })


if __name__ == "__main__":
    main()
