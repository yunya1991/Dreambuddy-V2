"""P0 试爬回填：odaily 深度文章 500 篇正文 + C1 广告剔除 + 报告（SPEC-D1 §4 P0）。

用法：
  python3 scripts/backfill_odaily_post_content.py --target 500

流程：
  1. odaily_post 列表翻页（depth_only=True）收集深度文章 id+元数据
  2. odaily_post_content 逐篇爬正文（sleep 800ms，礼貌爬取）
  3. ad_filter 双判据剔除，审计 JSONL 落盘
  4. 报告：成功率 / 剔除率 / 深度板块分布 → backfill/report_odaily_p0.json

FAIL-OPEN：中断已爬结果仍落盘（每 50 篇 checkpoint）。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_center.collectors.news.odaily_post import OdailyPostCollector  # noqa: E402
from data_center.collectors.news.odaily_post_content import (  # noqa: E402
    OdailyPostContentCollector,
)
from data_center.processing.ad_filter import filter_batch  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_odaily_p0")

OUT_DIR = ROOT / "backfill" / "odaily_p0"
SLEEP_MS = 800
CHECKPOINT_EVERY = 50


def _fetch_page_retry(c: OdailyPostCollector, page: int, retries: int = 3) -> list:
    """单页拉取带重试：FAIL-OPEN 返回 [] 可能是瞬时网络错误，不直接当翻页结束。"""
    for attempt in range(retries):
        recs = c.fetch({"page": page, "limit": 100, "depth_only": True})
        if recs:
            return recs
        logger.warning("page=%d 空结果（attempt %d/%d），重试", page, attempt + 1, retries)
        time.sleep(2 * (attempt + 1))
    return []


def collect_depth_ids(target: int) -> list[dict]:
    """翻页收集深度文章元数据（depthPlateId>0）。

    终止判据：连续 3 页（重试后仍）空才算真实结束，避免瞬时错误截断。
    """
    c = OdailyPostCollector()
    metas: list[dict] = []
    page = 1
    empty_streak = 0
    while len(metas) < target and page <= 500:
        recs = _fetch_page_retry(c, page)
        if not recs:
            empty_streak += 1
            if empty_streak >= 3:
                logger.info("连续 3 页空，停止翻页 page=%d", page)
                break
            page += 1
            continue
        empty_streak = 0
        for r in recs:
            metas.append(
                {
                    "id": r.metrics["odp_source_id"],
                    "title": r.raw.get("title", ""),
                    "summary": r.raw.get("summary", ""),
                    "depth_plate_id": r.metrics["odp_depth_plate_id"],
                }
            )
        logger.info("page=%d 累计深度文章 %d/%d", page, len(metas), target)
        page += 1
        time.sleep(0.5)
    return metas[:target]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=500)
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cc = OdailyPostContentCollector()

    metas = collect_depth_ids(args.target)
    logger.info("深度文章元数据收集完成: %d", len(metas))

    results: list[dict] = []
    for i, meta in enumerate(metas):
        rec = cc.fetch({"ids": [meta["id"]]})[0]
        m = rec.metrics
        results.append(
            {
                **meta,
                "fetch_ok": m["odpc_fetch_ok"] == "true",
                "content_text": rec.raw.get("content_text", ""),
                "content_len": m["odpc_content_len"],
                "date_published": m["odpc_date_published"],
            }
        )
        if (i + 1) % CHECKPOINT_EVERY == 0:
            _checkpoint(results)
            logger.info("checkpoint %d/%d", i + 1, len(metas))
        time.sleep(SLEEP_MS / 1000.0)
    _checkpoint(results)

    # C1 广告剔除 + 审计
    decisions = filter_batch(results, audit_path=str(OUT_DIR / "c1_audit.jsonl"))
    for r, d in zip(results, decisions, strict=False):
        r["c1_decision"] = d["decision"]
        r["c1_rules"] = d["hit_rules"]

    # 报告
    ok = [r for r in results if r["fetch_ok"]]
    dropped = [r for r in results if r.get("c1_decision") == "drop"]
    plate_dist: dict[str, int] = {}
    for r in ok:
        plate_dist[str(r["depth_plate_id"])] = plate_dist.get(str(r["depth_plate_id"]), 0) + 1
    report = {
        "target": args.target,
        "meta_collected": len(metas),
        "crawled": len(results),
        "fetch_ok": len(ok),
        "success_rate": round(len(ok) / max(1, len(results)), 4),
        "c1_drop": len(dropped),
        "c1_drop_rate": round(len(dropped) / max(1, len(results)), 4),
        "low_density": sum(1 for r in results if "low_density" in r.get("c1_rules", [])),
        "depth_plate_dist": dict(sorted(plate_dist.items(), key=lambda x: -x[1])),
        "avg_content_len": round(sum(r["content_len"] for r in ok) / max(1, len(ok))),
    }
    (OUT_DIR / "report_odaily_p0.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("报告: %s", json.dumps(report, ensure_ascii=False))
    return 0


def _checkpoint(results: list[dict]) -> None:
    (OUT_DIR / "contents.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in results) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    sys.exit(main())
