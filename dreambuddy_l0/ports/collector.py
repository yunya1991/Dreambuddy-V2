"""Collector port：collect / status（采集能力）。"""
from typing import Any, Dict, Optional, Protocol, runtime_checkable


@runtime_checkable
class CollectorPort(Protocol):
    def collect(self, source: str, *, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]: ...
    def status(self, source: str = "") -> Dict[str, Any]: ...
