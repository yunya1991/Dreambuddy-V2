#!/usr/bin/env python3
"""
Dream OS 动态评估调度器 - 常驻进程启动入口

职责:
    1. 定期评估调度 (默认每6小时触发回测评估)
    2. 事件触发评估 (亏损/回撤/市场事件)
    3. 编排策略更新 (基于评估结果自动优化)

用法:
    cd 1-ARCHITECTURE
    python -m dreamos.cli.run_dynamic_evaluator
    python -m dreamos.cli.run_dynamic_evaluator --interval 3600
"""

from __future__ import annotations

import os
import sys
import time
import logging
import argparse
import signal
from datetime import datetime

# 确保从 1-ARCHITECTURE 目录运行
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

logger = logging.getLogger("dynamic_evaluator_runner")


def main():
    parser = argparse.ArgumentParser(description="Dream OS 动态评估调度器")
    parser.add_argument("--interval", type=int, default=21600,
                        help="定期评估间隔(秒), 默认21600(6小时)")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    logger.info("=" * 60)
    logger.info("Dream OS 动态评估调度器启动")
    logger.info(f"评估间隔: {args.interval}秒 ({args.interval/3600:.1f}小时)")
    logger.info("=" * 60)

    from dreamos.core.scheduler.dynamic_evaluator import DynamicEvaluationScheduler

    config = {
        "schedule_interval": args.interval,
        "max_concurrent_tasks": 1,
        "task_timeout": 600,
        "triggers": {
            "loss": {
                "consecutive_losses_threshold": 3,
                "single_loss_threshold": -0.03,
            },
            "drawdown": {
                "drawdown_threshold": 0.10,
            },
            "market": {
                "volatility_spike_threshold": 2.0,
                "trend_reversal_threshold": 0.15,
            },
            "threshold": {
                "score_change_threshold": 0.15,
            },
        },
    }

    scheduler = DynamicEvaluationScheduler(config=config)

    # 优雅退出
    def signal_handler(signum, frame):
        logger.info(f"收到信号 {signum}, 停止调度器...")
        scheduler.stop()
        logger.info("调度器已停止, 退出")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    scheduler.start()
    logger.info("调度器已启动, 进入主循环 (Ctrl+C 退出)")

    # 主循环: 保持进程运行, 定期输出心跳
    try:
        while True:
            time.sleep(60)
            # 每分钟输出一次心跳
            logger.debug(f"心跳: {datetime.now().isoformat()} 调度器运行中")
    except KeyboardInterrupt:
        signal_handler(signal.SIGINT, None)


if __name__ == "__main__":
    main()
