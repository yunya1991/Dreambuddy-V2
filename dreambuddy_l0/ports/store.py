"""Store port：read / write / query / health（存储能力）。

方言能力集（操作符+类型映射）由 adapter 声明，禁止跨方言声明等价。
"""
from typing import Any, Dict, Optional, Protocol, runtime_checkable


@runtime_checkable
class StorePort(Protocol):
    def read(self, table: str, *, key: str, cursor: Optional[str] = None,
             limit: int = 100) -> Dict[str, Any]: ...
    def write(self, table: str, *, data: Dict[str, Any],
              idempotency_key: str = "") -> bool: ...
    def query(self, table: str, *, filters: Optional[Dict[str, Any]] = None,
              cursor: Optional[str] = None, limit: int = 100) -> Dict[str, Any]: ...
    def health(self) -> Dict[str, Any]: ...
