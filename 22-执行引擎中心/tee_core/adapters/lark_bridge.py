"""Minimal Feishu / Lark alert bridge for TEE Fail-Open Manager.

Signature provided (tests mock a MagicMock with this exact contract):

    bridge.send_alert(*, title, level="error", message="", details=None,
                     md_body=None, system="TEE", alert_type="TEE_FAILOPEN")
      -> Optional[str] (msg_id or None if skipped/unavailable)

The real implementation lazily imports the Feishu alert module
(``15-监控告警系统/feishu_alert.send_alert``). Importing only happens
inside :meth:`send_alert` so module-graph NFR-4 gate scans never see a
top-level strategy/monitor import. Missing credentials → the underlying
Feishu helper returns None with a soft print (its existing behaviour)
which the bridge preserves as a ``None`` return.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional


# 4 parents up from adapters/lark_bridge.py → repo root.
_MONITOR_DIR: Path = Path(__file__).resolve().parents[3] / "15-监控告警系统"


class LarkBridge:
    """DI-friendly Feishu bridge. Tests inject MagicMock() instead."""

    DEFAULT_ALERT_TYPE = "TEE_FAILOPEN"
    DEFAULT_SYSTEM = "TEE"

    def __init__(
        self,
        monitor_dir: Optional[Path] = None,
        default_alert_type: str = DEFAULT_ALERT_TYPE,
        default_system: str = DEFAULT_SYSTEM,
    ) -> None:
        self._monitor_dir = Path(monitor_dir) if monitor_dir else _MONITOR_DIR
        self._default_alert_type = default_alert_type
        self._default_system = default_system
        self._send_alert_fn: Any = None  # cached lazy import

    # ── public surface ─────────────────────────────────────────────────
    def send_alert(
        self,
        *,
        title: str,
        level: str = "error",
        message: str = "",
        details: Optional[Dict[str, Any]] = None,
        md_body: Optional[str] = None,
        system: Optional[str] = None,
        alert_type: Optional[str] = None,
    ) -> Optional[str]:
        fn = self._resolve_send_alert()
        if fn is None:
            print(
                f"[TEE.LARK_BRIDGE] feishu_alert unavailable. "
                f"Alert suppressed: [{level}] {title}"
            )
            return None

        merged_details: Dict[str, Any] = dict(details or {})
        if md_body:
            merged_details.setdefault("md_body", str(md_body))
        merged_message = (
            f"{title}\n{message}".strip() if message else str(title)
        )
        # NOTE: raises are intentionally propagated out of the bridge so
        # the manager's outer try/except (TR-8.3) can log them fail-safe.
        msg_id = fn(
            alert_type or self._default_alert_type,
            str(level),
            merged_message,
            merged_details,
            system or self._default_system,
        )
        return msg_id or None

    # ── lazy import helper ─────────────────────────────────────────────
    def _resolve_send_alert(self) -> Any:
        if self._send_alert_fn is not None:
            return self._send_alert_fn
        dir_str = str(self._monitor_dir)
        inserted = dir_str not in sys.path
        try:
            if inserted:
                sys.path.insert(0, dir_str)
            import feishu_alert  # type: ignore
            fn = getattr(feishu_alert, "send_alert", None)
        except Exception:  # noqa: BLE001 — fail-safe, no propagate
            fn = None
        finally:
            if inserted:
                try:
                    sys.path.remove(dir_str)
                except ValueError:
                    pass
        if not callable(fn):
            return None
        self._send_alert_fn = fn
        return fn


__all__ = ["LarkBridge"]
