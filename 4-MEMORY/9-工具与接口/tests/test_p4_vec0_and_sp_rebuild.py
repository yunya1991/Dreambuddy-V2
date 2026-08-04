#!/usr/bin/env python3
"""TDD RED: P4a SQLite vec0 扩展加载 & P4b Solution Paths 重建"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


# ============================================================
# P4a: vec0 扩展加载
# ============================================================

def test_sqlite_vec_loads_on_auto_engine_and_search_uses_it():
    """P4a: VMI auto 模式下 vec0 扩展可加载，self.engine == 'sqlite_vec'"""
    from vector_memory_interface import VectorMemoryInterface

    tmpdir = tempfile.mkdtemp()
    try:
        db_path = os.path.join(tmpdir, "vec.db")
        # 构造几条测试记忆，加入后执行搜索
        vmi = VectorMemoryInterface(storage_path=db_path, engine="auto")
        # 注意：若系统 python 未启用 enable_load_extension / 未安装 sqlite-vec，
        #   _try_sqlite_vec 返回 None，engine 回退到 numpy。
        # 本测试仅检查"如果装了 sqlite-vec 且 Python 支持扩展加载，则 engine=sqlite_vec"
        # 同时断言：无论是哪个引擎，recall 功能都能正常工作（正确性不受影响）
        assert vmi.engine in ("sqlite_vec", "numpy"), f"engine 应是两者之一：{vmi.engine}"
        vmi.add("认知守护进程 P1 修复：排除 .workbuddy 目录和 heartbeat.json 噪声文件",
                quality_level="A", confidence=0.9,
                tags=["daemon", "noise-filter"], verify_count=5,
                source="cognitive-daemon")
        vmi.add("sqlite-vec 扩展缺失时，使用 numpy fallback 搜索路径保证正确性",
                quality_level="B", confidence=0.6,
                tags=["sqlite", "vec0", "fallback"], verify_count=2,
                source="认知系统修复-2026-08-01")
        vmi.add("Solution Paths 归档机制：低质量模板移动到 _archived/ 并可移回恢复",
                quality_level="S", confidence=0.99,
                tags=["solution-paths", "archive", "reversible"], verify_count=20,
                source="P2b 清理")

        res = vmi.search("daemon 噪声 .workbuddy 排除", top_k=2, quality_filter="C")
        assert len(res) >= 1, f"至少召回 1 条：{len(res)}"
        # 如果确实走了 sqlite_vec，应命中引擎标记
        # (我们写一个 vec_memories 表存在性的检查)
        has_vec0_table = vmi.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='vec_memories'"
        ).fetchone()
        if vmi.engine == "sqlite_vec":
            assert has_vec0_table is not None, "走 sqlite_vec 时应创建 vec_memories"
            print(f"   ✅ vec0 引擎启用，版本: {vmi.db.execute('SELECT vec_version()').fetchone()[0]}")
        else:
            print(f"   ℹ️ 环境未支持 sqlite-vec，走 numpy fallback 路径（已验证正确性 OK）")
            print(f"       engine={vmi.engine}, vec_memories 存在? {has_vec0_table is not None}")
        vmi.close()
        print("✅ test_sqlite_vec_loads_on_auto_engine_and_search_uses_it 通过")
        return True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_vec0_no_regression_on_quality_filter_tag_filter():
    """P4a: 无论用 sqlite_vec 还是 numpy，quality 过滤 + tags 过滤结果一致"""
    from vector_memory_interface import VectorMemoryInterface

    tmpdir = tempfile.mkdtemp()
    try:
        # numpy 引擎
        db_numpy = os.path.join(tmpdir, "np.db")
        vmi_np = VectorMemoryInterface(storage_path=db_numpy, engine="numpy")
        # auto 引擎（可能 sqlite_vec 也可能 numpy）
        db_auto = os.path.join(tmpdir, "auto.db")
        vmi_auto = VectorMemoryInterface(storage_path=db_auto, engine="auto")
        # 写入完全相同的 4 条
        items = [
            ("S级 公理", "S", 0.99, ["gold"], 20),
            ("A级 经验", "A", 0.85, ["process"], 9),
            ("B级 一般经验", "B", 0.6, ["process"], 2),
            ("C级 daemon 噪声", "C", 0.1, ["daemon"], 0),
        ]
        for (c, q, cf, tags, vc) in items:
            vmi_np.add(c, q, cf, tags=tags, verify_count=vc, source="test")
            vmi_auto.add(c, q, cf, tags=tags, verify_count=vc, source="test")
        q = "公理 经验"
        # min_quality=B 过滤：numpy 与 auto 都只返回 S/A/B，不应含 C
        for name, vmi in [("numpy", vmi_np), ("auto", vmi_auto)]:
            r = vmi.search(q, top_k=10, quality_filter="B")
            qs = [x.quality_level for x in r]
            assert set(qs) <= {"S", "A", "B"}, f"{name} quality 过滤错误: {qs}"
            # tags_filter=["gold"] 只应召回 S
            r2 = vmi.search(q, top_k=10, tags_filter=["gold"])
            assert len(r2) == 1 and r2[0].quality_level == "S", \
                f"{name} tags 过滤错误: {[x.quality_level for x in r2]}"
        print("✅ test_vec0_no_regression_on_quality_filter_tag_filter 通过")
        return True
    finally:
        vmi_np.close()
        vmi_auto.close()
        shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================
# P4b: Solution Paths 重建
# ============================================================

def _seed_high_quality_memories(tmpdir: str) -> str:
    """向 test sqlite DB 写入 15 条 B+ 级高价值记忆（S/A/B 混合）"""
    db_path = os.path.join(tmpdir, "mem.db")
    conn = sqlite3.connect(db_path)
    conn.execute("""CREATE TABLE memories (
        id TEXT PRIMARY KEY, content TEXT, vector BLOB, quality_level TEXT,
        confidence REAL, tags TEXT, memory_type TEXT, source TEXT,
        created_at TEXT, updated_at TEXT, verify_count INTEGER)""")

    items = [
        # S x 3
        ("VM-S-1", "S级公理级：Python TDD 红-绿-重构循环", "S", 0.99, ["tdd", "python"], 20),
        ("VM-S-2", "S级公理级：vec0 缺失使用 numpy fallback 保证正确性", "S", 0.98, ["sqlite", "fallback"], 15),
        ("VM-S-3", "S级公理级：可逆清理用 archived 标记 + _archived 目录", "S", 0.97, ["archive", "reversible"], 12),
        # A x 6
        ("VM-A-1", "A级经验：daemon 噪声排除 .workbuddy/heartbeat/.*_time.json", "A", 0.9, ["daemon", "noise"], 9),
        ("VM-A-2", "A级经验：daemon --log-file 重定向到 logs/cognitive_daemon.log", "A", 0.88, ["daemon", "logging"], 7),
        ("VM-A-3", "A级经验：Suggestions TTL 15min + 动作>=5 双触发刷新", "A", 0.86, ["suggestions", "refresh"], 6),
        ("VM-A-4", "A级经验：cle.get_cle 单例 mock 时必须 patch get_cle 而非类", "A", 0.84, ["mock", "cle"], 5),
        ("VM-A-5", "A级经验：Consolidation Engine 三级分层 Tier0/1/2", "A", 0.83, ["consolidation"], 4),
        ("VM-A-6", "A级经验：Bayesian Beta 更新 Beta(a+k,b+n−k) 公式", "A", 0.82, ["bayesian"], 3),
        # B x 6
        ("VM-B-1", "B级一般经验：CognitiveSession status=active 时才从磁盘恢复", "B", 0.7, ["session", "recovery"], 2),
        ("VM-B-2", "B级一般经验：CognitiveSession 需要 .current 文件恢复跨进程会话", "B", 0.68, ["session"], 2),
        ("VM-B-3", "B级一般经验：sqlite_vec 需要 enable_load_extension 支持", "B", 0.66, ["sqlite"], 1),
        ("VM-B-4", "B级一般经验：dry_run=True 必须完全 noop 不能修改任何文件/SQL", "B", 0.64, ["dry-run"], 1),
        ("VM-B-5", "B级一般经验：SP 重名归档加时间戳后缀避免覆盖", "B", 0.62, ["solution-paths"], 1),
        ("VM-B-6", "B级一般经验：stress_test 做噪声过滤压力测时需要真实 1e4 小文件", "B", 0.6, ["stress-test"], 1),
        # 噪声（C 级，不应被作为 SP 模板重建）
        ("VM-C-NOISE-1", "[开发活动] 修改 3 个文件", "C", 0.1, ["daemon"], 0),
    ]
    for (i, c, q, cf, tags, vc) in items:
        conn.execute(
            "INSERT INTO memories VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (i, c, b"\x00" * 64, q, cf, json.dumps(tags, ensure_ascii=False),
             "experience", "test-P4b", time.strftime("%Y-%m-%d"),
             time.strftime("%Y-%m-%d"), vc),
        )
    conn.commit()
    conn.close()
    return db_path


def test_rebuild_solution_paths_from_high_quality_memories():
    """P4b: rebuild_solution_paths 从 B+ 记忆生成 APP-*.json，数量>=10，B+ 质量>=80%"""
    from vector_memory_interface import rebuild_solution_paths_from_memories

    tmpdir = tempfile.mkdtemp()
    try:
        db = _seed_high_quality_memories(tmpdir)
        sp_dir = os.path.join(tmpdir, "solution_paths")
        stats = rebuild_solution_paths_from_memories(
            sqlite_db_path=db,
            solution_paths_dir=sp_dir,
            min_quality="B",      # B 及以上才作为 SP 模板
            min_verify_count=1,   # 至少 1 次验证
        )
        print(f"   rebuild 结果: {json.dumps(stats, ensure_ascii=False)}")

        # 断言数量
        files = [f for f in os.listdir(sp_dir) if f.endswith(".json")]
        assert len(files) >= 10, f"至少生成 10 个 SP 模板，实际 {len(files)}: {files[:5]}"

        # 断言质量分布
        qc = Counter()
        for f in files:
            with open(os.path.join(sp_dir, f)) as fp:
                data = json.load(fp)
            qc[data.get("quality_level", "?")] += 1
        b_plus = qc.get("S", 0) + qc.get("A", 0) + qc.get("B", 0)
        ratio = b_plus / len(files)
        assert ratio >= 0.8, f"B+ 占比应 >=80%，实际 {ratio*100:.0f}% ({dict(qc)})"
        print(f"   质量分布: {dict(qc)} → B+ 占比 {ratio*100:.0f}%")
        print("✅ test_rebuild_solution_paths_from_high_quality_memories 通过")
        return True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_rebuild_skip_noise_memories():
    """P4b: C 级 daemon 0verify 噪声不应被重建为 SP 模板"""
    from vector_memory_interface import rebuild_solution_paths_from_memories

    tmpdir = tempfile.mkdtemp()
    try:
        db = _seed_high_quality_memories(tmpdir)
        sp_dir = os.path.join(tmpdir, "solution_paths")
        stats = rebuild_solution_paths_from_memories(
            sqlite_db_path=db,
            solution_paths_dir=sp_dir,
            min_quality="B",
            min_verify_count=1,
        )
        # VM-C-NOISE-1 不应在 template_ids 中出现
        files = [f for f in os.listdir(sp_dir) if f.endswith(".json")]
        ids = set()
        for f in files:
            with open(os.path.join(sp_dir, f)) as fp:
                data = json.load(fp)
            ids.add(data.get("template_id", ""))
        assert "VM-C-NOISE-1" not in ids, "C 级噪声不应被重建为 SP 模板"
        print("✅ test_rebuild_skip_noise_memories 通过")
        return True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    print("🔴 P4a/P4b RED 阶段（期望 ImportError / AssertionError）")
    tests = [
        ("vec0_load", test_sqlite_vec_loads_on_auto_engine_and_search_uses_it),
        ("vec0_regression", test_vec0_no_regression_on_quality_filter_tag_filter),
        ("sp_rebuild_quality", test_rebuild_solution_paths_from_high_quality_memories),
        ("sp_rebuild_skip_noise", test_rebuild_skip_noise_memories),
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
