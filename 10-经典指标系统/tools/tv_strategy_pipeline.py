from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_seg(raw: str, fallback: str = "x", max_len: int = 80) -> str:
    s = (raw or "").strip()
    if not s:
        return fallback
    out = []
    last_us = False
    for ch in s:
        ok = ("a" <= ch <= "z") or ("A" <= ch <= "Z") or ("0" <= ch <= "9") or ch in {"_", "-", "."}
        if ok:
            out.append(ch)
            last_us = False
        else:
            if not last_us:
                out.append("_")
                last_us = True
    v = "".join(out).strip("._-")
    if not v:
        v = fallback
    return v[:max_len]


def _pascal(name: str) -> str:
    parts = re.split(r"[^a-zA-Z0-9]+", name or "")
    parts = [p for p in parts if p]
    if not parts:
        return "TvImportedStrategy"
    out = "".join(p[:1].upper() + p[1:] for p in parts)
    if out[0].isdigit():
        out = f"Tv{out}"
    return out


def _sha256_bytes(b: bytes) -> str:
    h = hashlib.sha256()
    h.update(b)
    return h.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json_file(path: Path | None, default: Any) -> Any:
    if path is None or (not path.is_file()):
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _read_text_file(path: Path | None, default: str) -> str:
    if path is None or (not path.is_file()):
        return default
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return default


def _clipboard_text() -> str:
    try:
        p = subprocess.run(["pbpaste"], capture_output=True, text=True, check=False)
        if p.returncode == 0:
            return p.stdout or ""
    except Exception:
        return ""
    return ""


def _infer_can_short(pine_text: str) -> bool:
    low = pine_text.lower()
    return ("strategy.short" in low) or ("short" in low and "strategy.entry" in low)


def _looks_like_pine(pine_text: str) -> bool:
    low = (pine_text or "").lower()
    if not low.strip():
        return False
    if "@version" in low:
        return True
    if "indicator(" in low or "strategy(" in low:
        return True
    return False


def _build_strategy_code(class_name: str, timeframe: str, can_short: bool) -> str:
    tf = timeframe or "1h"
    short_flag = "True" if can_short else "False"
    short_block = ""
    short_exit_block = ""
    if can_short:
        short_block = """
        dataframe.loc[
            (
                (dataframe["rsi"] > self.sell_rsi.value) &
                (dataframe["close"] > dataframe["bb_upperband"]) &
                (dataframe["volume"] > 0)
            ),
            ["enter_short", "enter_tag"]
        ] = [1, "tv_short"]
"""
        short_exit_block = """
        dataframe.loc[
            (
                (dataframe["rsi"] < self.buy_rsi.value) |
                (dataframe["close"] < dataframe["bb_middleband"])
            ),
            "exit_short"
        ] = 1
"""
    return f"""import numpy as np
from pandas import DataFrame
from typing import Any, Dict, Optional
from datetime import datetime

from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter, stoploss_from_open
import talib.abstract as ta
from technical import qtpylib


class {class_name}(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "{tf}"
    can_short: bool = {short_flag}
    minimal_roi = {{"0": 0.03, "120": 0.01, "300": 0.0}}
    stoploss = -0.12
    use_custom_stoploss = False
    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    startup_candle_count: int = 50
    buy_rsi = IntParameter(20, 40, default=30, space="buy")
    sell_rsi = IntParameter(60, 85, default=70, space="sell")
    bb_std = DecimalParameter(1.5, 3.0, default=2.0, space="buy")
    order_types = {{
        "entry": "limit",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": False
    }}
    order_time_in_force = {{"entry": "GTC", "exit": "GTC"}}

    @property
    def plot_config(self) -> Dict[str, Any]:
        return {{
            "main_plot": {{
                "bb_lowerband": {{}},
                "bb_middleband": {{}},
                "bb_upperband": {{}}
            }},
            "subplots": {{
                "RSI": {{
                    "rsi": {{}}
                }}
            }}
        }}

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        bollinger = qtpylib.bollinger_bands(qtpylib.typical_price(dataframe), window=20, stds=float(self.bb_std.value))
        dataframe["bb_lowerband"] = bollinger["lower"]
        dataframe["bb_middleband"] = bollinger["mid"]
        dataframe["bb_upperband"] = bollinger["upper"]
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"] = 0
        dataframe["enter_short"] = 0
        dataframe["enter_tag"] = ""
        dataframe.loc[
            (
                (dataframe["rsi"] < self.buy_rsi.value) &
                (dataframe["close"] < dataframe["bb_lowerband"]) &
                (dataframe["volume"] > 0)
            ),
            ["enter_long", "enter_tag"]
        ] = [1, "tv_long"]
{short_block}
        conflict = (dataframe["enter_long"] == 1) & (dataframe["enter_short"] == 1)
        dataframe.loc[conflict, ["enter_long", "enter_short", "enter_tag"]] = [0, 0, ""]
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        dataframe["exit_short"] = 0
        dataframe.loc[
            (
                (dataframe["rsi"] > self.sell_rsi.value) |
                (dataframe["close"] > dataframe["bb_middleband"])
            ),
            "exit_long"
        ] = 1
{short_exit_block}
        return dataframe
"""


@dataclass
class BacktestResult:
    returncode: int
    stdout: str
    stderr: str
    command: list[str]


def _run_backtest(
    project_root: Path,
    config_path: Path,
    strategy_path: Path,
    strategy_class: str,
    timeframe: str,
    timerange: str,
) -> BacktestResult:
    cmd = [
        "freqtrade",
        "backtesting",
        "--config",
        str(config_path),
        "--strategy-path",
        str(strategy_path),
        "--strategy",
        strategy_class,
        "--timeframe",
        timeframe,
    ]
    if timerange:
        cmd.extend(["--timerange", timerange])
    p = subprocess.run(cmd, cwd=str(project_root), capture_output=True, text=True)
    return BacktestResult(returncode=int(p.returncode), stdout=p.stdout or "", stderr=p.stderr or "", command=cmd)


def _extract_float(patterns: list[str], text: str) -> float | None:
    out: list[float] = []
    for pat in patterns:
        for m in re.finditer(pat, text, flags=re.IGNORECASE | re.MULTILINE):
            try:
                out.append(float(m.group(1)))
            except Exception:
                continue
    if not out:
        return None
    return out[-1]


def _extract_int(patterns: list[str], text: str) -> int | None:
    out: list[int] = []
    for pat in patterns:
        for m in re.finditer(pat, text, flags=re.IGNORECASE | re.MULTILINE):
            try:
                out.append(int(m.group(1)))
            except Exception:
                continue
    if not out:
        return None
    return max(out)


def _parse_metrics(stdout: str, stderr: str) -> dict[str, Any]:
    text = (stdout or "") + "\n" + (stderr or "")
    return {
        "win_rate_pct": _extract_float([r"win(?:ning)?\s*(?:rate|%)\s*[:=]?\s*(-?\d+(?:\.\d+)?)\s*%"], text),
        "sharpe": _extract_float([r"sharpe(?:\s*ratio)?\s*[:=]?\s*(-?\d+(?:\.\d+)?)"], text),
        "max_drawdown_pct": _extract_float([r"(?:max(?:imum)?\s*drawdown|max\s*drawdown|drawdown)\s*[:=]?\s*(-?\d+(?:\.\d+)?)\s*%"], text),
        "total_trades": _extract_int([r"(?:total\s*trades|trades)\s*[:=]?\s*(\d+)"], text),
    }


def _write_checksums(base_dir: Path, file_paths: list[Path]) -> Path:
    checksums = {}
    for fp in file_paths:
        if fp.is_file():
            rel = str(fp.relative_to(base_dir))
            checksums[rel] = _sha256_bytes(fp.read_bytes())
    out_path = base_dir / "checksums" / "sha256.json"
    _write_json(out_path, {"generated_at": _now_iso(), "sha256": checksums})
    return out_path


def _strategy_key(strategy_name: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"{_safe_seg(strategy_name, fallback='tv_strategy', max_len=80)}__{ts}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-root", default="/Users/zhangjiangtao/ft_userdata/经典指标机器学习系统")
    ap.add_argument("--strategy-name", required=True)
    ap.add_argument("--strategy-key", default="")
    ap.add_argument("--visibility-type", default="open", choices=["open", "protected", "invite_only", "built_in"])
    ap.add_argument("--is-author", action="store_true")
    ap.add_argument("--source-visible", action="store_true")
    ap.add_argument("--pine-file", default="")
    ap.add_argument("--pine-clipboard", action="store_true")
    ap.add_argument("--tv-url", default="")
    ap.add_argument("--timeframe", default="1h")
    ap.add_argument("--timerange", default="20240101-20251231")
    ap.add_argument("--config", default="user_data/config_local_backtest.json")
    ap.add_argument("--alerts-json", default="")
    ap.add_argument("--strategy-report-md", default="")
    ap.add_argument("--params-json", default="")
    ap.add_argument("--skip-backtest", action="store_true")
    ns = ap.parse_args()

    project_root = Path(ns.project_root).resolve()
    key = ns.strategy_key.strip() or _strategy_key(ns.strategy_name)
    base_dir = project_root / "user_data" / "strategies" / "tradingview" / "research" / key
    source_dir = base_dir / "source"
    source_dir.mkdir(parents=True, exist_ok=True)

    pine_text = ""
    pine_path = Path(ns.pine_file).resolve() if ns.pine_file else None
    if pine_path and pine_path.is_file():
        pine_text = pine_path.read_text(encoding="utf-8")
    if ns.pine_clipboard and (not pine_text):
        pine_text = _clipboard_text()

    source_visible = bool(ns.source_visible)
    if not source_visible:
        if ns.visibility_type == "open":
            source_visible = True
        elif ns.visibility_type == "built_in" and bool(ns.is_author):
            source_visible = True
        elif bool(ns.is_author) and ns.visibility_type in {"protected", "invite_only"}:
            source_visible = True
    if source_visible and (not _looks_like_pine(pine_text)):
        source_visible = False

    meta = {
        "strategy_key": key,
        "strategy_name": ns.strategy_name,
        "visibility_type": ns.visibility_type,
        "is_author": bool(ns.is_author),
        "source_visible": bool(source_visible),
        "tv_url": ns.tv_url,
        "created_at": _now_iso(),
        "path_type": "A" if source_visible else "B",
    }
    meta_path = source_dir / "meta.json"
    _write_json(meta_path, meta)

    files_for_checksum: list[Path] = [meta_path]
    output: dict[str, Any] = {"ok": True, "path_type": meta["path_type"], "strategy_key": key, "base_dir": str(base_dir)}

    if source_visible:
        pine_dir = source_dir / "pine"
        pine_dir.mkdir(parents=True, exist_ok=True)
        original_pine = pine_dir / "original.pine"
        original_pine.write_text(pine_text, encoding="utf-8")
        files_for_checksum.append(original_pine)

        class_name = _pascal(ns.strategy_name) + "TvStrategy"
        strategy_dir = base_dir / "strategy"
        strategy_dir.mkdir(parents=True, exist_ok=True)
        strategy_path = strategy_dir / f"{class_name}.py"
        strategy_code = _build_strategy_code(class_name, ns.timeframe, _infer_can_short(pine_text))
        strategy_path.write_text(strategy_code, encoding="utf-8")
        files_for_checksum.append(strategy_path)

        backtest_dir = base_dir / "backtest"
        backtest_dir.mkdir(parents=True, exist_ok=True)
        bt_meta_path = backtest_dir / "metadata.json"
        bt_stdout = backtest_dir / "stdout.log"
        bt_stderr = backtest_dir / "stderr.log"
        bt_report = backtest_dir / "report.md"
        cfg_snapshot = backtest_dir / "config.snapshot.json"
        config_path = (project_root / ns.config).resolve() if not Path(ns.config).is_absolute() else Path(ns.config).resolve()
        if config_path.is_file():
            cfg_snapshot.write_text(config_path.read_text(encoding="utf-8"), encoding="utf-8")
            files_for_checksum.append(cfg_snapshot)
        bt_result = None
        if not ns.skip_backtest:
            bt_result = _run_backtest(project_root, config_path, strategy_dir, class_name, ns.timeframe, ns.timerange)
            bt_stdout.write_text(bt_result.stdout, encoding="utf-8")
            bt_stderr.write_text(bt_result.stderr, encoding="utf-8")
            files_for_checksum.extend([bt_stdout, bt_stderr])
        metrics = _parse_metrics(bt_result.stdout if bt_result else "", bt_result.stderr if bt_result else "")
        bt_meta = {
            "strategy_key": key,
            "strategy_class": class_name,
            "returncode": bt_result.returncode if bt_result else None,
            "metrics": metrics,
            "command": bt_result.command if bt_result else [],
            "created_at": _now_iso(),
        }
        _write_json(bt_meta_path, bt_meta)
        files_for_checksum.append(bt_meta_path)
        report_lines = [
            f"# TV Import Backtest - {key}",
            "",
            f"- Strategy Class: {class_name}",
            f"- Return Code: {bt_meta['returncode']}",
            f"- Win Rate: {metrics.get('win_rate_pct')}",
            f"- Sharpe: {metrics.get('sharpe')}",
            f"- Max Drawdown: {metrics.get('max_drawdown_pct')}",
            f"- Total Trades: {metrics.get('total_trades')}",
            "",
        ]
        bt_report.write_text("\n".join(report_lines), encoding="utf-8")
        files_for_checksum.append(bt_report)
        output["strategy_path"] = str(strategy_path)
        output["backtest_metadata"] = str(bt_meta_path)
    else:
        blackbox_dir = base_dir / "blackbox"
        blackbox_dir.mkdir(parents=True, exist_ok=True)
        alerts = _read_json_file(Path(ns.alerts_json).resolve() if ns.alerts_json else None, [])
        params_snapshot = _read_json_file(Path(ns.params_json).resolve() if ns.params_json else None, {})
        strategy_report = _read_text_file(Path(ns.strategy_report_md).resolve() if ns.strategy_report_md else None, "")
        alerts_path = blackbox_dir / "alerts.json"
        params_path = blackbox_dir / "params_snapshot.json"
        report_path = blackbox_dir / "strategy_report.md"
        notes_path = blackbox_dir / "execution_notes.md"
        _write_json(alerts_path, alerts)
        _write_json(params_path, params_snapshot)
        report_path.write_text(strategy_report, encoding="utf-8")
        notes_path.write_text("source_not_visible=true\nblackbox_asset=true\n", encoding="utf-8")
        files_for_checksum.extend([alerts_path, params_path, report_path, notes_path])
        output["blackbox"] = {
            "alerts_path": str(alerts_path),
            "params_snapshot_path": str(params_path),
            "strategy_report_path": str(report_path),
        }

    checksum_path = _write_checksums(base_dir, files_for_checksum)
    output["checksums"] = str(checksum_path)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
