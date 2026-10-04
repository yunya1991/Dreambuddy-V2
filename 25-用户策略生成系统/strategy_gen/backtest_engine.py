"""
25-用户策略生成系统 - 回测验证引擎（P0 实现）

调用 Freqtrade backtesting CLI 执行回测，解析 JSON 输出返回 metrics_summary。

设计原则：
- subprocess 调用 freqtrade CLI（而非 import Python API），避免 FastAPI 兼容性污染
- 每个回测独立进程，互不干扰
- 回测结果 JSON 存 user_data/backtest_results/，M27 gate 可直接读取
- FAIL-OPEN：异常时返回 ok=False 不阻断上层
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# 常量配置
# ---------------------------------------------------------------------------

# Freqtrade 可执行文件
_FREQTRADE_BIN = os.environ.get("FREQTRADE_BIN", "/opt/anaconda3/bin/freqtrade")

# 经典系统根目录（10-经典指标系统）
_CLASSIC_ROOT = Path(__file__).resolve().parents[2] / "10-经典指标系统"
_USER_DATA_DIR = _CLASSIC_ROOT / "user_data"
_STRATEGIES_DIR = _USER_DATA_DIR / "strategies"
# Freqtrade `--datadir` 应指向 exchange 目录（数据按 {pair}-{tf}.json 组织）
# 数据文件位置: user_data/data/okx/BTC_USDT-1h.json
_DATA_DIR = _USER_DATA_DIR / "data" / "okx"
_BACKTEST_RESULTS_DIR = _USER_DATA_DIR / "backtest_results"
_TEMP_CONFIG_DIR = _USER_DATA_DIR / "tmp_configs"
_TEMP_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

# 默认回测参数
_DEFAULT_TIMEFRAME = "1h"
_DEFAULT_TIMERANGE = "20260422-20260721"
_DEFAULT_PAIRS = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
_DEFAULT_STAKE_AMOUNT = 60
_DEFAULT_MAX_OPEN_TRADES = 3
_DEFAULT_FEE = 0.0015

# 回测超时（秒）
_BACKTEST_TIMEOUT = int(os.environ.get("FREQTRADE_BACKTEST_TIMEOUT", "600"))


# ---------------------------------------------------------------------------
# 策略文件定位
# ---------------------------------------------------------------------------

def _resolve_strategy_path(strategy_id: str, source_zip: Optional[str] = None) -> Optional[Path]:
    """定位策略 Python 文件。

    优先级：
    1. source_zip 指定的 zip 包（解压到临时目录）
    2. strategies 目录下与 strategy_id 同名的 .py 文件
    3. strategies 目录下包含该类名的 .py 文件
    """
    # 1. 从 strategies 目录查找
    if _STRATEGIES_DIR.exists():
        # 同名文件
        same_name = _STRATEGIES_DIR / f"{strategy_id}.py"
        if same_name.exists():
            return same_name
        # 类名匹配
        for f in _STRATEGIES_DIR.glob("*.py"):
            if f.name == "__init__.py":
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
                if f"class {strategy_id}" in text:
                    return f
            except Exception:
                continue

    # 2. TODO: 从 source_zip 解压（Phase 2）
    if source_zip:
        zip_path = Path(source_zip)
        if zip_path.exists():
            extract_dir = _TEMP_CONFIG_DIR / f"unzip_{uuid.uuid4().hex[:8]}"
            extract_dir.mkdir(parents=True, exist_ok=True)
            shutil.unpack_archive(str(zip_path), str(extract_dir))
            for f in extract_dir.rglob("*.py"):
                try:
                    text = f.read_text(encoding="utf-8", errors="ignore")
                    if f"class {strategy_id}" in text:
                        return f
                except Exception:
                    continue
    return None


# ---------------------------------------------------------------------------
# 临时 config 构建
# ---------------------------------------------------------------------------

def _build_backtest_config(
    strategy_name: str,
    *,
    timeframe: str = _DEFAULT_TIMEFRAME,
    timerange: str = _DEFAULT_TIMERANGE,
    pairs: Optional[list] = None,
    stake_amount: float = _DEFAULT_STAKE_AMOUNT,
    max_open_trades: int = _DEFAULT_MAX_OPEN_TRADES,
    fee: float = _DEFAULT_FEE,
    **extra: Any,
) -> Path:
    """构建临时回测 config，返回 config 文件路径。"""
    pairs = pairs or _DEFAULT_PAIRS
    config = {
        "max_open_trades": max_open_trades,
        "trading_mode": "spot",
        "stake_currency": "USDT",
        "stake_amount": stake_amount,
        "dry_run": True,
        "fee": fee,
        "exchange": {
            "name": "okx",
            "key": "",
            "secret": "",
            "password": "",
            "skip_pair_validation": True,
            "markets": "",
            "ccxt_config": {
                "enableRateLimit": True,
                "rateLimit": 2500,
                "options": {"defaultType": "spot"},
            },
            "pair_whitelist": pairs,
        },
        "pairlists": [{"method": "StaticPairList"}],
        "entry_pricing": {
            "price_side": "other",
            "use_order_book": True,
            "order_book_top": 1,
        },
        "exit_pricing": {
            "price_side": "other",
            "use_order_book": True,
            "order_book_top": 1,
        },
        "api_server": {
            "enabled": False,
            "listen_ip_address": "127.0.0.1",
            "listen_port": 8080,
            "username": "x",
            "password": "x",
        },
        "strategy": strategy_name,
        "timeframe": timeframe,
        "dataformat_ohlcv": "json",
        "internals": {"process_throttle_secs": 5},
    }
    # 允许 extra 覆盖
    config.update({k: v for k, v in extra.items() if v is not None})

    config_path = _TEMP_CONFIG_DIR / f"bt_{strategy_name}_{uuid.uuid4().hex[:8]}.json"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return config_path


# ---------------------------------------------------------------------------
# Freqtrade CLI 调用
# ---------------------------------------------------------------------------

def _run_freqtrade_backtest(
    config_path: Path,
    strategy_name: str,
    *,
    timerange: str,
    pairs: Optional[list] = None,
    export: str = "trades",
) -> Dict[str, Any]:
    """调用 freqtrade backtesting CLI，返回 subprocess 结果。"""
    cmd = [
        _FREQTRADE_BIN, "backtesting",
        "--config", str(config_path),
        "--strategy", strategy_name,
        "--userdir", str(_USER_DATA_DIR),
        "--datadir", str(_DATA_DIR),
        "--timerange", timerange,
        "--data-format-ohlcv", "json",
        "--export", export,
    ]
    if pairs:
        cmd.extend(["--pairs", *pairs])

    env = os.environ.copy()
    env["PYTHONPATH"] = str(_CLASSIC_ROOT)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_BACKTEST_TIMEOUT,
            env=env,
            cwd=str(_CLASSIC_ROOT),
        )
        return {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "ok": result.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        return {"returncode": -1, "stdout": "", "stderr": "timeout", "ok": False}
    except Exception as e:
        return {"returncode": -2, "stdout": "", "stderr": str(e), "ok": False}


# ---------------------------------------------------------------------------
# 回测结果解析
# ---------------------------------------------------------------------------

def _find_latest_backtest_result() -> Optional[Path]:
    """找到最新的回测结果文件（.zip 或 .json）。"""
    if not _BACKTEST_RESULTS_DIR.exists():
        return None
    # Freqtrade 新版本默认输出 .zip
    results = list(_BACKTEST_RESULTS_DIR.glob("backtest-result*.zip"))
    if not results:
        # 兼容旧版 .json
        results = list(_BACKTEST_RESULTS_DIR.glob("backtest-result*.json"))
        results = [r for r in results if not r.name.endswith(".meta.json")]
    if not results:
        return None
    results.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return results[0]


def _read_backtest_result(result_file: Path) -> Dict[str, Any]:
    """读取回测结果文件，支持 .zip 和 .json 格式。"""
    if result_file.suffix == ".zip":
        import zipfile
        with zipfile.ZipFile(result_file) as zf:
            # 找到主结果 JSON（不含 _config 后缀）
            json_names = [n for n in zf.namelist()
                          if n.endswith(".json") and "_config" not in n]
            if not json_names:
                json_names = [n for n in zf.namelist() if n.endswith(".json")]
            data = json.loads(zf.read(json_names[0]))
            return data
    else:
        return json.loads(result_file.read_text(encoding="utf-8"))


def _extract_metrics_summary(result_data: Dict[str, Any]) -> Dict[str, Any]:
    """从回测结果 JSON 中提取 metrics_summary。

    Freqtrade backtest-result JSON 结构：
    {
      "strategy": {"strategy_name": {...}},
      "metadata": {...},
      "strategy_comparison": [
        {"key": "strategy_name", "profit_factor": ..., "sharpe": ..., ...}
      ]
    }
    """
    summary: Dict[str, Any] = {}

    # strategy_comparison 是核心指标表
    comparison = result_data.get("strategy_comparison") or []
    if comparison:
        row = comparison[0]

        def _f(v: Any) -> float:
            """安全转 float。"""
            try:
                return float(v) if v is not None else 0.0
            except (ValueError, TypeError):
                return 0.0

        summary = {
            "profit_factor": _f(row.get("profit_factor", 0)),
            "sharpe_ratio": _f(row.get("sharpe", 0)),
            "sortino_ratio": _f(row.get("sortino", 0)),
            "max_drawdown_pct": _f(row.get("max_drawdown_account", 0)),
            "max_drawdown_abs": _f(row.get("max_drawdown_abs", 0)),
            "winrate": _f(row.get("winrate", 0)),
            "trades": int(row.get("trades", 0) or 0),
            "profit_total_pct": _f(row.get("profit_total_pct", 0)),
            "profit_total_abs": _f(row.get("profit_total_abs", 0)),
            "avg_duration": str(row.get("duration_avg", "")),
            "cagr": _f(row.get("cagr", 0)),
            "calmar_ratio": _f(row.get("calmar", 0)),
            "sqn": _f(row.get("sqn", 0)),
            "expectancy": _f(row.get("expectancy", 0)),
            "expectancy_ratio": _f(row.get("expectancy_ratio", 0)),
        }

    # 从 strategy 详情补充 exit_reason 分布
    strategies = result_data.get("strategy") or {}
    if strategies:
        strat_data = next(iter(strategies.values()), {})
        exits = strat_data.get("exits") or {}
        if exits:
            exit_reasons = {}
            for reason, info in exits.items():
                exit_reasons[reason] = info.get("trades", 0)
            summary["exit_reasons"] = exit_reasons

    return summary


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def run_backtest(
    strategy_id: str,
    source_zip: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """执行回测，返回 metrics_summary。

    Args:
        strategy_id: 策略类名（如 Bot2StrategyTrend）
        source_zip: 策略 zip 路径（可选）
        **kwargs: 可选回测参数
            - timeframe: 周期（默认 1h）
            - timerange: 时间范围（默认 20260422-20260721）
            - pairs: 交易对列表
            - stake_amount: 单笔金额
            - max_open_trades: 最大持仓数
            - fee: 手续费率

    Returns:
        {
            "ok": bool,
            "strategy_id": str,
            "metrics_summary": {...},
            "backtest_result_file": str,
            "trades_count": int,
            "error": str (仅失败时)
        }
    """
    # 1. 定位策略文件
    strategy_path = _resolve_strategy_path(strategy_id, source_zip)
    if strategy_path is None:
        return {
            "ok": False,
            "strategy_id": strategy_id,
            "error": f"strategy_not_found: {strategy_id}",
            "metrics_summary": {},
        }

    # 2. 构建 config
    timeframe = kwargs.get("timeframe") or _DEFAULT_TIMEFRAME
    timerange = kwargs.get("timerange") or _DEFAULT_TIMERANGE
    pairs = kwargs.get("pairs")
    stake_amount = float(kwargs.get("stake_amount") or _DEFAULT_STAKE_AMOUNT)
    max_open_trades = int(kwargs.get("max_open_trades") or _DEFAULT_MAX_OPEN_TRADES)
    fee = float(kwargs.get("fee") or _DEFAULT_FEE)

    config_path = _build_backtest_config(
        strategy_id,
        timeframe=timeframe,
        timerange=timerange,
        pairs=pairs,
        stake_amount=stake_amount,
        max_open_trades=max_open_trades,
        fee=fee,
    )

    # 3. 执行回测
    run_result = _run_freqtrade_backtest(
        config_path,
        strategy_id,
        timerange=timerange,
        pairs=pairs,
    )

    # 4. 清理临时 config
    try:
        config_path.unlink(missing_ok=True)
    except Exception:
        pass

    if not run_result["ok"]:
        return {
            "ok": False,
            "strategy_id": strategy_id,
            "error": run_result.get("stderr", "")[-500:],
            "stdout": run_result.get("stdout", "")[-1000:],
            "metrics_summary": {},
        }

    # 5. 解析回测结果
    result_file = _find_latest_backtest_result()
    if result_file is None:
        return {
            "ok": False,
            "strategy_id": strategy_id,
            "error": "backtest_result_not_found",
            "metrics_summary": {},
        }

    try:
        result_data = _read_backtest_result(result_file)
    except Exception as e:
        return {
            "ok": False,
            "strategy_id": strategy_id,
            "error": f"parse_result_failed: {e}",
            "metrics_summary": {},
        }

    metrics_summary = _extract_metrics_summary(result_data)
    trades_count = metrics_summary.get("trades", 0)

    return {
        "ok": True,
        "strategy_id": strategy_id,
        "metrics_summary": metrics_summary,
        "backtest_result_file": str(result_file),
        "trades_count": trades_count,
        "backtest_ts": int(time.time() * 1000),
    }


# ---------------------------------------------------------------------------
# 便捷方法：直接获取回测指标（供 M27 gate 调用）
# ---------------------------------------------------------------------------

def get_backtest_metrics(
    strategy_id: str,
    source_zip: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """获取回测指标（run_backtest 的简化包装）。"""
    result = run_backtest(strategy_id, source_zip, **kwargs)
    return result.get("metrics_summary", {})


# ---------------------------------------------------------------------------
# P3: show-trades / download-data / plot-profit
# ---------------------------------------------------------------------------

def show_trades(strategy_id: str, **kwargs: Any) -> Dict[str, Any]:
    """展示回测交易记录。

    Args:
        strategy_id: 策略类名
        **kwargs: timerange, pairs, timeframe 等

    Returns:
        {"ok": bool, "trades": [...], "backtest_result_file": str}
    """
    # 1. 先执行回测（--export trades）
    bt_result = run_backtest(strategy_id, **kwargs)
    if not bt_result.get("ok"):
        return {"ok": False, "error": bt_result.get("error", "backtest_failed"), "trades": []}

    # 2. 从结果文件中提取交易记录
    result_file = Path(bt_result["backtest_result_file"])
    try:
        result_data = _read_backtest_result(result_file)
    except Exception as e:
        return {"ok": False, "error": f"parse_failed: {e}", "trades": []}

    # 提取交易记录
    trades = []
    strategies = result_data.get("strategy") or {}
    if strategies:
        strat_data = next(iter(strategies.values()), {})
        # trades 可能在 strat_data 中
        raw_trades = strat_data.get("trades") or []
        for t in raw_trades:
            if isinstance(t, dict):
                trades.append({
                    "pair": t.get("pair"),
                    "open_date": t.get("open_date"),
                    "close_date": t.get("close_date"),
                    "open_rate": t.get("open_rate"),
                    "close_rate": t.get("close_rate"),
                    "profit_abs": t.get("profit_abs"),
                    "profit_pct": t.get("profit_ratio"),
                    "exit_reason": t.get("exit_reason"),
                    "duration": t.get("duration"),
                })

    return {
        "ok": True,
        "strategy_id": strategy_id,
        "trades": trades,
        "trades_count": len(trades),
        "backtest_result_file": str(result_file),
    }


def download_data(
    pairs: list,
    *,
    timeframe: str = "1h",
    timerange: str = "20260101-",
    exchange: str = "okx",
) -> Dict[str, Any]:
    """下载 OHLCV 数据。

    Args:
        pairs: 交易对列表，如 ["BTC/USDT", "ETH/USDT"]
        timeframe: 周期（默认 1h）
        timerange: 时间范围
        exchange: 交易所（默认 okx）

    Returns:
        {"ok": bool, "downloaded": [...], "error": str (失败时)}
    """
    cmd = [
        _FREQTRADE_BIN, "download-data",
        "--exchange", exchange,
        "--timeframes", timeframe,
        "--timerange", timerange,
        "--pairs", *pairs,
        "--userdir", str(_USER_DATA_DIR),
        "--data-format-ohlcv", "json",
    ]
    if exchange == "okx":
        cmd.extend(["--trading-mode", "spot"])

    env = os.environ.copy()
    env["PYTHONPATH"] = str(_CLASSIC_ROOT)

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600,
            env=env, cwd=str(_CLASSIC_ROOT),
        )
        if result.returncode != 0:
            return {"ok": False, "error": result.stderr[-1000:]}

        # 解析下载结果
        downloaded = []
        for line in result.stdout.split("\n"):
            if "Downloaded" in line or "downloaded" in line.lower():
                downloaded.append(line.strip())

        return {"ok": True, "downloaded": downloaded, "pairs": pairs, "timeframe": timeframe}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def plot_profit(strategy_id: str, **kwargs: Any) -> Dict[str, Any]:
    """生成回测利润图。

    Args:
        strategy_id: 策略类名
        **kwargs: timerange, pairs, timeframe 等

    Returns:
        {"ok": bool, "plot_file": str, "backtest_result_file": str}
    """
    # 1. 先执行回测
    bt_result = run_backtest(strategy_id, **kwargs)
    if not bt_result.get("ok"):
        return {"ok": False, "error": bt_result.get("error", "backtest_failed")}

    # 2. 用 freqtrade plot-profit 生成图表
    result_file = bt_result["backtest_result_file"]
    config_path = _build_backtest_config(strategy_id, **{
        k: v for k, v in kwargs.items() if v is not None
    })

    cmd = [
        _FREQTRADE_BIN, "plot-profit",
        "--config", str(config_path),
        "--strategy", strategy_id,
        "--userdir", str(_USER_DATA_DIR),
        "--export-filename", str(result_file),
    ]

    env = os.environ.copy()
    env["PYTHONPATH"] = str(_CLASSIC_ROOT)

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120,
            env=env, cwd=str(_CLASSIC_ROOT),
        )
        # 清理 config
        config_path.unlink(missing_ok=True)

        if result.returncode != 0:
            return {"ok": False, "error": result.stderr[-1000:]}

        # 查找生成的图表文件
        plot_dir = _USER_DATA_DIR / "plot"
        plot_files = list(plot_dir.glob("*.html")) if plot_dir.exists() else []
        plot_file = str(plot_files[0]) if plot_files else ""

        return {
            "ok": True,
            "strategy_id": strategy_id,
            "plot_file": plot_file,
            "backtest_result_file": result_file,
        }
    except subprocess.TimeoutExpired:
        config_path.unlink(missing_ok=True)
        return {"ok": False, "error": "timeout"}
    except Exception as e:
        config_path.unlink(missing_ok=True)
        return {"ok": False, "error": str(e)}
