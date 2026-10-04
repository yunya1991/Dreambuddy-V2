"""策略工厂 Freqtrade 执行模块。

动态加载 IStrategy 子类，调用 populate_indicators/entry/exit 三钩子产生信号。
"""
from __future__ import annotations

import contextlib
import importlib
import os
from typing import Any, Dict, List, Optional

try:
    import pandas as pd
except Exception:
    pd = None


def _dep(name: str):
    import ml_trade_service as _mts
    return getattr(_mts, name)


def _run_freqtrade_strategy_signal_hyperliquid(
    strategy_module: str,
    class_name: str,
    coin: str,
    param_names: Optional[List[str]] = None,
) -> Dict[str, Any]:
    if pd is None:
        return {"ok": False, "error": "pandas_unavailable"}

    # 延迟获取大文件依赖
    _hl_coin_from_pair = _dep("_hl_coin_from_pair")
    _now_ms = _dep("_now_ms")
    _json_sanitize = _dep("_json_sanitize")
    _ensure_freqtrade_shims = _dep("_ensure_freqtrade_shims")
    _ensure_technical_shims = _dep("_ensure_technical_shims")
    _InlineDataProvider = _dep("_InlineDataProvider")
    _instantiate_strategy = _dep("_instantiate_strategy")
    _extract_params = _dep("_extract_params")
    _last_closed_bar_pos_from_df = _dep("_last_closed_bar_pos_from_df")

    try:
        _ensure_freqtrade_shims()
        _ensure_technical_shims()
    except Exception as e:
        return {"ok": False, "error": f"shim_failed:{e}"}

    try:
        mod = importlib.import_module(str(strategy_module))
        cls = getattr(mod, str(class_name))
    except Exception as e:
        return {"ok": False, "error": f"strategy_import_failed:{e}", "module": str(strategy_module), "class": str(class_name)}

    pair = f"{_hl_coin_from_pair(coin)}-PERP"
    dp = _InlineDataProvider(base_pair=pair)
    try:
        strat = _instantiate_strategy(cls)
        setattr(strat, "dp", dp)
        setattr(strat, "config", {"trading_mode": "futures", "exchange": {"name": "hyperliquid"}})
    except Exception as e:
        return {"ok": False, "error": f"strategy_init_failed:{e}"}

    @contextlib.contextmanager
    def _suppress_strategy_export_env():
        keys = [
            "ML_EXPORT_URL",
            "ML_FEATURE_EXPORT_URL",
            "ML_EXPORT_TRIGGER_DECISION",
            "ML_EXPORT_THRESHOLD",
            "ML_EXPORT_SIZE",
        ]
        saved: Dict[str, Any] = {}
        for k in keys:
            saved[k] = os.environ.get(k) if k in os.environ else None
            os.environ[k] = ""
        try:
            yield
        finally:
            for k, v in saved.items():
                if v is None:
                    try:
                        if k in os.environ:
                            del os.environ[k]
                    except Exception:
                        pass
                else:
                    os.environ[k] = str(v)

    try:
        params = _extract_params(strat, list(param_names or []))
        tf = str(getattr(strat, "timeframe", "1h"))
        base_df = dp.get_pair_dataframe(pair, tf)
        if base_df is None:
            return {"ok": False, "error": "no_candles", "pair": pair, "timeframe": tf}
        need = int(getattr(strat, "startup_candle_count", 200) or 200)
        if len(base_df) < need:
            return {"ok": False, "error": "insufficient_candles", "pair": pair, "timeframe": tf, "count": int(len(base_df)), "need": int(need)}

        meta = {"pair": pair}
        with _suppress_strategy_export_env():
            df = strat.populate_indicators(base_df.copy(), meta)
            df = strat.populate_entry_trend(df, meta)
            try:
                if hasattr(strat, "populate_exit_trend"):
                    df = strat.populate_exit_trend(df, meta)
            except Exception:
                pass
        if df is None or df.empty:
            return {"ok": False, "error": "strategy_no_output"}

        now_ms = _now_ms()
        pos, row, bar_open_ms, bar_close_ms = _last_closed_bar_pos_from_df(df, tf, now_ms=now_ms)
        prev_row = None
        try:
            if pos > 0:
                prev_row = df.iloc[int(pos) - 1]
        except Exception:
            prev_row = None

        def _flag(v: Any) -> int:
            try:
                if v is None:
                    return 0
                if pd is not None and pd.isna(v):
                    return 0
                if isinstance(v, bool):
                    return 1 if v else 0
                return int(v)
            except Exception:
                return 0

        enter_long = _flag(row.get("enter_long", 0))
        enter_short = _flag(row.get("enter_short", 0))
        buy_flag = _flag(row.get("buy", 0))
        if enter_long == 0 and enter_short == 0 and buy_flag == 1:
            enter_long = 1
        side = None
        if enter_short == 1:
            side = "short"
        elif enter_long == 1:
            side = "long"
        tag = row.get("enter_tag")
        tag_s = "" if tag is None else str(tag)
        if (not tag_s.strip()) and ("buy_tag" in df.columns):
            tag = row.get("buy_tag")

        return {
            "ok": True,
            "coin": _hl_coin_from_pair(coin),
            "pair": pair,
            "timeframe": str(tf),
            "ts": int(bar_open_ms),
            "bar_open_ms": int(bar_open_ms),
            "bar_close_ms": int(bar_close_ms),
            "bar_closed": True,
            "side": side,
            "tag": (None if tag is None or (pd is not None and pd.isna(tag)) else str(tag)),
            "row": _json_sanitize(row.to_dict() if hasattr(row, "to_dict") else {}),
            "prev_row": _json_sanitize(prev_row.to_dict() if prev_row is not None and hasattr(prev_row, "to_dict") else {}),
            "params": _json_sanitize(dict(params or {})),
        }
    except Exception as e:
        return {"ok": False, "error": f"strategy_run_failed:{e}"}


__all__ = ["_run_freqtrade_strategy_signal_hyperliquid"]
