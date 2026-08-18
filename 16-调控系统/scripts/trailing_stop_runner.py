#!/usr/bin/env python3
"""
移动止盈代码级调度器
====================

完全代码驱动，不依赖 AI 自动化。以固定间隔（默认 300 秒 = 5 分钟）
循环调用 TrailingStopComponent.evaluate()，当检测到 TRIGGER_CLOSE
时直接通过 ExitExecutor 执行真实平仓。

使用方式::

    # 前台运行（默认 5 分钟间隔，dry-run 模式）
    python scripts/trailing_stop_runner.py

    # 实盘模式，自定义 5 分钟间隔
    python scripts/trailing_stop_runner.py --real --interval 300

    # 后台运行（nohup）
    nohup python scripts/trailing_stop_runner.py --real --interval 300 \
        > logs/trailing_runner.log 2>&1 &

    # 单次执行（不循环，只跑一轮）
    python scripts/trailing_stop_runner.py --once --real

CLI 参数：
    --interval    轮询间隔秒数（默认 300 = 5 分钟）
    --dry-run     模拟模式（不执行真实交易）
    --real        实盘模式（触发时执行真实平仓）
    --once        仅执行一次后退出（不循环）
    --system      限定评估的系统（可多次指定，默认全部）
    --config      自定义配置文件路径
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

# 路径初始化
BASE_DIR = Path(__file__).resolve().parent.parent          # 16-调控系统
CORE_DIR = BASE_DIR / "core"
sys.path.insert(0, str(CORE_DIR))
sys.path.insert(0, str(BASE_DIR / "scripts"))

# 日志
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# 全局退出标志（信号处理）
_running = True


def _log(msg: str, level: str = "INFO"):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    print(line, flush=True)
    log_file = LOG_DIR / f"trailing_runner_{datetime.now(timezone.utc).strftime('%Y%m%d')}.log"
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def _signal_handler(signum, frame):
    global _running
    _log(f"收到信号 {signum}，准备优雅退出...", "WARN")
    _running = False


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


# =====================================================================
# 平仓执行器（轻量封装，复用 ExitExecutor）
# =====================================================================


class TrailingExecutor:
    """移动止盈触发的平仓执行器。

    复用 ExitExecutor 的真实下单能力，但只执行 CLOSE 动作。
    """

    def __init__(self, mode: str = "dry_run"):
        self.mode = mode
        self._executor = None
        if mode == "real":
            try:
                from exit_executor import create_executor_from_env
                os.environ["EXIT_MODE"] = "real"
                self._executor = create_executor_from_env()
                _log(f"ExitExecutor 初始化完成（mode=real, max_exec={self._executor.max_executions_per_cycle}）")
            except Exception as e:
                _log(f"ExitExecutor 初始化失败，降级为 dry_run: {e}", "WARN")
                self.mode = "dry_run"

    def execute_trigger(self, trigger: dict) -> dict:
        """执行单个 TRIGGER_CLOSE。

        Args:
            trigger: 来自 TrailingResult 的触发字典，包含：
                - system, symbol(coin), direction(side)
                - locked_profit_pct, reason

        Returns:
            执行结果字典
        """
        symbol = trigger.get("symbol", "")
        system = trigger.get("system", "")
        direction = (trigger.get("direction") or "").lower()

        if self.mode == "dry_run":
            _log(
                f"[DRY-RUN] 移动止盈触发 → {system}/{symbol} {direction} "
                f"锁定盈利={trigger.get('locked_profit_pct', 0):.2%} "
                f"（dry-run 不执行真实交易）"
            )
            return {
                "status": "skipped",
                "mode": "dry_run",
                "system": system,
                "symbol": symbol,
                "action": "CLOSE",
                "reason": trigger.get("reason", ""),
            }

        # real 模式：通过 ExitExecutor 执行
        if self._executor is None:
            _log("ExitExecutor 未初始化，无法执行真实平仓", "ERROR")
            return {"status": "failed", "error": "executor_not_initialized"}

        try:
            # 查询该持仓的详细信息（获取 size）
            from unified_position_query import fetch_all_positions
            all_data = fetch_all_positions()
            positions = all_data.get("positions", [])

            target_pos = None
            for p in positions:
                if (p.get("system") == system
                    and p.get("symbol") == symbol
                    and (p.get("direction", "").upper() == direction.upper()
                         or p.get("direction", "").upper() == direction.upper())):
                    target_pos = p
                    break

            if target_pos is None:
                _log(f"未找到匹配持仓 {system}/{symbol}/{direction}，跳过", "WARN")
                return {"status": "skipped", "reason": "position_not_found"}

            size = float(target_pos.get("size", 0))
            if size <= 0:
                _log(f"持仓 {system}/{symbol} size=0，跳过", "WARN")
                return {"status": "skipped", "reason": "zero_size"}

            # 构造评估条目（ExitExecutor 格式）
            eval_entry = {
                "recommended_action": "CLOSE",
                "confidence": 0.95,
                "urgency": "HIGH",
                "source": "trailing_stop",
                "reason": trigger.get("reason", ""),
                "position": {
                    "symbol": symbol,
                    "system": system,
                    "strategy_id": system,
                    "direction": direction.upper(),
                    "size": size,
                    "entry_price": float(target_pos.get("entry_price", 0)),
                    "unrealized_pnl": float(target_pos.get("unrealized_pnl", 0)),
                    "upl_ratio": float(target_pos.get("upl_ratio", 0)),
                },
                "confidence_gated": False,
                "permission_check": {"allowed": True},
            }

            _log(
                f"[REAL] 移动止盈触发平仓 → {system}/{symbol} {direction} "
                f"size={size} locked_profit={trigger.get('locked_profit_pct', 0):.2%}"
            )

            results = self._executor.execute_evaluations([eval_entry])
            if results:
                r = results[0]
                _log(
                    f"[REAL] 执行结果: status={r.get('status')} "
                    f"order_id={r.get('order_id', '')} "
                    f"executed_size={r.get('executed_size', 0)} "
                    f"price={r.get('execution_price', 0)}"
                )
                return r
            return {"status": "unknown"}

        except Exception as e:
            _log(f"[REAL] 平仓执行异常: {e}", "ERROR")
            _log(traceback.format_exc(), "ERROR")
            return {"status": "failed", "error": str(e)}


# =====================================================================
# 主循环
# =====================================================================


def run_single_cycle(
    component,
    executor: TrailingExecutor,
    systems: Optional[List[str]] = None,
) -> dict:
    """执行单次移动止盈评估周期。

    Returns:
        周期结果摘要
    """
    cycle_start = time.time()
    _log("--- 移动止盈评估周期开始 ---")

    # 1. 评估
    snapshot = component.evaluate(systems=systems)
    stats = snapshot.stats
    _log(
        f"评估完成: 总持仓={stats.total_positions} "
        f"IDLE={stats.idle_count} ARMED={stats.armed_count} "
        f"TRIGGERED={stats.triggered_count} CLOSED={stats.closed_count} "
        f"历史触发累计={stats.triggered_total}"
    )

    # 2. 处理触发
    trigger_count = 0
    exec_results = []
    for sk, r in snapshot.by_state.items():
        if r.action.value == "TRIGGER_CLOSE":
            trigger_count += 1
            _log(
                f"触发平仓: {sk} → {r.reason[:100]}  "
                f"锁定盈利={r.locked_profit_pct:.2%}"
            )
            # 记录详细信息
            trigger_info = {
                "state_key": sk,
                "system": r.system,
                "symbol": r.coin,
                "direction": r.side,
                "locked_profit_pct": r.locked_profit_pct,
                "trailing_stop_price": r.trailing_stop_price,
                "triggered_price": r.current_price,
                "peak_price": r.peak_price,
                "reason": r.reason,
            }
            result = executor.execute_trigger(trigger_info)
            exec_results.append({
                "trigger": trigger_info,
                "execution": result,
            })

    # 3. 打印 ARMED 状态
    for sk, r in snapshot.by_state.items():
        if r.status.value == "ARMED" and r.action.value == "HOLD":
            _log(
                f"  ARMED: {sk} trail={r.trailing_stop_price:.4f} "
                f"peak={r.peak_price:.4f} current={r.current_price:.4f} "
                f"距触发={r.trail_distance_pct:.2%} "
                f"pnl_eff={r.current_pnl_eff_pct:.2%}"
            )

    elapsed = time.time() - cycle_start
    _log(f"--- 周期完成，耗时 {elapsed:.1f}s，触发 {trigger_count} 笔 ---")

    return {
        "total_positions": stats.total_positions,
        "armed_count": stats.armed_count,
        "triggered_count": stats.triggered_count,
        "trigger_executions": exec_results,
        "elapsed_seconds": round(elapsed, 1),
    }


def main():
    parser = argparse.ArgumentParser(
        description="移动止盈代码级调度器（ATR 自适应法）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  # 前台 dry-run，默认 5 分钟间隔\n"
            "  python scripts/trailing_stop_runner.py\n\n"
            "  # 实盘模式\n"
            "  python scripts/trailing_stop_runner.py --real\n\n"
            "  # 自定义 3 分钟间隔\n"
            "  python scripts/trailing_stop_runner.py --real --interval 180\n\n"
            "  # 单次执行\n"
            "  python scripts/trailing_stop_runner.py --once --real\n\n"
            "  # 后台运行\n"
            "  nohup python scripts/trailing_stop_runner.py --real \\\n"
            "    > logs/trailing_runner.log 2>&1 &\n"
        ),
    )
    parser.add_argument(
        "--interval", type=int, default=300,
        help="轮询间隔秒数（默认 300 = 5 分钟）",
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=True,
        help="模拟模式（不执行真实交易，默认）",
    )
    parser.add_argument(
        "--real", action="store_true",
        help="实盘模式（触发时执行真实平仓）",
    )
    parser.add_argument(
        "--once", action="store_true",
        help="仅执行一次后退出（不循环）",
    )
    parser.add_argument(
        "--system", action="append", default=None,
        help="限定评估的系统（可多次指定，默认全部）",
    )
    parser.add_argument(
        "--config", type=str, default=None,
        help="自定义配置文件路径",
    )
    args = parser.parse_args()

    # 模式
    mode = "real" if args.real else "dry_run"
    _log(f"移动止盈调度器启动")
    _log(f"  模式: {mode}")
    _log(f"  间隔: {args.interval}s ({args.interval / 60:.1f} 分钟)")
    _log(f"  单次: {'是' if args.once else '否'}")
    _log(f"  系统: {args.system or '全部'}")

    # 初始化组件
    from trailing_stop import TrailingStopComponent, TrailingAction

    config_path = Path(args.config) if args.config else None
    component = TrailingStopComponent(config_path=config_path)
    executor = TrailingExecutor(mode=mode)

    # 单次模式
    if args.once:
        result = run_single_cycle(component, executor, systems=args.system)
        _log(f"单次执行完成: {result}")
        return 0

    # 循环模式
    cycle_count = 0
    global _running
    while _running:
        cycle_count += 1
        _log(f"===== 第 {cycle_count} 轮 =====")

        try:
            run_single_cycle(component, executor, systems=args.system)
        except Exception as e:
            _log(f"周期异常: {e}", "ERROR")
            _log(traceback.format_exc(), "ERROR")

        if not _running:
            break

        # 等待下一轮（可被信号中断）
        _log(f"等待 {args.interval}s ...")
        wait_start = time.time()
        while _running and (time.time() - wait_start) < args.interval:
            time.sleep(1)

    _log(f"调度器已退出，共执行 {cycle_count} 轮")
    return 0


if __name__ == "__main__":
    sys.exit(main())
