"""Analysis port：analyze / report（REA 逆向解析能力）。"""
from typing import Any, Dict, Optional, Protocol, runtime_checkable


@runtime_checkable
class AnalysisPort(Protocol):
    def analyze(self, target: str, *, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]: ...
    def report(self, analysis_id: str, *, format: str = "json") -> Dict[str, Any]: ...
