"""六 port Protocol 定义（SPEC-C C2）：Memory/Collector/Search/Store/Analysis/Event。

每 port 方法数 ≤7，签名不出现 Connection/row/SQL，带四类语义
（事务边界/分页/身份权限/错误枚举）。
"""
from .memory import MemoryPort
from .collector import CollectorPort
from .search import SearchPort
from .store import StorePort
from .analysis import AnalysisPort
from .event import EventPort

__all__ = ["MemoryPort", "CollectorPort", "SearchPort", "StorePort", "AnalysisPort", "EventPort"]
