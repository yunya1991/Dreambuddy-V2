# -*- coding: utf-8 -*-
"""
registry.py — Threshold Registry 加载器（P0-3）
================================================
职责（PLAN P0-3 验收）：
- 版本化加载 config/thresholds.yaml（SPEC §8.1）
- 缺字段 / 非法枚举 / 重复项 → 拒绝（ThresholdConfigError）
- 变更写审计：加载时计算内容哈希并记录日志（版本 + sha256）

规则：
- get(category, item) 未命中 → KeyError（默认拒绝，§2.6）
- 阈值判定方向由 direction 决定：gte 判 CI 下界，lte 判 CI 上界（§8.2）
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "config" / "thresholds.yaml"

CATEGORIES = ("finance", "ai", "engineering")
KINDS = ("hard", "weighted")
DIRECTIONS = ("gte", "lte")
REQUIRED_ITEM_FIELDS = ("category", "item", "value", "metric", "min_n", "kind")


class ThresholdConfigError(ValueError):
    """阈值配置非法：缺字段、枚举越界、重复项、版本缺失等。"""


@dataclass(frozen=True)
class Threshold:
    """单条阈值（SPEC §3.3 Threshold Registry 必填字段）。"""

    category: str
    item: str
    value: float
    metric: str
    min_n: int
    kind: str
    direction: str = "gte"
    stat: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    name: str = ""


class ThresholdRegistry:
    """版本化阈值注册表：不可变快照，加载即全量校验。"""

    def __init__(self, version: str, items: list[Threshold], content_hash: str):
        self._version = version
        self._items = tuple(items)
        self._content_hash = content_hash
        self._index = {(t.category, t.item): t for t in items}

    # ---------- 加载与校验 ----------

    @classmethod
    def load(cls, path: str | Path = DEFAULT_PATH) -> "ThresholdRegistry":
        path = Path(path)
        if not path.is_file():
            raise ThresholdConfigError(f"阈值文件不存在: {path}")
        raw_bytes = path.read_bytes()
        content_hash = hashlib.sha256(raw_bytes).hexdigest()
        try:
            doc = yaml.safe_load(raw_bytes.decode("utf-8"))
        except yaml.YAMLError as exc:
            raise ThresholdConfigError(f"YAML 解析失败: {exc}") from exc
        if not isinstance(doc, dict):
            raise ThresholdConfigError("阈值文件顶层必须是 mapping")

        version = doc.get("version")
        if not version or not isinstance(version, str):
            raise ThresholdConfigError("缺 version（阈值必须版本化，§8.5）")

        raw_items = doc.get("items")
        if not isinstance(raw_items, list) or not raw_items:
            raise ThresholdConfigError("items 必须是非空列表")

        items = [cls._parse_item(i, raw) for i, raw in enumerate(raw_items)]
        seen: set[tuple[str, str]] = set()
        for t in items:
            key = (t.category, t.item)
            if key in seen:
                raise ThresholdConfigError(f"重复阈值项: {key[0]}/{key[1]}")
            seen.add(key)

        registry = cls(version=version, items=items, content_hash=content_hash)
        # 变更审计：版本 + 内容哈希 + 条目数落日志（§8.5 阈值治理）
        logger.info(
            "threshold_registry loaded version=%s items=%d sha256=%s",
            version,
            len(items),
            content_hash,
        )
        return registry

    @staticmethod
    def _parse_item(idx: int, raw: Any) -> Threshold:
        if not isinstance(raw, dict):
            raise ThresholdConfigError(f"items[{idx}] 必须是 mapping")
        for f in REQUIRED_ITEM_FIELDS:
            if f not in raw:
                raise ThresholdConfigError(f"items[{idx}] 缺必填字段: {f}")

        category = raw["category"]
        if category not in CATEGORIES:
            raise ThresholdConfigError(
                f"items[{idx}] category 非法: {category!r}（须为 {CATEGORIES}）"
            )
        kind = raw["kind"]
        if kind not in KINDS:
            raise ThresholdConfigError(f"items[{idx}] kind 非法: {kind!r}（须为 {KINDS}）")
        direction = raw.get("direction", "gte")
        if direction not in DIRECTIONS:
            raise ThresholdConfigError(
                f"items[{idx}] direction 非法: {direction!r}（须为 {DIRECTIONS}）"
            )
        value = raw["value"]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ThresholdConfigError(f"items[{idx}] value 必须是数值，实际: {value!r}")
        min_n = raw["min_n"]
        if isinstance(min_n, bool) or not isinstance(min_n, int) or min_n < 0:
            raise ThresholdConfigError(f"items[{idx}] min_n 必须是非负整数，实际: {min_n!r}")
        params = raw.get("params", {})
        if not isinstance(params, dict):
            raise ThresholdConfigError(f"items[{idx}] params 必须是 mapping")

        return Threshold(
            category=category,
            item=str(raw["item"]),
            value=float(value),
            metric=str(raw["metric"]),
            min_n=min_n,
            kind=kind,
            direction=direction,
            stat=str(raw.get("stat", "")),
            params=params,
            name=str(raw.get("name", "")),
        )

    # ---------- 查询 ----------

    @property
    def version(self) -> str:
        return self._version

    @property
    def content_hash(self) -> str:
        return self._content_hash

    def all(self) -> tuple[Threshold, ...]:
        return self._items

    def get(self, category: str, item: str) -> Threshold:
        """按 (category, item) 取阈值；未登记即拒（§2.6 默认拒绝）。"""
        try:
            return self._index[(category, item)]
        except KeyError:
            raise KeyError(f"未登记阈值: {category}/{item}") from None

    def by_category(self, category: str) -> tuple[Threshold, ...]:
        return tuple(t for t in self._items if t.category == category)
