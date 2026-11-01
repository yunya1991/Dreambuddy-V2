#!/usr/bin/env python3
"""云端一次性评估 + 注入：inbox 候选 → GitHub API 校验 → 分级 → 合并主清单 → 分批注入。

分级规则（方案 §8.7 Q2/Q3）：
  reject    语言不在 {Python, TypeScript} / 已归档 / 仓库不存在
  qualified stars >= MIN_STARS 且 license ∈ 宽松许可  → 进主清单，wave=4
  candidate 其余（stars 不足或无 license）              → 留在 inbox，不进主清单

内存门禁（方案 §8.5）：MemAvailable < REA_MEM_MIN_FREE_MB(默认800) → 写 ALERT + exit 3。

用法（在 33-REA逆向解析工程 目录下）：
  python3 scripts/oneshot_inbox_ingest.py --dry-run
  python3 scripts/oneshot_inbox_ingest.py --apply --inject --inject-max 5
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

REA_DIR = Path(__file__).resolve().parents[1]
os.chdir(REA_DIR)
sys.path.insert(0, ".")

SOURCES_JSON = Path("reflection_data/external_sources.json")
INBOX_FILE = Path("reflection_data/inbox/external_sources.local.json")
REPORT_DIR = Path("reflection_data/reports")
ALERT_DIR = Path("reflection_data/reports")

MIN_STARS = int(os.environ.get("REA_MIN_STARS", "300"))
MEM_MIN_MB = int(os.environ.get("REA_MEM_MIN_FREE_MB", "800"))
OK_LANGS = {"Python", "TypeScript"}
OK_LICENSES = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "BSD", "ISC", "MPL-2.0"}


def log(msg: str) -> None:
    print(f"[oneshot] {msg}", flush=True)


def mem_available_mb() -> float | None:
    try:
        info = Path("/proc/meminfo").read_text()
        avail = int(re.search(r"MemAvailable:\s+(\d+) kB", info).group(1))
        return avail / 1024
    except Exception:
        return None


def mem_gate() -> bool:
    avail = mem_available_mb()
    if avail is None:
        return True
    if avail < MEM_MIN_MB:
        ALERT_DIR.mkdir(parents=True, exist_ok=True)
        alert = {
            "type": "memory_pressure",
            "ts": dt.datetime.now().isoformat(timespec="seconds"),
            "mem_available_mb": round(avail, 1),
            "threshold_mb": MEM_MIN_MB,
            "action": "pause",
        }
        (ALERT_DIR / f"ALERT_mem_{dt.datetime.now():%Y%m%d_%H%M%S}.json").write_text(
            json.dumps(alert, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"ALERT mem_available={avail:.0f}MB < {MEM_MIN_MB}MB → 暂停")
        return False
    return True


def gh_api(owner_repo: str) -> dict | None:
    url = f"https://api.github.com/repos/{owner_repo}"
    req = urllib.request.Request(url, headers={"User-Agent": "rea-ingest", "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r)
    except Exception as e:
        log(f"api_fail {owner_repo}: {e}")
        return None


def parse_owner_repo(loc: str) -> str:
    m = re.search(r"github\.com/([^/]+)/([^/?#]+)", loc)
    return f"{m.group(1)}/{m.group(2)}" if m else ""


def classify_level(meta: dict | None) -> tuple[str, str]:
    if meta is None:
        return "reject", "repo_not_found"
    if meta.get("archived"):
        return "reject", "archived"
    lang = meta.get("language") or ""
    if lang not in OK_LANGS:
        return "reject", f"language={lang or 'unknown'}"
    lic = (meta.get("license") or {}).get("spdx_id") or "unknown"
    if lic not in OK_LICENSES:
        return "reject", f"license={lic}"
    stars = meta.get("stargazers_count") or 0
    if stars < MIN_STARS:
        return "candidate", f"stars={stars}<{MIN_STARS}"
    return "qualified", "ok"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="写回主清单（否则仅评估报告）")
    ap.add_argument("--inject", action="store_true", help="对 qualified 执行 harvest 注入")
    ap.add_argument("--inject-max", type=int, default=5, help="单次注入上限")
    ap.add_argument("--batch", type=int, default=1, help="每批注入条数（并发固定 1）")
    args = ap.parse_args()

    if not mem_gate():
        return 3

    inbox = json.loads(INBOX_FILE.read_text(encoding="utf-8"))
    data = json.loads(SOURCES_JSON.read_text(encoding="utf-8"))
    existing = {s["location"].rstrip("/").lower(): s for s in data["sources"]}

    results = {"qualified": [], "candidate": [], "reject": []}
    evaluated = []
    for src in inbox.get("sources", []):
        owner_repo = parse_owner_repo(src["location"])
        meta = gh_api(owner_repo)
        level, reason = classify_level(meta)
        rec = {
            "id": src["id"], "location": src["location"], "category": src["category"],
            "level": level, "reason": reason,
            "stars": (meta or {}).get("stargazers_count"),
            "language": (meta or {}).get("language"),
            "license": ((meta or {}).get("license") or {}).get("spdx_id"),
        }
        evaluated.append(rec)
        results[level].append(rec)
        log(f"{level:9s} {owner_repo:42s} {reason}")

    merged = 0
    if args.apply:
        for rec in results["qualified"]:
            key = rec["location"].rstrip("/").lower()
            if key in existing:
                cur = existing[key]
                cur.update({"level": "qualified", "verified": True,
                            "stars": rec["stars"], "language": rec["language"],
                            "license": rec["license"] or cur.get("license"),
                            "last_checked_at": dt.date.today().isoformat()})
            else:
                entry = next(s for s in inbox["sources"] if s["location"] == rec["location"])
                entry.update({"level": "qualified", "verified": True, "priority": "P3", "wave": 4,
                              "stars": rec["stars"], "language": rec["language"],
                              "license": rec["license"], "last_checked_at": dt.date.today().isoformat()})
                data["sources"].append(entry)
                merged += 1
        tmp = SOURCES_JSON.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, SOURCES_JSON)
        log(f"merged_into_main={merged} total={len(data['sources'])}")

    injected, errors = [], []
    if args.inject and results["qualified"]:
        from core.reflection.harvest import ExternalHarvester, HarvestSource
        from core.reflection.replay_simulator import ReplayPool
        pool = ReplayPool("reflection_data/replay_pool")
        harvester = ExternalHarvester(pool, work_dir="/tmp/rea_harvest")
        existing_labels = {t.source_label for t in pool.list_trees("external")}
        todo = [r for r in results["qualified"] if r["id"] not in existing_labels][: args.inject_max]
        log(f"inject_candidates={len(todo)} (已存在跳过 {len(results['qualified']) - len(todo)})")
        for i in range(0, len(todo), max(1, args.batch)):
            if not mem_gate():
                errors.append("paused_memory")
                break
            chunk = todo[i:i + max(1, args.batch)]
            sources = [HarvestSource(source_type="github_repo", location=r["location"], label=r["id"]) for r in chunk]
            outcome = harvester.harvest(sources)
            injected.extend(t.source_label for t in outcome.injected_trees)
            errors.extend(str(e) for e in outcome.errors)
            log(f"batch={i//max(1,args.batch)+1} injected={len(outcome.injected_trees)} errors={len(outcome.errors)}")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "apply": args.apply, "inject": args.inject,
        "inbox_total": len(inbox.get("sources", [])),
        "qualified": len(results["qualified"]), "candidate": len(results["candidate"]),
        "reject": len(results["reject"]), "merged": merged,
        "injected": injected, "errors": errors,
        "mem_available_mb": mem_available_mb(),
        "items": evaluated,
    }
    path = REPORT_DIR / f"oneshot_ingest_{dt.date.today().isoformat()}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"report={path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
