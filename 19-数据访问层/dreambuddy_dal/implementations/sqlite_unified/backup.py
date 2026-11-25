"""
dreambuddy_dal.implementations.sqlite_unified.backup
-----------------------------------------------------
P3-1 全量备份 + SHA256 校验 + AES256 加密

入口：
  backup_database(db_path, backup_dir, *, encrypt=True, passphrase=None) → str
  verify_backup(backup_path, *, passphrase=None) → bool

设计（对齐 MIGRATION_PLAN §4.1）：
  1. VACUUM INTO 做在线全量备份（不锁库，WAL-safe）
  2. SHA256 校验和写 .sha256 sidecar
  3. AES256-GCM 加密（passphrase 非 None 时；否则明文 .db）
"""

from __future__ import annotations

import hashlib
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from dreambuddy_dal.connection import get_sqlite_connection

# 备份需要与源库等量的额外空间（VACUUM INTO 写全新副本），留 20% 余量
_REQUIRED_FREE_RATIO = 1.2


def _aes256_encrypt(plaintext: bytes, passphrase: str) -> bytes:
    """AES256-GCM 加密；返回 nonce + ciphertext + tag。"""

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    # 派生 32 字节密钥（SHA256）
    key = hashlib.sha256(passphrase.encode("utf-8")).digest()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ct = aesgcm.encrypt(nonce, plaintext, None)
    # 格式: nonce(12) + ct
    return nonce + ct


def _aes256_decrypt(ciphertext: bytes, passphrase: str) -> bytes:
    """AES256-GCM 解密。"""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = hashlib.sha256(passphrase.encode("utf-8")).digest()
    aesgcm = AESGCM(key)
    nonce = ciphertext[:12]
    ct = ciphertext[12:]
    return aesgcm.decrypt(nonce, ct, None)


def backup_database(
    db_path: str,
    backup_dir: str,
    *,
    encrypt: bool = True,
    passphrase: str | None = None,
) -> str:
    """全量备份 → 返回备份文件路径。"""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    Path(backup_dir).mkdir(parents=True, exist_ok=True)

    # Step 0: 空间预检（不足时明确失败，避免写半截副本残留占满磁盘）
    db_size = os.path.getsize(db_path)
    free = shutil.disk_usage(backup_dir).free
    required = int(db_size * _REQUIRED_FREE_RATIO)
    if free < required:
        raise RuntimeError(
            f"磁盘空间不足，无法备份: 需要约 {required / 2**30:.1f}G，"
            f"可用 {free / 2**30:.1f}G（库 {db_size / 2**30:.1f}G）。"
            f"请先执行 deploy/ops/cleanup-cloud-backups.sh 清理旧备份。"
        )

    # Step 1: VACUUM INTO 做明文备份
    plain_path = os.path.join(backup_dir, f"dreambuddy_core_{ts}.db.tmp")
    try:
        with get_sqlite_connection(db_path) as conn:
            conn.execute(f"VACUUM INTO '{plain_path}'")

        with open(plain_path, "rb") as f:
            plain_data = f.read()

        # Step 2: 加密 or 明文
        if encrypt and passphrase:
            enc_data = _aes256_encrypt(plain_data, passphrase)
            final_path = plain_path.replace(".db.tmp", ".db.enc")
            with open(final_path, "wb") as f:
                f.write(enc_data)
            os.unlink(plain_path)
        else:
            final_path = plain_path.replace(".db.tmp", ".db")
            os.rename(plain_path, final_path)
    except BaseException:
        # 失败时清理残留的 .tmp 与其 journal，避免 disk-full 循环恶化
        for leftover in (plain_path, plain_path + "-journal"):
            if os.path.exists(leftover):
                try:
                    os.unlink(leftover)
                except OSError:
                    pass
        raise

    # Step 3: SHA256 sidecar
    with open(final_path, "rb") as f:
        sha256 = hashlib.sha256(f.read()).hexdigest()
    sha_path = final_path + ".sha256"
    with open(sha_path, "w") as f:
        f.write(sha256)

    return final_path


def verify_backup(backup_path: str, *, passphrase: str | None = None) -> bool:
    """验证备份完整性：SHA256 校验 + 解密测试。"""
    p = Path(backup_path)
    if not p.exists():
        return False

    # SHA256 校验
    sha_path = backup_path + ".sha256"
    if not os.path.exists(sha_path):
        return False
    with open(sha_path, "r") as f:
        expected_sha = f.read().strip()
    with open(backup_path, "rb") as f:
        actual_sha = hashlib.sha256(f.read()).hexdigest()
    if actual_sha != expected_sha:
        return False

    # 加密备份：解密验证
    if backup_path.endswith(".enc"):
        if not passphrase:
            return False
        try:
            with open(backup_path, "rb") as f:
                enc_data = f.read()
            plain_data = _aes256_decrypt(enc_data, passphrase)
            # 验证解密后是合法 SQLite 文件（前 16 字节 "SQLite format 3\x00"）
            if not plain_data[:16] == b"SQLite format 3\x00":
                return False
        except Exception:
            return False

    return True


__all__ = ["backup_database", "verify_backup"]
