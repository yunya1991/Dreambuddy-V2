#!/usr/bin/env python3
"""DualWrite 沙箱测试脚本 — 验证 DualWrite 启用 + 审计表写入。

安全设计：
  - DB_BACKEND=dual_write 显式指定，不影响全局环境
  - READ_SOURCE=shadow 只做读比对，不替换 legacy
  - 使用临时数据库路径，不污染生产数据
  - Kill-Switch 文件兜底（创建即回退）

验证步骤：
  1. 设置环境变量
  2. 写入一条 metric（触发 legacy + new 双写）
  3. 设置 READ_SOURCE=shadow 读一条 metric（触发审计写入）
  4. 查询 ma_migration_audit 表
"""
import os
import sys
import tempfile
import sqlite3
from datetime import datetime

# 设置环境变量（沙箱模式）
_tmp_dir = tempfile.mkdtemp(prefix="dal_dualwrite_test_")
os.environ["DB_BACKEND"] = "dual_write"
os.environ["DATA_DIR"] = _tmp_dir
os.environ["READ_SOURCE"] = ""  # 写阶段不走 shadow

# 添加 19-DAL 到 sys.path
_DAL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)
sys.path.insert(0, _DAL_DIR)
sys.path.insert(0, os.path.dirname(_DAL_DIR))

print(f"沙箱临时目录: {_tmp_dir}")
print(f"DB_BACKEND={os.environ['DB_BACKEND']}")
print(f"DATA_DIR={os.environ['DATA_DIR']}")
print()

# ============================================================
# Step 1: 获取 DualWrite repo
# ============================================================
print("=" * 60)
print("Step 1: 获取 DualWrite MarketMacro repo")
print("=" * 60)
try:
    from dreambuddy_dal.di import get_market_macro_repo, _resolve_backend
    backend = _resolve_backend(None)
    print(f"  解析 backend: {backend}")
    assert backend == "dual_write", f"backend 应为 dual_write, 实际 {backend}"
    repo = get_market_macro_repo()
    print(f"  repo 类型: {type(repo).__name__}")
    print(f"  ✓ DualWrite repo 获取成功")
except Exception as e:
    print(f"  ✗ 失败: {e}")
    import traceback; traceback.print_exc()
    sys.exit(1)

# ============================================================
# Step 2: 写入一条 metric（触发 legacy + new 双写）
# ============================================================
print()
print("=" * 60)
print("Step 2: 写入 metric（触发 DualWrite 双写）")
print("=" * 60)
try:
    ts = datetime.now()
    result = repo.upsert_metric(
        source="dualwrite_test",
        sub_category="test_sub",
        metric_name="test_metric",
        metric_value=42.0,
        ts=ts,
    )
    print(f"  upsert_metric 返回: {result}")
    print(f"  ✓ 写入成功（legacy + new 双写）")
except Exception as e:
    print(f"  ✗ 写入失败: {e}")
    import traceback; traceback.print_exc()

# ============================================================
# Step 3: 设置 READ_SOURCE=shadow 读一条 metric（触发审计写入）
# ============================================================
print()
print("=" * 60)
print("Step 3: shadow read 触发审计写入")
print("=" * 60)
os.environ["READ_SOURCE"] = "shadow"
try:
    # 获取新 repo 实例（确保 READ_SOURCE 生效）
    from dreambuddy_dal.di import _INSTANCES, _lock
    with _lock:
        _INSTANCES.clear()  # 清除缓存，强制重新创建
    repo2 = get_market_macro_repo()
    result = repo2.query_latest_metric("test_sub", "test_metric")
    print(f"  query_latest_metric 返回: {result}")
    print(f"  ✓ shadow read 完成（应写入 ma_migration_audit）")
except Exception as e:
    print(f"  ✗ shadow read 失败: {e}")
    import traceback; traceback.print_exc()

# ============================================================
# Step 4: 查询 ma_migration_audit 表
# ============================================================
print()
print("=" * 60)
print("Step 4: 查询 ma_migration_audit 审计表")
print("=" * 60)
db_path = os.path.join(_tmp_dir, "dreambuddy_core.db")
print(f"  数据库路径: {db_path}")
try:
    conn = sqlite3.connect(db_path)
    # 查看表
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    print(f"  数据库表: {[t[0] for t in tables]}")

    # 查询审计记录
    rows = conn.execute(
        "SELECT category, event_name, entity_key, result, severity, details "
        "FROM ma_migration_audit ORDER BY id DESC LIMIT 10"
    ).fetchall()
    print(f"  ma_migration_audit 行数: {len(rows)}")
    for r in rows:
        print(f"    category={r[0]} event={r[1]} key={r[2][:40]} result={r[3]} severity={r[4]}")
        print(f"      details={r[5][:100] if r[5] else 'null'}")
    conn.close()

    if rows:
        print(f"\n  ✓ 审计表有 {len(rows)} 条记录，DualWrite 验证成功！")
    else:
        print("\n  ⚠ 审计表为空（可能 shadow read 未触发，或 legacy 无数据可比对）")
except Exception as e:
    print(f"  ✗ 查询失败: {e}")
    import traceback; traceback.print_exc()

# ============================================================
# Step 5: 验证调用方无错误（读 legacy 数据）
# ============================================================
print()
print("=" * 60)
print("Step 5: 验证调用方返回正常（安全检查）")
print("=" * 60)
os.environ["READ_SOURCE"] = ""  # 恢复默认
try:
    with _lock:
        _INSTANCES.clear()
    repo3 = get_market_macro_repo()
    result = repo3.query_latest_metric("test_sub", "test_metric")
    print(f"  query_latest_metric (legacy) 返回: {result}")
    print(f"  ✓ 调用方正常返回 legacy 数据，无错误")
except Exception as e:
    print(f"  ✗ 调用方异常: {e}")

print()
print("=" * 60)
print("沙箱测试完成")
print(f"临时目录可手动清理: rm -rf {_tmp_dir}")
print("=" * 60)
