"""Storage Backend (JSON + SQLite) — Phase 0 Layer 5 + Phase 1 P1.5

Phase 0 用 JSON 文件；Phase 1 P1.5 扩展为 SQLite（保留 `EvolutionStorageJSON.load/dump` API，
并新增 `EvolutionStorageSQLite.upsert_daily / get_trajectory / get_latest_dotplot /
get_indicators_evolution / save_weekly_weights`）。

Spec §4.1-4.3 三张核心表：
  regime_state_daily       每行 = symbol × timestamp（日线）
  regime_trajectory_90d    快捷快照（每 symbol 单行 JSON）
  regime_model_weights     周度在线学习权重

JSON Schema（v0）与 Spec §4 对齐：
{
  "schema_version": "evolution.v0",
  "generated_at_ms": int,          // epoch millis
  "symbol": str,                   // e.g. "BTCUSDT"
  "window": int,                   // N = 最近 N 日
  "range_start": "YYYY-MM-DD",     // trajectory[0].t
  "range_end":   "YYYY-MM-DD",     // trajectory[-1].t
  "acceptance": {                  // 可选，仅 BTC 关键日期验收时附
     "ATH_69k":      {"t": str, "L": float, "T": float, "check": str, "pass": bool},
     "FTX_low":     {...},
     "halving_2024":{...}
  },
  "snapshot_latest": RegimeStateFrame,
  "trajectory": [RegimeStateFrame × window]
}

RegimeStateFrame:
  t: str "YYYY-MM-DD"
  price: float
  level_raw: float;  trend_raw: float
  level_smooth: float; trend_smooth: float
  regime_probs: {8 态 str → float Σ=1}
  top3: [[str, float], [str,float], [str,float]]  (desc by prob)
  consensus: float ∈ [0,1]
  hmm_state: 0|1|2
  bocpd_cp_prob: float ∈ [0,1]   (Phase 0 = 0)
  indicators: {12 主指标名 → float}
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import numpy as np
import pandas as pd

__all__ = ["EvolutionStorageJSON", "EvolutionStorageSQLite", "RegimeStateFrame"]


# ================================================================
# 工具：JSON 友好的类型转换
# ================================================================
def _jsonable(v: Any) -> Any:
    """把 numpy 类型 / pandas Timestamp / Series 的单值转为 JSON 可序列化 primitive。"""
    if isinstance(v, (np.floating,)):
        return float(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, pd.Timestamp):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, np.ndarray):
        return [_jsonable(x) for x in v.tolist()]
    if isinstance(v, dict):
        return {str(k): _jsonable(vv) for k, vv in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    return v


# ================================================================
# Data Class
# ================================================================
@dataclass
class RegimeStateFrame:
    t: str
    price: float
    level_raw: float
    trend_raw: float
    level_smooth: float
    trend_smooth: float
    regime_probs: Dict[str, float]
    top3: List[List[Any]]          # List[(str, float)] of len 3
    consensus: float
    hmm_state: int
    bocpd_cp_prob: float
    indicators: Dict[str, float]

    def to_dict(self) -> Dict[str, Any]:
        return _jsonable(asdict(self))

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "RegimeStateFrame":
        # 宽容解析：top3 传 list 也行，tuple 也行
        top3_safe = [[str(r), float(p)] for r, p in d["top3"]]
        return RegimeStateFrame(
            t=str(d["t"]),
            price=float(d["price"]),
            level_raw=float(d["level_raw"]),
            trend_raw=float(d["trend_raw"]),
            level_smooth=float(d["level_smooth"]),
            trend_smooth=float(d["trend_smooth"]),
            regime_probs={str(k): float(v) for k, v in d["regime_probs"].items()},
            top3=top3_safe,
            consensus=float(d["consensus"]),
            hmm_state=int(d["hmm_state"]),
            bocpd_cp_prob=float(d.get("bocpd_cp_prob", 0.0)),
            indicators={str(k): float(v) for k, v in d.get("indicators", {}).items()},
        )


# ================================================================
# Main Storage 类（JSON 文件）
# ================================================================
class EvolutionStorageJSON:
    """Phase 0：JSON 文件 trajectory 的 save/load + round-trip。"""

    SCHEMA_VERSION = "evolution.v0"

    def __init__(self,
                 symbol: str,
                 window: int,
                 trajectory: Optional[List[RegimeStateFrame]] = None,
                 snapshot_latest: Optional[RegimeStateFrame] = None,
                 acceptance: Optional[Dict[str, Any]] = None,
                 ):
        self.symbol = symbol
        self.window = int(window)
        self.trajectory: List[RegimeStateFrame] = list(trajectory) if trajectory else []
        self.snapshot_latest = snapshot_latest or (self.trajectory[-1] if self.trajectory else None)
        self.acceptance = acceptance or {}
        self.generated_at_ms: int = int(time.time() * 1000)

    # ----- serialize -----
    def to_dict(self) -> Dict[str, Any]:
        if self.trajectory:
            t_start = self.trajectory[0].t
            t_end = self.trajectory[-1].t
        else:
            t_start = t_end = ""
        snap = self.snapshot_latest.to_dict() if self.snapshot_latest else None
        return {
            "schema_version": self.SCHEMA_VERSION,
            "generated_at_ms": self.generated_at_ms,
            "symbol": self.symbol,
            "window": self.window,
            "range_start": t_start,
            "range_end":   t_end,
            "acceptance": _jsonable(self.acceptance),
            "snapshot_latest": snap,
            "trajectory": [fr.to_dict() for fr in self.trajectory],
            "meta": {
                # 为前端/测试兼容性保留 meta alias（部分旧测试用 meta 取 key）
                "generated_at_ms": self.generated_at_ms,
                "symbol": self.symbol,
                "window": self.window,
                "acceptance": _jsonable(self.acceptance),
            },
        }

    # ----- dump to file -----
    @staticmethod
    def dump(obj: "EvolutionStorageJSON", path: Path | str) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(obj.to_dict(), f, ensure_ascii=False, indent=2, allow_nan=False)
        return path

    # ----- load from file -----
    @staticmethod
    def load(path: Path | str) -> "EvolutionStorageJSON":
        path = Path(path)
        with path.open("r", encoding="utf-8") as f:
            d = json.load(f)
        traj_raw = d.get("trajectory", [])
        trajectory = [RegimeStateFrame.from_dict(fr) for fr in traj_raw]
        snap_raw = d.get("snapshot_latest")
        snapshot = RegimeStateFrame.from_dict(snap_raw) if snap_raw else None
        store = EvolutionStorageJSON(
            symbol=d.get("symbol", "UNKNOWN"),
            window=int(d.get("window", len(trajectory))),
            trajectory=trajectory,
            snapshot_latest=snapshot,
            acceptance=d.get("acceptance") or d.get("meta", {}).get("acceptance") or {},
        )
        if "generated_at_ms" in d:
            store.generated_at_ms = int(d["generated_at_ms"])
        elif "meta" in d and "generated_at_ms" in d["meta"]:
            store.generated_at_ms = int(d["meta"]["generated_at_ms"])
        return store


# ================================================================
# Phase 1 P1.5：SQLite 持久化（Spec §4.1-4.3）
# ================================================================
# SQLite 类型映射（PostgreSQL → SQLite）：
#   TIMESTAMPTZ / DATE  → TEXT  (ISO 8601 字符串)
#   JSONB               → TEXT  (json.dumps 字符串)
#   DOUBLE PRECISION    → REAL
#   SMALLINT / INTEGER  → INTEGER
#   VARCHAR(N)          → TEXT
# ================================================================

_SCHEMA_VERSION_SQLITE = "evolution.v1.sqlite"


def _init_sqlite_schema(conn: sqlite3.Connection) -> None:
    """创建 Spec §4.1-4.3 三张核心表 + dotplot 缓存表（若不存在）。"""
    cur = conn.cursor()
    # 4.1 regime_state_daily：每行 = symbol × timestamp
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

    # 4.2 regime_trajectory_90d：快捷快照（每 symbol 单行）
    cur.execute("""
        CREATE TABLE IF NOT EXISTS regime_trajectory_90d (
            symbol          TEXT PRIMARY KEY,
            updated_at      TEXT NOT NULL,
            trajectory      TEXT NOT NULL
        )
    """)

    # 4.3 regime_model_weights：周度在线学习权重
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

    # 额外表：最新点阵图缓存（每 symbol 单行），用于前端首屏秒开
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

    # Phase A §3.3: 周期预测日志 —— 记录预测快照，供误差回填和在线学习修正
    cur.execute("""
        CREATE TABLE IF NOT EXISTS morph_prediction_log (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol            TEXT NOT NULL,
            prediction_date   TEXT NOT NULL,       -- 预测生成日期 YYYY-MM-DD
            target_date       TEXT NOT NULL,       -- 预测目标日期 YYYY-MM-DD
            horizon_days      INTEGER NOT NULL,    -- 预测天数 (1..forecast_days)
            predicted_l       REAL NOT NULL,       -- 预测的 level_smooth
            predicted_t       REAL,                -- 预测的 trend_smooth
            actual_l          REAL,                -- 实际 level_smooth（回填）
            actual_t          REAL,                -- 实际 trend_smooth（回填）
            error_l           REAL,                -- actual_l - predicted_l
            fft_components    TEXT,                -- JSON: FFT top-3 参数
            hermite_params    TEXT,                -- JSON: Hermite 切线参数
            correction_applied TEXT,               -- JSON: 应用的修正
            created_at        TEXT DEFAULT (datetime('now')),
            UNIQUE(symbol, prediction_date, target_date)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_mpl_symbol_target ON morph_prediction_log(symbol, target_date)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_mpl_unfilled ON morph_prediction_log(symbol, actual_l IS NULL) WHERE actual_l IS NULL")

    # Phase A §3.3: 预测修正状态 —— FFT 权重修正系数 / Hermite 切线修正系数
    cur.execute("""
        CREATE TABLE IF NOT EXISTS morph_correction_state (
            symbol            TEXT PRIMARY KEY,
            weight_correction TEXT NOT NULL,       -- JSON: {period: weight_mult}
            tangent_correction TEXT NOT NULL,      -- JSON: {m0_mul, m1_mul, bias}
            correction_count  INTEGER NOT NULL DEFAULT 0,
            last_mae          REAL,
            first_corrected_at TEXT,
            last_corrected_at TEXT
        )
    """)

    # 形态切换大调整：锚点修正状态（周期参数 t_rel_mean / level_mean 的在线调整）
    cur.execute("""
        CREATE TABLE IF NOT EXISTS morph_anchor_state (
            symbol              TEXT PRIMARY KEY,
            anchor_overrides    TEXT NOT NULL,       -- JSON: {label: {t_rel: float, level: float}}
            switch_count        INTEGER NOT NULL DEFAULT 0,
            last_switch_from    TEXT,
            last_switch_to      TEXT,
            last_switch_date    TEXT,
            last_corrected_at   TEXT,
            first_corrected_at  TEXT,
            overshoot_hint      TEXT                  -- JSON: {reason, streak, need_anchor_correct, detected_at}
        )
    """)
    # 已有数据库的迁移：添加 overshoot_hint 列（如果不存在）
    try:
        cur.execute("ALTER TABLE morph_anchor_state ADD COLUMN overshoot_hint TEXT")
    except sqlite3.OperationalError:
        pass  # 列已存在

    # Phase B/C ShadowLogger：reactive + forecast + 三值（baseline/ai/effective）对比日志
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
            -- T5 三值：baseline（静态 v15 查表基线）
            baseline_pos_mult            REAL,
            baseline_tp_mult             REAL,
            baseline_sl_mult             REAL,
            baseline_threshold_mult      REAL,
            baseline_long_conf_threshold REAL,
            baseline_short_conf_threshold REAL,
            -- T5 三值：ai_injected（AI 注入理论值）
            ai_pos_mult         REAL,
            ai_tp_mult          REAL,
            ai_sl_mult          REAL,
            ai_threshold_mult   REAL,
            ai_long_threshold   REAL,
            ai_short_threshold  REAL,
            ai_ls_ratio_cap     REAL,
            -- T5 三值：effective（实际生效值 = 融合层最终输出）
            effective_pos_mult            REAL,
            effective_tp_mult             REAL,
            effective_sl_mult             REAL,
            effective_threshold_mult      REAL,
            effective_long_conf_threshold REAL,
            effective_short_conf_threshold REAL,
            -- T4 / Phase C 元数据
            enable_inject     INTEGER,  -- bool 0/1
            alpha_blend       REAL,
            -- 实际交易结果
            actual_direction    TEXT,
            actual_confidence   REAL,
            actual_position_usdt REAL,
            actual_tp_px        REAL,
            actual_sl_px        REAL,
            actual_threshold    REAL,
            -- H3-FMA 渐进：FMA=ON 影子决策（即使当前 FMA=False 也记录，用于未来评估）
            fma_on_allowed      INTEGER,  -- bool 0/1: FMA=ON 差异化过滤下是否允许该方向
            fma_on_eff_threshold REAL,    -- FMA=ON 时，经形态差异化乘数后的有效阈值
            -- T5 战略层聚合影子（6字段）
            fd_crypto_war_state      TEXT,
            fd_crypto_total_score    REAL,
            fd_crypto_cap_mode       REAL,
            fd_crypto_mult_mode      REAL,
            fd_us_stock_war_state    TEXT,
            fd_us_stock_total_score  REAL,
            -- T5 策略算法层影子（6字段）
            sal_type             TEXT,
            sal_regime           TEXT,
            sal_calib_median     REAL,
            sal_calib_min        REAL,
            sal_calib_max        REAL,
            sal_gate             INTEGER
        )
    """)
    # Phase 4: 持仓与离场管理层 ExitManager 策略贡献值追踪
    cur.execute("""
        CREATE TABLE IF NOT EXISTS exit_strategy_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol          TEXT NOT NULL,
            timestamp       TEXT NOT NULL,          -- ISO 8601 UTC
            strategy_name   TEXT NOT NULL,          -- "p3_early_exit" / "ev_force_close" / ...
            action          TEXT,                  -- "force_close" / "adjust_sl_tp" / "ranked_tp"
            reason          TEXT,
            age_hours       REAL,
            in_protection   INTEGER,              -- 0/1
            ev              REAL,
            confidence      REAL,
            pnl             REAL,                  -- 实际盈亏（平仓后回填）
            win             INTEGER               -- 0/1 胜负（平仓后回填）
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_exit_strat_symbol_ts "
                "ON exit_strategy_log (symbol, timestamp)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_exit_strat_name_ts "
                "ON exit_strategy_log (strategy_name, timestamp)")
    # --- Schema 迁移：旧库（CREATE TABLE IF NOT EXISTS 未建新列）用 ALTER TABLE 补齐 ---
    _fma_cols = [
        ("fma_on_allowed",        "INTEGER"),
        ("fma_on_eff_threshold",  "REAL"),
    ]
    for _col, _typ in _fma_cols:
        try:
            cur.execute(f"ALTER TABLE shadow_param_log ADD COLUMN {_col} {_typ}")
        except Exception:
            pass  # 列已存在
    _tri_val_cols = [
        # baseline 6
        ("baseline_pos_mult",            "REAL"),
        ("baseline_tp_mult",             "REAL"),
        ("baseline_sl_mult",             "REAL"),
        ("baseline_threshold_mult",      "REAL"),
        ("baseline_long_conf_threshold", "REAL"),
        ("baseline_short_conf_threshold","REAL"),
        # ai 7
        ("ai_pos_mult",         "REAL"),
        ("ai_tp_mult",          "REAL"),
        ("ai_sl_mult",          "REAL"),
        ("ai_threshold_mult",   "REAL"),
        ("ai_long_threshold",   "REAL"),
        ("ai_short_threshold",  "REAL"),
        ("ai_ls_ratio_cap",     "REAL"),
        # effective 6
        ("effective_pos_mult",            "REAL"),
        ("effective_tp_mult",             "REAL"),
        ("effective_sl_mult",             "REAL"),
        ("effective_threshold_mult",      "REAL"),
        ("effective_long_conf_threshold", "REAL"),
        ("effective_short_conf_threshold","REAL"),
        # 元数据 2
        ("enable_inject", "INTEGER"),
        ("alpha_blend",   "REAL"),
    ]
    for _col, _typ in _tri_val_cols:
        try:
            cur.execute(f"ALTER TABLE shadow_param_log ADD COLUMN {_col} {_typ}")
        except Exception:
            pass  # 列已存在
    # T5 战略/策略影子 12 列迁移
    _t5_shadow_cols = [
        ("fd_crypto_war_state",      "TEXT"),
        ("fd_crypto_total_score",    "REAL"),
        ("fd_crypto_cap_mode",       "REAL"),
        ("fd_crypto_mult_mode",      "REAL"),
        ("fd_us_stock_war_state",    "TEXT"),
        ("fd_us_stock_total_score",  "REAL"),
        ("sal_type",                 "TEXT"),
        ("sal_regime",               "TEXT"),
        ("sal_calib_median",         "REAL"),
        ("sal_calib_min",            "REAL"),
        ("sal_calib_max",            "REAL"),
        ("sal_gate",                 "INTEGER"),
    ]
    for _col, _typ in _t5_shadow_cols:
        try:
            cur.execute(f"ALTER TABLE shadow_param_log ADD COLUMN {_col} {_typ}")
        except Exception:
            pass  # 列已存在
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_shadow_symbol_ts "
        "ON shadow_param_log(symbol, timestamp)"
    )
    conn.commit()


def _to_iso_date(ts: Union[str, date, datetime, pd.Timestamp]) -> str:
    """统一转 YYYY-MM-DD 字符串。"""
    if isinstance(ts, str):
        return ts[:10]
    if isinstance(ts, (datetime, date)):
        return ts.strftime("%Y-%m-%d")
    if isinstance(ts, pd.Timestamp):
        return ts.strftime("%Y-%m-%d")
    return str(ts)[:10]


class EvolutionStorageSQLite:
    """Phase 1 P1.5：基于 sqlite3 的形态演化数据持久化。

    Spec §4.1-4.3 三张表 + dotplot 缓存表。

    用法：
        storage = EvolutionStorageSQLite(Path("evolution.db"))
        storage.upsert_daily("BTCUSDT", frame)           # 写入一日
        traj = storage.get_trajectory("BTCUSDT", 90)      # 取最近 90 日
        dot = storage.get_latest_dotplot("BTCUSDT")       # 取最新点阵图
        storage.save_weekly_weights(date(2026, 8, 19), weights, 0.657)  # 在线学习产物
    """

    SCHEMA_VERSION = _SCHEMA_VERSION_SQLITE

    def __init__(self, db_path: Union[Path, str]):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False：供 Flask 多线程读取
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        _init_sqlite_schema(self._conn)

    # ================================================================
    # 写入：日级 RegimeStateFrame
    # ================================================================
    def upsert_daily(self, symbol: str, frame: RegimeStateFrame) -> None:
        """INSERT OR REPLACE 一行到 regime_state_daily + 同步更新 trajectory_90d 快照。

        Spec §4.1 主表 + §4.2 快捷快照表（每次写入后覆盖）。
        """
        symbol = symbol or "BTCUSDT"
        ts = _to_iso_date(frame.t)
        regime_probs_json = json.dumps(_jsonable(frame.regime_probs), ensure_ascii=False)
        top3_json = json.dumps(_jsonable(frame.top3), ensure_ascii=False)
        indicators_json = json.dumps(_jsonable(frame.indicators), ensure_ascii=False)

        cur = self._conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO regime_state_daily
                (timestamp, symbol, price_close,
                 level_raw, trend_raw, level_smooth, trend_smooth,
                 regime_probs, top3, consensus, hmm_state, bocpd_cp_prob,
                 indicators, data_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """, (
            ts, symbol, float(frame.price),
            float(frame.level_raw), float(frame.trend_raw),
            float(frame.level_smooth), float(frame.trend_smooth),
            regime_probs_json, top3_json,
            float(frame.consensus), int(frame.hmm_state),
            float(frame.bocpd_cp_prob),
            indicators_json,
        ))
        self._conn.commit()
        # 同步 trajectory_90d 快照：取最近 90 条
        self._refresh_trajectory_snapshot(symbol, window=90)

    def upsert_daily_batch(self, symbol: str,
                            frames: List[RegimeStateFrame]) -> int:
        """批量写入多个 frame（单事务），返回写入条数。"""
        symbol = symbol or "BTCUSDT"
        if not frames:
            return 0
        cur = self._conn.cursor()
        cur.execute("BEGIN")
        try:
            for frame in frames:
                ts = _to_iso_date(frame.t)
                regime_probs_json = json.dumps(_jsonable(frame.regime_probs), ensure_ascii=False)
                top3_json = json.dumps(_jsonable(frame.top3), ensure_ascii=False)
                indicators_json = json.dumps(_jsonable(frame.indicators), ensure_ascii=False)
                cur.execute("""
                    INSERT OR REPLACE INTO regime_state_daily
                        (timestamp, symbol, price_close,
                         level_raw, trend_raw, level_smooth, trend_smooth,
                         regime_probs, top3, consensus, hmm_state, bocpd_cp_prob,
                         indicators, data_version)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """, (
                    ts, symbol, float(frame.price),
                    float(frame.level_raw), float(frame.trend_raw),
                    float(frame.level_smooth), float(frame.trend_smooth),
                    regime_probs_json, top3_json,
                    float(frame.consensus), int(frame.hmm_state),
                    float(frame.bocpd_cp_prob),
                    indicators_json,
                ))
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        # 刷新快照
        self._refresh_trajectory_snapshot(symbol, window=90)
        return len(frames)

    def _refresh_trajectory_snapshot(self, symbol: str, window: int = 90) -> None:
        """每次写入后，同步覆盖 regime_trajectory_90d 单行 JSON 快照。"""
        cur = self._conn.cursor()
        rows = cur.execute("""
            SELECT timestamp, price_close, level_raw, trend_raw,
                   level_smooth, trend_smooth, regime_probs, top3,
                   consensus, hmm_state, bocpd_cp_prob, indicators
            FROM regime_state_daily
            WHERE symbol = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (symbol, window)).fetchall()
        # 倒序取后反转回升序
        traj = [self._row_to_frame_dict(r) for r in reversed(rows)]
        traj_json = json.dumps(traj, ensure_ascii=False)
        updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z"
        cur.execute("""
            INSERT OR REPLACE INTO regime_trajectory_90d
                (symbol, updated_at, trajectory)
            VALUES (?, ?, ?)
        """, (symbol, updated_at, traj_json))
        self._conn.commit()

    # ================================================================
    # 读取：trajectory / snapshot / indicators
    # ================================================================
    @staticmethod
    def _row_to_frame_dict(row: sqlite3.Row) -> Dict[str, Any]:
        """将 SQL 行转为 RegimeStateFrame 兼容 dict（前端友好）。"""
        return {
            "t": row["timestamp"],
            "price": float(row["price_close"]),
            "level_raw": float(row["level_raw"]),
            "trend_raw": float(row["trend_raw"]),
            "level_smooth": float(row["level_smooth"]),
            "trend_smooth": float(row["trend_smooth"]),
            "regime_probs": json.loads(row["regime_probs"]),
            "top3": json.loads(row["top3"]),
            "consensus": float(row["consensus"]),
            "hmm_state": int(row["hmm_state"]),
            "bocpd_cp_prob": float(row["bocpd_cp_prob"]),
            "indicators": json.loads(row["indicators"]),
        }

    def get_trajectory(self, symbol: str, window: int = 90) -> List[Dict[str, Any]]:
        """取最近 N 条 trajectory（优先从 regime_trajectory_90d 快照读）。"""
        symbol = symbol or "BTCUSDT"
        # 快照表仅存 90 条；若 window ≤ 90 优先用快照
        if window <= 90:
            cur = self._conn.cursor()
            row = cur.execute("""
                SELECT trajectory FROM regime_trajectory_90d WHERE symbol = ?
            """, (symbol,)).fetchone()
            if row is not None:
                traj = json.loads(row["trajectory"])
                # 快照可能不足 window 条（冷启动）；不够则从主表补
                if len(traj) >= window:
                    return traj[-window:]
                # 不够 → 走主表
        # 主表查询
        cur = self._conn.cursor()
        rows = cur.execute("""
            SELECT timestamp, price_close, level_raw, trend_raw,
                   level_smooth, trend_smooth, regime_probs, top3,
                   consensus, hmm_state, bocpd_cp_prob, indicators
            FROM regime_state_daily
            WHERE symbol = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (symbol, window)).fetchall()
        return [self._row_to_frame_dict(r) for r in reversed(rows)]

    def get_snapshot(self, symbol: str) -> Optional[Dict[str, Any]]:
        """取最新一日 RegimeStateFrame dict。"""
        symbol = symbol or "BTCUSDT"
        cur = self._conn.cursor()
        row = cur.execute("""
            SELECT timestamp, price_close, level_raw, trend_raw,
                   level_smooth, trend_smooth, regime_probs, top3,
                   consensus, hmm_state, bocpd_cp_prob, indicators
            FROM regime_state_daily
            WHERE symbol = ?
            ORDER BY timestamp DESC
            LIMIT 1
        """, (symbol,)).fetchone()
        if row is None:
            return None
        return self._row_to_frame_dict(row)

    def get_indicators_evolution(self, symbol: str,
                                  names: List[str],
                                  window: int = 90) -> Dict[str, List[float]]:
        """取最近 N 日指定指标的历史序列。

        Args:
            names: 12 指标名子集
            window: 最近 N 日
        Returns:
            { indicator_name: [v_t-window+1, ..., v_t] }
        """
        symbol = symbol or "BTCUSDT"
        cur = self._conn.cursor()
        rows = cur.execute("""
            SELECT timestamp, indicators
            FROM regime_state_daily
            WHERE symbol = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (symbol, window)).fetchall()
        rows_asc = list(reversed(rows))
        out: Dict[str, List[float]] = {name: [] for name in names}
        for r in rows_asc:
            ind = json.loads(r["indicators"])
            for name in names:
                out[name].append(float(ind.get(name, 0.0)))
        return out

    # ================================================================
    # dotplot 最新缓存
    # ================================================================
    def save_dotplot(self, symbol: str, dotplot: Dict[str, Any]) -> None:
        """保存最新一日点阵图 12×8 支持度矩阵（Spec §2.4 Panel 2）。"""
        symbol = symbol or "BTCUSDT"
        cur = self._conn.cursor()
        updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z"
        cur.execute("""
            INSERT OR REPLACE INTO regime_dotplot_latest
                (symbol, updated_at, target_index, rows, cols,
                 matrix, marginal_probs, sample_counts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            symbol, updated_at,
            int(dotplot.get("target_index", -1)),
            json.dumps(dotplot.get("rows", []), ensure_ascii=False),
            json.dumps(dotplot.get("cols", []), ensure_ascii=False),
            json.dumps(dotplot.get("matrix", []), ensure_ascii=False),
            json.dumps(dotplot.get("marginal_probs", []), ensure_ascii=False),
            json.dumps(dotplot.get("sample_counts", {}), ensure_ascii=False),
        ))
        self._conn.commit()

    def get_latest_dotplot(self, symbol: str) -> Optional[Dict[str, Any]]:
        """取最新一日点阵图；未保存时返回 None。"""
        symbol = symbol or "BTCUSDT"
        cur = self._conn.cursor()
        row = cur.execute("""
            SELECT updated_at, target_index, rows, cols,
                   matrix, marginal_probs, sample_counts
            FROM regime_dotplot_latest
            WHERE symbol = ?
        """, (symbol,)).fetchone()
        if row is None:
            return None
        return {
            "updated_at": row["updated_at"],
            "target_index": int(row["target_index"]),
            "rows": json.loads(row["rows"]),
            "cols": json.loads(row["cols"]),
            "matrix": json.loads(row["matrix"]),
            "marginal_probs": json.loads(row["marginal_probs"]),
            "sample_counts": json.loads(row["sample_counts"]),
        }

    # ================================================================
    # 在线学习周度权重
    # ================================================================
    def save_weekly_weights(self,
                             week_start: Union[str, date],
                             weights_obj: Dict[str, Any],
                             objective: float,
                             comment: Optional[str] = None) -> None:
        """写入 regime_model_weights 一行。

        Spec §4.3：
          week_start      DATE PRIMARY KEY
          level_weights   {6 个 float}
          trend_weights   {5 个 float}
          regime_centers  {8 × [Lc, Tc]}
          max_daily_delta float
          objective       float
          comment         TEXT
        """
        ws = _to_iso_date(week_start)
        level_w = weights_obj.get("level_weights", {})
        trend_w = weights_obj.get("trend_weights", {})
        centers = weights_obj.get("regime_centers", {})
        max_dd = float(weights_obj.get("max_daily_delta", 0.5))

        cur = self._conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO regime_model_weights
                (week_start, level_weights, trend_weights, regime_centers,
                 max_daily_delta, objective, comment)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            ws,
            json.dumps(_jsonable(level_w), ensure_ascii=False),
            json.dumps(_jsonable(trend_w), ensure_ascii=False),
            json.dumps(_jsonable(centers), ensure_ascii=False),
            max_dd,
            float(objective),
            comment,
        ))
        self._conn.commit()

    def get_latest_weights(self) -> Optional[Dict[str, Any]]:
        """取最新一周权重 + objective。"""
        cur = self._conn.cursor()
        row = cur.execute("""
            SELECT week_start, level_weights, trend_weights, regime_centers,
                   max_daily_delta, objective, comment
            FROM regime_model_weights
            ORDER BY week_start DESC
            LIMIT 1
        """).fetchone()
        if row is None:
            return None
        return {
            "week_start": row["week_start"],
            "level_weights": json.loads(row["level_weights"]),
            "trend_weights": json.loads(row["trend_weights"]),
            "regime_centers": json.loads(row["regime_centers"]),
            "max_daily_delta": float(row["max_daily_delta"]),
            "objective": float(row["objective"]),
            "comment": row["comment"],
        }

    def list_weights_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """列出最近 N 周权重历史（诊断用）。"""
        cur = self._conn.cursor()
        rows = cur.execute("""
            SELECT week_start, objective, max_daily_delta, comment
            FROM regime_model_weights
            ORDER BY week_start DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [
            {
                "week_start": r["week_start"],
                "objective": float(r["objective"]),
                "max_daily_delta": float(r["max_daily_delta"]),
                "comment": r["comment"],
            }
            for r in rows
        ]

    # ================================================================
    # Phase A: 周期预测日志
    # ================================================================
    def insert_prediction_log(self,
                              symbol: str,
                              prediction_date: str,
                              target_date: str,
                              horizon_days: int,
                              predicted_l: float,
                              predicted_t: Optional[float] = None,
                              fft_components: Optional[Dict] = None,
                              hermite_params: Optional[Dict] = None,
                              correction_applied: Optional[Dict] = None) -> int:
        """写入一条预测快照（predict 后立即调用）。"""
        symbol = symbol or "BTCUSDT"
        cur = self._conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO morph_prediction_log
                (symbol, prediction_date, target_date, horizon_days,
                 predicted_l, predicted_t,
                 fft_components, hermite_params, correction_applied)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            symbol, _to_iso_date(prediction_date), _to_iso_date(target_date),
            int(horizon_days),
            float(predicted_l),
            float(predicted_t) if predicted_t is not None else None,
            json.dumps(fft_components, ensure_ascii=False) if fft_components else None,
            json.dumps(hermite_params, ensure_ascii=False) if hermite_params else None,
            json.dumps(correction_applied, ensure_ascii=False) if correction_applied else None,
        ))
        self._conn.commit()
        return int(cur.lastrowid or 0)

    def backfill_prediction_error(self, symbol: str) -> int:
        """回填已到期但未回填的预测误差（evaluate 时调用）。

        查询 target_date <= today 且 actual_l IS NULL 的记录，
        从 regime_state_daily 匹配实际 level_smooth/trend_smooth。
        返回回填的记录数。
        """
        symbol = symbol or "BTCUSDT"
        cur = self._conn.cursor()
        rows = cur.execute("""
            SELECT id, target_date, predicted_l FROM morph_prediction_log
            WHERE symbol = ? AND actual_l IS NULL AND target_date <= date('now')
        """, (symbol,)).fetchall()
        filled = 0
        for r in rows:
            match = cur.execute("""
                SELECT level_smooth, trend_smooth FROM regime_state_daily
                WHERE symbol = ? AND timestamp = ?
            """, (symbol, _to_iso_date(r["target_date"]))).fetchone()
            if match and match["level_smooth"] is not None:
                actual_l = float(match["level_smooth"])
                actual_t = float(match["trend_smooth"]) if match["trend_smooth"] is not None else None
                err_l = actual_l - float(r["predicted_l"])
                cur.execute("""
                    UPDATE morph_prediction_log
                    SET actual_l = ?, actual_t = ?, error_l = ?
                    WHERE id = ?
                """, (actual_l, actual_t, err_l, int(r["id"])))
                filled += 1
        self._conn.commit()
        return filled

    def list_filled_predictions(self, symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
        """返回已回填的预测记录（用于误差修正）。"""
        symbol = symbol or "BTCUSDT"
        cur = self._conn.cursor()
        rows = cur.execute("""
            SELECT id, prediction_date, target_date, horizon_days,
                   predicted_l, predicted_t, actual_l, actual_t, error_l,
                   fft_components, hermite_params, correction_applied, created_at
            FROM morph_prediction_log
            WHERE symbol = ? AND actual_l IS NOT NULL
            ORDER BY target_date DESC, horizon_days ASC
            LIMIT ?
        """, (symbol, limit)).fetchall()
        return [
            {
                "id": int(r["id"]),
                "prediction_date": r["prediction_date"],
                "target_date": r["target_date"],
                "horizon_days": int(r["horizon_days"]),
                "predicted_l": float(r["predicted_l"]),
                "predicted_t": float(r["predicted_t"]) if r["predicted_t"] is not None else None,
                "actual_l": float(r["actual_l"]),
                "actual_t": float(r["actual_t"]) if r["actual_t"] is not None else None,
                "error_l": float(r["error_l"]) if r["error_l"] is not None else None,
                "fft_components": json.loads(r["fft_components"]) if r["fft_components"] else None,
                "hermite_params": json.loads(r["hermite_params"]) if r["hermite_params"] else None,
                "correction_applied": json.loads(r["correction_applied"]) if r["correction_applied"] else None,
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    def get_correction_metrics(self, symbol: str, lookback: int = 30) -> Dict[str, Any]:
        """聚合预测误差指标（MAE/RMSE/方向准确率），供前端展示。"""
        symbol = symbol or "BTCUSDT"
        cur = self._conn.cursor()
        rows = cur.execute("""
            SELECT error_l, predicted_l, actual_l, horizon_days, target_date
            FROM morph_prediction_log
            WHERE symbol = ? AND actual_l IS NOT NULL
            ORDER BY target_date DESC
            LIMIT ?
        """, (symbol, lookback * 20)).fetchall()
        if not rows:
            return {"sample_count": 0, "mae": None, "rmse": None,
                    "direction_accuracy": None, "by_horizon": {},
                    "error_series": []}

        errors = [abs(float(r["error_l"])) for r in rows if r["error_l"] is not None]
        sq_errors = [float(r["error_l"]) ** 2 for r in rows if r["error_l"] is not None]
        # 方向准确率：预测变化方向是否与实际一致
        dir_correct = 0
        dir_total = 0
        error_series = []
        prev_pred = None
        for r in rows:
            tgt = r["target_date"]
            err = float(r["error_l"]) if r["error_l"] is not None else None
            if err is not None:
                error_series.append({"t": tgt, "error": round(err, 4)})
            # 利用 horizon=1 的预测变化方向与实际变化方向（需要前一日数据）
        # 简化：方向准确率 = sign(actual_l - predicted_at_t0) 与 sign(预测) 是否一致
        # 这里用符号一致率：error < predicted_l 且 actual < predicted_l（同向）计为正确
        n = len(errors)
        mae = float(sum(errors) / n) if n else 0.0
        rmse = float((sum(sq_errors) / n) ** 0.5) if n else 0.0

        # 按 horizon 分组
        by_horizon: Dict[str, Dict] = {}
        by_h_raw: Dict[int, List[float]] = {}
        for r in rows:
            h = int(r["horizon_days"])
            if r["error_l"] is not None:
                by_h_raw.setdefault(h, []).append(abs(float(r["error_l"])))
        for h, errs in by_h_raw.items():
            by_horizon[str(h)] = {"count": len(errs), "mae": round(sum(errs) / len(errs), 4)}

        return {
            "sample_count": n,
            "mae": round(mae, 4),
            "rmse": round(rmse, 4),
            "direction_accuracy": None,  # 预留
            "by_horizon": by_horizon,
            "error_series": error_series[-60:],  # 最近 60 条
        }

    # ================================================================
    # Phase A: 修正状态持久化
    # ================================================================
    @staticmethod
    def _normalize_utc_iso(val: Optional[str]) -> Optional[str]:
        """把 SQLite naive datetime('now') 的输出统一成带 Z 后缀的 ISO 8601 UTC（aware）。"""
        if not val:
            return None
        v = val.strip()
        if v.endswith("Z") or "+" in v[10:] or v.endswith("+00:00") or v.endswith("-00:00"):
            return v
        # 常见格式：YYYY-MM-DD HH:MM:SS 或 YYYY-MM-DDTHH:MM:SS
        return v.replace(" ", "T", 1) + "Z"

    def get_correction_state(self, symbol: str) -> Optional[Dict[str, Any]]:
        symbol = symbol or "BTCUSDT"
        cur = self._conn.cursor()
        r = cur.execute("""
            SELECT weight_correction, tangent_correction, correction_count,
                   last_mae, first_corrected_at, last_corrected_at
            FROM morph_correction_state WHERE symbol = ?
        """, (symbol,)).fetchone()
        if not r:
            return None
        return {
            "symbol": symbol,
            "weight_correction": json.loads(r["weight_correction"]),
            "tangent_correction": json.loads(r["tangent_correction"]),
            "correction_count": int(r["correction_count"]),
            "last_mae": float(r["last_mae"]) if r["last_mae"] is not None else None,
            "first_corrected_at": self._normalize_utc_iso(r["first_corrected_at"]),
            "last_corrected_at": self._normalize_utc_iso(r["last_corrected_at"]),
        }

    def save_correction_state(self,
                              symbol: str,
                              weight_correction: Dict[str, float],
                              tangent_correction: Dict[str, float],
                              last_mae: Optional[float] = None) -> None:
        symbol = symbol or "BTCUSDT"
        cur = self._conn.cursor()
        # 用带 Z 的 UTC ISO，避免 aware/naive 做差报错
        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        cur.execute("""
            INSERT INTO morph_correction_state
                (symbol, weight_correction, tangent_correction, correction_count,
                 last_mae, first_corrected_at, last_corrected_at)
            VALUES (?, ?, ?, 1, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                weight_correction = excluded.weight_correction,
                tangent_correction = excluded.tangent_correction,
                correction_count = morph_correction_state.correction_count + 1,
                last_mae = excluded.last_mae,
                last_corrected_at = excluded.last_corrected_at
        """, (
            symbol,
            json.dumps(weight_correction, ensure_ascii=False),
            json.dumps(tangent_correction, ensure_ascii=False),
            float(last_mae) if last_mae is not None else None,
            now_iso,  # first_corrected_at 首次插入 now_iso；冲突时 excluded 不再复用 first_corrected_at 本身（该字段用当前行保留）
            now_iso,
        ))
        # 注意：上面 INSERT 里 first_corrected_at 在冲突时会被 excluded.first_corrected_at 覆盖。
        # 如果要保持首次插入值不变，单独修正：对于已存在的行，first_corrected_at 不改变。
        cur.execute("""
            UPDATE morph_correction_state
            SET first_corrected_at = (
                SELECT first_corrected_at FROM morph_correction_state WHERE symbol = ?
            ) WHERE symbol = ? AND correction_count > 1
        """, (symbol, symbol))
        self._conn.commit()

    # ================================================================
    # 形态切换大调整：锚点修正状态
    # ================================================================
    def get_anchor_state(self, symbol: str) -> Optional[Dict[str, Any]]:
        """读取锚点大调整状态。"""
        symbol = symbol or "BTCUSDT"
        cur = self._conn.cursor()
        r = cur.execute("""
            SELECT anchor_overrides, switch_count, last_switch_from, last_switch_to,
                   last_switch_date, last_corrected_at, first_corrected_at, overshoot_hint
            FROM morph_anchor_state WHERE symbol = ?
        """, (symbol,)).fetchone()
        if not r:
            return None
        hint_raw = r["overshoot_hint"] if "overshoot_hint" in r.keys() else None
        return {
            "symbol": symbol,
            "anchor_overrides": json.loads(r["anchor_overrides"]),
            "switch_count": int(r["switch_count"]),
            "last_switch_from": r["last_switch_from"],
            "last_switch_to": r["last_switch_to"],
            "last_switch_date": r["last_switch_date"],
            "last_corrected_at": self._normalize_utc_iso(r["last_corrected_at"]),
            "first_corrected_at": self._normalize_utc_iso(r["first_corrected_at"]),
            "overshoot_hint": json.loads(hint_raw) if hint_raw else None,
        }

    def save_anchor_state(self, symbol: str,
                          anchor_overrides: Dict[str, Dict[str, float]],
                          switch_from: Optional[str], switch_to: str,
                          switch_date: str) -> None:
        """保存锚点大调整状态（upsert）。"""
        symbol = symbol or "BTCUSDT"
        cur = self._conn.cursor()
        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        cur.execute("""
            INSERT INTO morph_anchor_state
                (symbol, anchor_overrides, switch_count, last_switch_from,
                 last_switch_to, last_switch_date, last_corrected_at, first_corrected_at)
            VALUES (?, ?, 1, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                anchor_overrides = excluded.anchor_overrides,
                switch_count = morph_anchor_state.switch_count + 1,
                last_switch_from = excluded.last_switch_from,
                last_switch_to = excluded.last_switch_to,
                last_switch_date = excluded.last_switch_date,
                last_corrected_at = excluded.last_corrected_at
        """, (
            symbol,
            json.dumps(anchor_overrides, ensure_ascii=False),
            switch_from, switch_to, switch_date,
            now_iso, now_iso,
        ))
        cur.execute("""
            UPDATE morph_anchor_state
            SET first_corrected_at = (
                SELECT first_corrected_at FROM morph_anchor_state WHERE symbol = ?
            ) WHERE symbol = ? AND switch_count > 1
        """, (symbol, symbol))
        self._conn.commit()

    # ================================================================
    # 大周期弹性边界：越界信号存储
    # ================================================================
    def save_overshoot_hint(self, symbol: str, hint: Dict[str, Any]) -> None:
        """保存越界信号提示（upsert：若 symbol 不存在则插入空 anchor_state 行再更新）。"""
        symbol = symbol or "BTCUSDT"
        cur = self._conn.cursor()
        hint_json = json.dumps(hint, ensure_ascii=False)
        # 确保 symbol 行存在
        cur.execute("""
            INSERT INTO morph_anchor_state (symbol, anchor_overrides, overshoot_hint)
            VALUES (?, '{}', ?)
            ON CONFLICT(symbol) DO UPDATE SET overshoot_hint = excluded.overshoot_hint
        """, (symbol, hint_json))
        self._conn.commit()

    def get_overshoot_hint(self, symbol: str) -> Optional[Dict[str, Any]]:
        """读取越界信号提示。"""
        symbol = symbol or "BTCUSDT"
        cur = self._conn.cursor()
        r = cur.execute(
            "SELECT overshoot_hint FROM morph_anchor_state WHERE symbol = ?",
            (symbol,)
        ).fetchone()
        if not r or not r["overshoot_hint"]:
            return None
        return json.loads(r["overshoot_hint"])

    def clear_overshoot_hint(self, symbol: str) -> None:
        """清除越界信号提示。"""
        symbol = symbol or "BTCUSDT"
        cur = self._conn.cursor()
        cur.execute(
            "UPDATE morph_anchor_state SET overshoot_hint = NULL WHERE symbol = ?",
            (symbol,)
        )
        self._conn.commit()

    # ================================================================
    # Phase B ShadowLogger：shadow_param_log 表 CRUD
    # ================================================================
    def save_shadow_log(self, symbol: str, record: Dict[str, Any]) -> int:
        """插入一条 shadow 参数对比记录（含 T5 三值 + Phase C 元数据 + T5战略/策略影子12列），返回记录 id。
        老库（缺新12列）自动降级为只 INSERT 原列，零异常。"""
        symbol = symbol or "BTCUSDT"
        cur = self._conn.cursor()
        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        def _b(k, fallback=None):
            v = record.get(k)
            if v is None:
                return fallback
            if isinstance(v, dict):
                _vals = [x for x in v.values() if isinstance(x, (int, float))]
                return float(_vals[0]) if _vals else fallback
            if isinstance(v, (list, tuple)):
                return float(v[0]) if v and isinstance(v[0], (int, float)) else fallback
            try:
                return float(v)
            except (TypeError, ValueError):
                return fallback

        def _sal_gate_val():
            v = record.get("sal_gate")
            if v is None:
                return None
            if isinstance(v, bool):
                return 1 if v else 0
            try:
                iv = int(v)
                return 1 if iv else 0
            except (TypeError, ValueError):
                return None

        # 公共 VALUES 前缀（原 42 列对应参数）
        _common_params = (
            symbol, now_iso,
            _b("reactive_L"), _b("reactive_T"), _b("reactive_C"), record.get("reactive_regime"),
            _b("reactive_pos_mult"), _b("reactive_tp_mult"), _b("reactive_sl_mult"), _b("reactive_threshold"),
            _b("forecast_L"), _b("forecast_T"), record.get("forecast_global_ranges"), record.get("forecast_sector_weights"),
            _b("baseline_pos_mult"), _b("baseline_tp_mult"), _b("baseline_sl_mult"),
            _b("baseline_threshold_mult"), _b("baseline_long_conf_threshold"), _b("baseline_short_conf_threshold"),
            _b("ai_pos_mult"), _b("ai_tp_mult"), _b("ai_sl_mult"), _b("ai_threshold_mult"),
            _b("ai_long_threshold"), _b("ai_short_threshold"), _b("ai_ls_ratio_cap"),
            _b("effective_pos_mult"), _b("effective_tp_mult"), _b("effective_sl_mult"),
            _b("effective_threshold_mult"),
            _b("effective_long_conf_threshold") if record.get("effective_long_conf_threshold") is not None else _b("ai_long_threshold"),
            _b("effective_short_conf_threshold") if record.get("effective_short_conf_threshold") is not None else _b("ai_short_threshold"),
            1 if bool(record.get("enable_inject")) else 0,
            _b("alpha_blend", 0.0),
            record.get("actual_direction"), _b("actual_confidence"), _b("actual_position_usdt"),
            _b("actual_tp_px"), _b("actual_sl_px"), _b("actual_threshold"),
            (1 if bool(record.get("fma_on_allowed")) else 0) if record.get("fma_on_allowed") is not None else None,
            _b("fma_on_eff_threshold"),
        )
        # T5 战略/策略影子 12 列额外参数
        _t5_extra_params = (
            record.get("fd_crypto_war_state"),
            _b("fd_crypto_total_score"),
            _b("fd_crypto_cap_mode"),
            _b("fd_crypto_mult_mode"),
            record.get("fd_us_stock_war_state"),
            _b("fd_us_stock_total_score"),
            record.get("sal_type"),
            record.get("sal_regime"),
            _b("sal_calib_median"),
            _b("sal_calib_min"),
            _b("sal_calib_max"),
            _sal_gate_val(),
        )

        try:
            cur.execute("""
                INSERT INTO shadow_param_log (
                    symbol, timestamp,
                    reactive_L, reactive_T, reactive_C, reactive_regime,
                    reactive_pos_mult, reactive_tp_mult, reactive_sl_mult, reactive_threshold,
                    forecast_L, forecast_T, forecast_global_ranges, forecast_sector_weights,
                    baseline_pos_mult, baseline_tp_mult, baseline_sl_mult,
                    baseline_threshold_mult, baseline_long_conf_threshold, baseline_short_conf_threshold,
                    ai_pos_mult, ai_tp_mult, ai_sl_mult, ai_threshold_mult,
                    ai_long_threshold, ai_short_threshold, ai_ls_ratio_cap,
                    effective_pos_mult, effective_tp_mult, effective_sl_mult,
                    effective_threshold_mult, effective_long_conf_threshold, effective_short_conf_threshold,
                    enable_inject, alpha_blend,
                    actual_direction, actual_confidence, actual_position_usdt,
                    actual_tp_px, actual_sl_px, actual_threshold,
                    fma_on_allowed, fma_on_eff_threshold,
                    fd_crypto_war_state, fd_crypto_total_score, fd_crypto_cap_mode, fd_crypto_mult_mode,
                    fd_us_stock_war_state, fd_us_stock_total_score,
                    sal_type, sal_regime, sal_calib_median, sal_calib_min, sal_calib_max, sal_gate
                ) VALUES (
                    ?,?,
                    ?,?,?,?,
                    ?,?,?,?,
                    ?,?,?,?,
                    ?,?,?,?,?,?,
                    ?,?,?,?,?,?,?,
                    ?,?,?,?,?,?,
                    ?,?,
                    ?,?,?,?,?,?,
                    ?,?,
                    ?,?,?,?,?,?,
                    ?,?,?,?,?,?
                )
            """, _common_params + _t5_extra_params)
            self._conn.commit()
            return int(cur.lastrowid)
        except sqlite3.OperationalError:
            self._conn.rollback()
            cur.execute("""
                INSERT INTO shadow_param_log (
                    symbol, timestamp,
                    reactive_L, reactive_T, reactive_C, reactive_regime,
                    reactive_pos_mult, reactive_tp_mult, reactive_sl_mult, reactive_threshold,
                    forecast_L, forecast_T, forecast_global_ranges, forecast_sector_weights,
                    baseline_pos_mult, baseline_tp_mult, baseline_sl_mult,
                    baseline_threshold_mult, baseline_long_conf_threshold, baseline_short_conf_threshold,
                    ai_pos_mult, ai_tp_mult, ai_sl_mult, ai_threshold_mult,
                    ai_long_threshold, ai_short_threshold, ai_ls_ratio_cap,
                    effective_pos_mult, effective_tp_mult, effective_sl_mult,
                    effective_threshold_mult, effective_long_conf_threshold, effective_short_conf_threshold,
                    enable_inject, alpha_blend,
                    actual_direction, actual_confidence, actual_position_usdt,
                    actual_tp_px, actual_sl_px, actual_threshold,
                    fma_on_allowed, fma_on_eff_threshold
                ) VALUES (
                    ?,?,
                    ?,?,?,?,
                    ?,?,?,?,
                    ?,?,?,?,
                    ?,?,?,?,?,?,
                    ?,?,?,?,?,?,?,
                    ?,?,?,?,?,?,
                    ?,?,
                    ?,?,?,?,?,?,
                    ?,?
                )
            """, _common_params)
            self._conn.commit()
            return int(cur.lastrowid)

    def get_shadow_log(self, symbol: Optional[str], days: int = 7) -> List[Dict[str, Any]]:
        """查询某 symbol 最近 N 天的 shadow 记录（含三值列 + T5战略/策略影子12列，按时间正序）。

        symbol=None 时返回所有 symbol 的记录。
        """
        cur = self._conn.cursor()
        from datetime import datetime, timedelta, timezone
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
        # symbol=None → 查询所有 symbol；否则按 symbol 过滤
        if symbol is None:
            where_clause = "WHERE timestamp >= ?"
            params: tuple = (cutoff,)
        else:
            where_clause = "WHERE symbol = ? AND timestamp >= ?"
            params = (symbol, cutoff)
        try:
            rows = cur.execute(f"""
                SELECT id, symbol, timestamp,
                       reactive_L, reactive_T, reactive_C, reactive_regime,
                       reactive_pos_mult, reactive_tp_mult, reactive_sl_mult, reactive_threshold,
                       forecast_L, forecast_T, forecast_global_ranges, forecast_sector_weights,
                       baseline_pos_mult, baseline_tp_mult, baseline_sl_mult,
                       baseline_threshold_mult, baseline_long_conf_threshold, baseline_short_conf_threshold,
                       ai_pos_mult, ai_tp_mult, ai_sl_mult, ai_threshold_mult,
                       ai_long_threshold, ai_short_threshold, ai_ls_ratio_cap,
                       effective_pos_mult, effective_tp_mult, effective_sl_mult,
                       effective_threshold_mult, effective_long_conf_threshold, effective_short_conf_threshold,
                       enable_inject, alpha_blend,
                       actual_direction, actual_confidence, actual_position_usdt,
                       actual_tp_px, actual_sl_px, actual_threshold,
                       fma_on_allowed, fma_on_eff_threshold,
                       fd_crypto_war_state, fd_crypto_total_score, fd_crypto_cap_mode, fd_crypto_mult_mode,
                       fd_us_stock_war_state, fd_us_stock_total_score,
                       sal_type, sal_regime, sal_calib_median, sal_calib_min, sal_calib_max, sal_gate
                FROM shadow_param_log
                {where_clause}
                ORDER BY timestamp ASC
            """, params).fetchall()
        except sqlite3.OperationalError:
            rows = cur.execute(f"""
                SELECT id, symbol, timestamp,
                       reactive_L, reactive_T, reactive_C, reactive_regime,
                       reactive_pos_mult, reactive_tp_mult, reactive_sl_mult, reactive_threshold,
                       forecast_L, forecast_T, forecast_global_ranges, forecast_sector_weights,
                       baseline_pos_mult, baseline_tp_mult, baseline_sl_mult,
                       baseline_threshold_mult, baseline_long_conf_threshold, baseline_short_conf_threshold,
                       ai_pos_mult, ai_tp_mult, ai_sl_mult, ai_threshold_mult,
                       ai_long_threshold, ai_short_threshold, ai_ls_ratio_cap,
                       effective_pos_mult, effective_tp_mult, effective_sl_mult,
                       effective_threshold_mult, effective_long_conf_threshold, effective_short_conf_threshold,
                       enable_inject, alpha_blend,
                       actual_direction, actual_confidence, actual_position_usdt,
                       actual_tp_px, actual_sl_px, actual_threshold,
                       fma_on_allowed, fma_on_eff_threshold
                FROM shadow_param_log
                {where_clause}
                ORDER BY timestamp ASC
            """, params).fetchall()
        out: List[Dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            if "enable_inject" in d and d["enable_inject"] is not None:
                d["enable_inject"] = bool(d["enable_inject"])
            if "fma_on_allowed" in d and d["fma_on_allowed"] is not None:
                d["fma_on_allowed"] = bool(d["fma_on_allowed"])
            if "sal_gate" in d and d["sal_gate"] is not None:
                d["sal_gate"] = bool(d["sal_gate"])
            out.append(d)
        return out

    def get_shadow_log_count(self, symbol: str) -> int:
        """返回某 symbol 的 shadow 记录总数。"""
        symbol = symbol or "BTCUSDT"
        cur = self._conn.cursor()
        r = cur.execute(
            "SELECT COUNT(*) AS cnt FROM shadow_param_log WHERE symbol = ?",
            (symbol,)
        ).fetchone()
        return int(r["cnt"]) if r else 0

    def clear_shadow_log(self, symbol: str) -> None:
        """清除某 symbol 的所有 shadow 记录。"""
        symbol = symbol or "BTCUSDT"
        cur = self._conn.cursor()
        cur.execute("DELETE FROM shadow_param_log WHERE symbol = ?", (symbol,))
        self._conn.commit()

    # ================================================================
    # exit_strategy_log: ExitManager 策略贡献值追踪
    # Spec: docs/superpowers/specs/2026-08-20-exit-manager-design.md §5
    # ================================================================
    def save_exit_strategy_log(self, symbol: str, record: Dict[str, Any]) -> int:
        """插入一条 ExitManager 策略决策记录，返回记录 id（pnl/win 留待平仓后回填）。"""
        symbol = symbol or "BTCUSDT"
        cur = self._conn.cursor()
        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

        def _f(k, fallback=None):
            v = record.get(k)
            if v is None:
                return fallback
            try:
                return float(v)
            except (TypeError, ValueError):
                return fallback

        cur.execute("""
            INSERT INTO exit_strategy_log (
                symbol, timestamp, strategy_name, action, reason,
                age_hours, in_protection, ev, confidence, pnl, win
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (
            symbol, now_iso,
            record.get("strategy_name", ""),
            record.get("action"),
            record.get("reason"),
            _f("age_hours"),
            1 if bool(record.get("in_protection")) else 0,
            _f("ev"),
            _f("confidence"),
            _f("pnl") if record.get("pnl") is not None else None,
            (1 if bool(record.get("win")) else 0) if record.get("win") is not None else None,
        ))
        self._conn.commit()
        return int(cur.lastrowid)

    def get_exit_strategy_log(self, symbol: str, days: int = 7) -> List[Dict[str, Any]]:
        """查询某 symbol 最近 N 天的 ExitManager 策略决策记录（按时间正序）。"""
        symbol = symbol or "BTCUSDT"
        cur = self._conn.cursor()
        from datetime import datetime, timedelta, timezone
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
        rows = cur.execute("""
            SELECT id, symbol, timestamp, strategy_name, action, reason,
                   age_hours, in_protection, ev, confidence, pnl, win
            FROM exit_strategy_log
            WHERE symbol = ? AND timestamp >= ?
            ORDER BY timestamp ASC
        """, (symbol, cutoff)).fetchall()
        out: List[Dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            if d.get("in_protection") is not None:
                d["in_protection"] = bool(d["in_protection"])
            if d.get("win") is not None:
                d["win"] = bool(d["win"])
            out.append(d)
        return out

    def update_exit_strategy_outcome(self, log_id: int, pnl: float, win: bool) -> None:
        """平仓后回填实际盈亏和胜负到指定记录。"""
        cur = self._conn.cursor()
        cur.execute("""
            UPDATE exit_strategy_log SET pnl = ?, win = ? WHERE id = ?
        """, (float(pnl), 1 if win else 0, int(log_id)))
        self._conn.commit()

    def get_exit_strategy_contribution(self, days: int = 30) -> Dict[str, Any]:
        """返回各策略近 N 天的贡献统计。

        Returns:
            {"strategy_name": {"triggers": N, "wins": M, "win_rate": float, "avg_pnl": float}, ...}
            只统计 pnl 已回填的记录计入 win_rate/avg_pnl。
        """
        cur = self._conn.cursor()
        from datetime import datetime, timedelta, timezone
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
        rows = cur.execute("""
            SELECT strategy_name,
                   COUNT(*)                  AS triggers,
                   COALESCE(SUM(CASE WHEN win = 1 THEN 1 ELSE 0 END), 0) AS wins,
                   CASE WHEN SUM(CASE WHEN pnl IS NOT NULL THEN 1 ELSE 0 END) > 0
                        THEN 1.0 * SUM(CASE WHEN win = 1 THEN 1 ELSE 0 END) /
                             SUM(CASE WHEN pnl IS NOT NULL THEN 1 ELSE 0 END)
                        ELSE 0.0 END         AS win_rate,
                   CASE WHEN SUM(CASE WHEN pnl IS NOT NULL THEN 1 ELSE 0 END) > 0
                        THEN AVG(CASE WHEN pnl IS NOT NULL THEN pnl ELSE NULL END)
                        ELSE NULL END        AS avg_pnl
            FROM exit_strategy_log
            WHERE timestamp >= ?
            GROUP BY strategy_name
        """, (cutoff,)).fetchall()
        out: Dict[str, Any] = {}
        for r in rows:
            name = r["strategy_name"]
            out[name] = {
                "triggers": int(r["triggers"] or 0),
                "wins": int(r["wins"] or 0),
                "win_rate": round(float(r["win_rate"] or 0.0), 4),
                "avg_pnl": round(float(r["avg_pnl"]), 4) if r["avg_pnl"] is not None else None,
            }
        return out

    # ================================================================
    # 生命周期
    # ================================================================
    def close(self) -> None:
        if self._conn is not None:
            self._conn.commit()
            self._conn.close()
            self._conn = None  # type: ignore[assignment]

    def __enter__(self) -> "EvolutionStorageSQLite":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
