#!/usr/bin/env python3
"""
Dream OS 调度器守护进程启动脚本

启动 DreamOS 每小时自动调度任务，分析 BTC、ETH、SOL、AVAX、LINK、DOT、MATIC、BNB、OP、ARB 共10个币种
"""

import os
import sys
import time
import logging
from pathlib import Path

dreamos_dir = Path(__file__).parent.parent
sys.path.insert(0, str(dreamos_dir.parent))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(dreamos_dir / 'logs' / 'scheduler.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


def main():
    logger.info("=" * 60)
    logger.info("Dream OS 调度器守护进程启动")
    logger.info("=" * 60)

    try:
        from dreamos.cli.scheduler import DreamOSScheduler

        scheduler = DreamOSScheduler(data_dir='1-ARCHITECTURE/dreamos/cli/scheduler_data')
        
        jobs = scheduler.list_jobs()
        logger.info(f"已加载 {len(jobs)} 个定时任务")
        for j in jobs:
            logger.info(f"  - {j['name']}: cron={j['cron_expr']}, status={j['status']}")

        scheduler.start()
        logger.info("调度器已启动，开始监听定时任务...")

        logger.info("立即执行一次全币种扫描...")
        scheduler.run_all_now()

        try:
            while True:
                time.sleep(60)
                stats = scheduler.get_stats()
                logger.debug(f"调度器运行中 | 任务数: {stats['total_jobs']} | 运行中: {stats['running_jobs']}")
        except KeyboardInterrupt:
            logger.info("收到中断信号，正在停止调度器...")
        finally:
            scheduler.stop()
            logger.info("调度器已停止")

    except Exception as e:
        logger.error(f"调度器启动失败: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()