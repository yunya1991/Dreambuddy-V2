"""run_shadow_probe.py — E1 shadow 探针执行入口（SPEC-EMERGENCE-EVOLUTION v0.5 §4 E1）。
周期运行 anomaly_probe（coupling 3σ 探测）→ EmergenceBus 点火广播 →
shadow 订阅者（rea/eval/data）消费并落盘 resp/watchlist。
开关：EMERGENCE_BUS=1 或 events/ENABLED flag 文件（与 emergence_bus.enabled() 一致）。
FAIL-OPEN：任何异常不抛出，退出码恒为 0，不影响调用方。
用法：
  单次执行：python run_shadow_probe.py
  循环执行：python run_shadow_probe.py --interval 300
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from emergence_bus import EmergenceBus, enabled  # noqa: E402
from anomaly_probe import run_probe  # noqa: E402
import shadow_subscribers as ss  # noqa: E402

logger = logging.getLogger("run_shadow_probe")
SUBSCRIBER_DOMAINS = ("rea", "eval", "data")


def run_once(bus: EmergenceBus) -> int:
    """单轮探测：coupling 3σ 探测 → 点火广播 → 订阅者消费。返回点燃数。"""
    fired = run_probe(bus)
    ts = datetime.now(timezone.utc).isoformat()
    if fired:
        for env in fired:
            logger.info(
                "点燃 %s source=%s metric=%s z=%s value=%s",
                env.get("event_id"),
                env.get("source_domain"),
                env.get("metric"),
                env.get("z_score"),
                env.get("value"),
            )
    else:
        logger.info("本轮无 3σ 异常信号（%s）", ts)
    return len(fired)


def main() -> int:
    parser = argparse.ArgumentParser(description="E1 shadow 探针执行入口")
    parser.add_argument(
        "--interval",
        type=int,
        default=0,
        help="大于 0 时循环执行（秒）；默认单次执行后退出",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if not enabled():
        logger.warning("EMERGENCE_BUS 未开启（env/flag 均未生效），本轮直接退出")
        return 0

    bus = EmergenceBus()
    for domain in SUBSCRIBER_DOMAINS:
        ss.ShadowSubscriber(domain).attach(bus)
    logger.info("shadow 订阅者已挂载: %s", ",".join(SUBSCRIBER_DOMAINS))

    try:
        if args.interval > 0:
            while True:
                run_once(bus)
                time.sleep(args.interval)
        else:
            run_once(bus)
    except KeyboardInterrupt:
        logger.info("收到中断，退出")
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        logger.warning("探针执行异常（FAIL-OPEN 不抛出）: %s", exc)
    return 0


if __name__ == "__main__":
    sys.exit(main())

