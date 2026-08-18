#!/usr/bin/env python3
"""
认知系统健康体检工具

用法:
    python3 cognitive_health_check.py

检查范围:
    1. L1 向量记忆库 (cognitive_memory.db) — 总量/质量分布/信噪比/vec0保护
    2. Solution Paths (应用记忆层) — 活跃/归档/质量分布/B+占比
    3. 会话状态 — 历史会话/活跃会话/suggestions/P3刷新
    4. 召回/闭环验证 — 实际 search 3 个典型 query
    5. 错误日志扫描 — ERROR/WARNING/vec0 计数
    6. TDD 测试套件 — 文件清单与项数

注意:
    session.json 持久化时只写 action_count 计数，不写 action_chain 数组
    （完整行动链另存 action_chain.jsonl，跨进程 reload 时读回）。
    因此统计行动链长度应读 action_count 字段，切勿读 action_chain 数组。
"""

import os
import sys
import sqlite3
import json
import time
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).parent))
ROOT = Path(__file__).resolve().parent.parent.parent  # 项目根


def _tag(v, ok="OK", low="LOW", bad="BAD"):
    """三档状态标签"""
    if v is True:
        return ok
    if v is False:
        return bad
    return low


def _action_count_of(session_dir: Path, meta: dict) -> int:
    """
    正确获取会话行动链长度。
    优先读 session.json 的 action_count 字段；
    若缺失则回退统计 action_chain.jsonl 行数。
    """
    n = int(meta.get("action_count", 0) or 0)
    if n:
        return n
    chain_file = session_dir / "action_chain.jsonl"
    if chain_file.exists():
        try:
            with open(chain_file, "r") as f:
                return sum(1 for _ in f)
        except OSError:
            return 0
    return 0


def check_l1_memory():
    """1/6 L1 向量记忆库"""
    print()
    print("1/6  L1 向量记忆库 (cognitive_memory.db)")
    db_path = ROOT / "4-MEMORY/data/cognitive_memory.db"
    if not db_path.exists():
        print("   [BAD] 数据库文件不存在: {}".format(db_path))
        return
    conn = sqlite3.connect(str(db_path))
    total = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    q_rows = conn.execute(
        "SELECT quality_level, COUNT(*), AVG(confidence), AVG(verify_count) "
        "FROM memories GROUP BY quality_level ORDER BY quality_level"
    ).fetchall()
    print("   总记忆数          : {} 条".format(total))
    valid_total = 0
    for q, c, avg_conf, avg_vc in q_rows:
        if q in ("S", "A", "B"):
            flg = "  OK"
        elif q == "C":
            flg = "  LOW"
        elif q == "archived":
            flg = "  ARC"
        else:
            flg = ""
        print("   {q:10s} x {c:>4}  avg_conf={cf:.2f}  avg_vc={vc:.1f}{flg}".format(
            q=str(q), c=c, cf=float(avg_conf or 0), vc=float(avg_vc or 0), flg=flg))
        if q in ("S", "A", "B", "C"):
            valid_total += c
    archived_list = [c for q, c, _, _ in q_rows if q == "archived"]
    archived = archived_list[0] if archived_list else 0
    snr = valid_total * 100 // max(1, total)
    tag = _tag(snr >= 30, ok="OK", low="LOW", bad="BAD") if snr < 15 else "OK" if snr >= 30 else "LOW"
    print("   有效(S/A/B/C)      : {} 条".format(valid_total))
    print("   已归档(archived)   : {} 条 (P2b 清理结果)".format(archived))
    print("   信噪比             : {}/{} = {}%  [{}]".format(valid_total, total, snr, tag))
    has_vm = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='vec_memories'"
    ).fetchone() is not None
    print("   vec_memories遗留   : {}".format("是 (已做保护不访问)" if has_vm else "否 正常"))
    conn.close()


def check_solution_paths():
    """2/6 Solution Paths"""
    print()
    print("2/6  Solution Paths (应用记忆层)")
    sp_dir = ROOT / "4-MEMORY/1-开发记忆单元/solution_paths"
    active_files = sorted([f for f in os.listdir(sp_dir) if f.endswith(".json")]) if sp_dir.exists() else []
    arch_dir = sp_dir / "_archived"
    archived_count = len([f for f in os.listdir(arch_dir) if f.endswith(".json")]) if arch_dir.exists() else 0
    qc = Counter()
    rebuilt_ids = 0
    for f in active_files:
        try:
            d = json.load(open(sp_dir / f))
            qc[d.get("quality_level", "?")] += 1
            if d.get("rebuild_version"):
                rebuilt_ids += 1
        except Exception:
            pass
    b_plus = sum(qc.get(q, 0) for q in ("S", "A", "B"))
    bpr = b_plus * 100 // max(1, len(active_files)) if active_files else 0
    bp_tag = "OK" if bpr >= 80 else "LOW" if bpr >= 50 else "BAD"
    print("   活跃 APP-*.json    : {} 个".format(len(active_files)))
    print("   _archived/归档     : {} 个".format(archived_count))
    print("   原始总数           : {} 个".format(len(active_files) + archived_count))
    print("   质量分布           : {}".format(dict(qc)))
    if active_files:
        print("   B+级占比           : {}/{} = {}%  [{}]".format(b_plus, len(active_files), bpr, bp_tag))
        print("   含rebuild_version  : {} 个 (P4b重建产物)".format(rebuilt_ids))


def check_sessions():
    """3/6 会话状态"""
    print()
    print("3/6  会话状态")
    sess_dir = ROOT / ".cognitive/sessions"
    subdirs = sorted([d for d in os.listdir(sess_dir) if os.path.isdir(sess_dir / d)]) if sess_dir.exists() else []
    sessions = [d for d in subdirs if (sess_dir / d / "session.json").exists()]
    total_sessions = len(sessions)
    with_sug = 0
    with_refresh = 0
    active_sess = None
    active_entry = {}
    latest_list = []
    for d in sessions:
        sj = sess_dir / d / "session.json"
        try:
            sdata = json.load(open(sj))
        except Exception:
            continue
        sug = (sess_dir / d / "suggestions.md").exists()
        if sug:
            with_sug += 1
        meta = sess_dir / d / "suggestions_meta.json"
        rcount = 0
        if meta.exists():
            with_refresh += 1
            try:
                rcount = json.load(open(meta)).get("refresh_count", 0)
            except Exception:
                pass
        actions = _action_count_of(sess_dir / d, sdata)
        entry = {
            "id": d, "task": sdata.get("task_type", "?"),
            "actions": actions, "status": sdata.get("status", "?"),
            "rcount": rcount, "has_sug": sug,
        }
        latest_list.append(entry)
        if sdata.get("status") == "active":
            active_sess = d
            active_entry = entry

    latest_list.sort(key=lambda x: -x["actions"])
    print("   历史会话总数       : {} 个".format(total_sessions))
    print("   生成过suggestions  : {}/{}".format(with_sug, total_sessions))
    print("   触发过refresh(P3)  : {}/{}".format(with_refresh, total_sessions))
    if active_sess:
        e = active_entry
        print("   当前活跃会话       : {}".format(e["id"]))
        print("     任务类型         : {}".format(e["task"]))
        print("     行动链长度       : {} 条".format(e["actions"]))
        print("     suggestions.md   : {}".format("已生成 OK" if e["has_sug"] else "未生成"))
        rtag = "OK" if e["rcount"] > 0 else "(零动作可能)"
        print("     P3刷新次数       : {} 次 {}".format(e["rcount"], rtag))
    else:
        print("   (当前无活跃会话)")
    print("   Top-5 最长会话:")
    for e in latest_list[:5]:
        tag = " refresh {}次".format(e["rcount"]) if e["rcount"] else ""
        print("     {}  task={:15s}  actions={:>5}  status={:10s}{}".format(
            e["id"], e["task"], e["actions"], e["status"], tag))


def check_recall():
    """4/6 召回/闭环验证"""
    print()
    print("4/6  召回/闭环验证 (实际search 3个典型query)")
    try:
        from vector_memory_interface import VectorMemoryInterface
        vmi = VectorMemoryInterface(
            storage_path=str(ROOT / "4-MEMORY/data/cognitive_memory.db"), engine="auto"
        )
        print("   引擎选择           : {}".format(vmi.engine))
        queries = [
            ("认知daemon噪声排除 .workbuddy heartbeat", "记忆-认知"),
            ("交易系统 风控 马丁策略", "交易"),
            ("文档 doc_lint 覆盖度", "文档系统"),
        ]
        for q, domain in queries:
            t0 = time.time()
            try:
                r = vmi.search(q, top_k=3, quality_filter="C")
                dt = (time.time() - t0) * 1000
                top_q = r[0].quality_level if r else "-"
                n = len(r)
                tag = "OK" if n >= 1 else "MISS"
                print("   [{:6s}] {:2d}条 top={} {:4.0f}ms  [{}]".format(domain, n, top_q, dt, tag))
            except Exception as e:
                print("   [{:6s}] ERROR: {}: {}".format(domain, type(e).__name__, e))
        vmi.close()
    except Exception as e:
        print("   VMI初始化异常: {}: {}".format(type(e).__name__, e))


def check_log_errors():
    """5/6 错误日志扫描"""
    print()
    print("5/6  错误日志扫描")
    log_path = ROOT / "logs/cognitive_daemon.log"
    err_count = 0
    warn_count = 0
    vec0_count = 0
    total_lines = 0
    if log_path.exists():
        with open(log_path, errors="ignore") as f:
            for line in f:
                total_lines += 1
                low = line.lower()
                if any(k in low for k in ["error", "exception", "traceback", "operationalerror", "nameerror"]):
                    err_count += 1
                    if "vec0" in low:
                        vec0_count += 1
                if any(k in low for k in ["warning", "warn"]):
                    warn_count += 1
    err_tag = "OK" if err_count == 0 else "LOW" if err_count <= 5 else "BAD"
    warn_tag = "OK" if warn_count == 0 else "LOW" if warn_count <= 20 else "BAD"
    print("   log总行数          : {}".format(total_lines))
    extra = "  (其中vec0 x {})".format(vec0_count) if vec0_count else ""
    print("   ERROR级条目        : {}  [{}]{}".format(err_count, err_tag, extra))
    print("   WARNING级条目      : {}  [{}]".format(warn_count, warn_tag))


def check_test_suite():
    """6/6 TDD测试套件"""
    print()
    print("6/6  TDD测试套件")
    tests = [
        ("test_cognitive_daemon.py", 9, "daemon噪声排除+日志重定向+防抖+触发"),
        ("tests/test_p2b_memory_cleanup.py", 3, "SQLite归档+SP归档+dry_run安全"),
        ("tests/test_p3_suggestions_refresh.py", 5, "TTL+动作阈值+刷新标记+NOOP安全"),
        ("tests/test_p4_vec0_and_sp_rebuild.py", 4, "vec0三层保护+SP重建质量过滤"),
    ]
    for name, count, desc in tests:
        p = Path(__file__).parent / name
        exists = p.exists()
        print("   {st}  {name:40s} {c}项  {d}".format(
            st="OK" if exists else "--", name=name, c=count, d=desc))
    print("   (手动执行: cd 4-MEMORY/9-工具与接口 && python3 test_cognitive_daemon.py ...)")


def main():
    print("=" * 70)
    print("  认知系统健康体检报告  {}".format(time.strftime("%Y-%m-%d %H:%M:%S")))
    print("=" * 70)
    check_l1_memory()
    check_solution_paths()
    check_sessions()
    check_recall()
    check_log_errors()
    check_test_suite()
    print()
    print("=" * 70)
    print("  体检完成")
    print("=" * 70)


if __name__ == "__main__":
    main()
