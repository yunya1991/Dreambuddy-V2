#!/usr/bin/env python3
"""inbox → 主清单合并（云端唯一写者）。

对应 SPEC-33-外部源自动沉淀流水线 §8.2 单写者 + §8.4 合并协议：
  幂等键 location（小写去尾斜杠）
  两侧同源 → 并集 1 条，discovered_from 冲突值进 also_seen_in[]
  category 冲突 → priority 更高者胜（P0>P1>P2>P3），同级保留云端值
  id 冲突（不同 location 同 id）→ 先入者保留，后来者追加 -2、-3
  元数据冲突（license/stars/language）→ 云端校验值优先，本地值写 local_hint
  删除 → 不删，标 retired=true + retired_at
  重复执行 → content_hash 不变则不写盘

用法（在 33-REA逆向解析工程 目录下）：
  python3 scripts/merge_external_inbox.py --dry-run
  python3 scripts/merge_external_inbox.py            # 合并并归档 inbox
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import fcntl
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

REA_DIR = Path(__file__).resolve().parents[1]
SOURCES_JSON = REA_DIR / "reflection_data" / "external_sources.json"
INBOX_DIR = REA_DIR / "reflection_data" / "inbox"
ARCHIVE_DIR = INBOX_DIR / "archive"
REPORT_DIR = REA_DIR / "reflection_data" / "reports"

PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
META_FIELDS = ("license", "stars", "language")


def log(msg: str) -> None:
    print(f"[merge] {msg}", flush=True)


def norm_location(location: str) -> str:
    return location.rstrip("/").lower()


def content_hash(data: dict) -> str:
    """忽略版本/生成时间/合并历史后的内容指纹，用于幂等判定。"""
    payload = {
        k: v for k, v in data.items() if k not in ("version", "generated_at", "merge_history")
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def _unique_id(base: str, taken: set[str]) -> str:
    cand, n = base, 2
    while cand in taken:
        cand = f"{base}-{n}"
        n += 1
    return cand


def _fallback_id(location: str) -> str:
    tail = location.rstrip("/").split("/")[-1].lower()
    return tail or "repo"


def _merge_existing(cur: dict, inc: dict, stats: dict, today: str) -> bool:
    """把 inbox 提案合并进已存在条目；返回是否有变更。"""
    changed = False

    # discovered_from：主值保留，另一侧进 also_seen_in
    inc_from = inc.get("discovered_from")
    if inc_from and inc_from != cur.get("discovered_from"):
        also = cur.setdefault("also_seen_in", [])
        if inc_from not in also:
            also.append(inc_from)
            changed = True

    # category 冲突：priority 更高者胜，同级保留云端（当前 cur 即云端值）
    inc_cat = inc.get("category")
    if inc_cat and inc_cat != cur.get("category"):
        inc_rank = PRIORITY_RANK.get(str(inc.get("priority", "P3")), 3)
        cur_rank = PRIORITY_RANK.get(str(cur.get("priority", "P3")), 3)
        stats["category_conflict"] += 1
        if inc_rank < cur_rank and cur.get("category") != inc_cat:
            cur["category_from_inbox"] = inc_cat
            cur["category"] = inc_cat
            changed = True

    # 元数据冲突：云端已校验值优先，本地值只作参考
    for field in META_FIELDS:
        iv = inc.get(field)
        if iv in (None, "", "unknown"):
            continue
        cv = cur.get(field)
        if cv in (None, "", "unknown"):
            cur[field] = iv
            changed = True
        elif str(iv).lower() != str(cv).lower():
            if cur.get("verified"):
                hint = cur.setdefault("local_hint", {})
                if hint.get(field) != iv:
                    hint[field] = iv
                    changed = True
        else:
            pass

    # 退役标记：只增不删
    if inc.get("retired") and not cur.get("retired"):
        cur["retired"] = True
        cur["retired_at"] = inc.get("retired_at") or today
        changed = True

    return changed


def merge_payload(main: dict, inbox_payloads: list[dict], today: str) -> dict:
    """纯函数：返回统计，就地修改 main。"""
    sources = main.setdefault("sources", [])
    by_loc = {norm_location(s["location"]): s for s in sources}
    taken_ids = {s["id"] for s in sources}
    stats = {
        "added": 0,
        "updated": 0,
        "skipped": 0,
        "category_conflict": 0,
        "id_conflict": 0,
        "retired": 0,
        "inbox_total": 0,
        "matched_existing": 0,
        "new_ids": [],
    }

    for payload in inbox_payloads:
        for inc in payload.get("sources", []):
            loc = inc.get("location")
            if not loc:
                continue
            stats["inbox_total"] += 1
            key = norm_location(loc)
            cur = by_loc.get(key)
            if cur is not None:
                stats["matched_existing"] += 1
                if _merge_existing(cur, inc, stats, today):
                    stats["updated"] += 1
                else:
                    stats["skipped"] += 1
                if inc.get("retired"):
                    stats["retired"] += 1
                continue

            entry = copy.deepcopy(inc)
            base = entry.get("id") or _fallback_id(loc)
            if base in taken_ids:
                entry["id"] = _unique_id(base, taken_ids)
                stats["id_conflict"] += 1
            else:
                entry["id"] = base
            entry.setdefault("level", "candidate")
            entry.setdefault("source_type", "github_repo")
            entry.setdefault("size_cap_mb", 50)
            entry.setdefault("verified", False)
            entry.setdefault("discovered_at", today)
            entry["merged_from_inbox"] = True
            sources.append(entry)
            taken_ids.add(entry["id"])
            by_loc[key] = entry
            stats["added"] += 1
            stats["new_ids"].append(entry["id"])

    return stats


def _bump_version(version: str) -> str:
    try:
        return f"{float(version) + 0.01:.2f}"
    except (TypeError, ValueError):
        return "2.11"


def _write_atomic(data: dict) -> None:
    lock_path = SOURCES_JSON.with_suffix(".json.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        tmp = SOURCES_JSON.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, SOURCES_JSON)
        fcntl.flock(lock_fd, fcntl.LOCK_UN)


def load_inbox_files(inbox_dir: Path = INBOX_DIR) -> list[tuple[Path, dict]]:
    if not inbox_dir.is_dir():
        return []
    out = []
    for p in sorted(inbox_dir.glob("*.json")):
        try:
            out.append((p, json.loads(p.read_text(encoding="utf-8"))))
        except (OSError, ValueError) as e:
            log(f"skip_bad_inbox {p.name}: {e}")
    return out


def archive_inboxes(files: list[Path], archive_dir: Path = ARCHIVE_DIR) -> list[str]:
    if not files:
        return []
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    target = archive_dir / stamp
    target.mkdir(parents=True, exist_ok=True)
    moved = []
    for f in files:
        dest = target / f.name
        shutil.move(str(f), str(dest))
        moved.append(str(dest))
    return moved


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只报告，不写主清单、不归档")
    ap.add_argument("--no-archive", action="store_true", help="合并后保留 inbox 文件")
    ar = ap.parse_args(argv)

    if not SOURCES_JSON.exists():
        log(f"FATAL 主清单不存在: {SOURCES_JSON}")
        return 2
    main_data = json.loads(SOURCES_JSON.read_text(encoding="utf-8"))
    before_hash = content_hash(main_data)

    files = load_inbox_files()
    payloads = [p for _, p in files]
    log(
        f"inbox_files={len(files)} inbox_sources={sum(len(p.get('sources', [])) for p in payloads)}"
    )

    today = dt.date.today().isoformat()
    stats = merge_payload(main_data, payloads, today)
    after_hash = content_hash(main_data)
    changed = after_hash != before_hash

    if changed and not ar.dry_run:
        main_data["version"] = _bump_version(main_data.get("version", "2.1"))
        main_data["generated_at"] = today
        _write_atomic(main_data)
        log(f"write main total={len(main_data['sources'])} version={main_data['version']}")

    archived = []
    # inbox 全部已被主清单覆盖（本次新增或此前已合并）→ 可归档，避免每周重复消费
    consumed = stats["inbox_total"] > 0 and stats["matched_existing"] == stats["inbox_total"]
    if not ar.dry_run and not ar.no_archive and (changed or consumed):
        archived = archive_inboxes([f for f, _ in files])
        log(f"archived={len(archived)} consumed={consumed}")
    elif not ar.dry_run and files:
        log("inbox 仍有未入主清单的条目，保留（下周重试或人工确认）")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "dry_run": ar.dry_run,
        "inbox_files": [str(f.relative_to(REA_DIR)) for f, _ in files],
        "content_hash_before": before_hash,
        "content_hash_after": after_hash,
        "changed": changed,
        "total_sources": len(main_data.get("sources", [])),
        "archived": archived,
        **stats,
    }
    report_path = REPORT_DIR / f"merge-{today}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    log(
        f"added={stats['added']} updated={stats['updated']} skipped={stats['skipped']} "
        f"id_conflict={stats['id_conflict']} changed={changed} report={report_path.name}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
