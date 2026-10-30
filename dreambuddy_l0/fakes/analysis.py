"""Analysis port 内存 fake：analyze/report。"""
from typing import Any, Dict, Optional


class FakeAnalysis:
    def __init__(self):
        self._results: Dict[str, Dict[str, Any]] = {}

    def analyze(self, target: str, *, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        aid = f"AN-{len(self._results)}"
        self._results[aid] = {"target": target, "params": params or {}, "evidence_count": 0}
        return {"analysis_id": aid}

    def report(self, analysis_id: str, *, format: str = "json") -> Dict[str, Any]:
        r = self._results.get(analysis_id)
        return r if r else {"error_code": "not_found"}
