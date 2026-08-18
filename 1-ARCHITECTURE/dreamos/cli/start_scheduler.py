#!/usr/bin/env python3
"""
Dream OS 调度器守护进程启动脚本

启动 DreamOS 每小时自动调度任务，分析 BTC、ETH、SOL、AVAX、LINK、DOT、MATIC、BNB、OP、ARB 共10个币种
"""

import os
import sys
import time
import fcntl
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

# 单例锁 fd 持有引用(必须保持进程级存活,flock 随 fd 关闭释放)
_lock_fd = None


def main():
    # 临时暂停标记:平仓维护中,调度器启动后立即退出
    pause_file = dreamos_dir / "logs" / "SCHEDULER_PAUSED"
    if pause_file.exists():
        logger.info("暂停标记文件存在,调度器立即退出")
        return

    # P0.6 修复: 单例锁 — 防止双实例并发(8/15 00:00~01:02 曾出现双实例重复执行)
    # crontab 的 pgrep 守卫只防 cron 发起的重复;手动/其他途径启动仍需 flock 兜底
    global _lock_fd
    lock_file = dreamos_dir / "logs" / "scheduler.lock"
    _lock_fd = open(lock_file, "w")
    try:
        fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, OSError):
        logger.info("已有调度器实例在运行(flock 冲突),本实例退出")
        return
    _lock_fd.write(str(os.getpid()))
    _lock_fd.flush()

    logger.info("=" * 60)
    logger.info("Dream OS 调度器守护进程启动")
    logger.info("=" * 60)

    try:
        from dreamos.cli.scheduler import DreamOSScheduler

        # 使用绝对路径加载 scheduler_data,避免 cwd 差异导致加载失败
        scheduler_data_dir = str(dreamos_dir / "cli" / "scheduler_data")
        scheduler = DreamOSScheduler(data_dir=scheduler_data_dir)
        
        jobs = scheduler.list_jobs()
        logger.info(f"已加载 {len(jobs)} 个定时任务")
        for j in jobs:
            logger.info(f"  - {j['name']}: cron={j['cron_expr']}, status={j['status']}")

        scheduler.start()
        logger.info("调度器已启动，开始监听定时任务...")

        logger.info("立即执行一次全币种扫描...")
        scheduler.run_all_now()

        try:
            _beat = 0
            while True:
                time.sleep(60)
                _beat += 1
                stats = scheduler.get_stats()
                # P0.6 修复: 每30分钟 INFO 心跳 + 各任务 next_run 快照
                # (8/15 ENOSPC 事故中 06:00~10:30 完全静默,无法定位停摆窗口;
                #  心跳断档即告警信号,next_run=None 的任务会被直接点名)
                if _beat % 30 == 0:
                    jobs_snap = scheduler.list_jobs()
                    parts = [
                        f"{j['name']}:next={j['next_run'] or 'None!'}"
                        for j in jobs_snap
                    ]
                    logger.info(
                        f"[HEARTBEAT] 调度器运行中 | 任务数: {stats['total_jobs']} "
                        f"| 运行中: {stats['running_jobs']} | 累计错误: {stats['total_errors']} "
                        f"| {'; '.join(parts)}"
                    )
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