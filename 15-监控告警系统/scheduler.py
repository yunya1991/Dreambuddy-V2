#!/usr/bin/env python3
"""
统一监控调度器
定时执行所有系统的监控检查，并发送飞书告警

双层调度架构：
- 5分钟轻量轮询：持仓同步（对比交易所真实持仓+更新盈亏）
- 60分钟完整监控：健康检查+性能统计+风险评估+告警发送
"""
import json
import os
import time
import schedule
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).parent


def run_monitor():
    """执行完整监控任务（60分钟）"""
    from monitor_core import UnifiedMonitor

    try:
        monitor = UnifiedMonitor()
        results = monitor.monitor_all()
        monitor.send_alerts(results)

        healthy_count = sum(1 for r in results.values() if r.is_healthy())
        print(f"\n[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] "
              f"完整监控完成: {healthy_count}/{len(results)} 系统正常")

    except Exception as e:
        print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] "
              f"完整监控执行异常: {e}")


def run_position_sync():
    """执行持仓同步任务（5分钟轻量轮询）"""
    from position_sync import run_position_sync as sync_func

    try:
        sync_func()
        print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] "
              f"持仓同步完成")

    except Exception as e:
        print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] "
              f"持仓同步异常: {e}")


def main():
    print("=" * 60)
    print("统一监控调度器启动")
    print("=" * 60)

    config_path = BASE_DIR / "config" / "monitor_config.json"
    if config_path.exists():
        with open(config_path) as f:
            config = json.load(f)
        monitor_interval = config.get("scheduler", {}).get("interval_minutes", 60)
        sync_interval = config.get("scheduler", {}).get("sync_interval_minutes", 5)
    else:
        monitor_interval = 60
        sync_interval = 5

    print(f"完整监控间隔: {monitor_interval} 分钟")
    print(f"持仓同步间隔: {sync_interval} 分钟")
    print(f"启动时间: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}")

    run_position_sync()
    run_monitor()

    schedule.every(sync_interval).minutes.do(run_position_sync)
    schedule.every(monitor_interval).minutes.do(run_monitor)

    while True:
        try:
            schedule.run_pending()
            time.sleep(60)
        except KeyboardInterrupt:
            print("\n调度器已停止")
            break
        except Exception as e:
            print(f"调度器异常: {e}")
            time.sleep(60)


if __name__ == "__main__":
    main()
