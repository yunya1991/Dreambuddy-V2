"""正文存储 — SPEC-EMERGENCE-FINANCIAL-ENV §3.1 / §3.2 红线 4。

设计纪律：
  1. 事件表只存引用：`body_ref = "bodies.jsonl#<body_id>"`，正文单独落盘避免事件表膨胀
  2. 正文必须是 point-in-time 快照：`date_published`（源发布时间）与 `fetched_at`（抓取时间）
     同时记录；源未暴露修订时间时 `revision_time=null`（禁止用修订后正文回填历史）
  3. append-only + `body_id` 幂等：sha1(source|url|date_published)[:16]
  4. 结构与 `18-数据获取中心/backfill/odaily_p0/contents.jsonl` 同构
     （id / url / title / content_text / content_len / date_published / fetch_ok）
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

BODIES_PATH = Path(__file__).resolve().parent / "bodies.jsonl"

_REQUIRED = ("id", "source", "url", "title", "date_published", "fetched_at")


class BodyContractError(ValueError):
    """正文不满足 point-in-time 快照契约。"""


def _parse_iso(ts: str, field: str) -> datetime:
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, TypeError) as e:
        raise BodyContractError(f"{field} 非合法 ISO8601：{ts!r}") from e
    if dt.tzinfo is None:
        raise BodyContractError(f"{field} 必须带时区：{ts!r}")
    return dt.astimezone(timezone.utc)


def make_body_id(source: str, url: str, date_published: str) -> str:
    """幂等键：sha1(source|url|date_published)[:16]。"""
    key = f"{source}|{url}|{date_published}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def body_ref(body_id: str) -> str:
    return f"bodies.jsonl#{body_id}"


def normalize_body(row: dict) -> dict:
    """补齐派生字段并校验，返回可直接落盘的 dict。"""
    if not isinstance(row, dict):
        raise BodyContractError(f"正文必须是 dict，收到 {type(row).__name__}")

    missing = [k for k in _REQUIRED if not row.get(k)]
    if missing:
        raise BodyContractError(f"正文缺少必填字段 {missing}：{row.get('title')!r}")

    date_published = _parse_iso(row["date_published"], "date_published")
    fetched_at = _parse_iso(row["fetched_at"], "fetched_at")
    revision = row.get("revision_time")
    if revision:
        revision = _parse_iso(revision, "revision_time").isoformat().replace("+00:00", "Z")

    content = str(row.get("content_text") or "")
    return {
        "id": str(row["id"]),
        "source": str(row["source"]),
        "url": str(row["url"]),
        "title": str(row["title"]),
        "content_text": content,
        "content_len": int(row.get("content_len") or len(content)),
        "content_sha1": row.get("content_sha1")
        or hashlib.sha1(content.encode("utf-8")).hexdigest()[:12],
        "date_published": date_published.isoformat().replace("+00:00", "Z"),
        "fetched_at": fetched_at.isoformat().replace("+00:00", "Z"),
        "revision_time": revision,
        "fetch_ok": bool(row.get("fetch_ok", True)),
        "lang": row.get("lang") or "zh",
    }


def load_bodies(path: Path | str | None = None) -> dict[str, dict]:
    """返回 body_id → 正文行；文件不存在返回空 dict。"""
    target = Path(path or BODIES_PATH)
    if not target.is_file():
        return {}
    out: dict[str, dict] = {}
    with open(target, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("id"):
                out[row["id"]] = row
    return out


def append_bodies(rows: list[dict], path: Path | str | None = None) -> tuple[int, int]:
    """按 body_id 幂等追加；返回 (新增数, 跳过数)。"""
    target = Path(path or BODIES_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    seen = set(load_bodies(target))

    to_write: list[dict] = []
    skipped = 0
    for row in rows:
        norm = normalize_body(row)
        if norm["id"] in seen:
            skipped += 1
            continue
        seen.add(norm["id"])
        to_write.append(norm)

    if to_write:
        with open(target, "a", encoding="utf-8") as f:
            for row in to_write:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(to_write), skipped


def resolve_body_ref(ref: str | None, index: dict[str, dict] | None = None) -> str:
    """把 `bodies.jsonl#<id>` 解析为正文文本；找不到返回 ""。"""
    if not ref:
        return ""
    body_id = str(ref).split("#")[-1].strip()
    row = (index if index is not None else load_bodies()).get(body_id)
    if not row:
        return ""
    return str(row.get("content_text") or "")
