# -*- coding: utf-8 -*-
"""资产池加载与校验（S1.0-2）。

单一事实源：config/asset_pool.yaml。本模块只做「读 + 校验 + 查询」，
不采集、不回填、不做统计——回填见 S1.0-3，覆盖体检见 S1.0-4。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

import yaml

_DEFAULT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config",
    "asset_pool.yaml",
)


class AssetPoolError(ValueError):
    """资产池结构非法（缺字段/重复 id/类别无龙头等）。"""


@dataclass(frozen=True)
class Anchor:
    """锚定资产：必须有 ≥3 年日频历史。"""

    id: str
    name: str
    asset_class: str
    role: str
    timezone: str
    enabled: bool
    aliases: Tuple[str, ...]
    storage_sub_category: str
    storage_metric: str
    storage_volume_metric: Optional[str] = None
    venue: str = ""
    inst_type: str = ""
    inst_id: str = ""
    series_id: str = ""
    granularity: str = "1D"
    years: int = 3
    backfill: str = ""
    proxy: bool = False
    proxy_note: str = ""

    @property
    def storage_key(self) -> Tuple[str, str]:
        """mm_metrics 的 (sub_category, metric_name)。"""
        return self.storage_sub_category, self.storage_metric

    @property
    def instrument_id(self) -> str:
        """交易所标的（okx）或 FRED series（fred）。"""
        return self.inst_id or self.series_id


@dataclass
class AssetPool:
    version: int
    updated: str
    timezone_default: str
    source_priority: List[str]
    quality: Dict[str, Any]
    anchors: Tuple[Anchor, ...]
    dynamic: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------ 查询
    def resolve(self, key: str) -> Optional[Anchor]:
        """按 id 或别名解析（大小写不敏感，忽略首尾空格）。"""
        if not key:
            return None
        probe = key.strip().lower()
        for anchor in self.anchors:
            if anchor.id.lower() == probe:
                return anchor
            if any(alias.lower() == probe for alias in anchor.aliases):
                return anchor
        return None

    def by_class(self, asset_class: str) -> List[Anchor]:
        return [a for a in self.anchors if a.asset_class == asset_class]

    def leader_of(self, asset_class: str) -> Optional[Anchor]:
        for anchor in self.by_class(asset_class):
            if anchor.role == "leader":
                return anchor
        return None

    def classes(self) -> List[str]:
        seen: List[str] = []
        for anchor in self.anchors:
            if anchor.asset_class not in seen:
                seen.append(anchor.asset_class)
        return seen

    def storage_keys(self) -> Iterable[Tuple[str, Tuple[str, str]]]:
        for anchor in self.anchors:
            yield anchor.id, anchor.storage_key

    # ------------------------------------------------------------ 校验
    def validate(self) -> List[str]:
        """返回错误列表（空 = 通过）。"""
        errors: List[str] = []
        ids, aliases = set(), {}
        for anchor in self.anchors:
            if not anchor.id:
                errors.append("anchor 缺少 id")
                continue
            if anchor.id in ids:
                errors.append(f"重复 id: {anchor.id}")
            ids.add(anchor.id)
            for alias in anchor.aliases:
                owner = aliases.get(alias.lower())
                if owner and owner != anchor.id:
                    errors.append(f"别名冲突: {alias} 同时属于 {owner} 与 {anchor.id}")
                aliases[alias.lower()] = anchor.id
                if alias.lower() in ids and alias.lower() != anchor.id.lower():
                    errors.append(f"别名与 id 冲突: {alias}")
            if not anchor.storage_sub_category or not anchor.storage_metric:
                errors.append(f"{anchor.id} 缺少 storage.sub_category/metric")
            if not anchor.instrument_id:
                errors.append(f"{anchor.id} 缺少 instrument.inst_id / series_id")
            if anchor.years < 3:
                errors.append(f"{anchor.id} history.years={anchor.years} < 3（S2/S3 无法统计）")
            if anchor.role not in ("leader", "member"):
                errors.append(f"{anchor.id} role 非法: {anchor.role}")

        for asset_class in self.classes():
            leaders = [a for a in self.by_class(asset_class) if a.role == "leader"]
            if len(leaders) != 1:
                errors.append(f"类别 {asset_class} 的龙头数量为 {len(leaders)}（必须恰好 1 个）")

        benchmarks = (self.dynamic.get("relation") or {}).get("benchmarks") or []
        for bench in benchmarks:
            if self.resolve(bench) is None:
                errors.append(f"dynamic.relation.benchmarks 未在锚定表中: {bench}")
        return errors


def _parse_anchor(raw: Dict[str, Any]) -> Anchor:
    inst = raw.get("instrument") or {}
    storage = raw.get("storage") or {}
    history = raw.get("history") or {}
    aliases = raw.get("aliases") or []
    return Anchor(
        id=str(raw.get("id", "")).strip(),
        name=str(raw.get("name", "")),
        asset_class=str(raw.get("asset_class", "")),
        role=str(raw.get("role", "member")),
        timezone=str(raw.get("timezone") or "UTC"),
        enabled=bool(raw.get("enabled", True)),
        aliases=tuple(str(a) for a in aliases),
        storage_sub_category=str(storage.get("sub_category", "")),
        storage_metric=str(storage.get("metric", "")),
        storage_volume_metric=storage.get("volume_metric"),
        venue=str(inst.get("venue", "")),
        inst_type=str(inst.get("inst_type", "")),
        inst_id=str(inst.get("inst_id", "")),
        series_id=str(inst.get("series_id", "")),
        granularity=str(history.get("granularity", "1D")),
        years=int(history.get("years", 0)),
        backfill=str(history.get("backfill", "")),
        proxy=bool(raw.get("proxy", False)),
        proxy_note=str(raw.get("proxy_note", "")),
    )


def load(path: Optional[str] = None, *, validate: bool = True) -> AssetPool:
    """加载资产池；结构非法抛 AssetPoolError。"""
    target = path or _DEFAULT_PATH
    if not os.path.exists(target):
        raise AssetPoolError(f"资产池配置不存在: {target}")
    with open(target, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    anchors_raw = raw.get("anchors") or []
    if not anchors_raw:
        raise AssetPoolError("资产池为空: anchors 缺失")

    pool = AssetPool(
        version=int(raw.get("version", 0)),
        updated=str(raw.get("updated", "")),
        timezone_default=str(raw.get("timezone_default", "UTC")),
        source_priority=[str(s) for s in (raw.get("source_priority") or [])],
        quality=dict(raw.get("quality") or {}),
        anchors=tuple(_parse_anchor(a) for a in anchors_raw),
        dynamic=dict(raw.get("dynamic") or {}),
    )
    if validate:
        errors = pool.validate()
        if errors:
            raise AssetPoolError("资产池校验失败:\n- " + "\n- ".join(errors))
    return pool


def main(argv=None) -> int:  # pragma: no cover - 手工排查用
    import argparse
    import json

    parser = argparse.ArgumentParser(description="资产池校验")
    parser.add_argument("--path", default=None)
    args = parser.parse_args(argv)
    try:
        pool = load(args.path)
    except AssetPoolError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "version": pool.version,
                "anchors": len(pool.anchors),
                "classes": {cls: [a.id for a in pool.by_class(cls)] for cls in pool.classes()},
                "leaders": {
                    cls: (pool.leader_of(cls).id if pool.leader_of(cls) else "")
                    for cls in pool.classes()
                },
                "dynamic": pool.dynamic.get("enabled", False),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
