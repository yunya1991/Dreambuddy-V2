"""Collector port 内存 fake：collect/status。"""
from typing import Any, Dict, Optional


class FakeCollector:
    def __init__(self):
        self._runs: List[Dict[str, Any]] = []

    def collect(self, source: str, *, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        run = {"source": source, "params": params or {}, "ok": True, "count": 0}
        self._runs.append(run)
        return run

    def status(self, source: str = "") -> Dict[str, Any]:
        return {"runs": len(self._runs), "last": self._runs[-1] if self._runs else None}
