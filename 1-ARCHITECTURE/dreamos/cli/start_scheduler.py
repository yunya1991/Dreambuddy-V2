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

# 加载 Dream OS 独立 .env 文件(含 Aster 账户配置等)
_env_path = dreamos_dir / ".env"
if _env_path.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_path)
    except ImportError:
        # dotenv 不可用时降级:手动解析 KEY=VALUE
        with open(_env_path) as _fp:
            for _line in _fp:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _v = _line.split("=", 1)
                    os.environ.setdefault(_k.strip(), _v.strip())

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
    # 临时暂停标记:平仓维护中,调度器启动后立即退出
    pause_file = dreamos_dir / "logs" / "SCHEDULER_PAUSED"
    if pause_file.exists():
        logger.info("暂停标记文件存在,调度器立即退出")
        return
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