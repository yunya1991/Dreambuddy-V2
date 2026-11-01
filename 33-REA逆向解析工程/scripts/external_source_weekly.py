#!/usr/bin/env python3
"""外部源周任务编排（云端 cron 入口）。

SPEC-33-外部源自动沉淀流水线 §8.3：
  [0] 内存门禁      MemAvailable < 800MB 或 < 10% → ALERT + exit 3（本周不跑）
  [1] 云端自调研入库 scan 全仓 md → 主清单（幂等 upsert；云端是唯一写者）
  [2] 消费本地 inbox merge_external_inbox.py → 归档
  [3] 增量校验      verify_external_sources.py（未验证或 >30 天，≤40，并发 1）
  [4] 可选注入      --inject-max N（默认 0 = 不注入）
  [5] 汇总报告      reflection_data/reports/weekly-<date>.json

用法（在 33-REA逆向解析工程 目录下）：
  python3 scripts/external_source_weekly.py --dry-run
  python3 scripts/external_source_weekly.py                  # 报告 + 合并，不注入
  python3 scripts/external_source_weekly.py --inject-max 5   # 额外注入 ≤5 源
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REA_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REA_DIR / "scripts"
SOURCES_JSON = REA_DIR / "reflection_data" / "external_sources.json"
REPORT_DIR = REA_DIR / "reflection_data" / "reports"

sys.path.insert(0, str(SCRIPTS_DIR))
from verify_external_sources import mem_gate, mem_stats  # noqa: E402


def log(msg: str) -> None:
    print(f"[weekly] {msg}", flush=True)


def run_step(name: str, args: list[str], timeout: int = 3600) -> dict:
    started = time.time()
    cmd = [sys.executable, str(SCRIPTS_DIR / args[0]), *args[1:]]
    log(f"step={name} cmd={' '.join(args)}")
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(REA_DIR),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        rc, out, err = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as e:
        rc, out, err = 124, (e.stdout or ""), f"timeout {timeout}s"
    except Exception as e:  # FAIL-OPEN
        rc, out, err = 125, "", str(e)
    elapsed = round(time.time() - started, 1)
    tail = "\n".join((out or "").strip().splitlines()[-6:])
    log(f"step={name} rc={rc} elapsed={elapsed}s")
    if rc != 0:
        log(f"step={name} tail={tail or err}")
    return {
        "name": name,
        "cmd": args,
        "returncode": rc,
        "elapsed_s": elapsed,
        "stdout_tail": tail,
        "stderr_tail": "\n".join((err or "").strip().splitlines()[-3:]),
    }


def pool_labels() -> set[str]:
    try:
        from core.reflection.replay_simulator import ReplayPool
    except Exception as e:
        log(f"pool_load_fail: {e}")
        return set()
    pool = ReplayPool(str(REA_DIR / "reflection_data" / "replay_pool"))
    return {t.source_label for t in pool.list_trees("external")}


def do_inject(inject_max: int) -> dict:
    """[4] 注入：仅 priority/qualified + verified + admissible 且池中未存在。"""
    if inject_max <= 0:
        return {"enabled": False}
    if not mem_gate(stage="inject:pre"):
        return {"enabled": True, "paused_memory": True, "injected": []}

    from core.reflection.harvest import ExternalHarvester, HarvestSource

    data = json.loads(SOURCES_JSON.read_text(encoding="utf-8"))
    existing = pool_labels()
    todo = [
        s
        for s in data.get("sources", [])
        if s.get("source_type") == "github_repo"
        and s.get("verified")
        and s.get("admissible")
        and s.get("level") in ("priority", "qualified")
        and s.get("id") not in existing
    ][:inject_max]
    log(f"inject_candidates={len(todo)}")

    work_dir = os.environ.get("REA_HARVEST_WORK", str(REA_DIR / "reflection_data" / "harvest_work"))
    from core.reflection.replay_simulator import ReplayPool

    harvester = ExternalHarvester(
        ReplayPool(str(REA_DIR / "reflection_data" / "replay_pool")), work_dir=work_dir
    )
    injected, rejected, errors = [], [], []
    for i, src in enumerate(todo, 1):
        if not mem_gate(stage=f"inject:{src['id']}"):
            return {
                "enabled": True,
                "paused_memory": True,
                "injected": injected,
                "rejected": rejected,
                "errors": errors,
            }
        outcome = harvester.harvest(
            [
                HarvestSource(
                    source_type="github_repo",
                    location=src["location"],
                    label=src["id"],
                    license=src.get("license") or "",
                )
            ]
        )
        injected.extend(src["id"] for _ in outcome.injected_trees)
        rejected.extend(outcome.rejected)
        errors.extend(str(e) for e in outcome.errors)
        log(f"inject {i}/{len(todo)} {src['id']} ok={len(outcome.injected_trees)}")
    return {
        "enabled": True,
        "paused_memory": False,
        "injected": injected,
        "rejected": rejected,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="各步 dry-run（不写主清单/不注入）")
    ap.add_argument("--limit", type=int, default=int(os.environ.get("REA_VERIFY_LIMIT", "40")))
    ap.add_argument("--inject-max", type=int, default=int(os.environ.get("REA_INJECT_MAX", "0")))
    ap.add_argument(
        "--roots",
        nargs="*",
        default=os.environ.get("REA_SCAN_ROOTS", ".").split(),
        help="step1 自调研扫描根目录（云端默认全仓）",
    )
    ap.add_argument("--skip", nargs="*", default=[], help="跳过步骤：scan merge verify inject")
    ar = ap.parse_args(argv)

    started = time.time()
    # [0] 硬门禁
    if not mem_gate(stage="start"):
        return 3
    avail, total = mem_stats()

    steps: list[dict] = []
    dry = ["--dry-run"] if ar.dry_run else []

    if "scan" not in ar.skip:
        steps.append(
            run_step(
                "scan",
                ["sync_external_sources.py", "--roots", *ar.roots, "--max-new", "50", *dry],
            )
        )
    if "merge" not in ar.skip:
        steps.append(run_step("merge", ["merge_external_inbox.py", *dry]))
    if "verify" not in ar.skip:
        steps.append(
            run_step("verify", ["verify_external_sources.py", "--limit", str(ar.limit), *dry])
        )

    inject = {"enabled": False}
    if "inject" not in ar.skip:
        inject = do_inject(0 if ar.dry_run else ar.inject_max)
        if inject.get("paused_memory"):
            log("inject 因内存门禁暂停（已完成结果保留）")

    avail_end, total_end = mem_stats()
    report = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "dry_run": ar.dry_run,
        "elapsed_s": round(time.time() - started, 1),
        "roots": ar.roots,
        "steps": steps,
        "inject": inject,
        "mem_start_mb": round(avail, 1) if avail else None,
        "mem_total_mb": round(total, 1) if total else None,
        "mem_end_mb": round(avail_end, 1) if avail_end else None,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / f"weekly-{dt.date.today().isoformat()}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"report={path.relative_to(REA_DIR)} elapsed={report['elapsed_s']}s")

    if any(s["returncode"] == 3 for s in steps) or inject.get("paused_memory"):
        log("PAUSED 内存门禁触发（exit 3）")
        return 3
    if any(s["returncode"] != 0 for s in steps):
        log("PARTIAL 有步骤失败（FAIL-OPEN，已写报告）")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
