#!/usr/bin/env python3
"""P5-3b：`dreambuddy cloud sync` —— 封装既有 dbsync 镜像，不另建第二套同步。

复用 `31-分布式计算部署/phase7/08-local-mirror.sh`（LaunchAgent com.dreambuddy.dbsync，
10 分钟周期），本命令只负责触发、超时与结果清单，避免双写分叉。

用法:
    python3 tools/cloud_sync.py            # 立即同步一次并输出清单
    python3 tools/cloud_sync.py --check    # 只检查本地镜像新鲜度（不联网）
    python3 tools/cloud_sync.py --json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "31-分布式计算部署/phase7/08-local-mirror.sh"
DAL_DIR = ROOT / "19-数据访问层/data"
CORE_DB = DAL_DIR / "dreambuddy_core.db"
COG_DB = ROOT / "4-MEMORY/data/cognitive_memory.db"
STALE_SECONDS = 1800
CORE_MIN_TABLES = 29
REQUIRED_TABLES = (
    "cv_config_versions",
    "tr_trades",
    "po_positions",
    "rs_state",
    "mm_metrics",
    "kg_triples",
)


def _file_info(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {"path": str(path), "exists": False}
    stat = path.stat()
    return {
        "path": str(path),
        "exists": True,
        "size": stat.st_size,
        "mtime": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(stat.st_mtime)),
        "age_seconds": int(time.time() - stat.st_mtime),
    }


def core_db_info() -> Dict[str, Any]:
    """核心库完整性：表数 ≥ 基线且关键表齐全（防止掩盖残缺镜像）。"""
    if not CORE_DB.is_file():
        return {
            "exists": False,
            "tables": 0,
            "min_tables": CORE_MIN_TABLES,
            "missing": list(REQUIRED_TABLES),
            "tables_ok": False,
        }
    try:
        conn = sqlite3.connect("file:{}?mode=ro".format(CORE_DB), uri=True)
        try:
            names = {
                row[0] for row in conn.execute("select name from sqlite_master where type='table'")
            }
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return {
            "exists": True,
            "tables": 0,
            "min_tables": CORE_MIN_TABLES,
            "missing": list(REQUIRED_TABLES),
            "tables_ok": False,
            "error": str(exc),
        }
    missing = [name for name in REQUIRED_TABLES if name not in names]
    return {
        "exists": True,
        "tables": len(names),
        "min_tables": CORE_MIN_TABLES,
        "missing": missing,
        "tables_ok": len(names) >= CORE_MIN_TABLES and not missing,
    }


def manifest() -> Dict[str, Any]:
    dbs = sorted(DAL_DIR.glob("*.db")) if DAL_DIR.is_dir() else []
    targets = [_file_info(path) for path in dbs] + [_file_info(COG_DB)]
    ages = [item["age_seconds"] for item in targets if item.get("exists")]
    core = core_db_info()
    fresh = bool(ages) and max(ages) <= STALE_SECONDS
    return {
        "script": str(SCRIPT),
        "script_exists": SCRIPT.is_file(),
        "targets": targets,
        "core_db": core,
        "fresh": fresh,
        "ok": fresh and core["tables_ok"],
        "stale_seconds": STALE_SECONDS,
    }


def run_sync(timeout: int = 300) -> Dict[str, Any]:
    if not SCRIPT.is_file():
        raise FileNotFoundError("E_INPUT：未找到 {}".format(SCRIPT))
    started = time.time()
    result = subprocess.run(
        ["/bin/bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    tail = (result.stdout or "").strip().splitlines()[-6:]
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "duration_ms": int((time.time() - started) * 1000),
        "tail": tail,
        "error": (result.stderr or "").strip()[-400:],
        "manifest": manifest(),
    }


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="DAL/认知库本地镜像（复用既有 dbsync）")
    parser.add_argument("--check", action="store_true", help="只检查新鲜度，不触发同步")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.check:
        report = manifest()
        code = 0 if report["ok"] else 1
    else:
        try:
            report = run_sync(args.timeout)
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            print("E_SYNC：{}".format(exc), file=sys.stderr)
            return 2
        code = 0 if report["ok"] else 1

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        data = report.get("manifest", report)
        for target in data["targets"]:
            if target.get("exists"):
                print(
                    "{}  {:.1f} MB  {}（{} 秒前）".format(
                        target["path"],
                        target["size"] / 1024 / 1024,
                        target["mtime"],
                        target["age_seconds"],
                    )
                )
            else:
                print("{}  缺失".format(target["path"]))
        print("镜像新鲜：{}".format("是" if data["fresh"] else "否"))
        if report.get("tail"):
            print("同步输出：")
            for line in report["tail"]:
                print("  " + line)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
