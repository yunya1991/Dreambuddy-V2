"""emergence_bus.py — E1 广播总线接线层（SPEC-EMERGENCE-EVOLUTION v0.5 §4 E1）。

接线复用：GWT bus 真实实现在 4-MEMORY/9-工具与接口/workspace_bus.py（pub/sub+ignite+
FAIL-OPEN），本层只做接线不复用所有权（SPEC §8 边界声明）。

设计要点（BIO 条件 #5）：
  a) 点火阈值 = 3σ 偏离（z_score ≥ 3 才广播），不能什么都广播
  b) shadow 期广播 envelope 落盘 48-涌现架构/events/emergence_shadow/bus_YYYYMMDD.jsonl

开关（默认关闭，零行为变化；沿用 mcp_shells shadow_hook 范式）：
  - EMERGENCE_BUS=1           显式开启
  - <repo>/48-涌现架构/events/ENABLED  运维开关文件（存在即开启）

FAIL-OPEN：落盘失败/订阅者异常/z 无法计算均不影响调用方。
"""

from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WS_BUS_DIR = _REPO_ROOT / "4-MEMORY" / "9-工具与接口"
if str(_WS_BUS_DIR) not in sys.path:
    sys.path.insert(0, str(_WS_BUS_DIR))

from workspace_bus import WorkspaceBus, WorkspaceContent  # noqa: E402

logger = logging.getLogger(__name__)

DEFAULT_EVENTS_DIR = _REPO_ROOT / "48-涌现架构" / "events" / "emergence_shadow"
FLAG_PATH = _REPO_ROOT / "48-涌现架构" / "events" / "ENABLED"

IGNITE_Z = 3.0  # 3σ 点火阈值（SPEC §4 E1 设计要点 a）


def enabled() -> bool:
    """开关优先级：显式 env > flag 文件 > 默认关。"""
    env = os.environ.get("EMERGENCE_BUS")
    if env is not None:
        return env.strip() == "1"
    try:
        return FLAG_PATH.exists()
    except Exception:  # noqa: BLE001
        return False


class EmergenceBus:
    """E1 涌现广播总线：异常信号 → 3σ 点火判定 → GWT 广播 → shadow envelope 落盘。"""

    def __init__(
        self,
        events_dir: Optional[Path] = None,
        ignite_z: float = IGNITE_Z,
        enabled: Optional[bool] = None,
    ) -> None:
        self._events_dir = Path(events_dir) if events_dir else DEFAULT_EVENTS_DIR
        self._ignite_z = ignite_z
        self._enabled = enabled if enabled is not None else globals()["enabled"]()
        self._bus = WorkspaceBus()

    def subscribe(self, domain: str, callback: Callable[[WorkspaceContent], None]) -> str:
        """订阅广播（透传 WorkspaceBus）。domain 用于订阅 ID 标识。"""
        return self._bus.subscribe(domain, callback)

    def report_anomaly(
        self,
        source_domain: str,
        metric: str,
        value: float,
        baseline_mean: float,
        baseline_std: float,
        detail: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """异常上报 → 3σ 点火判定 → 广播 + shadow 落盘。

        Returns:
            点燃时返回 envelope dict；未达阈值/关闭/异常时返回 None（FAIL-OPEN）。
        """
        if not self._enabled:
            return None
        try:
            if baseline_std <= 0:
                return None  # 无法计算 z → FAIL-OPEN 不广播
            z = (float(value) - float(baseline_mean)) / float(baseline_std)
        except (TypeError, ValueError):
            return None
        if abs(z) < self._ignite_z:
            return None  # 未达点火阈值：不广播（BIO 条件 #5a）

        envelope = {
            "event_id": f"EB-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}",
            "trace_id": f"emergence-shadow-{uuid.uuid4().hex[:16]}",
            "ts": datetime.now(timezone.utc).isoformat(),
            "source_domain": source_domain,
            "metric": metric,
            "value": float(value),
            "baseline_mean": float(baseline_mean),
            "baseline_std": float(baseline_std),
            "z_score": round(z, 4),
            "ignited": True,
            "detail": detail or {},
        }
        # GWT 广播（显式点燃；confidence 映射 z→[0.8, 0.99] 供下游参考）
        content = WorkspaceContent(
            intent={
                "type": "domain_anomaly",
                "source_domain": source_domain,
                "metric": metric,
                "z_score": round(z, 4),
            },
            confidence=min(0.99, 0.8 + abs(z) / 100),
            ignited=True,
            execution_result=envelope,
        )
        self._bus.ignite(content)
        self._persist(envelope)
        return envelope

    def _persist(self, envelope: Dict[str, Any]) -> None:
        """shadow envelope 落盘 bus_YYYYMMDD.jsonl。FAIL-OPEN。"""
        try:
            self._events_dir.mkdir(parents=True, exist_ok=True)
            day = datetime.now(timezone.utc).strftime("%Y%m%d")
            with (self._events_dir / f"bus_{day}.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(envelope, ensure_ascii=False) + "\n")
        except Exception as exc:  # noqa: BLE001
            logger.warning("emergence bus 落盘失败（降级不抛出）: %s", exc)

    def stats(self) -> Dict[str, Any]:
        s = self._bus.stats()
        s["enabled"] = self._enabled
        s["ignite_z"] = self._ignite_z
        return s
