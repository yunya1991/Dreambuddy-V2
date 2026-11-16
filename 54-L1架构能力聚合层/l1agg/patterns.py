# -*- coding: utf-8 -*-
"""归纳层：同类现象（patterns）构建与校验（TASKS-20261116 T4-1 / T4-2 / T4-3）。

输入 = Discovery 的 findings（逐单元评估结果）；输出 = 按「关系类型 × 变换族 × 期限」
聚合的同类现象。纪律：
  - 纯函数：不取数、不写库、不读注册表（关系映射由调用方传入）；
  - 只做计数与二项检验，不做因果措辞（schema 禁止自然语言字段）；
  - 同一输入 + 同一参数 → 字节一致的 JSON（排序固定、浮点固定 6 位）。
"""

from __future__ import annotations

import json
import math
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

SCHEMA_VERSION = "1.0"

# 变换 → 族：族用于把不同变换但同语义的现象归到一起
TRANSFORM_FAMILY: Dict[str, str] = {
    "raw": "level",
    "diff": "chg",
    "pct": "chg",
    "zscore60": "mom",
    "ts_rank60": "mom",
    "quintile5": "bucket",
}
FAMILY_LABEL = {
    "level": "水平",
    "chg": "变化",
    "mom": "动量",
    "bucket": "分箱",
    "other": "其他",
}

DEFAULT_ALPHA = 0.05
DEFAULT_MIN_AGREE = 0.8
# 二项功效下限：n=9 全同向 p≈0.0039、n=10 全同向 p≈0.00195；
# min_members=3 与 alpha=0.05 组合数学上不可达（n=3 时 p=0.25），故取 10。
DEFAULT_MIN_MEMBERS = 10
DEFAULT_PRIMARY_ONLY = True
DEFAULT_MIN_MINORITY_SHARE = 0.3

PATTERN_KEYS = (
    "pattern_id",
    "relation_type",
    "family",
    "horizon",
    "direction",
    "support",
    "oppose",
    "significant_n",
    "sign_agreement",
    "bimodal",
    "p_value",
    "p_adj",
    "members",
    "status",
)


def family_of(transform: Any) -> str:
    return TRANSFORM_FAMILY.get(str(transform or "").strip(), "other")


def _binom_two_sided(k: int, n: int) -> float:
    """二项检验（H0: p=0.5）双侧 p。n=0 视为 1.0。"""
    if n <= 0:
        return 1.0
    k = max(0, min(k, n))
    tail = sum(math.comb(n, i) for i in range(k, n + 1)) / float(2**n)
    return min(1.0, 2.0 * tail)


def _bh(pvalues: Sequence[float]) -> List[float]:
    """Benjamini–Hochberg 校正；返回与输入同序的 p_adj。"""
    count = len(pvalues)
    if count == 0:
        return []
    order = sorted(range(count), key=lambda index: pvalues[index])
    adjusted = [1.0] * count
    running = 1.0
    for rank_from_end in range(count - 1, -1, -1):
        index = order[rank_from_end]
        value = pvalues[index] * count / float(rank_from_end + 1)
        running = min(running, value)
        adjusted[index] = min(1.0, running)
    return adjusted


def _relation_ids(
    finding: Dict[str, Any],
    relation_of: Dict[str, Sequence[str]],
    primary_only: bool,
) -> List[str]:
    """取 finding 的关系类；primary_only 时只取注册表首类（一条证据只计一次）。"""
    explicit = finding.get("relation_type")
    if explicit:
        return [str(explicit)]
    method = str(finding.get("method") or "").strip()
    roles = [str(item) for item in (relation_of.get(method) or [])]
    return roles[:1] if primary_only else roles


def build_patterns(
    findings: Iterable[Dict[str, Any]],
    relation_of: Optional[Dict[str, Sequence[str]]] = None,
    *,
    alpha: float = DEFAULT_ALPHA,
    min_agree: float = DEFAULT_MIN_AGREE,
    min_members: int = DEFAULT_MIN_MEMBERS,
    primary_only: bool = DEFAULT_PRIMARY_ONLY,
    min_minority_share: float = DEFAULT_MIN_MINORITY_SHARE,
) -> Dict[str, Any]:
    """把 findings 聚成 patterns。

    - 无法归类的计入 `unmapped`；
    - 缺 `p_adj` / `horizon` / `eval_id` 的计入 `skipped`（eval_id 为契约必填）。
    """
    mapping = {
        str(key): [str(item) for item in value] for key, value in (relation_of or {}).items()
    }
    groups: Dict[Tuple[str, str, int], List[Dict[str, Any]]] = {}
    unmapped: set[str] = set()
    skipped = 0

    for finding in findings:
        if not isinstance(finding, dict):
            skipped += 1
            continue
        eval_id = str(finding.get("eval_id") or "").strip()
        if not eval_id:
            skipped += 1
            continue
        rank_ic = finding.get("rank_ic")
        p_adj = finding.get("p_adj")
        try:
            horizon = int(finding.get("horizon"))
        except (TypeError, ValueError):
            skipped += 1
            continue
        if rank_ic is None or p_adj is None:
            skipped += 1
            continue
        relations = _relation_ids(finding, mapping, primary_only)
        if not relations:
            unmapped.add(str(finding.get("method") or "unknown"))
            continue
        family = family_of(finding.get("transform"))
        for relation in relations:
            groups.setdefault((relation, family, horizon), []).append(finding)

    drafts: List[Dict[str, Any]] = []
    pvalues: List[float] = []
    for (relation, family, horizon), members in groups.items():
        support = 0
        oppose = 0
        for item in members:
            value = float(item.get("rank_ic") or 0.0)
            significant = float(item.get("p_adj") or 1.0) < alpha and value != 0.0
            if not significant:
                continue
            if value > 0:
                support += 1
            else:
                oppose += 1
        significant_n = support + oppose
        if significant_n == 0:
            continue
        direction = 1 if support >= oppose else -1
        agreement = round(max(support, oppose) / float(significant_n), 6)
        minority_share = min(support, oppose) / float(significant_n)
        p_value = round(_binom_two_sided(max(support, oppose), significant_n), 6)
        drafts.append(
            {
                "pattern_id": f"PAT-{relation}-{family}-h{horizon}",
                "relation_type": relation,
                "family": family,
                "horizon": horizon,
                "direction": direction,
                "support": support,
                "oppose": oppose,
                "significant_n": significant_n,
                "sign_agreement": agreement,
                "bimodal": minority_share >= min_minority_share,
                "p_value": p_value,
                "members": sorted({str(item["eval_id"]) for item in members}),
            }
        )
        pvalues.append(p_value)

    adjusted = _bh(pvalues)
    for draft, p_adj in zip(drafts, adjusted, strict=False):
        draft["p_adj"] = round(float(p_adj), 6)
        stable = (
            draft["sign_agreement"] >= min_agree
            and draft["p_adj"] < alpha
            and draft["significant_n"] >= min_members
        )
        draft["status"] = "stable" if stable else "candidate"

    drafts.sort(key=lambda item: item["pattern_id"])
    return {
        "schema_version": SCHEMA_VERSION,
        "params": {
            "alpha": alpha,
            "min_agree": min_agree,
            "min_members": min_members,
            "primary_only": primary_only,
        },
        "pattern_count": len(drafts),
        "unmapped": sorted(unmapped),
        "skipped": skipped,
        "patterns": drafts,
    }


def validate_document(document: Dict[str, Any]) -> List[str]:
    """结构校验（等价于 contracts/patterns.schema.json 的必填与白名单检查）。"""
    errors: List[str] = []
    if not isinstance(document, dict):
        return ["document 必须是对象"]
    if document.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version 必须为 1.0")
    patterns = document.get("patterns")
    if not isinstance(patterns, list):
        return errors + ["patterns 必须是数组"]
    for index, pattern in enumerate(patterns):
        if not isinstance(pattern, dict):
            errors.append(f"patterns[{index}] 必须是对象")
            continue
        extra = sorted(set(pattern) - set(PATTERN_KEYS))
        if extra:
            errors.append(f"patterns[{index}] 含非法字段 {extra}（禁止自然语言/附加字段）")
        missing = [key for key in PATTERN_KEYS if key not in pattern]
        if missing:
            errors.append(f"patterns[{index}] 缺字段 {missing}")
        if pattern.get("status") not in ("stable", "candidate"):
            errors.append(f"patterns[{index}] status 非法")
        if not isinstance(pattern.get("bimodal"), bool):
            errors.append(f"patterns[{index}] bimodal 必须是布尔值")
        if not isinstance(pattern.get("members"), list):
            errors.append(f"patterns[{index}] members 必须是数组")
    return errors


def to_json(document: Dict[str, Any]) -> str:
    return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
