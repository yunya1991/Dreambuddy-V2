"""集成模型训练数据标注工具

功能：
1. 读取 collected/ 目录下的未标注样本
2. 从 OKX 获取对应币种的历史K线
3. 计算每个样本时间点后的未来 N 日收益率
4. 回填 _future_return 字段
5. 调用 train_ensemble() 训练模型

用法（命令行）：
    python3 ml/label_samples.py --lookahead 7
    python3 ml/label_samples.py --train --lookahead 7

用法（代码调用）：
    from ml.label_samples import label_collected_samples, train_from_collected
    label_collected_samples(lookahead_days=7)
    train_from_collected(lookahead_days=7)
"""

import json
import os
import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


# ── 路径配置 ──────────────────────────────────────────────────────────────

TREND_SYSTEM = Path(__file__).parent.parent
ENSEMBLE_DIR = TREND_SYSTEM / "ml" / "models" / "ensemble"
DATA_COLLECTOR = ENSEMBLE_DIR / "collected"
ENSEMBLE_DIR.mkdir(parents=True, exist_ok=True)
DATA_COLLECTOR.mkdir(parents=True, exist_ok=True)


def _load_all_samples() -> pd.DataFrame:
    """加载所有已收集的样本（含已标注和未标注）"""
    all_samples = []
    for f in sorted(DATA_COLLECTOR.glob("samples_*.jsonl")):
        with open(f, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        all_samples.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

    if not all_samples:
        return pd.DataFrame()

    df = pd.DataFrame(all_samples)
    if "_timestamp" in df.columns:
        df["_dt"] = pd.to_datetime(df["_timestamp"], utc=True)
    return df


def _save_samples(df: pd.DataFrame) -> None:
    """按日期拆分保存样本回 jsonl 文件"""
    if df.empty:
        return

    if "_dt" not in df.columns and "_timestamp" in df.columns:
        df["_dt"] = pd.to_datetime(df["_timestamp"], utc=True)

    # 按日期分组
    if "_dt" in df.columns:
        df["_date"] = df["_dt"].dt.strftime("%Y-%m-%d")
    else:
        df["_date"] = "unknown"

    cols_to_write = [c for c in df.columns if c not in ("_dt", "_date")]

    for date_str, group in df.groupby("_date"):
        file_path = DATA_COLLECTOR / f"samples_{date_str}.jsonl"
        with open(file_path, "w", encoding="utf-8") as f:
            for _, row in group.iterrows():
                record = {c: row[c] for c in cols_to_write}
                # 处理 NaN
                record = {k: (None if pd.isna(v) else v) for k, v in record.items()}
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def _fetch_daily_candles(symbol: str, limit: int = 300) -> pd.DataFrame:
    """获取日线K线数据

    参数:
        symbol: 币种符号，如 "BTC"
        limit: 获取数量

    返回:
        DataFrame，列包括 ts, o, h, l, c, vol，按时间正序
    """
    try:
        try:
            from data.market_data import fetch_candles
        except ImportError:
            sys.path.insert(0, str(TREND_SYSTEM))
            from data.market_data import fetch_candles

        inst_id = f"{symbol}-USDT"
        candles = fetch_candles(inst_id, "1D", limit)
        if not candles:
            return pd.DataFrame()

        df = pd.DataFrame(candles)
        df["dt"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
        for col in ["o", "h", "l", "c", "vol"]:
            if col in df.columns:
                df[col] = df[col].astype(float)
        return df
    except Exception as e:
        print(f"  [WARN] 获取 {symbol} K线失败: {e}")
        return pd.DataFrame()


def _calc_future_return(price_series: pd.Series, lookahead: int = 7) -> pd.Series:
    """计算未来 N 日收益率

    使用未来第 N 根K线的收盘价计算收益率。
    如果未来不足 N 根K线，返回 NaN。
    """
    return price_series.shift(-lookahead) / price_series - 1.0


def label_collected_samples(lookahead_days: int = 7, min_candles: int = 60) -> Dict:
    """标注已收集的样本

    遍历 collected/ 目录下的所有样本，根据时间戳计算未来 N 日收益率，
    回填到 _future_return 字段。

    参数:
        lookahead_days: 未来收益的前瞻天数
        min_candles: 最少需要的K线数量

    返回:
        统计结果 dict
    """
    df = _load_all_samples()
    if df.empty:
        return {"error": "没有已收集的样本"}

    total = len(df)
    already_labeled = df["_future_return"].notna().sum() if "_future_return" in df.columns else 0
    to_label = total - already_labeled

    print(f"总样本数: {total}")
    print(f"已标注: {already_labeled}")
    print(f"待标注: {to_label}")

    if to_label <= 0:
        print("全部样本已标注，跳过")
        return {"total": total, "labeled": already_labeled, "new_labeled": 0}

    # 按币种分组
    if "_symbol" not in df.columns:
        return {"error": "样本缺少 _symbol 字段"}

    new_labeled = 0
    symbols = df["_symbol"].unique()

    for symbol in symbols:
        mask = df["_symbol"] == symbol
        sym_df = df[mask].copy()

        # 获取该币种的K线
        need_limit = min_candles + lookahead_days + 30
        candles = _fetch_daily_candles(symbol, limit=need_limit)
        if candles.empty or len(candles) < lookahead_days + 5:
            print(f"  [SKIP] {symbol}: K线数据不足（{len(candles)} 根）")
            continue

        # 计算未来收益
        candles["future_return"] = _calc_future_return(candles["c"], lookahead=lookahead_days)

        # 对每个样本，找到最近的K线并匹配未来收益
        sample_count = 0
        for idx, row in sym_df.iterrows():
            if not pd.isna(row.get("_future_return")):
                continue  # 已有标签，跳过

            sample_dt = row.get("_dt")
            if sample_dt is None or pd.isna(sample_dt):
                continue

            # 找到时间戳 ≤ 样本时间的最后一根K线
            past_candles = candles[candles["dt"] <= sample_dt]
            if past_candles.empty:
                continue

            last_idx = past_candles.index[-1]
            future_ret = candles.loc[last_idx, "future_return"]

            if pd.isna(future_ret):
                continue  # 未来K线不足

            df.at[idx, "_future_return"] = float(future_ret)
            sample_count += 1

        new_labeled += sample_count
        print(f"  [OK] {symbol}: 新增标注 {sample_count} 个样本（K线 {len(candles)} 根）")

    # 保存回文件
    _save_samples(df)

    result = {
        "total": total,
        "already_labeled": int(already_labeled),
        "new_labeled": new_labeled,
        "total_labeled": int(already_labeled) + new_labeled,
        "lookahead_days": lookahead_days,
    }
    print(f"\n标注完成：新增 {new_labeled} 个，总计 {result['total_labeled']} 个已标注")
    return result


def train_from_collected(lookahead_days: int = 7, test_ratio: float = 0.3) -> Dict:
    """从已收集样本训练集成模型

    1. 先标注样本（如果有未标注的）
    2. 调用 train_ensemble() 训练

    参数:
        lookahead_days: 前瞻天数
        test_ratio: 测试集比例

    返回:
        训练结果 dict
    """
    # 先标注
    label_result = label_collected_samples(lookahead_days=lookahead_days)
    if "error" in label_result:
        return label_result

    # 训练
    try:
        try:
            from ml.algo_ensemble import train_ensemble
        except ImportError:
            sys.path.insert(0, str(TREND_SYSTEM))
            from ml.algo_ensemble import train_ensemble

        result = train_ensemble(label_lookahead=lookahead_days, test_ratio=test_ratio)
        return {"label": label_result, "train": result}
    except Exception as e:
        return {"error": f"训练失败: {e}"}


# ── 命令行入口 ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="集成模型样本标注与训练工具")
    parser.add_argument("--lookahead", type=int, default=7, help="前瞻天数（默认7）")
    parser.add_argument("--train", action="store_true", help="标注后训练模型")
    parser.add_argument("--test-ratio", type=float, default=0.3, help="测试集比例（默认0.3）")
    parser.add_argument("--list", action="store_true", help="仅列出样本统计，不标注")
    args = parser.parse_args()

    if args.list:
        df = _load_all_samples()
        if df.empty:
            print("暂无样本")
            return
        print(f"总样本数: {len(df)}")
        if "_symbol" in df.columns:
            print("按币种统计:")
            for sym, cnt in df["_symbol"].value_counts().items():
                labeled = df[df["_symbol"] == sym]["_future_return"].notna().sum() if "_future_return" in df.columns else 0
                print(f"  {sym}: {cnt} 个（已标注 {labeled}）")
        return

    if args.train:
        result = train_from_collected(
            lookahead_days=args.lookahead,
            test_ratio=args.test_ratio,
        )
    else:
        result = label_collected_samples(lookahead_days=args.lookahead)

    print("\n" + json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
