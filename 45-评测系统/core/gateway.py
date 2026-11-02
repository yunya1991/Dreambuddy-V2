# -*- coding: utf-8 -*-
"""
gateway.py — 评测受理网关（P0-4）
==================================
职责（PLAN P0-4 验收 / SPEC §13.1）：
- 受理 EvalRequest：jsonschema 校验（eval_request.v1.json），非法即拒
- 类别匹配校验：category ↔ object_type 依 config/categories.yaml，不匹配即拒
- 幂等受理：Idempotency-Key 强制；同 key 重复提交返回同一 eval_id
- eval_id 分配：EV-YYYYMMDD-NNNNNN（按日序号）

边界：
- spec_hash 当前为占位实现（sha256({"spec_id": ...})）；
  TODO(P2-9)：spec 注册表落地后改为 sha256(canonical_json(EvalSpec))（§3.1）
- env_manifest 语义校验（endpoints 可达性 / 明文密钥）由 P1-1 的
  core/validators.py 提供：实盘（gate.shadow=false）硬拒，影子只告警
- 存储为 EvalRequestStore 接口；P0-4 提供内存实现供单测，
  P0-5 由 storage/repo.py 提供 PostgreSQL 实现
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

import yaml
from jsonschema import Draft202012Validator

from core.spec_registry import SpecRegistry

from core.validators import EnvManifestError, EnvManifestValidator  # noqa: F401 — 对外统一导出

logger = logging.getLogger(__name__)

MODULE_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = MODULE_ROOT / "contracts" / "schemas" / "eval_request.v1.json"
CATEGORIES_PATH = MODULE_ROOT / "config" / "categories.yaml"

CATEGORIES = ("finance", "ai", "engineering")
OBJECT_TYPES = (
    "strategy",
    "model",
    "service",
    "code_artifact",
    "dataset",
    "knowledge",
)


# ---------- 错误 ----------


class GatewayError(Exception):
    """受理网关错误基类。"""


class MissingIdempotencyKeyError(GatewayError):
    """缺 Idempotency-Key（§13.1 强制幂等头）。"""


class RequestValidationError(GatewayError):
    """请求体不符合 eval_request.v1.json 契约。"""


class CategoryMismatchError(GatewayError):
    """category 与 object_type 不匹配（§13.1 受理即拒条件）。"""


class CategoriesConfigError(ValueError):
    """categories.yaml 非法：缺版本、未知类别/对象类型、空映射等。"""


# ---------- 类别配置 ----------


@dataclass(frozen=True)
class CategoriesConfig:
    """类别↔对象类型映射 + 门禁模式（不可变快照，加载即全量校验）。"""

    version: str
    mapping: dict[str, tuple[str, ...]]
    gate_shadow: bool

    @classmethod
    def load(cls, path: str | Path = CATEGORIES_PATH) -> "CategoriesConfig":
        path = Path(path)
        if not path.is_file():
            raise CategoriesConfigError(f"类别配置文件不存在: {path}")
        try:
            doc = yaml.safe_load(path.read_bytes().decode("utf-8"))
        except yaml.YAMLError as exc:
            raise CategoriesConfigError(f"YAML 解析失败: {exc}") from exc
        if not isinstance(doc, dict):
            raise CategoriesConfigError("类别配置顶层必须是 mapping")

        version = doc.get("version")
        if not version or not isinstance(version, str):
            raise CategoriesConfigError("缺 version（配置必须版本化）")

        raw_categories = doc.get("categories")
        if not isinstance(raw_categories, dict) or not raw_categories:
            raise CategoriesConfigError("categories 必须是非空 mapping")

        mapping: dict[str, tuple[str, ...]] = {}
        for category, body in raw_categories.items():
            if category not in CATEGORIES:
                raise CategoriesConfigError(f"未知类别: {category!r}（须为 {CATEGORIES}）")
            if not isinstance(body, dict):
                raise CategoriesConfigError(f"categories.{category} 必须是 mapping")
            object_types = body.get("object_types")
            if not isinstance(object_types, list) or not object_types:
                raise CategoriesConfigError(f"categories.{category}.object_types 必须是非空列表")
            if len(set(object_types)) != len(object_types):
                raise CategoriesConfigError(f"categories.{category}.object_types 存在重复项")
            for ot in object_types:
                if ot not in OBJECT_TYPES:
                    raise CategoriesConfigError(
                        f"categories.{category} 未知 object_type: {ot!r}（须为 {OBJECT_TYPES}）"
                    )
            mapping[category] = tuple(object_types)

        # gate 段缺失时 fail-safe 默认影子模式（初期只受理不拦截）
        raw_gate = doc.get("gate") or {}
        if not isinstance(raw_gate, dict):
            raise CategoriesConfigError("gate 必须是 mapping")
        gate_shadow = raw_gate.get("shadow", True)
        if not isinstance(gate_shadow, bool):
            raise CategoriesConfigError("gate.shadow 必须是布尔值")

        config = cls(version=version, mapping=mapping, gate_shadow=gate_shadow)
        logger.info(
            "categories_config loaded version=%s categories=%d gate_shadow=%s",
            version,
            len(mapping),
            gate_shadow,
        )
        return config

    def allows(self, category: str, object_type: str) -> bool:
        return object_type in self.mapping.get(category, ())


# ---------- 记录与存储 ----------


@dataclass(frozen=True)
class EvalRequestRecord:
    """已受理的评测申请记录（对应 eval_requests 表，§12）。"""

    eval_id: str
    idempotency_key: str
    object_ref: str
    category: str
    object_type: str
    submitter: str
    purpose: str
    priority: str
    spec_id: str
    env_manifest: dict[str, Any]
    spec_hash: str
    status: str  # queued / running / succeeded / failed / cancelled
    created_at: datetime


class EvalRequestStore(Protocol):
    """受理存储接口：P0-4 内存实现，P0-5 替换为 PostgreSQL。"""

    def get_by_idempotency_key(self, key: str) -> EvalRequestRecord | None: ...

    def insert_request(self, record: EvalRequestRecord) -> None: ...

    def count_for_day(self, day: str) -> int: ...


class InMemoryEvalRequestStore:
    """内存存储：单测与本地空跑用；幂等语义与 PG 唯一键一致。"""

    def __init__(self) -> None:
        self._by_key: dict[str, EvalRequestRecord] = {}
        self._by_id: dict[str, EvalRequestRecord] = {}

    def get_by_idempotency_key(self, key: str) -> EvalRequestRecord | None:
        return self._by_key.get(key)

    def insert_request(self, record: EvalRequestRecord) -> None:
        if record.idempotency_key in self._by_key:
            raise ValueError(f"幂等键冲突: {record.idempotency_key}")
        if record.eval_id in self._by_id:
            raise ValueError(f"eval_id 冲突: {record.eval_id}")
        self._by_key[record.idempotency_key] = record
        self._by_id[record.eval_id] = record

    def count_for_day(self, day: str) -> int:
        prefix = f"EV-{day}-"
        return sum(1 for k in self._by_id if k.startswith(prefix))

    def all(self) -> list[EvalRequestRecord]:
        return list(self._by_id.values())


# ---------- 受理结果 ----------


@dataclass(frozen=True)
class SubmitResult:
    """受理回执（§13.1 → 202）。"""

    eval_id: str
    status: str  # "accepted"
    spec_hash: str


def spec_hash_placeholder(spec_id: str) -> str:
    """占位 spec_hash：spec 注册表（P2-9）落地前以 spec_id 规范化哈希代替。

    TODO(P2-9): 改为 sha256(canonical_json(EvalSpec))（§3.1）。
    注意：PgRepo 读取 eval_requests 时按本规则重算 spec_hash（§12 表中无该列），
    两处的确定性一致是幂等回放的前提。
    """
    canonical = json.dumps(
        {"spec_id": spec_id}, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------- 网关 ----------


class Gateway:
    """评测受理网关：校验 → 类别匹配 → 幂等受理 → 分配 eval_id。"""

    def __init__(
        self,
        store: EvalRequestStore,
        categories: CategoriesConfig,
        schema_path: str | Path = SCHEMA_PATH,
        clock: Callable[[], datetime] | None = None,
        prober: Callable[[str], bool] | None = None,
        spec_registry: SpecRegistry | None = None,
    ) -> None:
        self._store = store
        # P2-9 收口：注册表可用时按 §3.1 全量哈希；未提供时保持占位（向后兼容）
        self._spec_registry = spec_registry
        self._categories = categories
        schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
        self._validator = Draft202012Validator(schema)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        # 实盘（shadow=false）硬拒；影子只告警（P1-3 只受理不拦截）
        self._env_validator = EnvManifestValidator(strict=not categories.gate_shadow, prober=prober)

    @property
    def gate_shadow(self) -> bool:
        """影子模式：只受理不拦截（P1-3 据此放行回调）。"""
        return self._categories.gate_shadow

    def submit(self, payload: Any, idempotency_key: str | None) -> SubmitResult:
        """受理评测申请；同 Idempotency-Key 重放返回原始 eval_id。"""
        if idempotency_key is None or not str(idempotency_key).strip():
            raise MissingIdempotencyKeyError("缺少 Idempotency-Key 请求头（§13.1 强制幂等）")
        idempotency_key = str(idempotency_key).strip()

        self._validate_schema(payload)
        self._env_validator.enforce(payload["env_manifest"])
        self._validate_category(payload["category"], payload["object_type"])

        existing = self._store.get_by_idempotency_key(idempotency_key)
        if existing is not None:
            logger.info(
                "idempotent replay key=%s eval_id=%s",
                idempotency_key,
                existing.eval_id,
            )
            return SubmitResult(
                eval_id=existing.eval_id,
                status="accepted",
                spec_hash=existing.spec_hash,
            )

        now = self._clock()
        day = now.strftime("%Y%m%d")
        seq = self._store.count_for_day(day) + 1
        eval_id = f"EV-{day}-{seq:06d}"
        if self._spec_registry is not None:
            spec_hash = self._spec_registry.spec_hash(payload["spec_id"])
        else:
            spec_hash = spec_hash_placeholder(payload["spec_id"])

        record = EvalRequestRecord(
            eval_id=eval_id,
            idempotency_key=idempotency_key,
            object_ref=payload["object_ref"],
            category=payload["category"],
            object_type=payload["object_type"],
            submitter=payload["submitter"],
            purpose=payload["purpose"],
            priority=payload.get("priority", "normal"),
            spec_id=payload["spec_id"],
            env_manifest=payload["env_manifest"],
            spec_hash=spec_hash,
            status="queued",
            created_at=now,
        )
        # 注意：count_for_day + insert 非原子，内存实现可接受；
        # PG 实现（P0-5）依赖唯一键约束兜底防重。
        self._store.insert_request(record)
        logger.info(
            "eval accepted eval_id=%s category=%s object_type=%s submitter=%s purpose=%s",
            eval_id,
            record.category,
            record.object_type,
            record.submitter,
            record.purpose,
        )
        return SubmitResult(eval_id=eval_id, status="accepted", spec_hash=spec_hash)

    # ---------- 内部校验 ----------

    def _validate_schema(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            raise RequestValidationError(
                f"请求体必须是 JSON object，实际: {type(payload).__name__}"
            )
        errors = sorted(
            self._validator.iter_errors(payload),
            key=lambda e: list(e.absolute_path),
        )
        if errors:
            details = "; ".join(
                f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
                for e in errors[:5]
            )
            raise RequestValidationError(f"请求体不符合契约: {details}")

    def _validate_category(self, category: str, object_type: str) -> None:
        if not self._categories.allows(category, object_type):
            allowed = self._categories.mapping.get(category, ())
            raise CategoryMismatchError(
                f"类别与对象类型不匹配: {category}/{object_type}"
                f"（{category} 允许: {allowed or '无'}）"
            )
