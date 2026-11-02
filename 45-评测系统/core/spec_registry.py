# -*- coding: utf-8 -*-
"""
spec_registry.py — EvalSpec 注册表与全量 spec_hash（P2-9 收口）
=============================================================
职责（SPEC §3.1 / §3.3）：
- SpecRegistry：spec_id → 完整 EvalSpec 的注册与解析
  - register：登记 EvalSpec（版本化，禁止原地修改，同 id 再注册即拒绝）
  - resolve：解析 spec_id → EvalSpec dict（未注册即拒，fail-closed）
  - spec_hash：sha256(canonical_json(EvalSpec))（§3.1 规范化哈希）
- FileSpecRegistry：从 JSON 文件加载（registry_items 表的文件形态）

与占位实现的差异（闭环 TODO(P2-9)）：
- 占位：sha256(canonical_json({"spec_id": ...}))，仅绑定 id，spec 内容变更不感知
- 全量：sha256(canonical_json(完整 EvalSpec))，任何字段变更 → 哈希变化 → 新版本

一致性约束（幂等回放前提）：
- Gateway 受理时计算与 PgRepo 读取时重算必须使用同一注册表实例/同一 spec 定义
- canonical_json：sort_keys + 紧凑分隔符 + ensure_ascii=False（与既有约定一致）
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class SpecRegistryError(ValueError):
    """spec 注册表错误（未注册 / 重复注册 / 文件非法）。"""


def canonical_json(obj: Any) -> str:
    """规范化 JSON：键排序 + 紧凑分隔符 + 非 ASCII 原样。"""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def spec_hash_of(spec: dict[str, Any]) -> str:
    """§3.1：sha256(canonical_json(EvalSpec))。"""
    return hashlib.sha256(canonical_json(spec).encode("utf-8")).hexdigest()


# 必填字段（contracts/schemas/eval_spec.v1.json required）
SPEC_REQUIRED_FIELDS = (
    "spec_id",
    "version",
    "category",
    "object_type",
    "evaluator_ref",
    "scorers",
    "thresholds_ref",
    "created_by",
)


class SpecRegistry:
    """EvalSpec 注册表：内存实现（单机默认）；PG registry_items 表为持久形态。"""

    def __init__(self) -> None:
        self._specs: dict[str, dict[str, Any]] = {}

    def register(self, spec: dict[str, Any]) -> None:
        """登记 EvalSpec；spec_id 已存在即拒绝（版本不可变，§2.2）。"""
        if not isinstance(spec, dict):
            raise SpecRegistryError("EvalSpec 必须是 mapping")
        missing = [f for f in SPEC_REQUIRED_FIELDS if f not in spec]
        if missing:
            raise SpecRegistryError(f"EvalSpec 缺必填字段: {missing}")
        spec_id = spec["spec_id"]
        if spec_id in self._specs:
            raise SpecRegistryError(
                f"spec_id 已注册，禁止原地修改（§2.2 版本不可变）: {spec_id}"
            )
        # 深拷贝冻结，防止登记后被外部引用修改导致哈希漂移
        self._specs[spec_id] = json.loads(canonical_json(spec))

    def resolve(self, spec_id: str) -> dict[str, Any]:
        """解析 spec_id → EvalSpec；未注册即拒（fail-closed，§2.6 默认拒绝）。"""
        spec = self._specs.get(spec_id)
        if spec is None:
            raise SpecRegistryError(f"spec 未注册，拒绝受理: {spec_id}")
        return spec

    def spec_hash(self, spec_id: str) -> str:
        """§3.1 全量哈希：sha256(canonical_json(EvalSpec))。"""
        return spec_hash_of(self.resolve(spec_id))

    def __len__(self) -> int:
        return len(self._specs)


class FileSpecRegistry(SpecRegistry):
    """从 JSON 文件加载的注册表：[{...spec...}, ...] 或 {"specs": [...]}。"""

    def __init__(self, path: str | Path) -> None:
        super().__init__()
        p = Path(path)
        if not p.exists():
            raise SpecRegistryError(f"spec 注册表文件不存在: {path}")
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SpecRegistryError(f"spec 注册表 JSON 解析失败: {exc}") from exc
        if isinstance(data, dict):
            data = data.get("specs", [])
        if not isinstance(data, list):
            raise SpecRegistryError("spec 注册表顶层必须是 list 或含 specs 键的 mapping")
        for item in data:
            self.register(item)
