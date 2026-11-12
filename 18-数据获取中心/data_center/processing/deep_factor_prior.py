"""深度文章组合因子（SPEC-EMERGENCE-FINANCIAL-ENV §8.3，打通 G8）。

链路：`events.jsonl` + `bodies.jsonl`（P1-A 四源正文）
      → F1/F2/F3（`factor_extractor.extract_dominance_claim`）
      → 组合因子（按 dominant_factor × direction × horizon 聚合）
      → `factor_prior.json`（去 degraded，按源分层）

与 `factor_prior.py` 的分工：
  - `factor_prior.py`：快讯敏感度先验（P3-c1），**默认关闭**（双证失败，见其 docstring）
  - 本模块：深度文章主导主张先验，**默认启用**，产出 `factor-prior-v2`

契约（SPEC §8.3）：
  - 必须带 `n_articles` / `n_sources` / `degraded_reason`
  - 组合因子必须按源分层：`by_source` 区分 crypto / traditional_finance / other
  - 某源 `n < 30` → 列入 `weak_evidence_sources`，**不进**顶层正式 `factors`
  - 保留 `newsflash` 块如实标注快讯先验状态（被关闭 ≠ 数据缺失）

FAIL-OPEN：任何异常返回 degraded 块，不阻断主链路，不抛。
"""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from data_center.processing.factor_extractor import extract_dominance_claim

logger = logging.getLogger("data_center.processing.deep_factor_prior")

_REPO = Path(__file__).resolve().parents[3]
_EVENTS_DIR = _REPO / "18-数据获取中心" / "data_center" / "events"
DEFAULT_EVENTS = _EVENTS_DIR / "events.jsonl"
DEFAULT_BODIES = _EVENTS_DIR / "bodies.jsonl"
DEFAULT_OUT = _REPO / "18-数据获取中心" / "backfill" / "p3c1" / "factor_prior.json"

COMPOSITE_VERSION = "factor-prior-v2"

# SPEC §8.3 / 39 SPEC §7.4：单源持续 n<30 视为弱证据
WEAK_MIN_ARTICLES = 30

TRADITIONAL = "traditional_finance"
CRYPTO = "crypto"
OTHER = "other"

TRADITIONAL_SOURCES = frozenset({"sina_finance", "wallstreetcn", "cls", "jin10"})
CRYPTO_SOURCES = frozenset(
    {"odaily", "cryptopanic", "panewslab", "blockbeats", "coindesk", "cointelegraph", "theblock"}
)


def tier_of(source: Any) -> str:
    s = str(source or "").strip().lower()
    if s in TRADITIONAL_SOURCES:
        return TRADITIONAL
    if s in CRYPTO_SOURCES:
        return CRYPTO
    return OTHER


def _load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not path.exists():
        return rows
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _body_id(body_ref: Any) -> str:
    """`bodies.jsonl#<id>` → `<id>`；无法解析返回空串。"""
    ref = str(body_ref or "").strip()
    if not ref:
        return ""
    return ref.rsplit("#", 1)[-1] if "#" in ref else ref


def _claims(
    events: Iterable[dict], bodies: dict[str, dict]
) -> tuple[list[dict], Counter, int, int]:
    """→ (claims, joined_by_source, n_joined, n_no_body)。

    弱证据阈值按**已取到正文的文章数**判断（SPEC §8.3「某源持续 n<30」），
    不是按 claim 数——claim 少可能只是文章没提主导因素，不等于该源样本不足。
    """
    claims: list[dict] = []
    joined_by_source: Counter = Counter()
    joined = 0
    no_body = 0
    for ev in events:
        body = bodies.get(_body_id(ev.get("body_ref")))
        if not body or body.get("fetch_ok") is False:
            no_body += 1
            continue
        text = body.get("content_text") or ""
        if not text.strip():
            no_body += 1
            continue
        joined += 1
        source = str(ev.get("source") or "unknown")
        joined_by_source[source] += 1
        claim = extract_dominance_claim(
            text,
            doc_id=str(ev.get("event_id") or body.get("id") or ""),
            published_at=str(ev.get("event_time") or ""),
        )
        if not claim.get("dominant_factor"):
            continue
        claims.append(
            {
                "factor_id": claim["dominant_factor"],
                "dimension": claim.get("dominant_dimension"),
                "direction": claim.get("direction") or "neutral",
                "horizon": claim.get("horizon") or "days",
                "urgency": float(claim.get("urgency") or 0.0),
                "impact": float(claim.get("impact") or 1.0),
                "confidence": float(claim.get("confidence_in_text") or 0.0),
                "source": source,
                "tier": tier_of(source),
                "available_at": str(ev.get("available_at") or ev.get("event_time") or ""),
            }
        )
    return claims, joined_by_source, joined, no_body


def _aggregate(rows: list[dict]) -> list[dict]:
    """按 (factor, horizon) 聚合成 SPEC §8.3 组合因子。

    不按 direction 分组：方向是聚合结果，聚合前先分组会让 `composite_score`
    恒为 ±1，失去"多空一致度"信息。
    """
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        grouped[(r["factor_id"], r["horizon"])].append(r)

    out: list[dict] = []
    for (factor, horizon), items in grouped.items():
        weights = [max(r["confidence"] * r["impact"], 0.0) for r in items]
        total_w = sum(weights)
        signed = 0.0
        for w, r in zip(weights, items, strict=True):
            signed += w * (
                1.0 if r["direction"] == "bullish" else -1.0 if r["direction"] == "bearish" else 0.0
            )
        score = (signed / total_w) if total_w else 0.0
        direction = "bullish" if score > 0.15 else "bearish" if score < -0.15 else "neutral"
        out.append(
            {
                "dominant_factor": factor,
                "dominant_dimension": items[0].get("dimension"),
                "direction": direction,
                "horizon": horizon,
                "urgency": round(sum(r["urgency"] for r in items) / len(items), 4),
                "impact": round(sum(r["impact"] for r in items) / len(items), 4),
                "composite_score": round(score, 4),
                "direction_mix": dict(Counter(r["direction"] for r in items).most_common()),
                "source_mix": dict(Counter(r["source"] for r in items).most_common()),
                "article_count": len(items),
                "_weight": round(total_w, 6),
            }
        )
    out.sort(key=lambda x: (-x["article_count"], -abs(x["composite_score"]), x["dominant_factor"]))
    return out


def _summary(rows: list[dict]) -> dict:
    factors = _aggregate(rows)
    return {
        "n_articles": len(rows),
        "n_sources": len({r["source"] for r in rows}),
        "n_factors": len(factors),
        "factors": factors,
    }


def build_composite_prior(
    *,
    events_path: Any = None,
    bodies_path: Any = None,
    out_path: Any = None,
    weak_min: int = WEAK_MIN_ARTICLES,
) -> dict:
    """读事件+正文 → 写 `factor_prior.json`（v2）。返回产物 dict。"""
    events_p = Path(events_path or DEFAULT_EVENTS)
    bodies_p = Path(bodies_path or DEFAULT_BODIES)
    out_p = Path(out_path or DEFAULT_OUT)
    result: dict[str, Any] = {
        "version": COMPOSITE_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of": None,
        "source": {"events": str(events_p), "bodies": str(bodies_p)},
        "degraded": True,
        "degraded_reason": None,
        "n_articles": 0,
        "n_sources": 0,
        "n_factors": 0,
        "dims": {},
        "factors": [],
        "by_source": {},
        "weak_evidence_sources": [],
        # 快讯先验仍按其双证结论保持关闭，如实标注而非静默缺字段
        "newsflash": {
            "degraded": True,
            "reason": "newsflash_prior_disabled_by_default",
            "n_factors": 0,
        },
    }
    try:
        events = _load_jsonl(events_p)
        if not events:
            result["degraded_reason"] = "events_missing"
            _write(out_p, result)
            return result

        bodies = {str(b.get("id")): b for b in _load_jsonl(bodies_p) if b.get("id")}
        claims, joined_by_source, joined, no_body = _claims(events, bodies)
        result.update(
            n_articles=joined,
            n_events=len(events),
            n_claims=len(claims),
            n_without_body=no_body,
        )
        if not claims:
            result["degraded_reason"] = "no_dominance_claims"
            _write(out_p, result)
            return result

        weak = sorted(s for s, n in joined_by_source.items() if n < weak_min)
        formal = [c for c in claims if c["source"] not in weak]

        tiers: dict[str, list[dict]] = defaultdict(list)
        for c in claims:
            tiers[c["tier"]].append(c)
        by_source: dict[str, Any] = {}
        for tier in (TRADITIONAL, CRYPTO, OTHER):
            rows = tiers.get(tier) or []
            if not rows:
                continue
            summary = _summary(rows)
            tier_sources = Counter(r["source"] for r in rows)
            summary["n_articles"] = sum(joined_by_source.get(s, 0) for s in tier_sources)
            summary["n_claims"] = len(rows)
            summary["weak_evidence"] = all(
                joined_by_source.get(s, 0) < weak_min for s in tier_sources
            )
            summary["sources"] = dict(tier_sources.most_common())
            by_source[tier] = summary

        factors = _aggregate(formal)
        dims: dict[str, float] = {}
        for f in factors:
            dim = str(f.get("dominant_dimension") or "?")
            dims[dim] = round(dims.get(dim, 0.0) + f["_weight"], 6)
        for f in factors:
            f.pop("_weight", None)

        dates = sorted(c["available_at"][:10] for c in claims if len(str(c["available_at"])) >= 10)
        result.update(
            as_of=dates[-1] if dates else None,
            n_sources=len(joined_by_source),
            n_factors=len(factors),
            factors=factors,
            dims=dims,
            by_source=by_source,
            weak_evidence_sources=[
                {"source": s, "n_articles": joined_by_source[s], "threshold": weak_min}
                for s in weak
            ],
            degraded=not factors,
            degraded_reason=None if factors else "no_formal_factors",
        )
        _write(out_p, result)
        return result
    except Exception as e:  # noqa: BLE003  FAIL-OPEN
        logger.warning("[FAIL-OPEN] build_composite_prior %s: %s", type(e).__name__, str(e)[:200])
        result.update(degraded=True, degraded_reason=f"error:{type(e).__name__}")
        return result


def _write(path: Path, payload: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:  # FAIL-OPEN
        logger.warning("[FAIL-OPEN] write composite prior %s: %s", type(e).__name__, str(e)[:120])


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="深度文章组合因子 → factor_prior.json")
    ap.add_argument("--events", default=None)
    ap.add_argument("--bodies", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--weak-min", type=int, default=WEAK_MIN_ARTICLES)
    args = ap.parse_args()
    res = build_composite_prior(
        events_path=args.events,
        bodies_path=args.bodies,
        out_path=args.out,
        weak_min=args.weak_min,
    )
    print(
        json.dumps(
            {
                "out": str(Path(args.out or DEFAULT_OUT)),
                "degraded": res["degraded"],
                "degraded_reason": res["degraded_reason"],
                "as_of": res["as_of"],
                "n_articles": res["n_articles"],
                "n_sources": res["n_sources"],
                "n_factors": res["n_factors"],
                "weak": [w["source"] for w in res["weak_evidence_sources"]],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not res["degraded"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
