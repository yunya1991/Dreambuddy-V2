"""T6.1 T5 Schema 兼容性回归测试：老库(42列) + 新库(54列) 双场景零异常。

运行:
  cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统
  python3 -m pytest scripts/memory_l4/tests/test_t5_shadow_schema_compat.py -v --tb=short
"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict

import pytest

THIS_DIR = Path(__file__).resolve().parent
MEMORY_L4_DIR = THIS_DIR.parent
sys.path.insert(0, str(MEMORY_L4_DIR))


# ================================================================
# 老库 42 列 schema（与实盘历史表完全相同，不含 T5 新 12 列）
# ================================================================
OLD_SCHEMA_42_COLS_CREATE = """
CREATE TABLE shadow_param_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT NOT NULL,
    timestamp       TEXT NOT NULL,
    reactive_L      REAL,
    reactive_T      REAL,
    reactive_C      REAL,
    reactive_regime TEXT,
    reactive_pos_mult  REAL,
    reactive_tp_mult   REAL,
    reactive_sl_mult   REAL,
    reactive_threshold REAL,
    forecast_L      REAL,
    forecast_T      REAL,
    forecast_global_ranges   TEXT,
    forecast_sector_weights  TEXT,
    baseline_pos_mult            REAL,
    baseline_tp_mult             REAL,
    baseline_sl_mult             REAL,
    baseline_threshold_mult      REAL,
    baseline_long_conf_threshold REAL,
    baseline_short_conf_threshold REAL,
    ai_pos_mult         REAL,
    ai_tp_mult          REAL,
    ai_sl_mult          REAL,
    ai_threshold_mult   REAL,
    ai_long_threshold   REAL,
    ai_short_threshold  REAL,
    ai_ls_ratio_cap     REAL,
    effective_pos_mult            REAL,
    effective_tp_mult             REAL,
    effective_sl_mult             REAL,
    effective_threshold_mult      REAL,
    effective_long_conf_threshold REAL,
    effective_short_conf_threshold REAL,
    enable_inject     INTEGER,
    alpha_blend       REAL,
    actual_direction    TEXT,
    actual_confidence   REAL,
    actual_position_usdt REAL,
    actual_tp_px        REAL,
    actual_sl_px        REAL,
    actual_threshold    REAL,
    fma_on_allowed      INTEGER,
    fma_on_eff_threshold REAL
)
"""

# T5 新 12 列名称
T5_NEW_COLS = [
    "fd_crypto_war_state", "fd_crypto_total_score",
    "fd_crypto_cap_mode", "fd_crypto_mult_mode",
    "fd_us_stock_war_state", "fd_us_stock_total_score",
    "sal_type", "sal_regime", "sal_calib_median",
    "sal_calib_min", "sal_calib_max", "sal_gate",
]


def _make_record_with_12_new_fields(**overrides) -> Dict[str, Any]:
    """构造含全部 12 个 T5 新字段值的完整 record（用于插入老库/新库）。"""
    rec = {
        # reactive
        "reactive_L": 0.61,
        "reactive_T": 0.17,
        "reactive_C": 0.73,
        "reactive_regime": "TREND_UP_STRONG",
        "reactive_pos_mult": 1.15,
        "reactive_tp_mult": 1.02,
        "reactive_sl_mult": 0.88,
        "reactive_threshold": 0.96,
        # forecast
        "forecast_L": 0.82,
        "forecast_T": 0.24,
        "forecast_global_ranges": json.dumps(
            {"global_position_mult": [0.85, 1.25], "ls_ratio_cap": [0.3, 0.7]}),
        "forecast_sector_weights": json.dumps(
            {"weights": {"defi": 0.22, "ai": 0.28, "rwa": 0.18, "meme": 0.14, "l2": 0.18}}),
        # baseline 6
        "baseline_pos_mult": 1.1,
        "baseline_tp_mult": 1.0,
        "baseline_sl_mult": 0.95,
        "baseline_threshold_mult": 1.05,
        "baseline_long_conf_threshold": 0.785,
        "baseline_short_conf_threshold": 0.81,
        # ai 7
        "ai_pos_mult": 1.22,
        "ai_tp_mult": 1.04,
        "ai_sl_mult": 0.86,
        "ai_threshold_mult": 1.06,
        "ai_long_threshold": 0.765,
        "ai_short_threshold": 0.815,
        "ai_ls_ratio_cap": 2.1,
        # effective 6
        "effective_pos_mult": 1.16,
        "effective_tp_mult": 1.02,
        "effective_sl_mult": 0.89,
        "effective_threshold_mult": 1.03,
        "effective_long_conf_threshold": 0.775,
        "effective_short_conf_threshold": 0.805,
        # 元数据 2
        "enable_inject": True,
        "alpha_blend": 0.3,
        # actual 交易 6（原42列中关键断言字段）
        "actual_direction": "LONG",
        "actual_confidence": 0.83,
        "actual_position_usdt": 520.0,
        "actual_tp_px": 72600.0,
        "actual_sl_px": 67900.0,
        "actual_threshold": 0.80,
        # FMA 2
        "fma_on_allowed": True,
        "fma_on_eff_threshold": 0.815,
        # T5 战略层影子 6 字段
        "fd_crypto_war_state": "攻守兼备-中",
        "fd_crypto_total_score": 76.5,
        "fd_crypto_cap_mode": 0.64,
        "fd_crypto_mult_mode": 1.32,
        "fd_us_stock_war_state": "进攻-强",
        "fd_us_stock_total_score": 86.0,
        # T5 策略算法层影子 6 字段
        "sal_type": "crypto_usdt",
        "sal_regime": "TREND_UP_STRONG",
        "sal_calib_median": 0.045,
        "sal_calib_min": -0.115,
        "sal_calib_max": 0.175,
        "sal_gate": 1,
    }
    rec.update(overrides)
    return rec


# ================================================================
# T6.1 测试用例 3：老库 42 列零异常 + 新库 54 列镜像
# ================================================================
class TestT5ShadowSchemaCompat:
    """验证 T5 新12列 schema 兼容性：
    1) 老库(42列) INSERT 降级不抛异常，原42列正确写入
    2) 新库(54列) 完整写入，查回12新列值正确
    """

    def test_old_db_42_cols_zero_exception(self, tmp_path, monkeypatch):
        """1) 原生 sqlite3 创建 42 列老库（不含 T5 新列）
           2) EvolutionStorageSQLite 打开（通过 monkeypatch 禁用 T5 列 ALTER TABLE，
              模拟「迁移逻辑 try/except pass 无副作用」的场景）
           3) save_shadow_log 插入 2 次含 12 新字段值的 record：
              - rid > 0（零异常，降级 INSERT）
              - reactive_L / actual_direction / enable_inject 正确
              - 新字段值返回 None（自动补 None）
           4) fresh 54 列新库镜像：查回 T5 新字段值正确
        """
        from scripts.memory_l4.bcrm2.storage import EvolutionStorageSQLite

        # ============================================================
        # Part A：老库 42 列场景
        # ============================================================
        old_db_path = tmp_path / "old_schema_42cols.db"

        # A1: 原生 sqlite3 创建 42 列老库（与实盘历史表完全相同的 schema）
        conn_old = sqlite3.connect(str(old_db_path))
        cur_old = conn_old.cursor()
        cur_old.execute(OLD_SCHEMA_42_COLS_CREATE)
        conn_old.commit()

        # 验证老库确为 42 列（不含 T5 新 12 列）
        cols_old = [r[1] for r in cur_old.execute(
            "PRAGMA table_info(shadow_param_log)").fetchall()]
        for nc in T5_NEW_COLS:
            assert nc not in cols_old, f"老库不应包含新列 {nc}！"
        conn_old.close()

        # A2: 关键 — monkeypatch 掉 T5 12 列的 ALTER TABLE 迁移，
        #     模拟「迁移失败/try-except pass 无副作用」的老库场景
        import scripts.memory_l4.bcrm2.storage as storage_module

        original_init = storage_module._init_sqlite_schema

        def _patched_init_skip_t5_migration(conn: sqlite3.Connection):
            """执行 schema 初始化，但跳过 T5 12 列迁移（模拟老库零 ALTER 副作用）。"""
            cur = conn.cursor()
            # --- 1. 原核心 CREATE TABLE（原样） ---
            cur.execute("""
                CREATE TABLE IF NOT EXISTS regime_state_daily (
                    timestamp       TEXT NOT NULL,
                    symbol          TEXT NOT NULL DEFAULT 'BTCUSDT',
                    price_close     REAL NOT NULL,
                    level_raw       REAL NOT NULL,
                    trend_raw       REAL NOT NULL,
                    level_smooth    REAL NOT NULL,
                    trend_smooth    REAL NOT NULL,
                    regime_probs    TEXT NOT NULL,
                    top3            TEXT NOT NULL,
                    consensus       REAL NOT NULL,
                    hmm_state       INTEGER NOT NULL,
                    bocpd_cp_prob   REAL NOT NULL,
                    indicators      TEXT NOT NULL,
                    data_version    INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY (timestamp, symbol)
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_regime_state_daily_ts "
                        "ON regime_state_daily (timestamp)")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS regime_trajectory_90d (
                    symbol          TEXT PRIMARY KEY,
                    updated_at      TEXT NOT NULL,
                    trajectory      TEXT NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS regime_model_weights (
                    week_start      TEXT PRIMARY KEY,
                    level_weights   TEXT NOT NULL,
                    trend_weights   TEXT NOT NULL,
                    regime_centers  TEXT NOT NULL,
                    max_daily_delta REAL NOT NULL,
                    objective       REAL NOT NULL,
                    comment         TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS regime_dotplot_latest (
                    symbol          TEXT PRIMARY KEY,
                    updated_at      TEXT NOT NULL,
                    target_index    INTEGER NOT NULL,
                    rows            TEXT NOT NULL,
                    cols            TEXT NOT NULL,
                    matrix          TEXT NOT NULL,
                    marginal_probs  TEXT NOT NULL,
                    sample_counts   TEXT NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS morph_prediction_log (
                    id                INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol            TEXT NOT NULL,
                    prediction_date   TEXT NOT NULL,
                    target_date       TEXT NOT NULL,
                    horizon_days      INTEGER NOT NULL,
                    predicted_l       REAL NOT NULL,
                    predicted_t       REAL,
                    actual_l          REAL,
                    actual_t          REAL,
                    error_l           REAL,
                    fft_components    TEXT,
                    hermite_params    TEXT,
                    correction_applied TEXT,
                    created_at        TEXT DEFAULT (datetime('now')),
                    UNIQUE(symbol, prediction_date, target_date)
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_mpl_symbol_target ON morph_prediction_log(symbol, target_date)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_mpl_unfilled ON morph_prediction_log(symbol, actual_l IS NULL) WHERE actual_l IS NULL")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS morph_correction_state (
                    symbol            TEXT PRIMARY KEY,
                    weight_correction TEXT NOT NULL,
                    tangent_correction TEXT NOT NULL,
                    correction_count  INTEGER NOT NULL DEFAULT 0,
                    last_mae          REAL,
                    first_corrected_at TEXT,
                    last_corrected_at TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS morph_anchor_state (
                    symbol              TEXT PRIMARY KEY,
                    anchor_overrides    TEXT NOT NULL,
                    switch_count        INTEGER NOT NULL DEFAULT 0,
                    last_switch_from    TEXT,
                    last_switch_to      TEXT,
                    last_switch_date    TEXT,
                    last_corrected_at   TEXT,
                    first_corrected_at  TEXT,
                    overshoot_hint      TEXT
                )
            """)
            try:
                cur.execute("ALTER TABLE morph_anchor_state ADD COLUMN overshoot_hint TEXT")
            except sqlite3.OperationalError:
                pass

            # --- 2. shadow_param_log CREATE TABLE（只创建到 FMA，不含 T5 12 新列） ---
            # 这里故意只创建「老库 42 列 + id/symbol/timestamp」版本，
            # 模拟老库从未有过 T5 列。CURRENT 表已由原生 sqlite3 创建好，
            # 所以 CREATE TABLE IF NOT EXISTS 不会重建。
            cur.execute("""
                CREATE TABLE IF NOT EXISTS shadow_param_log (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol          TEXT NOT NULL,
                    timestamp       TEXT NOT NULL,
                    reactive_L      REAL,
                    reactive_T      REAL,
                    reactive_C      REAL,
                    reactive_regime TEXT,
                    reactive_pos_mult  REAL,
                    reactive_tp_mult   REAL,
                    reactive_sl_mult   REAL,
                    reactive_threshold REAL,
                    forecast_L      REAL,
                    forecast_T      REAL,
                    forecast_global_ranges   TEXT,
                    forecast_sector_weights  TEXT,
                    baseline_pos_mult            REAL,
                    baseline_tp_mult             REAL,
                    baseline_sl_mult             REAL,
                    baseline_threshold_mult      REAL,
                    baseline_long_conf_threshold REAL,
                    baseline_short_conf_threshold REAL,
                    ai_pos_mult         REAL,
                    ai_tp_mult          REAL,
                    ai_sl_mult          REAL,
                    ai_threshold_mult   REAL,
                    ai_long_threshold   REAL,
                    ai_short_threshold  REAL,
                    ai_ls_ratio_cap     REAL,
                    effective_pos_mult            REAL,
                    effective_tp_mult             REAL,
                    effective_sl_mult             REAL,
                    effective_threshold_mult      REAL,
                    effective_long_conf_threshold REAL,
                    effective_short_conf_threshold REAL,
                    enable_inject     INTEGER,
                    alpha_blend       REAL,
                    actual_direction    TEXT,
                    actual_confidence   REAL,
                    actual_position_usdt REAL,
                    actual_tp_px        REAL,
                    actual_sl_px        REAL,
                    actual_threshold    REAL,
                    fma_on_allowed      INTEGER,
                    fma_on_eff_threshold REAL
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS exit_strategy_log (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol          TEXT NOT NULL,
                    timestamp       TEXT NOT NULL,
                    strategy_name   TEXT NOT NULL,
                    action          TEXT,
                    reason          TEXT,
                    age_hours       REAL,
                    in_protection   INTEGER,
                    ev              REAL,
                    confidence      REAL,
                    pnl             REAL,
                    win             INTEGER
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_exit_strat_symbol_ts "
                        "ON exit_strategy_log (symbol, timestamp)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_exit_strat_name_ts "
                        "ON exit_strategy_log (strategy_name, timestamp)")

            # --- 3. Schema 迁移：故意不执行 T5 12 列迁移（模拟 try/except pass） ---
            # FMA 列迁移：可以执行（老库也有）
            _fma_cols = [
                ("fma_on_allowed", "INTEGER"),
                ("fma_on_eff_threshold", "REAL"),
            ]
            for _col, _typ in _fma_cols:
                try:
                    cur.execute(f"ALTER TABLE shadow_param_log ADD COLUMN {_col} {_typ}")
                except Exception:
                    pass
            _tri_val_cols = [
                ("baseline_pos_mult", "REAL"),
                ("baseline_tp_mult", "REAL"),
                ("baseline_sl_mult", "REAL"),
                ("baseline_threshold_mult", "REAL"),
                ("baseline_long_conf_threshold", "REAL"),
                ("baseline_short_conf_threshold", "REAL"),
                ("ai_pos_mult", "REAL"),
                ("ai_tp_mult", "REAL"),
                ("ai_sl_mult", "REAL"),
                ("ai_threshold_mult", "REAL"),
                ("ai_long_threshold", "REAL"),
                ("ai_short_threshold", "REAL"),
                ("ai_ls_ratio_cap", "REAL"),
                ("effective_pos_mult", "REAL"),
                ("effective_tp_mult", "REAL"),
                ("effective_sl_mult", "REAL"),
                ("effective_threshold_mult", "REAL"),
                ("effective_long_conf_threshold", "REAL"),
                ("effective_short_conf_threshold", "REAL"),
                ("enable_inject", "INTEGER"),
                ("alpha_blend", "REAL"),
            ]
            for _col, _typ in _tri_val_cols:
                try:
                    cur.execute(f"ALTER TABLE shadow_param_log ADD COLUMN {_col} {_typ}")
                except Exception:
                    pass

            # ★★★ 故意跳过 T5 12 列 ALTER TABLE 迁移（模拟老库零副作用 try/except pass）
            # _t5_shadow_cols = [...] 迁移块不执行！

            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_shadow_symbol_ts "
                "ON shadow_param_log(symbol, timestamp)"
            )
            conn.commit()

        monkeypatch.setattr(
            storage_module, "_init_sqlite_schema", _patched_init_skip_t5_migration
        )

        # 打开老库：此时 T5 新列不存在（ALTER TABLE 被跳过）
        storage_old = EvolutionStorageSQLite(old_db_path)

        # 确认：老库确无 T5 12 列
        cols_after = [r[1] for r in storage_old._conn.execute(
            "PRAGMA table_info(shadow_param_log)").fetchall()]
        for nc in T5_NEW_COLS:
            assert nc not in cols_after, (
                f"monkeypatch 后老库仍有新列 {nc}！迁移跳过逻辑失效。"
            )

        # A3: 构造 2 条含全部 12 新字段值的 record 并插入
        rec1 = _make_record_with_12_new_fields(
            reactive_L=0.55,
            actual_direction="LONG",
            enable_inject=True,
        )
        rec2 = _make_record_with_12_new_fields(
            reactive_L=0.72,
            actual_direction="SHORT",
            enable_inject=False,
        )

        # 断言：两次 rid > 0（零异常，降级 INSERT 成功）
        rid1 = storage_old.save_shadow_log("BTCUSDT", rec1)
        assert rid1 > 0, f"老库第1次 INSERT 返回 rid={rid1}，应 > 0"

        rid2 = storage_old.save_shadow_log("BTCUSDT", rec2)
        assert rid2 > 0, f"老库第2次 INSERT 返回 rid={rid2}，应 > 0"

        # A4: get_shadow_log() 查回 2 条记录，断言原 42 列值正确
        rows_old = storage_old.get_shadow_log("BTCUSDT", days=7)
        assert len(rows_old) == 2, f"老库应返回 2 条记录，实际 {len(rows_old)}"

        # 第 1 条
        r1 = rows_old[0]
        assert abs(float(r1.get("reactive_L") or 0) - 0.55) < 1e-9, (
            f"老库查回 reactive_L 错: {r1.get('reactive_L')} ≠ 0.55"
        )
        assert r1.get("actual_direction") == "LONG", (
            f"老库查回 actual_direction 错: {r1.get('actual_direction')} ≠ LONG"
        )
        assert r1.get("enable_inject") is True, (
            f"老库查回 enable_inject 错: {r1.get('enable_inject')} ≠ True"
        )

        # 第 2 条
        r2 = rows_old[1]
        assert abs(float(r2.get("reactive_L") or 0) - 0.72) < 1e-9, (
            f"老库查回 reactive_L 错: {r2.get('reactive_L')} ≠ 0.72"
        )
        assert r2.get("actual_direction") == "SHORT", (
            f"老库查回 actual_direction 错: {r2.get('actual_direction')} ≠ SHORT"
        )
        assert r2.get("enable_inject") is False, (
            f"老库查回 enable_inject 错: {r2.get('enable_inject')} ≠ False"
        )

        # A5: 断言 T5 新字段值返回 None（老库降级查询返回 42 列，新列 key 不存在 → None）
        for row in (r1, r2):
            for nc in T5_NEW_COLS:
                val = row.get(nc)
                assert val is None, (
                    f"老库查回新字段 {nc} 应为 None，实际 {val!r}"
                )

        storage_old._conn.close()

        # ============================================================
        # Part B：取消 monkeypatch → fresh 54 列新库镜像
        # ============================================================
        monkeypatch.undo()
        # 恢复原始初始化函数
        monkeypatch.setattr(storage_module, "_init_sqlite_schema", original_init)

        new_db_path = tmp_path / "fresh_schema_54cols.db"

        # B1: EvolutionStorageSQLite 创建全新 54 列库（含 T5 新12列）
        storage_new = EvolutionStorageSQLite(new_db_path)

        # 验证新库确包含 12 新列
        cur_new = storage_new._conn.cursor()
        cols_new = [r[1] for r in cur_new.execute(
            "PRAGMA table_info(shadow_param_log)").fetchall()]
        for nc in T5_NEW_COLS:
            assert nc in cols_new, f"新库应包含新列 {nc}！"

        # B2: 插入与 Part A 相同的 2 条 record
        rid1_new = storage_new.save_shadow_log("BTCUSDT", rec1)
        rid2_new = storage_new.save_shadow_log("BTCUSDT", rec2)
        assert rid1_new > 0, "新库第1次 INSERT 失败"
        assert rid2_new > 0, "新库第2次 INSERT 失败"

        # B3: 查回并断言原 42 列值（与老库相同）
        rows_new = storage_new.get_shadow_log("BTCUSDT", days=7)
        assert len(rows_new) == 2

        n1 = rows_new[0]
        assert abs(float(n1.get("reactive_L") or 0) - 0.55) < 1e-9
        assert n1.get("actual_direction") == "LONG"
        assert n1.get("enable_inject") is True

        n2 = rows_new[1]
        assert abs(float(n2.get("reactive_L") or 0) - 0.72) < 1e-9
        assert n2.get("actual_direction") == "SHORT"
        assert n2.get("enable_inject") is False

        # B4: 断言 T5 新 12 字段值正确（完整写入）
        # 第 1 条新字段断言
        assert n1.get("fd_crypto_war_state") == "攻守兼备-中", (
            f"新库 fd_crypto_war_state 错: {n1.get('fd_crypto_war_state')}"
        )
        assert abs(float(n1.get("fd_crypto_total_score") or 0) - 76.5) < 1e-6
        assert abs(float(n1.get("fd_crypto_cap_mode") or 0) - 0.64) < 1e-6
        assert abs(float(n1.get("fd_crypto_mult_mode") or 0) - 1.32) < 1e-6
        assert n1.get("fd_us_stock_war_state") == "进攻-强"
        assert abs(float(n1.get("fd_us_stock_total_score") or 0) - 86.0) < 1e-6
        assert n1.get("sal_type") == "crypto_usdt"
        assert n1.get("sal_regime") == "TREND_UP_STRONG"
        assert abs(float(n1.get("sal_calib_median") or 0) - 0.045) < 1e-6
        assert abs(float(n1.get("sal_calib_min") or 0) - (-0.115)) < 1e-6
        assert abs(float(n1.get("sal_calib_max") or 0) - 0.175) < 1e-6
        assert n1.get("sal_gate") is True  # INTEGER 1 → bool 转换

        # 第 2 条新字段（与 rec1 相同模板值，因为未 override）
        assert n2.get("fd_crypto_war_state") == "攻守兼备-中"
        assert abs(float(n2.get("fd_crypto_total_score") or 0) - 76.5) < 1e-6
        assert n2.get("sal_gate") is True

        storage_new._conn.close()
