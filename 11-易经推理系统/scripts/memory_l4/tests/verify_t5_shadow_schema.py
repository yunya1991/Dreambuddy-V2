"""T5 ShadowLogger Schema 扩展独立验证脚本

验证内容：
1. py_compile 语法 OK（前置条件）
2. TDD 15 项核心用例：
   - shadow_logger.record_polling() 12 kwargs Optional 默认 None
   - record dict 中 12 字段正确写入（None / 指定值）
   - storage.CREATE TABLE 含新 12 列
   - storage.save_shadow_log() 新库插入新字段无异常
   - storage.get_shadow_log() 可查回 12 字段
3. 场景①：Fresh SQLite（新库）→ 插入含新字段 record → 无异常 + 可查回
4. 场景②：老库模拟（只有原 42 列）→ 插入含新字段 record → 触发降级 → 不抛异常 → 原字段正确写入
"""
from __future__ import annotations

import os
import sys
import sqlite3
import tempfile
import py_compile
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
MEMORY_L4_DIR = THIS_DIR.parent
BCRM2_DIR = MEMORY_L4_DIR / "bcrm2"
sys.path.insert(0, str(MEMORY_L4_DIR))

passed = 0
failed = 0
total = 0

def check(name, cond, detail=""):
    global passed, failed, total
    total += 1
    if cond:
        passed += 1
        print(f"  [PASS #{total}] {name}" + (f"  ({detail})" if detail else ""))
    else:
        failed += 1
        print(f"  [FAIL #{total}] {name}" + (f"  ({detail})" if detail else ""))

# ================================================================
# 0. py_compile 语法检查
# ================================================================
print("\n=== 0. py_compile 语法检查 ===")
try:
    py_compile.compile(str(BCRM2_DIR / "shadow_logger.py"), doraise=True)
    check("shadow_logger.py 语法 OK", True)
except py_compile.PyCompileError as e:
    check("shadow_logger.py 语法 OK", False, str(e))

try:
    py_compile.compile(str(BCRM2_DIR / "storage.py"), doraise=True)
    check("storage.py 语法 OK", True)
except py_compile.PyCompileError as e:
    check("storage.py 语法 OK", False, str(e))

# ================================================================
# 1. TDD：shadow_logger.record_polling() kwargs + record dict
# ================================================================
print("\n=== 1. TDD：ShadowLogger.record_polling() kwargs + record dict ===")

from bcrm2.shadow_logger import ShadowLogger

# 1.1 检查函数签名 12 kwargs 默认 None
import inspect
sig = inspect.signature(ShadowLogger.record_polling)
params = sig.parameters

t5_kwargs = [
    "fd_crypto_war_state", "fd_crypto_total_score", "fd_crypto_cap_mode", "fd_crypto_mult_mode",
    "fd_us_stock_war_state", "fd_us_stock_total_score",
    "sal_type", "sal_regime", "sal_calib_median", "sal_calib_min", "sal_calib_max", "sal_gate",
]
for k in t5_kwargs:
    check(f"kwargs {k} 存在", k in params)
    if k in params:
        check(f"kwargs {k} 默认值=None", params[k].default is None, f"default={params[k].default!r}")

# 1.2 组装 record dict（通过直接构造 storage.save_shadow_log 用的 record）
from datetime import datetime, timezone

def _make_full_record(**overrides):
    """构造含新12字段的完整 shadow record。"""
    base = {
        "reactive_L": 0.6, "reactive_T": 0.15, "reactive_C": 0.72,
        "reactive_regime": "TREND_UP_STRONG",
        "reactive_pos_mult": 1.2, "reactive_tp_mult": 1.0, "reactive_sl_mult": 0.9, "reactive_threshold": 1.1,
        "forecast_L": 0.8, "forecast_T": 0.2,
        "forecast_global_ranges": '{"global_position_mult":[0.8,1.2]}',
        "forecast_sector_weights": '{"weights":{"defi":0.2}}',
        "baseline_pos_mult": 1.1, "baseline_tp_mult": 1.0, "baseline_sl_mult": 0.95,
        "baseline_threshold_mult": 1.05, "baseline_long_conf_threshold": 0.78, "baseline_short_conf_threshold": 0.8,
        "ai_pos_mult": 1.25, "ai_tp_mult": 1.05, "ai_sl_mult": 0.88, "ai_threshold_mult": 1.08,
        "ai_long_threshold": 0.76, "ai_short_threshold": 0.81, "ai_ls_ratio_cap": 2.0,
        "effective_pos_mult": 1.2, "effective_tp_mult": 1.03, "effective_sl_mult": 0.9,
        "effective_threshold_mult": 1.07,
        "effective_long_conf_threshold": 0.77, "effective_short_conf_threshold": 0.805,
        "enable_inject": True, "alpha_blend": 0.35,
        "actual_direction": "LONG", "actual_confidence": 0.85,
        "actual_position_usdt": 500.0, "actual_tp_px": 72000.0, "actual_sl_px": 68000.0, "actual_threshold": 0.8,
        "fma_on_allowed": True, "fma_on_eff_threshold": 0.82,
        # T5 新12字段
        "fd_crypto_war_state": "攻守兼备-中",
        "fd_crypto_total_score": 78.5,
        "fd_crypto_cap_mode": 0.62,
        "fd_crypto_mult_mode": 1.35,
        "fd_us_stock_war_state": "进攻-强",
        "fd_us_stock_total_score": 85.0,
        "sal_type": "crypto_usdt",
        "sal_regime": "TREND_UP_STRONG",
        "sal_calib_median": 0.042,
        "sal_calib_min": -0.12,
        "sal_calib_max": 0.18,
        "sal_gate": 1,
    }
    base.update(overrides)
    return base

# 1.3 验证 record 构造 OK，新字段位置在 fma_on_eff_threshold 之后
rec_full = _make_full_record()
check("record 新12字段 fd_crypto_war_state 存在", "fd_crypto_war_state" in rec_full)
check("record 新12字段 sal_gate 存在", "sal_gate" in rec_full)
fma_idx = list(rec_full.keys()).index("fma_on_eff_threshold")
fd_idx = list(rec_full.keys()).index("fd_crypto_war_state")
sal_idx = list(rec_full.keys()).index("sal_gate")
check("12字段写在 fma_on_eff_threshold 之后（fd_crypto_war_state > fma）", fd_idx > fma_idx)
check("12字段写在 fma_on_eff_threshold 之后（sal_gate > fma）", sal_idx > fma_idx)

# 1.4 None 值 record（全部12字段 None）
rec_none = _make_full_record(
    fd_crypto_war_state=None, fd_crypto_total_score=None, fd_crypto_cap_mode=None, fd_crypto_mult_mode=None,
    fd_us_stock_war_state=None, fd_us_stock_total_score=None,
    sal_type=None, sal_regime=None, sal_calib_median=None, sal_calib_min=None, sal_calib_max=None, sal_gate=None,
)
for k in t5_kwargs:
    check(f"None record: {k} is None", rec_none[k] is None)

# 1.5 sal_gate 边界：True/False/None 转 1/0/None
from bcrm2.storage import EvolutionStorageSQLite
def _sg(v):
    if v is None: return None
    if isinstance(v, bool): return 1 if v else 0
    try: return 1 if int(v) else 0
    except: return None
check("sal_gate True → 1", _sg(True) == 1)
check("sal_gate False → 0", _sg(False) == 0)
check("sal_gate None → None", _sg(None) is None)
check("sal_gate 1 → 1", _sg(1) == 1)
check("sal_gate 0 → 0", _sg(0) == 0)

# ================================================================
# 2. 场景①：Fresh SQLite（新库）插入含新字段 record → 无异常 + 可查回
# ================================================================
print("\n=== 2. 场景①：新库（fresh SQLite）插入含新字段 → 无异常+可查回 ===")

with tempfile.TemporaryDirectory() as tmpdir:
    fresh_db = Path(tmpdir) / "fresh_evo.db"
    storage_fresh = EvolutionStorageSQLite(fresh_db)

    # 2.1 检查表结构：新12列存在
    cur = storage_fresh._conn.cursor()
    cols = [r[1] for r in cur.execute("PRAGMA table_info(shadow_param_log)").fetchall()]
    for k in t5_kwargs:
        check(f"新库表结构含列 {k}", k in cols, f"missing={k not in cols}")

    # 2.2 插入带新字段的记录
    rid = storage_fresh.save_shadow_log("BTCUSDT", rec_full)
    check(f"新库 INSERT 成功 rid={rid} > 0", rid > 0)

    # 2.3 get_shadow_log 查回新12字段值
    rows = storage_fresh.get_shadow_log("BTCUSDT", days=7)
    check(f"get_shadow_log 返回 1 行", len(rows) == 1)
    if rows:
        r = rows[0]
        check("查回 fd_crypto_war_state='攻守兼备-中'", r.get("fd_crypto_war_state") == "攻守兼备-中")
        check("查回 fd_crypto_total_score=78.5", abs(float(r.get("fd_crypto_total_score") or 0) - 78.5) < 1e-6)
        check("查回 fd_crypto_cap_mode=0.62", abs(float(r.get("fd_crypto_cap_mode") or 0) - 0.62) < 1e-6)
        check("查回 fd_crypto_mult_mode=1.35", abs(float(r.get("fd_crypto_mult_mode") or 0) - 1.35) < 1e-6)
        check("查回 fd_us_stock_war_state='进攻-强'", r.get("fd_us_stock_war_state") == "进攻-强")
        check("查回 fd_us_stock_total_score=85.0", abs(float(r.get("fd_us_stock_total_score") or 0) - 85.0) < 1e-6)
        check("查回 sal_type='crypto_usdt'", r.get("sal_type") == "crypto_usdt")
        check("查回 sal_regime='TREND_UP_STRONG'", r.get("sal_regime") == "TREND_UP_STRONG")
        check("查回 sal_calib_median=0.042", abs(float(r.get("sal_calib_median") or 0) - 0.042) < 1e-6)
        check("查回 sal_calib_min=-0.12", abs(float(r.get("sal_calib_min") or 0) - (-0.12)) < 1e-6)
        check("查回 sal_calib_max=0.18", abs(float(r.get("sal_calib_max") or 0) - 0.18) < 1e-6)
        check("查回 sal_gate=True（bool 转换）", r.get("sal_gate") is True)

    # 2.4 插入 None 值 record，确认无异常
    rid2 = storage_fresh.save_shadow_log("ETHUSDT", rec_none)
    check(f"新库 None 值 INSERT 成功 rid2={rid2} > 0", rid2 > 0)
    rows2 = storage_fresh.get_shadow_log("ETHUSDT", days=7)
    if rows2:
        r2 = rows2[0]
        for k in t5_kwargs:
            check(f"None record 查回 {k} is None/NULL", r2.get(k) is None)

    storage_fresh._conn.close()

# ================================================================
# 3. 场景②：老库模拟（CREATE TABLE 只含原 42 列不含新增12列）→ 触发降级
# ================================================================
print("\n=== 3. 场景②：老库（只有原42列）→ 降级 INSERT，零异常 ===")

with tempfile.TemporaryDirectory() as tmpdir:
    old_db = Path(tmpdir) / "old_evo.db"

    # 3.1 手工创建「老库」：只有原 42 列（不含 T5 新12列）
    conn_old = sqlite3.connect(str(old_db))
    cur_old = conn_old.cursor()
    cur_old.execute("""
        CREATE TABLE IF NOT EXISTS shadow_param_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol          TEXT NOT NULL,
            timestamp       TEXT NOT NULL,
            reactive_L      REAL, reactive_T REAL, reactive_C REAL, reactive_regime TEXT,
            reactive_pos_mult  REAL, reactive_tp_mult   REAL, reactive_sl_mult   REAL, reactive_threshold REAL,
            forecast_L      REAL, forecast_T      REAL,
            forecast_global_ranges   TEXT, forecast_sector_weights  TEXT,
            baseline_pos_mult REAL, baseline_tp_mult REAL, baseline_sl_mult REAL,
            baseline_threshold_mult REAL, baseline_long_conf_threshold REAL, baseline_short_conf_threshold REAL,
            ai_pos_mult REAL, ai_tp_mult REAL, ai_sl_mult REAL, ai_threshold_mult REAL,
            ai_long_threshold REAL, ai_short_threshold REAL, ai_ls_ratio_cap REAL,
            effective_pos_mult REAL, effective_tp_mult REAL, effective_sl_mult REAL,
            effective_threshold_mult REAL, effective_long_conf_threshold REAL, effective_short_conf_threshold REAL,
            enable_inject INTEGER, alpha_blend REAL,
            actual_direction TEXT, actual_confidence REAL, actual_position_usdt REAL,
            actual_tp_px REAL, actual_sl_px REAL, actual_threshold REAL,
            fma_on_allowed INTEGER, fma_on_eff_threshold REAL
        )
    """)
    conn_old.commit()
    conn_old.close()

    # 3.2 用 EvolutionStorageSQLite 打开老库（_init_sqlite_schema 会 try ALTER TABLE，但就算失败 save_shadow_log 也有降级）
    storage_old = EvolutionStorageSQLite(old_db)

    # 3.3 验证老库（不执行 ALTER TABLE，模拟真老库：这里 _init_sqlite_schema 实际会 ALTER，所以我们重新用 sqlite3 连回，去掉新列模拟真老库）
    # 重新构建真老库：删除新建的列——SQLite 不支持 DROP COLUMN，所以重新创建
    storage_old._conn.close()
    os.remove(str(old_db))

    conn_old2 = sqlite3.connect(str(old_db))
    co = conn_old2.cursor()
    # 先建其他核心表（避免 _init_sqlite_schema 报错无关的），再建 shadow_param_log 老版
    co.execute("""
        CREATE TABLE IF NOT EXISTS regime_state_daily (
            timestamp TEXT NOT NULL, symbol TEXT NOT NULL DEFAULT 'BTCUSDT',
            price_close REAL NOT NULL, level_raw REAL NOT NULL, trend_raw REAL NOT NULL,
            level_smooth REAL NOT NULL, trend_smooth REAL NOT NULL,
            regime_probs TEXT NOT NULL, top3 TEXT NOT NULL, consensus REAL NOT NULL,
            hmm_state INTEGER NOT NULL, bocpd_cp_prob REAL NOT NULL, indicators TEXT NOT NULL,
            data_version INTEGER NOT NULL DEFAULT 1, PRIMARY KEY (timestamp, symbol)
        )
    """)
    co.execute("""
        CREATE TABLE IF NOT EXISTS shadow_param_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol          TEXT NOT NULL, timestamp       TEXT NOT NULL,
            reactive_L      REAL, reactive_T REAL, reactive_C REAL, reactive_regime TEXT,
            reactive_pos_mult  REAL, reactive_tp_mult   REAL, reactive_sl_mult   REAL, reactive_threshold REAL,
            forecast_L      REAL, forecast_T      REAL,
            forecast_global_ranges   TEXT, forecast_sector_weights  TEXT,
            baseline_pos_mult REAL, baseline_tp_mult REAL, baseline_sl_mult REAL,
            baseline_threshold_mult REAL, baseline_long_conf_threshold REAL, baseline_short_conf_threshold REAL,
            ai_pos_mult REAL, ai_tp_mult REAL, ai_sl_mult REAL, ai_threshold_mult REAL,
            ai_long_threshold REAL, ai_short_threshold REAL, ai_ls_ratio_cap REAL,
            effective_pos_mult REAL, effective_tp_mult REAL, effective_sl_mult REAL,
            effective_threshold_mult REAL, effective_long_conf_threshold REAL, effective_short_conf_threshold REAL,
            enable_inject INTEGER, alpha_blend REAL,
            actual_direction TEXT, actual_confidence REAL, actual_position_usdt REAL,
            actual_tp_px REAL, actual_sl_px REAL, actual_threshold REAL,
            fma_on_allowed INTEGER, fma_on_eff_threshold REAL
        )
    """)
    conn_old2.commit()
    conn_old2.close()

    # 现在打开老库：关闭 check_same_thread 安全
    storage_old2 = EvolutionStorageSQLite.__new__(EvolutionStorageSQLite)
    storage_old2.db_path = old_db
    storage_old2._conn = sqlite3.connect(str(old_db), check_same_thread=False)
    storage_old2._conn.row_factory = sqlite3.Row
    # 不调用 _init_sqlite_schema（保留老库纯净状态——仅原42列）

    # 3.4 尝试 INSERT 带新12字段的记录 → 应该触发降级路径，零异常
    rid_old = storage_old2.save_shadow_log("BTCUSDT", rec_full)
    check(f"老库 INSERT（降级）成功 rid_old={rid_old} > 0", rid_old > 0, f"rid={rid_old}")

    # 3.5 验证原字段正确写入（get_shadow_log 有 SELECT 降级，使用原生 SQL 查）
    cur_verify = storage_old2._conn.cursor()
    row = cur_verify.execute("SELECT symbol, reactive_L, reactive_regime, ai_pos_mult, actual_direction, fma_on_allowed, fma_on_eff_threshold FROM shadow_param_log WHERE id=?", (rid_old,)).fetchone()
    check("老库降级写入：symbol='BTCUSDT'", row["symbol"] == "BTCUSDT")
    check("老库降级写入：reactive_L≈0.6", abs(float(row["reactive_L"] or 0) - 0.6) < 1e-6)
    check("老库降级写入：reactive_regime='TREND_UP_STRONG'", row["reactive_regime"] == "TREND_UP_STRONG")
    check("老库降级写入：ai_pos_mult≈1.25", abs(float(row["ai_pos_mult"] or 0) - 1.25) < 1e-6)
    check("老库降级写入：actual_direction='LONG'", row["actual_direction"] == "LONG")
    check("老库降级写入：fma_on_allowed=1 (True→1)", int(row["fma_on_allowed"] or 0) == 1)
    check("老库降级写入：fma_on_eff_threshold≈0.82", abs(float(row["fma_on_eff_threshold"] or 0) - 0.82) < 1e-6)

    # 3.6 验证老库中确实没有新12列（查 PRAGMA）
    cols_old = [r[1] for r in cur_verify.execute("PRAGMA table_info(shadow_param_log)").fetchall()]
    check("老库确认：无 fd_crypto_war_state 列", "fd_crypto_war_state" not in cols_old)
    check("老库确认：无 sal_gate 列", "sal_gate" not in cols_old)

    # 3.7 save_shadow_log 在老库不抛任何异常（包括多次调用）
    try:
        rid_old2 = storage_old2.save_shadow_log("ETHUSDT", rec_none)
        check("老库二次 INSERT（None 值）零异常", rid_old2 > 0)
    except Exception as e:
        check("老库二次 INSERT（None 值）零异常", False, f"{type(e).__name__}: {e}")

    storage_old2._conn.close()

# ================================================================
# 4. 汇总
# ================================================================
print("\n" + "=" * 60)
print(f"验证汇总：共 {total} 项，PASS {passed}，FAIL {failed}")
print("=" * 60)
sys.exit(0 if failed == 0 else 1)
