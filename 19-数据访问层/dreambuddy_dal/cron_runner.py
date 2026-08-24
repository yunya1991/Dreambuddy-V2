#!/usr/bin/env python3
"""
dreambuddy_dal CLI — Cron 三件套统一入口
==========================================
launchd/cron 调用此脚本，通过子命令选择 backup / integrity / rotate。

用法：
  python -m dreambuddy_dal.cron_runner backup   --db-path /path/to/db --backup-dir /path/to/backups [--no-encrypt] [--passphrase ENV_VAR]
  python -m dreambuddy_dal.cron_runner integrity --db-path /path/to/db
  python -m dreambuddy_dal.cron_runner rotate    --backup-dir /path/to/backups --keep 7
  python -m dreambuddy_dal.cron_runner checkpoint --db-path /path/to/db

环境变量（launchd plist 中设置）：
  DATA_DIR       — 数据根目录（默认 ./data）
  DAL_DB_PATH    — 统一库路径（默认 $DATA_DIR/dreambuddy_core.db）
  BACKUP_DIR     — 备份目录（默认 $DATA_DIR/backups）
  BACKUP_PASSPHRASE — AES256 加密口令（未设则明文备份）
  BACKUP_KEEP    — 轮转保留份数（默认 7）
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

_log = logging.getLogger("dreambuddy_dal.cron")


def _get_db_path(args):
    return args.db_path or os.environ.get(
        "DAL_DB_PATH",
        os.path.join(os.environ.get("DATA_DIR", "./data"), "dreambuddy_core.db"),
    )


def _get_backup_dir(args):
    return args.backup_dir or os.environ.get(
        "BACKUP_DIR",
        os.path.join(os.environ.get("DATA_DIR", "./data"), "backups"),
    )


def _get_passphrase():
    return os.environ.get("BACKUP_PASSPHRASE", None)


def cmd_backup(args):
    from dreambuddy_dal.implementations.sqlite_unified.backup import backup_database
    db_path = _get_db_path(args)
    backup_dir = _get_backup_dir(args)
    passphrase = _get_passphrase()
    encrypt = not args.no_encrypt
    if encrypt and not passphrase:
        _log.warning("加密启用但 BACKUP_PASSPHRASE 未设 → 明文备份")
        encrypt = False
    path = backup_database(db_path, backup_dir, encrypt=encrypt, passphrase=passphrase)
    _log.info("备份完成: %s", path)
    print(f"BACKUP_OK: {path}")


def cmd_integrity(args):
    from dreambuddy_dal.implementations.sqlite_unified.integrity import run_integrity_check
    db_path = _get_db_path(args)
    result = run_integrity_check(db_path)
    if result.ok:
        print("INTEGRITY_OK")
    else:
        print(f"INTEGRITY_FAIL: errors={result.errors[:5]} fk={result.fk_violations[:5]}")
        sys.exit(1)


def cmd_rotate(args):
    from dreambuddy_dal.implementations.sqlite_unified.rotate import rotate_backups
    backup_dir = _get_backup_dir(args)
    keep = args.keep or int(os.environ.get("BACKUP_KEEP", "7"))
    deleted = rotate_backups(backup_dir, keep=keep)
    print(f"ROTATE_OK: deleted={len(deleted)} files, kept={keep}")


def cmd_checkpoint(args):
    from dreambuddy_dal.implementations.sqlite_unified.rotate import wal_checkpoint
    db_path = _get_db_path(args)
    pages = wal_checkpoint(db_path)
    print(f"CHECKPOINT_OK: {pages} pages")


def main():
    parser = argparse.ArgumentParser(description="dreambuddy_dal cron 三件套")
    sub = parser.add_subparsers(dest="command", required=True)

    p_backup = sub.add_parser("backup", help="全量备份")
    p_backup.add_argument("--db-path", default=None)
    p_backup.add_argument("--backup-dir", default=None)
    p_backup.add_argument("--no-encrypt", action="store_true")
    p_backup.add_argument("--keep", type=int, default=None)

    p_integrity = sub.add_parser("integrity", help="完整性检查")
    p_integrity.add_argument("--db-path", default=None)

    p_rotate = sub.add_parser("rotate", help="旧备份轮转")
    p_rotate.add_argument("--backup-dir", default=None)
    p_rotate.add_argument("--keep", type=int, default=None)

    p_checkpoint = sub.add_parser("checkpoint", help="WAL checkpoint")
    p_checkpoint.add_argument("--db-path", default=None)

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.command == "backup":
        cmd_backup(args)
    elif args.command == "integrity":
        cmd_integrity(args)
    elif args.command == "rotate":
        cmd_rotate(args)
    elif args.command == "checkpoint":
        cmd_checkpoint(args)


if __name__ == "__main__":
    main()
