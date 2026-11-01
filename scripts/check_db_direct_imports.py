#!/usr/bin/env python3
"""C3 直连基线仪表（report-only）。

扫描 adapter 之外的 DB 直连（sqlite3.connect / psycopg2.connect / pg8000.connect），
输出名单与趋势报告。SPEC-L0 §6 P0-C3：report-only，CI 不阻断；
C10 承接 enforce（先 report-only 2 周再切 enforce，包化前用 grep 门禁 + 白名单）。

基线（SPEC §4，云端 4d6837f880）：
  sqlite3.connect 179 处 / 85 文件（约 92% 在存储层之外）
  PG 直连 14 处 / 11 文件（含 39 dc_pg.py 民间封装；2026-10-30 云端复测 12 处/10 文件）

用法:
  python3 scripts/check_db_direct_imports.py            # 人读报告（默认）
  python3 scripts/check_db_direct_imports.py --json      # 机器可读（CI 记录趋势）
  python3 scripts/check_db_direct_imports.py --baseline  # 与 SPEC 基线对照
  python3 scripts/check_db_direct_imports.py --write-whitelist  # 生成/刷新白名单
  python3 scripts/check_db_direct_imports.py --ratchet   # C10 门禁：拦新增直连（阻断）

C10 ratchet 语义（SPEC §6 C10：grep 门禁 + 白名单，包化前不启用 import-linter）：
  - 白名单外文件出现直连 → 违规，exit 1；
  - 白名单内文件直连数超过登记值 → 违规，exit 1（存量只减不增）；
  - 白名单内已删除/已收编的文件不影响结果（允许只减）。
report 模式退出码恒为 0（不阻断）；--ratchet 违规时 exit 1。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# 存储层（adapter 所在，直连合法区）
STORAGE_LAYER_DIRS = ("19-数据访问层/dreambuddy_dal",)

# 扫描排除目录（.cognitive/.trae 为 gitignored 运行态，非仓内代码，不计入基线）
EXCLUDE_PARTS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    ".workbuddy",
    ".cognitive",
    ".trae",
}

# C10 白名单默认位置（与 capabilities.yaml / job_registry.yaml 同目录治理）
DEFAULT_WHITELIST = REPO_ROOT / "0-系统文档管理" / "db_direct_whitelist.tsv"

# 直连模式：sqlite3 / psycopg2 / pg8000
DIRECT_PATTERNS = {
    "sqlite3": re.compile(r"\bsqlite3\.connect\s*\("),
    "psycopg2": re.compile(r"\bpsycopg2\.connect\s*\("),
    "pg8000": re.compile(r"\bpg8000\.connect\s*\("),
}

# SPEC §4 云端基线（4d6837f880）
SPEC_BASELINE = {
    "sqlite3": {"hits": 179, "files": 85},
    "pg": {"hits": 14, "files": 11},
}


def is_storage_layer(rel_path: str) -> bool:
    return any(rel_path.startswith(d) for d in STORAGE_LAYER_DIRS)


def scan_repo() -> list:
    """扫描仓库，返回直连命中记录列表。"""
    records = []
    for py in REPO_ROOT.rglob("*.py"):
        rel = py.relative_to(REPO_ROOT).as_posix()
        if any(part in EXCLUDE_PARTS for part in py.parts):
            continue
        try:
            text = py.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for kind, pat in DIRECT_PATTERNS.items():
                if pat.search(line):
                    records.append(
                        {
                            "kind": kind,
                            "path": rel,
                            "line": lineno,
                            "in_storage_layer": is_storage_layer(rel),
                        }
                    )
    return records


def summarize(records: list) -> dict:
    files = {r["path"] for r in records}
    outside = [r for r in records if not r["in_storage_layer"]]
    outside_files = {r["path"] for r in outside}
    by_dir = {}
    for r in outside:
        top = r["path"].split("/")[0]
        by_dir[top] = by_dir.get(top, 0) + 1
    return {
        "total_hits": len(records),
        "total_files": len(files),
        "outside_hits": len(outside),
        "outside_files": len(outside_files),
        "outside_pct": round(len(outside) * 100.0 / len(records), 1) if records else 0.0,
        "by_top_dir": dict(sorted(by_dir.items(), key=lambda kv: -kv[1])),
    }


def print_human(records: list, summary: dict) -> None:
    print("=" * 72)
    print("C3 直连基线仪表（report-only，不阻断）")
    print("=" * 72)
    print("直连总命中   : %d 处 / %d 文件" % (summary["total_hits"], summary["total_files"]))
    print(
        "存储层之外   : %d 处 / %d 文件（%.1f%%）"
        % (summary["outside_hits"], summary["outside_files"], summary["outside_pct"])
    )
    print("")
    print("按顶层目录分布（存储层之外）:")
    for d, n in summary["by_top_dir"].items():
        print("  %5d  %s" % (n, d))
    print("")
    print("明细（存储层之外，前 200 条）:")
    shown = 0
    for r in records:
        if r["in_storage_layer"]:
            continue
        print("  %s:%d  [%s]" % (r["path"], r["line"], r["kind"]))
        shown += 1
        if shown >= 200:
            print("  ...（其余 %d 条省略，用 --json 查看全量）" % (summary["outside_hits"] - shown))
            break
    print("")
    print("判读：存储层之外 = C5 收编对象（分批走 Store port）；")
    print("      新增直连属违规（C10 enforce 后 CI 拦截，当前 report-only）。")


def print_baseline_check(records: list) -> None:
    print("")
    print("=" * 72)
    print("与 SPEC §4 云端基线对照")
    print("=" * 72)
    cur_sq_hits = sum(1 for r in records if r["kind"] == "sqlite3")
    cur_sq_files = len({r["path"] for r in records if r["kind"] == "sqlite3"})
    cur_pg_hits = sum(1 for r in records if r["kind"] in ("psycopg2", "pg8000"))
    cur_pg_files = len({r["path"] for r in records if r["kind"] in ("psycopg2", "pg8000")})
    rows = [
        (
            "sqlite3.connect",
            cur_sq_hits,
            cur_sq_files,
            SPEC_BASELINE["sqlite3"]["hits"],
            SPEC_BASELINE["sqlite3"]["files"],
        ),
        (
            "PG connect",
            cur_pg_hits,
            cur_pg_files,
            SPEC_BASELINE["pg"]["hits"],
            SPEC_BASELINE["pg"]["files"],
        ),
    ]
    for name, ch, cf, bh, bf in rows:
        dh, df = ch - bh, cf - bf
        mark = "=" if (dh == 0 and df == 0) else ("+" if dh > 0 else "-")
        print(
            "  %-16s 当前 %4d 处/%3d 文件  基线 %4d 处/%3d 文件  Δ %+d 处/%+d 文件  [%s]"
            % (name, ch, cf, bh, bf, dh, df, mark)
        )
    print("")
    print("注：PG 基线 14/11 含 39 dc_pg.py 民间封装口径；2026-10-30 云端复测为 12/10。")
    print("    偏差只提示趋势，收编进度以 C5 批次报告为准。")


# ── C10 白名单 ratchet ───────────────────────────────────────────────
def whitelist_counts(records: list) -> dict:
    """{(path, kind): count}，只统计存储层之外的命中。"""
    counts: dict = {}
    for r in records:
        if r["in_storage_layer"]:
            continue
        key = (r["path"], r["kind"])
        counts[key] = counts.get(key, 0) + 1
    return counts


def write_whitelist(records: list, path: Path) -> int:
    """把当前存量直连写入白名单（TSV：path<TAB>kind<TAB>count）。返回登记行数。"""
    counts = whitelist_counts(records)
    lines = [
        "# C10 直连门禁白名单（SPEC-L0 §6 C10：存量登记，新增直连会被 CI 拦截）",
        "# 格式: path<TAB>kind<TAB>max_count —— 存量只减不增；收编后请删除对应行",
    ]
    for (path_, kind), n in sorted(counts.items()):
        lines.append(f"{path_}\t{kind}\t{n}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(counts)


def load_whitelist(path: Path) -> dict:
    counts: dict = {}
    if not path.exists():
        return counts
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        counts[(parts[0], parts[1])] = int(parts[2])
    return counts


def ratchet_check(records: list, whitelist: dict) -> list:
    """比对当前扫描与白名单，返回违规列表（新文件 / 超登记数）。"""
    violations = []
    current = whitelist_counts(records)
    for (path_, kind), n in sorted(current.items()):
        allowed = whitelist.get((path_, kind))
        if allowed is None:
            violations.append(
                {
                    "type": "new_file",
                    "path": path_,
                    "kind": kind,
                    "count": n,
                    "allowed": 0,
                }
            )
        elif n > allowed:
            violations.append(
                {
                    "type": "count_exceeded",
                    "path": path_,
                    "kind": kind,
                    "count": n,
                    "allowed": allowed,
                }
            )
    return violations


def main() -> int:
    ap = argparse.ArgumentParser(description="C3 直连基线仪表（report-only）/ C10 门禁（ratchet）")
    ap.add_argument("--json", action="store_true", help="机器可读 JSON 输出")
    ap.add_argument("--baseline", action="store_true", help="附 SPEC 基线对照")
    ap.add_argument("--write-whitelist", action="store_true", help="把当前存量写入白名单")
    ap.add_argument("--ratchet", action="store_true", help="C10 门禁：白名单外新增直连 exit 1")
    ap.add_argument("--whitelist", default=str(DEFAULT_WHITELIST), help="白名单路径")
    args = ap.parse_args()

    records = scan_repo()

    if args.write_whitelist:
        n = write_whitelist(records, Path(args.whitelist))
        print("白名单已写入 %s（%d 行登记）" % (args.whitelist, n))
        return 0

    if args.ratchet:
        violations = ratchet_check(records, load_whitelist(Path(args.whitelist)))
        if args.json:
            print(
                json.dumps(
                    {
                        "report": "c10-direct-gate",
                        "mode": "ratchet",
                        "violations": violations,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            if violations:
                print("C10 门禁违规（白名单外新增直连，存量只减不增）:")
                for v in violations:
                    print(
                        "  [%s] %s [%s] 当前 %d 处 / 登记 %d 处"
                        % (v["type"], v["path"], v["kind"], v["count"], v["allowed"])
                    )
                print("")
                print(
                    "处置：新代码改走 Store port；确属存量登记请刷新白名单（--write-whitelist）。"
                )
            else:
                print("C10 门禁通过：白名单外无新增直连。")
        return 1 if violations else 0

    summary = summarize(records)
    if args.json:
        payload = {
            "report": "c3-db-direct-imports",
            "mode": "report-only",
            "storage_layer_dirs": list(STORAGE_LAYER_DIRS),
            "summary": summary,
            "records": records,
        }
        if args.baseline:
            payload["spec_baseline"] = SPEC_BASELINE
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_human(records, summary)
        if args.baseline:
            print_baseline_check(records)
    return 0  # report-only：恒 0，不阻断


if __name__ == "__main__":
    sys.exit(main())
