# -*- coding: utf-8 -*-
"""残差记忆器单测（SPEC §3.7′ / §4′）。

覆盖：
1. 分型保守性（未知 → D-policy；轨迹 → runtime；锚点 → code/config）
2. 写入裁决 S0 敏感 / S2 轨迹 / S4 非残差 / M1 锚点
3. 治理决策：D-policy 永久免疫、未分型冻结、runtime 才受时效约束
4. M1 指针解码：成功 / 缺失 / 越界
5. 存量回填：分类统计 + 幂等
6. TTL 候选：受保护子类不进入候选
"""

import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_COG_DIR = Path(__file__).resolve().parent.parent
if str(_COG_DIR) not in sys.path:
    sys.path.insert(0, str(_COG_DIR))

import memory_ttl_manager as ttl  # noqa: E402
from residual_memory import (  # noqa: E402
    backfill,
    classify,
    decode,
    ensure_residual_columns,
    gate,
    governance_decision,
    reclassify_invalid_anchors,
    score_blind_sample,
    verify_deletion_set,
)

# ============================================================
# 1. 分型
# ============================================================


def test_classify_defaults_to_policy():
    assert classify("今天天气不错") == "D-policy"


def test_classify_trajectory_is_runtime():
    assert classify("[RAG检索] 命中 3 条", source="rag-bridge") == "runtime"


def test_classify_anchor():
    assert classify("实现在 a.py:foo", source_anchor="a.py:foo") == "code"
    assert classify("端口在 config/app.yaml:port", source_anchor="config/app.yaml:port") == "config"


def test_classify_hints():
    assert classify("选型时弃用了 X，代价是回滚一次") == "D-tech"
    assert classify("用户裁定：这条红线不得突破") == "D-policy"


# ============================================================
# 2. 写入裁决
# ============================================================


def test_gate_rejects_sensitive():
    v = gate("api_key = sk-abcdefgh12345678", mode="enforce")
    assert v.accepted is False
    assert v.reason == "sensitive"
    assert v.enforced is True


def test_gate_trajectory_hard_zero_in_enforce_n3():
    v = gate("[RAG检索] 检索到 5 条", source="rag-bridge", mode="enforce_n3")
    assert v.accepted is False and v.reason == "trajectory" and v.enforced is True


def test_gate_shadow_never_enforces():
    v = gate("[RAG检索] 检索到 5 条", source="rag-bridge", mode="shadow")
    assert v.enforced is False


def test_gate_plain_text_is_non_residual():
    v = gate("今天天气不错", mode="enforce")
    assert v.accepted is False and v.reason == "non_residual"


def test_gate_anchor_becomes_m1():
    v = gate("入口在 4-MEMORY/x.py:foo", mode="enforce")
    assert v.accepted is True and v.form == "M1" and v.subclass == "code"


def test_gate_residual_becomes_m2():
    v = gate("试过了，这个方案不行，回滚耗时 2 小时", mode="enforce")
    assert v.accepted is True and v.form == "M2"


# ============================================================
# 3. 治理决策
# ============================================================


def _row(**kw):
    base = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "access_count": 0,
        "last_used_at": None,
        "verify_state": "fresh",
        "classify": "",
    }
    base.update(kw)
    return base


def test_governance_policy_never_touched():
    old = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
    for state in ("fresh", "stale", "degraded"):
        d = governance_decision(_row(subclass="D-policy", verify_state=state, created_at=old))
        assert d["action"] == "keep"


def test_governance_unclassified_frozen():
    d = governance_decision(_row(subclass=None))
    assert d == {"action": "keep", "reason": "unclassified_hold"}


def test_governance_runtime_ttl_candidate():
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    assert (
        governance_decision(_row(subclass="runtime", created_at=old))["action"] == "ttl_candidate"
    )


def test_governance_runtime_recently_used_kept():
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    d = governance_decision(_row(subclass="runtime", created_at=old, access_count=3))
    assert d["action"] == "keep"


def test_governance_code_never_ttl():
    old = (datetime.now(timezone.utc) - timedelta(days=999)).isoformat()
    row = _row(subclass="code", created_at=old, source_anchor="a.py:foo")
    assert governance_decision(row)["action"] == "keep"
    assert governance_decision({**row, "verify_state": "degraded"})["action"] == "degrade"


# ============================================================
# 4. 解码
# ============================================================


def test_decode_roundtrip(tmp_path):
    src = tmp_path / "pkg" / "mod.py"
    src.parent.mkdir()
    src.write_text("def foo():\n    return 1\n", encoding="utf-8")
    out = decode("pkg/mod.py:foo", repo_root=tmp_path)
    assert out["ok"] is True and "def foo" in out["snippet"]


def test_decode_missing_is_explicit(tmp_path):
    out = decode("pkg/none.py:foo", repo_root=tmp_path)
    assert out["ok"] is False and out["degraded_reason"] == "anchor_missing"


def test_decode_outside_repo_blocked(tmp_path):
    out = decode("../../etc/passwd", repo_root=tmp_path)
    assert out["ok"] is False and out["degraded_reason"] in {
        "anchor_outside_repo",
        "anchor_missing",
    }


# ============================================================
# 5. 回填
# ============================================================


def _mem_db(schema_suffix: str = "") -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute(
        "CREATE TABLE memories("
        "id TEXT PRIMARY KEY, content TEXT, source TEXT, tags TEXT, memory_type TEXT, "
        "quality_level TEXT, created_at TEXT, access_count INTEGER DEFAULT 0, "
        "last_used_at INTEGER" + schema_suffix + ")"
    )
    return con


def test_backfill_reports_missing_columns():
    con = _mem_db()
    report = backfill(con, dry_run=True)
    assert report["degraded_reason"] == "residual_columns_missing"
    out = ensure_residual_columns(con)
    assert set(out["added"]) == {"subclass", "form", "source_anchor", "verify_state"}
    assert ensure_residual_columns(con)["added"] == []


def test_reclassify_invalid_anchors(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    con = _mem_db(", subclass TEXT, form TEXT, source_anchor TEXT, verify_state TEXT")
    con.executemany(
        "INSERT INTO memories(id, content, source, tags, memory_type, subclass, form, "
        "source_anchor, verify_state) VALUES (?,?,?,?,?,?,?,?,?)",
        [
            (
                "ok",
                "实现在 pkg/mod.py:foo",
                "trae",
                "[]",
                "experience",
                "code",
                "M1",
                "pkg/mod.py:foo",
                "fresh",
            ),
            ("bad", "实现在 pool.js", "trae", "[]", "experience", "code", "M1", "pool.js", "fresh"),
        ],
    )
    report = reclassify_invalid_anchors(con, repo_root=tmp_path, dry_run=False)
    assert report["kept"] == 1 and report["reclassified"] == 1
    row = con.execute(
        "SELECT subclass, form, source_anchor FROM memories WHERE id='bad'"
    ).fetchone()
    assert row[0] in {"D-tech", "D-policy"} and row[1] == "M2" and row[2] == ""


def test_verify_deletion_set_passes_and_blocks_policy_delete(tmp_path):
    old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    cases = [
        {"id": "d1", "label": "delete", "subclass": "runtime", "created_at": old},
        {"id": "d2", "label": "delete", "subclass": "runtime", "created_at": old},
        {
            "id": "k1",
            "label": "keep",
            "subclass": "D-policy",
            "verify_state": "degraded",
            "created_at": old,
        },
        {
            "id": "k2",
            "label": "keep",
            "subclass": "code",
            "source_anchor": "a.py:f",
            "created_at": old,
        },
        {"id": "a1", "label": "ambiguous", "subclass": "D-tech", "created_at": old},
    ]
    path = tmp_path / "set.jsonl"
    path.write_text("\n".join(json.dumps(c) for c in cases), encoding="utf-8")
    report = verify_deletion_set(path)
    assert report["passed"] is True
    assert report["tp"] == 2 and report["fp"] == 0 and report["tn"] == 2

    bad = [dict(c) for c in cases]
    bad[2]["label"] = "delete"  # 把 D-policy 标成应删 → 必须失败
    path2 = tmp_path / "bad.jsonl"
    path2.write_text("\n".join(json.dumps(c) for c in bad), encoding="utf-8")
    assert verify_deletion_set(path2)["passed"] is False


def test_score_blind_sample_computes_kappa(tmp_path):
    import csv

    sheet = tmp_path / "sheet.csv"
    with sheet.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "sample", "human_subclass"])
        w.writerows(
            [
                ["1", 1, "code"],
                ["2", 1, "D-policy"],
                ["3", 1, "runtime"],
                ["4", 0, ""],
            ]
        )
    answers = tmp_path / "answers.jsonl"
    answers.write_text(
        "\n".join(
            json.dumps({"id": i, "subclass": s})
            for i, s in [("1", "code"), ("2", "D-policy"), ("3", "D-policy")]
        ),
        encoding="utf-8",
    )
    report = score_blind_sample(sheet, answers)
    assert report["scored"] == 3
    assert report["agreement"] == round(2 / 3, 4)
    assert report["passed"] is False


def test_backfill_classifies_and_is_idempotent():
    con = _mem_db(", subclass TEXT, form TEXT, source_anchor TEXT, verify_state TEXT")
    con.executemany(
        "INSERT INTO memories(id, content, source, tags, memory_type) VALUES (?,?,?,?,?)",
        [
            ("1", "实现在 a.py:foo", "trae", "[]", "experience"),
            ("2", "[RAG检索] 命中", "rag-bridge", "[]", "experience"),
            ("3", "今天天气不错", "trae", "[]", "experience"),
        ],
    )
    report = backfill(con, dry_run=False)
    assert report["updated"] == 3
    rows = {r["id"]: r for r in con.execute("SELECT * FROM memories")}
    assert rows["1"]["subclass"] == "code" and rows["1"]["form"] == "M1"
    assert rows["2"]["subclass"] == "runtime"
    assert rows["3"]["subclass"] == "D-policy"
    assert backfill(con, dry_run=False)["scanned"] == 0


# ============================================================
# 6. 索引巡检（P0 / G0）
# ============================================================


def test_inspect_index_detects_mixed_dim():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE memories(id TEXT PRIMARY KEY, vector BLOB)")
    con.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")
    con.execute("CREATE TABLE vec_memories(rowid INTEGER PRIMARY KEY)")
    con.execute("INSERT INTO meta VALUES ('embed_dim','512')")
    con.execute("INSERT INTO memories VALUES ('a', ?)", (b"\x00" * 2048,))
    con.execute("INSERT INTO memories VALUES ('b', ?)", (b"\x00" * 1024,))
    con.execute("INSERT INTO vec_memories VALUES (1)")
    con.execute("INSERT INTO vec_memories VALUES (2)")
    report = ttl.inspect_index(con)
    assert report["degraded"] is True
    assert report["mixed_dim"] == 1
    assert report["count_gap"] == 0


# ============================================================
# 7. TTL 候选范围
# ============================================================


def test_ttl_candidates_exclude_protected_subclasses():
    con = _mem_db(
        ", subclass TEXT, form TEXT, source_anchor TEXT, verify_state TEXT DEFAULT 'fresh'"
    )
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    con.executemany(
        "INSERT INTO memories(id, content, source, tags, memory_type, quality_level, "
        "created_at, subclass) VALUES (?,?,?,?,?,?,?,?)",
        [
            ("r", "runtime", "rag-bridge", "[]", "experience", "C", old, "runtime"),
            ("p", "policy", "trae", "[]", "experience", "C", old, "D-policy"),
            ("c", "code", "trae", "[]", "experience", "C", old, "code"),
            ("n1", "null轨迹", "rag-bridge", "[]", "experience", "C", old, None),
            ("n2", "null非轨迹", "trae", "[]", "experience", "C", old, None),
        ],
    )
    got = {
        r["id"] for r in ttl._iter_expired(con, ("rag-bridge", "trae"), datetime.now(timezone.utc))
    }
    assert got == {"r", "n1"}
