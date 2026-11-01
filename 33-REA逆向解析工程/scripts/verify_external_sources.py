#!/usr/bin/env python3
"""外部源增量校验（云端）：存在性 + 归档 + 语言/许可/star 硬指标（Q2）。

对应 SPEC-33-外部源自动沉淀流水线 §8.3 step3 / §8.5 内存门禁 / §8.7 Q2：
  选取：未校验 或 last_checked_at 超过 stale_days（默认 30 天），单次上限 40
  并发：固定 1；每源前后各一次内存检查，越线即停（已完成结果保留）
  门禁：MemAvailable < 800MB 或占总量 < 10% → 写 ALERT + exit 3，不改主清单
  写盘：原子替换；storage 不变则不写

用法（在 33-REA逆向解析工程 目录下）：
  python3 scripts/verify_external_sources.py --limit 5 --dry-run
  python3 scripts/verify_external_sources.py --limit 40
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REA_DIR = Path(__file__).resolve().parents[1]
SOURCES_JSON = REA_DIR / "reflection_data" / "external_sources.json"
REPORT_DIR = REA_DIR / "reflection_data" / "reports"
ALERT_DIR = REPORT_DIR

MIN_STARS = int(os.environ.get("REA_MIN_STARS", "300"))
MEM_MIN_MB = int(os.environ.get("REA_MEM_MIN_FREE_MB", "800"))
MEM_MIN_PCT = float(os.environ.get("REA_MEM_MIN_FREE_PCT", "10"))
DEFAULT_LIMIT = int(os.environ.get("REA_VERIFY_LIMIT", "40"))
STALE_DAYS = int(os.environ.get("REA_VERIFY_STALE_DAYS", "30"))
OK_LANGS = {"Python", "TypeScript"}
# 科研仓库 primary language 常为 Notebook，实现语言仍是 Python
NOTEBOOK_LANGS = {"Jupyter Notebook"}
ACCEPT_LANGS = OK_LANGS | NOTEBOOK_LANGS
OK_LICENSES = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "BSD", "ISC", "MPL-2.0"}
UNKNOWN_LICENSES = {"unknown", "NOASSERTION", ""}
API_TIMEOUT = 15


def log(msg: str) -> None:
    print(f"[verify] {msg}", flush=True)


# ---------------------------------------------------------------- 内存门禁


def mem_stats() -> tuple[float | None, float | None]:
    """返回 (MemAvailable MB, MemTotal MB)。

    本地 macOS 无 /proc/meminfo → 返回 (None, None) 视为放行。
    测试/验收可用 REA_MEM_FAKE_AVAILABLE_MB 模拟低内存。
    """
    fake = os.environ.get("REA_MEM_FAKE_AVAILABLE_MB")
    if fake:
        try:
            return float(fake), float(os.environ.get("REA_MEM_FAKE_TOTAL_MB", "8000"))
        except ValueError:
            return None, None
    try:
        info = Path("/proc/meminfo").read_text()
        avail = int(re.search(r"MemAvailable:\s+(\d+) kB", info).group(1)) / 1024
        total = int(re.search(r"MemTotal:\s+(\d+) kB", info).group(1)) / 1024
        return avail, total
    except Exception:
        return None, None


def mem_gate(alert_dir: Path | None = None, stage: str = "run") -> bool:
    """硬门禁：不通过则写 ALERT 并返回 False（调用方 exit 3）。"""
    avail, total = mem_stats()
    if avail is None:
        return True
    pct = (avail / total * 100) if total else 100.0
    if avail < MEM_MIN_MB or pct < MEM_MIN_PCT:
        target = alert_dir or ALERT_DIR
        target.mkdir(parents=True, exist_ok=True)
        alert = {
            "type": "memory_pressure",
            "ts": dt.datetime.now().isoformat(timespec="seconds"),
            "stage": stage,
            "mem_available_mb": round(avail, 1),
            "mem_total_mb": round(total, 1) if total else None,
            "mem_available_pct": round(pct, 1),
            "threshold_mb": MEM_MIN_MB,
            "threshold_pct": MEM_MIN_PCT,
            "action": "pause",
        }
        path = target / f"ALERT_mem_{dt.datetime.now():%Y%m%d_%H%M%S}.json"
        path.write_text(json.dumps(alert, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"ALERT mem_available={avail:.0f}MB({pct:.1f}%) < {MEM_MIN_MB}MB/{MEM_MIN_PCT}% → 暂停")
        return False
    return True


# ---------------------------------------------------------------- GitHub


def gh_api(owner_repo: str) -> dict | None:
    url = f"https://api.github.com/repos/{owner_repo}"
    headers = {"User-Agent": "rea-verify", "Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=API_TIMEOUT) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"__not_found__": True}
        raise
    finally:
        time.sleep(0.2)  # 固定并发 1，轻微退避


def parse_owner_repo(location: str) -> str:
    m = re.search(r"github\.com/([^/]+)/([^/?#]+)", location)
    return f"{m.group(1)}/{m.group(2)}" if m else ""


def q2_verdict(meta: dict, prior: dict | None = None) -> tuple[bool, str]:
    """Q2 硬指标：Python/TS + 宽松许可 + stars≥门限。

    GitHub 的 primary language 对科研仓库常报 Jupyter Notebook（实现仍是 Python），
    license 常报 NOASSERTION。因此：
      - Notebook 主语言视为 Python 兼容
      - 上述两类的 "无信息" 值不覆盖清单里已人工登记的具体值
    """
    if meta.get("archived"):
        return False, "archived"
    prior = prior or {}
    lang = meta.get("language") or ""
    if lang not in ACCEPT_LANGS and lang not in ("", None):
        return False, f"language={lang}"
    if not lang and (prior.get("language") or "") not in ACCEPT_LANGS:
        return False, "language=unknown"

    lic = (meta.get("license") or {}).get("spdx_id") or "unknown"
    if lic in UNKNOWN_LICENSES:
        prev = prior.get("license")
        if prev in OK_LICENSES:
            lic = prev
    if lic not in OK_LICENSES:
        return False, f"license={lic}"
    stars = meta.get("stargazers_count") or 0
    if stars < MIN_STARS:
        return False, f"stars={stars}<{MIN_STARS}"
    return True, "ok"


def _stale_days(last: str | None) -> int:
    if not last:
        return 10**6
    try:
        d = dt.date.fromisoformat(str(last)[:10])
    except ValueError:
        return 10**6
    return (dt.date.today() - d).days


def pick_targets(sources: list[dict], limit: int, stale_days: int) -> list[dict]:
    cand = [
        s
        for s in sources
        if s.get("source_type") == "github_repo"
        and not s.get("retired")
        and (not s.get("verified") or _stale_days(s.get("last_checked_at")) >= stale_days)
    ]
    # 长期未校验优先，其次未校验
    cand.sort(key=lambda s: (-_stale_days(s.get("last_checked_at")), s.get("id", "")))
    return cand[:limit]


def _write_atomic(data: dict) -> None:
    lock_path = SOURCES_JSON.with_suffix(".json.lock")
    with open(lock_path, "w") as lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        tmp = SOURCES_JSON.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, SOURCES_JSON)
        fcntl.flock(lock_fd, fcntl.LOCK_UN)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    ap.add_argument("--stale-days", type=int, default=STALE_DAYS)
    ap.add_argument("--dry-run", action="store_true", help="只校验不写主清单")
    ap.add_argument("--offline", action="store_true", help="不访问网络，仅列出待校验清单")
    ar = ap.parse_args(argv)

    if not mem_gate(stage="start"):
        return 3

    if not SOURCES_JSON.exists():
        log(f"FATAL 主清单不存在: {SOURCES_JSON}")
        return 2
    data = json.loads(SOURCES_JSON.read_text(encoding="utf-8"))
    targets = pick_targets(data.get("sources", []), ar.limit, ar.stale_days)
    log(f"targets={len(targets)} limit={ar.limit} stale_days={ar.stale_days} offline={ar.offline}")

    results, errors = [], []
    paused = False
    mem_peak = None
    for i, src in enumerate(targets, 1):
        label = src.get("id", "?")
        if ar.offline:
            results.append({"id": label, "location": src["location"], "skipped": "offline"})
            continue
        if not mem_gate(stage=f"pre:{label}"):
            paused = True
            break
        owner_repo = parse_owner_repo(src["location"])
        try:
            meta = gh_api(owner_repo) if owner_repo else None
        except Exception as e:  # 网络/限流：不改条目，下周重试
            log(f"{i}/{len(targets)} ERROR {label}: {e}")
            errors.append({"id": label, "error": str(e)})
            continue
        if meta is None:
            errors.append({"id": label, "error": "bad_location"})
            continue

        if meta.get("__not_found__"):
            rec = {
                "id": label,
                "location": src["location"],
                "verified": False,
                "reason": "repo_not_found",
                "stars": None,
                "language": None,
                "license": None,
            }
            src["verified"] = False
            src["verify_reason"] = "repo_not_found"
            src["last_checked_at"] = dt.date.today().isoformat()
        else:
            ok, reason = q2_verdict(meta, prior=src)
            lic = (meta.get("license") or {}).get("spdx_id") or "unknown"
            prior_lic = src.get("license")
            if lic in UNKNOWN_LICENSES and prior_lic in OK_LICENSES:
                lic = prior_lic  # NOASSERTION/unknown 不覆盖已登记的具体许可
            rec = {
                "id": label,
                "location": src["location"],
                "verified": True,
                "reason": reason,
                "stars": meta.get("stargazers_count"),
                "language": meta.get("language"),
                "license": lic,
                "admissible": ok,
            }
            src["verified"] = True
            src["verify_reason"] = reason
            src["stars"] = meta.get("stargazers_count")
            if meta.get("language"):
                src["language"] = meta["language"]
            src["license"] = lic
            src["admissible"] = ok
            src["last_checked_at"] = dt.date.today().isoformat()
            # 仅在做候选层时升级，不降级 priority/qualified
            if ok and src.get("level") == "candidate":
                src["level"] = "qualified"
                src["wave"] = src.get("wave", 4)
        log(f"{i}/{len(targets)} {label:26s} verified={rec['verified']} {rec['reason']}")
        results.append(rec)

        avail, _ = mem_stats()
        if avail is not None:
            mem_peak = avail if mem_peak is None else min(mem_peak, avail)
        if not mem_gate(stage=f"post:{label}"):
            paused = True
            break

    avail, total = mem_stats()
    if avail is not None:
        mem_peak = avail if mem_peak is None else min(mem_peak, avail)

    if results and not ar.dry_run:
        _write_atomic(data)
        log(f"write main total={len(data.get('sources', []))}")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "dry_run": ar.dry_run,
        "limit": ar.limit,
        "stale_days": ar.stale_days,
        "checked": len(results),
        "targets": len(targets),
        "verified_ok": sum(1 for r in results if r.get("verified")),
        "admissible": sum(1 for r in results if r.get("admissible")),
        "errors": errors,
        "paused_memory": paused,
        "mem_available_mb": round(avail, 1) if avail else None,
        "mem_total_mb": round(total, 1) if total else None,
        "mem_peak_available_mb": round(mem_peak, 1) if mem_peak else None,
        "items": results,
    }
    path = REPORT_DIR / f"verify-{dt.date.today().isoformat()}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    log(
        f"checked={len(results)} ok={report['verified_ok']} errors={len(errors)} report={path.name}"
    )

    if paused:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
