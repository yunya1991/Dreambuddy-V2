"""fh CLI — FeatureHub 命令行工具

命令：
  fh list                              列出所有模块和启用集合
  fh inspect --set <name>               检查集合的列数/模块/血缘
  fh run-sample --set <name> --symbol S 用合成数据跑一次特征
  fh export-schema --set <name>        导出 JSON schema
"""
from __future__ import annotations

import json
import sys
from typing import List, Optional

import numpy as np
import pandas as pd


def _make_sample_ohlcv(n: int = 300, symbol: str = "BTC") -> pd.DataFrame:
    """生成 n 行合成 OHLCV 数据用于 inspect / run-sample。"""
    rng = np.random.default_rng(hash(symbol) % 2**32)
    t = np.linspace(100, 200, n) * (1 + rng.normal(0, 0.01, n))
    idx = pd.date_range("2021-01-01", periods=n, freq="D")
    return pd.DataFrame({
        "open":   t * (1 + rng.normal(0, 0.004, n)),
        "high":   t * (1 + np.abs(rng.normal(0, 0.01, n))),
        "low":    t * (1 - np.abs(rng.normal(0, 0.01, n))),
        "close":  t,
        "volume": 1e6 * (1 + rng.uniform(-0.5, 1.0, n)),
    }, index=idx)


def _build_pipeline():
    """构建 FeaturePipeline 并注册模块 + 集合。"""
    from feature_hub.pipeline.feature_pipeline import FeaturePipeline
    from feature_hub.modules.loader import load_default_sets

    pipe = FeaturePipeline()
    load_default_sets(pipe)
    return pipe


# ============================================================
# fh list
# ============================================================
def _cmd_list() -> int:
    pipe = _build_pipeline()
    print("Modules:")
    for name in sorted(pipe._modules.keys()):
        print(f"  - {name}")
    print("\nEnabled Sets:")
    for name in sorted(pipe._sets.keys()):
        mods = pipe._sets[name]
        print(f"  - {name}: {', '.join(mods) if mods else '(all)'}")
    return 0


# ============================================================
# fh inspect --set <name>
# ============================================================
def _cmd_inspect(set_name: str) -> int:
    pipe = _build_pipeline()
    df = _make_sample_ohlcv(symbol="BTC")

    fv = pipe.run(set_name=set_name, df=df, symbol="BTC")
    cols = list(fv.df.columns)

    print(f"Set: {set_name}")
    print(f"Actual columns: {len(cols)}")
    print(f"Columns: {', '.join(cols[:20])}{'...' if len(cols) > 20 else ''}")
    mods = fv.meta.get("modules_run", [])
    print(f"Modules run: {', '.join(mods) if mods else '(none)'}")
    failed = fv.meta.get("modules_failed", [])
    if failed:
        print(f"Modules failed: {', '.join(failed)}")
    print(f"Lineage: OK")
    return 0


# ============================================================
# fh run-sample --set <name> --symbol <symbol>
# ============================================================
def _cmd_run_sample(set_name: str, symbol: str = "BTC") -> int:
    pipe = _build_pipeline()
    df = _make_sample_ohlcv(symbol=symbol)

    fv = pipe.run(set_name=set_name, df=df, symbol=symbol)
    mods = fv.meta.get("modules_run", [])

    print(f"Set: {set_name}")
    print(f"Symbol: {symbol}")
    print(f"Rows: {len(fv.df)}")
    print(f"Columns: {len(fv.df.columns)}")
    print(f"Modules run: {', '.join(mods) if mods else '(none)'}")
    return 0


# ============================================================
# fh export-schema --set <name>
# ============================================================
def _cmd_export_schema(set_name: str) -> int:
    pipe = _build_pipeline()
    df = _make_sample_ohlcv(symbol="BTC")

    fv = pipe.run(set_name=set_name, df=df, symbol="BTC")
    cols = list(fv.df.columns)

    schema = {
        "set_name": set_name,
        "columns": cols,
        "column_count": len(cols),
        "modules_run": fv.meta.get("modules_run", []),
    }
    print(json.dumps(schema, ensure_ascii=False, indent=2))
    return 0


# ============================================================
# main 入口
# ============================================================
def main(argv: Optional[List[str]] = None) -> int:
    """CLI 主入口。

    Returns:
        0 成功，1 错误。
    """
    args = argv if argv is not None else sys.argv[1:]

    if not args:
        print("Usage: fh <command> [options]")
        print("Commands: list, inspect, run-sample, export-schema")
        return 1

    cmd = args[0]

    if cmd == "list":
        return _cmd_list()

    if cmd == "inspect":
        set_name = ""
        for i, a in enumerate(args[1:], 1):
            if a == "--set" and i + 1 < len(args):
                set_name = args[i + 1]
        if not set_name:
            print("Usage: fh inspect --set <name>")
            return 1
        return _cmd_inspect(set_name)

    if cmd == "run-sample":
        set_name = ""
        symbol = "BTC"
        i = 1
        while i < len(args):
            if args[i] == "--set" and i + 1 < len(args):
                set_name = args[i + 1]
                i += 2
            elif args[i] == "--symbol" and i + 1 < len(args):
                symbol = args[i + 1]
                i += 2
            else:
                i += 1
        if not set_name:
            print("Usage: fh run-sample --set <name> [--symbol <symbol>]")
            return 1
        return _cmd_run_sample(set_name, symbol)

    if cmd == "export-schema":
        set_name = ""
        for i, a in enumerate(args[1:], 1):
            if a == "--set" and i + 1 < len(args):
                set_name = args[i + 1]
        if not set_name:
            print("Usage: fh export-schema --set <name>")
            return 1
        return _cmd_export_schema(set_name)

    print(f"Unknown command: {cmd}")
    print("Commands: list, inspect, run-sample, export-schema")
    return 1


if __name__ == "__main__":
    sys.exit(main())
