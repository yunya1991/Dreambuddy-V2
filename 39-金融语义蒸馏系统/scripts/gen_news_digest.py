# -*- coding: utf-8 -*-
"""gen_news_digest.py — 新闻检索库产物生成（SPEC-41-L1-新闻意图检索 §6）

为什么需要它：hot_news.json 是 24h / top50 影响力榜，天然挤出加密类内容且无历史纵深，
不能作为 `event_listing` 的检索源。本脚本产出全量 + 30 天的检索用摘要库。

输入：semantic_events.jsonl 中 source=="events.jsonl" 且 event 非空的行
逻辑：标题归一化去重（保留最早 + dup_count）→ 计算 importance → 输出 news_digest/v1
输出：news_digest.json（覆盖写 + 临时文件原子 rename，可重复执行）

用法：
  python3 gen_news_digest.py                     # 默认 30 天 → 39-金融语义蒸馏系统/news_digest.json
  python3 gen_news_digest.py --window-days 7 --out /tmp/digest.json
"""

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SYS_DIR = os.path.dirname(_THIS_DIR)
_REPO = os.path.dirname(_SYS_DIR)

if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from gen_semantic_events import (  # noqa: E402
    _parse_ts,
    _row_event_type,
    _row_title,
    _sentiment_block,
    importance,
    normalize_title,
    topic_of,
)

SEMANTIC_PATH = os.environ.get("SEMANTIC_EVENTS_PATH") or os.path.join(
    _SYS_DIR, "semantic_events.jsonl"
)
DIGEST_PATH = os.environ.get("NEWS_DIGEST_PATH") or os.path.join(_SYS_DIR, "news_digest.json")

SCHEMA = "news_digest/v1"
DEFAULT_WINDOW_DAYS = 30
MAX_WINDOW_DAYS = 30
MAX_ITEMS = 8000
MAX_TITLE_LEN = 200
MAX_BYTES = 4 * 1024 * 1024


def _load_rows(path):
    rows = []
    if not os.path.isfile(path):
        return rows
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def _item_id(title, ts_text):
    return hashlib.sha1(f"{title}|{ts_text}".encode("utf-8")).hexdigest()[:16]


def _atomic_write_compact(path, payload):
    """紧凑 JSON（无缩进）原子写：4MB 上限靠此才够装 8000 条。"""
    tmp = f"{path}.tmp"
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def build_news_digest(rows, now=None, window_days=DEFAULT_WINDOW_DAYS):
    """语义事件行 → 检索摘要库（dict）。纯函数，便于测试。"""
    now = now or datetime.now(timezone.utc)
    window_days = max(1, min(int(window_days), MAX_WINDOW_DAYS))
    cutoff = now - timedelta(days=window_days)

    # 1) 取窗口内 events 源、有 event 块的行
    entries = []
    for row in rows:
        if row.get("source") != "events.jsonl":
            continue
        if not isinstance(row.get("event"), dict):
            continue
        dt = _parse_ts(row.get("timestamp"))
        if dt is None or dt < cutoff or dt > now:
            continue
        title = _row_title(row)
        if not title:
            continue
        entries.append({"row": row, "ts": dt, "title": title, "norm": normalize_title(title)})

    # 2) 按归一化标题去重：保留最早一条，统计重复数与多源印证
    groups = {}
    for entry in entries:
        groups.setdefault(entry["norm"], []).append(entry)

    items = []
    topic_dist = Counter()
    models = Counter()
    high_impact = 0
    unscored = 0
    for members in groups.values():
        rep = min(members, key=lambda e: e["ts"])
        row = rep["row"]
        origins = {str(m["row"].get("origin") or "unknown") for m in members}
        sentiment = row.get("sentiment")
        etype = _row_event_type(row)
        score, parts = importance(
            published_at=row.get("timestamp"),
            etype=etype,
            sentiment=sentiment,
            origin=row.get("origin"),
            source_count=len(origins),
            now=now,
        )
        topic = row.get("topic") or topic_of(rep["title"])
        block = _sentiment_block(sentiment)
        if block is None:
            unscored += 1
        elif isinstance(sentiment, dict) and sentiment.get("model"):
            models[sentiment["model"]] += 1
        if score >= 70:
            high_impact += 1
        topic_dist[topic] += 1
        items.append(
            {
                "id": _item_id(rep["title"], row.get("timestamp")),
                "ts": row.get("timestamp"),
                "title": rep["title"][:MAX_TITLE_LEN],
                "topic": topic,
                "event_type": etype,
                "sentiment": block,
                "importance": score,
                "origin": row.get("origin"),
                "source_url": row.get("source_url"),
                "source_count": len(origins),
                "dup_count": len(members) - 1,
                "_ts": rep["ts"].timestamp(),
            }
        )

    # 3) 排序 + 截断
    items.sort(key=lambda x: (-x["importance"], -x["_ts"]))
    truncated = False
    if len(items) > MAX_ITEMS:
        items = items[:MAX_ITEMS]
        truncated = True
    for item in items:
        item.pop("_ts", None)

    total_in_window = len(entries)
    dedup_saved = total_in_window - len(groups)

    payload = {
        "schema": SCHEMA,
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window_days": window_days,
        "max_window_days": MAX_WINDOW_DAYS,
        "model": Counter(models).most_common(1)[0][0] if models else "unavailable",
        "degraded": unscored > 0,
        "coverage": {},
        "topic_dist": dict(topic_dist.most_common()),
        "stats": {
            "total": total_in_window,
            "dedup_saved": dedup_saved,
            "high_impact": high_impact,
            "items": len(items),
            "unscored": unscored,
            "truncated": truncated,
        },
        "items": items,
    }
    payload["coverage"] = _coverage(items, now, window_days)
    return _enforce_size(payload)


def _coverage(items, now, window_days):
    """窗口内逐日计数，缺失日补 0（§6.3 硬约束）。"""
    counts = Counter()
    for item in items:
        dt = _parse_ts(item.get("ts"))
        if dt is not None:
            counts[dt.strftime("%Y-%m-%d")] += 1
    days = []
    today = now.date()
    for i in range(window_days - 1, -1, -1):
        days.append((today - timedelta(days=i)).strftime("%Y-%m-%d"))
    return {d: counts.get(d, 0) for d in days}


def _enforce_size(payload):
    """文件 ≤4MB：超出按 importance 截断（已按 importance 降序，直接砍尾部）。"""
    while payload["items"]:
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(raw) <= MAX_BYTES:
            return payload
        keep = max(1, int(len(payload["items"]) * 0.9))
        payload["items"] = payload["items"][:keep]
        payload["stats"]["items"] = len(payload["items"])
        payload["stats"]["truncated"] = True
    return payload


def write_news_digest(semantic_path=None, out_path=None, now=None, window_days=DEFAULT_WINDOW_DAYS):
    """读取语义事件流 → 覆盖写 news_digest.json（幂等）。"""
    semantic_path = semantic_path or SEMANTIC_PATH
    out_path = out_path or DIGEST_PATH
    payload = build_news_digest(_load_rows(semantic_path), now=now, window_days=window_days)
    _atomic_write_compact(out_path, payload)
    return payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--in", dest="src", default=None, help="语义事件流路径")
    parser.add_argument("--out", default=None, help="输出路径（默认 39/news_digest.json）")
    parser.add_argument(
        "--window-days", type=int, default=DEFAULT_WINDOW_DAYS, help="窗口天数（上限 30）"
    )
    args = parser.parse_args()
    payload = write_news_digest(args.src, args.out, window_days=args.window_days)
    out = args.out or DIGEST_PATH
    size = os.path.getsize(out) if os.path.isfile(out) else 0
    print(
        f"[OK] news_digest {payload['schema']} 窗口 {payload['window_days']}d "
        f"条目 {payload['stats']['items']} / 扫描 {payload['stats']['total']} "
        f"去重省 {payload['stats']['dedup_saved']} 高影响 {payload['stats']['high_impact']} "
        f"实体 {size} B → {out}"
    )


if __name__ == "__main__":
    main()
