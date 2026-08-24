"""sqlite 落库 — 对齐 TECHNICAL_DESIGN.md §6。

默认落库表 records，schema 对齐 DataRecord；dedupe_key 唯一 + INSERT OR IGNORE 去重。
"""
from __future__ import annotations

import json
import sqlite3

from data_center.core.contract import DataRecord
from data_center.storage.cache import dedupe_key

_SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dedupe_key TEXT UNIQUE,
    source TEXT, category TEXT, sub_category TEXT, timestamp TEXT,
    metrics TEXT, events TEXT, timeseries TEXT, raw TEXT, schema_version TEXT
)
"""

# 列清单与占位符程序化生成，避免手数列数/占位符不匹配
_COLUMNS = [
    "dedupe_key", "source", "category", "sub_category", "timestamp",
    "metrics", "events", "timeseries", "raw", "schema_version",
]
_INSERT_SQL = (
    f"INSERT OR IGNORE INTO records ({', '.join(_COLUMNS)}) "
    f"VALUES ({', '.join(['?'] * len(_COLUMNS))})"
)


class SqliteSink:
    def __init__(self, db_path: str):
        self.db_path = db_path
        conn = sqlite3.connect(db_path)
        conn.execute(_SCHEMA)
        conn.commit()
        conn.close()

    def write(self, records: list[DataRecord]) -> int:
        """落库，返回实际新增行数（同 dedupe_key 被忽略）。"""
        conn = sqlite3.connect(self.db_path)
        inserted = 0
        for r in records:
            cur = conn.execute(
                _INSERT_SQL,
                (
                    dedupe_key(r), r.source, r.category, r.sub_category, r.timestamp,
                    json.dumps(r.metrics, ensure_ascii=False),
                    json.dumps(r.events, ensure_ascii=False),
                    json.dumps(r.timeseries, ensure_ascii=False),
                    json.dumps(r.raw, ensure_ascii=False),
                    r.schema_version,
                ),
            )
            inserted += cur.rowcount
        conn.commit()
        conn.close()
        return inserted

    def read_all(self) -> list[DataRecord]:
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT source, category, sub_category, timestamp, "
            "metrics, events, timeseries, raw, schema_version FROM records"
        ).fetchall()
        conn.close()
        return [
            DataRecord(
                source=r[0], category=r[1], sub_category=r[2], timestamp=r[3],
                metrics=json.loads(r[4]), events=json.loads(r[5]),
                timeseries=json.loads(r[6]), raw=json.loads(r[7]),
                schema_version=r[8],
            )
            for r in rows
        ]
