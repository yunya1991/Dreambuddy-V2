#!/usr/bin/env python3
"""P6 E0 特征管道：三屏 token 序列生成器（token_sequence.parquet）。
依据：docs/SPEC_encoder_trend_classifier.md v0.2 实施阶段 E0——
  FeatureHub → token 序列生成器（含 MA200 预计算特征），
  三屏 token 序列可复现生成，血缘完整。
设计：
  - 三屏：1W（定方向）/ 1D（找时机，MA200 预计算特征注入）/ 1H（确认入场）
  - 跨资产共享样本（SPEC 风险 7a）：BTC/ETH/SOL 三资产
  - 特征：21 中心 classic_indicators 模块（15+ 列经典技术指标）
  - MA200 预计算特征（v0.2 修订）：日线屏注入 ma200_dist_pct / above_ma200 /
    ma50_ma100_state（预计算，不依赖模型窗口内学习）
  - 每个 token = 一个时间步的特征行，带 symbol/timeframe/feature_version 血缘列
  - 落盘 40系统/token_sequence.parquet（供 p6_gate E0 门槛消费）
红线：只读 18/21 系统模块，不修改任何外部系统文件；
  token 序列为训练特征数据，不产生交易信号。
"""
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

TREND = "/home/luke/dreambuddy/12-三屏趋势系统"
DCENTER = "/home/luke/dreambuddy/18-数据获取中心"
FHUB = "/home/luke/dreambuddy/21-特征工程中心"
sys.path.insert(0, TREND)
sys.path.insert(0, DCENTER)
sys.path.insert(0, FHUB)

OUT_PATH = "/home/luke/dreambuddy/40-周期神经网络系统/token_sequence.parquet"
META_OUT = "/home/luke/dreambuddy/40-周期神经网络系统/token_sequence_meta.json"

# 预注册参数（禁止运行时调整）
SYMBOLS = ["BTC", "ETH", "SOL"]          # 跨资产共享样本（SPEC 风险 7a）
SCREENS = {"1W": "weekly", "1D": "daily", "1H": "hourly"}  # 三屏
CANDLE_LIMIT = 300                        # 每屏每资产 K 线数
FEATURE_VERSION = "classic_indicators_v1+ma200_v1"  # 特征版本血缘


def _ma200_precompute(df: pd.DataFrame) -> pd.DataFrame:
    """MA200 预计算特征（v0.2 修订：预计算注入，不依赖模型窗口内学习）。
    - ma200_dist_pct: 收盘价与 MA200 距离百分比
    - above_ma200: 收盘价在 MA200 上方布尔状态
    - ma50_ma100_state: MA50/MA100 多级分界状态（1=多头排列, -1=空头, 0=中性/未定）
    """
    close = df["close"].astype(float)
    ma50 = close.rolling(50).mean()
    ma100 = close.rolling(100).mean()
    ma200 = close.rolling(200).mean()
    out = pd.DataFrame(index=df.index)
    out["ma200_dist_pct"] = (close - ma200) / (ma200 + 1e-9) * 100.0
    out["above_ma200"] = (close > ma200).astype(float)
    out["ma50_ma100_state"] = np.sign(ma50 - ma100).where(
        ma50.notna() & ma100.notna(), 0.0
    )
    return out


def main() -> int:
    from data_center.compat import fetch_candles
    from feature_hub.modules.classic_indicators import compute as classic_compute

    def _to_ohlcv(candles):
        """从原始 candles 构建 OHLCV DataFrame（18 中心 ts 为秒级，直接转换避免精度丢失）。"""
        df = pd.DataFrame([
            {
                "date": pd.to_datetime(c["ts"], unit="s"),
                "ts": int(c["ts"]),
                "open": float(c["o"]),
                "high": float(c["h"]),
                "low": float(c["l"]),
                "close": float(c["c"]),
                "volume": float(c.get("vol", 0)),
            }
            for c in candles
        ])
        return df.sort_values("date").reset_index(drop=True)

    frames = []
    lineage = []
    for sym in SYMBOLS:
        for bar, screen_name in SCREENS.items():
            candles = fetch_candles(f"{sym}-USDT", bar, CANDLE_LIMIT)
            df = _to_ohlcv(candles)
            if df is None or len(df) < 60:
                print(f"[WARN] {sym} {bar}: K 线不足（{0 if df is None else len(df)}），跳过")
                continue

            # 21 中心经典指标特征（fail-open：异常跳过该屏）
            try:
                feats = classic_compute(df, symbol=sym)
            except Exception as e:
                print(f"[WARN] {sym} {bar}: 特征计算失败 {e}，跳过")
                continue

            token = pd.DataFrame(index=df.index)
            token["symbol"] = sym
            token["timeframe"] = bar
            token["screen"] = screen_name
            token["ts"] = df["ts"].astype("int64")  # 18 中心原始秒级 ts
            token["feature_version"] = FEATURE_VERSION

            for col in feats.columns:
                token[col] = feats[col]

            # MA200 预计算特征：仅日线屏注入（周线窗口不足 200 根，1H 屏无 MA200 语义）
            if bar == "1D":
                ma_feats = _ma200_precompute(df)
                for col in ma_feats.columns:
                    token[col] = ma_feats[col]

            frames.append(token)
            lineage.append({
                "symbol": sym,
                "timeframe": bar,
                "candles": int(len(df)),
                "feature_cols": int(len(feats.columns)),
                "ma200_precompute": bar == "1D",
            })

    if not frames:
        print("[FAIL] 无有效 token 生成")
        return 1

    all_tokens = pd.concat(frames, ignore_index=True)
    # 有效 token：剔除全特征 NaN 行（指标暖机期）
    feat_cols = [c for c in all_tokens.columns
                 if c not in ("symbol", "timeframe", "screen", "ts", "feature_version")]
    valid_mask = all_tokens[feat_cols].notna().any(axis=1)
    valid_tokens = all_tokens[valid_mask].reset_index(drop=True)

    # 落盘 parquet
    valid_tokens.to_parquet(OUT_PATH, index=False)

    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "module": "P6 E0 三屏 token 序列生成器",
        "feature_version": FEATURE_VERSION,
        "symbols": SYMBOLS,
        "screens": SCREENS,
        "candle_limit": CANDLE_LIMIT,
        "total_rows": int(len(all_tokens)),
        "valid_rows": int(len(valid_tokens)),
        "feature_cols": feat_cols,
        "lineage": lineage,
        "note": "三屏 token 序列（周/日/1H），日线屏含 MA200 预计算特征；供 P6 E2 训练消费，不产生交易信号",
    }
    with open(META_OUT, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"[OK] E0 token 序列: 总行 {len(all_tokens)} / 有效行 {len(valid_tokens)} -> {OUT_PATH}")
    for sym in SYMBOLS:
        n = int((valid_tokens["symbol"] == sym).sum())
        print(f"     {sym}: {n} tokens")
    for bar in SCREENS:
        n = int((valid_tokens["timeframe"] == bar).sum())
        print(f"     {bar}: {n} tokens")
    print(f"     特征列数: {len(feat_cols)}（含 MA200 预计算 3 列，日线屏）")
    print(f"     血缘元数据 -> {META_OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
