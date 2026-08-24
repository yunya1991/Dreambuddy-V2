"""
dreambuddy_dal.implementations.sqlite_unified.audit_summary
-------------------------------------------------------------
P2 门禁测量引擎：独立于 import_runner（防止既当裁判又当运动员）。

入口：
  compute_audit_summary(db_path, window_hours=72) → AuditSummary

G-1 通过标准：write_diff_rate < 0.001（< 0.1%）
G-3 通过标准：read_consistency_rate >= 0.9999（≥ 99.99%）

数据来源：ma_migration_audit 表
  - category='dual_write'   → 写审计（result=APPLIED/SKIPPED/FAILED）
  - category='shadow_read'  → 读审计（result=MATCH/DIFF）
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from dreambuddy_dal.connection import get_sqlite_connection


@dataclass
class AuditSummary:
    """G-1/G-3 门禁测量结果。"""
    # G-1：双写差异率
    write_total: int = 0
    write_fail: int = 0
    write_diff_rate: float = 0.0  # fail / total

    # G-3：影子读一致率
    shadow_read_total: int = 0
    shadow_read_match: int = 0
    shadow_read_diff: int = 0
    read_consistency_rate: float = 1.0  # match / total

    # 元数据
    window_hours: int = 72
    computed_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "write_total": self.write_total,
            "write_fail": self.write_fail,
            "write_diff_rate": self.write_diff_rate,
            "shadow_read_total": self.shadow_read_total,
            "shadow_read_match": self.shadow_read_match,
            "shadow_read_diff": self.shadow_read_diff,
            "read_consistency_rate": self.read_consistency_rate,
            "window_hours": self.window_hours,
            "computed_at": self.computed_at,
        }

    @property
    def g1_pass(self) -> bool:
        """G-1：双写差异率 < 0.001（< 0.1%）。"""
        return self.write_diff_rate < 0.001

    @property
    def g3_pass(self) -> bool:
        """G-3：影子读一致率 ≥ 99.99%。"""
        return self.read_consistency_rate >= 0.9999


def compute_audit_summary(db_path: str, window_hours: int = 72) -> AuditSummary:
    """从 ma_migration_audit 表统计 G-1/G-3 指标。"""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).isoformat()

    with get_sqlite_connection(db_path) as conn:
        # G-1: dual_write 审计
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN result='FAILED' THEN 1 ELSE 0 END) AS fail
            FROM ma_migration_audit
            WHERE category='dual_write' AND run_at >= ?
            """,
            (cutoff,),
        ).fetchone()
        write_total = int(row[0] or 0)
        write_fail = int(row[1] or 0)
        write_diff_rate = (write_fail / write_total) if write_total > 0 else 0.0

        # G-3: shadow_read 审计
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN result='MATCH' THEN 1 ELSE 0 END) AS match_cnt,
                SUM(CASE WHEN result='DIFF' THEN 1 ELSE 0 END) AS diff_cnt
            FROM ma_migration_audit
            WHERE category='shadow_read' AND run_at >= ?
            """,
            (cutoff,),
        ).fetchone()
        sr_total = int(row[0] or 0)
        sr_match = int(row[1] or 0)
        sr_diff = int(row[2] or 0)
        consistency = (sr_match / sr_total) if sr_total > 0 else 1.0

    return AuditSummary(
        write_total=write_total,
        write_fail=write_fail,
        write_diff_rate=write_diff_rate,
        shadow_read_total=sr_total,
        shadow_read_match=sr_match,
        shadow_read_diff=sr_diff,
        read_consistency_rate=consistency,
        window_hours=window_hours,
        computed_at=datetime.now(timezone.utc).isoformat(),
    )


__all__ = ["AuditSummary", "compute_audit_summary"]
