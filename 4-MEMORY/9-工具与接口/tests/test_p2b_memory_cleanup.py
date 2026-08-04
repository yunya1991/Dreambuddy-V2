#!/usr/bin/env python3
"""TDD RED: P2b 清理历史C级噪声记忆"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def _make_test_db(tmpdir: str) -> str:
    """构造有噪声的测试 SQLite 库（mirror memories 表）"""
    db_path = os.path.join(tmpdir, "test_mem.db")
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE memories (
            id TEXT PRIMARY KEY,
            content TEXT,
            vector BLOB,
            quality_level TEXT,
            confidence REAL,
            tags TEXT,
            memory_type TEXT,
            source TEXT,
            created_at TEXT,
            updated_at TEXT,
            verify_count INTEGER
        )
    """)
    # 插入高价值记忆（不应被清理）
    conn.execute("INSERT INTO memories VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                 ("VM-VALID-A", "MCP单例mock失效的解法", b"\x00"*16, "A", 0.85,
                  "[]", "experience", "认知闭环开发-2026-07-29",
                  "2026-07-29", "2026-07-30", 9))
    conn.execute("INSERT INTO memories VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                 ("VM-VALID-S", "公理级经验", b"\x00"*16, "S", 0.99,
                  "[]", "experience", "git-post-commit",
                  "2026-07-29", "2026-07-29", 20))
    conn.execute("INSERT INTO memories VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                 ("VM-VALID-B-DAEMON", "B级daemon记忆有验证", b"\x00"*16, "B", 0.7,
                  "[]", "experience", "cognitive-daemon",  # daemon来源但B级有验证
                  "2026-07-29", "2026-07-29", 3))
    # 插入 P1-1 前的 daemon 噪声（C级，0验证，低置信）
    for i in range(5):
        conn.execute("INSERT INTO memories VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (f"VM-NOISE-{i}", f"[开发活动] 修改 {i} 个文件", b"\x00"*16, "C", 0.1,
                      '["file-change","daemon"]', "experience", "cognitive-daemon",
                      "2026-07-30", "2026-07-30", 0))
    # 插入边界: daemon来源但verify_count>0（不应清理）
    conn.execute("INSERT INTO memories VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                 ("VM-NOISE-BUT-VERIFIED", "已验证的daemon记忆", b"\x00"*16, "C", 0.1,
                  "[]", "experience", "cognitive-daemon",
                  "2026-07-30", "2026-07-30", 1))
    # 边界: daemon来源但 confidence=0.3（>0.2阈值）
    conn.execute("INSERT INTO memories VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                 ("VM-NOISE-BUT-CONF-HIGH", "高置信daemon记忆", b"\x00"*16, "C", 0.3,
                  "[]", "experience", "cognitive-daemon",
                  "2026-07-30", "2026-07-30", 0))
    conn.commit()
    conn.close()
    return db_path


def _make_test_solution_paths(tmpdir: str) -> str:
    """构造测试 solution_paths 目录（含C级噪声+边界）"""
    sp_dir = os.path.join(tmpdir, "solution_paths")
    os.makedirs(sp_dir)

    # 噪声: C级 x3
    for i in range(3):
        p = os.path.join(sp_dir, f"APP-C-{i}.json")
        with open(p, "w") as f:
            json.dump({"template_id": f"APP-C-{i}", "quality_level": "C",
                       "confidence": 0.3, "verify_count": 0,
                       "content": f"Noise {i}"}, f)
    # 噪声: quarantined x1
    with open(os.path.join(sp_dir, "APP-Q-1.json"), "w") as f:
        json.dump({"template_id": "APP-Q-1", "quality_level": "quarantined"}, f)
    # 边界: B级（应保留）
    with open(os.path.join(sp_dir, "APP-B-good.json"), "w") as f:
        json.dump({"template_id": "APP-B-good", "quality_level": "B",
                   "verify_count": 5, "content": "Valid"}, f)
    return sp_dir


def test_sqlite_cleanup_strategy_no_false_positives():
    """P2b SQLite 清理：只清理 daemon+C+0verify+低置信，不误伤高价值"""
    from consolidation_engine import cleanup_legacy_c_noise  # 目标函数

    tmpdir = tempfile.mkdtemp()
    try:
        db = _make_test_db(tmpdir)
        # RED 阶段：函数尚未实现，应该会失败
        stats = cleanup_legacy_c_noise(
            sqlite_db_path=db,
            solution_paths_dir=None,
            dry_run=False,
            max_confidence=0.2,
        )
        assert stats["sqlite_noise_total"] == 5, f"应识别5条噪声: {stats}"
        assert stats["sqlite_archived"] == 5, f"应归档5条: {stats}"

        # 验证存活的记忆
        conn = sqlite3.connect(db)
        rows = conn.execute("SELECT id, quality_level FROM memories ORDER BY id").fetchall()
        id_to_q = {r[0]: r[1] for r in rows}
        # 高价值保留
        assert id_to_q.get("VM-VALID-A") == "A", "A级应保留"
        assert id_to_q.get("VM-VALID-S") == "S", "S级应保留"
        assert id_to_q.get("VM-VALID-B-DAEMON") == "B", "B级daemon应保留"
        # 边界保留
        assert id_to_q.get("VM-NOISE-BUT-VERIFIED") == "C", "有验证的C级daemon应保留"
        assert id_to_q.get("VM-NOISE-BUT-CONF-HIGH") == "C", "高置信C级daemon应保留"
        # 噪声被标记为 archived（不再被 min_quality=C 召回）
        for i in range(5):
            assert id_to_q.get(f"VM-NOISE-{i}") == "archived", \
                f"Noise {i} 应被标记为 archived, 实际={id_to_q.get(f'VM-NOISE-{i}')}"
        conn.close()
        print("✅ test_sqlite_cleanup_strategy_no_false_positives 通过")
        return True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_solution_paths_archive_only_noise():
    """P2b solution_paths 清理：只归档 C/quarantined 级，保留 B+ 级"""
    from consolidation_engine import cleanup_legacy_c_noise

    tmpdir = tempfile.mkdtemp()
    try:
        sp_dir = _make_test_solution_paths(tmpdir)
        stats = cleanup_legacy_c_noise(
            sqlite_db_path=None,
            solution_paths_dir=sp_dir,
            dry_run=False,
        )
        assert stats["sp_c_level_total"] == 4, f"应识别3+C+1Q=4条噪声: {stats}"
        assert stats["sp_archived"] == 4, f"应归档4条: {stats}"

        # 验证归档目录 + 存活目录
        archived_dir = os.path.join(sp_dir, "_archived")
        archived = sorted(os.listdir(archived_dir)) if os.path.exists(archived_dir) else []
        remaining = sorted([f for f in os.listdir(sp_dir)
                            if f.endswith(".json") and f != "_archived"])
        assert len(archived) == 4, f"归档目录应有4个: {archived}"
        assert "APP-B-good.json" in remaining, f"B级应保留: {remaining}"
        assert len(remaining) == 1, f"只剩1个B级: {remaining}"
        print("✅ test_solution_paths_archive_only_noise 通过")
        return True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_dry_run_is_really_noop():
    """P2b dry_run=True 不做任何修改（安全性）"""
    from consolidation_engine import cleanup_legacy_c_noise

    tmpdir = tempfile.mkdtemp()
    try:
        db = _make_test_db(tmpdir)
        sp_dir = _make_test_solution_paths(tmpdir)
        sp_before = set(os.listdir(sp_dir))

        stats = cleanup_legacy_c_noise(
            sqlite_db_path=db,
            solution_paths_dir=sp_dir,
            dry_run=True,
        )
        # dry_run 仍应报告统计，但不修改数据
        assert stats["dry_run"] is True
        assert stats["sqlite_noise_total"] == 5
        assert stats["sp_c_level_total"] == 4
        assert stats["sqlite_archived"] == 0, "dry_run 不应真正归档SQL"
        assert stats["sp_archived"] == 0, "dry_run 不应真正移动文件"

        # 验证 solution_paths 无变化
        sp_after = set(os.listdir(sp_dir))
        assert sp_before == sp_after, "dry_run 不应改动 solution_paths"

        # 验证 memories 表无修改
        conn = sqlite3.connect(db)
        c_count = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE quality_level='C' AND source='cognitive-daemon'"
        ).fetchone()[0]
        conn.close()
        assert c_count == 7, "dry_run SQLite 无变化（5+C级daemon噪声 +1已验证 +1高置信）"
        print("✅ test_dry_run_is_really_noop 通过")
        return True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    print("🔴 P2b RED 阶段（期望失败）")
    tests = [
        ("dry_run_noop", test_dry_run_is_really_noop),
        ("sqlite_cleanup", test_sqlite_cleanup_strategy_no_false_positives),
        ("sp_archive", test_solution_paths_archive_only_noise),
    ]
    passed, failed = 0, 0
    for name, fn in tests:
        print(f"\n▶ {name}")
        try:
            if fn():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            failed += 1
            print(f"   ❌ {type(e).__name__}: {e}")
    print(f"\n📊 {passed}/{len(tests)} 通过")
    sys.exit(0 if failed == 0 else 1)
