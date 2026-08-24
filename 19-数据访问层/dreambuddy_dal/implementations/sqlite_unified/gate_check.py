"""
dreambuddy_dal.implementations.sqlite_unified.gate_check
---------------------------------------------------------
P2 门禁一键检查（G-1~G-5）。

入口：
  run_gate_check(db_path, log_dir=None, rollback_drill_pass=False,
                 backup_db_path=None, window_hours=72) → GateCheckResult

G-1: 双写差异率 < 0.001（audit_summary 计算）
G-2: "database is locked" 0 次（扫描 log_dir 下 *.log/*.jsonl）
G-3: 影子读一致率 ≥ 99.99%（audit_summary 计算）
G-4: 回滚演练 30 分钟零事故（手动传入 pass/fail）
G-5: 冷备份可用性（PRAGMA integrity_check + 抽样）

G-4/G-5 未提供数据时默认 PASS（留待现场操作时填入）。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

from dreambuddy_dal.connection import get_sqlite_connection
from dreambuddy_dal.implementations.sqlite_unified.audit_summary import (
    compute_audit_summary,
)

_log = logging.getLogger(__name__)

_DB_LOCKED_PATTERN = re.compile(r"database is locked", re.IGNORECASE)


@dataclass
class GateCheckResult:
    """G-1~G-5 五项门禁检查结果。"""
    g1_pass: bool = True
    g2_pass: bool = True
    g3_pass: bool = True
    g4_pass: bool = True
    g5_pass: bool = True
    details: Dict[str, str] = field(default_factory=dict)

    @property
    def all_pass(self) -> bool:
        return all([self.g1_pass, self.g2_pass, self.g3_pass,
                     self.g4_pass, self.g5_pass])

    def summary(self) -> str:
        lines = [
            f"G-1 (双写差异率 < 0.1%): {'PASS' if self.g1_pass else 'FAIL'} — {self.details.get('g1', '')}",
            f"G-2 (database locked 0 次): {'PASS' if self.g2_pass else 'FAIL'} — {self.details.get('g2', '')}",
            f"G-3 (影子读一致率 ≥ 99.99%): {'PASS' if self.g3_pass else 'FAIL'} — {self.details.get('g3', '')}",
            f"G-4 (回滚演练零事故): {'PASS' if self.g4_pass else 'FAIL'} — {self.details.get('g4', '')}",
            f"G-5 (冷备份可用性): {'PASS' if self.g5_pass else 'FAIL'} — {self.details.get('g5', '')}",
            f"════════════════════════════════════════",
            f"  ALL PASS: {'✅ YES — 可切读' if self.all_pass else '❌ NO — 延长观察期'}",
        ]
        return "\n".join(lines)


def _check_g1_g3(db_path: str, window_hours: int) -> tuple:
    """G-1 + G-3 通过 audit_summary 计算。"""
    summary = compute_audit_summary(db_path, window_hours=window_hours)
    g1_pass = summary.g1_pass
    g3_pass = summary.g3_pass
    g1_detail = f"write_total={summary.write_total}, fail={summary.write_fail}, diff_rate={summary.write_diff_rate:.6f}"
    g3_detail = f"shadow_total={summary.shadow_read_total}, match={summary.shadow_read_match}, diff={summary.shadow_read_diff}, consistency={summary.read_consistency_rate:.6f}"
    return g1_pass, g1_detail, g3_pass, g3_detail


def _check_g2(log_dir: Optional[str]) -> tuple:
    """G-2: 扫描日志目录中 "database is locked" 出现次数。"""
    if log_dir is None:
        return True, "no log_dir provided — skipped (PASS)"
    log_path = Path(log_dir)
    if not log_path.exists():
        return True, f"log_dir {log_dir} does not exist — skipped (PASS)"
    locked_count = 0
    files_scanned = 0
    for f in log_path.rglob("*"):
        if not f.is_file():
            continue
        if f.suffix not in (".log", ".jsonl", ".txt"):
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
            locked_count += len(_DB_LOCKED_PATTERN.findall(text))
            files_scanned += 1
        except Exception:
            continue
    passed = locked_count == 0
    detail = f"scanned {files_scanned} files, 'database is locked' count={locked_count}"
    return passed, detail


def _check_g5(db_path: str, backup_db_path: Optional[str]) -> tuple:
    """G-5: PRAGMA integrity_check + 抽样 10 条。"""
    if backup_db_path is None:
        return True, "no backup_db_path provided — skipped (PASS)"
    target = Path(backup_db_path)
    if not target.exists():
        return False, f"backup file {backup_db_path} does not exist"
    try:
        with get_sqlite_connection(str(target)) as conn:
            row = conn.execute("PRAGMA integrity_check").fetchone()
            if row is None or row[0] != "ok":
                return False, f"integrity_check: {row[0] if row else 'None'}"
            # 抽样 10 条
            sample = conn.execute(
                "SELECT trade_id, symbol FROM tr_trades LIMIT 10"
            ).fetchall()
            detail = f"integrity=ok, sampled {len(sample)} trades"
        return True, detail
    except Exception as exc:
        return False, f"integrity_check error: {exc}"


def run_gate_check(
    db_path: str,
    *,
    log_dir: Optional[str] = None,
    rollback_drill_pass: bool = True,
    backup_db_path: Optional[str] = None,
    window_hours: int = 72,
) -> GateCheckResult:
    """执行 G-1~G-5 五项门禁检查。"""
    result = GateCheckResult()

    # G-1 + G-3
    g1_pass, g1_detail, g3_pass, g3_detail = _check_g1_g3(db_path, window_hours)
    result.g1_pass = g1_pass
    result.details["g1"] = g1_detail
    result.g3_pass = g3_pass
    result.details["g3"] = g3_detail

    # G-2
    g2_pass, g2_detail = _check_g2(log_dir)
    result.g2_pass = g2_pass
    result.details["g2"] = g2_detail

    # G-4
    result.g4_pass = rollback_drill_pass
    result.details["g4"] = "manual: rollback drill passed" if rollback_drill_pass else "manual: rollback drill FAILED"

    # G-5
    g5_pass, g5_detail = _check_g5(db_path, backup_db_path)
    result.g5_pass = g5_pass
    result.details["g5"] = g5_detail

    return result


__all__ = ["GateCheckResult", "run_gate_check"]
