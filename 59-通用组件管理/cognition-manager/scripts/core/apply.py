"""写入执行与回滚。

契约见 references/routing-matrix.md §写入安全：
- 单次最多 10 个文件，超出由调用方降级 plan
- apply 前把受影响文件快照到 `.cm/backup/<run_id>/` 并写 manifest.json
- `cm rollback <run_id>` 按 manifest 逆序恢复，并校验哈希
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path

from . import store

MAX_FILES = 10
VALID_OPS = ("create", "modify", "delete")
RUN_ID_RE = re.compile(r"^rt-\d{8}-\d{4}$")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _safe_path(root: Path, rel: str) -> Path:
    raw = (rel or "").strip()
    if not raw or raw.startswith("/") or raw.startswith(".."):
        raise store.CmError(store.EXIT_USAGE, "非法路径：{}".format(rel))
    target = (root / raw).resolve()
    if target != root and root not in target.parents:
        raise store.CmError(store.EXIT_USAGE, "路径越界：{}".format(rel))
    return target


def _backup_dir(root: Path, run_id: str) -> Path:
    if not RUN_ID_RE.match(run_id or ""):
        raise store.CmError(store.EXIT_USAGE, "非法 run_id：{}".format(run_id))
    return store.cm_dir(root) / store.BACKUP_DIR / run_id


def _manifest_path(root: Path, run_id: str) -> Path:
    return _backup_dir(root, run_id) / "manifest.json"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".cm-tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def find_applied(conn, idempotency_key: str):
    row = conn.execute(
        "SELECT run_id, idempotency_key, rolled_back_at FROM apply_runs "
        "WHERE idempotency_key = ?",
        (idempotency_key,),
    ).fetchone()
    if not row:
        return None
    return {
        "run_id": row["run_id"],
        "idempotency_key": row["idempotency_key"],
        "rolled_back_at": row["rolled_back_at"],
    }


def _validate(patch: dict) -> list:
    files = (patch or {}).get("files") or []
    if not files:
        raise store.CmError(store.EXIT_USAGE, "patch 为空，禁止 apply")
    if len(files) > MAX_FILES:
        raise store.CmError(store.EXIT_USAGE,
                            "patch 超过 {} 个文件，禁止 apply".format(MAX_FILES))
    seen = set()
    for entry in files:
        op = entry.get("op")
        if op not in VALID_OPS:
            raise store.CmError(store.EXIT_USAGE, "非法 op：{}".format(op))
        path = entry.get("path")
        if not path:
            raise store.CmError(store.EXIT_USAGE, "patch 条目缺少 path")
        if path in seen:
            raise store.CmError(store.EXIT_USAGE, "patch 存在重复路径：{}".format(path))
        seen.add(path)
        if op in ("create", "modify"):
            expected = _sha256_text(entry.get("content") or "")
            if entry.get("sha256") and entry["sha256"] != expected:
                raise store.CmError(store.EXIT_USAGE,
                                    "patch 哈希不一致：{}".format(path))
    return files


def apply_patch(root, run_id: str, idempotency_key: str, patch: dict, conn=None) -> dict:
    """快照 + 落盘；返回执行摘要。"""
    root = Path(root).expanduser().resolve()
    files = _validate(patch)
    backup_root = _backup_dir(root, run_id)
    backup_files = backup_root / "files"
    backup_root.mkdir(parents=True, exist_ok=True)

    replay = find_applied(conn, idempotency_key) if conn is not None else None
    if replay:
        return {
            "applied": False,
            "replayed": True,
            "run_id": replay["run_id"],
            "reason": "idempotency_key 已应用，跳过重复写入",
        }

    prepared = []
    for entry in files:
        target = _safe_path(root, entry["path"])
        existed = target.exists()
        op = entry["op"]
        if op == "create" and existed:
            raise store.CmError(store.EXIT_IO, "create 目标已存在：{}".format(entry["path"]))
        if op in ("modify", "delete") and not existed:
            raise store.CmError(store.EXIT_IO, "{} 目标不存在：{}".format(op, entry["path"]))
        before_sha = _sha256_file(target) if existed else None
        backup_path = None
        if existed:
            backup_path = backup_files / entry["path"]
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup_path)
        prepared.append({
            "op": op,
            "path": entry["path"],
            "after_sha256": _sha256_text(entry.get("content") or "") if op != "delete" else None,
            "before": {
                "existed": existed,
                "sha256": before_sha,
                "backup": str(backup_path.relative_to(backup_root)) if backup_path else None,
            },
        })

    manifest = {
        "run_id": run_id,
        "idempotency_key": idempotency_key,
        "created_at": time.time(),
        "status": "prepared",
        "files": prepared,
    }
    manifest_file = _manifest_path(root, run_id)
    manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                             encoding="utf-8")

    for entry, item in zip(files, prepared):
        target = _safe_path(root, item["path"])
        if item["op"] == "delete":
            target.unlink()
            continue
        _atomic_write(target, entry.get("content") or "")
        actual = _sha256_file(target)
        if actual != item["after_sha256"]:
            raise store.CmError(store.EXIT_IO, "写入校验失败：{}".format(item["path"]))

    manifest["status"] = "applied"
    manifest["applied_at"] = time.time()
    manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                             encoding="utf-8")

    if conn is not None:
        conn.execute(
            "INSERT INTO apply_runs(run_id, idempotency_key, created_at, mode, "
            "files_json, manifest_ref, rolled_back_at) "
            "VALUES(?, ?, ?, 'apply', ?, ?, NULL)",
            (run_id, idempotency_key, manifest["created_at"],
             json.dumps([item["path"] for item in prepared], ensure_ascii=False),
             str(manifest_file.relative_to(root))),
        )
        conn.commit()

    return {
        "applied": True,
        "replayed": False,
        "run_id": run_id,
        "files": [item["path"] for item in prepared],
        "backup": str(backup_root),
        "manifest": str(manifest_file),
    }


def rollback(root, run_id: str, conn=None) -> dict:
    """按 manifest 逆序恢复；哈希不一致时整体中止，不做半途回滚。"""
    root = Path(root).expanduser().resolve()
    manifest_file = _manifest_path(root, run_id)
    if not manifest_file.exists():
        raise store.CmError(store.EXIT_USAGE, "未找到备份：{}".format(run_id))
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if manifest.get("status") != "applied":
        raise store.CmError(store.EXIT_USAGE,
                            "run {} 状态为 {}，无法回滚".format(run_id, manifest.get("status")))

    conflicts = []
    for item in manifest.get("files", []):
        target = _safe_path(root, item["path"])
        if item["op"] == "delete":
            if target.exists():
                conflicts.append({"path": item["path"], "reason": "删除类应不存在"})
            continue
        if not target.exists():
            conflicts.append({"path": item["path"], "reason": "文件缺失"})
            continue
        if _sha256_file(target) != item.get("after_sha256"):
            conflicts.append({"path": item["path"], "reason": "hash_mismatch"})

    if conflicts:
        return {
            "rolled_back": False,
            "run_id": run_id,
            "conflicts": conflicts,
            "reason": "文件已被后续修改，回滚中止",
        }

    backup_root = _backup_dir(root, run_id)
    restored = []
    for item in reversed(manifest.get("files", [])):
        target = _safe_path(root, item["path"])
        if item["op"] == "create":
            if target.exists():
                target.unlink()
            restored.append({"path": item["path"], "action": "removed"})
            continue
        backup_rel = item.get("before", {}).get("backup")
        if not backup_rel:
            continue
        source = backup_root / backup_rel
        if not source.exists():
            raise store.CmError(store.EXIT_IO, "备份缺失：{}".format(item["path"]))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        expected = item.get("before", {}).get("sha256")
        if expected and _sha256_file(target) != expected:
            raise store.CmError(store.EXIT_IO, "恢复校验失败：{}".format(item["path"]))
        restored.append({"path": item["path"], "action": "restored"})

    manifest["status"] = "rolled_back"
    manifest["rolled_back_at"] = time.time()
    manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                             encoding="utf-8")
    if conn is not None:
        conn.execute("UPDATE apply_runs SET rolled_back_at = ? WHERE run_id = ?",
                     (manifest["rolled_back_at"], run_id))
        conn.commit()

    return {
        "rolled_back": True,
        "run_id": run_id,
        "restored": restored,
        "manifest": str(manifest_file),
    }
