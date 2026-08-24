"""run_evolution_pipeline.py — Phase 0/1 7 层流水线 CLI

入口（Phase 0 最小可运行版，100% 回滚兼容，默认参数下字节等价 P0）：
  python run_evolution_pipeline.py --csv BTC_1D_full.csv --window 90 --out evolution_btc_90.json [--symbol BTCUSDT]

Phase 1 扩展（全部为**可选开关**，关闭时完全不干扰 JSON schema）：
  --with-lgbm <dir>              加载 LGBMCalibrator，在 trajectory 顶部追加 regime_probs_calibrated_traj
  --global-ranges                追加 global_ranges_latest / global_ranges（ParameterMapper 6 范围参数）
  --sector-weights               追加 sector_weights_latest / sector_weights（5 板块 Σ=1，默认 identity betas）
  --feature-schema-out <path>    导出 FeatureRegistry v4 schema JSON

流程（7 层，新增 L6 L7 可选，不启用时输出与 Phase 0 字节等价）：
  Layer 0: 读取 CSV，保证 timestamp + close/high/low/volume
  Layer 1: IndicatorBank 计算 12 主指标 + 6 __raw_ 列
  Layer 2: ScoreComposer → (level_raw, trend_raw)，钳制
  Layer 3: TemporalSmoother → (level_smooth, trend_smooth, hmm_state, ema, bocpd=0)
  Layer 4: RegimeMapper → 逐帧 regime_probs/Top3/consensus
  Layer 5: EvolutionStorageJSON.dump → JSON 文件（回滚兼容核心）
  Layer 6: (可选 --global-ranges) ParameterMapper.map_global_parameters → 6 范围
  Layer 7: (可选 --sector-weights) ParameterMapper.map_sector_weights → 5 板块权重
  Layer 8: (可选 --with-lgbm)   LGBMCalibrator → 校准 8 态概率
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

# 允许以脚本形式直接运行 python bcrm2/run_evolution_pipeline.py（自动补 sys.path）
_THIS_FILE = Path(__file__).resolve()
_BCRM2_DIR = _THIS_FILE.parent
_MEMORY_L4_DIR = _BCRM2_DIR.parent
if str(_MEMORY_L4_DIR) not in sys.path:
    sys.path.insert(0, str(_MEMORY_L4_DIR))

from bcrm2.indicators import IndicatorBank                       # noqa: E402
from bcrm2.score_composer import ScoreComposer                   # noqa: E402
from bcrm2.temporal_smoother import TemporalSmoother             # noqa: E402
from bcrm2.regime_mapper import RegimeMapper, REGIME_ORDER       # noqa: E402
from bcrm2.storage import (                                       # noqa: E402
    EvolutionStorageJSON, EvolutionStorageSQLite, RegimeStateFrame,
)


# ================================================================
# Phase 1 P1.5/P1.6：SQLite 单例 + ensure_evolution_db
#   供 ml_trade_service.py 的 4 条 Flask 路由复用
# ================================================================
_DEFAULT_DB_PATH = Path(_MEMORY_L4_DIR).parent / "artifacts" / "evolution_btc" / "evolution.db"
_STORAGE_SINGLETON: Optional[EvolutionStorageSQLite] = None


def ensure_evolution_db(db_path: Optional[Union[str, Path]] = None) -> Path:
    """确保 SQLite DB 文件存在并初始化 schema，返回 db 绝对路径。

    供 Flask 后端启动时调用一次（P1.6 入口）。db_path 为 None 时用默认路径。
    """
    p = Path(db_path).expanduser().resolve() if db_path else _DEFAULT_DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    # 触发 schema 初始化（构造函数内 _init_sqlite_schema）
    _ = EvolutionStorageSQLite(p)
    return p


def get_storage(db_path: Optional[Union[str, Path]] = None,
                reuse_singleton: bool = True) -> EvolutionStorageSQLite:
    """获取 EvolutionStorageSQLite 单例（供 Flask 路由复用同一连接）。

    首次调用会 ensure_evolution_db + 创建单例；后续调用返回同一对象。
    测试场景下传 reuse_singleton=False 强制新建独立实例。
    """
    global _STORAGE_SINGLETON
    if reuse_singleton and _STORAGE_SINGLETON is not None:
        return _STORAGE_SINGLETON
    p = Path(db_path).expanduser().resolve() if db_path else _DEFAULT_DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    storage = EvolutionStorageSQLite(p)
    if reuse_singleton:
        _STORAGE_SINGLETON = storage
    return storage


def reset_storage_singleton() -> None:
    """重置单例（仅供测试 teardown 使用）。"""
    global _STORAGE_SINGLETON
    if _STORAGE_SINGLETON is not None:
        _STORAGE_SINGLETON.close()
        _STORAGE_SINGLETON = None


# ================================================================
# BTC 特有关键日期（中文 tag 仅用于 acceptance 报告）
# ================================================================
BTC_KEY_DATES = [
    # (tag,  target_date_str,  Level 规则,   Trend 规则,   check_description)
    # 基于冷启动中心 + BTC 真实 L/T 诊断：
    #   ATH 69k:    L≈+3.1, T≈+1.6 → FOMO_RALLY / TREND_UP_STRONG
    #   FTX 底:     L≈-2.3, T≈-1.5 → CONSOLIDATION（深熊区间）
    #   2024-04-20: L≈+2.7, T≈+1.5 → FOMO_RALLY（减半后牛市）
    ("ATH_69k",      "2021-11-10", lambda L,T: L >= +2.0, lambda L,T: T >= +1.0, "ATH 顶：L≥+2 且 T≥+1 → 牛市狂热区"),
    ("FTX_low",      "2022-11-21", lambda L,T: L <= -1.5, lambda L,T: T <= -1.0, "FTX 熊市底：L≤-1.5 且 T≤-1 → 深熊区间"),
    ("halving_2024", "2024-04-20", lambda L,T: L >= +1.5, lambda L,T: T >= +1.0, "2024 减半后：L≥+1.5 且 T≥+1 → 牛市延续"),
]


def _find_date_loc(df: pd.DataFrame, date_str: str) -> int:
    ts = pd.Timestamp(date_str, tz=df.index.tz)
    pos = df.index.get_indexer([ts], method="nearest")[0]
    return int(pos)


def _read_csv(csv_path: Path) -> pd.DataFrame:
    """统一读取：timestamp 列 → index；缺 high/low/volume 则自动派生。"""
    df = pd.read_csv(csv_path)
    # 兼容 "timestamp" / "datetime" / "date" 等列名
    ts_candidates = [c for c in df.columns if c.lower() in {"timestamp", "datetime", "date", "time"}]
    if ts_candidates:
        ts_col = ts_candidates[0]
        df[ts_col] = pd.to_datetime(df[ts_col])
        df = df.set_index(ts_col)
    else:
        df.index = pd.to_datetime(df.index)
        df.index.name = df.index.name or "timestamp"

    close = df["close"] if "close" in df.columns else pd.Series(df.iloc[:, -1].astype(float))
    if "high" not in df.columns:
        df["high"] = close * 1.001
    if "low" not in df.columns:
        df["low"]  = close * 0.999
    if "volume" not in df.columns:
        df["volume"] = 1.0
    # 确保所有核心列 float
    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = df[col].astype(float)
    return df.sort_index()


def build_trajectory_frames(
    df: pd.DataFrame,
    mapper: RegimeMapper,
    indicators: dict,
    level_raw: pd.Series,
    trend_raw: pd.Series,
    level_smooth: pd.Series,
    trend_smooth: pd.Series,
    hmm_state: pd.Series,
    bocpd_cp_prob: pd.Series,
) -> list[RegimeStateFrame]:
    """把 Layer 1-4 的所有输出组装成 RegimeStateFrame 列表。"""
    n = len(df)
    # Layer 4：序列级 transform_sequence（批量）
    mapper_result = mapper.transform_sequence(
        level_smooth, trend_smooth,
        indicators=indicators,
        hmm_state=hmm_state,
        bocpd_cp_prob=bocpd_cp_prob,
    )
    # 主指标 keys（IndicatorBank.MAIN_INDICATORS）
    main12 = list(IndicatorBank.MAIN_INDICATORS)
    # 预处理 indicators → numpy dict 加速
    ind_arr = {k: np.asarray(indicators[k], dtype=float) for k in main12}
    close_arr = np.asarray(df["close"], dtype=float)

    frames: list[RegimeStateFrame] = []
    for i in range(n):
        mr = mapper_result[i]
        indicators_row = {k: float(ind_arr[k][i]) for k in main12}
        date_str = df.index[i].strftime("%Y-%m-%d") if hasattr(df.index[i], "strftime") else str(df.index[i])
        frame = RegimeStateFrame(
            t=date_str,
            price=float(close_arr[i]),
            level_raw=float(level_raw.iloc[i]),
            trend_raw=float(trend_raw.iloc[i]),
            level_smooth=float(mr["level_smooth"]),
            trend_smooth=float(mr["trend_smooth"]),
            regime_probs={k: float(v) for k, v in mr["regime_probs"].items()},
            top3=[[str(r), float(p)] for r, p in mr["top3"]],
            consensus=float(mr["consensus"]),
            hmm_state=int(mr["hmm_state"]),
            bocpd_cp_prob=float(mr["bocpd_cp_prob"]),
            indicators=indicators_row,
        )
        frames.append(frame)
    return frames


def run_pipeline(csv: Path, window: int, symbol: str,
                 calibrate: bool, run_acceptance: bool,
                 ) -> EvolutionStorageJSON:
    # Layer 0
    df = _read_csv(csv)
    n_total = len(df)
    if n_total < window:
        raise ValueError(f"数据长度 {n_total} < --window {window}")

    # Layer 1
    bank = IndicatorBank()
    indicators = bank.compute_all(df)

    # Layer 2
    composer = ScoreComposer()
    level_raw, trend_raw = composer.compose(indicators, df)

    # Layer 3
    smoother = TemporalSmoother(n_hmm_states=3, random_state=42)
    so = smoother.transform(level_raw, trend_raw)

    # Layer 4（可选校准）
    mapper = RegimeMapper()
    if calibrate and symbol.upper().startswith("BTC"):
        try:
            from bcrm2.labels.regime_labeler import generate_8state_label
            labels = generate_8state_label(df, forward_days=20, lookback=252)
            valid = labels.notna()
            if valid.sum() >= 200:
                new_centers = RegimeMapper.calibrate_centers(
                    labels[valid], level_raw[valid], trend_raw[valid], min_samples=50
                )
                mapper = RegimeMapper(centers=new_centers, softmax_temperature=0.6)
                print(f"[pipeline] BTC 冷启动中心校准 OK，有效样本 {int(valid.sum())} 条", flush=True)
            else:
                print(f"[pipeline] 有效标签仅 {int(valid.sum())} < 200，跳过冷启动校准", flush=True)
        except Exception as e:
            print(f"[pipeline] 冷启动校准失败（跳过）：{e}", flush=True)

    # 组装所有帧（全样本 N 条）
    all_frames = build_trajectory_frames(
        df, mapper, indicators,
        level_raw, trend_raw,
        so.level_smooth, so.trend_smooth, so.hmm_state, so.bocpd_cp_prob,
    )

    # 只保留最后 window 条做 trajectory
    traj_frames = all_frames[-window:]

    acceptance: dict = {}
    if run_acceptance and symbol.upper().startswith("BTC"):
        # 在全样本中查询 4 关键日期位置
        for tag, target_date, L_rule, T_rule, desc in BTC_KEY_DATES:
            pos = _find_date_loc(df, target_date)
            L = float(so.level_smooth.iloc[pos])
            T = float(so.trend_smooth.iloc[pos])
            actual_date = df.index[pos].strftime("%Y-%m-%d")
            ok = bool(L_rule(L, T) and T_rule(L, T))
            acceptance[tag] = {
                "t": actual_date,
                "target_t": target_date,
                "L": round(L, 3),
                "T": round(T, 3),
                "price": round(float(df["close"].iloc[pos]), 2),
                "check": desc,
                "pass": ok,
            }
            print(f"[acceptance] {tag:16s} [{actual_date}] L={L:+.2f} T={T:+.2f} → {'PASS' if ok else 'FAIL'}", flush=True)

    store = EvolutionStorageJSON(
        symbol=symbol,
        window=window,
        trajectory=traj_frames,
        snapshot_latest=traj_frames[-1],
        acceptance=acceptance,
    )

    # ============================================================
    # Phase 1 扩展：把原始 df / smooth / indicator 等 pipeline 中间产物
    #   挂载到 store._pipeline_context，供 main 中 --global-ranges / --sector-weights / --with-lgbm
    #   扩展键追加时使用。不修改 EvolutionStorageJSON.to_dict()，保持回滚字节等价。
    # ============================================================
    ctx: Dict[str, Any] = {
        "df": df,
        "level_smooth": so.level_smooth,
        "trend_smooth": so.trend_smooth,
        "consensus": pd.Series([fr.consensus for fr in all_frames], index=df.index),
        "level_raw": level_raw,
        "trend_raw": trend_raw,
        "indicators": indicators,
        "window": window,
        "all_frames": all_frames,  # Phase 1 P1.5 SQLite 写入用
    }
    store._pipeline_context = ctx  # type: ignore[attr-defined]
    return store


# ================================================================
# Phase 1 扩展：追加 global_ranges / sector_weights / calibrated_probs
#   —— 全部工作在 store.to_dict() 之后的 dict 追加层完成，
#      不启用时 store.to_dict() 与 P0 字节完全等价（回滚铁律）。
# ============================================================
_SECTOR_NAMES_IDENTITY: Tuple[str, ...] = ("defi", "ai", "rwa", "meme", "l2")
_DEFAULT_IDENTITY_BETAS = {
    # 所有板块 β=1.0, α=0, corr=0.5 → 中性无偏直通时 softmax 均匀 0.20
    # 若用户需要真实板块权重，可扩展 CLI 加 sector csv 接口（当前保留 identity 基线）
    "defi": (1.0, 0.0, 0.5),
    "ai":   (1.0, 0.0, 0.5),
    "rwa":  (1.0, 0.0, 0.5),
    "meme": (1.0, 0.0, 0.5),
    "l2":   (1.0, 0.0, 0.5),
}


def _default_stats_row() -> Dict[str, float]:
    """ParameterMapper 的 stats_row（当前未使用，预留滚动分位锚点）。"""
    return {
        "L_p10_60d": -3.0, "L_p90_60d": 3.0,
        "T_p10_60d": -2.5, "T_p90_60d": 2.8,
        "L_p10_252d": -3.0, "L_p90_252d": 3.0,
        "T_p10_252d": -2.5, "T_p90_252d": 2.8,
    }


def append_extensions_to_payload(
    payload: Dict[str, Any],
    store: EvolutionStorageJSON,
    *,
    enable_global_ranges: bool = False,
    enable_sector_weights: bool = False,
    lgbm_calibrator_dir: Optional[str] = None,
    feature_schema_out: Optional[str] = None,
    feature_set: str = "btc_morphology_v4",
) -> Dict[str, Any]:
    """在 EvolutionStorageJSON.to_dict() 输出上**增量追加**扩展键。

    若所有扩展关闭，直接原封不动返回 payload（字节等价 P0）。
    """
    if not any([enable_global_ranges, enable_sector_weights,
                lgbm_calibrator_dir is not None, feature_schema_out is not None]):
        return payload

    # Feature schema out（一次性导出，不加入 payload，避免污染字节，保持回滚）
    if feature_schema_out is not None:
        from bcrm2.feature_registry import FeatureRegistry
        schema = FeatureRegistry.build_feature_schema(set_name=feature_set)
        fso = Path(feature_schema_out).expanduser().resolve()
        fso.parent.mkdir(parents=True, exist_ok=True)
        fso.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[ext] FeatureRegistry schema → {fso} （{len(schema.get('feature_names_in_order', []))} 列）", flush=True)

    ctx: Optional[Dict[str, Any]] = getattr(store, "_pipeline_context", None)
    if ctx is None:
        # 没有 pipeline context（极旧 store）→ 无法计算扩展，跳过
        return payload

    L_all: pd.Series = ctx["level_smooth"]
    T_all: pd.Series = ctx["trend_smooth"]
    C_all: pd.Series = ctx["consensus"]
    w = int(ctx["window"])

    # 取 window 切片（对齐 trajectory 的最后 N 条）
    L_win = L_all.iloc[-w:]
    T_win = T_all.iloc[-w:]
    C_win = C_all.iloc[-w:]

    stats_row = _default_stats_row()

    # ---- (1) Global Ranges ----
    if enable_global_ranges:
        from bcrm2.parameter_mapper import ParameterMapper
        pm = ParameterMapper()
        ranges_seq: List[Dict[str, List[float]]] = []
        for i in range(w):
            r = pm.map_global_parameters(
                L=float(L_win.iloc[i]), T=float(T_win.iloc[i]),
                C=float(C_win.iloc[i]), stats_row=stats_row,
            )
            ranges_seq.append({k: [float(lo), float(hi)] for k, (lo, hi) in r.items()})
        payload["global_ranges"] = ranges_seq
        payload["global_ranges_latest"] = ranges_seq[-1]
        print(f"[ext] 已追加 global_ranges（{w} 帧，6 参数 [lo,hi] 范围）", flush=True)
        latest_6 = ranges_seq[-1]
        snap_center = {k: round(0.5*(v[0]+v[1]), 4) for k, v in latest_6.items()}
        print(f"       最新中心：{snap_center}", flush=True)

    # ---- (2) Sector Weights（默认 identity betas；无偏时 0.20 均匀，满足 identity 不变量）----
    if enable_sector_weights:
        from bcrm2.parameter_mapper import ParameterMapper
        pm = ParameterMapper()
        w_seq: List[Dict[str, float]] = []
        for i in range(w):
            wt = pm.map_sector_weights(
                L=float(L_win.iloc[i]), T=float(T_win.iloc[i]),
                C=float(C_win.iloc[i]), sector_betas=_DEFAULT_IDENTITY_BETAS,
            )
            w_seq.append({k: round(float(v), 6) for k, v in wt.items()})
        payload["sector_weights"] = w_seq
        payload["sector_weights_latest"] = w_seq[-1]
        latest_sum = sum(w_seq[-1].values())
        print(f"[ext] 已追加 sector_weights（{w} 帧，Σ={latest_sum:.4f}）", flush=True)
        print(f"       最新：{w_seq[-1]}", flush=True)

    # ---- (3) LGBM Calibrated probs ----
    if lgbm_calibrator_dir is not None:
        from bcrm2.lgbm_calibrator import LGBMCalibrator
        from bcrm2.feature_registry import FeatureRegistry
        cal_dir = Path(lgbm_calibrator_dir).expanduser().resolve()
        print(f"[ext] 加载 LGBMCalibrator ← {cal_dir}", flush=True)
        cal = LGBMCalibrator.load(str(cal_dir))

        # 用 FeatureRegistry 计算推理所需 X（对齐 calibrator regime_order 顺序）
        df_all: pd.DataFrame = ctx["df"]
        mod = FeatureRegistry.get(feature_set)
        X_all = mod.compute(df_all)
        # 严格 reindex 列（不抛错，按 schema 顺序；真正的校验在 calibrate 内进行）
        expected_cols = cal.feature_names
        missing = [c for c in expected_cols if c not in X_all.columns]
        if missing:
            raise ValueError(
                f"[ext] LGBM 推理特征缺失 {len(missing)} 列：{missing[:5]}... "
                f"FeatureRegistry set={feature_set!r} 产出列数={len(X_all.columns)}，"
                f"Calibrator 需要 {len(expected_cols)} 列。请用相同 --feature-set 训练/推理。"
            )
        X_recent = X_all[expected_cols].iloc[-w:]

        # p_gauss：来自 trajectory 中每帧的 regime_probs → 按 calibrator regime_order 取 → np.stack
        p_gauss_rows = []
        for fr in store.trajectory:
            row = []
            for name in cal.regime_order:
                # 若某 frame 的 regime_probs 不含该名 → 0；之后 normalize
                row.append(float(fr.regime_probs.get(name, 0.0)))
            p_gauss_rows.append(row)
        p_gauss = np.asarray(p_gauss_rows, dtype=float)
        # 归一（补齐缺失 regime 后可能和不为 1）
        p_gauss = p_gauss / np.clip(p_gauss.sum(axis=1, keepdims=True), 1e-12, None)

        p_cal = cal.calibrate(p_gauss, X_recent)
        # 转 List[Dict[str,float]]，不修改原 frame 的 regime_probs，独立追加
        calibrated = [
            {str(name): round(float(p_cal[i, j]), 6)
             for j, name in enumerate(cal.regime_order)}
            for i in range(w)
        ]
        payload["regime_probs_calibrated_traj"] = calibrated
        top1_cal = max(calibrated[-1].items(), key=lambda kv: kv[1])
        print(f"[ext] 已追加 regime_probs_calibrated_traj（{w} 帧），"
              f"最新 top1_cal={top1_cal[0]}({top1_cal[1]:.3f})", flush=True)

    return payload


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Evolution Engine — 形态演化流水线 CLI（Phase 0 兼容 + Phase 1 扩展）")
    parser.add_argument("--csv", required=True, help="OHLCV CSV 路径（timestamp/open/high/low/close/volume）")
    parser.add_argument("--out", required=True, help="输出 trajectory JSON 路径")
    parser.add_argument("--window", type=int, default=90, help="trajectory 最近 N 日（默认 90）")
    parser.add_argument("--symbol", type=str, default="UNKNOWN", help="交易对代号，默认 UNKNOWN")
    parser.add_argument("--no-calibrate", action="store_true", help="跳过 BTC 冷启动中心校准")
    parser.add_argument("--run-acceptance", action="store_true", help="输出 4 关键日期象限验收（仅 BTC 有效）")

    # ---------- Phase 1 扩展开关（默认关闭 → 100% 字节等价 P0） ----------
    parser.add_argument("--global-ranges", action="store_true",
                        help="【Phase 1】输出 6 个全局参数范围（global_ranges + global_ranges_latest）")
    parser.add_argument("--sector-weights", action="store_true",
                        help="【Phase 1】输出 5 板块权重（sector_weights + sector_weights_latest），默认 identity betas")
    parser.add_argument("--with-lgbm", type=str, default=None, metavar="DIR",
                        help="【Phase 1】用 train_lgbm_calibrator_v4.py 产出目录，追加 regime_probs_calibrated_traj")
    parser.add_argument("--feature-set", type=str, default="btc_morphology_v4",
                        help="【Phase 1】--with-lgbm/--feature-schema-out 使用的特征集名")
    parser.add_argument("--feature-schema-out", type=str, default=None, metavar="PATH",
                        help="【Phase 1】将 FeatureRegistry v4 schema JSON 输出到该路径")
    parser.add_argument("--sqlite-db", type=str, default=None, metavar="PATH",
                        help="【Phase 1 P1.5】将 trajectory 写入 SQLite（默认不写）。"
                             "若指定，等价于 ensure_evolution_db(db_path) 并 upsert 全部帧 + dotplot")

    args = parser.parse_args(argv)

    csv_path = Path(args.csv).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()
    if not csv_path.exists():
        print(f"[error] CSV 不存在: {csv_path}", file=sys.stderr)
        return 2

    calibrate = (not args.no_calibrate)
    store = run_pipeline(csv_path, args.window, args.symbol, calibrate, args.run_acceptance)

    # --- 基础序列化（P0 原 schema） ---
    base_dict = store.to_dict()

    # --- Phase 1 扩展（开关全部关闭时 append_extensions_to_payload 直通返回，字节 100% 等价 P0） ---
    extended_dict = append_extensions_to_payload(
        base_dict, store,
        enable_global_ranges=args.global_ranges,
        enable_sector_weights=args.sector_weights,
        lgbm_calibrator_dir=args.with_lgbm,
        feature_schema_out=args.feature_schema_out,
        feature_set=args.feature_set,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(extended_dict, f, ensure_ascii=False, indent=2, allow_nan=False)

    # ---- Phase 1 P1.5：可选写入 SQLite（--sqlite-db 指定路径）----
    if args.sqlite_db:
        db_path = Path(args.sqlite_db).expanduser().resolve()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        # 用独立实例（不复用单例，避免 CLI 与 Flask 服务冲突）
        with EvolutionStorageSQLite(db_path) as storage:
            # upsert 全部 frames（不只是 trajectory 90 天）
            all_traj_frames: List[RegimeStateFrame] = getattr(store, "_pipeline_context", {}).get(
                "all_frames", None
            ) or store.trajectory  # fallback：没存 all_frames 时退化为 trajectory
            n_written = storage.upsert_daily_batch(args.symbol or "BTCUSDT", all_traj_frames)
            print(f"[sqlite] upsert_daily_batch OK：{n_written} 条 frame → {db_path}", flush=True)

            # 计算并保存 dotplot（基于全部 frames，最后一日作为 target）
            try:
                from bcrm2.labels.regime_labeler import generate_8state_label
                df_all = store._pipeline_context["df"]  # type: ignore[attr-defined]
                indicators_all = store._pipeline_context["indicators"]  # type: ignore[attr-defined]
                labels = generate_8state_label(df_all, forward_days=20, lookback=252)
                valid = labels.notna()
                if valid.sum() >= 200:
                    mapper_for_dot = RegimeMapper()
                    # 对齐 indicators（剔除 NaN 标签）
                    ind_valid = {k: v[valid] for k, v in indicators_all.items()}
                    labels_valid = labels[valid]
                    # 重置 target_index：使用 valid 后最后一日
                    dotplot = mapper_for_dot.compute_dotplot_support(
                        ind_valid, labels_valid, min_samples=20, target_index=len(labels_valid) - 1
                    )
                    storage.save_dotplot(args.symbol or "BTCUSDT", dotplot)
                    print(f"[sqlite] dotplot OK：target_idx={dotplot['target_index']} → saved", flush=True)
                else:
                    print(f"[sqlite] 跳过 dotplot：有效标签 {int(valid.sum())} < 200", flush=True)
            except Exception as e:
                print(f"[sqlite] dotplot 计算失败（跳过）：{e}", flush=True)

    # 人类可读摘要
    snap = store.snapshot_latest
    print(
        f"[pipeline] OK → {out_path}  "
        f"window={store.window}  "
        f"snap_t={snap.t}  price={snap.price:.2f}  "
        f"L/T=({snap.level_smooth:+.2f},{snap.trend_smooth:+.2f})  "
        f"top1={snap.top3[0][0]}({snap.top3[0][1]:.2f})  "
        f"consensus={snap.consensus:.3f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
