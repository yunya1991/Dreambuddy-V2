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

# 交易日市场（缺口率分母用工作日）；其余（okx 等 7×24）用日历日
_TRADING_VENUES = ("fred", "nasdaq", "yfinance")


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
    # v2：展示层五类视图（加密/避险/大宗/美股/情绪），底层 asset_class 仍取 40 层
    view_class: str = ""
    # v2：代币化标的（OKX *-USDT-SWAP，非证券本体），必须同时 proxy=True
    tokenized: bool = False
    # v2：per-anchor 质量下限（覆盖全局 quality）；0 = 未声明，回落全局
    min_rows: int = 0
    history_lt_3y: bool = False
    history_note: str = ""

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
    # v2：扩展池（历史 < 3 年或非首屏），anchors 保持核心 8 个不变
    extended: Tuple[Anchor, ...] = ()
    pools: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    view_order: Tuple[str, ...] = ()

    # ------------------------------------------------------------ 查询
    def all_anchors(self) -> List[Anchor]:
        """核心锚定 + 扩展池（顺序：核心在前）。"""
        return list(self.anchors) + list(self.extended)

    def resolve(self, key: str) -> Optional[Anchor]:
        """按 id 或别名解析（大小写不敏感，忽略首尾空格）。"""
        if not key:
            return None
        probe = key.strip().lower()
        for anchor in self.all_anchors():
            if anchor.id.lower() == probe:
                return anchor
            if any(alias.lower() == probe for alias in anchor.aliases):
                return anchor
        return None

    def by_class(self, asset_class: str, *, include_extended: bool = False) -> List[Anchor]:
        source = self.all_anchors() if include_extended else list(self.anchors)
        return [a for a in source if a.asset_class == asset_class]

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

    # ------------------------------------------------------------ v2：五类视图 / 首屏池
    def views(self) -> List[str]:
        """展示层五类视图（按 view_order 排序；未声明的类排最后）。"""
        declared = list(self.view_order)
        extra: List[str] = []
        for anchor in self.all_anchors():
            if anchor.view_class and anchor.view_class not in declared + extra:
                extra.append(anchor.view_class)
        return declared + extra

    def by_view(self, view: str) -> List[Anchor]:
        return [a for a in self.all_anchors() if a.view_class == view]

    def pool(self, name: str = "default") -> List[Anchor]:
        """首屏/扩展池成员（未配置或 id 不可解析抛 AssetPoolError）。"""
        ids = self.pools.get(name)
        if not ids:
            raise AssetPoolError(f"资产池 pools.{name} 未配置")
        out: List[Anchor] = []
        for key in ids:
            anchor = self.resolve(key)
            if anchor is None:
                raise AssetPoolError(f"pools.{name} 引用了不存在的标的: {key}")
            out.append(anchor)
        return out

    def min_rows_for(self, anchor: Anchor) -> int:
        """per-anchor 质量下限；未声明时按 venue 回落全局（交易日 / 7×24 两套口径）。"""
        if anchor.min_rows:
            return int(anchor.min_rows)
        trading = (anchor.venue or "") in _TRADING_VENUES
        key = "min_rows_3y_trading" if trading else "min_rows_3y"
        return int(self.quality.get(key, 0))

    # ------------------------------------------------------------ 校验
    def validate(self) -> List[str]:
        """返回错误列表（空 = 通过）。"""
        errors: List[str] = []
        ids, aliases = set(), {}
        for anchor in self.all_anchors():
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
            if anchor.role not in ("leader", "co_leader", "member"):
                errors.append(f"{anchor.id} role 非法: {anchor.role}")
            if anchor.view_class and self.view_order and anchor.view_class not in self.view_order:
                errors.append(f"{anchor.id} view_class 非法: {anchor.view_class}")
            if anchor.tokenized and not anchor.proxy:
                errors.append(f"{anchor.id} tokenized=true 必须同时 proxy=true（代理必须标注）")

        # 核心锚定：必须 ≥3 年日频，且每类恰好 1 个 leader
        for anchor in self.anchors:
            if anchor.years < 3:
                errors.append(f"{anchor.id} history.years={anchor.years} < 3（S2/S3 无法统计）")

        for asset_class in self.classes():
            leaders = [a for a in self.by_class(asset_class) if a.role == "leader"]
            if len(leaders) != 1:
                errors.append(f"类别 {asset_class} 的龙头数量为 {len(leaders)}（必须恰好 1 个）")

        # 扩展池：允许 history_lt_3y 降级，但必须显式声明 per-anchor min_rows（B-LT5）
        for anchor in self.extended:
            if anchor.history_lt_3y:
                if anchor.min_rows <= 0:
                    errors.append(f"{anchor.id} history_lt_3y=true 必须声明 history.min_rows")
            elif anchor.years < 3:
                errors.append(f"{anchor.id} history.years={anchor.years} < 3 且未标 history_lt_3y")

        for name, keys in self.pools.items():
            for key in keys:
                if self.resolve(key) is None:
                    errors.append(f"pools.{name} 引用了不存在的标的: {key}")

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
        min_rows=int(history.get("min_rows", 0) or 0),
        history_lt_3y=bool(history.get("history_lt_3y", False)),
        history_note=str(history.get("note", "")),
        view_class=str(raw.get("view_class", "")),
        tokenized=bool(raw.get("tokenized", False)),
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
        extended=tuple(_parse_anchor(a) for a in (raw.get("extended_anchors") or [])),
        pools={
            str(name): tuple(str(s) for s in (ids or []))
            for name, ids in (raw.get("pools") or {}).items()
        },
        view_order=tuple(str(v) for v in (raw.get("view_order") or [])),
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
                "extended": len(pool.extended),
                "classes": {cls: [a.id for a in pool.by_class(cls)] for cls in pool.classes()},
                "leaders": {
                    cls: (pool.leader_of(cls).id if pool.leader_of(cls) else "")
                    for cls in pool.classes()
                },
                "views": {view: [a.id for a in pool.by_view(view)] for view in pool.views()},
                "pools": {name: list(ids) for name, ids in pool.pools.items()},
                "dynamic": pool.dynamic.get("enabled", False),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
