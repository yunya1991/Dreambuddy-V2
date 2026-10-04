#!/usr/bin/env python3
"""
文档索引 HTTP Adapter — 单次请求模式调用 doc_sync_trigger.py 的只读接口 + 扫描文档目录。

用法:
  python3 doc_index_adapter.py list '{}'
  python3 doc_index_adapter.py list '{"root":"0-系统文档管理"}'
  python3 doc_index_adapter.py scan '{}'
  python3 doc_index_adapter.py sync '{}'

stdout: 单行 JSON {"ok": true, "data": {...}} 或 {"ok": false, "error": "..."}
stderr: 错误日志 + import 噪音

设计:
  - 复刻 P0 cognitive_adapter.py + P1 skill_index_adapter.py 的 stdout→stderr 重定向模式 (VM-1789618914215)
  - 只读不改后端: list 扫描文档目录; sync 调用 DocSyncTrigger.sync() 触发认知 record
  - 不改 doc_sync_trigger.py 后端, 仅在 3.1-FRONTEND 接入层新增 adapter
  - FAIL-OPEN: 异常返回 {ok: false, error, traceback}, 不崩溃

复用已有后端能力 (VM-1790871681293):
  - DocSyncTrigger(project_root, record_fn=None, sync_fn=None) — FAIL-OPEN 自动加载认知 record
  - detect_changes(before, after) — 检测变更
  - scan_checksums() — 扫描跟踪文件
  - sync(changes) — 触发同步 + 认知库 record
"""
import sys
import os
import json
import traceback
from datetime import datetime, timezone
from pathlib import Path


def _resolve_project_root():
    """解析 dreambuddy-v2 仓库根路径。"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # 3.1-FRONTEND/scripts/ → ../../ = dreambuddy-v2/
    candidate1 = os.path.normpath(os.path.join(script_dir, '..', '..'))
    if os.path.exists(os.path.join(candidate1, '4-MEMORY')):
        return candidate1
    candidate2 = '/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2'
    if os.path.exists(os.path.join(candidate2, '4-MEMORY')):
        return candidate2
    return candidate1


def _safe_print(payload):
    """唯一向 stdout 输出的入口，确保单行 JSON。"""
    sys.stdout = sys.__stdout__
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + '\n')
    sys.stdout.flush()


def _file_mtime_iso(path: Path) -> str:
    """返回文件 mtime ISO 格式（带 Z）。"""
    try:
        ts = path.stat().st_mtime
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace('+00:00', 'Z')
    except (OSError, IOError):
        return ''


def _derive_category(rel_path: str, root_name: str) -> str:
    """从相对路径推导五件套分类。"""
    # 0-系统文档管理/1-规范体系/... → "1-规范体系"
    # 2-KNOWLEDGE/1-TRADING/... → "1-TRADING"
    parts = rel_path.replace('\\', '/').split('/')
    if len(parts) >= 2:
        second = parts[1]
        # 跳过 archive 目录，归到 "archive"
        if second == 'archive' and len(parts) >= 3:
            return f"archive/{parts[2]}" if len(parts) >= 3 else 'archive'
        return second
    return root_name


def _scan_docs(project_root: Path, root_name: str, ignore_dirs=None):
    """扫描指定根目录下的 .md 文件，返回 DocItem 列表。"""
    if ignore_dirs is None:
        ignore_dirs = {'archive', 'node_modules', '.git', '__pycache__', '.next', 'dist', 'build'}
    root_dir = project_root / root_name
    if not root_dir.exists():
        return []

    items = []
    for path in root_dir.rglob('*.md'):
        try:
            rel_to_root = path.relative_to(root_root := root_dir)
        except ValueError:
            continue
        rel_parts = path.relative_to(project_root).parts
        rel_path = '/'.join(rel_parts)

        # 跳过 ignore_dirs
        if any(ignored in rel_parts for ignored in ignore_dirs):
            continue

        category = _derive_category(rel_path, root_name)
        items.append({
            'path': rel_path,
            'root': root_name,
            'category': category,
            'last_synced': _file_mtime_iso(path),
            'cognitive_linked': False,  # 默认 false，sync 后由前端根据 memory_id 标记
            'size_bytes': path.stat().st_size if path.exists() else 0,
        })
    return items


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
        project_root = Path(_resolve_project_root())
    except Exception as e:
        _safe_print({
            "ok": False,
            "error": f"resolve_root_failed: {type(e).__name__}: {e}",
            "traceback": traceback.format_exc(),
        })
        return

    try:
        if command == "list":
            # 扫描 0-系统文档管理 + 2-KNOWLEDGE 目录
            roots = args.get('roots') or ['0-系统文档管理', '2-KNOWLEDGE']
            if isinstance(roots, str):
                roots = [roots]
            all_items = []
            for root_name in roots:
                all_items.extend(_scan_docs(project_root, root_name))
            # 按路径排序
            all_items.sort(key=lambda x: x['path'])
            _safe_print({
                "ok": True,
                "data": {
                    "schema_version": "1.0",
                    "count": len(all_items),
                    "docs": all_items,
                    "roots_scanned": roots,
                }
            })

        elif command == "scan":
            # 调用 DocSyncTrigger.scan_checksums() 返回跟踪文件清单
            sys.path.insert(0, str(project_root / '1-ARCHITECTURE' / 'dreamos' / 'core' / 'compute'))
            from doc_sync_trigger import DocSyncTrigger  # noqa
            trigger = DocSyncTrigger(project_root=project_root)
            checksums = trigger.scan_checksums()
            _safe_print({
                "ok": True,
                "data": {
                    "count": len(checksums),
                    "files": sorted(checksums.keys()),
                }
            })

        elif command == "sync":
            # 手动触发 doc-sync → 认知库 record（快速模式：直接 record，不扫描全量文件）
            # 完整扫描模式见 scan + sync_full（scan_checksums 扫描 4000+ 文件需 >20s）
            sys.path.insert(0, str(project_root / '1-ARCHITECTURE' / 'dreamos' / 'core' / 'compute'))
            from doc_sync_trigger import DocSyncTrigger  # noqa
            trigger = DocSyncTrigger(project_root=project_root)
            record_fn = trigger._record_fn
            if not record_fn:
                _safe_print({
                    "ok": False,
                    "error": "no record_fn available (cognitive system not loaded)",
                })
                return
            mem_id = record_fn(
                content=(
                    "[文档自同步-手动触发] 用户从 dashboard 手动触发 doc-sync。"
                    "Tags 含 doc-sync → TAG_HOOKS 触发 dream-doc-sync-workflow 完整链路。"
                    "本次为快速模式（不扫描全量文件，直接 record）。"
                ),
                quality_level="B",
                tags="doc-sync,文档索引,手动触发,认知闭环,L4自迭代",
            )
            _safe_print({
                "ok": True,
                "data": {
                    "action": "sync",
                    "index_updated": False,
                    "knowledge_updated": False,
                    "lint_passed": False,
                    "recorded": bool(mem_id),
                    "memory_id": mem_id,
                    "reason": "manual record (fast mode, no full scan)",
                    "synced_at": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                    "files_scanned": 0,
                }
            })

        else:
            _safe_print({
                "ok": False,
                "error": f"unknown command: {command}. available: list, scan, sync",
            })

    except Exception as e:
        _safe_print({
            "ok": False,
            "error": f"handler_error: {type(e).__name__}: {e}",
            "traceback": traceback.format_exc(),
        })


if __name__ == "__main__":
    main()
