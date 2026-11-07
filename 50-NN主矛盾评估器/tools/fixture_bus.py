"""R0-03 本地 fixture 总线：模拟 ≥6 源多轮调度，验证 TTL/空 bus/authority 负向。

不触真实 11 子池；运行态 3 日在线率属云端/ops 门禁。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable

from core.mappings import (
    CONSTRAINT_SOURCES,
    EXTERNAL_SOURCES,
    SELF_MIRROR_SOURCES,
)

DEFAULT_SOURCES = sorted(EXTERNAL_SOURCES | CONSTRAINT_SOURCES | SELF_MIRROR_SOURCES)


def make_fixture_bus(
    sources: Iterable[str] | None = None,
    now: datetime | None = None,
    ttl_hours: float = 2.0,
    symbol: str = "BTC-USDT-SWAP",
) -> dict:
    moment = now or datetime.now(timezone.utc)
    srcs = list(sources) if sources else list(DEFAULT_SOURCES)
    signals = []
    for idx, src in enumerate(srcs):
        signals.append(
            {
                "signal_id": f"sig_{src}_{moment.strftime('%Y%m%dT%H%M%SZ')}",
                "source": src,
                "ts": moment.isoformat().replace("+00:00", "Z"),
                "symbol": "crypto_usdt" if src == "11-bcrm" else symbol,
                "direction": "long",
                "confidence": round(0.5 + 0.05 * idx, 3),
                "horizon": "hours",
                "risk_exposure_hint": 0.1,
                "expires_at": (moment + timedelta(hours=ttl_hours))
                .isoformat()
                .replace("+00:00", "Z"),
                "payload": {},
            }
        )
    return {
        "bus_id": "fixture",
        "generated_at": moment.isoformat().replace("+00:00", "Z"),
        "signal_count": len(signals),
        "sources": srcs,
        "signals": signals,
        "rejected": [],
    }


def run_cycles(n: int = 3, step_hours: float = 1.0) -> list[dict]:
    """模拟 n 轮总线调度，每轮时钟推进 step_hours。"""
    now = datetime(2026, 11, 8, 0, 0, tzinfo=timezone.utc)
    buses = []
    for _ in range(n):
        buses.append(make_fixture_bus(now=now))
        now += timedelta(hours=step_hours)
    return buses


def authority_negative_bus() -> dict:
    """authority=all 拦截 11 子池写入 → 总线无源（负向用例）。"""
    moment = datetime.now(timezone.utc)
    return {
        "bus_id": "fixture_authority_all",
        "generated_at": moment.isoformat().replace("+00:00", "Z"),
        "signal_count": 0,
        "sources": [],
        "signals": [],
        "rejected": [],
        "note": "authority=all：11 子池状态文件停止更新",
    }
