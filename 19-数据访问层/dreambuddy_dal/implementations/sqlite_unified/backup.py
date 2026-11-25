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
# 流式处理块大小：避免把整库读进内存（18G 库曾导致 6.4G 内存峰值被 oomd 杀）
_CHUNK_SIZE = 8 * 1024 * 1024


def _sha256_file(path: str) -> str:
    """流式计算文件 SHA256。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


def _aes256_encrypt_file(src: str, dst: str, passphrase: str) -> None:
    """流式 AES256-GCM 加密文件；输出格式 nonce(12) + ciphertext + tag(16)。"""

    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    key = hashlib.sha256(passphrase.encode("utf-8")).digest()
    nonce = os.urandom(12)
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    with open(src, "rb") as fin, open(dst, "wb") as fout:
        fout.write(nonce)
        for chunk in iter(lambda: fin.read(_CHUNK_SIZE), b""):
            fout.write(encryptor.update(chunk))
        fout.write(encryptor.finalize())
        fout.write(encryptor.tag)


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

        # Step 2: 加密 or 明文（均为流式，不整库读入内存）
        if encrypt and passphrase:
            final_path = plain_path.replace(".db.tmp", ".db.enc")
            _aes256_encrypt_file(plain_path, final_path, passphrase)
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
    sha256 = _sha256_file(final_path)
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
    actual_sha = _sha256_file(backup_path)
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
