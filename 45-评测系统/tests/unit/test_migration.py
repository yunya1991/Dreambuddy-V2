# -*- coding: utf-8 -*-
"""
test_migration.py — P0-2 迁移结构测试
======================================
验收（PLAN P0-2）：
- 001_init.sql 建出 SPEC §12 定义的 8 张表
- eval_requests.idempotency_key 唯一键、各表外键与 CHECK 约束正确
- thresholds / registry_items 复合主键正确

集成测试：设置 EVAL_PG_DSN 环境变量后，会对真实 PG 执行迁移并回滚清理；
未设置时自动跳过（本机默认）。
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

MIGRATION = (
    Path(__file__).resolve().parent.parent.parent / "storage" / "migrations" / "001_init.sql"
)
SQL = MIGRATION.read_text(encoding="utf-8")

# SPEC §12 定义的 8 张表
EXPECTED_TABLES = [
    "eval_requests",
    "eval_runs",
    "eval_items",
    "evidence",
    "eval_reports",
    "thresholds",
    "callbacks",
    "registry_items",
]


def table_block(table: str) -> str:
    """提取某张表的 CREATE TABLE 语句体（括号内字段定义）。"""
    m = re.search(rf"CREATE TABLE IF NOT EXISTS {table}\s*\((.*?)\n\);", SQL, re.S)
    assert m, f"缺少建表语句: {table}"
    return m.group(1)


class TestTablePresence:
    def test_exactly_eight_tables(self):
        found = re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", SQL)
        assert len(found) == 8, f"建表数量应为 8，实际 {len(found)}: {found}"

    @pytest.mark.parametrize("table", EXPECTED_TABLES)
    def test_table_exists(self, table):
        assert re.search(rf"CREATE TABLE IF NOT EXISTS {table}\s*\(", SQL)


class TestEvalRequests:
    def test_idempotency_key_unique(self):
        block = table_block("eval_requests")
        line = next(ln for ln in block.splitlines() if "idempotency_key" in ln)
        assert "UNIQUE" in line.upper(), "idempotency_key 必须为 UNIQUE（受理幂等）"

    def test_eval_id_primary_key(self):
        block = table_block("eval_requests")
        line = next(ln for ln in block.splitlines() if "eval_id" in ln)
        assert "PRIMARY KEY" in line.upper()

    def test_category_check(self):
        block = table_block("eval_requests")
        assert re.search(r"category IN \('finance',\s*'ai',\s*'engineering'\)", block)

    def test_env_manifest_jsonb(self):
        block = table_block("eval_requests")
        assert re.search(r"env_manifest\s+JSONB NOT NULL", block)

    def test_status_check_allows_cancel_states(self):
        """§13.2：仅 queued/running 可取消，状态枚举必须包含二者。"""
        block = table_block("eval_requests")
        assert "'queued'" in block and "'running'" in block


class TestForeignKeys:
    def test_runs_references_requests(self):
        block = table_block("eval_runs")
        assert re.search(r"REFERENCES eval_requests \(eval_id\)", block)

    def test_items_references_runs(self):
        block = table_block("eval_items")
        assert re.search(r"REFERENCES eval_runs \(run_id\)", block)

    def test_items_references_evidence(self):
        block = table_block("eval_items")
        assert re.search(r"evidence_id\s+TEXT REFERENCES evidence \(evidence_id\)", block)

    def test_evidence_references_runs(self):
        block = table_block("evidence")
        assert re.search(r"REFERENCES eval_runs \(run_id\)", block)

    def test_reports_references_requests_and_runs(self):
        block = table_block("eval_reports")
        assert re.search(r"REFERENCES eval_requests \(eval_id\)", block)
        assert re.search(r"REFERENCES eval_runs \(run_id\)", block)

    def test_callbacks_references_requests(self):
        block = table_block("callbacks")
        assert re.search(r"REFERENCES eval_requests \(eval_id\)", block)


class TestConstraints:
    def test_verdict_check(self):
        block = table_block("eval_reports")
        assert re.search(r"verdict IN \('PASS',\s*'BLOCK',\s*'INCONCLUSIVE'\)", block)

    def test_item_kind_check(self):
        block = table_block("eval_items")
        assert re.search(r"kind IN \('hard',\s*'weighted'\)", block)

    def test_evidence_hash_chain_columns(self):
        """证据链：prev_hash + hash，且 hash 唯一（§2.1 可离线验证）。"""
        block = table_block("evidence")
        assert "prev_hash" in block
        line = next(ln for ln in block.splitlines() if re.match(r"\s*hash\s", ln))
        assert "UNIQUE" in line.upper()

    def test_thresholds_composite_pk(self):
        block = table_block("thresholds")
        assert re.search(
            r"PRIMARY KEY \(version,\s*category,\s*item\)", block, re.S
        ), "thresholds 需 (version, category, item) 复合主键"

    def test_registry_items_composite_pk(self):
        block = table_block("registry_items")
        assert re.search(r"PRIMARY KEY \(reg_type,\s*item_id,\s*version\)", block, re.S)

    def test_thresholds_required_columns(self):
        """§3.3 Threshold Registry 必填字段：value/metric/min_n/effective_from/approved_by。"""
        block = table_block("thresholds")
        for col in ("value", "metric", "min_n", "effective_from", "approved_by"):
            assert re.search(rf"\b{col}\b", block), f"thresholds 缺字段 {col}"

    def test_block_reasons_jsonb_default(self):
        block = table_block("eval_reports")
        assert re.search(r"block_reasons\s+JSONB NOT NULL DEFAULT '\[\]'::jsonb", block)

    def test_table_creation_order_respects_fk(self):
        """父表必须先于子表创建（认知经验：FK 指向未建表会整批失败）。"""
        pos = {t: SQL.index(f"CREATE TABLE IF NOT EXISTS {t}") for t in EXPECTED_TABLES}
        assert pos["eval_requests"] < pos["eval_runs"]
        assert pos["eval_runs"] < pos["evidence"] < pos["eval_items"]
        assert pos["eval_runs"] < pos["eval_reports"]
        assert pos["eval_requests"] < pos["callbacks"]


# ---------------- PG 集成测试（可选） ----------------


def _clean_dsn(dsn: str) -> str:
    """去除 Prisma 专有查询参数（认知经验 VM-1791981667092：psycopg 遇 ?schema= 报 invalid dsn）。"""
    return re.sub(
        r"[?&]schema=[^&]*", lambda m: "?" if m.group(0).startswith("?") else "", dsn
    ).rstrip("?")


def _split_statements(sql: str) -> list[str]:
    """按分号切分语句，剔除纯注释行（迁移 SQL 无函数体，切分安全）。"""
    no_comments = "\n".join(ln for ln in sql.splitlines() if not ln.strip().startswith("--"))
    return [s.strip() for s in no_comments.split(";") if s.strip()]


@pytest.mark.skipif(
    not os.environ.get("EVAL_PG_DSN"), reason="EVAL_PG_DSN 未设置，跳过 PG 集成测试"
)
class TestMigrationOnRealPG:
    """对真实 PG 执行迁移并校验，结束后 DROP 清理，不留痕迹。"""

    TABLES_DDL_ORDER = [
        "callbacks",
        "eval_reports",
        "eval_items",
        "evidence",
        "eval_runs",
        "thresholds",
        "registry_items",
        "eval_requests",
    ]

    def test_apply_and_verify(self):
        psycopg = pytest.importorskip("psycopg")
        dsn = _clean_dsn(os.environ["EVAL_PG_DSN"])
        with psycopg.connect(dsn, autocommit=True) as conn:
            try:
                for stmt in _split_statements(SQL):
                    conn.execute(stmt)
                rows = conn.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                ).fetchall()
                names = {r[0] for r in rows}
                assert set(EXPECTED_TABLES) <= names

                # 唯一键：eval_requests.idempotency_key
                idx = conn.execute(
                    "SELECT indexdef FROM pg_indexes WHERE tablename = 'eval_requests'"
                ).fetchall()
                assert any("idempotency_key" in r[0] and "UNIQUE" in r[0].upper() for r in idx)

                # 外键数量：runs1 + evidence1 + items2 + reports2 + callbacks1 = 7
                fks = conn.execute(
                    "SELECT COUNT(*) FROM information_schema.table_constraints "
                    "WHERE constraint_type = 'FOREIGN KEY' AND table_schema = 'public' "
                    "AND table_name = ANY(%s)",
                    (["eval_runs", "eval_items", "evidence", "eval_reports", "callbacks"],),
                ).fetchone()
                assert fks[0] == 7
            finally:
                conn.execute(
                    "DROP TABLE IF EXISTS " + ", ".join(self.TABLES_DDL_ORDER) + " CASCADE"
                )
