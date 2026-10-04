"""策略工厂 Gate 检查辅助。

加载最新回测报告，供 gate 校验（pf/dd/trades/winrate 阈值）使用。
依赖大文件中的回测函数（_backtest_* / _bt_* / _eval_*）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional


def _dep(name):
    import ml_trade_service as _mts
    return getattr(_mts, name)

# 懒加载包装
def _now_ms(*a, **k): return _dep("_now_ms")(*a, **k)
def _backtest_zip_metrics(*a, **k): return _dep("_backtest_zip_metrics")(*a, **k)
def _bt_aligned_metrics_from_zip(*a, **k): return _dep("_bt_aligned_metrics_from_zip")(*a, **k)
def _bt_metrics_pick_strategy(*a, **k): return _dep("_bt_metrics_pick_strategy")(*a, **k)
def _bt_metrics_slim(*a, **k): return _dep("_bt_metrics_slim")(*a, **k)
def _eval_standard_pack(*a, **k): return _dep("_eval_standard_pack")(*a, **k)


def _backtest_pick_latest_zip_path() -> Optional[Path]:
    try:
        from ml_trade_service import _backtest_last_result_zip_name, _backtests_dir
        name = _backtest_last_result_zip_name()
        if name:
            p = _backtests_dir() / name
            if p.exists():
                return p
        zips = list(_backtests_dir().glob("*.zip"))
        if not zips:
            return None
        zips.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        return zips[0]
    except Exception:
        return None


def _backtest_report_from_zip(
    zip_path: Optional[Path],
    strategy: Optional[str] = None,
    policy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if zip_path is None:
        return {"ok": False, "error": "no_backtest_zip"}
    p = Path(zip_path)
    if (not p.exists()) or (not p.is_file()):
        return {"ok": False, "error": "backtest_zip_not_found", "zip": str(p.name)}
    try:
        from ml_trade_service import (
            _backtest_zip_metrics,
            _bt_metrics_pick_strategy,
            _bt_metrics_slim,
            _bt_aligned_metrics_from_zip,
            _eval_standard_pack,
        )
        from classic_pipeline.core.runtime import _now_ms
    except Exception:
        return {"ok": False, "error": "backtest_import_failed"}
    metrics = _backtest_zip_metrics(p)
    picked = _bt_metrics_pick_strategy(metrics, strategy)
    summary = _bt_metrics_slim(picked)
    aligned = None
    aligned_eval = None
    try:
        aligned = _bt_aligned_metrics_from_zip(p, strategy=strategy)
    except Exception:
        aligned = None
    try:
        if isinstance(aligned, dict) and bool(aligned.get("ok")):
            aligned_eval = _eval_standard_pack(aligned, policy=policy)
    except Exception:
        aligned_eval = None
    return {
        "ok": True,
        "ts": _now_ms(),
        "kind": "freqtrade_backtest",
        "zip": str(p.name),
        "strategy": (None if strategy is None else str(strategy)),
        "metrics_summary": summary,
        "metrics": metrics,
        "aligned_metrics": aligned,
        "eval": aligned_eval,
        "source": {
            "zip": str(p.name),
            "has_metrics": bool(metrics),
            "has_metrics_summary": bool(summary),
            "has_aligned_metrics": bool(aligned) if isinstance(aligned, dict) else False,
        },
    }


__all__ = ["_backtest_pick_latest_zip_path", "_backtest_report_from_zip"]
