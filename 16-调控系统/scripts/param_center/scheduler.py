"""参数中心聚合调度器 — 每小时运行一次 runner.py，结果通过 JSON 持久化共享给 polling_trader。

使用方式:
    nohup python3 scheduler.py >> ../../logs/param_center_scheduler.log 2>&1 &

设计:
    - threading.Timer 每 3600 秒触发一次聚合
    - 聚合结果写入 param_center/data/aggregated_params.json
    - polling_trader 进程启动时从该 JSON 加载聚合缓存
"""
from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("param_center_scheduler")

# 调度间隔（秒）：1 小时
INTERVAL_SECONDS = 3600

# 聚合币种列表（与 polling_trader 监控币种一致）
SYMBOLS = "BTC,ETH,SOL,BNB,OKB,UNI,HYPE,PUMP,ZEC,ARB,LINK,XAU,XAG,MU,GOOGL,NVDA,AMZN,SNDK,SPCX,MSTR,COIN,CRCL,BMNR"

# 当前脚本所在目录: .../16-调控系统/scripts/param_center/
_THIS = Path(__file__).resolve()
SCRIPTS_DIR = _THIS.parent.parent  # .../16-调控系统/scripts
RUNNER_PATH = _THIS.parent / "runner.py"
PYTHON = sys.executable or "/opt/anaconda3/bin/python3"


def run_aggregation() -> None:
    """执行一次参数中心聚合。"""
    try:
        logger.info("开始参数中心聚合...")
        result = subprocess.run(
            [PYTHON, str(RUNNER_PATH), "--symbol", SYMBOLS, "--regime", "chop"],
            cwd=str(SCRIPTS_DIR),
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode == 0:
            logger.info("聚合完成 | stdout 尾部: %s", result.stdout.strip()[-200:])
        else:
            logger.error("聚合失败 rc=%d | stderr: %s", result.returncode, result.stderr[-500:])
    except subprocess.TimeoutExpired:
        logger.error("聚合超时（>300s）")
    except Exception as exc:
        logger.error("聚合异常: %s", exc)


def schedule_loop() -> None:
    """定时循环：先跑一次，然后每小时间隔执行。"""
    while True:
        run_aggregation()
        logger.info("下次聚合将在 %d 秒后执行", INTERVAL_SECONDS)
        time.sleep(INTERVAL_SECONDS)


def main() -> None:
    logger.info("=" * 60)
    logger.info("参数中心聚合调度器启动 | interval=%ds symbols=%s", INTERVAL_SECONDS, SYMBOLS)
    logger.info("runner: %s", RUNNER_PATH)
    logger.info("python: %s", PYTHON)
    logger.info("=" * 60)
    # 用线程运行，便于未来扩展多任务
    t = threading.Thread(target=schedule_loop, daemon=True)
    t.start()
    # 主线程等待（daemon 线程随主线程退出）
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("调度器停止")


if __name__ == "__main__":
    main()
