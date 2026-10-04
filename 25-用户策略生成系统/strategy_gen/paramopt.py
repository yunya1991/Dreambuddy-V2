"""
25-用户策略生成系统 - 参数优化（P1a 实现）

调用 Freqtrade hyperopt CLI 进行参数空间搜索，返回最优 config_patch。

设计原则：
- subprocess 调用 freqtrade hyperopt CLI，与 backtest_engine 保持一致
- 结果从 hyperopt 输出 JSON 中提取最优参数
- FAIL-OPEN：异常时返回 ok=False 不阻断上层
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

# 复用 backtest_engine 的配置
from strategy_gen.backtest_engine import (
    _CLASSIC_ROOT,
    _DATA_DIR,
    _FREQTRADE_BIN,
    _STRATEGIES_DIR,
    _USER_DATA_DIR,
    _build_backtest_config,
)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

_DEFAULT_EPOCHS = 50
_DEFAULT_HYPEROPT_LOSS = "SharpeHyperOptLossDaily"
_DEFAULT_SPACES = ["buy", "sell"]
_HYPEROPT_TIMEOUT = 1800  # 30 分钟

_HYPEROPT_RESULTS_DIR = _USER_DATA_DIR / "hyperopt_results"


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def paramopt(
    strategy_id: str,
    param_space: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """调用 Freqtrade hyperopt 进行参数优化。

    Args:
        strategy_id: 策略类名（如 Bot2StrategyTrend）
        param_space: 参数空间配置（预留，当前用策略内定义的 space）
        **kwargs: 可选参数
            - epochs: 迭代次数（默认 50）
            - spaces: 搜索空间列表（默认 ['buy', 'sell']）
            - hyperopt_loss: 损失函数名（默认 SharpeHyperOptLossDaily）
            - timerange: 时间范围
            - pairs: 交易对列表
            - random_state: 随机种子

    Returns:
        {
            "ok": bool,
            "strategy_id": str,
            "config_patch": {...},          # 最优参数补丁
            "best_metrics": {...},           # 最优指标
            "hyperopt_result_file": str,
            "epochs": int,
            "error": str (仅失败时)
        }
    """
    # 1. 定位策略文件
    strategy_path = _resolve_strategy(strategy_id)
    if strategy_path is None:
        return {
            "ok": False,
            "strategy_id": strategy_id,
            "error": f"strategy_not_found: {strategy_id}",
            "config_patch": {},
        }

    # 2. 参数
    epochs = int(kwargs.get("epochs", _DEFAULT_EPOCHS))
    spaces = kwargs.get("spaces", _DEFAULT_SPACES)
    if isinstance(spaces, str):
        spaces = [spaces]
    hyperopt_loss = kwargs.get("hyperopt_loss", _DEFAULT_HYPEROPT_LOSS)
    timerange = kwargs.get("timerange", "20260421-20260721")
    pairs = kwargs.get("pairs")
    random_state = kwargs.get("random_state", 42)

    # 3. 构建 config（复用 backtest config）
    config_path = _build_backtest_config(
        strategy_id,
        timerange=timerange,
        pairs=pairs,
    )

    # 4. 执行 hyperopt
    run_result = _run_freqtrade_hyperopt(
        config_path,
        strategy_id,
        epochs=epochs,
        spaces=spaces,
        hyperopt_loss=hyperopt_loss,
        timerange=timerange,
        pairs=pairs,
        random_state=random_state,
    )

    # 5. 清理临时 config
    try:
        config_path.unlink(missing_ok=True)
    except Exception:
        pass

    if not run_result["ok"]:
        return {
            "ok": False,
            "strategy_id": strategy_id,
            "error": run_result.get("stderr", "")[-800:],
            "config_patch": {},
        }

    # 6. 解析 hyperopt 输出，提取最优参数
    config_patch = _extract_best_params(run_result.get("stdout", ""))
    best_metrics = _extract_best_metrics(run_result.get("stdout", ""))

    return {
        "ok": True,
        "strategy_id": strategy_id,
        "config_patch": config_patch,
        "best_metrics": best_metrics,
        "epochs": epochs,
        "spaces": spaces,
    }


# ---------------------------------------------------------------------------
# 策略定位
# ---------------------------------------------------------------------------

def _resolve_strategy(strategy_id: str) -> Optional[Path]:
    """定位策略文件。"""
    if not _STRATEGIES_DIR.exists():
        return None
    for f in _STRATEGIES_DIR.glob(f"{strategy_id}.py"):
        return f
    return None


# ---------------------------------------------------------------------------
# Freqtrade hyperopt CLI 调用
# ---------------------------------------------------------------------------

def _run_freqtrade_hyperopt(
    config_path: Path,
    strategy_name: str,
    *,
    epochs: int,
    spaces: list,
    hyperopt_loss: str,
    timerange: str,
    pairs: Optional[list] = None,
    random_state: int = 42,
) -> Dict[str, Any]:
    """调用 freqtrade hyperopt CLI。"""
    cmd = [
        _FREQTRADE_BIN, "hyperopt",
        "--config", str(config_path),
        "--strategy", strategy_name,
        "--userdir", str(_USER_DATA_DIR),
        "--datadir", str(_DATA_DIR),
        "--timerange", timerange,
        "--data-format-ohlcv", "json",
        "--epochs", str(epochs),
        "--spaces", *spaces,
        "--hyperopt-loss", hyperopt_loss,
        "--random-state", str(random_state),
        "--print-json",
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
            timeout=_HYPEROPT_TIMEOUT,
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
# 结果解析
# ---------------------------------------------------------------------------

def _extract_best_params(stdout: str) -> Dict[str, Any]:
    """从 hyperopt --print-json 输出中提取最优参数。

    hyperopt 输出格式（扁平 params + 顶层策略参数）：
    {
      "params": {"buy_ema_fast_period": 26, "sell_rsi_range": 70, ...},
      "minimal_roi": {"0": 0.138, ...},
      "stoploss": -0.028,
      "trailing_stop": false,
      ...
    }
    """
    config_patch: Dict[str, Any] = {}

    # 从 stdout 中提取 JSON
    json_match = re.search(r'\{[\s\S]*"params"[\s\S]*\}', stdout)
    if not json_match:
        return config_patch

    try:
        data = json.loads(json_match.group(0))
    except json.JSONDecodeError:
        return config_patch

    # params 是扁平 dict（key 已含 buy_/sell_ 前缀）
    params = data.get("params", {})
    if isinstance(params, dict):
        config_patch.update(params)

    # 顶层策略参数也加入
    for top_key in ["minimal_roi", "stoploss", "trailing_stop",
                    "trailing_stop_positive", "trailing_stop_positive_offset",
                    "trailing_only_offset_is_reached", "max_open_trades"]:
        if top_key in data and data[top_key] is not None:
            config_patch[top_key] = data[top_key]

    return config_patch


def _extract_best_metrics(stdout: str) -> Dict[str, Any]:
    """从 hyperopt 输出中提取最优指标（从 Best result 文本行解析）。

    输出格式示例：
    *    3/5: 1 trades. 1/0/0 Wins/Draws/Losses. Avg profit 0.09%.
             Total profit 0.0528 USDT (0.01%). Avg duration 5:00:00 min. Objective: -4.07319
    """
    metrics: Dict[str, Any] = {}

    # 找 Best result 行
    best_line = None
    for line in stdout.split("\n"):
        if "Wins/Draws/Losses" in line and "Objective" in line:
            best_line = line
            break
    if not best_line:
        return metrics

    # trades
    m = re.search(r"(\d+)\s+trades", best_line)
    if m:
        metrics["trades"] = int(m.group(1))

    # wins/draws/losses
    m = re.search(r"(\d+)/(\d+)/(\d+)\s+Wins/Draws/Losses", best_line)
    if m:
        metrics["wins"] = int(m.group(1))
        metrics["draws"] = int(m.group(2))
        metrics["losses"] = int(m.group(3))

    # avg profit %
    m = re.search(r"Avg profit\s+([-\d.]+)%", best_line)
    if m:
        metrics["avg_profit_pct"] = float(m.group(1))

    # total profit
    m = re.search(r"Total profit\s+([-\d.]+)\s+USDT", best_line)
    if m:
        metrics["total_profit_usdt"] = float(m.group(1))

    m = re.search(r"Total profit[^(]+\(\s*([-\d.]+)%\)", best_line)
    if m:
        metrics["total_profit_pct"] = float(m.group(1))

    # objective (loss)
    m = re.search(r"Objective:\s*([-\d.]+)", best_line)
    if m:
        metrics["objective"] = float(m.group(1))

    return metrics
