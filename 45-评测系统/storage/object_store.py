# -*- coding: utf-8 -*-
"""
object_store.py — WORM 对象存储（P4-2）
=======================================
职责（PLAN P4-2 / SPEC §14.4/§15）：
- 对象锁（compliance）：保留期内禁止覆盖 / 删除；到期后允许新版本追加
- 保留期策略可配：`config/object_store.yaml` + 环境变量；默认按 §15 分级
  （报告 ≥3 年、证据 ≥1 年、审计 ≥1 年）
- LocalWormStore：本地只读落盘 + 元数据（sha256/version_id/retention_until），
  供单测与单机部署；MinioWormStore：MinIO Object Lock（需 `minio` 依赖）

边界：
- 本层只负责对象读写与锁语义，不承担 PG 索引（URI 回到 §12 evidence 表）
- MinIO 模式在依赖缺失时 fail-closed（禁止静默降级为本地存储）
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, ClassVar, Mapping

import yaml

from storage.repo import canonical_json, zulu

logger = logging.getLogger(__name__)

MODULE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = MODULE_ROOT / "config" / "object_store.yaml"
META_SUFFIX = ".worm.json"
URI_PREFIX = "local://worm/"


class ObjectStoreError(Exception):
    """对象存储操作失败：非法 key / 对象不存在 / 配置缺失等。"""


class WormViolation(ObjectStoreError):
    """对象锁拒绝：保留期内覆盖或删除。"""


# ---------- 保留期策略 ----------


@dataclass(frozen=True)
class RetentionPolicy:
    """按对象类别分级的保留期（天）；未配置类别取 SPEC §15 默认。"""

    DEFAULT_DAYS: ClassVar[int] = 365

    days: Mapping[str, int] = field(default_factory=dict)

    def days_for(self, kind: str) -> int:
        if kind in self.days:
            return int(self.days[kind])
        return int(DEFAULT_RETENTION_DAYS.get(kind, self.DEFAULT_DAYS))


# SPEC §15 保留期下限：评测记录与报告 ≥3 年、证据 ≥1 年、审计 ≥1 年
DEFAULT_RETENTION_DAYS: dict[str, int] = {"evidence": 365, "report": 1095, "audit": 365}


def load_retention_policy(path: str | Path | None = None) -> RetentionPolicy:
    """读取 `retention_days` 配置；文件缺失或空配置回退 SPEC 默认。"""
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    if not config_path.is_file():
        return RetentionPolicy()
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return RetentionPolicy(dict(data.get("retention_days") or {}))


# ---------- 对象元数据 ----------


@dataclass(frozen=True)
class WormObject:
    key: str
    uri: str
    sha256: str
    size: int
    version_id: str
    retention_until: datetime
    mode: str = "compliance"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _validate_key(key: str) -> None:
    """拒绝绝对路径与路径穿越（对象 key 仅允许相对分段）。"""
    if not key or key.startswith("/") or "\\" in key:
        raise ObjectStoreError(f"invalid_key:{key}")
    parts = Path(key).parts
    if any(part in ("..", "") for part in parts):
        raise ObjectStoreError(f"invalid_key:{key}")


def _uri(key: str) -> str:
    return f"{URI_PREFIX}{key}"


# ---------- 本地 WORM 实现 ----------


class LocalWormStore:
    """文件系统 WORM：只读对象 + 元数据旁路文件 + 保留期锁。"""

    def __init__(
        self,
        root: str | Path,
        policy: RetentionPolicy | None = None,
        clock: Any = None,
    ) -> None:
        self._root = Path(root)
        self.policy = policy or RetentionPolicy()
        self._clock = clock or _utcnow

    # 路径
    def _data_path(self, key: str) -> Path:
        _validate_key(key)
        return self._root / key

    def _meta_path(self, key: str) -> Path:
        return self._data_path(key).with_name(self._data_path(key).name + META_SUFFIX)

    # 元数据读写
    def _read_meta(self, key: str) -> dict[str, Any]:
        meta_path = self._meta_path(key)
        if not meta_path.is_file():
            raise ObjectStoreError(f"object_not_found:{key}")
        return json.loads(meta_path.read_text(encoding="utf-8"))

    def _write_file(self, path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        tmp.write_bytes(content)
        os.chmod(tmp, 0o444)
        os.replace(tmp, path)

    def put(self, key: str, data: bytes, kind: str = "evidence") -> WormObject:
        """写入对象；保留期内已存在即 WormViolation（对象锁生效）。"""
        data_path = self._data_path(key)
        now = self._clock()
        if data_path.exists():
            meta = self._read_meta(key)
            retention_until = datetime.fromisoformat(meta["retention_until"])
            if now < retention_until:
                raise WormViolation(
                    f"object_locked:{key} retention_until={meta['retention_until']}"
                    f" mode={meta.get('mode', 'compliance')}"
                )

        version_id = uuid.uuid4().hex
        retention_until = now + timedelta(days=self.policy.days_for(kind))
        sha256 = hashlib.sha256(data).hexdigest()
        self._write_file(data_path, data)
        self._write_file(
            self._meta_path(key),
            json.dumps(
                {
                    "key": key,
                    "kind": kind,
                    "sha256": sha256,
                    "size": len(data),
                    "version_id": version_id,
                    "mode": "compliance",
                    "retention_until": zulu(retention_until),
                    "created_at": zulu(now),
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8"),
        )
        return WormObject(
            key=key,
            uri=_uri(key),
            sha256=sha256,
            size=len(data),
            version_id=version_id,
            retention_until=retention_until,
        )

    def get(self, key: str) -> bytes:
        data_path = self._data_path(key)
        if not data_path.is_file():
            raise ObjectStoreError(f"object_not_found:{key}")
        return data_path.read_bytes()

    def head(self, key: str) -> WormObject:
        meta = self._read_meta(key)
        return WormObject(
            key=meta["key"],
            uri=_uri(meta["key"]),
            sha256=meta["sha256"],
            size=int(meta["size"]),
            version_id=meta["version_id"],
            retention_until=datetime.fromisoformat(meta["retention_until"]),
            mode=meta.get("mode", "compliance"),
        )

    def delete(self, key: str) -> None:
        """删除对象；保留期内拒绝（compliance 语义）。"""
        now = self._clock()
        meta = self._read_meta(key)
        retention_until = datetime.fromisoformat(meta["retention_until"])
        if now < retention_until:
            raise WormViolation(
                f"object_locked:{key} retention_until={meta['retention_until']}"
                f" mode={meta.get('mode', 'compliance')}"
            )
        self._data_path(key).unlink()
        self._meta_path(key).unlink()


# ---------- MinIO WORM 实现（需 minio 依赖） ----------


class MinioWormStore:  # pragma: no cover — 需 MinIO 服务与 minio SDK；本地/CI 无
    """MinIO Object Lock（compliance）：对象锁由服务端强制。"""

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        policy: RetentionPolicy | None = None,
        secure: bool = False,
        clock: Any = None,
    ) -> None:
        if not endpoint:
            raise ObjectStoreError("minio_config_missing:EVAL_WORM_ENDPOINT")
        try:
            from minio import Minio
            from minio.commonconfig import COMPLIANCE
            from minio.retention import Retention
        except ImportError as exc:
            raise ObjectStoreError(f"minio_missing:{exc}") from exc

        self._Retention = Retention
        self._COMPLIANCE = COMPLIANCE
        self._client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )
        self._bucket = bucket
        self.policy = policy or RetentionPolicy()
        self._clock = clock or _utcnow
        if not self._client.bucket_exists(bucket):
            self._client.make_bucket(bucket, object_lock=True)

    def put(self, key: str, data: bytes, kind: str = "evidence") -> WormObject:
        _validate_key(key)
        now = self._clock()
        retention_until = now + timedelta(days=self.policy.days_for(kind))
        retention = self._Retention(
            self._COMPLIANCE, retain_until_date=retention_until.replace(microsecond=0)
        )
        self._client.put_object(
            self._bucket,
            key,
            data,
            length=len(data),
            retention=retention,
        )
        stat = self._client.stat_object(self._bucket, key)
        return WormObject(
            key=key,
            uri=f"s3://{self._bucket}/{key}",
            sha256=hashlib.sha256(data).hexdigest(),
            size=len(data),
            version_id=stat.version_id or "",
            retention_until=retention_until,
            mode="compliance",
        )

    def get(self, key: str) -> bytes:
        response = self._client.get_object(self._bucket, key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def head(self, key: str) -> WormObject:
        stat = self._client.stat_object(self._bucket, key)
        return WormObject(
            key=key,
            uri=f"s3://{self._bucket}/{key}",
            sha256=stat.etag or "",
            size=stat.size,
            version_id=stat.version_id or "",
            retention_until=self._clock(),
            mode="compliance",
        )

    def delete(self, key: str) -> None:
        # compliance 模式下服务端拒绝保留期内的删除（客户端不自证）
        self._client.remove_object(self._bucket, key)


# ---------- 装配 ----------


def build_store(
    config_path: str | Path | None = None,
    root: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> Any:
    """按配置/环境装配对象存储；未知模式或缺依赖均 fail-closed。"""
    env = os.environ if env is None else env
    config_file = Path(config_path) if config_path is not None else DEFAULT_CONFIG_PATH
    config: dict[str, Any] = {}
    if config_file.is_file():
        config = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}

    policy = load_retention_policy(config_file)
    mode = env.get("EVAL_WORM_MODE") or config.get("mode") or "local"

    if mode == "local":
        resolved_root = root or env.get("EVAL_WORM_ROOT") or config.get("root") or "artifacts/worm"
        root_path = Path(resolved_root)
        if not root_path.is_absolute():
            root_path = MODULE_ROOT / root_path
        return LocalWormStore(root_path, policy=policy)

    if mode == "minio":
        return MinioWormStore(
            endpoint=env.get("EVAL_WORM_ENDPOINT", ""),
            access_key=env.get("EVAL_WORM_ACCESS_KEY", ""),
            secret_key=env.get("EVAL_WORM_SECRET_KEY", ""),
            bucket=env.get("EVAL_WORM_BUCKET") or config.get("bucket") or "eval-evidence",
            policy=policy,
            secure=(env.get("EVAL_WORM_SECURE", "false").lower() == "true"),
        )

    raise ObjectStoreError(f"unknown_mode:{mode}")


def archive_bundle(
    store: Any, bundle: Mapping[str, Any], eval_id: str | None = None
) -> dict[str, Any]:
    """证据包 → WORM 对象（`evidence/<eval_id>.json`），返回归档凭据。"""
    target_eval = eval_id or bundle.get("eval_id")
    if not target_eval:
        raise ObjectStoreError("missing_eval_id")
    key = f"evidence/{target_eval}.json"
    obj = store.put(key, canonical_json(dict(bundle)).encode("utf-8"), kind="evidence")
    return {
        "uri": obj.uri,
        "sha256": obj.sha256,
        "version_id": obj.version_id,
        "retention_until": zulu(obj.retention_until),
    }
